import subprocess
from datetime import datetime, timedelta, timezone
from backend import runner
from backend.db import connect, now, set_setting
from backend.mobile.engine import enqueue, claim, training_tick
from test_mobile import client


def test_engine_health_requires_recent_completion(client):
    assert client.get('/health/engine').status_code == 503
    with connect() as c:
        set_setting(c, 'mobile_last_success', now())
    assert client.get('/health/engine').status_code == 200
    with connect() as c:
        set_setting(c, 'mobile_last_success', (datetime.now(timezone.utc)-timedelta(minutes=16)).isoformat())
    assert client.get('/health/engine').status_code == 503


def test_training_and_engine_claim_separate_jobs():
    with connect() as c:
        enqueue(c, 'train:test', 'train', {}, 0, now())
        enqueue(c, 'file:test', 'file', {}, 1, now())
    assert claim(now(), training=False)['kind'] == 'file'
    assert claim(now(), training=True)['kind'] == 'train'
    assert claim(now(), training=False) is None


def test_training_failure_is_persisted_and_lease_released(monkeypatch):
    with connect() as c:
        enqueue(c, 'train:test', 'train', {}, 0, now())
    def fail(_):
        raise TimeoutError('secret must not appear')
    monkeypatch.setattr('backend.mobile.engine.run_job', fail)
    assert training_tick()['errors'] == 1
    with connect() as c:
        job = c.execute('SELECT * FROM mobile_jobs').fetchone()
        assert job['status'] == 'queued'
        assert job['attempts'] == 1
        assert 'secret' not in job['message']
        assert c.execute('SELECT 1 FROM mobile_leases').fetchone() is None


class Stop:
    stopped = False
    def is_set(self):
        return self.stopped
    def wait(self, duration):
        if duration > 1:
            self.stopped = True
        return self.stopped


def test_supervisor_kills_hung_process_and_waits_before_retry():
    class Child:
        returncode = None
        terminated = False
        killed = False
        def poll(self): return None
        def terminate(self): self.terminated = True
        def kill(self): self.killed = True; self.returncode = -9
        def wait(self, timeout=None):
            if timeout:
                raise subprocess.TimeoutExpired('child', timeout)
    child = Child()
    commands = []
    def launch(command, **kwargs):
        commands.append(command)
        return child
    clock = iter([0, 241, 251])
    runner.supervise('engine', Stop(), launch=launch, monotonic=lambda: next(clock))
    assert child.terminated and child.killed
    assert len(commands) == 1
    assert commands[0][-1] == 'engine'


def test_supervisor_shutdown_terminates_active_child():
    class Shutdown(Stop):
        def wait(self, duration):
            self.stopped = True
            return True
    class Child:
        returncode = None
        terminated = False
        def poll(self): return None
        def terminate(self): self.terminated = True
        def wait(self, timeout=None): self.returncode = -15
    child = Child()
    runner.supervise('trainer', Shutdown(), launch=lambda *a, **k: child)
    assert child.terminated
