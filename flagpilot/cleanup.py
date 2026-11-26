"""Open a pull request that removes a completed experiment's flag from the code.

Dry-run is the default and changes no file. --apply works in a temporary git worktree, so
your checkout is not touched, and pushes only after every check passes. Nothing is merged.
"""

import ast
import difflib
import json
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from flagpilot import audit, card, config, lifecycle, recommend, refs, repo
from flagpilot import flagsmith_cli as cli

TIER = 1  # a branch and a pull request: reversible, and nothing served changes
OK, FAILED, REFUSED = 0, 1, 2
CONTROL = recommend.CONTROL

_EXPERIMENT_JQ = (
    "{id, name, status, rollout_decision, rollout_variant, "
    "feature: (.feature | {id, name, multivariate_options})}"
)


class Refused(RuntimeError):
    pass


@dataclass
class Plan:
    experiment: dict
    winner: str
    winner_value: object
    assumed: bool
    sites: list = field(default_factory=list)
    flag_tests: list = field(default_factory=list)
    other_mentions: dict = field(default_factory=dict)  # outside the scanned code
    edits: dict = field(default_factory=dict)  # path -> new text, or None to delete
    originals: dict = field(default_factory=dict)
    manual: list = field(default_factory=list)  # why an automatic edit is not possible
    allowed: set = field(default_factory=set)  # the only files a cleanup may change

    @property
    def flag(self) -> str:
        return self.experiment["feature"]["name"]

    @property
    def branch(self) -> str:
        return f"cleanup/{self.flag}-{self.winner}"

    @property
    def title(self) -> str:
        return f"Remove {self.flag}: ship {self.winner} (experiment {self.experiment['id']})"


def read_experiment(experiment_id: int) -> dict:
    return cli.get(cli.env_path(f"experiments/{experiment_id}/"), jq=_EXPERIMENT_JQ)


def read_flag(flag: str) -> dict:
    return cli.run(["feature", "get", flag], jq="{enabled, default_value}")


def resolve_winner(experiment: dict, assume: str | None) -> tuple[str, object]:
    """(variant key or 'control', the value it serves), from the API unless assumed."""
    eid, status = experiment["id"], experiment["status"]
    options = experiment["feature"].get("multivariate_options") or []
    if assume is not None:
        if status == "completed":
            raise Refused(f"experiment {eid} is completed, so the API decides the winner; "
                          "drop --assume-winner")
        chosen = next((o for o in options if o.get("key") == assume), None)
        if assume != CONTROL and not chosen:
            keys = ", ".join([CONTROL, *(o["key"] for o in options if o.get("key"))])
            raise Refused(f"'{assume}' is not a variant of this experiment (have: {keys})")
    else:
        if status != "completed":
            raise Refused(f"experiment {eid} is '{status}', not 'completed'")
        decision = experiment.get("rollout_decision")
        if decision == "variant":
            chosen = next((o for o in options
                           if o["id"] == experiment.get("rollout_variant")), None)
            if not chosen or not chosen.get("key"):
                raise Refused(f"rollout_variant {experiment.get('rollout_variant')} is not a "
                              "keyed variant of the flag")
            assume = chosen["key"]
        elif decision == CONTROL:
            assume, chosen = CONTROL, None
        else:
            raise Refused(f"rollout_decision is '{decision}'; only 'control' and 'variant' "
                          "can be cleaned up")
    state = read_flag(experiment["feature"]["name"])
    if not state["enabled"]:
        raise Refused("the flag is disabled in this environment, so the winning behaviour "
                      "is ambiguous")
    value = state["default_value"] if assume == CONTROL else recommend.option_value(chosen)
    return assume, value


def _imports(text: str, modules: set[str]) -> bool:
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Import):
            if any(a.name in modules for a in node.names):
                return True
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module in modules or any(
                    f"{node.module}.{a.name}" in modules for a in node.names):
                return True
    return False


def build_plan(root: Path, experiment: dict, winner: str, value: object, assumed: bool,
               options: dict) -> Plan:
    app, tests = options["app_paths"], options["test_paths"]
    flag = experiment["feature"]["name"]
    files = refs.load(root)
    hits = refs.grep(root, flag)
    plan = Plan(experiment, winner, value, assumed)
    plan.sites = refs.find(files, flag, app, hits)
    plan.flag_tests = refs.marked_test_files(files, flag, tests)
    for path, _line, _text in hits:
        if not refs.within(path, app) and path not in plan.flag_tests:
            plan.other_mentions[path] = plan.other_mentions.get(path, 0) + 1
    if not any(s.is_reference for s in plan.sites) and not plan.flag_tests:
        raise Refused(f"no references to '{flag}' in {', '.join(app)}: nothing to clean up")

    known = refs.constants(files)
    for site in plan.sites:
        if site.kind in ("dynamic", "unparsed"):
            plan.manual.append(f"{site.path}:{site.line}: " + (
                "reads a flag whose name is only known at run time" if site.kind == "dynamic"
                else "cannot be parsed"))
    changed_paths = sorted({s.path for s in plan.sites if s.is_reference})
    for path in changed_paths:
        plan.originals[path] = files[path]
        if not path.endswith(".py"):
            plan.manual.append(f"{path}: not a Python file")
            continue
        try:
            new = refs.rewrite(files[path], flag, refs.Winner(True, value), known)
        except (refs.Unsupported, SyntaxError) as reason:
            plan.manual.append(f"{path}: {reason}")
            continue
        if new != files[path]:
            plan.edits[path] = new
        left = refs.find({**files, path: new}, flag, [path], [
            (path, n, line) for n, line in enumerate(new.split("\n"), 1)
            if refs.mentions(line, flag)])
        for site in left:
            if site.is_reference:
                plan.manual.append(f"{path}:{site.line}: `{site.code}` still names the flag")
    for path in plan.flag_tests:
        plan.originals[path], plan.edits[path] = files[path], None

    modules = {p.removesuffix(".py").replace("/", ".") for p in changed_paths}
    importers = {p for p, text in files.items()
                 if refs.within(p, tests) and p.endswith(".py") and _imports(text, modules)}
    plan.allowed = set(changed_paths) | set(plan.flag_tests) | importers
    return plan


def diff(plan: Plan) -> str:
    chunks = []
    for path, new in sorted(plan.edits.items()):
        chunks.extend(difflib.unified_diff(
            plan.originals[path].splitlines(), [] if new is None else new.splitlines(),
            f"a/{path}", "/dev/null" if new is None else f"b/{path}", lineterm=""))
    return "\n".join(chunks)


def render(plan: Plan, options: dict) -> str:
    e = plan.experiment
    lines = []
    if plan.assumed:
        lines += [f"PREVIEW ONLY: the winner is ASSUMED. Experiment {e['id']} is "
                  f"'{e['status']}' and nothing has been decided.", ""]
    lines += [
        f"Cleanup for experiment {e['id']}: {e['name']}, flag {plan.flag}",
        f"Winner ({'assumed' if plan.assumed else 'from the API'}): {plan.winner}, "
        f"serves {json.dumps(plan.winner_value)}",
        f"Stays: the code path taken when {plan.flag} serves {json.dumps(plan.winner_value)}",
        "Goes:  the flag read, the other path(s), and tests that only cover the flag",
        "",
        f"Call sites in {', '.join(options['app_paths'])} (ast, cross-checked with git grep)",
    ]
    lines += [f"  {s.path}:{s.line}  [{s.kind}]  {s.code}" for s in plan.sites] or ["  none"]
    lines += ["", "Flag-only test files to delete"]
    lines += [f"  {path}" for path in plan.flag_tests] or ["  none"]
    lines += ["", "Other mentions, left alone (tooling, docs, fixtures)"]
    lines += [f"  {path}  ({n} line{'s' * (n > 1)})"
              for path, n in sorted(plan.other_mentions.items())] or ["  none"]
    lines += ["", "Files a cleanup may change: " + ", ".join(sorted(plan.allowed))]
    if plan.manual:
        lines += ["", "NEEDS A MANUAL EDIT (use --patch)"] + [f"  {m}" for m in plan.manual]
    lines += ["", "Planned diff" + (" (incomplete)" if plan.manual else ""), diff(plan) or "  none",
              "", f"Branch: {plan.branch}", f"Pull request: {plan.title}",
              "Note: this applies the winner wherever this code is deployed, including any "
              "environment where the flag serves something else."]
    return "\n".join(lines)


def _audit_rows(experiment_id: int, log_path: Path) -> list[dict]:
    if not log_path.exists():
        return []
    rows = []
    for line in log_path.read_text().splitlines():
        entry = json.loads(line)
        path = entry.get("path") or ""
        action = entry.get("action") or ""
        if (f"experiments/{experiment_id}/" in path
                or path.split(" flag ")[0] == f"experiment {experiment_id}"
                or (entry.get("response_id") == experiment_id
                    and action.startswith("experiment_"))):
            rows.append(entry)
    return rows


def pr_body(plan: Plan, decision: dict, snapshot: bool, changed: list[str],
            options: dict) -> str:
    e = plan.experiment

    def table(header: list[str], rows: list[list]) -> list[str]:
        cells = [[" ".join(str(c).split()).replace("|", "\\|") for c in row] for row in rows]
        return ["| " + " | ".join(header) + " |", "|" + "---|" * len(header),
                *("| " + " | ".join(row) + " |" for row in cells)]

    if snapshot:
        verdict = (f"**{decision['verdict']}**, recorded by `flagpilot ship` just before its "
                   "`complete/` call.")
        if decision["winner"] != plan.winner:
            verdict += (f" **Warning:** it chose `{decision['winner']}`, which differs from "
                        "what was rolled out.")
    else:
        verdict = ("**not recorded**. The rules below were recomputed after completion, when "
                   "`status` and `srm` can no longer be evaluated.")

    def result(rule: dict) -> str:
        if rule["passed"]:
            return "PASS"
        return "n/a (completed)" if not snapshot and rule["rule"] in ("status", "srm") else "FAIL"

    lines = [
        "## Verdict",
        f"- Rolled out (from the API): **{plan.winner}** (`rollout_decision: "
        f"{e['rollout_decision']}`, `rollout_variant: {e['rollout_variant']}`)",
        f"- Flag Pilot verdict: {verdict}",
        "", "## Rules",
        *table(["#", "Rule", "Value", "Needs", "Result"],
               [[i, r["rule"], card._value(r), r["threshold"], result(r)]
                for i, r in enumerate(decision["rules"], 1)]),
        "", "## Results",
        f"Results as of {decision['data']['results_as_of']}.", "",
        *table(["Arm", "Identities", "Conversions", "Rate", "Chance to win"], [
            [a["key"], a["identities"], a["conversions"], card._percent(a["rate"]),
             "baseline" if a["key"] == CONTROL else card._percent(a["chance_to_win"])]
            for a in decision["arms"]]),
        "", f"[Open the experiment in Flagsmith]({decision['dashboard']})",
        "", "## What changed",
        *[f"- `{path}`" for path in changed],
        "- `track_event(\"purchase\")` and other event tracking is **kept**: it is analytics, "
        "not part of the flag.",
        f"- Checked: tests pass, and `{plan.flag}` has 0 references in "
        f"{', '.join(options['app_paths'])}.",
        "- This applies the winner wherever this code is deployed, including any environment "
        "where the flag serves something else.",
    ]
    if plan.other_mentions:
        lines.append("- Still named outside application code (left alone): "
                     + ", ".join(f"`{p}`" for p in sorted(plan.other_mentions)))
    rows = _audit_rows(e["id"], audit.AUDIT_PATH)
    lines += ["", "## audit.jsonl entries"]
    lines += table(["Time", "Action", "Tier", "Dry run", "Approved by", "Status"], [
        [r["ts"], r["action"], r["tier"], r["dry_run"], r["approved_by"] or "-", r["status"]]
        for r in rows]) if rows else ["None found on this machine."]
    lines += ["", "## After merge", f"- [ ] after merge: `flagpilot retire {plan.flag}`", "",
              "Opened by Flag Pilot. A human reviews and merges."]
    return "\n".join(lines)


def evidence(experiment_id: int, settings: dict) -> tuple[dict, bool]:
    """The decision recorded at ship time, or one recomputed now."""
    saved = lifecycle.load_state().get("ship_decisions", {}).get(str(experiment_id))
    if saved:
        return saved, True
    return recommend.recommend(experiment_id, settings), False


def _log(action: str, plan_or_id, status: str, *, dry_run: bool, method: str = "CLI",
         body: object = None, approved_by: str | None = None) -> None:
    if isinstance(plan_or_id, Plan):
        eid = plan_or_id.experiment["id"]
        path = f"experiment {eid} flag {plan_or_id.flag}"
    else:
        eid, path = plan_or_id, f"experiment {plan_or_id}"
    audit.record(action=action, tier=TIER, method=method, path=path, body=body,
                 dry_run=dry_run, approved_by=approved_by, status=status, response_id=eid)


def _changed_files(tree: Path) -> list[str]:
    out = repo.git(tree, "status", "--porcelain", "-z", "--no-renames",
                   "--untracked-files=all")
    return sorted(entry[3:] for entry in out.split("\0") if entry)


def _check_apply(root: Path, plan: Plan, patch: Path | None, options: dict) -> None:
    base, scope = options["base_branch"], options["app_paths"] + options["test_paths"]
    repo.git(root, "fetch", "origin", base)
    differing = repo.git(root, "diff", "--name-only", f"origin/{base}", "--", *scope).split()
    differing += repo.git(root, "ls-files", "--others", "--exclude-standard", "--",
                          *scope).split()
    if differing:
        raise Refused(f"these files differ from origin/{base}, so the dry-run would not match "
                      f"the pull request: {', '.join(sorted(set(differing)))}")
    if repo.git(root, "branch", "--list", plan.branch).strip():
        raise Refused(f"branch {plan.branch} already exists locally")
    if repo.git(root, "ls-remote", "--heads", "origin", plan.branch).strip():
        raise Refused(f"branch {plan.branch} already exists on origin")
    if plan.manual and patch is None:
        raise Refused("this code needs a manual edit; pass it with --patch: "
                      + "; ".join(plan.manual))
    if patch is not None and not patch.is_file():
        raise Refused(f"patch file {patch} does not exist")


def _verify(tree: Path, plan: Plan, options: dict, events_before) -> list[str]:
    """Raise unless the edited worktree meets every condition. Returns changed files."""
    changed = _changed_files(tree)
    if not changed:
        raise Refused("the edit changed nothing")
    outside = sorted(set(changed) - plan.allowed)
    if outside:
        raise Refused(f"files outside the plan were changed: {', '.join(outside)}")
    files = refs.load(tree)
    app, tests = options["app_paths"], options["test_paths"]
    left = [s for s in refs.find(files, plan.flag, app, refs.grep(tree, plan.flag))
            if s.is_reference]
    places = [f"{s.path}:{s.line}" for s in left]
    places += refs.marked_test_files(files, plan.flag, tests)
    if places:
        raise Refused(f"'{plan.flag}' is still referenced: {', '.join(places)}")
    lost = events_before - refs.tracked_events(files, app)
    if lost:
        raise Refused(f"event tracking was removed: {', '.join(sorted(lost))}")
    return changed


def _apply(root: Path, plan: Plan, patch: Path | None, settings: dict) -> int:
    options = settings["cleanup"]
    base = options["base_branch"]
    decision, snapshot = evidence(plan.experiment["id"], settings)
    events_before = refs.tracked_events(refs.load(root), options["app_paths"])
    tree = Path(tempfile.mkdtemp(prefix="flagpilot-cleanup-")) / "tree"
    repo.git(root, "worktree", "add", "-b", plan.branch, str(tree), f"origin/{base}")
    _log("cleanup_branch", plan, "success", dry_run=False, approved_by="user",
         body={"branch": plan.branch})
    print(f"Branch {plan.branch} created from origin/{base} in {tree}")
    step = "cleanup_edit"
    try:
        if patch is not None:
            repo.git(tree, "apply", str(patch.resolve()))
        else:
            for path, text in plan.edits.items():
                if text is None:
                    (tree / path).unlink()
                else:
                    (tree / path).write_text(text)
        _verify(tree, plan, options, events_before)
        _log(step, plan, "success", dry_run=False, approved_by="user",
             body={"patch": patch is not None})
        print("Edit verified: only planned files changed, 0 references, tracking kept.")

        step = "cleanup_tests"
        passed, output = repo.run_tests(tree, options["test_command"])
        print(output)
        if not passed:
            raise Refused("tests failed")
        changed = _verify(tree, plan, options, events_before)
        _log(step, plan, "success", dry_run=False)

        step = "cleanup_push"
        repo.git(tree, "add", "-A", "--", *changed)
        repo.git(tree, "commit", "-m", plan.title)
        body = pr_body(plan, decision, snapshot, changed, options)
        repo.push(tree, plan.branch)
        _log(step, plan, "success", dry_run=False, approved_by="user")

        step = "cleanup_pr_create"
        url = repo.gh(tree, "pr", "create", "--base", base, "--head", plan.branch,
                      "--title", plan.title, "--body-file", "-", input=body).strip()
        _log(step, plan, "success", dry_run=False, approved_by="user", body={"url": url})
    except (Refused, repo.RepoError, OSError, subprocess.SubprocessError) as error:
        _log(step, plan, f"failed: {error}", dry_run=False)
        print(f"STOPPED at {step}: {error}", file=sys.stderr)
        state = {
            "cleanup_push": "was not confirmed as pushed",
            "cleanup_pr_create": "WAS pushed, but no pull request was confirmed",
        }.get(step, "is NOT pushed")
        print(f"The branch {state}. Inspect {tree}. To discard: git worktree remove --force {tree} && "
              f"git branch -D {plan.branch}", file=sys.stderr)
        return FAILED
    repo.git(root, "worktree", "remove", "--force", str(tree))
    print(f"Pull request: {url}")
    print(f"Review and merge it yourself. After merge: flagpilot retire {plan.flag}")
    return OK


def cleanup(experiment_id: int, settings: dict, *, apply: bool, assume_winner: str | None = None,
            patch: Path | None = None, root: Path | None = None) -> int:
    root = root or config.ROOT
    options = settings["cleanup"]
    try:
        if assume_winner is not None and apply:
            raise Refused("--assume-winner is for previews only and cannot be used with --apply")
        experiment = read_experiment(experiment_id)
        winner, value = resolve_winner(experiment, assume_winner)
        plan = build_plan(root, experiment, winner, value, assume_winner is not None, options)
        print(render(plan, options))
        print()
        if not apply:
            _log("cleanup_plan", plan, "assumed winner" if plan.assumed else "planned",
                 dry_run=True, body={"winner": winner, "diff": diff(plan)})
            print("DRY-RUN: no file, branch or pull request was created "
                  "(only audit.jsonl was appended to).")
            return OK
        _check_apply(root, plan, patch, options)
    except (Refused, repo.RepoError, cli.CliError) as reason:
        print(f"REFUSED: {reason}", file=sys.stderr)
        _log("cleanup_refused", experiment_id, f"refused: {reason}", dry_run=not apply)
        return REFUSED
    return _apply(root, plan, patch, settings)
