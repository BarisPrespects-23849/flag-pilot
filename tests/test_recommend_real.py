"""Against the real experiment 570 payloads."""

import json

import pytest

from flagpilot import card, main, recommend, settings
from tests import real_570

SETTINGS = settings.load()


def decision():
    return recommend.decide(*real_570.load(), SETTINGS)


def rules(result):
    return {r["rule"]: r for r in result["rules"]}


def test_verdict_and_ship_call():
    result = decision()
    assert result["verdict"] == "SHIP_VARIANT"
    assert (result["winner"], result["variant_option_id"], result["winner_value"]) == (
        "buy_now", 37071, "buy_now")
    assert all(r["passed"] for r in result["rules"])
    assert result["ship_call"]["body"] == {"rollout_decision": "variant", "rollout_variant": 37071}
    assert "<env_key>" in result["ship_call"]["path"]


def test_numbers_come_from_the_payload():
    found = rules(decision())
    assert found["sample_size"]["value"] == 287
    assert found["conversions"]["value"] == 19
    assert found["excluded_identities"]["value"] == 0
    assert found["chance_to_win"]["value"] == pytest.approx(0.988585, abs=1e-6)
    # srm_p_value is null in the real payload, so Flag Pilot computes it: chi2 = 1.1267, df 1
    assert found["srm"]["source"] == "flagpilot"
    assert found["srm"]["value"] == pytest.approx(0.2885, abs=1e-3)


def test_card_is_deterministic_and_complete():
    text = card.render(decision())
    assert text == card.render(decision())
    for expected in (
        "VERDICT: SHIP_VARIANT", "98.9%", '"rollout_variant": 37071', "/experiments/570",
        "the flag's default value stays control for unidentified users until cleanup",
    ):
        assert expected in text
    assert "FAIL" not in text


def test_json_output_is_one_compact_object(monkeypatch, capsys):
    monkeypatch.setattr(recommend, "fetch", lambda experiment_id: real_570.load())
    monkeypatch.setattr(recommend, "refresh", lambda *a: pytest.fail("refreshed without --refresh"))
    assert main.main(["recommend", "570", "--json"]) == 0
    output = capsys.readouterr().out
    assert output.count("\n") == 1
    assert json.loads(output)["verdict"] == "SHIP_VARIANT"
