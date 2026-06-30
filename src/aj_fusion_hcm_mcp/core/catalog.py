"""Resource catalog: bundled seed list + live ``/describe`` cache + capability
discovery.

The seed catalog lets ``list_resources`` work offline and degrade gracefully;
``describe`` confirms reality against the pod and caches schemas. Capability
discovery probes one representative resource per ``auto`` module to decide which
tool groups are live (DESIGN.md §12.3).
"""

from __future__ import annotations

import json
from importlib.resources import files
from typing import Any

from . import filters
from .client import HcmClient
from .errors import HcmApiError

# One representative resource per module (DESIGN.md §12.4). Probe names are
# confirmed against the pinned REST version during the live-pod phase.
MODULE_PROBES: dict[str, str] = {
    "core_hr": "workers",
    "compensation": "salaries",
    "absence": "absences",
    "payroll": "payrollFlows",
    "recruiting": "recruitingCEJobRequisitions",
    "talent": "workerGoals",
    "learning": "learnerLearningRecords",
    "benefits": "benefitEnrollments",
    "time_labor": "timeRecords",
}


def _load_seed() -> list[dict[str, str]]:
    raw = files("aj_fusion_hcm_mcp.data").joinpath("seed_catalog.json").read_text("utf-8")
    return json.loads(raw).get("resources", [])


def summarize_describe(resource: str, raw: dict[str, Any]) -> dict[str, Any]:
    """Reduce Oracle's verbose ``/describe`` payload to attributes/children/actions."""
    resources = raw.get("Resources") if isinstance(raw, dict) else None
    node: Any = None
    if isinstance(resources, dict):
        node = resources.get(resource) or (next(iter(resources.values()), None))
    if not isinstance(node, dict):
        return {"resource": resource, "raw": raw}

    attributes = [
        {k: a.get(k) for k in ("name", "type", "title", "updatable", "mandatory") if k in a}
        for a in (node.get("attributes") or [])
        if isinstance(a, dict)
    ]
    children = [
        c["name"] if isinstance(c, dict) and c.get("name") else c
        for c in (node.get("children") or [])
        if isinstance(c, (dict, str))
    ]
    actions_node = node.get("actions")
    if isinstance(actions_node, dict):
        actions = list(actions_node.keys())
    elif isinstance(actions_node, list):
        actions = [a.get("name") if isinstance(a, dict) else a for a in actions_node]
    else:
        actions = []

    return {
        "resource": resource,
        "title": node.get("title"),
        "attributes": attributes,
        "children": [c for c in children if c],
        "actions": [a for a in actions if a],
    }


class Catalog:
    def __init__(self, client: HcmClient, modules_config: Any) -> None:
        self._client = client
        self._modules = modules_config
        self._seed = _load_seed()
        self._describe_cache: dict[str, dict[str, Any]] = {}
        self._attrs_cache: dict[str, set[str]] = {}
        self._capabilities: dict[str, dict[str, Any]] | None = None

    # ---- seed catalog (offline) ------------------------------------------

    def list_resources(
        self, search: str | None = None, module: str | None = None, limit: int = 50
    ) -> list[dict[str, str]]:
        results = self._seed
        if module:
            results = [r for r in results if r.get("module") == module]
        if search:
            needle = search.lower()
            results = [
                r
                for r in results
                if needle in r["name"].lower()
                or needle in r.get("title", "").lower()
                or needle in r.get("description", "").lower()
            ]
        return results[:limit]

    # ---- live describe (cached) ------------------------------------------

    async def describe(self, resource: str) -> dict[str, Any]:
        if resource not in self._describe_cache:
            raw = await self._client.describe(resource)
            summary = summarize_describe(resource, raw)
            self._describe_cache[resource] = summary
            self._attrs_cache[resource] = {
                a["name"] for a in summary.get("attributes", []) if a.get("name")
            }
        return self._describe_cache[resource]

    async def validate_filter(self, resource: str, q: str) -> None:
        """Validate a ``q`` filter against the resource's attributes (best-effort)."""
        attrs = self._attrs_cache.get(resource)
        if attrs is None:
            try:
                await self.describe(resource)
                attrs = self._attrs_cache.get(resource)
            except HcmApiError:
                return  # can't validate offline / on error — let the pod decide
        filters.validate_q(q, attrs or set())

    # ---- capability discovery --------------------------------------------

    async def get_capabilities(self, refresh: bool = False) -> dict[str, dict[str, Any]]:
        if self._capabilities is not None and not refresh:
            return self._capabilities

        caps: dict[str, dict[str, Any]] = {}
        for module, mode in self._modules.model_dump().items():
            if mode == "off":
                caps[module] = {"mode": mode, "status": "disabled", "enabled": False}
                continue
            if mode == "on":
                caps[module] = {"mode": mode, "status": "enabled", "enabled": True}
                continue
            # mode == "auto": probe the pod
            probe = MODULE_PROBES.get(module)
            if probe is None:
                caps[module] = {"mode": mode, "status": "unknown", "enabled": False}
                continue
            status = await self._client.classify_module(probe)
            caps[module] = {
                "mode": mode,
                "status": status,
                "enabled": status == "provisioned",
                "probe": probe,
            }

        self._capabilities = caps
        return caps
