from fastapi.testclient import TestClient
from flagsmith import EventProcessorConfig, Flagsmith

from demo.app import create_app, default_flag
from flagpilot import config
from tests.stub import Stub


def client_for(stub: Stub, api_url: str | None = None):
    return lambda: Flagsmith(
        environment_key="ser.stub",
        api_url=api_url or stub.url + "api/v1/",
        enable_events=True,
        event_processor_config=EventProcessorConfig(events_api_url=stub.url),
        default_flag_handler=default_flag,
    )


def test_purchase_is_flushed_on_shutdown():
    with Stub() as stub:
        with TestClient(create_app(client_for(stub))) as http:
            assert http.post("/purchase?user_id=user-1").status_code == 200
        sent = [(e["event"], e["identifier"]) for e in stub.events]
    assert sent == [(config.CONVERSION_EVENT, "user-1")]


def test_user_id_is_escaped_and_required():
    with Stub() as stub:
        with TestClient(create_app(client_for(stub))) as http:
            assert "<script>" not in http.get("/", params={"user_id": "<script>1"}).text
            assert http.get("/").status_code == 422
