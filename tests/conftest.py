import pytest

from flagpilot import audit, lifecycle
from flagpilot import flagsmith_cli as cli


@pytest.fixture(autouse=True)
def isolate(monkeypatch, tmp_path):
    """No test may write the real audit log or state file, or run the real CLI."""
    monkeypatch.setattr(audit, "AUDIT_PATH", tmp_path / "audit.jsonl")
    monkeypatch.setattr(lifecycle, "STATE_PATH", tmp_path / "state.json")

    def no_cli(command, **kwargs):
        raise AssertionError(f"test tried to run: {command[:3]}")

    monkeypatch.setattr(cli.subprocess, "run", no_cli)
