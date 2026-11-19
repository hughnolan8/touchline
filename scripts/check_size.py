"""Warn (never fail) when a module grows past 200 lines, so files stay cheap to read."""

from pathlib import Path

LIMIT = 200
for path in sorted(Path("touchline").rglob("*.py")):
    lines = len(path.read_text().splitlines())
    if lines > LIMIT:
        print(f"::warning file={path}::{path} has {lines} lines (> {LIMIT}); consider splitting")
