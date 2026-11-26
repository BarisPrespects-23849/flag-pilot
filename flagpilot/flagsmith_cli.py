"""Thin wrapper over Flagsmith CLI v2. Admin calls use the CLI's own credentials."""

import json
import re
import subprocess

from flagpilot.config import ROOT, project_config


class CliError(RuntimeError):
    pass


class RateLimited(CliError):
    """Flagsmith answered 429: the same request will be accepted later."""


def _execute(args: list[str], body: object = None) -> subprocess.CompletedProcess:
    result = subprocess.run(
        ["flagsmith", *args, "--no-input"],
        input=None if body is None else json.dumps(body),
        capture_output=True,
        text=True,
        cwd=ROOT,
        timeout=60,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()[:500]
        limited = "429 Too Many Requests" in f"{result.stderr}{result.stdout}"
        error = RateLimited if limited else CliError
        raise error(redact(f"flagsmith {' '.join(args[:3])} failed: {detail}"))
    return result


def status_only(args: list[str]) -> dict:
    """For `api` calls that may answer with an empty body, which --jq rejects."""
    first_line = (_execute([*args, "-i"]).stdout.splitlines() or [""])[0]
    match = re.match(r"HTTP/\S+ (\d{3})", first_line)
    if not match or not match.group(1).startswith("2"):
        raise CliError(f"Unexpected response status: {first_line[:100]!r}")
    return {"http_status": int(match.group(1))}


def run(args: list[str], *, body: object = None, jq: str = ".") -> object:
    result = _execute([*args, "--jq", jq], body)
    output = result.stdout.strip()
    if not output:
        return None
    try:
        return json.loads(output)
    except json.JSONDecodeError:
        return output  # --jq prints bare strings unquoted


def env_path(suffix: str) -> str:
    return f"api/v1/environments/{project_config()['environment']}/{suffix}"


def redact(text: str) -> str:
    return text.replace(project_config()["environment"], "<env_key>")


def get(path: str, jq: str = ".") -> object:
    return run(["api", path], jq=jq)
