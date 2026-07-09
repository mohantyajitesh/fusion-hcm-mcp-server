"""Shared test fakes: an in-memory MCP registry, a scriptable client, audit, auth."""

from __future__ import annotations

from typing import Any, Callable

from aj_fusion_hcm_mcp.config import Config
from aj_fusion_hcm_mcp.context import ServerContext
from aj_fusion_hcm_mcp.core.catalog import Catalog
from aj_fusion_hcm_mcp.safety.redaction import Redactor


class FakeMCP:
    """Captures @tool-decorated functions so tests can call them directly."""

    def __init__(self) -> None:
        self.tools: dict[str, Callable[..., Any]] = {}

    def tool(self, *args: Any, **kwargs: Any) -> Callable[[Callable], Callable]:
        def deco(fn: Callable) -> Callable:
            self.tools[fn.__name__] = fn
            return fn

        return deco


class FakeAudit:
    enabled = True

    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def record(self, **kwargs: Any) -> None:
        self.records.append(kwargs)


class DummyAuth:
    async def headers(self) -> dict[str, str]:
        return {}

    async def refresh(self) -> None:
        return None


_DEFAULTS: dict[str, Any] = {
    "query": {"items": [], "count": 0, "has_more": False, "total": None},
    "get_record": {},
    "get_href": {},
    "describe": {},
    "describe_catalog": {},
    "create": {},
    "update": {},
    "delete": {},
    "invoke_action": {},
    "atom_feed": "",
    "classify_module": "provisioned",
}

_REDACTABLE = {"query", "get_record", "get_href"}


class FakeClient:
    """Scriptable stand-in for HcmClient. Mimics the redaction floor."""

    def __init__(self, redactor: Redactor | None = None) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.redactor = redactor
        self.handlers: dict[str, Callable[..., Any]] = {}

    def set(self, method: str, fn: Callable[..., Any]) -> None:
        self.handlers[method] = fn

    async def _call(self, method: str, redact: bool = True, **kw: Any) -> Any:
        self.calls.append((method, kw))
        fn = self.handlers.get(method)
        value = fn(**kw) if fn else _DEFAULTS[method]
        if redact and self.redactor is not None and method in _REDACTABLE:
            value = self.redactor.redact(value)
        return value

    async def query(self, resource: str, *, redact: bool = True, **kw: Any) -> Any:
        return await self._call("query", redact=redact, resource=resource, **kw)

    async def get_record(self, resource: str, key: str, *, redact: bool = True, **kw: Any) -> Any:
        return await self._call("get_record", redact=redact, resource=resource, key=key, **kw)

    async def get_href(self, href: str, *, redact: bool = True, **kw: Any) -> Any:
        return await self._call("get_href", redact=redact, href=href, **kw)

    async def describe(self, resource: str) -> Any:
        return await self._call("describe", redact=False, resource=resource)

    async def describe_catalog(self) -> Any:
        return await self._call("describe_catalog", redact=False)

    async def create(self, resource: str, payload: dict, *, redact: bool = True) -> Any:
        return await self._call("create", redact=redact, resource=resource, payload=payload)

    async def update(self, resource: str, key: str, payload: dict, *, redact: bool = True) -> Any:
        return await self._call("update", redact=redact, resource=resource, key=key, payload=payload)

    async def delete(self, resource: str, key: str, *, redact: bool = True) -> Any:
        return await self._call("delete", redact=redact, resource=resource, key=key)

    async def invoke_action(
        self, resource: str, key: str | None, action: str, params: Any = None, *, redact: bool = True
    ) -> Any:
        return await self._call(
            "invoke_action", redact=redact, resource=resource, key=key, action=action, params=params
        )

    async def atom_feed(
        self, workspace: str, collection: str, *, updated_min: Any = None, page_size: Any = None
    ) -> Any:
        return await self._call(
            "atom_feed", redact=False, workspace=workspace, collection=collection,
            updated_min=updated_min, page_size=page_size,
        )

    async def classify_module(self, probe: str) -> Any:
        return await self._call("classify_module", redact=False, probe=probe)


def make_context(
    *,
    features: dict[str, Any] | None = None,
    modules: dict[str, Any] | None = None,
    client: FakeClient | None = None,
) -> ServerContext:
    cfg_data: dict[str, Any] = {"server": {"base_url": "https://pod.example"}}
    if features:
        cfg_data["features"] = features
    if modules:
        cfg_data["modules"] = modules
    cfg = Config.model_validate(cfg_data)
    redactor = Redactor(enabled=not cfg.features.sensitive_fields_enabled)
    audit = FakeAudit()
    cli = client or FakeClient(redactor=redactor)
    cli.redactor = redactor
    catalog = Catalog(cli, cfg.modules)
    return ServerContext(config=cfg, client=cli, catalog=catalog, redactor=redactor, audit=audit)
