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


def test_a_target_from_the_toml_uses_its_own_variant(monkeypatch, capsys, tmp_path):
    dress = config.TARGETS["dress"]
    assert (dress.flag, dress.variant_key) == ("flagpilot-dress", "new")
    monkeypatch.setattr(provision, "find_feature", lambda target: {
        "id": 1, "multivariate_options": [{"id": 4, "key": "new"}]})
    monkeypatch.setattr(provision, "find_metric", lambda: {
        "id": 3, "definition": {"event": config.CONVERSION_EVENT}})
    monkeypatch.setattr(provision, "experiments", lambda: [])
    body = provision.plan_experiment(dress).body
    [allocation] = body["experiment_rollout"]["multivariate_feature_state_values"]
    assert allocation["multivariate_feature_option"] == 4
    with pytest.raises(provision.Blocked, match="'new' already exists"):
        provision.plan_variant(dress)

    monkeypatch.setattr(provision, "find_feature", lambda target: {"id": 1})
    args = provision.plan_variant(dress).args
    assert args[args.index("--key") + 1] == args[args.index("--value") + 1] == "new"

    assert simulate.main(["--target", "dress", "--users", "3"]) == 0
    out = capsys.readouterr().out
    assert "'new': 0.16" in out and "buy_now" not in out and "dress-user-00001" in out


@pytest.mark.parametrize("change, reason", [
    ({"user_prefix": "sim-user"}, "share a flag or users"),
    ({"user_prefix": "sim-user-2"}, "share a flag or users"),
    ({"flag": config.FLAG_NAME}, "share a flag or users"),
    ({"variant_key": "control"}, "reserved"),
    ({"extra": "x"}, "unexpected keyword"),
])
def test_unsafe_toml_targets_are_rejected(tmp_path, change, reason):
    table = {"flag": "f", "experiment": "e", "hypothesis": "h", "description": "d",
             "user_prefix": "p", **change}
    path = tmp_path / "t.toml"
    path.write_text("[targets.x]\n" + "".join(f'{k} = "{v}"\n' for k, v in table.items()))
    with pytest.raises((ValueError, TypeError), match=reason):
        config.load_targets(path, {"checkout": config.CHECKOUT})
