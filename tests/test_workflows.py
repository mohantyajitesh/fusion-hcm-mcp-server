"""Tests for curated workflow tools (offline, via FakeClient)."""

from __future__ import annotations

from aj_fusion_hcm_mcp.tools import workflows
from tests.conftest import FakeMCP, make_context

MASK = "***REDACTED***"


def _wire(client=None):
    ctx = make_context(client=client)
    mcp = FakeMCP()
    workflows.register(mcp, ctx)
    return mcp, ctx


async def test_find_worker_requires_exactly_one_criterion():
    mcp, ctx = _wire()
    res = await mcp.tools["find_worker"](name="Ada", email="a@b.com")
    assert "error" in res


async def test_find_worker_builds_partial_name_query_and_compacts():
    mcp, ctx = _wire()
    ctx.client.set("query", lambda **kw: {
        "items": [{"PersonNumber": "100", "DisplayName": "Ada L", "NationalId": "999"}],
        "count": 1, "has_more": False, "total": None,
    })
    res = await mcp.tools["find_worker"](name="Ada")
    method, kw = ctx.client.calls[-1]
    assert kw["resource"] == "emps"
    assert kw["q"] == "DisplayName LIKE '%Ada%'"
    assert kw["fields"] == ["PersonNumber", "DisplayName", "WorkEmail"]
    # PII redacted by the (fake) client floor
    assert res["workers"][0]["NationalId"] == MASK


async def test_find_worker_escapes_quotes():
    mcp, ctx = _wire()
    await mcp.tools["find_worker"](name="O'Ada")
    _, kw = ctx.client.calls[-1]
    assert kw["q"] == "DisplayName LIKE '%O''Ada%'"


async def test_reporting_chain_up_resolves_via_child_link_and_person_id():
    mcp, ctx = _wire()

    def query_handler(resource=None, q=None, **kw):
        if resource == "workers" and "PersonNumber = '100'" in (q or ""):
            return {"items": [{"PersonNumber": "100", "workRelationships": {"items": [
                {"assignments": {"items": [
                    {"links": [{"name": "managers", "href": "https://pod.example/mgr"}]}
                ]}}
            ]}}], "count": 1, "has_more": False, "total": None}
        if resource == "workers" and "PersonId = 500" in (q or ""):
            return {"items": [{"PersonNumber": "M1", "DisplayName": "Boss"}],
                    "count": 1, "has_more": False, "total": None}
        # M1 has no manager link -> chain stops
        return {"items": [{"PersonNumber": "M1"}], "count": 1, "has_more": False, "total": None}

    ctx.client.set("query", query_handler)
    ctx.client.set("get_href", lambda **kw: {"items": [
        {"ManagerType": "LINE_MANAGER", "ManagerPersonId": 500}
    ]})
    res = await mcp.tools["get_reporting_chain"](person_number="100", direction="up")
    assert [c["PersonNumber"] for c in res["chain"]] == ["M1"]
    assert res["chain"][0]["DisplayName"] == "Boss"


async def test_reporting_chain_up_empty_returns_note():
    mcp, ctx = _wire()
    ctx.client.set("query", lambda **kw: {"items": [], "count": 0, "has_more": False, "total": None})
    res = await mcp.tools["get_reporting_chain"](person_number="X", direction="up")
    assert res["chain"] == [] and "note" in res


async def test_reporting_chain_effective_date_passes_through():
    mcp, ctx = _wire()
    ctx.client.set("query", lambda **kw: {"items": [], "count": 0, "has_more": False, "total": None})
    await mcp.tools["get_reporting_chain"](person_number="100", direction="up",
                                           effective_date="2023-01-01")
    _, kw = ctx.client.calls[-1]
    assert kw.get("effective_date") == "2023-01-01"


async def test_reporting_chain_down_levels():
    mcp, ctx = _wire()

    def query_handler(resource=None, q=None, **kw):
        if "PersonNumber = '100'" in (q or ""):
            reports = [{"PersonNumber": "200", "DisplayName": "B"}]
        elif "PersonNumber = '200'" in (q or ""):
            reports = [{"PersonNumber": "300", "DisplayName": "C"}]
        else:
            reports = []
        return {"items": [{"directReports": {"items": reports}}],
                "count": 1, "has_more": False, "total": None}

    ctx.client.set("query", query_handler)
    res = await mcp.tools["get_reporting_chain"](person_number="100", direction="down", depth=5)
    levels = {c["PersonNumber"]: c["level"] for c in res["chain"]}
    assert levels == {"200": 1, "300": 2}


async def test_list_direct_reports():
    mcp, ctx = _wire()
    ctx.client.set("query", lambda **kw: {"items": [{"directReports": {"items": [
        {"PersonNumber": "200", "DisplayName": "B"}
    ]}}], "count": 1, "has_more": False, "total": None})
    res = await mcp.tools["list_direct_reports"](person_number="100")
    assert res["count"] == 1 and res["direct_reports"][0]["PersonNumber"] == "200"


async def test_get_current_compensation_wrapper_not_redacted_but_rows_are():
    mcp, ctx = _wire()

    def query_handler(resource=None, **kw):
        if resource == "emps":
            return {"items": [{"assignments": {"items": [{"AssignmentId": 1}]}}],
                    "count": 1, "has_more": False, "total": None}
        # salaries
        return {"items": [{"SalaryAmount": 120000, "DateFrom": "2024-01-01"}],
                "count": 1, "has_more": False, "total": None}

    ctx.client.set("query", query_handler)
    res = await mcp.tools["get_current_compensation"](person_number="100")
    # wrapper key "salary_history" must NOT be masked wholesale...
    assert isinstance(res["salary_history"], list)
    # ...but the amount inside each row IS redacted by the floor
    assert res["salary_history"][0]["SalaryAmount"] == MASK
    assert res["amounts_redacted"] is True


async def test_list_absences_queries_person_only_and_filters_client_side():
    mcp, ctx = _wire()
    ctx.client.set("query", lambda **kw: {"items": [
        {"absenceStatusCd": "SUBMITTED", "startDate": "2024-05-01"},
        {"absenceStatusCd": "ORL_WITHDRAWN", "startDate": "2024-01-01"},
    ], "count": 2, "has_more": False, "total": None})
    res = await mcp.tools["list_absences"](person_number="100", status="submitted")
    _, kw = ctx.client.calls[-1]
    assert kw["q"] == "personNumber = '100'"  # person attr only
    assert res["count"] == 1 and res["absences"][0]["absenceStatusCd"] == "SUBMITTED"


async def test_lookup_org_unknown_type():
    mcp, ctx = _wire()
    res = await mcp.tools["lookup_org"](org_type="planet", search="x")
    assert "error" in res
