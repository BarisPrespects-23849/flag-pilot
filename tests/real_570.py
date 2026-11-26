"""REAL payloads read from experiment 570 on 2026-11-26 (traffic was simulated by us)."""

import json
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"


def load() -> tuple[dict, dict, dict]:
    """Fresh copies of (experiment, exposures, results)."""
    return tuple(
        json.loads((FIXTURES / f"570_{name}.json").read_text())
        for name in ("experiment", "exposures", "results")
    )
