"""Tests for configuration loading and env overrides."""

from __future__ import annotations

import pytest

from aj_fusion_hcm_mcp.config import load_config
from aj_fusion_hcm_mcp.core.errors import ConfigError


def test_missing_base_url_raises(tmp_path, monkeypatch):
    monkeypatch.delenv("HCM_BASE_URL", raising=False)
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text("[auth]\ntype = 'basic'\n")
    with pytest.raises(ConfigError):
        load_config(cfg_file)


def test_defaults_applied(tmp_path, monkeypatch):
    monkeypatch.delenv("HCM_REST_VERSION", raising=False)
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text("[server]\nbase_url = 'https://pod.example.com'\n")
    cfg = load_config(cfg_file)
    assert cfg.server.rest_version == "11.13.18.05"
    assert cfg.transport.type == "stdio"
    assert cfg.modules.core_hr == "on"
    assert cfg.modules.recruiting == "auto"
    assert cfg.features.writes_enabled is False
    assert cfg.limits.default_limit == 25


def test_env_overrides_file(tmp_path, monkeypatch):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text("[server]\nbase_url = 'https://file.example.com'\n")
    monkeypatch.setenv("HCM_BASE_URL", "https://env.example.com")
    monkeypatch.setenv("HCM_AUTH_TYPE", "oauth2")
    cfg = load_config(cfg_file)
    assert cfg.server.base_url == "https://env.example.com"
    assert cfg.auth.type == "oauth2"


def test_env_only_no_file(tmp_path, monkeypatch):
    monkeypatch.setenv("HCM_BASE_URL", "https://env-only.example.com")
    missing = tmp_path / "does-not-exist.toml"
    cfg = load_config(missing)
    assert cfg.server.base_url == "https://env-only.example.com"
