"""Small, credential-safe structured logging helpers for Railway."""
import json
import logging


def configure():
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    logging.getLogger('touchline').setLevel(logging.INFO)
    # Third-party clients can include credential-bearing URLs in their logs.
    logging.getLogger('httpx').setLevel(logging.WARNING)
    logging.getLogger('httpcore').setLevel(logging.WARNING)


def event(name, level=logging.INFO, **fields):
    print(json.dumps({'event': name, 'severity': logging.getLevelName(level).lower(), **fields}, default=str, separators=(',', ':')), flush=True)
