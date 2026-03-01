from __future__ import annotations

import os


def allow_origins() -> list[str]:
    cors = os.getenv("FARM_DUEL_CORS", "*")
    return [o.strip() for o in cors.split(",") if o.strip()] or ["*"]


def env_bool(name: str, default: bool = False) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.lower() in ("1", "true", "yes", "on")

