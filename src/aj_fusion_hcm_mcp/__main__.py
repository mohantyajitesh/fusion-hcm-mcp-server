"""Console entry point: ``aj-fusion-hcm-mcp``."""

from __future__ import annotations

import sys

from .core.errors import ConfigError
from .server import run


def main() -> int:
    try:
        run()
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
