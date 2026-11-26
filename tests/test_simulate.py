import pytest

from flagpilot import config, simulate
from tests.stub import Stub

RATES = {config.CONTROL_VALUE: 0.5, config.VARIANT_VALUE: 0.5}


def test_every_event_is_delivered_with_matching_identifiers():
    ids = simulate.user_ids(60, "t")
    with Stub() as stub:
        sent = simulate.simulate(simulate.make_client(**stub.client_args()), ids, RATES, seed=1)

    exposures = [e for e in stub.events if e["event"] == "$flag_exposure"]
    purchases = [e for e in stub.events if e["event"] == config.CONVERSION_EVENT]
    assert [e["identifier"] for e in exposures] == ids
    assert all(e["feature_name"] == config.FLAG_NAME for e in exposures)
    assert {e["identifier"] for e in purchases} <= set(ids)
    assert 0 < len(purchases) == sum(n for k, n in sent.items() if k.startswith("converted:"))
    assert len(stub.events) == len(exposures) + len(purchases)


def test_no_events_when_identity_is_not_in_a_running_experiment():
    with Stub(in_experiment=False) as stub:
        sent = simulate.simulate(
            simulate.make_client(**stub.client_args()), simulate.user_ids(5, "t"), RATES, seed=1
        )
    assert stub.events == []
    assert sent == {"not_enrolled": 5}


def test_stops_when_the_events_api_rejects_a_batch():
    with Stub(events_status=400) as stub:
        client = simulate.make_client(**stub.client_args())
        with pytest.raises(simulate.DeliveryError):
            simulate.simulate(client, simulate.user_ids(5, "t"), RATES, seed=1)


def test_a_retried_send_is_reported_but_does_not_stop_the_run():
    warnings: list[str] = []
    with Stub(failures_first=1) as stub:
        sent = simulate.simulate(
            simulate.make_client(**stub.client_args()), simulate.user_ids(3, "t"), RATES,
            seed=1, sdk_warnings=warnings,
        )
    assert sum(n for k, n in sent.items() if k.startswith("exposed:")) == 3
    assert len(warnings) == 1 and warnings[0].startswith(simulate.RETRY_WARNING)


def test_dry_run_sends_nothing(monkeypatch, tmp_path):
    monkeypatch.setattr(simulate.audit, "AUDIT_PATH", tmp_path / "audit.jsonl")
    monkeypatch.setattr(simulate, "make_client", lambda: pytest.fail("client created"))
    assert simulate.main(["--users", "3"]) == 0
    assert '"dry_run": true' in (tmp_path / "audit.jsonl").read_text()


def test_apply_is_blocked_unless_experiment_is_running(monkeypatch, tmp_path):
    monkeypatch.setattr(simulate.audit, "AUDIT_PATH", tmp_path / "audit.jsonl")
    monkeypatch.setattr(simulate.provision, "experiments", lambda: [
        {"name": config.EXPERIMENT_NAME, "status": "created"}])
    monkeypatch.setattr(simulate, "make_client", lambda: pytest.fail("client created"))
    assert simulate.main(["--apply", "--approved-by", "test"]) == 1
