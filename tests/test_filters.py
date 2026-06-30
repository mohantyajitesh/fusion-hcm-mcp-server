"""Tests for the q= filter helpers."""

from __future__ import annotations

import pytest

from aj_fusion_hcm_mcp.core.errors import FilterError
from aj_fusion_hcm_mcp.core.filters import build_q, extract_attributes, validate_q


def test_extract_attributes_basic():
    attrs = extract_attributes("PersonNumber = 100010 and LastName LIKE 'Sm%'")
    assert attrs == {"PersonNumber", "LastName"}


def test_extract_excludes_reserved_words():
    attrs = extract_attributes("Age >= 30 and Status = 'A'")
    assert "and" not in {a.lower() for a in attrs}


def test_validate_q_accepts_known():
    validate_q("LastName = 'Smith'", {"LastName", "FirstName"})  # no raise


def test_validate_q_rejects_unknown():
    with pytest.raises(FilterError) as exc:
        validate_q("Bogus = 'x'", {"LastName", "FirstName"})
    assert "Bogus" in str(exc.value)


def test_validate_q_skips_without_schema():
    validate_q("Anything = 1", set())  # empty allowed set -> skip, no raise


def test_build_q_quotes_and_joins():
    q = build_q([
        {"attr": "LastName", "op": "LIKE", "value": "Sm%"},
        {"attr": "Age", "op": ">=", "value": 30},
    ])
    assert q == "LastName LIKE 'Sm%' and Age >= 30"


def test_build_q_escapes_quotes():
    q = build_q([{"attr": "Name", "value": "O'Brien"}])
    assert q == "Name = 'O''Brien'"


def test_build_q_rejects_bad_operator():
    with pytest.raises(FilterError):
        build_q([{"attr": "X", "op": "DROP", "value": 1}])
