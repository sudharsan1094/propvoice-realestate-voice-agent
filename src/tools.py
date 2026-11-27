"""Small, side-effect-aware tools used by Aria."""

import json
import logging
import os
import re
from asyncio import to_thread
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace

from dotenv import load_dotenv
from livekit.agents import RunContext, function_tool

logger = logging.getLogger("propvoice.tools")
try:
    import gspread
except ImportError:
    gspread = SimpleNamespace(service_account=None)
ROOT = Path(__file__).resolve().parent.parent
LISTINGS_FILE = ROOT / "data" / "listings.json"
FALLBACK_FILE = ROOT / "data" / "leads_fallback.jsonl"
HANDOFF_FILE = ROOT / "data" / "handoffs.jsonl"
LEAD_FIELDS = {
    "name",
    "phone",
    "budget",
    "area",
    "bhk",
    "timeline",
    "purpose",
    "project",
    "site_visit",
}


async def _publish_lead_update(context: RunContext, fields: dict) -> None:
    """Send only approved, non-empty caller details to the connected frontend."""
    safe_fields = {
        key: value
        for key, value in fields.items()
        if key in LEAD_FIELDS and value is not None and value != ""
    }
    if not safe_fields:
        return
    try:
        await context.session.room.local_participant.publish_data(
            json.dumps({"type": "lead_update", "fields": safe_fields}),
            reliable=True,
            topic="lead_update",
        )
    except Exception as exc:
        logger.exception(
            "lead_update_publish_failed", extra={"error_type": type(exc).__name__}
        )


def _append_jsonl(path: Path, item: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(item, ensure_ascii=False) + "\n")


def _valid_phone(phone: str) -> bool:
    if not isinstance(phone, str):
        return False
    digits = re.sub(r"\D", "", phone)
    return 10 <= len(digits) <= 15


def _listings() -> list[dict]:
    with LISTINGS_FILE.open(encoding="utf-8") as handle:
        return json.load(handle)


@function_tool
async def search_properties(
    context: RunContext,
    area: str = "",
    bhk: int | None = None,
    max_budget_lakhs: int | None = None,
) -> dict:
    """Find listed homes matching area, BHK, and maximum price in lakhs."""
    try:
        results = _listings()
        if area:
            query = area.casefold()
            results = [
                p
                for p in results
                if query in p["area"].casefold()
                or query in p.get("city", "").casefold()
            ]
        if bhk is not None:
            results = [p for p in results if p["bhk"] == bhk]
        if max_budget_lakhs is not None:
            results = [p for p in results if p["price_lakhs"] <= max_budget_lakhs]
        await _publish_lead_update(
            context,
            {"area": area, "bhk": bhk, "budget": max_budget_lakhs},
        )
        return {"listings": results, "count": len(results)}
    except (OSError, ValueError, KeyError) as exc:
        logger.exception(
            "listing_search_failed", extra={"error_type": type(exc).__name__}
        )
        return {"error": "Property search is temporarily unavailable."}


@function_tool
async def book_site_visit(
    context: RunContext,
    project_id: str,
    name: str,
    phone: str,
    preferred_time: str = "",
) -> dict:
    """Record one site-visit request for a known listing and valid contact details."""
    project_id = project_id.strip() if isinstance(project_id, str) else ""
    preferred_time = preferred_time.strip() if isinstance(preferred_time, str) else ""
    if not project_id:
        return {"error": "Please tell me which listed project you want to visit."}
    if not preferred_time:
        return {"error": "What day or time would you prefer for the site visit?"}
    if not _valid_phone(phone):
        return {"error": "Please provide a valid phone number."}
    if not isinstance(name, str) or not name.strip():
        return {"error": "Please provide your name for the site-visit request."}

    try:
        listing = next((p for p in _listings() if p["id"] == project_id), None)
    except Exception as exc:  # tool errors are returned safely to the agent
        logger.exception(
            "site_visit_listing_lookup_failed", extra={"error_type": type(exc).__name__}
        )
        return {
            "error": "I couldn't check that project right now. Please try again later."
        }
    if listing is None:
        return {"error": "That project is not in the current listings."}

    request = {
        "type": "site_visit",
        "project_id": project_id,
        "project": listing["project"],
        "name": name.strip(),
        "phone": phone.strip(),
        "preferred_time": preferred_time,
        "notes": f"Preferred site visit time: {preferred_time}",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        # Keep booking as one independent CRM write; it does not call save_lead().
        await to_thread(_save_to_sheets, request)
    except Exception as exc:
        logger.exception(
            "site_visit_sheets_write_failed_using_fallback",
            extra={"error_type": type(exc).__name__},
        )
        try:
            await to_thread(_append_jsonl, FALLBACK_FILE, request)
        except OSError as fallback_exc:
            logger.exception(
                "site_visit_fallback_failed",
                extra={"error_type": type(fallback_exc).__name__},
            )
            return {
                "error": "I couldn't save that visit request. Please try again later."
            }
        await _publish_lead_update(
            context,
            {
                "name": name.strip(),
                "phone": phone.strip(),
                "project": listing["project"],
                "site_visit": True,
                "timeline": preferred_time,
            },
        )
        return {
            "success": True,
            "fallback": True,
            "message": "The site-visit request was saved for follow-up.",
        }

    await _publish_lead_update(
        context,
        {
            "name": name.strip(),
            "phone": phone.strip(),
            "project": listing["project"],
            "site_visit": True,
            "timeline": preferred_time,
        },
    )
    logger.info("site_visit_recorded", extra={"project_id": project_id})
    return {"success": True, "message": "Site visit request recorded."}


@lru_cache(maxsize=1)
def _get_sheets_client(key_file: str):
    if gspread.service_account is None:
        raise RuntimeError("gspread is not installed")
    return gspread.service_account(filename=key_file)


@lru_cache(maxsize=4)
def _get_sheets_worksheet(key_file: str, sheet_id: str, sheet_name: str):
    """Cache the worksheet; prefer ID lookup and support the existing name config."""
    client = _get_sheets_client(key_file)
    if sheet_id:
        return client.open_by_key(sheet_id).sheet1
    return client.open(sheet_name).sheet1


def _save_to_sheets(lead: dict) -> None:
    load_dotenv(ROOT / ".env.local")
    key_file = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "")
    sheet_id = os.getenv("GOOGLE_SHEET_ID", "")
    sheet_name = os.getenv("GOOGLE_SHEET_NAME", "")
    if not key_file or not (sheet_id or sheet_name):
        raise RuntimeError("Sheets configuration is missing")
    if not sheet_id:
        logger.warning("using_legacy_google_sheet_name_config")
    sheet = _get_sheets_worksheet(key_file, sheet_id, sheet_name)
    if not sheet.get_all_values():
        sheet.append_row(
            [
                "created_at",
                "type",
                "name",
                "phone",
                "area",
                "bhk",
                "budget_lakhs",
                "project_id",
                "notes",
            ]
        )
    sheet.append_row(
        [
            lead.get("created_at", ""),
            lead.get("type", "lead"),
            lead.get("name", ""),
            lead.get("phone", ""),
            lead.get("area", ""),
            lead.get("bhk", ""),
            lead.get("budget_lakhs", ""),
            lead.get("project_id", ""),
            lead.get("notes", ""),
        ]
    )


@function_tool
async def save_lead(
    context: RunContext,
    name: str,
    phone: str,
    area: str = "",
    bhk: int | None = None,
    budget_lakhs: int | None = None,
    notes: str = "",
) -> dict:
    """Save a caller's consented property requirements to Sunrise Realty's CRM."""
    if not _valid_phone(phone):
        return {"error": "Please provide a valid phone number before I save this."}
    lead = {
        "type": "lead",
        "name": name.strip(),
        "phone": phone.strip(),
        "area": area,
        "bhk": bhk,
        "budget_lakhs": budget_lakhs,
        "notes": notes,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        await to_thread(_save_to_sheets, lead)
    except Exception as exc:
        logger.exception(
            "sheets_lead_write_failed_using_fallback",
            extra={"error_type": type(exc).__name__},
        )
        try:
            await to_thread(_append_jsonl, FALLBACK_FILE, lead)
        except OSError as fallback_exc:
            logger.exception(
                "lead_fallback_failed",
                extra={"error_type": type(fallback_exc).__name__},
            )
            return {"error": "I couldn't save your details. Please try again later."}
        fallback = True
    else:
        fallback = False

    await _publish_lead_update(
        context,
        {
            "name": name.strip(),
            "phone": phone.strip(),
            "area": area,
            "bhk": bhk,
            "budget": budget_lakhs,
        },
    )
    if fallback:
        return {
            "success": True,
            "fallback": True,
            "message": "Lead saved locally for follow-up.",
        }
    logger.info("lead_saved")
    return {"success": True, "message": "Lead saved to the CRM."}


@function_tool
async def handoff_to_human(
    context: RunContext, reason: str, name: str = "", phone: str = ""
) -> dict:
    """Log a human callback request; this does not transfer the live call."""
    if phone and not _valid_phone(phone):
        return {"error": "Please provide a valid phone number for a callback."}
    try:
        _append_jsonl(
            HANDOFF_FILE,
            {
                "reason": reason,
                "name": name.strip(),
                "phone": phone.strip(),
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        await _publish_lead_update(
            context, {"name": name.strip(), "phone": phone.strip()}
        )
        logger.info("callback_request_logged")
        return {"success": True, "message": "A human callback request has been logged."}
    except OSError as exc:
        logger.exception(
            "callback_request_failed", extra={"error_type": type(exc).__name__}
        )
        return {"error": "I couldn't log the callback request. Please try again later."}
