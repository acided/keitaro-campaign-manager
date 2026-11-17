"""Thin async client for the Keitaro Admin API.

Payloads are built by the callers; this module owns auth, the User-Agent
(Cloudflare blocks default library UAs) and turning failures into KeitaroError.
"""

import time

import httpx

USER_AGENT = "keitaro-campaign-manager/0.1"
OFFERS_TTL = 120


class KeitaroError(Exception):
    """Keitaro is unreachable or rejected a request. The API layer answers 502."""

    status_code = 502

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def _error_text(response: httpx.Response) -> str:
    """Keitaro errors are {"error": "..."}, validation errors are {"field": "..."}."""
    try:
        body = response.json()
    except ValueError:
        return response.reason_phrase  # e.g. a Cloudflare HTML page
    if isinstance(body, dict):
        if "error" in body:
            return str(body["error"])
        return "; ".join(f"{field}: {msg}" for field, msg in body.items())
    return str(body)


class KeitaroClient:
    def __init__(self, base_url: str, api_key: str):
        self._http = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"Api-Key": api_key, "User-Agent": USER_AGENT},
            timeout=15,
        )
        self._offers: tuple[float, list[dict]] | None = None

    async def close(self) -> None:
        await self._http.aclose()

    async def _call(self, method: str, path: str, **kwargs):
        try:
            response = await self._http.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise KeitaroError(f"Keitaro is unreachable ({type(exc).__name__})") from exc
        if response.is_error:
            raise KeitaroError(
                f"Keitaro {method} {path} failed ({response.status_code}): {_error_text(response)}"
            )
        return response.json()

    # ---------------------------------------------------------------- reference data

    async def offers(self) -> list[dict]:
        """Cached for OFFERS_TTL seconds: Keitaro has no server-side search,
        so autocomplete filters this list on every keystroke."""
        if self._offers is None or time.monotonic() - self._offers[0] > OFFERS_TTL:
            self._offers = (time.monotonic(), await self._call("GET", "/offers"))
        return self._offers[1]

    async def domains(self) -> list[dict]:
        return await self._call("GET", "/domains")

    async def campaign_groups(self) -> list[dict]:
        return await self._call("GET", "/groups", params={"type": "campaigns"})

    async def traffic_sources(self) -> list[dict]:
        return await self._call("GET", "/traffic_sources")

    # ---------------------------------------------------------------- campaigns and streams

    async def campaigns(self) -> list[dict]:
        return await self._call("GET", "/campaigns")

    async def campaign(self, campaign_id: int) -> dict:
        return await self._call("GET", f"/campaigns/{campaign_id}")

    async def create_campaign(self, payload: dict) -> dict:
        return await self._call("POST", "/campaigns", json=payload)

    async def delete_campaign(self, campaign_id: int) -> None:
        """Moves the campaign to Keitaro's archive. Never clean the archive: it is shared."""
        await self._call("DELETE", f"/campaigns/{campaign_id}")

    async def campaign_streams(self, campaign_id: int) -> list[dict]:
        return await self._call("GET", f"/campaigns/{campaign_id}/streams")

    async def create_stream(self, payload: dict) -> dict:
        return await self._call("POST", "/streams", json=payload)

    async def set_stream_offers(self, stream_id: int, offers: list[dict]) -> dict:
        """Keitaro replaces the stream's whole offer list with `offers`."""
        return await self._call("PUT", f"/streams/{stream_id}", json={"offers": offers})
