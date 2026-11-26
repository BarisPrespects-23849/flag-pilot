"""Thin wrapper over Flagsmith CLI v2. Admin calls use the CLI's own credentials."""

import json
import subprocess

from flagpilot.config import ROOT, project_config


class CliError(RuntimeError):
    pass


def run(args: list[str], *, body: object = None, jq: str = ".") -> object:
    command = ["flagsmith", *args, "--no-input", "--jq", jq]
    result = subprocess.run(
        command,
        input=None if body is None else json.dumps(body),
        capture_output=True,
        text=True,
        cwd=ROOT,
        timeout=60,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()[:500]
        raise CliError(f"flagsmith {' '.join(args[:3])} failed: {detail}")
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
