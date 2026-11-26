"""Git, GitHub CLI and test-runner calls used by `cleanup` and `retire`."""

import os
import subprocess
from pathlib import Path

# Talk to the remote as the logged-in `gh` account, not a saved keychain credential.
_CREDENTIALS = ["-c", "credential.helper=", "-c", "credential.helper=!gh auth git-credential"]


class RepoError(RuntimeError):
    pass


def _run(command: list[str], cwd: Path, *, input: str | None = None, ok: tuple = (0,),
         timeout: float = 120) -> subprocess.CompletedProcess:
    result = subprocess.run(command, cwd=cwd, input=input, capture_output=True, text=True,
                            errors="replace", timeout=timeout)
    if result.returncode not in ok:
        detail = (result.stderr or result.stdout).strip()[:500]
        shown = [part for part in command if part != "-c" and not part.startswith("credential.")]
        raise RepoError(f"{' '.join(shown[:3])} failed: {detail}")
    return result


def git(root: Path, *args: str, ok: tuple = (0,)) -> str:
    credentials = _CREDENTIALS if args[0] in ("fetch", "ls-remote", "push") else []
    return _run(["git", *credentials, *args], root, ok=ok).stdout


def push(root: Path, branch: str) -> str:
    """Push the checked-out `branch` and confirm that origin now has local HEAD.

    The exit code of `git push` is not trusted: only what `ls-remote` reports counts.
    Returns the pushed commit, or raises RepoError with what git said.
    """
    current = git(root, "rev-parse", "--abbrev-ref", "HEAD").strip()
    if current != branch:
        raise RepoError(f"'{current}' is checked out, not '{branch}'")
    head = git(root, "rev-parse", "HEAD").strip()
    try:
        result = _run(["git", *_CREDENTIALS, "push", "-u", "origin", branch], root)
        said = result.stderr
    except (RepoError, subprocess.SubprocessError) as error:
        said = str(error)
    said = " ".join(said.split())[-500:] or "nothing"
    try:
        listed = git(root, "ls-remote", "origin", f"refs/heads/{branch}").split()
    except (RepoError, subprocess.SubprocessError) as error:
        raise RepoError(f"push not verified: {error}. git push said: {said}")
    remote = listed[0] if listed else None
    if remote != head:
        raise RepoError(f"push failed: origin/{branch} is at {remote[:7] if remote else 'nothing'}, "
                        f"local HEAD is {head[:7]}. git push said: {said}")
    return head


def gh(root: Path, *args: str, input: str | None = None) -> str:
    return _run(["gh", *args], root, input=input).stdout


def run_tests(root: Path, command: list[str]) -> tuple[bool, str]:
    """Run the test command in `root`. Returns (passed, last lines of its output)."""
    env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
    result = subprocess.run(command, cwd=root, env=env, capture_output=True, text=True,
                            errors="replace", timeout=600)
    tail = "\n".join((result.stdout + result.stderr).strip().splitlines()[-15:])
    return result.returncode == 0, tail
