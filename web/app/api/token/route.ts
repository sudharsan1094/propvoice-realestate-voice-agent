import { randomUUID } from "node:crypto";
import { RoomAgentDispatch, RoomConfiguration } from "@livekit/protocol";
import { AccessToken } from "livekit-server-sdk";
import { NextResponse } from "next/server";

export const runtime = "nodejs";

export async function POST() {
  const serverUrl = process.env.LIVEKIT_URL;
  const apiKey = process.env.LIVEKIT_API_KEY;
  const apiSecret = process.env.LIVEKIT_API_SECRET;

  if (!serverUrl || !apiKey || !apiSecret) {
    return NextResponse.json(
      { error: "LiveKit server credentials are not configured." },
      { status: 500 },
    );
  }

  const roomName = `propvoice-${randomUUID()}`;
  const at = new AccessToken(apiKey, apiSecret, {
    identity: `caller-${randomUUID()}`,
    name: "Caller",
    ttl: "10m",
  });
  at.addGrant({
    roomJoin: true,
    room: roomName,
    canPublish: true,
    canSubscribe: true,
    canPublishData: true,
  });
  at.roomConfig = new RoomConfiguration({
    agents: [new RoomAgentDispatch({ agentName: "my-agent", deployment: "local" })],
  });

  let token: string;
  try {
    token = await at.toJwt();
  } catch (error) {
    console.error("token_issue_failed", {
      errorName: error instanceof Error ? error.name : "UnknownError",
    });
    return NextResponse.json({ error: "Unable to prepare a call." }, { status: 500 });
  }
  console.info("token_issued", { roomName, agentName: "my-agent", deployment: "local" });
  return NextResponse.json({ serverUrl, token, roomName }, { status: 201 });
}
