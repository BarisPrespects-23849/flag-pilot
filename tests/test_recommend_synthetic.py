"""SYNTHETIC CASES. Every number here is invented to exercise one rule in isolation.

Nothing in this file is an experiment result, and none of it may be demoed.
Each case starts from the real 570 payload shape and overwrites values.
"""

import pytest

from flagpilot import card, recommend, settings, stats
from tests import real_570

SETTINGS = settings.load()


def synthetic(*, control=(300, 30), variant=(300, 60), chance=0.99, srm=None, excluded=0,
              status="running", exposures=None, direction="up"):
    experiment, exposure_data, results = real_570.load()
    experiment["status"] = status
    experiment["metrics"][0]["direction"] = direction
    metric = results["payload"]["metrics"][0]
    for arm, (n, conversions) in (("control", control), ("buy_now", variant)):
        metric["variants"][arm] = {"n": n, "sum": conversions, "sum_squares": conversions}
    metric["inference"]["buy_now"]["chance_to_win"] = chance
    results["payload"]["srm_p_value"] = srm
    exposure_data["payload"]["excluded_identities"] = excluded
    counts = exposures or (control[0], variant[0])
    exposure_data["payload"]["timeseries"]["points"] = [
        {"bucket": "synthetic", "new_identities": {"control": counts[0], "buy_now": counts[1]}}]
    return experiment, exposure_data, results


def decide(**case):
    return recommend.decide(*synthetic(**case), SETTINGS)


def failed(result):
    return [r["rule"] for r in result["rules"] if not r["passed"]]


def test_synthetic_baseline_passes():
    assert decide()["verdict"] == "SHIP_VARIANT"


@pytest.mark.parametrize("case, rule", [
    ({"control": (49, 10), "exposures": (300, 300)}, "sample_size"),
    ({"variant": (300, 4)}, "conversions"),
    ({"exposures": (200, 400)}, "srm"),
    ({"srm": 0.0005}, "srm"),
    ({"excluded": 7}, "excluded_identities"),
    ({"status": "completed"}, "status"),
    ({"status": "created"}, "status"),
    ({"direction": "down"}, "metric_supported"),
])
def test_one_failing_rule_blocks_shipping(case, rule):
    result = decide(**case)
    assert failed(result) == [rule]
    assert result["verdict"] == "KEEP_RUNNING"
    assert result["winner"] is None and result["ship_call"] is None
    assert "would make no call" in card.render(result)


@pytest.mark.parametrize("case", [
    {"control": (50, 5), "variant": (50, 5)},  # exactly the floors
    {"excluded": 6},                           # exactly 1% of 600
    {"status": "paused"},
    {"chance": 0.95},
])
def test_boundaries_pass(case):
    assert decide(**case)["verdict"] == "SHIP_VARIANT"


def test_flagsmith_srm_value_wins_over_our_own():
    srm = next(r for r in decide(exposures=(200, 400), srm=0.4)["rules"] if r["rule"] == "srm")
    assert (srm["source"], srm["value"], srm["passed"]) == ("flagsmith", 0.4, True)


@pytest.mark.parametrize("chance", [0.0501, 0.5, 0.9499])
def test_inconclusive_keeps_running(chance):
    result = decide(chance=chance)
    assert result["verdict"] == "KEEP_RUNNING"
    assert failed(result) == ["chance_to_win"]


@pytest.mark.parametrize("chance", [0.0, 0.05])
def test_losing_variant_ships_control(chance):
    result = decide(variant=(300, 10), chance=chance)
    assert (result["verdict"], result["winner"], result["variant_option_id"]) == (
        "SHIP_CONTROL", "control", None)
    assert result["winner_value"] == "control"
    assert result["ship_call"]["body"] == {"rollout_decision": "control"}
    assert "smoke-tested" in card.render(result)


@pytest.mark.parametrize("missing", ["exposures", "results"])
def test_missing_data_keeps_running(missing):
    experiment, exposures, results = synthetic()
    data = {"exposures": exposures, "results": results, missing: None}
    result = recommend.decide(experiment, data["exposures"], data["results"], SETTINGS)
    assert result["verdict"] == "KEEP_RUNNING"
    assert "data_available" in failed(result)
    card.render(result)


def test_computation_error_keeps_running():
    experiment, exposures, results = synthetic()
    results["last_error_at"] = "synthetic"
    result = recommend.decide(experiment, exposures, results, SETTINGS)
    assert failed(result) == ["data_available"]


@pytest.mark.parametrize("statistic, df, p", [(3.841, 1, 0.05), (5.991, 2, 0.05),
                                             (7.815, 3, 0.05), (9.488, 4, 0.05), (0, 1, 1.0)])
def test_chi_square_against_table_values(statistic, df, p):
    assert stats.chi_square_survival(statistic, df) == pytest.approx(p, abs=1e-4)


def test_srm_flags_traffic_to_an_arm_configured_for_none():
    assert stats.srm_p_value({"control": 5, "buy_now": 95}, {"control": 0, "buy_now": 100}) == 0.0
