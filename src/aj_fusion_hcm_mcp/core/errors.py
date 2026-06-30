"""Exception hierarchy for the Fusion HCM MCP server."""

from __future__ import annotations


class FusionMcpError(Exception):
    """Base class for all errors raised by this server."""


class ConfigError(FusionMcpError):
    """Raised when configuration is missing or invalid."""


class HcmApiError(FusionMcpError):
    """A normalized Oracle Fusion HCM REST error.

    Oracle returns errors in a few shapes; we flatten them into a stable
    structure so tools and the model can reason about them consistently.
    ``status == 0`` denotes a transport/network failure (no HTTP response).
    """

    def __init__(
        self,
        status: int,
        title: str | None = None,
        detail: str | None = None,
        errorpath: str | None = None,
    ) -> None:
        self.status = status
        self.title = title
        self.detail = detail
        self.errorpath = errorpath
        message = f"[{status}] {title or ''}: {detail or ''}".strip(" :")
        super().__init__(message or f"HCM API error {status}")

    def as_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "title": self.title,
            "detail": self.detail,
            "errorpath": self.errorpath,
        }
