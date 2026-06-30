"""FastMCP server assembly and transport selection.

Wires config -> auth -> REST client -> catalog/safety into a shared context,
then registers the Phase 1 read tools (discovery + query) plus a diagnostic
``server_info`` tool.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from mcp.server.fastmcp import FastMCP

from .auth import build_auth
from .config import Config, load_config
from .context import ServerContext
from .core.catalog import Catalog
from .core.client import HcmClient
from .safety import AuditLog, Redactor
from .tools import discovery, query


def _host_only(url: str) -> str:
    """Return just the host of a URL, so we never echo a full pod path/secret."""
    return urlsplit(url).netloc or url


def build_context(cfg: Config) -> ServerContext:
    auth = build_auth(cfg.auth)
    client = HcmClient(
        cfg.server.base_url,
        cfg.server.rest_version,
        auth,
        default_limit=cfg.limits.default_limit,
        max_limit=cfg.limits.max_limit,
    )
    catalog = Catalog(client, cfg.modules)
    redactor = Redactor(enabled=not cfg.features.sensitive_fields_enabled)
    audit = AuditLog(cfg.audit.path, enabled=cfg.audit.enabled)
    return ServerContext(config=cfg, client=client, catalog=catalog, redactor=redactor, audit=audit)


def build_server(config: Config | None = None) -> tuple[FastMCP, ServerContext]:
    cfg = config or load_config()
    ctx = build_context(cfg)
    mcp = FastMCP("aj-oracle-fusion-hcm")

    @mcp.tool()
    def server_info() -> dict[str, object]:
        """Report non-sensitive server configuration and enabled module flags.

        Safe to call without a live pod connection — useful for verifying a
        deployment's configuration before exercising the HCM API.
        """
        return {
            "name": "aj-oracle-fusion-hcm-mcp",
            "rest_version": cfg.server.rest_version,
            "pod_host": _host_only(cfg.server.base_url),
            "auth_type": cfg.auth.type,
            "transport": cfg.transport.type,
            "modules": cfg.modules.model_dump(),
            "features": cfg.features.model_dump(),
            "catalog_size": len(ctx.catalog.list_resources(limit=10_000)),
            "redaction_active": ctx.redactor.enabled,
        }

    discovery.register(mcp, ctx)
    query.register(mcp, ctx)
    return mcp, ctx


def run(config: Config | None = None) -> None:
    mcp, ctx = build_server(config)
    if ctx.config.transport.type == "http":
        mcp.settings.host = ctx.config.transport.host
        mcp.settings.port = ctx.config.transport.port
        mcp.run(transport="streamable-http")
    else:
        mcp.run(transport="stdio")
