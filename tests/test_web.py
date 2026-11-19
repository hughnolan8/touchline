from fastapi.testclient import TestClient

from tests.test_scheduler import AT, Fakes
from touchline import scheduler
from touchline.web.app import app


def client():
    return TestClient(app)


def test_every_page_renders_on_an_empty_database():
    with client() as c:
        for path in ("/", "/predictions", "/bets", "/engine", "/?league=E0", "/bets?league=XX"):
            response = c.get(path)
            assert response.status_code == 200, path
            assert "Touchline" in response.text


def test_pages_show_ledger_after_a_tick(monkeypatch):
    monkeypatch.setenv("ODDS_API_KEY", "test")
    scheduler.tick(AT, Fakes())
    with client() as c:
        assert "Arsenal v Aston Villa" in c.get("/bets").text
        assert "ok" in c.get("/engine").text
        assert c.get("/health").json()["last_tick"]["ok"] == 1


def test_admin_actions_require_token(monkeypatch):
    with client() as c:
        assert c.post("/admin/refit").status_code == 403
        monkeypatch.setenv("TOUCHLINE_ADMIN_TOKEN", "s3cret")
        assert c.post("/admin/refit").status_code == 401
        assert c.post("/admin/refit", auth=("x", "wrong")).status_code == 401
        ok = c.post("/admin/refit", auth=("admin", "s3cret"), follow_redirects=False)
        assert ok.status_code == 303
        assert c.post("/admin/nope", auth=("admin", "s3cret")).status_code == 404
