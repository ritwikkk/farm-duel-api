from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import allow_origins
from .routes import leaderboard, matches, players, meta
from . import db

db.init_db()

app = FastAPI(title="Farm Duel API", version="1.1")

# Simple CORS for local dev/Postman; configurable via env FARM_DUEL_CORS (csv).
app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(meta.router)
app.include_router(players.router)
app.include_router(matches.router)
app.include_router(leaderboard.router)
