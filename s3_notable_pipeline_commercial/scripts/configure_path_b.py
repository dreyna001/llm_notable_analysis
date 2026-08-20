#!/usr/bin/env python3
"""Interactive Path B setup helper for commercial AWS customer-default deploy."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from path_b_deploy_configurator import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
