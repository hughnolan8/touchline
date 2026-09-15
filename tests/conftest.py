import pytest
from backend.mobile.store import initialize as init
@pytest.fixture(autouse=True)
def isolated_db(tmp_path,monkeypatch):
    monkeypatch.delenv('DATABASE_URL', raising=False)
    monkeypatch.delenv('MOBILE_DATABASE_URL', raising=False)
    monkeypatch.setenv('ENGINE_DB',str(tmp_path/'test.sqlite3'));init()
