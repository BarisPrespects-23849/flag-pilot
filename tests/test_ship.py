"""Ship flow on the real 570 payloads. Flagsmith itself is faked: nothing is called.

The post-ship evaluations and statuses below are SYNTHETIC.
"""

import json

import pytest

from flagpilot import audit, recommend, settings, ship
from tests import real_570

SETTINGS = settings.load()
NAME = "checkout-button-buy-now"


@pytest.fixture
def flagsmith(monkeypatch):
    state = {"data": real_570.load(), "status": "running", "calls": [], "served": "buy_now",
             "complete_error": None}
    monkeypatch.setattr(recommend, "fetch", lambda experiment_id: state["data"])
    monkeypatch.setattr(ship, "read_status", lambda experiment_id: state["status"])
    monkeypatch.setattr(ship, "evaluate", lambda flag, identity: state["served"])

    def run(args, body=None, jq="."):
        state["calls"].append((args, body))
        if state["complete_error"]:
            raise state["complete_error"]
        state["status"] = "completed"
        return {"id": 570}

    monkeypatch.setattr(ship.provision.cli, "run", run)
    clock = iter(range(0, 10_000, 30))
    verify = ship.verify
    monkeypatch.setattr(ship, "verify", lambda *a: verify(
        *a, sleep=lambda s: None, clock=lambda: next(clock)))
    return state


def logged():
    return [json.loads(line) for line in audit.AUDIT_PATH.read_text().splitlines()]


def apply(**kwargs):
    return ship.ship(570, SETTINGS, apply=True,
                     **{"confirm": NAME, "expect_winner": "buy_now", **kwargs})


def test_dry_run_changes_nothing(flagsmith, capsys):
    assert ship.ship(570, SETTINGS, apply=False) == ship.OK
    assert flagsmith["calls"] == []
    output = capsys.readouterr().out
    assert '{"rollout_decision": "variant", "rollout_variant": 37071}' in output
    assert [e["action"] for e in logged()] == ["ship_recommend", "experiment_complete"]
    assert all(e["dry_run"] for e in logged())


def test_apply_ships_verifies_and_audits_every_step(flagsmith, capsys):
    assert apply() == ship.OK
    [(args, body)] = flagsmith["calls"]
    assert args[1].endswith("experiments/570/complete/")
    assert body == {"rollout_decision": "variant", "rollout_variant": 37071}
    assert [e["action"] for e in logged()] == [
        "ship_recommend", "ship_status_check", "experiment_complete", "ship_verify"]
    assert logged()[2]["tier"] == 3 and logged()[2]["approved_by"] == "user"
    output = capsys.readouterr().out
    assert "10/10" in output and "Run cleanup to make it permanent" in output


@pytest.mark.parametrize("kwargs", [
    {"confirm": "yes"},
    {"confirm": NAME.upper()},
    {"confirm": f"{NAME} "},
    {"expect_winner": None},
    {"expect_winner": "control"},
])
def test_apply_refuses_without_exact_approval(flagsmith, kwargs):
    assert apply(**kwargs) == ship.REFUSED
    assert flagsmith["calls"] == []
    assert logged()[-1]["action"] == "ship_refused"


def test_apply_prompts_for_the_name_on_a_terminal(flagsmith, monkeypatch):
    monkeypatch.setattr(ship.sys.stdin, "isatty", lambda: True, raising=False)
    assert ship.ship(570, SETTINGS, apply=True, prompt=lambda text: "no") == ship.REFUSED
    assert flagsmith["calls"] == []
    assert ship.ship(570, SETTINGS, apply=True, prompt=lambda text: NAME) == ship.OK


def test_apply_without_a_terminal_or_confirm_is_refused(flagsmith, monkeypatch):
    monkeypatch.setattr(ship.sys.stdin, "isatty", lambda: False, raising=False)
    assert ship.ship(570, SETTINGS, apply=True, prompt=pytest.fail) == ship.REFUSED
    assert flagsmith["calls"] == []


@pytest.mark.parametrize("apply_flag", [False, True])
def test_refuses_when_a_rule_fails(flagsmith, apply_flag):
    flagsmith["data"][2]["payload"]["metrics"][0]["inference"]["buy_now"]["chance_to_win"] = 0.5
    assert ship.ship(570, SETTINGS, apply=apply_flag, confirm=NAME,
                     expect_winner="buy_now") == ship.REFUSED
    assert flagsmith["calls"] == []


def test_status_is_rechecked_right_before_the_call(flagsmith):
    flagsmith["status"] = "completed"  # changed after the recommendation was read
    assert apply() == ship.REFUSED
    assert flagsmith["calls"] == []


def test_failed_complete_is_reported_and_not_retried(flagsmith, capsys):
    flagsmith["complete_error"] = TimeoutError("synthetic")
    assert apply() == ship.FAILED
    assert len(flagsmith["calls"]) == 1
    assert "Do not retry blindly" in capsys.readouterr().err
    assert logged()[-1]["status"] == "failed"


def test_rollout_that_never_arrives_is_not_reported_as_shipped(flagsmith, capsys):
    flagsmith["served"] = "control"
    assert apply() == ship.FAILED
    output = capsys.readouterr()
    assert "0/10" in output.out and "NOT VERIFIED" in output.err
    assert "Shipped" not in output.out
