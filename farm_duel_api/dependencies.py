from __future__ import annotations

from fastapi import Header, HTTPException

from . import db


def require_player_token(player_id: str, x_player_token: str | None) -> dict:
    player = db.get_player(player_id)
    if not player:
        raise HTTPException(status_code=404, detail="player not found")
    if not x_player_token or x_player_token != player["token"]:
        raise HTTPException(status_code=401, detail="invalid or missing X-Player-Token for this player")
    return player
