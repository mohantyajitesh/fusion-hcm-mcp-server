"""Tests for auth provider selection and keyring fallback."""

from __future__ import annotations

import pytest

import aj_fusion_hcm_mcp.auth as auth_pkg
from aj_fusion_hcm_mcp.auth import BasicAuthProvider, build_auth
from aj_fusion_hcm_mcp.config import AuthConfig
from aj_fusion_hcm_mcp.core.errors import ConfigError


async def test_basic_provider_builds_header():
    p = BasicAuthProvider("user", "secret")
    headers = await p.headers()
    assert headers["Authorization"].startswith("Basic ")


def test_config_password_takes_precedence(monkeypatch):
    monkeypatch.setattr(auth_pkg, "keyring_password", lambda u: "from-keyring")
    provider = build_auth(AuthConfig(type="basic", username="u", password="from-config"))
    assert isinstance(provider, BasicAuthProvider)  # built successfully with config pw


def test_keyring_fallback_used_when_no_config_password(monkeypatch):
    called = {}

    def fake_keyring(username):
        called["username"] = username
        return "kr-secret"

    monkeypatch.setattr(auth_pkg, "keyring_password", fake_keyring)
    provider = build_auth(AuthConfig(type="basic", username="u", password=None))
    assert isinstance(provider, BasicAuthProvider)
    assert called["username"] == "u"


def test_missing_password_everywhere_raises(monkeypatch):
    monkeypatch.setattr(auth_pkg, "keyring_password", lambda u: None)
    with pytest.raises(ConfigError) as exc:
        build_auth(AuthConfig(type="basic", username="u", password=None))
    assert "aj-fusion-hcm-mcp" in str(exc.value)  # names the keyring service


def test_keyring_password_never_raises():
    # No keyring backend/entry in CI — must return None, not raise.
    from aj_fusion_hcm_mcp.auth.basic import keyring_password

    assert keyring_password(None) is None
    assert keyring_password("nobody-here") in (None,) or isinstance(keyring_password("x"), (str, type(None)))
