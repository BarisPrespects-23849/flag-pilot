"""Turn an experiment's real results into a verdict. Deterministic: no LLM involved.

Payload shapes are the ones recorded in NOTES.md §3, which differ from the API spec.
"""

import contextlib
import sys
import time

from flagpilot import config, lifecycle, stats
from flagpilot import flagsmith_cli as cli
from flagpilot.provision import Blocked

SHIP_VARIANT = "SHIP_VARIANT"
SHIP_CONTROL = "SHIP_CONTROL"
KEEP_RUNNING = "KEEP_RUNNING"
SHIPPABLE = (SHIP_VARIANT, SHIP_CONTROL)

CONTROL = "control"  # reserved variant key for the control arm
ACTIVE = ("running", "paused")
DEFAULT_VALUE_NOTE = (
    "the flag's default value stays control for unidentified users until cleanup"
)

_EXPERIMENT_JQ = (
    "{id, name, status, feature: (.feature | {id, name, multivariate_options}), "
    "metrics: [.metrics[] | {metric, metric_name, aggregation, direction, expected_direction}], "
    "experiment_rollout}"
)
_EXPOSURES_JQ = ".exposures"
_RESULTS_JQ = (
    ".results | if . == null or .payload == null then . else "
    ".payload |= {srm_p_value, metrics: [.metrics[] | {metric_id, variants, inference}]} end"
)


def fetch(experiment_id: int) -> tuple[dict, dict | None, dict | None]:
    """Read-only: the experiment, its exposures and its results."""
    base = f"experiments/{experiment_id}/"
    return (
        cli.get(cli.env_path(base), jq=_EXPERIMENT_JQ),
        cli.get(cli.env_path(base + "exposures/"), jq=_EXPOSURES_JQ),
        cli.get(cli.env_path(base + "results/"), jq=_RESULTS_JQ),
    )


def refresh(experiment_id: int, timeout_seconds: float = 60) -> None:
    """Ask Flagsmith to recompute (tier 0). Progress goes to stderr."""
    path = cli.env_path(f"experiments/{experiment_id}/")
    experiment = cli.get(path, jq="{id, status}")
    previous = cli.get(path + "results/", jq=".results.as_of")
    refreshed_results = False
    with contextlib.redirect_stdout(sys.stderr):
        for step in ("exposures-refresh", "results-refresh"):
            try:
                lifecycle.run(step, apply=True, approved_by="auto (tier 0)",
                              experiment=experiment)
                refreshed_results = step == "results-refresh"
            except (Blocked, cli.RateLimited) as reason:
                print(f"{step} skipped: {reason}")
        if not refreshed_results:
            return
        deadline = time.monotonic() + timeout_seconds
        while cli.get(path + "results/", jq=".results.as_of") == previous:
            if time.monotonic() >= deadline:
                print("Results have not updated yet; showing the previous ones.")
                return
            time.sleep(3)


def option_value(option: dict) -> object:
    field = {"int": "integer_value", "bool": "boolean_value"}.get(
        option.get("type"), "string_value"
    )
    return option.get(field)


def exposure_counts(exposures: dict | None) -> dict[str, int]:
    counts: dict[str, int] = {}
    payload = (exposures or {}).get("payload") or {}
    for point in (payload.get("timeseries") or {}).get("points") or []:
        for arm, new in point["new_identities"].items():
            counts[arm] = counts.get(arm, 0) + new
    return counts


def dashboard_url(experiment_id: int) -> str:
    project = config.project_config()
    return (
        f"https://app.flagsmith.com/project/{project['project']}/environment/"
        f"{project['environment']}/experiments/{experiment_id}"
    )


def _rule(name: str, passed: bool, value: object, threshold: str, detail: str = "",
          **extra) -> dict:
    return {"rule": name, "passed": bool(passed), "value": value, "threshold": threshold,
            "detail": detail, **extra}


def decide(experiment: dict, exposures: dict | None, results: dict | None,
           settings: dict) -> dict:
    """Apply every rule and return the compact decision object."""
    gates = settings["gates"]
    options = {o["id"]: o for o in experiment["feature"].get("multivariate_options") or []}
    rollout = experiment.get("experiment_rollout")
    payload = (results or {}).get("payload") or {}
    metrics = payload.get("metrics") or []
    metric = metrics[0] if metrics else {}
    variants = metric.get("variants") or {}
    inference = metric.get("inference") or {}

    split: dict[str, float] = {}
    option_ids: dict[str, int] = {}
    if rollout:
        for allocation in rollout.get("multivariate_feature_state_values") or []:
            option = options.get(allocation["multivariate_feature_option"])
            if option and option.get("key"):
                split[option["key"]] = allocation["percentage_allocation"]
                option_ids[option["key"]] = option["id"]
        split = {CONTROL: max(0.0, 100 - sum(split.values())), **split}
    else:
        option_ids = {o["key"]: i for i, o in options.items() if o.get("key") in inference}
    treatments = list(option_ids)
    names = [CONTROL, *treatments]

    arms = []
    for name in names:
        counts = variants.get(name) or {}
        n, conversions = counts.get("n", 0), counts.get("sum", 0)
        stat = inference.get(name) or {}
        arms.append({
            "key": name,
            "identities": n,
            "conversions": conversions,
            "rate": conversions / n if n else None,
            **{k: stat.get(k) for k in ("chance_to_win", "lift", "ci_low", "ci_high")},
        })

    rules = [_rule("status", experiment["status"] in ACTIVE, experiment["status"],
                   "running or paused")]

    problems = []
    for label, data in (("results", results), ("exposures", exposures)):
        if not data or not data.get("payload"):
            problems.append(f"no {label} yet")
        elif data.get("last_error_at"):
            problems.append(f"{label} computation error at {data['last_error_at']}")
    rules.append(_rule("data_available", not problems, "; ".join(problems) or "ok",
                       "results and exposures computed without errors"))

    # Only this combination has been seen in real data, so nothing else is trusted.
    definitions = experiment.get("metrics") or []
    supported = (
        len(definitions) == 1 and len(metrics) == 1
        and definitions[0].get("aggregation") == "occurrence"
        and definitions[0].get("direction") == "up"
        and definitions[0].get("expected_direction") == "increase"
        and metrics[0].get("metric_id") == definitions[0].get("metric")
    )
    rules.append(_rule(
        "metric_supported", supported,
        ", ".join(f"{d.get('aggregation')}/{d.get('direction')}/{d.get('expected_direction')}"
                  for d in definitions) or "none",
        "one metric: occurrence/up/increase",
    ))

    for name, field, minimum in (
        ("sample_size", "identities", gates["min_identities_per_arm"]),
        ("conversions", "conversions", gates["min_conversions_per_arm"]),
    ):
        lowest = min((a[field] for a in arms), default=0)
        rules.append(_rule(
            name, len(arms) >= 2 and lowest >= minimum, lowest, f">= {minimum} in every arm",
            ", ".join(f"{a['key']} {a[field]}" for a in arms),
        ))

    counts = exposure_counts(exposures)
    srm_p, source = payload.get("srm_p_value"), "flagsmith"
    if srm_p is None:
        source = "flagpilot"
        try:
            srm_p = stats.srm_p_value(counts, split)
        except ValueError:
            srm_p = None
    rules.append(_rule(
        "srm", srm_p is not None and srm_p >= gates["srm_p_block"], srm_p,
        f"p >= {gates['srm_p_block']}",
        "exposures " + (", ".join(f"{k} {v}" for k, v in sorted(counts.items())) or "none"),
        source=source,
    ))

    total = sum(counts.values())
    excluded = ((exposures or {}).get("payload") or {}).get("excluded_identities")
    share = excluded / total if total and excluded is not None else None
    rules.append(_rule(
        "excluded_identities",
        share is not None and share <= gates["max_excluded_share"], share,
        f"<= {gates['max_excluded_share']:.1%} of exposures",
        f"{excluded} of {total}" if share is not None else "unknown",
    ))

    high, low = gates["ship_variant_chance"], gates["ship_control_chance"]
    chances = {t: (inference.get(t) or {}).get("chance_to_win") for t in treatments}
    outcome, winner, best = KEEP_RUNNING, None, None
    if chances and all(c is not None for c in chances.values()):
        leader = max(chances, key=chances.get)
        best = chances[leader]
        if best >= high:
            outcome, winner = SHIP_VARIANT, leader
        elif best <= low:
            outcome, winner = SHIP_CONTROL, CONTROL
    rules.append(_rule(
        "chance_to_win", outcome in SHIPPABLE, best, f">= {high} or <= {low}",
        ", ".join(f"{k} {v:.4f}" for k, v in chances.items() if v is not None) or "unknown",
    ))

    if not all(r["passed"] for r in rules):
        outcome, winner = KEEP_RUNNING, None

    ship_call = None
    if outcome in SHIPPABLE:
        body = {"rollout_decision": "control"}
        if outcome == SHIP_VARIANT:
            body = {"rollout_decision": "variant", "rollout_variant": option_ids[winner]}
        ship_call = {
            "method": "POST",
            "path": cli.redact(cli.env_path(f"experiments/{experiment['id']}/complete/")),
            "body": body,
        }

    winner_value = None
    if outcome == SHIP_VARIANT:
        winner_value = option_value(options[option_ids[winner]])
    elif outcome == SHIP_CONTROL:
        winner_value = rollout["feature_state_value"]["value"]

    return {
        "experiment": {"id": experiment["id"], "name": experiment["name"],
                       "status": experiment["status"], "flag": experiment["feature"]["name"]},
        "verdict": outcome,
        "winner": winner,
        "variant_option_id": option_ids.get(winner) if outcome == SHIP_VARIANT else None,
        "winner_value": winner_value,
        "rules": rules,
        "arms": arms,
        "data": {"results_as_of": (results or {}).get("as_of"),
                 "exposures_as_of": (exposures or {}).get("as_of")},
        "ship_call": ship_call,
        "dashboard": dashboard_url(experiment["id"]),
        "note": DEFAULT_VALUE_NOTE,
    }


def recommend(experiment_id: int, settings: dict) -> dict:
    return decide(*fetch(experiment_id), settings)
