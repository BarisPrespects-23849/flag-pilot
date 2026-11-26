"""Archive a flag once its experiment is over and its code is gone. Never deletes."""

import json
import sys
from pathlib import Path
from typing import Callable
from urllib.parse import quote

from flagpilot import audit, config, refs, repo
from flagpilot import flagsmith_cli as cli

TIER = 3  # typed-name approval, like other actions that retire something
OK, FAILED, REFUSED = 0, 1, 2


class Refused(RuntimeError):
    pass


def find_flag(flag: str) -> dict | None:
    project = config.project_config()["project"]
    found = cli.get(f"api/v1/projects/{project}/features/?search={quote(flag)}",
                    jq="[.results[] | {id, name, is_archived}]")
    return next((f for f in found if f["name"] == flag), None)


def read_experiments() -> dict:
    return cli.get(cli.env_path("experiments/"), jq=(
        "{next, results: [.results[] | {id, status, rollout_decision, feature: .feature.name}]}"))


def read_experiment(experiment_id: int) -> dict:
    return cli.get(cli.env_path(f"experiments/{experiment_id}/"), jq=(
        "{rollout_decision, rollout_variant, options: "
        "[.feature.multivariate_options[] | {id, key}]}"))


def _log(action: str, flag: str, status: str, *, dry_run: bool, method: str = "GET",
         body: object = None, approved_by: str | None = None, response_id=None) -> None:
    audit.record(action=action, tier=TIER if action.startswith("feature_") else 0,
                 method=method, path=f"flag {flag}", body=body, dry_run=dry_run,
                 approved_by=approved_by, status=status, response_id=response_id)


def cleanup_branch(flag: str, experiment_id: int) -> str:
    detail = read_experiment(experiment_id)
    winner = "control"
    if detail["rollout_decision"] == "variant":
        winner = next((o["key"] for o in detail["options"]
                       if o["id"] == detail["rollout_variant"]), None)
    if detail["rollout_decision"] not in ("control", "variant") or not winner:
        raise Refused(f"experiment {experiment_id} has no control or variant winner, so there "
                      "is no cleanup pull request to check")
    return f"cleanup/{flag}-{winner}"


def check(flag: str, settings: dict, *, no_code: bool, root: Path, dry_run: bool) -> dict:
    """Run every precondition. Raises Refused; returns what was found."""
    options = settings["cleanup"]
    base = options["base_branch"]
    feature = find_flag(flag)
    if not feature:
        raise Refused(f"flag '{flag}' was not found in the project")
    if feature["is_archived"]:
        raise Refused(f"flag '{flag}' is already archived")

    listing = read_experiments()
    if listing["next"]:
        raise Refused("there are more experiments than one page; cannot check them all")
    mine = [e for e in listing["results"] if e["feature"] == flag]
    if not mine:
        raise Refused(f"no experiment uses '{flag}', so there is no completed experiment")
    unfinished = [e for e in mine if e["status"] != "completed"]
    if unfinished:
        raise Refused(", ".join(f"experiment {e['id']} is '{e['status']}'" for e in unfinished)
                      + ", not 'completed'")
    latest = max(e["id"] for e in mine)
    _log("retire_check_experiment", flag, "completed", dry_run=dry_run,
         body={"experiments": [e["id"] for e in mine]}, response_id=latest)

    pull_request = None
    if not no_code:
        branch = cleanup_branch(flag, latest)
        try:
            pull_request = json.loads(repo.gh(
                root, "pr", "view", branch, "--json", "state,baseRefName,url"))
        except repo.RepoError as error:
            raise Refused(f"no cleanup pull request could be read for {branch}: {error}")
        if pull_request["state"] != "MERGED":
            raise Refused(f"cleanup pull request {pull_request['url']} is "
                          f"{pull_request['state']}, not MERGED")
        if pull_request["baseRefName"] != base:
            raise Refused(f"the cleanup pull request was merged into "
                          f"'{pull_request['baseRefName']}', not '{base}'")
        _log("retire_check_pr", flag, "MERGED", dry_run=dry_run, method="CLI",
             body=pull_request)

    try:
        repo.git(root, "fetch", "origin", base)
        ref = f"origin/{base}"
        files = refs.load(root, ref)
        hits = refs.grep(root, flag, ref=ref)
    except repo.RepoError as error:
        raise Refused(f"could not check origin/{base}: {error}")
    app, tests = options["app_paths"], options["test_paths"]
    marked = refs.marked_test_files(files, flag, tests)
    left = [f"{s.path}:{s.line} [{s.kind}]" for s in refs.find(files, flag, app, hits)
            if s.is_reference] + marked
    if left:
        raise Refused(f"{ref} still references '{flag}' (or has reads that cannot be ruled "
                      f"out): {', '.join(left)}")
    other = sorted({p for p, _n, _t in hits if not refs.within(p, app)})
    _log("retire_check_references", flag, "0 references", dry_run=dry_run, method="CLI",
         body={"ref": ref, "paths": app, "other_mentions": other})
    return {"feature": feature, "experiments": [e["id"] for e in mine], "ref": ref,
            "pull_request": pull_request, "other_mentions": other}


def retire(flag: str, settings: dict, *, apply: bool, no_code: bool = False,
           confirm: str | None = None, prompt: Callable = input,
           root: Path | None = None) -> int:
    root = root or config.ROOT
    args = ["feature", "update", flag, "--archive"]

    def refuse(reason: str) -> int:
        print(f"REFUSED: {reason}", file=sys.stderr)
        _log("retire_refused", flag, f"refused: {reason}", dry_run=not apply)
        return REFUSED

    try:
        found = check(flag, settings, no_code=no_code, root=root, dry_run=not apply)
    except (Refused, repo.RepoError, cli.CliError) as reason:
        return refuse(str(reason))

    app = ", ".join(settings["cleanup"]["app_paths"])
    print(f"Retire flag {flag} (id {found['feature']['id']})")
    print(f"  PASS  experiment(s) {', '.join(map(str, found['experiments']))} completed")
    if no_code:
        print("  SKIP  cleanup pull request (--no-code)")
    else:
        print(f"  PASS  cleanup pull request merged: {found['pull_request']['url']}")
    print(f"  PASS  0 references in {app} on {found['ref']}")
    if found["other_mentions"]:
        print("  NOTE  still named outside application code: "
              + ", ".join(found["other_mentions"]))
    print(f"{'APPLY' if apply else 'DRY-RUN'}  tier {TIER}  feature_archive")
    print(f"  CLI flagsmith {' '.join(args)}")
    print("  effect: archives the flag for the whole project. It is not deleted; "
          f"`flagsmith feature update {flag} --unarchive` restores it.")
    log = dict(method="CLI", body=args, response_id=found["feature"]["id"])
    if not apply:
        _log("feature_archive", flag, "planned", dry_run=True, **log)
        print("Nothing was changed. To archive, run again with --apply.")
        return OK

    if confirm is None:
        if not sys.stdin.isatty():
            return refuse("no terminal to type in; pass --confirm")
        confirm = prompt(f"Type the flag name ({flag}) to archive it: ")
    if confirm != flag:
        return refuse("the typed name does not match the flag name")
    try:
        cli.execute(args)
    except cli.CliError as error:
        _log("feature_archive", flag, "failed", dry_run=False, approved_by="user", **log)
        print(f"archive failed: {error}. Check the flag before retrying.", file=sys.stderr)
        return FAILED
    _log("feature_archive", flag, "success", dry_run=False, approved_by="user", **log)

    after = find_flag(flag)
    verified = bool(after and after["is_archived"])
    _log("retire_verify", flag, "archived" if verified else "unverified", dry_run=False,
         body=after)
    if not verified:
        print("NOT VERIFIED: the archive call succeeded, but the flag does not read back as "
              "archived. Check the dashboard.", file=sys.stderr)
        return FAILED
    print(f"Archived '{flag}' (verified: is_archived is true).")
    return OK
