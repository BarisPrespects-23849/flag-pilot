"""Create the flag, variant, metric and experiment, one approved step at a time.

Dry-run is the default. --apply makes exactly one state-changing call.
Nothing here starts the experiment, but creating it already changes what is served.

    python -m flagpilot.provision {flag,variant,metric,experiment} [--apply --approved-by NAME]
"""

import argparse
import json
import shlex
import sys
from dataclasses import dataclass
from urllib.parse import quote

from flagpilot import audit, config
from flagpilot import flagsmith_cli as cli

class Blocked(RuntimeError):
    """A precondition failed, so the step must not run."""


@dataclass
class Plan:
    action: str
    method: str
    args: list[str]  # CLI arguments
    body: object = None
    effect: str = ""
    tier: int = 1

    @property
    def path(self) -> str:
        if self.method == "CLI":
            return cli.redact(shlex.join(["flagsmith", *self.args]))
        return cli.redact(self.args[1])


def find_feature() -> dict | None:
    project = config.project_config()["project"]
    features = cli.get(
        f"api/v1/projects/{project}/features/?search={quote(config.FLAG_NAME)}",
        jq="[.results[] | {id, name, multivariate_options}]",
    )
    return next((f for f in features if f["name"] == config.FLAG_NAME), None)


def find_variant(feature: dict) -> dict | None:
    options = feature.get("multivariate_options") or []
    return next((o for o in options if o.get("key") == config.VARIANT_KEY), None)


def find_metric() -> dict | None:
    metrics = cli.get(
        cli.env_path("experiment-metrics/"), jq="[.results[] | {id, name, definition}]"
    )
    return next((m for m in metrics if m["name"] == config.METRIC_NAME), None)


def experiments() -> list[dict]:
    return cli.get(
        cli.env_path("experiments/"),
        jq="[.results[] | {id, name, status, feature: .feature.name}]",
    )


def plan_flag() -> Plan:
    if find_feature():
        raise Blocked(f"Flag '{config.FLAG_NAME}' already exists.")
    return Plan(
        action="feature_create",
        method="CLI",
        args=[
            "feature", "create", config.FLAG_NAME,
            "--value", config.CONTROL_VALUE,
            "--enabled",
            "--description", "Checkout button copy (Flag Pilot experiment)",
        ],
        effect="Creates a project-wide flag, enabled in every environment "
        f"(including Production), serving '{config.CONTROL_VALUE}' to everyone.",
    )


def plan_variant() -> Plan:
    feature = find_feature()
    if not feature:
        raise Blocked("The flag does not exist yet. Run the 'flag' step first.")
    if find_variant(feature):
        raise Blocked(f"Variant '{config.VARIANT_KEY}' already exists.")
    return Plan(
        action="feature_variant_add",
        method="CLI",
        args=[
            "feature", "variant", "add", config.FLAG_NAME,
            "--value", config.VARIANT_VALUE,
            "--key", config.VARIANT_KEY,
            "--weight", "0",
        ],
        effect="Adds a keyed variant at 0% weight. Nobody is served it.",
    )


def plan_metric() -> Plan:
    if find_metric():
        raise Blocked(f"Metric '{config.METRIC_NAME}' already exists.")
    return Plan(
        action="metric_create",
        method="POST",
        args=["api", cli.env_path("experiment-metrics/"), "-X", "POST", "--input", "-"],
        body={
            "name": config.METRIC_NAME,
            "aggregation": "occurrence",
            "direction": "up",
            "definition": {"version": 1, "event": config.CONVERSION_EVENT},
        },
        effect="Creates a metric definition. No effect on what users see.",
    )


def plan_experiment() -> Plan:
    feature = find_feature()
    variant = find_variant(feature) if feature else None
    metric = find_metric()
    if not (feature and variant and metric):
        raise Blocked("The flag, keyed variant and metric must all exist first.")
    if metric["definition"].get("event") != config.CONVERSION_EVENT:
        raise Blocked("The existing metric tracks a different event name.")
    active = [
        e for e in experiments()
        if e["feature"] == config.FLAG_NAME and e["status"] != "completed"
    ]
    if active:
        raise Blocked(f"The flag already has an active experiment (id {active[0]['id']}).")
    return Plan(
        action="experiment_create",
        method="POST",
        args=["api", cli.env_path("experiments/"), "-X", "POST", "--input", "-"],
        body={
            "feature": feature["id"],
            "name": config.EXPERIMENT_NAME,
            "hypothesis": config.HYPOTHESIS,
            "metrics": [{"metric": metric["id"], "expected_direction": "increase"}],
            "experiment_rollout": {
                "enabled": True,
                "rollout_percentage": 100,
                "feature_state_value": {"type": "string", "value": config.CONTROL_VALUE},
                "multivariate_feature_state_values": [
                    {"multivariate_feature_option": variant["id"], "percentage_allocation": 50}
                ],
            },
        },
        effect="Creates the experiment in status 'created' (not started). Its 50/50 "
        "rollout is served in this environment IMMEDIATELY.",
        tier=2,
    )


STEPS = {
    "flag": plan_flag,
    "variant": plan_variant,
    "metric": plan_metric,
    "experiment": plan_experiment,
}


def execute(plan: Plan, *, apply: bool, approved_by: str | None) -> object:
    log = dict(
        action=plan.action,
        tier=plan.tier,
        method=plan.method,
        path=plan.path,
        body=plan.body if plan.body is not None else plan.path,
    )
    print(f"{'APPLY' if apply else 'DRY-RUN'}  tier {plan.tier}  {plan.action}")
    print(f"  {plan.method} {plan.path}")
    if plan.body is not None:
        print("  body: " + json.dumps(plan.body))
    print(f"  effect: {plan.effect}")

    if not apply:
        audit.record(**log, dry_run=True, status="planned")
        return None

    try:
        response = cli.run(plan.args, body=plan.body)
    except Exception:
        audit.record(**log, dry_run=False, approved_by=approved_by, status="failed")
        raise
    response_id = response.get("id") if isinstance(response, dict) else None
    audit.record(
        **log, dry_run=False, approved_by=approved_by,
        status="success", response_id=response_id,
    )
    print(f"  done (id: {response_id})")
    return response


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("step", choices=STEPS)
    parser.add_argument("--apply", action="store_true", help="make the real call")
    parser.add_argument("--approved-by", help="who approved this call (required with --apply)")
    args = parser.parse_args(argv)
    if args.apply and not args.approved_by:
        parser.error("--apply requires --approved-by")
    try:
        execute(STEPS[args.step](), apply=args.apply, approved_by=args.approved_by)
    except (Blocked, cli.CliError) as error:
        print(f"BLOCKED: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
