import json
from pathlib import Path

FIXTURES = Path(__file__).with_name("fixtures")


def load(name: str):
    return json.loads((FIXTURES / name).read_text())
