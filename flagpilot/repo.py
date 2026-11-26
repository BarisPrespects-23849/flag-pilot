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


def push(root: Path, branch: str) -> None:
    git(root, "push", "-u", "origin", branch)


def gh(root: Path, *args: str, input: str | None = None) -> str:
    return _run(["gh", *args], root, input=input).stdout


def run_tests(root: Path, command: list[str]) -> tuple[bool, str]:
    """Run the test command in `root`. Returns (passed, last lines of its output)."""
    env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
    result = subprocess.run(command, cwd=root, env=env, capture_output=True, text=True,
                            errors="replace", timeout=600)
    tail = "\n".join((result.stdout + result.stderr).strip().splitlines()[-15:])
    return result.returncode == 0, tail
