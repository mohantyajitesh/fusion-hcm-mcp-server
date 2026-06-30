"""HTTP Basic auth provider. For development only — use OAuth2 in production."""

from __future__ import annotations

import base64

from ..core.errors import ConfigError


class BasicAuthProvider:
    def __init__(self, username: str | None, password: str | None) -> None:
        if not username or not password:
            raise ConfigError("Basic auth requires auth.username and auth.password.")
        token = base64.b64encode(f"{username}:{password}".encode()).decode()
        self._header = f"Basic {token}"

    async def headers(self) -> dict[str, str]:
        return {"Authorization": self._header}

    async def refresh(self) -> None:
        # Static credentials — nothing to refresh. A 401 is a real auth failure.
        return None
