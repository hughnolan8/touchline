"""Railway entrypoint for the Touchline web dashboard and API."""
from backend.app.api import create_app
app = create_app()
