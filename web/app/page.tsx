"use client";

import {
  BarVisualizer,
  LiveKitRoom,
  RoomAudioRenderer,
  useRoomContext,
  useVoiceAssistant,
} from "@livekit/components-react";
import { RoomEvent } from "livekit-client";
import { useCallback, useEffect, useRef, useState } from "react";

type Status = "idle" | "connecting" | "live" | "ended" | "error";
type TranscriptLine = { id: string; speaker: "AGENT" | "YOU"; text: string; time: string };
type Details = Record<string, string | number | boolean | undefined>;
type Credentials = { serverUrl: string; token: string; roomName: string };

const detailLabels = [
  ["name", "Name"],
  ["phone", "Phone"],
  ["area", "Area"],
  ["bhk", "Bedrooms"],
  ["budget", "Budget"],
  ["timeline", "Timeline"],
  ["purpose", "Purpose"],
  ["project", "Project"],
  ["site_visit", "Site visit"],
] as const;

export default function Home() {
  const [status, setStatus] = useState<Status>("idle");
  const [credentials, setCredentials] = useState<Credentials | null>(null);
  const [roomConnected, setRoomConnected] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");
  const [transcript, setTranscript] = useState<TranscriptLine[]>([]);
  const [details, setDetails] = useState<Details>({});

  const startCall = useCallback(async () => {
    setStatus("connecting");
    setRoomConnected(false);
    setErrorMessage("");
    setTranscript([]);
    setDetails({});
    try {
      const response = await fetch("/api/token", { method: "POST" });
      const body = await response.json();
      if (!response.ok) throw new Error(body.error || "Unable to prepare a call.");
      setCredentials(body as Credentials);
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "Unable to connect right now.");
      setStatus("error");
    }
  }, []);

  const endCall = useCallback(() => {
    setCredentials(null);
    setStatus("ended");
  }, []);

  const onConnected = useCallback(() => {
    setRoomConnected(true);
    console.info("room_connected", { roomName: credentials?.roomName });
  }, [credentials?.roomName]);
  const onAgentReady = useCallback(() => setStatus("live"), []);
  const onDisconnected = useCallback(() => {
    setRoomConnected(false);
    console.info("room_disconnected", { roomName: credentials?.roomName });
    setCredentials(null);
    setStatus((current) => (current === "error" ? current : "ended"));
  }, [credentials?.roomName]);
  const onError = useCallback((error: Error) => {
    console.error("room_connection_error", {
      errorName: error.name || "Error",
      stage: status,
      roomName: credentials?.roomName,
    });
    setCredentials(null);
    setErrorMessage(/permission|denied|device|microphone/i.test(error.message)
      ? "Microphone access was denied. Allow microphone access, then try again."
      : "The call could not connect. Check your connection and try again.");
    setStatus("error");
  }, [credentials?.roomName, status]);
  const onAgentFailure = useCallback((reason: "failed" | "timeout", agentState?: string) => {
    console.error("agent_connection_failed", {
      reason,
      agentState,
      roomName: credentials?.roomName,
    });
    setRoomConnected(false);
    setCredentials(null);
    setErrorMessage(reason === "timeout"
      ? "Aria did not join within twenty-five seconds. Check that the local agent is running, then try again."
      : "Aria could not join the room. Start a new call to try again.");
    setStatus("error");
  }, [credentials?.roomName]);

  useEffect(() => {
    if (!credentials || roomConnected) return;
    const timeout = window.setTimeout(() => {
      console.error("room_connection_timeout", { roomName: credentials.roomName });
      setCredentials(null);
      setErrorMessage("The room did not connect within twenty seconds. Check your connection and try again.");
      setStatus("error");
    }, 20_000);
    return () => window.clearTimeout(timeout);
  }, [credentials, roomConnected]);

  return (
    <main className="shell">
      <header className="topbar">
        <a className="wordmark" href="#" aria-label="PropVoice home">PropVoice</a>
        <div className={`connection ${status}`} aria-live="polite">
          <span className="status-dot" />
          <span>{status}</span>
        </div>
      </header>

      <div className="workspace">
        <section className="call-column" aria-label="Call controls">
          {credentials && (
            <LiveKitRoom
              serverUrl={credentials.serverUrl}
              token={credentials.token}
              connect
              audio
              video={false}
              onConnected={onConnected}
              onDisconnected={onDisconnected}
              onError={onError}
            >
              <RoomAudioRenderer />
              <CallSession
                connected={roomConnected}
                onEnd={endCall}
                onAgentFailure={onAgentFailure}
                onAgentReady={onAgentReady}
                onTranscript={(line) => setTranscript((current) => [...current, line])}
                onDetails={(fields) => setDetails((current) => ({ ...current, ...fields }))}
              />
            </LiveKitRoom>
          )}
          {status === "idle" && (
            <div className="call-prompt">
              <p className="eyebrow">SUNRISE REALTY · BENGALURU · CHENNAI</p>
              <h1>Find a place<br />to call home.</h1>
              <p className="intro">Talk through what you’re looking for. Aria can help you explore sample listings and arrange a visit.</p>
              <button className="primary-button" onClick={startCall}>Start call</button>
              <p className="privacy-note">Your microphone is used only during the call.</p>
            </div>
          )}
          {status === "connecting" && !credentials && (
            <div className="state-copy" aria-live="polite">
              <p className="eyebrow">CONNECTING</p><h1>Preparing your call</h1>
              <p>Allow microphone access when your browser asks.</p>
              <button className="text-button" onClick={endCall}>Cancel</button>
            </div>
          )}
          {status === "ended" && (
            <div className="state-copy">
              <p className="eyebrow">CALL ENDED</p><h1>That’s all for now.</h1>
              <p>Your transcript and captured details are still available here.</p>
              <button className="primary-button" onClick={startCall}>Start new call</button>
            </div>
          )}
          {status === "error" && (
            <div className="state-copy" role="alert">
              <p className="eyebrow">CALL NOT CONNECTED</p><h1>Let’s try again.</h1>
              <p>{errorMessage}</p>
              <button className="primary-button" onClick={startCall}>Try again</button>
            </div>
          )}
        </section>

        <aside className="record-column">
          <section className="transcript-section" aria-label="Transcript">
            <h2>Transcript</h2>
            {transcript.length ? <Transcript lines={transcript} /> : (
              <p className="empty-note">Conversation will appear here.</p>
            )}
          </section>
          <section className="details-section" aria-label="Captured details">
            <h2>Captured details</h2>
            <dl className="details-list">
              {detailLabels.map(([key, label]) => (
                <div className="detail-row" key={key}>
                  <dt>{label}</dt>
                  <dd key={`${key}-${details[key] ?? "empty"}`} className="detail-value">
                    {details[key] === undefined || details[key] === ""
                      ? "—"
                      : key === "site_visit" && details[key] === true
                        ? "Requested"
                        : String(details[key])}
                    {key === "budget" && details[key] !== undefined ? " lakhs" : ""}
                  </dd>
                </div>
              ))}
            </dl>
          </section>
        </aside>
      </div>

      <footer>Demo with sample listings. Calls are not recorded.</footer>
    </main>
  );
}

function CallSession({
  onEnd,
  connected,
  onAgentFailure,
  onAgentReady,
  onTranscript,
  onDetails,
}: {
  onEnd: () => void;
  connected: boolean;
  onAgentFailure: (reason: "failed" | "timeout", agentState?: string) => void;
  onAgentReady: () => void;
  onTranscript: (line: TranscriptLine) => void;
  onDetails: (fields: Details) => void;
}) {
  const room = useRoomContext();
  const agent = useVoiceAssistant();
  const [muted, setMuted] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const agentReady = ["idle", "listening", "thinking", "speaking"].includes(agent.state);

  useEffect(() => {
    const timer = window.setInterval(() => setElapsed((value) => value + 1), 1000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    const onTranscription = (segments: Array<{ id?: string; text: string; final?: boolean }>, participant?: { identity: string; isLocal?: boolean }) => {
      for (const segment of segments) {
        if (!segment.final || !segment.text.trim()) continue;
        onTranscript({
          id: segment.id ?? `${Date.now()}-${Math.random()}`,
          speaker: participant?.isLocal ? "YOU" : "AGENT",
          text: segment.text.trim(),
          time: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
        });
      }
    };
    const onData = (payload: Uint8Array) => {
      try {
        const message = JSON.parse(new TextDecoder().decode(payload)) as { type?: string; fields?: Details };
        if (message.type === "lead_update" && message.fields) onDetails(message.fields);
      } catch {
        // Ignore data messages that are not PropVoice detail updates.
      }
    };
    room.on(RoomEvent.TranscriptionReceived, onTranscription);
    room.on(RoomEvent.DataReceived, onData);
    return () => {
      room.off(RoomEvent.TranscriptionReceived, onTranscription);
      room.off(RoomEvent.DataReceived, onData);
    };
  }, [onDetails, onTranscript, room]);

  useEffect(() => {
    if (agent.state === "failed") onAgentFailure("failed", agent.state);
  }, [agent.state, onAgentFailure]);

  useEffect(() => {
    if (!connected || !agentReady) return;
    onAgentReady();
    console.info("agent_ready", { state: agent.state });
  }, [agent.state, agentReady, connected, onAgentReady]);

  useEffect(() => {
    if (!connected || agentReady || agent.state === "failed") return;
    const timeout = window.setTimeout(() => onAgentFailure("timeout", agent.state), 25_000);
    return () => window.clearTimeout(timeout);
  }, [agent.state, agentReady, connected, onAgentFailure]);

  const toggleMute = async () => {
    const next = !muted;
    await room.localParticipant.setMicrophoneEnabled(!next);
    setMuted(next);
  };
  const minutes = String(Math.floor(elapsed / 60)).padStart(2, "0");
  const seconds = String(elapsed % 60).padStart(2, "0");
  const speaking = agent.state === "speaking";
  const agentMessage = agent.state === "failed"
    ? "Aria could not join"
    : agent.state === "disconnected"
      ? "Waiting for Aria"
      : !connected || agent.state === "connecting" || agent.state === "initializing"
        ? "Connecting to Aria"
        : speaking
          ? "Aria is speaking"
          : "Listening";

  return (
    <div className="live-surface">
      <p className="eyebrow">SUNRISE REALTY · BENGALURU · CHENNAI</p>
      <h1>{agentMessage}</h1>
      <div className={`visualizer ${!connected ? "visualizer-off" : ""}`} aria-label={speaking ? "Agent audio level" : "Audio level"}>
        <BarVisualizer trackRef={agent.audioTrack} state={agent.state} barCount={48} options={{ minHeight: 1, maxHeight: 22 }} />
      </div>
      <p className="timer">{minutes}:{seconds}</p>
      <div className="call-actions">
        <button className="text-button" onClick={toggleMute}>{muted ? "Unmute" : "Mute"}</button>
        <button className="text-button end-button" onClick={onEnd}>End call</button>
      </div>
      <span className="sr-only">{speaking ? "Aria is speaking" : agentMessage}</span>
    </div>
  );
}

function Transcript({ lines }: { lines: TranscriptLine[] }) {
  const listRef = useRef<HTMLDivElement>(null);
  const shouldStick = useRef(true);
  const [hasNew, setHasNew] = useState(false);

  useEffect(() => {
    if (shouldStick.current && listRef.current) {
      listRef.current.scrollTop = listRef.current.scrollHeight;
      setHasNew(false);
    } else setHasNew(true);
  }, [lines]);

  return (
    <>
      <div
        className="transcript-list"
        ref={listRef}
        onScroll={(event) => {
          const element = event.currentTarget;
          shouldStick.current = element.scrollHeight - element.scrollTop - element.clientHeight < 32;
          if (shouldStick.current) setHasNew(false);
        }}
      >
        {lines.map((line) => (
          <article className="transcript-line" key={line.id}>
            <div className="line-meta"><span>{line.speaker}</span><time>{line.time}</time></div>
            <p>{line.text}</p>
          </article>
        ))}
      </div>
      {hasNew && <button className="new-lines" onClick={() => {
        if (listRef.current) listRef.current.scrollTop = listRef.current.scrollHeight;
        shouldStick.current = true;
        setHasNew(false);
      }}>Latest</button>}
    </>
  );
}
