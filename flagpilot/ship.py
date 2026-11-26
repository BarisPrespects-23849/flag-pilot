"""End the experiment and ship the winner (tier 3, irreversible)."""

import json
import sys
import time
from typing import Callable

from flagpilot import audit, card, provision, recommend
from flagpilot import flagsmith_cli as cli
from flagpilot.provision import Plan

TIER = 3
OK, FAILED, REFUSED = 0, 1, 2


def _log(action: str, experiment_id: int, status: str, *, tier: int, method: str,
         dry_run: bool, body: object = None, approved_by: str | None = None) -> None:
    audit.record(
        action=action, tier=tier, method=method, path=f"experiment {experiment_id}",
        body=body, dry_run=dry_run, approved_by=approved_by, status=status,
        response_id=experiment_id,
    )


def read_status(experiment_id: int) -> str:
    return cli.get(cli.env_path(f"experiments/{experiment_id}/"), jq="{status}")["status"]


def evaluate(flag: str, identity: str) -> object:
    # --trait makes this a what-if evaluation, so the identity is not persisted.
    result = cli.run(
        ["evaluate", flag, "--identity", identity, "--trait", "flagpilot_verify=1"],
        jq="{value}",
    )
    return result["value"]


def verify(flag: str, expected: object, settings: dict, *,
           sleep: Callable = time.sleep, clock: Callable = time.monotonic) -> tuple[int, int, float]:
    """Poll until every sample identity gets `expected`. Returns (matched, total, seconds)."""
    options = settings["verify"]
    identities = [f"flagpilot-verify-{n}" for n in range(1, options["sample_identities"] + 1)]
    started = clock()
    while True:
        matched = 0
        for identity in identities:
            try:
                matched += str(evaluate(flag, identity)) == str(expected)
            except Exception as error:  # keep polling through transient failures
                print(f"  evaluate {identity} failed: {error}", file=sys.stderr)
        elapsed = clock() - started
        if matched == len(identities) or elapsed >= options["timeout_seconds"]:
            return matched, len(identities), elapsed
        sleep(options["poll_seconds"])


def ship(experiment_id: int, settings: dict, *, apply: bool, confirm: str | None = None,
         expect_winner: str | None = None, prompt: Callable = input) -> int:
    decision = recommend.recommend(experiment_id, settings)
    _log("ship_recommend", experiment_id, decision["verdict"], tier=0, method="GET",
         dry_run=not apply, body=decision)
    print(card.render(decision))
    print()

    def refuse(reason: str) -> int:
        print(f"REFUSED: {reason}", file=sys.stderr)
        _log("ship_refused", experiment_id, f"refused: {reason}", tier=TIER, method="POST",
             dry_run=not apply)
        return REFUSED

    failed = [r["rule"] for r in decision["rules"] if not r["passed"]]
    if decision["verdict"] not in recommend.SHIPPABLE or failed:
        return refuse(f"verdict is {decision['verdict']}; rules not passing: "
                      f"{', '.join(failed) or 'none'}")

    name, flag = decision["experiment"]["name"], decision["experiment"]["flag"]
    body = decision["ship_call"]["body"]
    plan = Plan(
        action="experiment_complete", method="POST", tier=TIER, body=body,
        args=["api", cli.env_path(f"experiments/{experiment_id}/complete/"),
              "-X", "POST", "--input", "-"],
        effect=f"IRREVERSIBLE. Ends experiment {experiment_id} and serves "
        f"'{decision['winner']}' to every identified user of {flag}.",
    )
    if not apply:
        provision.execute(plan, apply=False, approved_by=None)
        print("Nothing was changed. To ship, run again with --apply.")
        return OK

    if confirm is None:
        if not sys.stdin.isatty():
            return refuse("no terminal to type in; pass --confirm and --expect-winner")
        confirm = prompt(f"Type the experiment name ({name}) to ship: ")
    elif expect_winner is None:
        return refuse("--confirm needs --expect-winner, the winner shown in the dry-run")
    if expect_winner is not None and expect_winner != decision["winner"]:
        return refuse(f"the winner is now '{decision['winner']}', not '{expect_winner}'")
    if confirm != name:
        return refuse("the typed name does not match the experiment name")

    status = read_status(experiment_id)
    _log("ship_status_check", experiment_id, status, tier=0, method="GET", dry_run=False)
    if status not in recommend.ACTIVE:
        return refuse(f"experiment is now '{status}'")

    try:
        provision.execute(plan, apply=True, approved_by="user")
    except Exception as error:
        print(f"complete/ failed: {error}", file=sys.stderr)
        print(f"Experiment status now: {read_status(experiment_id)}. Do not retry blindly.",
              file=sys.stderr)
        return FAILED

    matched, total, seconds = verify(flag, decision["winner_value"], settings)
    status = read_status(experiment_id)
    verified = matched == total and status == "completed"
    _log("ship_verify", experiment_id, "success" if verified else "failed", tier=0,
         method="CLI", dry_run=False,
         body={"matched": matched, "total": total, "status": status})
    print(f"Experiment status: {status}")
    print(f"{matched}/{total} sample identities get {json.dumps(decision['winner_value'])} "
          f"after {seconds:.0f} s")
    print(f"Dashboard: {decision['dashboard']}")
    if not verified:
        print("NOT VERIFIED: the experiment was completed, but check the rollout in the "
              "dashboard before relying on it.", file=sys.stderr)
        return FAILED
    print(f"Shipped '{decision['winner']}'. Note: {decision['note']}.")
    print("Run cleanup to make it permanent.")
    return OK
