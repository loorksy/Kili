"""Copy Rakazo's runtime credentials into Kili's own config without printing them.

Run this on the VPS after Kili is installed. It reads Rakazo's Postgres through
the existing Compose service, decrypts with ENCRYPTION_KEY, and writes Kili's
config plus a 0600 environment file. Rakazo is not modified and is not read
again after this command succeeds.
"""
from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path
from typing import cast

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from nanobot.config.loader import load_config, save_config, set_config_path
from nanobot.config.schema import Config
from nanobot.market.models import Connection
from nanobot.security.secrets import SecretStore

ZAI_API_BASE = "https://api.z.ai/api/coding/paas/v4"
_VERSION_PREFIX = "v2:"
_SALT_BYTES = 16
_IV_BYTES = 12
_TAG_BYTES = 16


class ProvisionError(Exception):
    """A safe message. It must not carry ciphertext or plaintext."""


def parse_env_file(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key:
            values[key] = value
    return values


def open_rakazo_secret(ciphertext: str, encryption_key: str, record_id: str) -> str:
    try:
        if ciphertext.startswith(_VERSION_PREFIX):
            blob = _b64(ciphertext[len(_VERSION_PREFIX):])
            if len(blob) < _SALT_BYTES + _IV_BYTES + _TAG_BYTES:
                raise ProvisionError("Encrypted Rakazo credential is malformed")
            salt = blob[:_SALT_BYTES]
            iv = blob[_SALT_BYTES:_SALT_BYTES + _IV_BYTES]
            tag = blob[_SALT_BYTES + _IV_BYTES:_SALT_BYTES + _IV_BYTES + _TAG_BYTES]
            enc = blob[_SALT_BYTES + _IV_BYTES + _TAG_BYTES:]
            key = Scrypt(salt=salt, length=32, n=16_384, r=8, p=1).derive(encryption_key.encode())
            return AESGCM(key).decrypt(iv, enc + tag, record_id.encode()).decode()
        blob = _b64(ciphertext)
        iv = blob[:_IV_BYTES]
        tag = blob[_IV_BYTES:_IV_BYTES + _TAG_BYTES]
        enc = blob[_IV_BYTES + _TAG_BYTES:]
        import hashlib
        key = hashlib.sha256(encryption_key.encode()).digest()
        return AESGCM(key).decrypt(iv, enc + tag, None).decode()
    except ProvisionError:
        raise
    except Exception as exc:
        raise ProvisionError("Could not decrypt a Rakazo credential") from exc


def _b64(value: str) -> bytes:
    import base64
    try:
        return base64.b64decode(value, validate=True)
    except Exception as exc:
        raise ProvisionError("Encrypted Rakazo credential is malformed") from exc


def map_metaapi_environment(value: str | None) -> str:
    normalized = (value or "").strip().upper()
    if normalized == "DEMO":
        return "practice"
    if normalized == "REAL":
        return "live"
    raise ProvisionError("Rakazo broker environment is not DEMO or REAL")


def map_region(value: str | None) -> str:
    region = (value or "london").strip().lower()
    if not region.replace("-", "").isalnum() or not region[0].isalpha() or not 2 <= len(region) <= 31:
        raise ProvisionError("Rakazo broker region is not usable by Kili")
    return region


def map_model_secret(plaintext: str, provider: str, model_id: str) -> tuple[str, str, str]:
    """Return Kili provider name, model id, and API base. The key stays outside."""
    payload = _json_object(plaintext)
    provider = provider.strip()
    model_id = model_id.strip()
    if payload is not None:
        if payload.get("kind") == "oauth":
            raise ProvisionError("Rakazo model credential is OAuth, not an API key")
        base = payload.get("baseUrl")
        if payload.get("kind") == "openai_compatible" and isinstance(base, str) and base.strip():
            return "zhipu", model_id, base.strip().rstrip("/")
        if "apiKey" not in payload and "key" not in payload:
            raise ProvisionError("Rakazo model credential is not a usable API key")
    if provider != "zai":
        raise ProvisionError(f"Rakazo model provider {provider!r} has no Kili mapping")
    if not model_id:
        raise ProvisionError("Rakazo model id is empty")
    return "zhipu", model_id, ZAI_API_BASE


def _json_object(plaintext: str) -> dict[str, object] | None:
    import json
    text = plaintext.strip()
    if not text.startswith("{"):
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProvisionError("Rakazo model credential is not a usable API key") from exc
    if not isinstance(payload, dict):
        raise ProvisionError("Rakazo model credential is not a usable API key")
    raw = cast(dict[object, object], payload)
    return {str(key): value for key, value in raw.items()}


def api_key_from_model_secret(plaintext: str) -> str:
    text = plaintext.strip()
    payload = _json_object(text)
    if payload is None:
        if not text:
            raise ProvisionError("Rakazo model credential is empty")
        return text
    for field in ("apiKey", "key"):
        value = payload.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    raise ProvisionError("Rakazo model credential is not a usable API key")


def public_summary(*, account_id: str, environment: str, region: str, currency: str | None,
                   provider: str, model_id: str, api_base: str) -> str:
    currency_text = currency or "unreported"
    return "\n".join([
        "KILI PROVISION SUMMARY",
        f"metaapi_account_id: {account_id}",
        f"metaapi_environment: {environment}",
        f"metaapi_region: {region}",
        f"metaapi_currency: {currency_text}",
        f"model_provider: {provider}",
        f"model_id: {model_id}",
        f"model_api_base: {api_base}",
        "secrets_written: yes",
        "secret_values_printed: no",
    ])


def _psql(rakazo_dir: Path, sql: str) -> str:
    completed = subprocess.run(
        ["docker", "compose", "--project-directory", str(rakazo_dir), "exec", "-T", "postgres",
         "sh", "-c", 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At -F "$(printf \'\\t\')" -c "$1"',
         "sh", sql],
        check=False, capture_output=True, text=True,
    )
    if completed.returncode != 0:
        raise ProvisionError("Could not read Rakazo Postgres")
    return completed.stdout


def _select_broker(rows: list[list[str]]) -> list[str]:
    usable = [row for row in rows if len(row) >= 6 and row[5]]
    if not usable:
        raise ProvisionError("Rakazo has no active MetaApi connection")
    return usable[0]


def _select_model(rows: list[list[str]]) -> list[str]:
    preferred = [row for row in rows if len(row) >= 4 and row[0] == "zai" and row[1] == "glm-5.3-flash"]
    chosen = preferred[0] if preferred else next((row for row in rows if len(row) >= 4 and row[0] == "zai"), None)
    if chosen is None:
        raise ProvisionError("Rakazo has no zai model credential")
    return chosen


def _write_private(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_text(text)
    path.chmod(0o600)


def apply_config(config_path: Path, *, account_id: str, token: str, environment: str, region: str,
                 model_id: str, api_base: str, public_host: str) -> None:
    set_config_path(config_path.resolve())
    config = load_config(config_path) if config_path.exists() else Config()
    reference = "connection_metaapi"
    SecretStore().put(reference, token)
    (SecretStore().root / reference).chmod(0o600)
    connection = Connection(
        secret_ref=reference, account_id=account_id,
        environment="live" if environment == "live" else "practice", region=region, name="Rakazo broker",
    )
    config.tools.integrations.metaapi_accounts = {account_id: connection}
    config.tools.integrations.default_metaapi_account = account_id
    config.tools.integrations.metaapi = connection
    config.tools.integrations.charts_enabled = True
    config.tools.integrations.delegated_trading_blocked = True
    config.agents.defaults.provider = "zhipu"
    config.agents.defaults.model = f"zhipu/{model_id}"
    config.agents.defaults.workspace = str(config_path.parent / "workspace")
    config.providers.zhipu.api_key = "${ZAI_API_KEY}"
    config.providers.zhipu.api_base = api_base
    config.gateway.host = "127.0.0.1"
    payload = config.model_dump(mode="json", by_alias=True)
    payload.setdefault("channels", {})["websocket"] = {
        "enabled": True, "host": "127.0.0.1", "port": 8765, "path": "/",
        "publicWsUrl": f"wss://{public_host}/", "tokenIssueSecret": "${KILI_WEB_TOKEN}",
        "websocketRequiresToken": True, "allowFrom": ["*"], "streaming": True,
    }
    saved = Config.model_validate(payload)
    from nanobot.channels.websocket.runtime import WebSocketConfig
    from nanobot.security.financial_auth import require_financial_gateway_auth
    WebSocketConfig.model_validate(payload["channels"]["websocket"])
    require_financial_gateway_auth(saved)
    save_config(saved, config_path)
    config_path.chmod(0o600)
    os.chmod(config_path.parent, 0o700)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rakazo-dir", type=Path, default=Path("/opt/rakazo"))
    parser.add_argument("--rakazo-env", type=Path, default=Path("/opt/rakazo/.env"))
    parser.add_argument("--kili-config", type=Path, default=Path("/opt/kili/data/config.json"))
    parser.add_argument("--kili-env", type=Path, default=Path("/opt/kili/data/kili.env"))
    parser.add_argument("--public-host", default="kili.lork.cloud")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    os.umask(0o077)
    env = parse_env_file(args.rakazo_env.read_text())
    encryption_key = env.get("ENCRYPTION_KEY", "")
    if not encryption_key:
        raise SystemExit("Rakazo ENCRYPTION_KEY is missing")
    broker_sql = (
        'SELECT id, "providerAccountId", COALESCE(region, \'\'), COALESCE(environment, \'\'), '
        'COALESCE(currency, \'\'), ciphertext FROM trading_connections '
        "WHERE provider = 'metaapi' AND \"revokedAt\" IS NULL "
        'ORDER BY "verifiedAt" DESC NULLS LAST, "updatedAt" DESC'
    )
    model_sql = (
        'SELECT c.provider, COALESCE(p."modelId", \'\'), s.id, s.ciphertext '
        "FROM user_model_credentials c "
        'JOIN secrets s ON s.id = c."secretId" '
        'LEFT JOIN space_model_preferences p ON p."credentialId" = c.id '
        "WHERE c.provider = 'zai' "
        'ORDER BY p."isDefault" DESC NULLS LAST, p."updatedAt" DESC NULLS LAST, c."updatedAt" DESC'
    )
    broker = _select_broker([line.split("\t") for line in _psql(args.rakazo_dir, broker_sql).splitlines() if line])
    model = _select_model([line.split("\t") for line in _psql(args.rakazo_dir, model_sql).splitlines() if line])
    token = open_rakazo_secret(broker[5], encryption_key, broker[0])
    model_plaintext = open_rakazo_secret(model[3], encryption_key, model[2])
    environment = map_metaapi_environment(broker[3])
    region = map_region(broker[2] or None)
    _provider, model_id, api_base = map_model_secret(model_plaintext, model[0], model[1])
    api_key = api_key_from_model_secret(model_plaintext)
    print(public_summary(
        account_id=broker[1], environment=environment, region=region, currency=broker[4] or None,
        provider="zhipu", model_id=model_id, api_base=api_base,
    ))
    if not args.apply:
        print("Dry run only. Re-run with --apply to write Kili config.")
        return
    web_token = os.urandom(32).hex()
    _write_private(args.kili_env, f"ZAI_API_KEY={api_key}\nKILI_WEB_TOKEN={web_token}\n")
    apply_config(
        args.kili_config, account_id=broker[1], token=token, environment=environment, region=region,
        model_id=model_id, api_base=api_base, public_host=args.public_host,
    )
    (args.kili_config.parent / "workspace").mkdir(parents=True, exist_ok=True)
    print(f"Wrote {args.kili_config} and {args.kili_env} mode 0600")


if __name__ == "__main__":
    main()
