import pytest

from touchline import cli, strategy
from touchline.db import connect


def test_promote_xi_requires_evidence():
    with pytest.raises(SystemExit, match="not eligible"):
        cli.main(["promote", "--league", "E0", "--model", "xi-v2"])
    cli.main(["promote", "--league", "E0", "--model", "xi-v2", "--force"])
    with connect() as conn:
        assert strategy.load(conn, "E0").active_model == "xi-v2"


def test_reset_needs_confirm():
    with pytest.raises(SystemExit):
        cli.main(["reset"])
