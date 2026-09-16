"""Railway engine supervisor: isolated jobs, bounded runtime and graceful shutdown."""
import argparse
import json
import logging
import os
import signal
import subprocess
import sys
import threading
import time


def run_once(mode):
    from backend.mobile.store import configure, initialize
    from backend.mobile.engine import tick
    configure()
    initialize()
    result = tick()
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
            logging.error(json.dumps({'event': 'engine_timeout', 'mode': mode, 'timeout_seconds': timeout}))
        elif process.returncode and not stop.is_set():
            logging.error(json.dumps({'event': 'engine_cycle_failed', 'mode': mode, 'exit_code': process.returncode}))
        # Missed windows are skipped: never launch a burst of overdue provider calls.
        remaining = max(1, interval - ((monotonic() - started) % interval))
        stop.wait(remaining)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=('engine',), default='engine')
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    # Provider URLs contain query-string credentials. Never log HTTP request URLs.
    logging.getLogger('httpx').setLevel(logging.WARNING)
    logging.getLogger('httpcore').setLevel(logging.WARNING)
    if args.once:
        try:
            return run_once(args.mode)
        except Exception as exc:
            # Exception messages from database/HTTP clients can contain credentials.
            logging.error(json.dumps({'event': 'engine_unavailable', 'mode': args.mode, 'error_type': type(exc).__name__}))
            return 1
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    supervise(args.mode, stop)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
