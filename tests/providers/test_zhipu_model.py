"""Zhipu and api.z.ai reject the zhipu/ route prefix."""
from nanobot.providers.openai_compat_provider import OpenAICompatProvider
from nanobot.providers.registry import find_by_name


def test_zhipu_sends_the_bare_model_name():
    spec = find_by_name("zhipu")
    assert spec is not None and spec.strip_model_prefix is True
    provider = OpenAICompatProvider.__new__(OpenAICompatProvider)
    provider._spec = spec
    assert provider._request_model_name("zhipu/glm-5.3-flash") == "glm-5.3-flash"
    assert provider._request_model_name("glm-5.3-flash") == "glm-5.3-flash"
