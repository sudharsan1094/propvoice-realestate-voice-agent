# Failure log

| Scenario | What went wrong | Fix | Result |
|---|---|---|---|
| booking mid-call | A site-visit booking triggered a roughly four-second synchronous gspread call on the event loop, causing an audio stall (reported in the LiveKit warning). | Run the gspread write with `await asyncio.to_thread(...)`, reuse a cached client, and open the configured sheet by ID. | The code path is updated and covered by an off-event-loop unit test. The audio stall has not been measured in console mode yet; verify that the warning no longer appears during a booking. |
