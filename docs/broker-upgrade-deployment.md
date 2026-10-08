# Deploy this broker upgrade with Cursor

Deploy only the existing trading checkout and its `kili-trading.service`.
Do not edit/restart the separate Nanobot service, other projects, or the retired
Kili backup. Do not reset tracked work or overwrite persistent data/config.
Confirm the checkout/service paths and service user before applying these steps.

1. Fetch GitHub main and fast-forward the trading checkout. Inspect local changes
   first. Keep the old config and protected storage; make a private external
   backup if required by the deployment's existing procedure.
2. Install the updated project into that service's virtualenv. Preserve the main
   environment's Socket.IO 5 dependency for channels; **do not pip-install the
   MetaApi SDK into that virtualenv**.
3. Run the official isolated connector installer as the service user, with the
   exact config path used by the service. For the previously reported deployment:

   ```sh
   sudo -u kili /opt/kili-trading/venv/bin/python -m nanobot.trading.sdk_install --config /opt/kili-trading/data/config.json
   ```

   Adapt these paths only after verifying the actual unit. The private SDK is
   stored beside that config under `internal/metaapi-sdk`.
4. In the trading frontend checkout run `npm ci` and `npm run build`.
   Chart-only JS/CSS and hashes ship in Git; regenerate with
   `npm run build:chart-renderer` only when intentionally rebuilding the adapter.
5. Verify a system `chromium`/`chromium-browser` is available to the service and
   that its project virtualenv contains the pinned Playwright dependency. No
   persistent browser, remote desktop or Playwright browsing service is needed.
6. Restart **only** `kili-trading.service`. Check sanitized logs, account catalog,
   broker quotes/history and chart image attachment delivery. Do not print
   tokens/config contents, enable operator emergency overrides, approve a live
   mandate or send a real trade as a deployment smoke test.
7. Check the separate Nanobot and other project services remain untouched.

Existing single MetaApi profiles are normalized into the account list on load.
Add further named connections through existing Settings. Use chat
`account(list_accounts/select_account)` for conversation selection. Existing
positions/proposals/charts/mandates stay bound to their original account.

OANDA settings are retired. Existing OANDA charts/evidence remain labeled
read-only cached archives; create a broker chart/watcher rather than changing
old source identity. Exact chat approval is required for financial authority.
Configured account/emergency guardrails and `delegatedTradingBlocked` still
block new risk. No automatic financial mutation is part of this deployment.
