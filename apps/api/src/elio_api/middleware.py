import uuid

import structlog
from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class RequestContextMiddleware:
    """ASGI middleware: attach and propagate X-Correlation-ID on every HTTP request."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.logger = structlog.get_logger("elio.request")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        incoming = headers.get("X-Correlation-ID")
        correlation_id = incoming if incoming else str(uuid.uuid4())
        scope.setdefault("state", {})["correlation_id"] = correlation_id

        structlog.contextvars.bind_contextvars(correlation_id=correlation_id)

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)["X-Correlation-ID"] = correlation_id
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            structlog.contextvars.clear_contextvars()
