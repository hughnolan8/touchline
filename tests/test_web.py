from fastapi.testclient import TestClient

from tests.test_scheduler import AT, Fakes
from touchline import scheduler
from touchline.web.app import app


def client():
    return TestClient(app)


def test_every_page_renders_on_an_empty_database():
    with client() as c:
        paths = ("/", "/predictions", "/accumulator", "/accumulator?auto=3&stake=x", "/bets")
        for path in (*paths, "/engine", "/?league=E0", "/bets?league=XX"):
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


def test_accumulator_prices_chosen_legs(monkeypatch):
    monkeypatch.setenv("ODDS_API_KEY", "test")
    monkeypatch.setattr("touchline.web.app.now", lambda: "2026-01-10T12:00:00+00:00")
    scheduler.tick(AT, Fakes())
    with client() as c:
        empty = c.get("/accumulator").text
        assert "Arsenal v Aston Villa" in empty
        leg = {"leg.E0:arsenal-astonvilla:2026-01-10": "away", "stake": "5"}
        priced = c.get("/accumulator", params=leg).text
        assert "Returns on £5.00" in priced and 'value="away" checked' in priced
