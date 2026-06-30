"""Tests for PII redaction."""

from __future__ import annotations

from aj_fusion_hcm_mcp.safety.redaction import Redactor

MASK = "***REDACTED***"


def test_masks_sensitive_fields():
    r = Redactor(enabled=True)
    out = r.redact({"FirstName": "Ada", "AnnualSalary": 120000, "NationalIdentifierNumber": "123"})
    assert out["FirstName"] == "Ada"
    assert out["AnnualSalary"] == MASK
    assert out["NationalIdentifierNumber"] == MASK


def test_nested_and_lists():
    r = Redactor(enabled=True)
    out = r.redact({"items": [{"DateOfBirth": "1990-01-01", "City": "NYC"}]})
    assert out["items"][0]["DateOfBirth"] == MASK
    assert out["items"][0]["City"] == "NYC"


def test_disabled_passthrough():
    r = Redactor(enabled=False)
    data = {"AnnualSalary": 120000}
    assert r.redact(data) == data


def test_is_sensitive_variants():
    r = Redactor(enabled=True)
    assert r.is_sensitive("national_id")
    assert r.is_sensitive("SSN")
    assert r.is_sensitive("base_salary_amount")
    assert not r.is_sensitive("PersonNumber")
