"""Explicit server runtime; no dotenv or local fixtures on import."""

import os

if os.environ.get("WORKSPACE_RUNTIME") != "1":
    raise RuntimeError(
        "Set WORKSPACE_RUNTIME=1 before importing server runtime; dotenv is forbidden"
    )
