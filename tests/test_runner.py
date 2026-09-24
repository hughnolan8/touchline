from backend import runner


def test_run_once_initializes_then_runs_a_tick(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr('backend.app.store.configure', lambda: calls.append('configure'))
    monkeypatch.setattr('backend.app.store.initialize', lambda: calls.append('initialize'))
    monkeypatch.setattr('backend.app.engine.tick', lambda: calls.append('tick') or {'refreshed': 1})
    assert runner.run_once('engine') == 0
    assert calls == ['configure', 'initialize', 'tick']
    assert '"event": "engine_cycle"' in capsys.readouterr().out


def test_supervise_runs_one_completed_cycle_then_waits_for_stop():
    launched = []

    class Process:
        returncode = 0

        def poll(self):
            return self.returncode

    class Stop:
        stopped = False

        def is_set(self):
            return self.stopped

        def wait(self, seconds):
            self.stopped = True
            return True

    runner.supervise('engine', Stop(), interval=60, launch=lambda *args, **kwargs: launched.append((args, kwargs)) or Process(), monotonic=lambda: 0)
    assert launched[0][0][0][-2:] == ['--mode', 'engine']
