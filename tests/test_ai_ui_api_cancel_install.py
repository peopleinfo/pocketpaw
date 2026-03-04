from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from pocketpaw.ai_ui.api import router


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_cancel_install_endpoint_running_process():
    with patch("pocketpaw.ai_ui.plugins.cancel_install", return_value=True):
        with _client() as client:
            resp = client.post("/api/ai-ui/plugins/demo/cancel-install")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "cancelled" in body["message"].lower()


def test_cancel_install_endpoint_no_running_process():
    with patch("pocketpaw.ai_ui.plugins.cancel_install", return_value=False):
        with _client() as client:
            resp = client.post("/api/ai-ui/plugins/demo/cancel-install")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "no running install found" in body["message"].lower()


def test_cancel_install_legacy_route_alias():
    with patch("pocketpaw.ai_ui.plugins.cancel_install", return_value=True):
        with _client() as client:
            resp = client.post("/api/ai-ui/plugins/cancel-install/demo")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
