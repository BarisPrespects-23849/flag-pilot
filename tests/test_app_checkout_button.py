"""Demo shop behaviour that only exists while the flag does.

`flagpilot cleanup` deletes this file together with the flag read.
"""

import pytest
from fastapi.testclient import TestClient

from demo.app import create_app
from flagpilot import config
from tests.stub import Stub
from tests.test_app import client_for

pytestmark = pytest.mark.flag("checkout_button")


def test_exposure_and_purchase_are_flushed_on_shutdown():
    with Stub() as stub:
        with TestClient(create_app(client_for(stub))) as http:
            assert "Buy now" in http.get("/?user_id=user-1").text
            assert "Proceed to checkout" in http.get("/?user_id=user-2").text
            assert http.post("/purchase?user_id=user-1").status_code == 200
        sent = [(e["event"], e["identifier"]) for e in stub.events]
    assert sent == [
        ("$flag_exposure", "user-1"),
        ("$flag_exposure", "user-2"),
        (config.CONVERSION_EVENT, "user-1"),
    ]


def test_serves_control_without_exposure_when_flagsmith_is_down():
    with Stub() as stub:
        factory = client_for(stub, api_url="http://127.0.0.1:1/api/v1/")
        with TestClient(create_app(factory)) as http:
            assert "Proceed to checkout" in http.get("/?user_id=user-1").text
        assert stub.events == []
