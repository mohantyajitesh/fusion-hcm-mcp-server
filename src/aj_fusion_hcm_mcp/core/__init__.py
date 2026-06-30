"""Core REST engine: client, errors, and (later) catalog + filters."""

from .client import HcmClient
from .errors import ConfigError, FusionMcpError, HcmApiError

__all__ = ["HcmClient", "ConfigError", "FusionMcpError", "HcmApiError"]
