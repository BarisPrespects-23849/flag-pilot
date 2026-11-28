"""Demo shop with one flagged feature: the checkout button.

    uvicorn demo.app:app --port 8800
    open http://127.0.0.1:8800/?user_id=alice
"""

from contextlib import asynccontextmanager
from html import escape
from typing import Annotated, Callable
from urllib.parse import quote

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse
from flagsmith import Flagsmith
from flagsmith.models import DefaultFlag

from flagpilot import config

UserId = Annotated[str, Query(min_length=1, max_length=200)]


def default_flag(feature_name: str) -> DefaultFlag:
    """Served if Flagsmith is unreachable. Records no exposure."""
    return DefaultFlag(enabled=False, value=config.CONTROL_VALUE)


def make_client() -> Flagsmith:
    # Default event buffering: this process is long-lived and serves concurrent
    # requests. close() on shutdown sends whatever is still buffered.
    return Flagsmith(
        environment_key=config.server_key(),
        enable_events=True,
        default_flag_handler=default_flag,
    )


def checkout_label(client: Flagsmith, user_id: str) -> str:
    return "Buy now"


def create_app(client_factory: Callable[[], Flagsmith] = make_client) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.flagsmith = client_factory()
        try:
            yield
        finally:
            app.state.flagsmith.close()  # flush buffered events before exit

    app = FastAPI(title="Flag Pilot demo shop", lifespan=lifespan)

    # Plain `def` routes: the SDK blocks on HTTP, so FastAPI runs them in a threadpool.
    @app.get("/", response_class=HTMLResponse)
    def checkout(request: Request, user_id: UserId):
        label = checkout_label(request.app.state.flagsmith, user_id)
        return (
            f"<h1>Your cart</h1><p>Signed in as {escape(user_id)}</p>"
            f'<form method="post" action="/purchase?user_id={escape(quote(user_id, safe=""))}">'
            f"<button>{label}</button></form>"
        )

    @app.post("/purchase", response_class=HTMLResponse)
    def purchase(request: Request, user_id: UserId):
        # Same identifier as the exposure, exact event name from the metric.
        request.app.state.flagsmith.track_event(config.CONVERSION_EVENT, identifier=user_id)
        return "<h1>Thanks for your order</h1>"

    return app


app = create_app()
