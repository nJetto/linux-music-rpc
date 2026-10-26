"""Allow running as ``python3 -m music_rpc``."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
