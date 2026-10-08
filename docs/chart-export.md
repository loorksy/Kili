# Native KLineChart image export

Interactive charts and `chart_snapshot` PNGs use the same pinned KLineChart Pro
0.1.1 / KLineChart 9.8.12 adapter. Backend scene candles, viewport, annotations
and calculated indicator series are the export inputs. Export never executes
model/user JavaScript or captures a desktop, Settings or conversation screenshot.

## Deployment

Install the project dependencies (including Playwright 1.63.0) in the service
virtualenv and install an operator-maintained system `chromium` or
`chromium-browser`. The service needs permission to launch the ephemeral chart
renderer and enough RAM for Chromium. No Playwright browser download, persistent
profile, display/VNC server or browsing tool is needed.

The release includes `nanobot/charts/assets/chart-renderer.{js,css}` and their
SHA-256 files, plus the licensed font. To reproduce after changing the adapter:

```sh
cd webui
npm ci
npm run build:chart-renderer
```

This separate production IIFE build uses the same hash-guarded library deltas
as the normal WebUI. It does not edit node_modules. Package assets ship in the
Python wheel; normal frontend builds do not regenerate this export bundle.

## Boundaries and limitations

Only the trusted fixed local document is rendered. HTTP and WebSocket routing
are denied, DNS is disabled, service workers/downloads are disabled, and the
child inherits only PATH and platform process essentials. Credentials, runtime
paths and provider datafeed URLs are not inputs. Bundle hashes must match.
Labels are data, never HTML/script source. PNG dimensions and JSON input/output
are bounded; a 45-second parent deadline terminates failed rendering.

The image uses the library's core picture export with a concise chart header.
Transient client hover/cursor state and user screen geometry are not exported.
Image bytes are reproducible on the same pinned rendering environment; different
Chromium/OS versions may rasterize fonts differently. This is not a general
browser sandbox for running uploaded code. The renderer runs trusted bundled
code only. Missing renderer dependencies cause an explicit export error while
structured inspection and durable chart state remain available.

Use `chart_snapshot(format="attachment")`, then `message(media=[artifact_path])`
for user delivery. `format="image"` supplies internal optional vision input;
`format="structured"` remains useful without image-capable models.
