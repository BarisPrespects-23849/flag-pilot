"""`recommend --refresh`, with Flagsmith faked."""

import json

from flagpilot import lifecycle, main, recommend
from tests import real_570


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
