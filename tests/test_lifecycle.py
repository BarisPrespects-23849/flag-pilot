from datetime import datetime, timedelta, timezone

import pytest

from flagpilot import config, lifecycle, provision


@pytest.fixture
def api(monkeypatch, tmp_path):
    monkeypatch.setattr(lifecycle, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(provision.audit, "AUDIT_PATH", tmp_path / "audit.jsonl")
    state = {"status": "running", "warehouse": ["pending_connection"], "calls": []}
    monkeypatch.setattr(provision, "experiments", lambda: [{
        "id": 7, "name": config.EXPERIMENT_NAME, "feature": config.FLAG_NAME,
        "status": state["status"]}])
    monkeypatch.setattr(lifecycle.cli, "get", lambda *a, **k: state["warehouse"])
    monkeypatch.setattr(provision.cli, "status_only",
                        lambda args: state["calls"].append(args) or {"http_status": 202})
    return state


def test_start_needs_a_warehouse_connection(api):
    api["status"] = "created"
    assert lifecycle.plan("start").tier == 2
    api["warehouse"] = []
    with pytest.raises(provision.Blocked):
        lifecycle.plan("start")


def test_refresh_is_blocked_before_start(api):
    api["status"] = "created"
    with pytest.raises(provision.Blocked):
        lifecycle.plan("results-refresh")


def test_results_refresh_is_limited_to_once_per_five_minutes(api):
    lifecycle.run("results-refresh", apply=True, approved_by="test")
    assert len(api["calls"]) == 1
    with pytest.raises(provision.Blocked):
        lifecycle.run("results-refresh", apply=True, approved_by="test")
    assert len(api["calls"]) == 1
    later = datetime.now(timezone.utc) + timedelta(minutes=5, seconds=1)
    assert lifecycle.seconds_until_refresh_allowed(7, later) == 0


def test_dry_run_does_not_start_the_rate_limit(api):
    lifecycle.run("results-refresh", apply=False, approved_by=None)
    assert api["calls"] == [] and lifecycle.load_state() == {}
