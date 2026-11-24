# PropVoice web demo

A restrained browser client for the Sunrise Realty voice agent. It connects to `src/agent.py`, shows the live transcript, and updates captured requirements as the agent collects them.

## Requirements and setup

Use Node.js 20 or later and npm. From this directory:

```console
npm install
Copy-Item .env.example .env.local
```

Set these values in `web/.env.local`:

```dotenv
LIVEKIT_URL=
LIVEKIT_API_KEY=
LIVEKIT_API_SECRET=
```

The API route signs a short-lived participant token on the server. These credentials are never sent to the browser. Because `src/agent.py` registers `agent_name="my-agent"`, the token explicitly dispatches that agent to a unique room.

## Run both processes

In the repository root, start the agent:

```console
uv run python src/agent.py dev
```

In a second terminal, start the web app:

```console
cd web
npm run dev
```

Open `http://localhost:3000`, allow microphone access, and select **Start call**. Calls use sample listings and are not recorded by this demo UI. LiveKit project observability settings may independently retain session data; configure those settings to match your intended privacy behavior.

## Quality checks

```console
npm run lint
npm run typecheck
npm run build
```

The frontend uses LiveKit React components for room audio and the audio level visualizer, and `livekit-client` room events for transcript and captured-detail updates. The server-only token route uses `livekit-server-sdk` and `@livekit/protocol` to set room agent dispatch.
