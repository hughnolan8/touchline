from backend import postgres


def test_sql_translates_sqlite_placeholders_conflicts_and_fixture_window():
    sql = postgres._sql("INSERT OR IGNORE INTO matches VALUES(?, ?) WHERE abs(julianday(kickoff)-julianday(?))<2")
    assert 'INSERT INTO matches' in sql
    assert sql.count('%s') == 3
    assert 'EXTRACT(EPOCH' in sql


def test_cursor_returns_inserted_ids_and_row_supports_numeric_indexing():
    class RawCursor:
        def __init__(self):
            self.statement = None

        def execute(self, statement, params):
            self.statement = statement

        def fetchone(self):
            return {'id': 7, 'name': 'Arsenal'}

        def fetchall(self):
            return [{'id': 8, 'name': 'Chelsea'}]

    raw = RawCursor()
    cursor = postgres.Cursor(raw).execute('INSERT INTO bets(portfolio) VALUES(?)', ('automatic',))
    assert cursor.lastrowid == 7
    assert 'RETURNING id' in raw.statement
    assert postgres.Row({'id': 7, 'name': 'Arsenal'})[0] == 7
    assert cursor.fetchall() == [{'id': 8, 'name': 'Chelsea'}]


def test_connect_commits_on_success_and_rolls_back_on_error(monkeypatch):
    class Raw:
        committed = rolled_back = closed = False

        def commit(self):
            self.committed = True

        def rollback(self):
            self.rolled_back = True

        def close(self):
            self.closed = True

    raw = Raw()
    monkeypatch.setenv('DATABASE_URL', 'postgresql://example.test/touchline')
    monkeypatch.setattr(postgres.psycopg, 'connect', lambda *args, **kwargs: raw)
    with postgres.connect() as connection:
        assert isinstance(connection, postgres.Connection)
    assert raw.committed and raw.closed
