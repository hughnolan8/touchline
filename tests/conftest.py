import random
from datetime import UTC, datetime, timedelta

import pytest

TEAMS = ["arsenal", "chelsea", "liverpool", "everton", "spurs", "villa"]


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Every test gets its own SQLite file and no external credentials."""
    monkeypatch.setenv("TOUCHLINE_DB", str(tmp_path / "test.sqlite3"))
    monkeypatch.setenv("TOUCHLINE_SCHEDULER", "0")
    for name in (
        "ODDS_API_KEY",
        "PUSHOVER_APP_TOKEN",
        "PUSHOVER_USER_KEY",
        "TOUCHLINE_ADMIN_TOKEN",
        "ODDS_MAX_REQUESTS_PER_DAY",
    ):
        monkeypatch.delenv(name, raising=False)


def make_results(count=120, seed=1, end="2026-01-01T15:00:00+00:00"):
    """Synthetic round-robin results; 'arsenal' is strongest, 'villa' weakest."""
    rng = random.Random(seed)
    strength = {team: 1.0 - 0.15 * i for i, team in enumerate(TEAMS)}
    start = datetime.fromisoformat(end) - timedelta(days=3 * count)
    results = []
    for i in range(count):
        home, away = rng.sample(TEAMS, 2)
        lam = 1.4 * strength[home] / strength[away] ** 0.5
        mu = 1.1 * strength[away] / strength[home] ** 0.5
        hg = sum(rng.random() < lam / 6 for _ in range(6))
        ag = sum(rng.random() < mu / 6 for _ in range(6))
        kickoff = (start + timedelta(days=3 * i)).astimezone(UTC).isoformat(timespec="seconds")
        results.append(
            {"id": f"E0:{i}", "home": home, "away": away, "kickoff": kickoff, "hg": hg, "ag": ag}
        )
    return results


@pytest.fixture
def results():
    return make_results()
