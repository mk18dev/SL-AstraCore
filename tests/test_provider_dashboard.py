from __future__ import annotations

import json

import dashboard_app as da
from astra.providers import ProviderConfigStore


def _save_test_provider(monkeypatch, tmp_path):
    monkeypatch.setenv("ASTRA_HOME", str(tmp_path / ".astra"))
    ProviderConfigStore().save(
        provider="openai-compatible",
        base_url="https://api.example.com/v1",
        model="test-model",
        api_key="secret-test-key",
    )


def test_provider_settings_api_never_returns_key(auth_client, monkeypatch, tmp_path):
    _save_test_provider(monkeypatch, tmp_path)

    response = auth_client.get("/api/providers/config")
    assert response.status_code == 200
    body = response.json()
    assert body["key_present"] is True
    assert body["model"] == "test-model"
    assert "api_key" not in body
    assert "secret-test-key" not in response.text

    updated = auth_client.post("/api/providers/config", json={
        "provider": "openai-compatible",
        "base_url": "https://api.example.com/v1",
        "model": "new-model",
        "api_key": "",
    })
    assert updated.status_code == 200, updated.text
    assert ProviderConfigStore().load().api_key == "secret-test-key"


def test_provider_settings_reject_insecure_remote_http(auth_client, monkeypatch, tmp_path):
    monkeypatch.setenv("ASTRA_HOME", str(tmp_path / ".astra"))
    response = auth_client.post("/api/providers/config", json={
        "provider": "openai-compatible",
        "base_url": "http://remote.example/v1",
        "model": "model",
        "api_key": "secret",
    })
    assert response.status_code == 400


def test_provider_test_endpoint_reports_connection_without_secret(
    auth_client, monkeypatch, tmp_path
):
    _save_test_provider(monkeypatch, tmp_path)

    class FakeProvider:
        def __init__(self, config):
            assert config.api_key == "secret-test-key"

        def __call__(self, prompt):
            assert "ASTRA_PROVIDER_OK" in prompt
            return "ASTRA_PROVIDER_OK"

    monkeypatch.setattr(da, "OpenAICompatibleProvider", FakeProvider)
    response = auth_client.post("/api/providers/test")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "connected"
    assert "secret-test-key" not in response.text


def test_agent_run_reviews_provider_output_without_applying(
    auth_client, monkeypatch, tmp_path
):
    _save_test_provider(monkeypatch, tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    source = repo / "billing.py"
    source.write_text(
        "def charge(amount):\n    return amount - 1\n",
        encoding="utf-8",
    )

    class FakeProvider:
        def __init__(self, config):
            pass

        def __call__(self, prompt):
            assert "def charge" in prompt
            return json.dumps({"edits": [{
                "path": "billing.py",
                "old_text": "return amount - 1",
                "new_text": "return amount",
                "reason": "remove off-by-one subtraction",
            }]})

    monkeypatch.setattr(da, "OpenAICompatibleProvider", FakeProvider)
    da._orchestrator.register_repo(str(repo))
    response = auth_client.post("/api/agent/run", json={
        "path": str(repo),
        "query": "fix the off by one error in charge",
        "max_tokens": 2000,
    })
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "reviewed", body
    assert body["edits"][0]["path"] == "billing.py"
    assert source.read_text(encoding="utf-8") == (
        "def charge(amount):\n    return amount - 1\n"
    )
