"""Shared names and settings. The app, simulator and provisioner must agree on these."""

import json
import os
from dataclasses import dataclass
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


@dataclass(frozen=True)
class Target:
    """What provisioning, lifecycle and the simulator act on. Variant and metric are shared."""

    flag: str
    experiment: str
    hypothesis: str
    description: str
    # The metric counts every purchase event, so targets must never share identifiers.
    user_prefix: str


CHECKOUT = Target(
    FLAG_NAME, EXPERIMENT_NAME, HYPOTHESIS,
    "Checkout button copy (Flag Pilot experiment)", "sim-user",
)
REHEARSAL = Target(
    "flagpilot-rehearsal", "flagpilot-rehearsal",
    "Rehearsal of the ship flow on a throwaway flag, with simulated users.",
    "Throwaway flag to rehearse flagpilot ship. Archive after the demo.", "rehearsal-user",
)
TARGETS = {"checkout": CHECKOUT, "rehearsal": REHEARSAL}


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
