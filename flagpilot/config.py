"""Shared names and settings. The app, simulator and provisioner must agree on these."""

import json
import os
import tomllib
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
    """What provisioning, lifecycle and the simulator act on. The metric is shared."""

    flag: str
    experiment: str
    hypothesis: str
    description: str
    # The metric counts every purchase event, so targets must never share identifiers.
    user_prefix: str
    variant_key: str = VARIANT_KEY
    variant_value: str = VARIANT_VALUE


CHECKOUT = Target(
    FLAG_NAME, EXPERIMENT_NAME, HYPOTHESIS,
    "Checkout button copy (Flag Pilot experiment)", "sim-user",
)
REHEARSAL = Target(
    "flagpilot-rehearsal", "flagpilot-rehearsal",
    "Rehearsal of the ship flow on a throwaway flag, with simulated users.",
    "Throwaway flag to rehearse flagpilot ship. Archive after the demo.", "rehearsal-user",
)


def load_targets(path: Path, builtin: dict[str, Target]) -> dict[str, Target]:
    """The built-in targets plus any `[targets.<name>]` tables in flagpilot.toml."""
    targets = dict(builtin)
    for name, table in tomllib.loads(path.read_text()).get("targets", {}).items():
        if name in targets:
            raise ValueError(f"target '{name}' is already built in")
        targets[name] = Target(**table)  # a missing or unknown key is an error
    for name, target in targets.items():
        if target.variant_key == CONTROL_VALUE or target.variant_value == CONTROL_VALUE:
            raise ValueError(f"target '{name}': '{CONTROL_VALUE}' is reserved")
        for other_name, other in targets.items():
            if name != other_name and (target.flag == other.flag
                                       or target.user_prefix.startswith(other.user_prefix)):
                raise ValueError(f"targets '{name}' and '{other_name}' share a flag or users")
    return targets


TARGETS = load_targets(ROOT / "flagpilot.toml", {"checkout": CHECKOUT, "rehearsal": REHEARSAL})


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
