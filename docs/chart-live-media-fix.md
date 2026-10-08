# Live chart prices and picture delivery

This fixes two deployment-visible gaps: charts refreshed candles every thirty
seconds, and chart image results were internal model previews with no attachment
path. It does not enable trading, change MetaApi, or add a runtime/browser/UI page.

## Implemented changes

- `nanobot/market/oanda.py`: protected practice/live pricing streaming,
  bounded NDJSON parsing, heartbeat handling, Decimal quotes, sanitized errors,
  no redirects and no minimum-byte buffering that would delay small ticks.
- `nanobot/market/streaming.py`: one active account stream shared by chart
  consumers, atomic subscription changes, one queued latest update per consumer,
  stale/duplicate rejection, bounded reconnect delay and idle/shutdown cleanup.
- `nanobot/webui/chart_stream.py` and existing command routing: authenticated
  connection-owned subscriptions, repeated scope/configuration checks, immediate
  quotes, asynchronous bounded REST history restoration and completed-candle
  reconciliation, provisional mid-price candles and New York/DST boundaries.
- Existing frontend socket/client/datafeed: incremental updates, source timestamps,
  bid/ask/freshness labels, reconnect/visibility cleanup, optional capability
  negotiation and no chart remount or model call on a price update.
- `chart_snapshot(format="attachment")`: exports a real PNG using existing
  media artifacts. `message(media=[artifact_path])` delivers it through existing
  chat/channels, without a vision model or image-generation connection.
- The chart-only rasterizer bundles licensed DejaVu Sans; normal Pillow wheels
  supply RAQM for Arabic shaping/bidi. The Arabic fixture image was also visually
  inspected. No system fonts, browser or OS screenshots are required.

## Verification

- Baseline: 92 Python passes / two optional provider skips; six frontend passes.
- Final Python chart/market/security/isolation/media/WebSocket regression:
  **684 passed, two optional provider tests skipped**.
- Trading plus final chart-stream/provider-stream recheck: **81 passed**.
  This overlaps the preceding suite; counts are not summed as unique tests.
- Relevant frontend chart, feed, API and client tests: **162 passed**.
- Full BasedPyright: **zero errors/warnings**. Changed Python modules were
  checked again after hardening. Full repository Ruff and WebUI ESLint passed.
- TypeScript/Vite production build and Git whitespace checks passed.
- Hatch package selection includes the bundled font and its license.

An intermediate simultaneous run hit existing three-second native-indicator
timeouts and a frontend hook timeout under load. Sequential chart tests passed
without modifying timeouts, assertions or isolation. New test setup/cleanup
errors were corrected and the affected complete frontend suite rerun.

Deterministic tests cover a price arriving while a REST request is blocked,
small open-stream frames, malformed/oversized/provider errors and redaction,
concurrent consumers, duplicate/old quotes, authorization and binding changes,
reconnect/cleanup, non-vision PNG attachment delivery, Arabic rendering, and
current/older-host compatibility. They do not place trades.

## Deployment and limits

Cursor should update and rebuild/reinstall **only** `kili-trading.service`'s
installation from this repository, preserving its configuration/runtime data.
Allow its selected OANDA streaming origin in addition to the REST origin:
`stream-fxpractice.oanda.com` or `stream-fxtrade.oanda.com`. Restart only this
service and reload its WebUI. Do not touch the other Nanobot deployment.
Keep delegated live trading disabled and perform only read/chart/media checks.

Real-provider streaming latency and VPS delivery are pending deployment
verification; local verification used deterministic providers, not production
credentials. OANDA pricing is sampled, up to four updates/second/instrument,
and cannot promise every broker tick or zero network delay. Forming candles
are provisional and streamed volume is unavailable; completed/history values
come from REST. Durable market watchers retain their own configured cadence.
Saved historical views do not jump to the latest bar. Raster exports use the
selected cached scene and retain the existing complex-overlay approximation;
they are not pixel-identical KLineChart Pro screenshots. Custom-built Pillow
installations require RAQM for connected Arabic/RTL text.
