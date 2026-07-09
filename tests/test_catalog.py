"""Tests for the seed catalog and describe summarization (offline)."""

from __future__ import annotations

from aj_fusion_hcm_mcp.config import ModulesConfig
from aj_fusion_hcm_mcp.core.catalog import Catalog, summarize_describe


def _catalog() -> Catalog:
    # client is unused by the offline paths exercised here.
    return Catalog(client=None, modules_config=ModulesConfig())


def test_seed_loads_and_lists():
    cat = _catalog()
    all_resources = cat.list_resources(limit=10_000)
    assert len(all_resources) > 10
    assert any(r["name"] == "workers" for r in all_resources)


def test_list_filter_by_module():
    cat = _catalog()
    comp = cat.list_resources(module="compensation", limit=100)
    assert comp and all(r["module"] == "compensation" for r in comp)


def test_list_search():
    cat = _catalog()
    hits = cat.list_resources(search="absence", limit=100)
    assert any("absence" in r["name"].lower() for r in hits)


def test_summarize_describe_extracts_fields():
    raw = {
        "Resources": {
            "workers": {
                "title": "Worker",
                "attributes": [
                    {"name": "PersonId", "type": "integer", "updatable": False},
                    {"name": "PersonNumber", "type": "string", "updatable": True},
                ],
                "children": [{"name": "assignments"}, {"name": "addresses"}],
                "actions": {"terminate": {}, "rehire": {}},
            }
        }
    }
    summary = summarize_describe("workers", raw)
    assert summary["title"] == "Worker"
    assert {a["name"] for a in summary["attributes"]} == {"PersonId", "PersonNumber"}
    assert set(summary["children"]) == {"assignments", "addresses"}
    assert set(summary["actions"]) == {"terminate", "rehire"}


def test_summarize_describe_fallback_on_unknown_shape():
    summary = summarize_describe("workers", {"unexpected": True})
    assert summary["resource"] == "workers"
    assert "raw" in summary


def test_summarize_surfaces_child_actions_excluding_crud():
    raw = {"Resources": {"workers": {
        "attributes": [{"name": "PersonNumber", "updatable": True}],
        "children": {"workRelationships": {"item": {"actions": {
            "terminate": {}, "changeLegalEmployer": {}, "get": {}, "update": {},
        }}}},
        "actions": {},
    }}}
    summary = summarize_describe("workers", raw)
    assert "workRelationships" in summary["children"]
    assert set(summary["child_actions"]["workRelationships"]) == {
        "terminate", "changeLegalEmployer"
    }  # generic CRUD verbs excluded


async def test_list_live_merges_and_dedupes_against_seed():
    from aj_fusion_hcm_mcp.config import ModulesConfig
    from tests.conftest import FakeClient

    client = FakeClient()
    # live index includes a seed resource (workers) and a novel one
    client.set("describe_catalog", lambda **kw: {"Resources": {
        "workers": {"title": "Workers"},
        "grievanceCases": {"title": "Grievance Cases"},
    }})
    cat = Catalog(client, ModulesConfig())
    merged = await cat.list_live(limit=10_000)
    names = {r["name"]: r["source"] for r in merged}
    assert names["workers"] == "seed-catalog"          # seed wins, not duplicated
    assert names["grievanceCases"] == "live-index"     # novel resource surfaced
    assert sum(1 for r in merged if r["name"] == "workers") == 1
