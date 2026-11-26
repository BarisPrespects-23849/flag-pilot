import subprocess

import pytest

from flagpilot import flagsmith_cli as cli


def fake(monkeypatch, returncode=0, stdout="", stderr=""):
    monkeypatch.setattr(cli.subprocess, "run", lambda command, **k: subprocess.CompletedProcess(
        command, returncode, stdout, stderr))


def test_empty_body_success_is_judged_by_status(monkeypatch):
    fake(monkeypatch, stdout="HTTP/2.0 202 Accepted\nContent-Length: 0\n\n")
    assert cli.status_only(["api", "x/", "-X", "POST"]) == {"http_status": 202}


@pytest.mark.parametrize("stdout", ["", "HTTP/2.0 429 Too Many Requests\n\n"])
def test_missing_or_error_status_fails(monkeypatch, stdout):
    fake(monkeypatch, stdout=stdout)
    with pytest.raises(cli.CliError):
        cli.status_only(["api", "x/", "-X", "POST"])


def test_errors_do_not_echo_the_environment_key(monkeypatch):
    key = cli.project_config()["environment"]
    fake(monkeypatch, returncode=1, stderr=f"Error: POST .../{key}/x returned 404")
    with pytest.raises(cli.CliError) as error:
        cli.run(["api", f"environments/{key}/x"])
    assert key not in str(error.value)
