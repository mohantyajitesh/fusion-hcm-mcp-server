"""FastMCP server assembly and transport selection.

Phase 1 foundation: wires config -> auth -> REST client and registers a
diagnostic ``server_info`` tool (no live pod required). The read tools
(discovery, query, capabilities) are added on top of this in the next slice.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from mcp.server.fastmcp import FastMCP

from .auth import build_auth
from .config import Config, load_config
from .core.client import HcmClient


def _host_only(url: str) -> str:
    """Return just the host of a URL, so we never echo a full pod path/secret."""
    return urlsplit(url).netloc or url


def build_server(config: Config | None = None) -> tuple[FastMCP, Config, HcmClient]:
    cfg = config or load_config()
    auth = build_auth(cfg.auth)
    client = HcmClient(
        cfg.server.base_url,
        cfg.server.rest_version,
        auth,
        default_limit=cfg.limits.default_limit,
        max_limit=cfg.limits.max_limit,
    )

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
        }

    return mcp, cfg, client


def run(config: Config | None = None) -> None:
    mcp, cfg, _client = build_server(config)
    if cfg.transport.type == "http":
        mcp.settings.host = cfg.transport.host
        mcp.settings.port = cfg.transport.port
        mcp.run(transport="streamable-http")
    else:
        mcp.run(transport="stdio")
