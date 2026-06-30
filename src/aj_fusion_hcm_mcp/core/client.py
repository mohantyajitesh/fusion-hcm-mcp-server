"""The ADF REST client — the single point of contact with Oracle Fusion HCM.

Responsibilities (DESIGN.md §4):
  * inject auth headers; refresh + retry once on 401
  * back off and retry on 429/503, honoring ``Retry-After``
  * default ``onlyData=true`` and a bounded ``limit`` to protect context
  * strip HATEOAS ``links`` (a large token sink) unless explicitly requested
  * normalize Oracle error envelopes into :class:`HcmApiError`
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from ..auth.base import AuthProvider
from .errors import HcmApiError

_MAX_RETRIES = 3
_MAX_BACKOFF_SECONDS = 30.0


def _strip_links(obj: Any) -> Any:
    """Recursively drop Oracle HATEOAS ``links`` keys."""
    if isinstance(obj, dict):
        return {k: _strip_links(v) for k, v in obj.items() if k != "links"}
    if isinstance(obj, list):
        return [_strip_links(v) for v in obj]
    return obj


class HcmClient:
    def __init__(
        self,
        base_url: str,
        rest_version: str,
        auth: AuthProvider,
        *,
        default_limit: int = 25,
        max_limit: int = 500,
        timeout: float = 60.0,
        include_links: bool = False,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._version = rest_version
        self._auth = auth
        self._default_limit = default_limit
        self._max_limit = max_limit
        self._include_links = include_links
        self._client = httpx.AsyncClient(timeout=timeout)

    async def aclose(self) -> None:
        await self._client.aclose()

    # ---- URL construction -------------------------------------------------

    def _url(self, resource: str, key: str | None = None, suffix: str | None = None) -> str:
        url = f"{self._base}/hcmRestApi/resources/{self._version}/{resource}"
        if key is not None:
            url += f"/{key}"
        if suffix is not None:
            url += f"/{suffix}"
        return url

    # ---- core request with retry semantics --------------------------------

    async def _request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any | None = None,
        _retry_auth: bool = True,
        _attempt: int = 0,
    ) -> Any:
        headers = await self._auth.headers()
        headers.setdefault("Content-Type", "application/json")
        try:
            resp = await self._client.request(
                method, url, params=params, json=json, headers=headers
            )
        except httpx.RequestError as exc:
            raise HcmApiError(status=0, title="network_error", detail=str(exc)) from exc

        if resp.status_code == 401 and _retry_auth:
            await self._auth.refresh()
            return await self._request(
                method, url, params=params, json=json, _retry_auth=False, _attempt=_attempt
            )

        if resp.status_code in (429, 503) and _attempt < _MAX_RETRIES:
            await asyncio.sleep(self._retry_after(resp, _attempt))
            return await self._request(
                method, url, params=params, json=json, _retry_auth=_retry_auth, _attempt=_attempt + 1
            )

        if resp.status_code >= 400:
            raise self._to_error(resp)

        if not resp.content:
            return {}
        return resp.json()

    @staticmethod
    def _retry_after(resp: httpx.Response, attempt: int) -> float:
        header = resp.headers.get("Retry-After")
        if header:
            try:
                return float(header)
            except ValueError:
                pass
        return min(2.0**attempt, _MAX_BACKOFF_SECONDS)

    @staticmethod
    def _to_error(resp: httpx.Response) -> HcmApiError:
        title = detail = errorpath = None
        try:
            body = resp.json()
        except ValueError:
            body = None
        if isinstance(body, dict):
            title = body.get("title")
            detail = body.get("detail")
            errorpath = body.get("o:errorPath") or body.get("errorPath")
        if detail is None and not isinstance(body, dict):
            detail = (resp.text or "").strip()[:500] or None
        return HcmApiError(resp.status_code, title=title, detail=detail, errorpath=errorpath)

    # ---- read operations --------------------------------------------------

    async def query(
        self,
        resource: str,
        *,
        q: str | None = None,
        fields: list[str] | None = None,
        expand: list[str] | None = None,
        order_by: str | None = None,
        limit: int | None = None,
        offset: int = 0,
        total_results: bool = False,
        only_data: bool = True,
    ) -> dict[str, Any]:
        effective_limit = min(limit or self._default_limit, self._max_limit)
        params: dict[str, Any] = {"limit": effective_limit, "offset": offset}
        if only_data:
            params["onlyData"] = "true"
        if q:
            params["q"] = q
        if fields:
            params["fields"] = ",".join(fields)
        if expand:
            params["expand"] = ",".join(expand)
        if order_by:
            params["orderBy"] = order_by
        if total_results:
            params["totalResults"] = "true"

        data = await self._request("GET", self._url(resource), params=params)
        items = data.get("items", [])
        if not self._include_links:
            items = [_strip_links(item) for item in items]
        return {
            "items": items,
            "count": data.get("count", len(items)),
            "has_more": data.get("hasMore", False),
            "total": data.get("totalResults"),
        }

    async def get_record(
        self,
        resource: str,
        key: str,
        *,
        fields: list[str] | None = None,
        expand: list[str] | None = None,
        only_data: bool = True,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if only_data:
            params["onlyData"] = "true"
        if fields:
            params["fields"] = ",".join(fields)
        if expand:
            params["expand"] = ",".join(expand)
        data = await self._request("GET", self._url(resource, key), params=params)
        return data if self._include_links else _strip_links(data)

    async def describe(self, resource: str) -> dict[str, Any]:
        return await self._request("GET", self._url(resource, suffix="describe"))

    async def classify_module(self, probe_resource: str) -> str:
        """Probe one representative resource for capability discovery (§12.3).

        Returns ``provisioned`` / ``not_provisioned`` / ``no_access``.
        """
        try:
            await self.query(probe_resource, limit=1)
        except HcmApiError as exc:
            if exc.status == 404:
                return "not_provisioned"
            if exc.status in (401, 403):
                return "no_access"
            # network failure (0) or server error (5xx) — transient/unknown
            return "unreachable"
        return "provisioned"
