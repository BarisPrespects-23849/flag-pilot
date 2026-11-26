"""Cleanup on a SYNTHETIC repository and experiment. Git is real; Flagsmith and GitHub
are faked. The rules table comes from the real 570 payloads."""

import copy
import json
import subprocess

import pytest

from flagpilot import audit, cleanup, recommend, repo, settings
from flagpilot import flagsmith_cli as cli
from tests import real_570, sample_repo
from tests.sample_repo import FLAG, git

SETTINGS = {**settings.load(), "cleanup": sample_repo.SETTINGS_CLEANUP}
BRANCH = f"cleanup/{FLAG}-buy_now"

EXPERIMENT = {
    "id": 9, "name": "synthetic", "status": "completed",
    "rollout_decision": "variant", "rollout_variant": 5,
    "feature": {"id": 1, "name": FLAG, "multivariate_options": [
        {"id": 5, "key": "buy_now", "type": "unicode", "string_value": "buy_now"}]},
}

GOOD_APP = '''def label(client, user):
    client.track_event("purchase", identifier=user)
    return "Buy now"
'''


@pytest.fixture
def world(monkeypatch, tmp_path):
    root = sample_repo.make(tmp_path)
    state = {"root": root, "experiment": copy.deepcopy(EXPERIMENT),
             "flag": {"enabled": True, "default_value": "control"}, "gh": [], "gh_error": None}
    monkeypatch.setattr(cleanup, "read_experiment", lambda eid: state["experiment"])
    monkeypatch.setattr(cleanup, "read_flag", lambda flag: state["flag"])
    decision = recommend.decide(*real_570.load(), SETTINGS)
    monkeypatch.setattr(cleanup, "evidence", lambda eid, s: (decision, True))

    def gh(cwd, *args, input=None):
        state["gh"].append((args, input))
        if state["gh_error"]:
            raise repo.RepoError(state["gh_error"])
        return "https://example.invalid/pull/1\n"

    monkeypatch.setattr(repo, "gh", gh)
    return state


def run(world, **kwargs):
    return cleanup.cleanup(9, SETTINGS, root=world["root"], **{"apply": False, **kwargs})


def logged():
    return [json.loads(line) for line in audit.AUDIT_PATH.read_text().splitlines()]


def remote_branches(world) -> str:
    return git(world["root"], "ls-remote", "--heads", "origin")


def assert_refused(world, capsys, reason, **kwargs):
    assert run(world, **kwargs) == cleanup.REFUSED
    assert reason in capsys.readouterr().err
    assert logged()[-1]["action"] == "cleanup_refused"
    assert world["gh"] == [] and "cleanup/" not in remote_branches(world)


def patch_for(world, tmp_path, files: dict, delete=("tests/test_flag.py",)):
    """A patch made the way an agent would: edit, diff, restore."""
    root = world["root"]
    sample_repo.write(root, files)
    for name in delete:
        (root / name).unlink()
    git(root, "add", "-A")
    patch = tmp_path / "edit.patch"
    patch.write_text(git(root, "diff", "--cached"))
    git(root, "reset", "-q", "--hard")
    return patch


# --- dry-run -----------------------------------------------------------------------------

def test_dry_run_shows_the_plan_and_writes_no_code(world, capsys):
    assert run(world) == cleanup.OK
    out = capsys.readouterr().out
    assert "demo/app.py:2  [read]" in out and '+    return "Buy now"' in out
    assert "tests/test_flag.py" in out and "tool/names.py" in out
    assert git(world["root"], "status", "--porcelain") == ""
    assert git(world["root"], "branch", "--list", "cleanup/*") == ""
    assert world["gh"] == []
    assert logged()[-1]["action"] == "cleanup_plan" and logged()[-1]["dry_run"]


def test_preview_with_an_assumed_winner(world, capsys):
    world["experiment"].update(status="running", rollout_decision=None, rollout_variant=None)
    assert run(world, assume_winner="control") == cleanup.OK
    out = capsys.readouterr().out
    assert "PREVIEW ONLY" in out and '-        return "Buy now"' in out
    assert git(world["root"], "status", "--porcelain") == ""


# --- refusals ----------------------------------------------------------------------------

@pytest.mark.parametrize("status", ["created", "running", "paused"])
@pytest.mark.parametrize("apply", [False, True])
def test_refuses_unless_completed(world, capsys, status, apply):
    world["experiment"]["status"] = status
    assert_refused(world, capsys, "not 'completed'", apply=apply)


def test_refuses_an_assumed_winner_with_apply(world, capsys):
    world["experiment"]["status"] = "running"
    assert_refused(world, capsys, "previews only", apply=True, assume_winner="buy_now")


def test_refuses_an_assumed_winner_once_completed(world, capsys):
    assert_refused(world, capsys, "the API decides", assume_winner="buy_now")


def test_refuses_an_unknown_assumed_winner(world, capsys):
    world["experiment"]["status"] = "running"
    assert_refused(world, capsys, "not a variant", assume_winner="nope")


@pytest.mark.parametrize("change, reason", [
    ({"rollout_decision": "disable"}, "only 'control' and 'variant'"),
    ({"rollout_decision": None}, "only 'control' and 'variant'"),
    ({"rollout_variant": 999}, "not a keyed variant"),
])
def test_refuses_without_a_usable_winner(world, capsys, change, reason):
    world["experiment"].update(change)
    assert_refused(world, capsys, reason)


def test_refuses_a_disabled_flag(world, capsys):
    world["flag"]["enabled"] = False
    assert_refused(world, capsys, "disabled")


def test_refuses_when_flagsmith_cannot_be_read(world, capsys, monkeypatch):
    def fail(eid):
        raise cli.CliError("synthetic outage")

    monkeypatch.setattr(cleanup, "read_experiment", fail)
    assert_refused(world, capsys, "synthetic outage")


def test_refuses_when_there_is_nothing_to_clean(world, capsys):
    world["experiment"]["feature"]["name"] = "unused_flag"
    assert_refused(world, capsys, "nothing to clean up")


@pytest.mark.parametrize("name", ["demo/app.py", "demo/new.py"])
def test_apply_refuses_code_that_differs_from_origin(world, capsys, name):
    path = world["root"] / name
    path.write_text((path.read_text() if path.exists() else "") + "# local only\n")
    assert_refused(world, capsys, "differ from origin/main", apply=True)


@pytest.mark.parametrize("where", ["local", "origin"])
def test_apply_refuses_an_existing_branch(world, capsys, where):
    git(world["root"], "branch", BRANCH)
    if where == "origin":
        git(world["root"], "push", "-q", "origin", BRANCH)
        git(world["root"], "branch", "-q", "-D", BRANCH)
    assert run(world, apply=True) == cleanup.REFUSED
    assert "already exists" in capsys.readouterr().err
    assert world["gh"] == []


def dynamic_read(world):
    sample_repo.write(world["root"], {"demo/other.py": "def f(c, n):\n    return c.get_flag(n)\n"})
    sample_repo.commit_and_push(world["root"])


def test_apply_refuses_manual_work_without_a_patch(world, capsys):
    dynamic_read(world)
    assert_refused(world, capsys, "needs a manual edit", apply=True)
    assert "only known at run time" in " ".join(e["status"] for e in logged())


def test_apply_refuses_a_missing_patch(world, capsys, tmp_path):
    assert_refused(world, capsys, "does not exist", apply=True, patch=tmp_path / "none.patch")


# --- failures after the branch exists: never pushed ---------------------------------------

def assert_stopped_unpushed(world, capsys, reason, step, **kwargs):
    assert run(world, apply=True, **kwargs) == cleanup.FAILED
    err = capsys.readouterr().err
    assert reason in err and "NOT pushed" in err
    assert logged()[-1]["action"] == step and logged()[-1]["status"].startswith("failed")
    assert world["gh"] == [] and "cleanup/" not in remote_branches(world)
    assert git(world["root"], "status", "--porcelain") == ""  # your checkout is untouched
    assert git(world["root"], "branch", "--show-current").strip() == "main"


@pytest.mark.parametrize("files, delete, reason", [
    ({"demo/app.py": GOOD_APP, "tool/names.py": "FLAG = None\n"}, ("tests/test_flag.py",),
     "outside the plan"),
    ({"demo/app.py": GOOD_APP + f"# {FLAG}\n"}, ("tests/test_flag.py",), "still referenced"),
    ({"demo/app.py": GOOD_APP}, (), "still referenced"),  # flag-only test file left behind
    ({"demo/app.py": 'def label(client, user):\n    return "Buy now"\n'},
     ("tests/test_flag.py",), "event tracking was removed"),
])
def test_a_patch_is_verified(world, capsys, tmp_path, files, delete, reason):
    patch = patch_for(world, tmp_path, files, delete)
    assert_stopped_unpushed(world, capsys, reason, "cleanup_edit", patch=patch)


def test_a_patch_that_does_not_apply_stops(world, capsys, tmp_path):
    patch = tmp_path / "bad.patch"
    patch.write_text("not a patch\n")
    assert_stopped_unpushed(world, capsys, "git apply", "cleanup_edit", patch=patch)


def test_failing_tests_leave_the_branch_unpushed(world, capsys):
    sample_repo.write(world["root"], {"tests/test_app.py": (
        "import demo.app\n\n\ndef test_fails():\n    assert not demo.app.label\n")})
    sample_repo.commit_and_push(world["root"])
    assert_stopped_unpushed(world, capsys, "tests failed", "cleanup_tests")


def test_a_failed_push_opens_no_pull_request(world, capsys, monkeypatch):
    def fail(root, branch):
        raise repo.RepoError("synthetic push failure")

    monkeypatch.setattr(repo, "push", fail)
    assert run(world, apply=True) == cleanup.FAILED
    assert "not confirmed as pushed" in capsys.readouterr().err
    assert world["gh"] == [] and logged()[-1]["action"] == "cleanup_push"


def test_a_push_that_only_claims_success_opens_no_pull_request(world, monkeypatch):
    real = repo._run

    def run(command, cwd, **kwargs):
        if "push" in command:  # SYNTHETIC: exit code 0, nothing sent
            return subprocess.CompletedProcess(command, 0, "", "error: RPC failed; HTTP 400")
        return real(command, cwd, **kwargs)

    monkeypatch.setattr(repo, "_run", run)
    assert cleanup.cleanup(9, SETTINGS, apply=True, root=world["root"]) == cleanup.FAILED
    assert world["gh"] == [] and logged()[-1]["action"] == "cleanup_push"
    assert logged()[-1]["status"].startswith("failed") and "HTTP 400" in logged()[-1]["status"]


def test_a_failed_pull_request_is_reported(world, capsys):
    world["gh_error"] = "synthetic gh failure"
    assert run(world, apply=True) == cleanup.FAILED
    assert "WAS pushed" in capsys.readouterr().err
    assert logged()[-1]["action"] == "cleanup_pr_create"


# --- success -----------------------------------------------------------------------------

def test_apply_opens_a_verified_pull_request(world, capsys):
    assert run(world, apply=True) == cleanup.OK
    assert BRANCH in remote_branches(world)
    root = world["root"]
    assert git(root, "show", f"{BRANCH}:demo/app.py") == GOOD_APP
    assert git(root, "diff", "--name-status", "main", BRANCH).split() == [
        "M", "demo/app.py", "D", "tests/test_flag.py"]
    assert git(root, "branch", "--show-current").strip() == "main"
    assert git(root, "status", "--porcelain") == ""
    assert git(root, "worktree", "list").count("\n") == 1  # temporary worktree removed

    [(args, body)] = world["gh"]
    assert args[:2] == ("pr", "create") and "merge" not in args
    assert args[args.index("--title") + 1] == f"Remove {FLAG}: ship buy_now (experiment 9)"
    for expected in (
        "rollout_variant: 5", "**SHIP_VARIANT**", "| 8 | chance_to_win | 98.9% |",
        "| buy_now | 313 | 50 | 16.0% | 98.9% |", "experiments/570", "is **kept**",
        "| cleanup_tests |", f"- [ ] after merge: `flagpilot retire {FLAG}`",
    ):
        assert expected in body, expected
    actions = [e["action"] for e in logged()]
    assert actions == ["cleanup_branch", "cleanup_edit", "cleanup_tests", "cleanup_push",
                       "cleanup_pr_create"]


def test_a_patch_can_change_what_the_rewriter_cannot(world, tmp_path):
    dynamic_read(world)
    patch = patch_for(world, tmp_path, {"demo/app.py": GOOD_APP, "demo/other.py": "x = 1\n"})
    assert run(world, apply=True, patch=patch) == cleanup.OK
    assert BRANCH in remote_branches(world)


@pytest.mark.parametrize("snapshot, winner, expected, absent", [
    (True, "buy_now", "**SHIP_VARIANT**, recorded by", "Warning:"),
    (True, "control", "differs from what was rolled out", "not recorded"),
    (False, "buy_now", "**not recorded**", "KEEP_RUNNING"),
])
def test_the_pull_request_is_honest_about_its_evidence(snapshot, winner, expected, absent):
    experiment, exposures, results = real_570.load()
    if not snapshot:  # SYNTHETIC: what the rules see once an experiment is completed
        experiment = {**experiment, "status": "completed", "experiment_rollout": None}
    decision = recommend.decide(experiment, exposures, results, SETTINGS)
    plan = cleanup.Plan(copy.deepcopy(EXPERIMENT), winner, winner, False)
    body = cleanup.pr_body(plan, decision, snapshot, ["demo/app.py"], SETTINGS["cleanup"])
    assert expected in body and absent not in body
    assert ("n/a (completed)" in body) is not snapshot


def test_apply_accepts_a_patch_within_the_plan(world, tmp_path):
    patch = patch_for(world, tmp_path, {
        "demo/app.py": GOOD_APP,
        "tests/test_app.py": "import demo.app\n\n\ndef test_ok():\n    assert demo.app.label\n"})
    assert run(world, apply=True, patch=patch) == cleanup.OK
    assert BRANCH in remote_branches(world)
