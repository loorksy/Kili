# Fresh Kili deploy on the existing VPS

Kili is a new install. The old `kili-trading` unit, `/opt/kili-trading`, and its data are gone. Rakazo stays running and is used once, as a credential source. After provisioning, Kili does not read Rakazo.

Do not print secret values. Do not commit `/opt/kili/data`. Do not run `docker compose down -v` in `/opt/rakazo`. Do not edit `/docker/traefik/dynamic/rakazo.yml`.

## What is copied

| Rakazo source | Kili destination | Notes |
| --- | --- | --- |
| `trading_connections` where `provider = metaapi` and `revokedAt` is null. Ciphertext opens with `ENCRYPTION_KEY` from `/opt/rakazo/.env`. The associated data is the connection id. | Secret file `connection_metaapi` under the Kili config `internal/secrets` directory. Config keeps only `secretRef`, account id, region, and `practice`/`live`. | `DEMO` becomes `practice`. `REAL` becomes `live`. The token is not written into `config.json`. |
| `user_model_credentials.provider = zai`, preferring model `glm-5.3-flash`, joined to `secrets`. Ciphertext opens with the secret row id. | `/opt/kili/data/kili.env` key `ZAI_API_KEY`. Config stores `${ZAI_API_KEY}` and API base `https://api.z.ai/api/coding/paas/v4` unless the stored secret already has `baseUrl`. | This base is the `zai` provider base in Rakazo's pinned `@earendil-works/pi-ai@0.87.1` catalog. Model becomes `zhipu/glm-5.3-flash`. |
| Nothing | `KILI_WEB_TOKEN` in the same env file, referenced as `channels.websocket.tokenIssueSecret`. | New Kili pairing secret. It is not a Rakazo secret. |

No other Rakazo secrets are copied. `delegatedTradingBlocked` is set true so this deploy cannot open risk. Chart reads stay enabled.

## Install

Run as root. Replace `COMMIT` with the pushed Kili SHA.

```sh
id kili >/dev/null 2>&1 || useradd --system --create-home --home-dir /opt/kili --shell /usr/sbin/nologin kili
install -d -o kili -g kili -m 0700 /opt/kili /opt/kili/src /opt/kili/data /opt/kili/data/workspace
sudo -u kili git clone https://github.com/loorksy/Kili.git /opt/kili/src
sudo -u kili git -C /opt/kili/src fetch origin
sudo -u kili git -C /opt/kili/src checkout COMMIT
cd /opt/kili/src/webui && sudo -u kili npm ci && sudo -u kili npm run build
sudo -u kili python3 -m venv /opt/kili/venv
sudo -u kili /opt/kili/venv/bin/pip install --upgrade pip
sudo -u kili /opt/kili/venv/bin/pip install /opt/kili/src
sudo -u kili /opt/kili/venv/bin/python -m nanobot.trading.sdk_install --config /opt/kili/data/config.json
```

`sdk_install` before the config exists still creates the protected SDK directory beside the config path once that parent exists. Create `/opt/kili/data` first, as above. If the installer complains that the config is missing, run it again after the provision step.

Install Chromium for chart export if `chromium` or `chromium-browser` is not already on `PATH` for the `kili` user. Do not install the MetaApi SDK into `/opt/kili/venv`.

## Provision from Rakazo

```sh
sudo -u kili /opt/kili/venv/bin/python /opt/kili/src/scripts/provision_kili_from_rakazo.py
sudo -u kili /opt/kili/venv/bin/python /opt/kili/src/scripts/provision_kili_from_rakazo.py --apply
```

The first command prints only account id, environment, region, currency, model id, and API base. The second writes:

- `/opt/kili/data/config.json` mode `0600`
- `/opt/kili/data/kili.env` mode `0600`
- the MetaApi token under `/opt/kili/data/internal/secrets/` mode `0600`

Read `KILI_WEB_TOKEN` only on the server when you need to open the WebUI. Do not paste it into chat, logs, or git.

Confirm Rakazo is unchanged:

```sh
docker compose --project-directory /opt/rakazo ps
git -C /opt/rakazo status --short
```

## Service and TLS

```sh
cp /opt/kili/src/deploy/kili.service /etc/systemd/system/kili.service
systemctl daemon-reload
systemctl enable --now kili.service
ss -ltnp | awk 'NR==1 || /:8765|:18790/'
```

`8765` and `18790` must be on `127.0.0.1` only.

Copy the router shape from `/docker/traefik/dynamic/rakazo.yml` into a new file `/docker/traefik/dynamic/kili.yml`. The example `deploy/traefik-kili.yml.example` matches the current file-provider style: `websecure`, `letsencrypt`, backend `http://127.0.0.1:8765`, host `kili.lork.cloud`. If `rakazo.yml` uses different field names, follow that file and change only the host and the backend URL. Do not change the Rakazo router.

## Checks

```sh
systemctl is-active kili.service
journalctl -u kili.service -n 80 --no-pager
sudo -u kili /opt/kili/venv/bin/python /opt/kili/src/scripts/vps_readonly_broker_check.py --config /opt/kili/data/config.json
sudo -u kili /opt/kili/venv/bin/python /opt/kili/src/scripts/vps_watcher_acceptance.py --config /opt/kili/data/config.json --unit kili.service
```

Expected watcher lines include `paused_lifecycle: SUSPENDED_BY_PARENT`, `resumed_lifecycle: ACTIVE`, `owner_cancel: CANCELLED`, and `stale_execution_error_count: 0`.

Public checks, from a browser:

- `https://kili.lork.cloud/` loads.
- Pair with `KILI_WEB_TOKEN` from the server env file.
- Send a short chat and confirm a model reply. The key must not appear in the page or in `journalctl`.
- Open Cloud Chart and confirm broker symbols, quotes, and candles.
- Switch language to Arabic and confirm `dir=rtl` on the document, with symbols and prices still left-to-right.

Mobile pairing uses the same public origin `https://kili.lork.cloud` and the same pairing secret. The app stores the issued session token in the device secure store. No server secret is built into the app.

There are no old watcher rows to migrate. The gateway reconciles watcher rows on startup and on each due pass.

Stopping Rakazo after this must leave Kili's env file, secret file, and config in place. Do not point Kili back at `/opt/rakazo`.

Approvals and mandates use the Approve and Deny buttons in the WebUI and mobile app. Those buttons send the exact stored action fingerprint to an owner-only endpoint. `/approve` remains a hidden fallback, and the agent is instructed not to ask for it.

The Android app is downloaded from `https://kili.lork.cloud/downloads/kili.apk`. Publishing the APK and interface updates is described in `docs/mobile-releases.md`.

The sidebar can create persistent agents and group chats. Each agent has its own conversation and instructions. A group handoff does not copy an approval card or transfer a mandate. There is no per-agent computer or browser sandbox.
