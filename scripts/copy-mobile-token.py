"""Copy the iPhone owner token from Railway to the Mac clipboard without printing it."""
import json
import os
from pathlib import Path
import shutil
import subprocess

root = Path(__file__).resolve().parents[1]
config = json.loads((root / "data/mobile/railway.json").read_text())

# Allow a short-lived environment variable for CI or an explicitly supplied token.
token = os.environ.get("MOBILE_OWNER_TOKEN")
if not token:
    cli = os.environ.get("RAILWAY_CLI") or shutil.which("railway")
    if not cli:
        raise SystemExit(
            "MOBILE_OWNER_TOKEN is not set and the Railway CLI was not found. "
            "Install it, run `railway login`, then try again."
        )
    try:
        result = subprocess.run(
            [
                cli,
                "variable",
                "list",
                "--kv",
                "--project",
                config["project_id"],
                "--environment",
                config["environment_id"],
                "--service",
                config["services"]["api"],
            ],
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError:
        raise SystemExit(
            "Unable to read the Railway API variables. Run `railway login` and make "
            "sure your account can access this project."
        )
    values = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
    token = values.get("MOBILE_OWNER_TOKEN")

if not token:
    raise SystemExit(
        "MOBILE_OWNER_TOKEN is not configured on the Railway api service. Add it in "
        "Railway, redeploy the api service, then run this command again."
    )

subprocess.run(["pbcopy"], input=token, text=True, check=True)
print("iPhone owner token copied. Paste it into Touchline; keep it private.")
