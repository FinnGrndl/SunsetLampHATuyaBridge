"""Client for the local Tuya Beacon bridge app."""

from __future__ import annotations

from typing import Any

from aiohttp import ClientError, ClientResponseError, ClientSession, ClientTimeout


class BridgeAPIError(RuntimeError):
    """Bridge request failed."""


class TuyaBeaconAPI:
    """Small local bridge API client."""

    def __init__(self, session: ClientSession, base_url: str, token: str) -> None:
        self._session = session
        self._base_url = base_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {token}"}
        self._timeout = ClientTimeout(total=45)

    async def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            async with self._session.request(
                method,
                f"{self._base_url}{path}",
                headers=self._headers,
                json=payload,
                timeout=self._timeout,
            ) as response:
                data = await response.json(content_type=None)
                if response.status >= 400:
                    raise BridgeAPIError(str(data.get("error", f"HTTP {response.status}")))
                if not isinstance(data, dict):
                    raise BridgeAPIError("bridge returned invalid JSON")
                return data
        except BridgeAPIError:
            raise
        except (ClientError, ClientResponseError, TimeoutError, ValueError) as err:
            raise BridgeAPIError(str(err)) from err

    async def status(self) -> dict[str, Any]:
        return await self._request("GET", "/v1/status")

    async def command(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/v1/command", payload)

