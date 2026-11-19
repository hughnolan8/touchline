"""Optional Pushover alerts. Returns False (never raises) when unconfigured or failing."""

import logging

import httpx

from touchline.config import config

URL = "https://api.pushover.net/1/messages.json"


def configured() -> bool:
    cfg = config()
    return bool(cfg.pushover_token and cfg.pushover_user)


def send(title: str, message: str) -> bool:
    cfg = config()
    if not configured():
        return False
    data = {
        "token": cfg.pushover_token,
        "user": cfg.pushover_user,
        "title": title,
        "message": message,
    }
    if cfg.pushover_device:
        data["device"] = cfg.pushover_device
    if cfg.dashboard_url:
        data |= {"url": cfg.dashboard_url, "url_title": "Open Touchline"}
    try:
        httpx.post(URL, data=data, timeout=10).raise_for_status()
        return True
    except httpx.HTTPError as error:
        logging.warning("pushover failed: %s", type(error).__name__)
        return False
