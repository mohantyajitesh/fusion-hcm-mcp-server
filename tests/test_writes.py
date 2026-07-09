"""Tests for the write gate stack — one test per layer."""

from __future__ import annotations

from aj_fusion_hcm_mcp.core.errors import HcmApiError
from aj_fusion_hcm_mcp.tools import writes
from tests.conftest import FakeMCP, make_context

_SALARIES_DESCRIBE = {"Resources": {"salaries": {
    "title": "Salaries",
    "attributes": [
        {"name": "Comments", "updatable": True},
        {"name": "SalaryAmount", "updatable": True},
        {"name": "SalaryId", "updatable": False},
    ],
    "children": {},
    "actions": {},
}}}

_WORKERS_DESCRIBE = {"Resources": {"workers": {
    "attributes": [{"name": "PersonNumber", "updatable": True}],
    "children": {"workRelationships": {"item": {"actions": {
        "terminate": {}, "changeLegalEmployer": {}, "get": {}
    }}}},
    "actions": {},
}}}


def _wire(writes_enabled: bool, describe=None):
    ctx = make_context(features={"writes_enabled": writes_enabled})
    if describe is not None:
        ctx.client.set("describe", describe)
    mcp = FakeMCP()
    writes.register(mcp, ctx)
    return mcp, ctx


# Layer 1 -------------------------------------------------------------------
async def test_layer1_flag_off_blocks_and_no_pod_call():
    mcp, ctx = _wire(writes_enabled=False)
    res = await mcp.tools["mutate_record"](resource="salaries", op="create", payload={"x": 1})
    assert res["blocked"] == "writes_disabled"
    assert not ctx.client.calls


# Layer 2 -------------------------------------------------------------------
async def test_layer2_dry_run_diffs_raw_and_does_not_write():
    mcp, ctx = _wire(writes_enabled=True, describe=lambda **kw: _SALARIES_DESCRIBE)
    ctx.client.set("get_record", lambda **kw: {"Comments": "old", "SalaryAmount": 100000})
    res = await mcp.tools["mutate_record"](
        resource="salaries", op="update", key="K1", payload={"Comments": "new"}
    )
    assert res["dry_run"] is True
    assert res["changes"] == {"Comments": {"from": "old", "to": "new"}}
    # unchanged sensitive field must NOT be flagged (diff RAW, not redact-first)
    assert "SalaryAmount" not in res["changes"]
    assert not any(m in ("update", "create", "delete") for m, _ in ctx.client.calls)


async def test_layer2_dry_run_create_shows_would_create():
    mcp, ctx = _wire(writes_enabled=True, describe=lambda **kw: _SALARIES_DESCRIBE)
    res = await mcp.tools["mutate_record"](
        resource="salaries", op="create", payload={"Comments": "hi"}
    )
    assert res["would_create"] == {"Comments": "hi"}


# Layer 3 -------------------------------------------------------------------
async def test_layer3_unknown_attribute_blocked():
    mcp, ctx = _wire(writes_enabled=True, describe=lambda **kw: _SALARIES_DESCRIBE)
    res = await mcp.tools["mutate_record"](
        resource="salaries", op="create", payload={"Bogus": 1}
    )
    assert "Bogus" in res["unknown_attributes"]


async def test_layer3_read_only_attribute_blocked():
    mcp, ctx = _wire(writes_enabled=True, describe=lambda **kw: _SALARIES_DESCRIBE)
    res = await mcp.tools["mutate_record"](
        resource="salaries", op="update", key="K1", payload={"SalaryId": 9}
    )
    assert "SalaryId" in res["read_only_attributes"]


async def test_layer3_fails_closed_when_schema_unavailable():
    def boom(**kw):
        raise HcmApiError(500, "server_error")

    mcp, ctx = _wire(writes_enabled=True, describe=boom)
    res = await mcp.tools["mutate_record"](
        resource="salaries", op="create", payload={"Comments": "x"}
    )
    assert res["blocked"] == "schema_unavailable"


# Layer 4 (commit + audit) --------------------------------------------------
async def test_layer4_explicit_commit_writes_and_audits():
    mcp, ctx = _wire(writes_enabled=True, describe=lambda **kw: _SALARIES_DESCRIBE)
    ctx.client.set("create", lambda **kw: {"SalaryId": 1})
    res = await mcp.tools["mutate_record"](
        resource="salaries", op="create", payload={"Comments": "x"}, dry_run=False
    )
    assert res["committed"] == "create"
    assert any(m == "create" for m, _ in ctx.client.calls)
    rec = ctx.audit.records[-1]
    assert rec["status"] == "committed" and rec["write"] is True


# run_action ----------------------------------------------------------------
async def test_run_action_valid_child_action_dry_run():
    mcp, ctx = _wire(writes_enabled=True, describe=lambda **kw: _WORKERS_DESCRIBE)
    res = await mcp.tools["run_action"](
        resource="workers/K/child/workRelationships", key="CK", action="terminate"
    )
    assert res["dry_run"] is True and res["would_invoke"] == "terminate"


async def test_run_action_unknown_action_blocked():
    mcp, ctx = _wire(writes_enabled=True, describe=lambda **kw: _WORKERS_DESCRIBE)
    res = await mcp.tools["run_action"](
        resource="workers/K/child/workRelationships", key="CK", action="explode"
    )
    assert "terminate" in res["available_actions"] and "error" in res


async def test_run_action_flag_off_blocks():
    mcp, ctx = _wire(writes_enabled=False)
    res = await mcp.tools["run_action"](resource="workers", key="K", action="anything")
    assert res["blocked"] == "writes_disabled"
