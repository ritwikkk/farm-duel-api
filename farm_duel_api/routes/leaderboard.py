from __future__ import annotations

from fastapi import APIRouter

from .. import db

router = APIRouter(prefix="/v1/leaderboard", tags=["leaderboard"])


@router.get("")
def leaderboard(limit: int = 10):
    limit = max(1, min(limit, 50))
    leaders = []
    rows = db.list_players(limit=10_000, offset=0, search=None)
    for p in rows:
        leaders.append({
            "player_id": p["player_id"],
            "name": p["name"],
            "rating": p["rating"],
            "wins": p["wins"],
            "losses": p["losses"],
            "ties": p["ties"],
            "games_played": p["games_played"],
        })
    leaders.sort(key=lambda x: (x["rating"], x["wins"]), reverse=True)
    leaders = leaders[:limit]
    for i, row in enumerate(leaders, start=1):
        row["rank"] = i
    return {"leaders": leaders}
