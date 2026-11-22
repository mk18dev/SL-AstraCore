r"""Cross-origin requests must not be able to drive the dashboard.

Every state-changing route is a GET with a `path` parameter, which auto-registered
and indexed an arbitrary directory. Any page the user happened to have open could
then pull e.g. C:\ into the graph (`<img src="http://localhost:8780/api/context?path=C:/">`)
and, because /api/patch/apply is confined to *registered* roots, write into it.
Registration is now explicit and foreign Origins are refused.
"""

import pytest
from fastapi.testclient import TestClient

import dashboard_app as da


@pytest.fixture
def client(auth_client):
    return auth_client


def test_foreign_origin_is_refused(client, tmp_path):
    for endpoint in ("/api/status", "/api/repos", "/api/explorer", "/api/context"):
        response = client.get(endpoint, params={"path": str(tmp_path)}, headers={"origin": "http://evil.example"})
        assert response.status_code == 403, f"{endpoint} accepted a cross-origin request"
        assert "cross-origin" in response.text


def test_local_origin_is_allowed(client):
    assert client.get("/api/status", headers={"origin": "http://localhost:8780"}).status_code == 200
    assert client.get("/api/status", headers={"origin": "http://127.0.0.1:8780"}).status_code == 200


def test_no_origin_header_is_allowed(client):
    """A direct navigation (curl, address bar) sends no Origin; that is legitimate."""
    assert client.get("/api/status").status_code == 200


def test_get_endpoints_do_not_register_unknown_paths(client, tmp_path):
    probe = tmp_path / "secret.txt"
    probe.write_text("sensitive", encoding="utf-8")
    before = len(da._orchestrator.list_repos())

    for endpoint in ("/api/context", "/api/execution", "/api/graph/sample", "/api/graph/node"):
        response = client.get(endpoint, params={"path": str(tmp_path), "query": "x", "node_id": "x"})
        assert response.status_code == 404, f"{endpoint} registered an unregistered repo"

    assert len(da._orchestrator.list_repos()) == before, "a GET created a repo registration"


def test_explicit_registration_still_works(client, tmp_path):
    (tmp_path / "main.py").write_text("def main():\n    return 1\n", encoding="utf-8")
    added = client.post("/api/repos/add", json={"path": str(tmp_path)})
    assert added.status_code == 200, added.text
    body = added.json()
    assert body["status"] == "active"
    assert body["files"] == 1

    # and it is now readable through the GET endpoints
    assert client.get("/api/context", params={"path": str(tmp_path), "query": "main"}).status_code == 200


# ── Access token ────────────────────────────────────────────────────────
#
# "Local" is not a boundary: any page open in the browser can reach
# localhost:8780, and the dashboard indexes arbitrary directories and writes
# into registered ones. A per-process token, minted at startup and sent as a
# bearer header, closes that.


def test_every_api_route_requires_a_token():
    from fastapi.routing import APIRoute

    unguarded = []
    for route in da.app.routes:
        if not isinstance(route, APIRoute):
            continue
        if route.path in da._PUBLIC_PATHS or route.path.startswith("/static"):
            continue
        response = TestClient(da.app, raise_server_exceptions=False).get(route.path)
        if response.status_code != 401:
            unguarded.append(route.path)
    assert not unguarded, f"routes reachable without a token: {unguarded}"


def test_wrong_token_is_refused(client):
    response = client.get("/api/status", headers={"Authorization": "Bearer nope"})
    assert response.status_code == 401


def test_valid_token_is_accepted(auth_client):
    assert auth_client.get("/api/status").status_code == 200


def test_shell_is_public_without_disclosing_the_token():
    """The SPA shell is public; every data/API route remains bearer-protected."""
    plain = TestClient(da.app, raise_server_exceptions=False)
    response = plain.get("/")
    assert response.status_code == 200
    assert da._ACCESS_TOKEN not in response.text


def test_query_parameter_cannot_authenticate_api_requests():
    plain = TestClient(da.app, raise_server_exceptions=False)
    response = plain.get("/api/status", params={"token": da._ACCESS_TOKEN})
    assert response.status_code == 401


def test_disable_auth_environment_flag_is_ignored(monkeypatch):
    monkeypatch.setenv("ASTRA_DISABLE_AUTH", "1")
    _token, required = da._resolve_token()
    assert required is True


def test_assets_stay_public():
    plain = TestClient(da.app, raise_server_exceptions=False)
    assert plain.get("/manifest.webmanifest").status_code == 200
    assert plain.get("/favicon.ico").status_code == 200



def test_server_binds_to_loopback_by_default(monkeypatch):
    monkeypatch.delenv("ASTRA_HOST", raising=False)
    assert da._server_host() == "127.0.0.1"


def test_server_network_binding_requires_explicit_configuration(monkeypatch):
    monkeypatch.setenv("ASTRA_HOST", "0.0.0.0")
    assert da._server_host() == "0.0.0.0"



def test_cli_server_uses_dashboard_host_policy(monkeypatch):
    from astra.cli import _server_host as cli_server_host

    monkeypatch.delenv("ASTRA_HOST", raising=False)
    assert cli_server_host() == "127.0.0.1"
    monkeypatch.setenv("ASTRA_HOST", "0.0.0.0")
    assert cli_server_host() == "0.0.0.0"
