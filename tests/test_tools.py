import asyncio
import json
import threading

import pytest

import tools


class FakeSheet:
    def __init__(self):
        self.rows = []

    def get_all_values(self):
        return self.rows

    def append_row(self, row):
        self.rows.append(row)


class FakeBook:
    def __init__(self, sheet):
        self.sheet1 = sheet


class FakeClient:
    def __init__(self, sheet):
        self.sheet = sheet

    def open_by_key(self, sheet_id):
        assert sheet_id == "test-sheet-id"
        return FakeBook(self.sheet)

    def open(self, sheet_name):
        assert sheet_name == "Test CRM"
        return FakeBook(self.sheet)


@pytest.fixture
def sheets(monkeypatch):
    sheet = FakeSheet()
    monkeypatch.setenv("GOOGLE_SHEET_ID", "test-sheet-id")
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_FILE", "fake.json")
    monkeypatch.setattr(
        tools.gspread, "service_account", lambda filename: FakeClient(sheet)
    )
    tools._get_sheets_client.cache_clear()
    tools._get_sheets_worksheet.cache_clear()
    return sheet


@pytest.mark.asyncio
async def test_search_properties_filters_listings():
    result = await tools.search_properties(None, area="Whitefield", bhk=2)
    assert result["count"] == 1
    assert result["listings"][0]["id"] == "SR001"


@pytest.mark.asyncio
async def test_lead_update_publishes_only_allowed_details():
    published = []

    class Participant:
        async def publish_data(self, data, **kwargs):
            published.append((json.loads(data), kwargs))

    class Session:
        room = type("Room", (), {"local_participant": Participant()})()

    class Context:
        session = Session()

    await tools._publish_lead_update(
        Context(), {"area": "Hebbal", "budget": 150, "secret": "never send"}
    )
    assert published == [
        (
            {"type": "lead_update", "fields": {"area": "Hebbal", "budget": 150}},
            {"reliable": True, "topic": "lead_update"},
        )
    ]


@pytest.mark.asyncio
async def test_sheets_save_lead(sheets):
    await tools.save_lead(None, "A", "+919999999999")
    assert sheets.rows[0][0] == "created_at"
    assert sheets.rows[1][2:4] == ["A", "+919999999999"]
    assert len(sheets.rows) == 2  # one header and exactly one lead row


@pytest.mark.asyncio
async def test_sheets_write_runs_off_event_loop(monkeypatch):
    event_loop_thread = threading.get_ident()
    worker_threads = []

    def blocking_write(lead):
        worker_threads.append(threading.get_ident())

    monkeypatch.setattr(tools, "_save_to_sheets", blocking_write)
    result = await tools.book_site_visit(
        None, "SR001", "A", "+919999999999", preferred_time="Saturday morning"
    )
    assert result["success"]
    assert worker_threads and worker_threads[0] != event_loop_thread


@pytest.mark.asyncio
async def test_site_visit_writes_once(sheets, monkeypatch):
    writes = []

    def write_once(request):
        writes.append(request)

    monkeypatch.setattr(tools, "_save_to_sheets", write_once)
    result = await tools.book_site_visit(
        None, "SR001", "A", "+919999999999", preferred_time="Saturday morning"
    )
    assert result["success"] and not result.get("fallback")
    assert len(writes) == 1
    assert writes[0]["type"] == "site_visit"
    assert writes[0]["preferred_time"] == "Saturday morning"


@pytest.mark.asyncio
async def test_site_visit_falls_back_after_sheets_failure(monkeypatch, tmp_path):
    fallback = tmp_path / "leads_fallback.jsonl"
    monkeypatch.setattr(tools, "FALLBACK_FILE", fallback)
    monkeypatch.setattr(
        tools,
        "_save_to_sheets",
        lambda request: (_ for _ in ()).throw(OSError("offline")),
    )
    result = await tools.book_site_visit(
        None, "SR001", "A", "+919999999999", preferred_time="Saturday morning"
    )
    assert result["success"] and result["fallback"]
    saved = json.loads(fallback.read_text())
    assert saved["type"] == "site_visit"
    assert saved["preferred_time"] == "Saturday morning"


@pytest.mark.asyncio
async def test_site_visit_rejects_missing_preferred_time(monkeypatch):
    writes = []
    monkeypatch.setattr(tools, "_save_to_sheets", writes.append)
    result = await tools.book_site_visit(None, "SR001", "A", "+919999999999")
    assert "prefer" in result["error"]
    assert writes == []


@pytest.mark.asyncio
async def test_site_visit_rejects_invalid_phone_and_project(monkeypatch):
    writes = []
    monkeypatch.setattr(tools, "_save_to_sheets", writes.append)
    bad_phone = await tools.book_site_visit(
        None, "SR001", "A", "123", preferred_time="Saturday morning"
    )
    bad_project = await tools.book_site_visit(
        None, "SR999", "A", "+919999999999", preferred_time="Saturday morning"
    )
    assert "valid phone" in bad_phone["error"]
    assert "not in the current listings" in bad_project["error"]
    assert writes == []


def test_sheets_client_is_cached(sheets, monkeypatch):
    calls = []
    original = tools.gspread.service_account

    def create_client(filename):
        calls.append(filename)
        return original(filename)

    monkeypatch.setattr(tools.gspread, "service_account", create_client)
    tools._get_sheets_client.cache_clear()
    assert tools._get_sheets_client("fake.json") is tools._get_sheets_client(
        "fake.json"
    )
    assert calls == ["fake.json"]


@pytest.mark.asyncio
async def test_sheets_write_supports_existing_sheet_name_config(sheets, monkeypatch):
    monkeypatch.setenv("GOOGLE_SHEET_ID", "")
    monkeypatch.setenv("GOOGLE_SHEET_NAME", "Test CRM")
    tools._get_sheets_client.cache_clear()
    tools._get_sheets_worksheet.cache_clear()
    await asyncio.to_thread(
        tools._save_to_sheets,
        {"type": "site_visit", "name": "A", "phone": "+919999999999"},
    )
    assert sheets.rows[-1][2:4] == ["A", "+919999999999"]


@pytest.mark.asyncio
async def test_save_lead_falls_back_when_sheets_fail(monkeypatch, tmp_path):
    fallback = tmp_path / "leads.jsonl"
    monkeypatch.setattr(tools, "FALLBACK_FILE", fallback)
    monkeypatch.setattr(
        tools, "_save_to_sheets", lambda lead: (_ for _ in ()).throw(OSError("offline"))
    )
    result = await tools.save_lead(None, "A", "+919999999999")
    assert result["success"] and result["fallback"]
    assert json.loads(fallback.read_text())["name"] == "A"


@pytest.mark.asyncio
async def test_visit_validates_listing_and_phone():
    assert "error" in await tools.book_site_visit(None, "unknown", "A", "+919999999999")
    assert "error" in await tools.book_site_visit(None, "SR001", "A", "123")


@pytest.mark.asyncio
async def test_handoff_logs_callback(monkeypatch, tmp_path):
    handoffs = tmp_path / "handoffs.jsonl"
    monkeypatch.setattr(tools, "HANDOFF_FILE", handoffs)
    result = await tools.handoff_to_human(None, "caller upset", "A", "+919999999999")
    assert result["success"]
    assert json.loads(handoffs.read_text())["reason"] == "caller upset"
