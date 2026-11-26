"""`recommend --refresh`, with Flagsmith faked."""

import json
import subprocess

import pytest

from flagpilot import flagsmith_cli as cli
from flagpilot import lifecycle, main, recommend
from tests import real_570

REAL_STATUS_ONLY = cli.status_only  # kept before any test fakes it


def fake(monkeypatch):
    posts, as_of = [], iter(["old", "new", "new"])
    monkeypatch.setattr(recommend, "fetch", lambda experiment_id: real_570.load())
    monkeypatch.setattr(recommend.cli, "get", lambda path, jq=".": (
        next(as_of) if jq == ".results.as_of" else {"id": 570, "status": "running"}))
    monkeypatch.setattr(lifecycle.provision.cli, "status_only",
                        lambda args: posts.append(args[1].split("/570/")[1]) or {"http_status": 202})
    return posts


def test_refresh_posts_both_and_keeps_json_stdout_clean(monkeypatch, capsys):
    posts = fake(monkeypatch)
    assert main.main(["recommend", "570", "--refresh", "--json"]) == 0
    assert posts == ["exposures/refresh/", "results/refresh/"]
    assert json.loads(capsys.readouterr().out)["verdict"] == "SHIP_VARIANT"


def test_second_refresh_within_five_minutes_skips_results(monkeypatch, capsys):
    posts = fake(monkeypatch)
    main.main(["recommend", "570", "--refresh", "--json"])
    posts.clear()
    assert main.main(["recommend", "570", "--refresh", "--json"]) == 0
    assert posts == ["exposures/refresh/"]
    assert "results-refresh skipped" in capsys.readouterr().err


# The message Flagsmith returned for experiment 592, 12 s after an earlier refresh.
TOO_SOON = (
    '{"detail":"A refresh was requested recently. Try again later. Expected available in '
    '288 seconds."}\nError: POST https://api.flagsmith.com/x/refresh/ returned 429 '
    "Too Many Requests\n"
)


@pytest.mark.parametrize("limited", ["exposures", "results"])
def test_a_429_on_one_refresh_skips_only_that_step(monkeypatch, capsys, limited):
    posts = fake(monkeypatch)
    accept = lifecycle.provision.cli.status_only

    def run(command, **kwargs):
        return subprocess.CompletedProcess(command, 1, "", TOO_SOON)

    def status_only(args):
        if f"/{limited}/refresh/" not in args[1]:
            return accept(args)
        with monkeypatch.context() as patch:
            patch.setattr(cli.subprocess, "run", run)
            return REAL_STATUS_ONLY(args)

    monkeypatch.setattr(lifecycle.provision.cli, "status_only", status_only)
    assert main.main(["recommend", "570", "--refresh", "--json"]) == 0
    other = "results" if limited == "exposures" else "exposures"
    assert posts == [f"{other}/refresh/"]
    out = capsys.readouterr()
    assert f"{limited}-refresh skipped" in out.err and "288 seconds" in out.err
    assert json.loads(out.out)["verdict"] == "SHIP_VARIANT"


def test_other_refresh_errors_still_stop_the_command(monkeypatch, capsys):
    fake(monkeypatch)

    def broken(args):
        raise cli.CliError("returned 500 Internal Server Error")

    monkeypatch.setattr(lifecycle.provision.cli, "status_only", broken)
    assert main.main(["recommend", "570", "--refresh", "--json"]) == 1
    assert capsys.readouterr().out == ""
