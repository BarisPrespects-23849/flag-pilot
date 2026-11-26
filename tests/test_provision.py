import pytest

from flagpilot import config, provision


@pytest.fixture
def calls(monkeypatch, tmp_path):
    monkeypatch.setattr(provision.audit, "AUDIT_PATH", tmp_path / "audit.jsonl")
    made = []
    monkeypatch.setattr(provision.cli, "run", lambda args, **kw: made.append(args) or {"id": 9})
    return made


PLAN = provision.Plan(action="x", method="CLI", args=["feature", "create", "f"])


def test_dry_run_makes_no_call(calls):
    provision.execute(PLAN, apply=False, approved_by=None)
    assert calls == []


def test_apply_makes_one_call(calls):
    provision.execute(PLAN, apply=True, approved_by="test")
    assert calls == [PLAN.args]


def test_apply_requires_an_approver(calls):
    with pytest.raises(SystemExit):
        provision.main(["flag", "--apply"])
    assert calls == []


def test_experiment_is_blocked_while_prerequisites_are_missing(monkeypatch):
    monkeypatch.setattr(provision, "find_feature", lambda: None)
    monkeypatch.setattr(provision, "find_metric", lambda: None)
    with pytest.raises(provision.Blocked):
        provision.plan_experiment()


def test_experiment_plan_never_starts_it(monkeypatch):
    monkeypatch.setattr(provision, "find_feature", lambda: {
        "id": 1, "multivariate_options": [{"id": 2, "key": config.VARIANT_KEY}]})
    monkeypatch.setattr(provision, "find_metric", lambda: {
        "id": 3, "definition": {"event": config.CONVERSION_EVENT}})
    monkeypatch.setattr(provision, "experiments", lambda: [])
    plan = provision.plan_experiment()
    assert "start" not in plan.path
    assert plan.tier == 2  # its rollout is served before the experiment starts
    assert plan.body["metrics"] == [{"metric": 3, "expected_direction": "increase"}]
