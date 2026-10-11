import json
from pathlib import Path

import pytest

from scripts.provision_kili_from_rakazo import (
    api_key_from_model_secret,
    apply_config,
    map_metaapi_environment,
    map_model_secret,
    open_rakazo_secret,
    public_summary,
)

_FIXTURE = "v2:MDEyMzQ1Njc4OWFiY2RlZqq7zN3u/wARIjNEVVbwYRn/JnSOJvMmWOBdsfAIFxx4KwGs8bFSvTuPlORywr8E83M="


def test_rakazo_v2_ciphertext_round_trip_uses_record_id():
    assert open_rakazo_secret(_FIXTURE, "fixture-encryption-key-at-least-32", "conn_fixture") == "fixture-metaapi-token"
    with pytest.raises(Exception):
        open_rakazo_secret(_FIXTURE, "fixture-encryption-key-at-least-32", "other-record")


def test_environment_and_zai_model_mapping():
    assert map_metaapi_environment("DEMO") == "practice"
    assert map_metaapi_environment("REAL") == "live"
    with pytest.raises(Exception):
        map_metaapi_environment("")
    provider, model, base = map_model_secret("fixture-key", "zai", "glm-5.3-flash")
    assert (provider, model, base) == ("zhipu", "glm-5.3-flash", "https://api.z.ai/api/coding/paas/v4")
    assert api_key_from_model_secret('{"kind":"openai_compatible","baseUrl":"https://example.test/v1","apiKey":"fixture-key"}') == "fixture-key"


def test_summary_and_config_do_not_contain_the_token(tmp_path: Path):
    import nanobot.config.loader as loader
    previous = loader._current_config_path
    try:
        summary = public_summary(
            account_id="acct-1", environment="practice", region="london", currency="USD",
            provider="zhipu", model_id="glm-5.3-flash", api_base="https://api.z.ai/api/coding/paas/v4",
        )
        assert "fixture-metaapi-token" not in summary
        config_path = tmp_path / "config.json"
        apply_config(
            config_path, account_id="acct-1", token="fixture-metaapi-token", environment="practice",
            region="london", model_id="glm-5.3-flash", api_base="https://api.z.ai/api/coding/paas/v4",
            public_host="kili.example",
        )
        text = config_path.read_text()
        assert "fixture-metaapi-token" not in text
        assert "${ZAI_API_KEY}" in text
        assert "${KILI_WEB_TOKEN}" in text
        saved = json.loads(text)
        assert saved["tools"]["integrations"]["delegatedTradingBlocked"] is True
        assert saved["channels"]["websocket"]["host"] == "127.0.0.1"
        secret = next((tmp_path / "internal" / "secrets").iterdir())
        assert secret.read_text() == "fixture-metaapi-token"
        assert secret.stat().st_mode & 0o077 == 0
    finally:
        loader._current_config_path = previous
