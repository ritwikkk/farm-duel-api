from __future__ import annotations

import time
from fastapi import APIRouter

from .. import db

router = APIRouter(prefix="/v1/meta", tags=["meta"])
_start_time = time.time()


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/info")
def info():
    return {
        "version": "1.1",
        "uptime_seconds": round(time.time() - _start_time, 2),
        "players": db.count_players(),
        "matches": db.count_matches(None),
        "mode": "precomputed_lookup_or_fallback",
    }
