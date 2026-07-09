"""Tests for the ATOM change-feed tool."""

from __future__ import annotations

from aj_fusion_hcm_mcp.tools import atom
from tests.conftest import FakeMCP, make_context

_FEED_XML = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>New Hire</title>
    <updated>2024-05-01T10:00:00.000Z</updated>
    <content type="application/json">{"Context": {"PersonNumber": "100", "NationalId": "999"}, "ChangedAttributes": ["HireDate"]}</content>
  </entry>
</feed>"""


def _wire(atom_enabled: bool):
    ctx = make_context(features={"atom_enabled": atom_enabled})
    mcp = FakeMCP()
    atom.register(mcp, ctx)
    return mcp, ctx


async def test_feature_gate_off_returns_note_and_no_pod_call():
    mcp, ctx = _wire(atom_enabled=False)
    res = await mcp.tools["list_changes"](feed="newhire", since="2024-01-01")
    assert "note" in res
    assert not ctx.client.calls  # never touched the pod


async def test_unknown_feed_rejected():
    mcp, ctx = _wire(atom_enabled=True)
    res = await mcp.tools["list_changes"](feed="bogus", since="2024-01-01")
    assert "error" in res


async def test_parses_feed_and_extracts_context_redacted():
    mcp, ctx = _wire(atom_enabled=True)
    ctx.client.set("atom_feed", lambda **kw: _FEED_XML)
    res = await mcp.tools["list_changes"](feed="newhire", since="2024-01-01")
    assert res["count"] == 1
    change = res["changes"][0]
    assert change["title"] == "New Hire"
    assert change["changed_attributes"] == ["HireDate"]
    # context carries the JSON payload; NationalId within it is redacted
    assert change["context"]["PersonNumber"] == "100"
    assert change["context"]["NationalId"] == "***REDACTED***"


async def test_date_only_since_expanded_to_iso():
    mcp, ctx = _wire(atom_enabled=True)
    ctx.client.set("atom_feed", lambda **kw: _FEED_XML)
    await mcp.tools["list_changes"](feed="termination", since="2024-01-01")
    _, kw = ctx.client.calls[-1]
    assert kw["collection"] == "termination"
    assert kw["updated_min"] == "2024-01-01T00:00:00.000Z"
