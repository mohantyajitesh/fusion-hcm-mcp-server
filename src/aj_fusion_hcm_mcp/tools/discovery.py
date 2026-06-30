"""Discovery tools: catalog browsing, schema introspection, capability report."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from ..context import ServerContext


def register(mcp: FastMCP, ctx: ServerContext) -> None:
    @mcp.tool()
    def list_resources(
        search: str | None = None, module: str | None = None, limit: int = 50
    ) -> dict[str, Any]:
        """Search the catalog of common Oracle Fusion HCM REST resources.

        Works offline from a bundled seed list. Filter by ``search`` (matches
        name/title/description) and/or ``module`` (e.g. core_hr, compensation,
        absence, payroll, recruiting, talent, learning, benefits, time_labor).
        Use ``describe_resource`` to confirm a resource's live schema.
        """
        results = ctx.catalog.list_resources(search=search, module=module, limit=limit)
        ctx.audit.record(tool="list_resources", count=len(results))
        return {"resources": results, "count": len(results), "source": "seed-catalog"}

    @mcp.tool()
    async def describe_resource(resource: str) -> dict[str, Any]:
        """Return a resource's live schema: attributes, child collections, actions.

        Hits Oracle's ``/describe`` endpoint (cached). This is the authoritative
        source of field names to use in ``fields=`` and ``q=`` filters.
        """
        summary = await ctx.catalog.describe(resource)
        ctx.audit.record(tool="describe_resource", resource=resource)
        return summary

    @mcp.tool()
    async def get_capabilities(refresh: bool = False) -> dict[str, Any]:
        """Report which HCM modules are live on this pod.

        For each module: its mode (on/off/auto) and discovered status
        (enabled/disabled/provisioned/not_provisioned/no_access/unreachable).
        Modules set to ``auto`` are probed against the pod. Pass ``refresh=True``
        to re-probe.
        """
        caps = await ctx.catalog.get_capabilities(refresh=refresh)
        ctx.audit.record(tool="get_capabilities")
        return {"modules": caps}
