"""Thresholds from flagpilot.toml."""

import tomllib
from pathlib import Path

from flagpilot.config import ROOT

SETTINGS_PATH = ROOT / "flagpilot.toml"


def load(path: Path | None = None) -> dict:
    settings = tomllib.loads((path or SETTINGS_PATH).read_text())
    gates = settings["gates"]
    if not 0 <= gates["ship_control_chance"] < gates["ship_variant_chance"] <= 1:
        raise ValueError("Need 0 <= ship_control_chance < ship_variant_chance <= 1.")
    return settings
