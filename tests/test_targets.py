"""The rehearsal must never reach the checkout flag, its experiment or its users."""

import json

import pytest

from flagpilot import config, lifecycle, provision, simulate

EXPERIMENTS = [
    {"id": 570, "name": config.EXPERIMENT_NAME, "feature": config.FLAG_NAME, "status": "running"},
    {"id": 9, "name": "flagpilot-rehearsal", "feature": "flagpilot-rehearsal",
     "status": "running"},
]


@pytest.mark.parametrize("module", [provision, lifecycle, simulate])
def test_the_command_line_requires_a_target(module):
    argv = {provision: ["flag"], lifecycle: ["start"], simulate: []}[module]
    with pytest.raises(SystemExit):
        module.main(argv)


def test_rehearsal_plans_name_only_the_rehearsal_flag(monkeypatch):
    monkeypatch.setattr(provision, "find_feature", lambda target: None)
    flag = provision.plan_flag(config.REHEARSAL)
    assert "flagpilot-rehearsal" in flag.args and config.FLAG_NAME not in flag.args

    monkeypatch.setattr(provision, "find_feature", lambda target: {"id": 1})
    variant = provision.plan_variant(config.REHEARSAL)
    assert "flagpilot-rehearsal" in variant.args and config.FLAG_NAME not in variant.args


def test_lifecycle_picks_the_targets_experiment(monkeypatch):
    monkeypatch.setattr(provision, "experiments", lambda: EXPERIMENTS)
    assert lifecycle.current_experiment(config.REHEARSAL)["id"] == 9


def test_simulator_uses_the_rehearsal_users(capsys, tmp_path):
    assert simulate.main(["--target", "rehearsal", "--users", "3"]) == 0
    out = capsys.readouterr().out
    assert "rehearsal-user-00001" in out and "sim-user" not in out
    assert config.FLAG_NAME not in out
    entry = json.loads((tmp_path / "audit.jsonl").read_text())
    assert entry["path"] == "simulate flagpilot-rehearsal"


def test_simulator_refuses_another_targets_users():
    with pytest.raises(SystemExit):
        simulate.main(["--target", "rehearsal", "--prefix", "sim-user", "--users", "3"])
