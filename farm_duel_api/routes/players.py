from __future__ import annotations

import secrets
from fastapi import APIRouter, HTTPException

from ..models import PlayerCreateRequest, PlayerPrivate, PlayerPublic
from .. import db

router = APIRouter(prefix="/v1/players", tags=["players"])


@router.post("", response_model=PlayerPrivate)
def create_player(req: PlayerCreateRequest):
    player_id = "p_" + secrets.token_hex(3)
    token = "t_" + secrets.token_hex(6)
    record = {
        "name": req.name,
        "token": token,
        "rating": 1500,
        "wins": 0,
        "losses": 0,
        "ties": 0,
        "games_played": 0,
        "player_id": player_id,
    }
    db.create_player(record)
    p = record
    return PlayerPrivate(
        player_id=player_id,
        name=p["name"],
        token=p["token"],
        rating=p["rating"],
        wins=p["wins"],
        losses=p["losses"],
        ties=p["ties"],
        games_played=p["games_played"],
    )


@router.get("/{player_id}", response_model=PlayerPublic)
def get_player(player_id: str):
    p = db.get_player(player_id)
    if not p:
        raise HTTPException(status_code=404, detail="player not found")
    return PlayerPublic(
        player_id=player_id,
        name=p["name"],
        rating=p["rating"],
        wins=p["wins"],
        losses=p["losses"],
        ties=p["ties"],
        games_played=p["games_played"],
    )


@router.get("", response_model=dict)
def list_players(limit: int = 50, offset: int = 0, search: str | None = None):
    limit = max(1, min(limit, 100))
    offset = max(0, offset)
    rows = db.list_players(limit=limit, offset=offset, search=search)
    total = db.count_players(search=search)
    return {"items": rows, "total": total, "limit": limit, "offset": offset}
