from __future__ import annotations

import secrets
import time
from typing import Optional

from fastapi import APIRouter, Header, HTTPException

from ..dependencies import require_player_token
from ..elo import elo_update
from ..models import (
    JoinRequest,
    JoinResponse,
    MatchCreateRequest,
    MatchRunResponse,
    MatchState,
    Strategy,
    StrategySubmitRequest,
    Winner,
)
from ..sim import explain, lookup_or_precomputed, score
from .. import db

router = APIRouter(prefix="/v1/matches", tags=["matches"])


@router.post("", response_model=MatchState)
def create_match(req: MatchCreateRequest):
    match_id = "m_" + secrets.token_hex(3)
    m = MatchState(
        match_id=match_id,
        scenario=req.scenario,
        crop_region=req.crop_region,
        status="waiting_for_players",
        created_at=time.time(),
    )
    db.create_match(m)
    return m

@router.get("", response_model=dict)
def list_matches(status: str | None = None, limit: int = 50, offset: int = 0):
    limit = max(1, min(limit, 100))
    offset = max(0, offset)
    rows = db.list_matches(status=status, limit=limit, offset=offset)
    total = db.count_matches(status=status)
    sliced = rows
    return {
        "items": sliced,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.post("/{match_id}/join", response_model=JoinResponse)
def join_match(
    match_id: str,
    req: JoinRequest,
    x_player_token: Optional[str] = Header(default=None),
):
    require_player_token(req.player_id, x_player_token)

    m = db.get_match(match_id)
    if not m:
        raise HTTPException(status_code=404, detail="match not found")
    if m.status == "completed":
        raise HTTPException(status_code=409, detail="match already completed; create a new match to play again")

    current = m.slots[req.slot]
    if current and current != req.player_id:
        raise HTTPException(status_code=409, detail=f"slot {req.slot} is already taken by another player")

    other_slot = "B" if req.slot == "A" else "A"
    if m.slots[other_slot] == req.player_id:
        raise HTTPException(status_code=409, detail="player already occupies the other slot; one player cannot take both slots")

    m.slots[req.slot] = req.player_id
    db.save_match(m)
    return JoinResponse(match_id=match_id, slot=req.slot, player_id=req.player_id, status="joined")


@router.post("/{match_id}/strategy")
def submit_strategy(
    match_id: str,
    req: StrategySubmitRequest,
    x_player_token: Optional[str] = Header(default=None),
):
    require_player_token(req.player_id, x_player_token)

    m = db.get_match(match_id)
    if not m:
        raise HTTPException(status_code=404, detail="match not found")
    if m.status == "completed":
        raise HTTPException(status_code=409, detail="match already completed; cannot submit new strategies")

    slot: Optional[str] = None
    for s in ("A", "B"):
        if m.slots[s] == req.player_id:
            slot = s
            break
    if slot is None:
        raise HTTPException(status_code=409, detail="player must join the match in a slot before submitting a strategy")

    m.strategies[slot] = Strategy(
        rotation=req.rotation,
        n_level=req.n_level,
        irrigation=req.irrigation,
        tillage=req.tillage,
    )

    if m.strategies["A"] and m.strategies["B"]:
        m.status = "ready"
    else:
        m.status = "waiting_for_players"

    db.save_match(m)
    return {"match_id": match_id, "status": "strategy_saved", "slot": slot}


def update_player_stats_after_match(match: MatchState, winner: Winner) -> None:
    pA_id = match.slots.get("A")
    pB_id = match.slots.get("B")
    if not pA_id or not pB_id:
        return

    pA = db.get_player(pA_id)
    pB = db.get_player(pB_id)
    if not pA or not pB:
        return

    if winner == "tie":
        pA["ties"] += 1
        pB["ties"] += 1
    elif winner == "A":
        pA["wins"] += 1
        pB["losses"] += 1
    else:
        pA["losses"] += 1
        pB["wins"] += 1

    newA, newB = elo_update(
        pA["rating"], pB["rating"], winner,
        pA["games_played"], pB["games_played"]
    )
    pA["rating"], pB["rating"] = newA, newB

    pA["games_played"] += 1
    pB["games_played"] += 1
    db.update_player_stats(pA_id, pA)
    db.update_player_stats(pB_id, pB)


@router.post("/{match_id}/run", response_model=MatchRunResponse)
def run_match(match_id: str):
    m = db.get_match(match_id)
    if not m:
        raise HTTPException(status_code=404, detail="match not found")
    if m.status == "completed" and m.result:
        return m.result
    if not m.strategies["A"] or not m.strategies["B"]:
        raise HTTPException(status_code=409, detail="cannot run: both slots must have strategies submitted")
    if not m.slots["A"] or not m.slots["B"]:
        raise HTTPException(status_code=409, detail="cannot run: both slots must be filled by players")

    pA_id = m.slots["A"]
    pB_id = m.slots["B"]
    pA = db.get_player(pA_id)
    pB = db.get_player(pB_id)
    if not pA or not pB:
        raise HTTPException(status_code=404, detail="one or more players not found for this match")

    sA = m.strategies["A"]
    sB = m.strategies["B"]

    simA = lookup_or_precomputed(m.crop_region, m.scenario, sA)
    simB = lookup_or_precomputed(m.crop_region, m.scenario, sB)

    econA = score(sA, simA)
    econB = score(sB, simB)

    if abs(econA.score - econB.score) < 1e-9:
        winner: Winner = "tie"
        winner_player_id = None
    else:
        winner = "A" if econA.score > econB.score else "B"
        winner_player_id = pA_id if winner == "A" else pB_id

    outA = {
        "player_id": pA_id,
        "name": pA["name"],
        "strategy": sA,
        "sim": simA,
        "economics": econA,
        "why": explain(sA, simA, econA, m.scenario),
    }
    outB = {
        "player_id": pB_id,
        "name": pB["name"],
        "strategy": sB,
        "sim": simB,
        "economics": econB,
        "why": explain(sB, simB, econB, m.scenario),
    }

    result = MatchRunResponse(
        match_id=match_id,
        status="completed",
        winner=winner,
        winner_player_id=winner_player_id,
        scenario=m.scenario,
        crop_region=m.crop_region,
        players={"A": outA, "B": outB},
    )

    update_player_stats_after_match(m, winner)

    m.status = "completed"
    m.result = result
    db.save_match(m)
    return result


@router.get("/{match_id}", response_model=MatchState)
def get_match(match_id: str):
    m = db.get_match(match_id)
    if not m:
        raise HTTPException(status_code=404, detail="match not found")
    return m
