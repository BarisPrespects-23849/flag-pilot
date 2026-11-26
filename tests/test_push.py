"""A push counts as done only when origin has local HEAD. Real git, local bare remote."""

import json
import subprocess

import pytest

from flagpilot import audit, push, repo
from tests import sample_repo
from tests.sample_repo import git

# What was seen for real: an error, then a claim that all is well, and exit code 0.
LIE = ("error: RPC failed; HTTP 400 curl 22 The requested URL returned error: 400\n"
       "fatal: the remote end hung up unexpectedly\nEverything up-to-date\n")


@pytest.fixture
def root(tmp_path):
    root = sample_repo.make(tmp_path)
    sample_repo.write(root, {"new.txt": "x\n"})
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "to push")
    return root


def head(root) -> str:
    return git(root, "rev-parse", "HEAD").strip()


def remote_head(root) -> str:
    return git(root, "ls-remote", "origin", "refs/heads/main").split()[0]


def logged():
    return [json.loads(line) for line in audit.AUDIT_PATH.read_text().splitlines()]


def apply(root, *extra):
    return push.main(["--apply", "--approved-by", "test", *extra], root=root)


def fake_push(monkeypatch, returncode: int, stderr: str, *, really: bool = False):
    real = repo._run

    def run(command, cwd, **kwargs):
        if "push" not in command:
            return real(command, cwd, **kwargs)
        if really:
            real(command, cwd, **kwargs)
        if returncode:
            raise repo.RepoError(f"git push failed: {stderr}")
        return subprocess.CompletedProcess(command, 0, "", stderr)

    monkeypatch.setattr(repo, "_run", run)


def test_success_is_logged_once_origin_has_head(root, capsys):
    assert apply(root) == 0
    assert remote_head(root) == head(root)
    [entry] = logged()
    assert entry["status"] == "success" and not entry["dry_run"]
    assert "Pushed and verified" in capsys.readouterr().out


def test_exit_code_zero_without_an_updated_remote_is_a_failure(root, monkeypatch, capsys):
    before = remote_head(root)
    fake_push(monkeypatch, 0, LIE)
    assert apply(root) == 1
    assert remote_head(root) == before
    [entry] = logged()
    assert entry["status"].startswith("failed: push failed")
    assert "HTTP 400" in entry["status"]
    assert "Pushed" not in capsys.readouterr().out


def test_a_rejected_push_is_logged_with_the_error(root, tmp_path):
    hook = tmp_path / "remote.git" / "hooks" / "pre-receive"
    hook.write_text("#!/bin/sh\necho 'synthetic rejection' >&2\nexit 1\n")
    hook.chmod(0o755)
    assert apply(root) == 1
    [entry] = logged()
    assert entry["status"].startswith("failed") and "synthetic rejection" in entry["status"]


def test_an_error_is_forgiven_only_if_origin_really_has_head(root, monkeypatch):
    fake_push(monkeypatch, 1, "connection lost after the update (synthetic)", really=True)
    assert apply(root) == 0
    assert logged()[-1]["status"] == "success"


def test_an_unreachable_remote_is_not_success(root):
    git(root, "remote", "set-url", "origin", "/nonexistent/repo.git")
    assert apply(root) == 1
    assert logged()[-1]["status"].startswith("failed: push not verified")


def test_refuses_a_branch_that_is_not_checked_out(root):
    git(root, "switch", "-q", "-c", "other")
    assert apply(root) == 1
    assert "'other' is checked out" in logged()[-1]["status"]


def test_dry_run_pushes_nothing(root, capsys):
    before = remote_head(root)
    assert push.main([], root=root) == 0
    assert remote_head(root) == before
    assert "to push" in capsys.readouterr().out
    assert logged()[-1]["status"] == "planned" and logged()[-1]["dry_run"]


def test_apply_requires_an_approver(root):
    with pytest.raises(SystemExit):
        push.main(["--apply"], root=root)
