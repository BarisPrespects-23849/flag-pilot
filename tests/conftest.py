import sys

import pytest

from flagpilot import audit, lifecycle
from flagpilot import flagsmith_cli as cli


@pytest.fixture(autouse=True)
def isolate(monkeypatch, tmp_path):
    """No test may write the real audit log or state file, or run the real CLI."""
    monkeypatch.setattr(audit, "AUDIT_PATH", tmp_path / "audit.jsonl")
    monkeypatch.setattr(lifecycle, "STATE_PATH", tmp_path / "state.json")

    real_run = cli.subprocess.run

    def guarded(command, *args, **kwargs):
        # Local git and the test interpreter are fine; Flagsmith, GitHub and pushes
        # through them are not.
        if command[0] not in ("git", sys.executable):
            raise AssertionError(f"test tried to run: {command[:3]}")
        return real_run(command, *args, **kwargs)

    monkeypatch.setattr(cli.subprocess, "run", guarded)
