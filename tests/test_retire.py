"""Retire on a SYNTHETIC repository and experiments. Git is real; Flagsmith and GitHub
are faked."""

import json

import pytest

from flagpilot import audit, repo, retire, settings
from flagpilot import flagsmith_cli as cli
from tests import sample_repo
from tests.sample_repo import FLAG

SETTINGS = {**settings.load(), "cleanup": sample_repo.SETTINGS_CLEANUP}
CLEAN = {**sample_repo.FILES, "demo/app.py": "def label():\n    return 1\n"}
del CLEAN["tests/test_flag.py"]


@pytest.fixture
def world(monkeypatch, tmp_path):
    state = {
        "root": sample_repo.make(tmp_path, CLEAN),
        "flag": {"id": 1, "name": FLAG, "is_archived": False},
        "listing": {"next": False, "results": [
            {"id": 9, "status": "completed", "feature": FLAG},
            {"id": 10, "status": "running", "feature": "another"}]},
        "experiment": {"rollout_decision": "variant", "rollout_variant": 5,
                       "options": [{"id": 5, "key": "buy_now"}]},
        "pr": {"state": "MERGED", "baseRefName": "main", "url": "https://example.invalid/1"},
        "gh": [], "archives": [], "archive_error": None, "archive_works": True,
    }
    monkeypatch.setattr(retire, "find_flag", lambda flag: state["flag"])
    monkeypatch.setattr(retire, "read_experiments", lambda: state["listing"])
    monkeypatch.setattr(retire, "read_experiment", lambda eid: state["experiment"])

    def gh(root, *args, input=None):
        state["gh"].append(args)
        if state["pr"] is None:
            raise repo.RepoError("no pull requests found (synthetic)")
        return json.dumps(state["pr"])

    def execute(args):
        state["archives"].append(args)
        if state["archive_error"]:
            raise state["archive_error"]
        if state["archive_works"]:
            state["flag"] = {**state["flag"], "is_archived": True}

    monkeypatch.setattr(repo, "gh", gh)
    monkeypatch.setattr(cli, "execute", execute)
    return state


def run(world, **kwargs):
    return retire.retire(FLAG, SETTINGS, root=world["root"], **{"apply": False, **kwargs})


def logged():
    return [json.loads(line) for line in audit.AUDIT_PATH.read_text().splitlines()]


def assert_refused(world, capsys, reason, **kwargs):
    kwargs = {"apply": True, "confirm": FLAG, **kwargs}
    assert run(world, **kwargs) == retire.REFUSED
    assert reason in capsys.readouterr().err
    assert world["archives"] == []
    assert logged()[-1]["action"] == "retire_refused"


def test_dry_run_changes_nothing(world, capsys):
    assert run(world) == retire.OK
    out = capsys.readouterr().out
    assert "feature update demo_flag --archive" in out and "tool/names.py" in out
    assert world["archives"] == []
    assert logged()[-1]["action"] == "feature_archive" and logged()[-1]["dry_run"]


def test_apply_archives_verifies_and_audits_every_step(world, capsys):
    assert run(world, apply=True, confirm=FLAG) == retire.OK
    assert world["archives"] == [["feature", "update", FLAG, "--archive"]]
    assert world["gh"][0][:3] == ("pr", "view", f"cleanup/{FLAG}-buy_now")
    assert [e["action"] for e in logged()] == [
        "retire_check_experiment", "retire_check_pr", "retire_check_references",
        "feature_archive", "retire_verify"]
    assert logged()[3]["approved_by"] == "user" and logged()[3]["tier"] == 3
    assert "verified" in capsys.readouterr().out


def test_no_code_skips_only_the_pull_request(world):
    world["pr"] = None
    assert run(world, apply=True, confirm=FLAG, no_code=True) == retire.OK
    assert world["gh"] == []


@pytest.mark.parametrize("flag, reason", [
    (None, "was not found"),
    ({"id": 1, "name": FLAG, "is_archived": True}, "already archived"),
])
def test_refuses_a_missing_or_archived_flag(world, capsys, flag, reason):
    world["flag"] = flag
    assert_refused(world, capsys, reason)


@pytest.mark.parametrize("listing, reason", [
    ({"next": True, "results": []}, "more experiments than one page"),
    ({"next": False, "results": []}, "no experiment uses"),
    ({"next": False, "results": [{"id": 9, "status": "running", "feature": FLAG}]},
     "experiment 9 is 'running'"),
    ({"next": False, "results": [{"id": 9, "status": "completed", "feature": FLAG},
                                 {"id": 11, "status": "created", "feature": FLAG}]},
     "experiment 11 is 'created'"),
])
@pytest.mark.parametrize("no_code", [False, True])
def test_refuses_unless_every_experiment_is_completed(world, capsys, listing, reason, no_code):
    world["listing"] = listing
    assert_refused(world, capsys, reason, no_code=no_code)


@pytest.mark.parametrize("pr, reason", [
    (None, "no cleanup pull request could be read"),
    ({"state": "OPEN", "baseRefName": "main", "url": "u"}, "is OPEN, not MERGED"),
    ({"state": "CLOSED", "baseRefName": "main", "url": "u"}, "is CLOSED, not MERGED"),
    ({"state": "MERGED", "baseRefName": "dev", "url": "u"}, "merged into 'dev'"),
])
def test_refuses_without_a_merged_cleanup_pull_request(world, capsys, pr, reason):
    world["pr"] = pr
    assert_refused(world, capsys, reason)


def test_refuses_when_there_is_no_winner_to_look_for(world, capsys):
    world["experiment"]["rollout_decision"] = "disable"
    assert_refused(world, capsys, "no control or variant winner")


@pytest.mark.parametrize("files", [
    {"demo/app.py": sample_repo.FILES["demo/app.py"]},
    {"demo/app.py": "def f(c, name):\n    return c.get_flag(name)\n"},
    {"demo/page.html": f"<!-- {FLAG} -->\n"},
    {"tests/test_flag.py": sample_repo.FILES["tests/test_flag.py"]},
])
@pytest.mark.parametrize("no_code", [False, True])
def test_refuses_while_main_references_the_flag(world, capsys, files, no_code):
    sample_repo.write(world["root"], files)
    sample_repo.commit_and_push(world["root"])
    assert_refused(world, capsys, "still references", no_code=no_code)


def test_checks_origin_main_not_the_local_checkout(world, capsys):
    root = world["root"]
    sample_repo.write(root, {"demo/app.py": sample_repo.FILES["demo/app.py"]})
    sample_repo.commit_and_push(root)
    sample_repo.write(root, {"demo/app.py": CLEAN["demo/app.py"]})  # removed only locally
    assert_refused(world, capsys, "origin/main still references")


def test_refuses_when_main_cannot_be_fetched(world, capsys):
    sample_repo.git(world["root"], "remote", "set-url", "origin", "/nonexistent/repo.git")
    assert_refused(world, capsys, "could not check origin/main")


def test_refuses_when_flagsmith_cannot_be_read(world, capsys, monkeypatch):
    def fail():
        raise cli.CliError("synthetic outage")

    monkeypatch.setattr(retire, "read_experiments", fail)
    assert_refused(world, capsys, "synthetic outage")


@pytest.mark.parametrize("confirm", ["yes", FLAG.upper(), f"{FLAG} ", ""])
def test_apply_needs_the_exact_flag_name(world, capsys, confirm):
    assert_refused(world, capsys, "does not match", confirm=confirm)


def test_apply_without_a_terminal_or_confirm_is_refused(world, capsys, monkeypatch):
    monkeypatch.setattr(retire.sys.stdin, "isatty", lambda: False, raising=False)
    assert_refused(world, capsys, "no terminal", confirm=None, prompt=pytest.fail)


def test_apply_prompts_for_the_name_on_a_terminal(world, monkeypatch):
    monkeypatch.setattr(retire.sys.stdin, "isatty", lambda: True, raising=False)
    assert run(world, apply=True, prompt=lambda text: "no") == retire.REFUSED
    assert world["archives"] == []
    assert run(world, apply=True, prompt=lambda text: FLAG) == retire.OK


def test_a_failed_archive_is_reported_and_not_retried(world, capsys):
    world["archive_error"] = cli.CliError("synthetic")
    assert run(world, apply=True, confirm=FLAG) == retire.FAILED
    assert len(world["archives"]) == 1 and logged()[-1]["status"] == "failed"


def test_an_unconfirmed_archive_is_not_reported_as_done(world, capsys):
    world["archive_works"] = False
    assert run(world, apply=True, confirm=FLAG) == retire.FAILED
    output = capsys.readouterr()
    assert "NOT VERIFIED" in output.err and "Archived" not in output.out
