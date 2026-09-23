"""Small token-authenticated HTTP API for the Home Assistant integration."""

from __future__ import annotations

import hmac
import json
import logging
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .bridge import BridgeError, NotReadyError, TuyaBeaconBridge
from .mgmt import MgmtError

_LOGGER = logging.getLogger(__name__)
_MAX_BODY = 4096


class BridgeHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], bridge: TuyaBeaconBridge) -> None:
        self.bridge = bridge
        super().__init__(address, BridgeRequestHandler)


class BridgeRequestHandler(BaseHTTPRequestHandler):
    server: BridgeHTTPServer
    protocol_version = "HTTP/1.1"
    server_version = "TuyaBeaconBridge/0.3"

    def log_message(self, message: str, *args: object) -> None:
        rendered = message % args
        logger = _LOGGER.debug if '"GET /v1/status ' in rendered else _LOGGER.info
        logger("API %s - %s", self.client_address[0], rendered)

    def _authorized(self) -> bool:
        supplied = self.headers.get("Authorization", "")
        expected = f"Bearer {self.server.bridge.config.api_token}"
        return hmac.compare_digest(supplied, expected)

    def _json(self, status: HTTPStatus, value: dict[str, Any]) -> None:
        encoded = json.dumps(value, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(encoded)

    def _body(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as err:
            raise ValueError("invalid Content-Length") from err
        if not 0 <= length <= _MAX_BODY:
            raise ValueError("request body is too large")
        if length == 0:
            return {}
        value = json.loads(self.rfile.read(length))
        if not isinstance(value, dict):
            raise TypeError("JSON request body must be an object")
        return value

    def do_GET(self) -> None:
        if self.path == "/health":
            self._json(HTTPStatus.OK, {"ok": True})
            return
        if not self._authorized():
            self._json(HTTPStatus.UNAUTHORIZED, {"ok": False, "error": "unauthorized"})
            return
        try:
            if self.path == "/v1/status":
                self._json(HTTPStatus.OK, self.server.bridge.status())
            elif self.path == "/v1/capabilities":
                self._json(HTTPStatus.OK, {"ok": True, **self.server.bridge.capabilities()})
            else:
                self._json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not found"})
        except MgmtError as err:
            self._json(HTTPStatus.SERVICE_UNAVAILABLE, {"ok": False, "error": str(err)})

    def do_POST(self) -> None:
        if not self._authorized():
            self._json(HTTPStatus.UNAUTHORIZED, {"ok": False, "error": "unauthorized"})
            return
        try:
            body = self._body()
            if self.path == "/v1/command":
                result = self.server.bridge.command(body)
            else:
                self._json(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not found"})
                return
            self._json(HTTPStatus.OK, result)
        except (TypeError, ValueError, json.JSONDecodeError) as err:
            self._json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(err)})
        except NotReadyError as err:
            self._json(HTTPStatus.CONFLICT, {"ok": False, "error": str(err)})
        except (MgmtError, BridgeError) as err:
            self._json(HTTPStatus.SERVICE_UNAVAILABLE, {"ok": False, "error": str(err)})
