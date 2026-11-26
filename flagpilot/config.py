"""Shared names and settings. The app, simulator and provisioner must agree on these."""

import json
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent

FLAG_NAME = "checkout_button"
CONTROL_VALUE = "control"
VARIANT_VALUE = "buy_now"
VARIANT_KEY = "buy_now"
CONVERSION_EVENT = "purchase"  # case-sensitive; must match the metric definition

METRIC_NAME = "checkout-purchase"
EXPERIMENT_NAME = "checkout-button-buy-now"
HYPOTHESIS = "A 'Buy now' checkout button increases the share of users who purchase."


def project_config() -> dict:
    """Project id and client-side environment key from flagsmith.json (not secret)."""
    return json.loads((ROOT / "flagsmith.json").read_text())


def server_key() -> str:
    """Server-side SDK key from .env. Never include its value in output or errors."""
    load_dotenv(ROOT / ".env")
    key = os.environ.get("FLAGSMITH_SERVER_KEY", "")
    if not key.startswith("ser.") or key == "ser.your-key-here":
        raise RuntimeError(
            "FLAGSMITH_SERVER_KEY is missing or not a server-side key. Add it to .env."
        )
    return key
