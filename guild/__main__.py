"""Allow `python3 -m guild ...` to run the CLI without installing the console script."""
from __future__ import annotations

from guild.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
