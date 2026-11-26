"""Start the checkout experiment and refresh its exposures and results.

Dry-run is the default. --apply makes exactly one state-changing call.
Ending the experiment is deliberately not implemented here.

    python -m flagpilot.lifecycle {start,exposures-refresh,results-refresh} [--apply --approved-by NAME]
"""

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flagpilot import config, provision
from flagpilot import flagsmith_cli as cli
from flagpilot.provision import Blocked, Plan

STATE_PATH = config.ROOT / ".flagpilot_state.json"
RESULTS_REFRESH_INTERVAL = timedelta(minutes=5)


def current_experiment() -> dict:
    matches = [
        e for e in provision.experiments()
        if e["name"] == config.EXPERIMENT_NAME and e["feature"] == config.FLAG_NAME
    ]
    if len(matches) != 1:
        raise Blocked(f"Expected one experiment '{config.EXPERIMENT_NAME}', found {len(matches)}.")
    return matches[0]


def load_state(path: Path | None = None) -> dict:
    path = path or STATE_PATH
    return json.loads(path.read_text()) if path.exists() else {}


def seconds_until_refresh_allowed(experiment_id: int, now: datetime) -> int:
    last = load_state().get("results_refresh", {}).get(str(experiment_id))
    if not last:
        return 0
    remaining = datetime.fromisoformat(last) + RESULTS_REFRESH_INTERVAL - now
    return max(0, int(remaining.total_seconds()) + 1)


def remember_refresh(experiment_id: int, now: datetime) -> None:
    state = load_state()
    state.setdefault("results_refresh", {})[str(experiment_id)] = now.isoformat()
    STATE_PATH.write_text(json.dumps(state, indent=2) + "\n")


def _post(experiment_id: int, suffix: str) -> list[str]:
    return ["api", cli.env_path(f"experiments/{experiment_id}/{suffix}"), "-X", "POST"]


def plan(step: str) -> Plan:
    experiment = current_experiment()
    eid, status = experiment["id"], experiment["status"]
    if step == "start":
        if status != "created":
            raise Blocked(f"Experiment {eid} is '{status}', expected 'created'.")
        if not cli.get(cli.env_path("warehouse-connections/"), jq="[.[] | .status]"):
            raise Blocked("No warehouse connection exists.")
        return Plan("experiment_start", "POST", _post(eid, "start/"), tier=2,
                    effect=f"Starts experiment {eid}. Exposures are recorded from now on.")
    if status == "created":
        raise Blocked(f"Experiment {eid} has not started.")
    if step == "exposures-refresh":
        return Plan("exposures_refresh", "POST", _post(eid, "exposures/refresh/"), tier=0,
                    empty_response=True, effect="Asks Flagsmith to recompute exposure counts.")
    wait = seconds_until_refresh_allowed(eid, datetime.now(timezone.utc))
    if wait:
        raise Blocked(f"Results were refreshed under 5 minutes ago. Retry in {wait} s.")
    return Plan("results_refresh", "POST", _post(eid, "results/refresh/"), tier=0,
                empty_response=True,
                effect="Asks Flagsmith to recompute results (allowed once per 5 minutes).")


def run(step: str, *, apply: bool, approved_by: str | None) -> None:
    planned = plan(step)
    if apply and step == "results-refresh":
        # Stored before the call, so a failed or timed-out request also counts.
        remember_refresh(current_experiment()["id"], datetime.now(timezone.utc))
    provision.execute(planned, apply=apply, approved_by=approved_by)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("step", choices=["start", "exposures-refresh", "results-refresh"])
    parser.add_argument("--apply", action="store_true", help="make the real call")
    parser.add_argument("--approved-by", help="who approved this call (required with --apply)")
    args = parser.parse_args(argv)
    if args.apply and not args.approved_by:
        parser.error("--apply requires --approved-by")
    try:
        run(args.step, apply=args.apply, approved_by=args.approved_by)
    except (Blocked, cli.CliError) as error:
        print(f"BLOCKED: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
