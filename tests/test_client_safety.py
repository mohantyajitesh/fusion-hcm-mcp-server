"""Tests for the client-layer safety floor: redaction + audit are inescapable."""

from __future__ import annotations

import httpx
import pytest

from aj_fusion_hcm_mcp.core.client import HcmClient
from aj_fusion_hcm_mcp.core.errors import HcmApiError
from aj_fusion_hcm_mcp.safety.redaction import Redactor
from tests.conftest import DummyAuth, FakeAudit

MASK = "***REDACTED***"


def _make_client(redactor_enabled=True):
    def handler(request: httpx.Request) -> httpx.Response:
        if "boom" in request.url.path:
            return httpx.Response(403, json={"title": "forbidden", "detail": "no access"})
        return httpx.Response(
            200, json={"items": [{"NationalId": "123", "DisplayName": "Ada"}], "count": 1}
        )

    audit = FakeAudit()
    client = HcmClient(
        "https://pod.example",
        "11.13.18.05",
        DummyAuth(),
        redactor=Redactor(enabled=redactor_enabled),
        audit=audit,
        transport=httpx.MockTransport(handler),
    )
    return client, audit


async def test_query_redacts_and_audits():
    client, audit = _make_client()
    res = await client.query("emps")
    assert res["items"][0]["NationalId"] == MASK
    assert res["items"][0]["DisplayName"] == "Ada"
    rec = audit.records[-1]
    assert rec["tool"] == "client:query" and rec["status"] == "ok" and rec["write"] is False
    await client.aclose()


async def test_redact_false_bypasses_but_still_audits():
    client, audit = _make_client()
    res = await client.query("emps", redact=False)
    assert res["items"][0]["NationalId"] == "123"  # not redacted
    assert audit.records[-1]["status"] == "ok"  # still audited
    await client.aclose()


async def test_write_is_flagged_in_audit():
    client, audit = _make_client()
    await client.create("someResource", {"a": 1})
    rec = audit.records[-1]
    assert rec["tool"] == "client:create" and rec["write"] is True
    await client.aclose()


async def test_action_name_and_write_in_audit():
    client, audit = _make_client()
    await client.invoke_action("workers/K/child/workRelationships", "CK", "terminate", {"x": 1})
    rec = audit.records[-1]
    assert rec["tool"] == "client:invoke_action" and rec["write"] is True
    await client.aclose()


async def test_failed_op_audited_then_reraised():
    client, audit = _make_client()
    with pytest.raises(HcmApiError):
        await client.query("boom")
    assert audit.records[-1]["status"] == "error:403"
    await client.aclose()


async def test_sensitive_flag_tracks_global_redactor_disabled():
    client, audit = _make_client(redactor_enabled=False)
    await client.query("emps")
    assert audit.records[-1]["sensitive"] is True
    await client.aclose()


async def test_ssrf_guard_blocks_foreign_href():
    client, audit = _make_client()
    with pytest.raises(HcmApiError) as exc:
        await client.get_href("https://evil.example/steal")
    assert exc.value.title == "ssrf_blocked"
    assert audit.records[-1]["status"].startswith("error")
    await client.aclose()
