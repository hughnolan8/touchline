from backend.db import connect, now
from backend.app.reset import reset_simulation_data
from backend.providers import ingest_match


def test_reset_simulation_data_removes_football_state_but_keeps_settings():
    with connect() as connection:
        ingest_match(connection, 'understat', '1', 'E0', 'Arsenal', 'Chelsea', '2026-08-01T12:00:00+00:00', True, 'scheduled', {}, now())
        connection.execute("INSERT INTO models(competition,created_at,cutoff,samples,payload,metrics) VALUES('E0',?,?,?,?,?)", (now(), now(), 1, '{}', '{}'))
        connection.execute("INSERT INTO settings VALUES('bootstrap_complete','true')")
        connection.execute("INSERT INTO settings VALUES('refreshed:fixture','true')")
        reset_simulation_data(connection)
        assert connection.execute('SELECT COUNT(*) FROM matches').fetchone()[0] == 0
        assert connection.execute('SELECT COUNT(*) FROM models').fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM settings WHERE key='refreshed:fixture'").fetchone()[0] == 0
        assert connection.execute("SELECT value FROM settings WHERE key='understat_cutover_complete'").fetchone()[0] == 'true'
