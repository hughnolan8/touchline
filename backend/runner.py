"""Railway engine supervisor: isolated jobs, bounded runtime and graceful shutdown."""
import argparse
import json
import os
import signal
import subprocess
import sys
import threading
import time
from backend.log import configure, event


def run_once(mode):
    from backend.app.store import configure, initialize
    from backend.app.engine import tick
    configure()
    initialize()
    event('engine_cycle_started', mode=mode)
    result = tick()
    event('engine_cycle_finished', mode=mode, **result)
    print(json.dumps({'event': 'engine_cycle', 'mode': mode, **result}), flush=True)
    return 1 if result.get('errors') else 0


def supervise(mode, stop, interval=300, timeout=None, launch=subprocess.Popen, monotonic=time.monotonic):
    timeout = timeout or 240
    while not stop.is_set():
        started = monotonic()
        process = launch([sys.executable, '-m', 'backend.runner', '--once', '--mode', mode], start_new_session=True)
        timed_out = False
        while process.poll() is None:
            if stop.wait(1) or monotonic() - started >= timeout:
                timed_out = not stop.is_set()
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                break
        if timed_out:
            event('engine_timeout', 40, mode=mode, timeout_seconds=timeout)
        elif process.returncode and not stop.is_set():
            event('engine_cycle_failed', 40, mode=mode, exit_code=process.returncode)
        # Missed windows are skipped: never launch a burst of overdue provider calls.
        remaining = max(1, interval - ((monotonic() - started) % interval))
        stop.wait(remaining)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=('engine',), default='engine')
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    configure()
    if args.once:
        try:
            return run_once(args.mode)
        except Exception as exc:
            # Exception messages from database/HTTP clients can contain credentials.
            event('engine_unavailable', 40, mode=args.mode, error_type=type(exc).__name__)
            return 1
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    supervise(args.mode, stop)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
