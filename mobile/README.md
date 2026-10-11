# Kili mobile

Native Expo client for the existing Kili gateway. It does not ship a second agent, database, or trading engine.

The visual direction follows the same dark, low-clutter conversation style used as a reference by Rakazo. No Rakazo backend, worker, or financial code is included, and no Rakazo source was copied.

## Connect

1. Run the Kili gateway you already use.
2. Open the app and enter that gateway address plus the pairing secret from `/webui/bootstrap`.
3. The session token is stored with `expo-secure-store`.

Chat, streaming, approvals, automations, and cloud-chart candles use the same authenticated HTTP and WebSocket contracts as the WebUI.

## Checks

```bash
npm test
npm run typecheck
npx expo-doctor
```

Maestro smoke flow: `maestro/smoke.yaml`.
