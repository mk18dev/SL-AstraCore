from __future__ import annotations

import io
import json
import os
from urllib.error import HTTPError

import pytest

from astra.providers import (
    OpenAICompatibleProvider,
    ProviderConfigStore,
    ProviderConfigurationError,
    ProviderRequestError,
    ProviderConfig,
    validate_base_url,
)


def test_validate_base_url_requires_https_except_loopback():
    assert validate_base_url("https://api.example.com/v1/") == "https://api.example.com/v1"
    assert validate_base_url("http://localhost:11434/v1") == "http://localhost:11434/v1"
    with pytest.raises(ProviderConfigurationError):
        validate_base_url("http://api.example.com/v1")
    with pytest.raises(ProviderConfigurationError):
        validate_base_url("https://user:pass@example.com/v1")


def test_config_store_masks_secret_and_preserves_blank_key(tmp_path):
    path = tmp_path / "providers.json"
    store = ProviderConfigStore(path)
    saved = store.save(
        provider="openai-compatible",
        base_url="https://api.example.com/v1",
        model="test-model",
        api_key="secret-value",
    )
    assert saved.api_key == "secret-value"
    assert store.public_view(saved) == {
        "provider": "openai-compatible",
        "base_url": "https://api.example.com/v1",
        "model": "test-model",
        "configured": True,
        "key_present": True,
    }

    store.save(
        provider="openai-compatible",
        base_url="https://api.example.com/v1",
        model="test-model-2",
        api_key="",
    )
    assert store.load().api_key == "secret-value"

    store.save(
        provider="openai-compatible",
        base_url="https://api.example.com/v1",
        model="test-model-2",
        api_key=None,
        clear_api_key=True,
    )
    assert store.load().api_key == ""
    if os.name == "posix":
        assert path.stat().st_mode & 0o777 == 0o600


def test_config_store_rejects_unsupported_provider(tmp_path):
    store = ProviderConfigStore(tmp_path / "providers.json")
    with pytest.raises(ProviderConfigurationError):
        store.save(
            provider="unsupported",
            base_url="https://api.example.com/v1",
            model="m",
            api_key="",
        )


def test_provider_sends_bearer_key_and_extracts_completion(monkeypatch):
    seen = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self, size):
            assert size == 1_048_577
            return json.dumps({
                "choices": [{"message": {"content": '{"edits": []}'}}]
            }).encode()

    def fake_urlopen(request, timeout):
        seen["url"] = request.full_url
        seen["authorization"] = request.get_header("Authorization")
        seen["timeout"] = timeout
        seen["payload"] = json.loads(request.data)
        return Response()

    monkeypatch.setattr("astra.providers.urlopen", fake_urlopen)
    provider = OpenAICompatibleProvider(
        ProviderConfig(
            base_url="https://api.example.com/v1",
            model="model-x",
            api_key="secret-value",
        ),
        timeout=12,
    )
    assert provider("inspect this repo") == '{"edits": []}'
    assert seen["url"] == "https://api.example.com/v1/chat/completions"
    assert seen["authorization"] == "Bearer secret-value"
    assert seen["timeout"] == 12
    assert seen["payload"]["model"] == "model-x"


def test_provider_does_not_leak_http_error_body_or_key(monkeypatch):
    def fail_urlopen(request, timeout):
        raise HTTPError(
            request.full_url,
            401,
            "unauthorized",
            hdrs=None,
            fp=io.BytesIO(b"secret-value should never escape"),
        )

    monkeypatch.setattr("astra.providers.urlopen", fail_urlopen)
    provider = OpenAICompatibleProvider(
        ProviderConfig(api_key="secret-value")
    )
    with pytest.raises(ProviderRequestError) as exc:
        provider("hello")
    assert "secret-value" not in str(exc.value)
    assert "401" in str(exc.value)



def test_config_store_defaults_and_environment_overrides(tmp_path, monkeypatch):
    store = ProviderConfigStore(tmp_path / "missing.json")
    assert store.load() == ProviderConfig()
    monkeypatch.setenv("ASTRA_PROVIDER", "openai-compatible")
    monkeypatch.setenv("ASTRA_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setenv("ASTRA_MODEL", "local-model")
    monkeypatch.setenv("ASTRA_API_KEY", "local-secret")
    config = store.load()
    assert config.base_url == "http://localhost:11434/v1"
    assert config.model == "local-model"
    assert config.api_key == "local-secret"


@pytest.mark.parametrize(
    "raw",
    [
        "not-json",
        "[]",
        '{"version": 99}',
    ],
)
def test_config_store_rejects_corrupt_or_unsupported_files(tmp_path, raw):
    path = tmp_path / "providers.json"
    path.write_text(raw, encoding="utf-8")
    with pytest.raises(ProviderConfigurationError):
        ProviderConfigStore(path).load()


@pytest.mark.parametrize("bad_key", ["bad\\nkey", "bad\\rkey", 123, ["not", "a", "key"]])
def test_config_store_rejects_invalid_api_keys(tmp_path, bad_key):
    store = ProviderConfigStore(tmp_path / "providers.json")
    with pytest.raises(ProviderConfigurationError):
        store.save(
            provider="openai-compatible",
            base_url="https://api.example.com/v1",
            model="test-model",
            api_key=bad_key,
        )


def test_provider_rejects_unconfigured_model():
    provider = OpenAICompatibleProvider(ProviderConfig(model="", base_url=""))
    with pytest.raises(ProviderConfigurationError, match="not configured"):
        provider("hello")


def test_provider_omits_authorization_when_key_is_not_required(monkeypatch):
    seen = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self, size):
            return b'{"choices":[{"message":{"content":"ok"}}]}'

    def fake_urlopen(request, timeout):
        seen["authorization"] = request.get_header("Authorization")
        return Response()

    monkeypatch.setattr("astra.providers.urlopen", fake_urlopen)
    assert OpenAICompatibleProvider(ProviderConfig(api_key=""))("hello") == "ok"
    assert seen["authorization"] is None


@pytest.mark.parametrize(
    ("response_bytes", "message"),
    [
        (b"not-json", "invalid JSON"),
        (b'{"choices":[]}', "did not contain a chat completion"),
        (b'{"choices":[{"message":{"content":" "}}]}', "empty completion"),
    ],
)
def test_provider_rejects_invalid_completion_payloads(
    monkeypatch, response_bytes, message
):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self, size):
            return response_bytes

    monkeypatch.setattr("astra.providers.urlopen", lambda request, timeout: Response())
    with pytest.raises(ProviderRequestError, match=message):
        OpenAICompatibleProvider(ProviderConfig())("hello")


def test_provider_rejects_oversized_response(monkeypatch):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self, size):
            return b"x" * size

    monkeypatch.setattr("astra.providers.urlopen", lambda request, timeout: Response())
    with pytest.raises(ProviderRequestError, match="exceeded 1 MiB"):
        OpenAICompatibleProvider(ProviderConfig())("hello")


def test_provider_sanitizes_connection_errors(monkeypatch):
    from urllib.error import URLError

    def fail_urlopen(request, timeout):
        raise URLError("secret transport details")

    monkeypatch.setattr("astra.providers.urlopen", fail_urlopen)
    with pytest.raises(ProviderRequestError) as exc:
        OpenAICompatibleProvider(ProviderConfig(api_key="secret"))("hello")
    assert "secret transport details" not in str(exc.value)
    assert "secret" not in str(exc.value)
