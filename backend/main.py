"""Railway entrypoint for the Touchline web dashboard and API."""
from backend.mobile.api import create_app
app = create_app()
