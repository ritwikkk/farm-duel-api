"""
Farm Duel API — hackathon-ready backend (FastAPI)
=================================================
Run:
  pip install fastapi uvicorn pydantic
  uvicorn farm_duel_api:app --reload

Optional:
  Place a cycles_results.json beside this file to use real Cycles outputs.
  Without it (or on missing key) the API returns deterministic precomputed fallback outputs.

Quick curl examples (replace IDs/TOKEN after creation)
-----------------------------------------------------
# 1) Create player
curl -s -X POST http://localhost:8000/v1/players -H "Content-Type: application/json" \
  -d '{"name":"Alice"}'

# 2) Create match
curl -s -X POST http://localhost:8000/v1/matches -H "Content-Type: application/json" \
  -d '{"scenario":"normal","crop_region":"il_cornbelt"}'

# 3) Join slot A
curl -s -X POST http://localhost:8000/v1/matches/<MATCH_ID>/join \
  -H "Content-Type: application/json" -H "X-Player-Token: <TOKEN>" \
  -d '{"player_id":"<PLAYER_ID>","slot":"A"}'

# 4) Submit strategy for slot A
curl -s -X POST http://localhost:8000/v1/matches/<MATCH_ID>/strategy \
  -H "Content-Type: application/json" -H "X-Player-Token: <TOKEN>" \
  -d '{"player_id":"<PLAYER_ID>","rotation":"corn","n_level":"medium","irrigation":"off","tillage":"no_till"}'

# Repeat steps 1/3/4 for player B in slot B, then run match:
# 5) Run match
curl -s -X POST http://localhost:8000/v1/matches/<MATCH_ID>/run

# 6) View leaderboard
curl -s http://localhost:8000/v1/leaderboard
"""

from __future__ import annotations

import json
import secrets
import time
from typing import Dict, List, Literal, Optional

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title="Farm Duel API", version="1.0")

# -----------------------------
# Enums / Types
# -----------------------------
Rotation = Literal["corn", "corn_soy", "wheat_cover"]
NLevel = Literal["low", "medium", "high"]
Irrigation = Literal["off", "on"]
Tillage = Literal["conventional", "reduced", "no_till"]
Scenario = Literal["normal", "drought", "wet"]
Slot = Literal["A", "B"]
Winner = Literal["A", "B", "tie"]


# -----------------------------
# Data Models
# -----------------------------
class PlayerCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=24)


class PlayerPublic(BaseModel):
    player_id: str
    name: str
    rating: int
    wins: int
    losses: int
    ties: int
    games_played: int


class PlayerPrivate(PlayerPublic):
    token: str


class MatchCreateRequest(BaseModel):
    scenario: Scenario = "normal"
    crop_region: str = "il_cornbelt"


class Strategy(BaseModel):
    rotation: Rotation
    n_level: NLevel
    irrigation: Irrigation
    tillage: Tillage


class StrategySubmitRequest(Strategy):
    player_id: str


class JoinRequest(BaseModel):
    player_id: str
    slot: Slot


class JoinResponse(BaseModel):
    match_id: str
    slot: Slot
    player_id: str
    status: str


class SimResult(BaseModel):
    yield_t_ha: float
    n_leaching_kg_ha: float
    water_irrig_mm: float
    soil_c_delta_t_ha: float
    notes: Optional[str] = None


class Economics(BaseModel):
    revenue_usd_ha: float
    cost_usd_ha: float
    profit_usd_ha: float
    penalty_usd_ha: float
    score: float


class PlayerOutcome(BaseModel):
    player_id: str
    name: str
    strategy: Strategy
    sim: SimResult
    economics: Economics
    why: List[str]


class MatchRunResponse(BaseModel):
    match_id: str
    status: str
    winner: Winner
    winner_player_id: Optional[str] = None
    scenario: Scenario
    crop_region: str
    players: Dict[Slot, PlayerOutcome]


class MatchState(BaseModel):
    match_id: str
    scenario: Scenario
    crop_region: str
    status: str
    created_at: float
    slots: Dict[Slot, Optional[str]] = Field(default_factory=lambda: {"A": None, "B": None})
    strategies: Dict[Slot, Optional[Strategy]] = Field(default_factory=lambda: {"A": None, "B": None})
    result: Optional[MatchRunResponse] = None


# -----------------------------
# In-memory stores (hackathon)
# -----------------------------
PLAYERS: Dict[str, dict] = {}  # player_id -> {name, token, rating, wins, losses, ties, games_played}
MATCHES: Dict[str, MatchState] = {}

# -----------------------------
# Cycles precomputed table
# -----------------------------
# Key: f"{crop_region}|{scenario}|{rotation}|N={n}|irr={irr}|till={till}"
# Value: { yield_t_ha, n_leaching_kg_ha, water_irrig_mm, soil_c_delta_t_ha }
CYCLES_TABLE: Dict[str, dict] = {}


def load_cycles_table(path: str = "cycles_results.json") -> None:
    """Load precomputed Cycles outputs if present; otherwise keep table empty."""
    global CYCLES_TABLE
    try:
        with open(path, "r") as f:
            CYCLES_TABLE = json.load(f)
    except FileNotFoundError:
        CYCLES_TABLE = {}


load_cycles_table()


def make_key(crop_region: str, scenario: Scenario, s: Strategy) -> str:
    return f"{crop_region}|{scenario}|{s.rotation}|N={s.n_level}|irr={s.irrigation}|till={s.tillage}"


def require_player_token(player_id: str, token: Optional[str]) -> dict:
    p = PLAYERS.get(player_id)
    if not p:
        raise HTTPException(404, "player not found")
    if not token or token != p["token"]:
        raise HTTPException(401, "invalid or missing X-Player-Token")
    return p


# -----------------------------
# Scoring constants (tweak freely)
# -----------------------------
PRICES_USD_PER_T = {
    "corn": 190.0,
    "corn_soy": 185.0,      # hackathon simplification
    "wheat_cover": 220.0
}
N_APPLIED_KG_HA = {"low": 60, "medium": 120, "high": 180}
N_COST_USD_PER_KG = 1.10
IRRIGATION_COST_USD_PER_MM = 0.35

PENALTY_N_LEACH_USD_PER_KG = 3.0
PENALTY_WATER_USD_PER_MM = 0.25
PENALTY_SOILC_LOSS_USD_PER_T = 80.0  # penalize carbon loss only


def score(strategy: Strategy, sim: SimResult) -> Economics:
    price = PRICES_USD_PER_T[strategy.rotation]
    revenue = sim.yield_t_ha * price

    n_cost = N_APPLIED_KG_HA[strategy.n_level] * N_COST_USD_PER_KG
    irrig_cost = sim.water_irrig_mm * IRRIGATION_COST_USD_PER_MM
    cost = n_cost + irrig_cost

    profit = revenue - cost

    soilc_loss = max(0.0, -sim.soil_c_delta_t_ha)
    penalty = (
        sim.n_leaching_kg_ha * PENALTY_N_LEACH_USD_PER_KG
        + sim.water_irrig_mm * PENALTY_WATER_USD_PER_MM
        + soilc_loss * PENALTY_SOILC_LOSS_USD_PER_T
    )

    return Economics(
        revenue_usd_ha=round(revenue, 2),
        cost_usd_ha=round(cost, 2),
        profit_usd_ha=round(profit, 2),
        penalty_usd_ha=round(penalty, 2),
        score=round(profit - penalty, 2),
    )


def explain(strategy: Strategy, sim: SimResult, econ: Economics, scenario: Scenario) -> List[str]:
    """Return concise heuristic reasons for the outcome."""
    why: List[str] = []

    if scenario == "drought" and strategy.irrigation == "off":
        why.append("Drought scenario: no irrigation can cap yield but avoids irrigation costs.")
    if scenario == "drought" and strategy.irrigation == "on":
        why.append("Drought scenario: irrigation boosts yield but adds water + irrigation costs.")
    if strategy.n_level == "high" and sim.n_leaching_kg_ha > 15:
        why.append("High N increased leaching penalty.")
    if strategy.n_level == "low" and sim.yield_t_ha < 7.5 and scenario != "drought":
        why.append("Low N likely limited yield potential.")
    if strategy.tillage == "no_till" and sim.soil_c_delta_t_ha >= 0:
        why.append("No-till helped maintain or increase soil carbon.")
    if econ.penalty_usd_ha > 0.25 * max(1.0, econ.profit_usd_ha):
        why.append("Environmental penalties materially reduced final score.")

    if not why:
        why.append("Balanced strategy: costs and penalties stayed moderate relative to revenue.")

    return why


def lookup_or_precomputed(crop_region: str, scenario: Scenario, s: Strategy) -> SimResult:
    """
    If cycles_results.json contains the key -> use real values.
    Otherwise return deterministic precomputed values so the API is usable immediately.
    """
    key = make_key(crop_region, scenario, s)
    row = CYCLES_TABLE.get(key)
    if row is not None:
        return SimResult(**row)

    # Deterministic precomputed fallback (repeatable for a given key)
    h = int.from_bytes(key.encode("utf-8"), "little") % 1000
    base_y = {"normal": 9.0, "drought": 7.4, "wet": 8.6}[scenario]
    n_mult = {"low": 0.92, "medium": 1.0, "high": 1.04}[s.n_level]
    irr_boost = (
        1.08 if (scenario == "drought" and s.irrigation == "on") else
        0.97 if (scenario == "wet" and s.irrigation == "on") else
        1.0
    )
    till_mult = {"conventional": 1.0, "reduced": 0.995, "no_till": 0.99}[s.tillage]

    yield_t_ha = base_y * n_mult * irr_boost * till_mult + (h % 15) * 0.02

    n_leach = {"low": 8.0, "medium": 14.0, "high": 22.0}[s.n_level]
    if scenario == "wet":
        n_leach += 4.0
    if s.irrigation == "on":
        n_leach += 1.0

    water = 0.0 if s.irrigation == "off" else (65.0 if scenario == "drought" else 30.0)

    soilc = (
        0.05 if s.tillage == "no_till" else
        0.01 if s.tillage == "reduced" else
        -0.02
    )

    return SimResult(
        yield_t_ha=round(yield_t_ha, 2),
        n_leaching_kg_ha=round(n_leach, 2),
        water_irrig_mm=round(water, 2),
        soil_c_delta_t_ha=round(soilc, 3),
        notes="precomputed_fallback",
    )


# -----------------------------
# Elo rating (Chess-inspired)
# -----------------------------
def elo_expected(ra: float, rb: float) -> float:
    return 1.0 / (1.0 + 10 ** ((rb - ra) / 400.0))


def k_factor(games_played: int) -> int:
    # New players move faster; stabilize after ~10 games
    return 48 if games_played < 10 else 32


def elo_update(ra: int, rb: int, outcome: Winner, games_a: int, games_b: int) -> tuple[int, int]:
    ea = elo_expected(ra, rb)
    eb = elo_expected(rb, ra)

    if outcome == "A":
        sa, sb = 1.0, 0.0
    elif outcome == "B":
        sa, sb = 0.0, 1.0
    else:
        sa, sb = 0.5, 0.5

    ka = k_factor(games_a)
    kb = k_factor(games_b)

    new_ra = round(ra + ka * (sa - ea))
    new_rb = round(rb + kb * (sb - eb))
    return new_ra, new_rb


def update_player_stats_after_match(match: MatchState, winner: Winner) -> None:
    pA_id = match.slots.get("A")
    pB_id = match.slots.get("B")
    if not pA_id or not pB_id:
        return

    pA = PLAYERS.get(pA_id)
    pB = PLAYERS.get(pB_id)
    if not pA or not pB:
        return

    # Update W/L/T
    if winner == "tie":
        pA["ties"] += 1
        pB["ties"] += 1
    elif winner == "A":
        pA["wins"] += 1
        pB["losses"] += 1
    else:
        pA["losses"] += 1
        pB["wins"] += 1

    # Elo update
    newA, newB = elo_update(
        pA["rating"], pB["rating"], winner,
        pA["games_played"], pB["games_played"]
    )
    pA["rating"], pB["rating"] = newA, newB

    # Games played
    pA["games_played"] += 1
    pB["games_played"] += 1


# -----------------------------
# Routes: Players
# -----------------------------
@app.post("/v1/players", response_model=PlayerPrivate)
def create_player(req: PlayerCreateRequest):
    player_id = "p_" + secrets.token_hex(3)
    token = "t_" + secrets.token_hex(6)

    PLAYERS[player_id] = {
        "name": req.name,
        "token": token,
        "rating": 1500,
        "wins": 0,
        "losses": 0,
        "ties": 0,
        "games_played": 0,
    }
    p = PLAYERS[player_id]
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


@app.get("/v1/players/{player_id}", response_model=PlayerPublic)
def get_player(player_id: str):
    p = PLAYERS.get(player_id)
    if not p:
        raise HTTPException(404, "player not found")
    return PlayerPublic(
        player_id=player_id,
        name=p["name"],
        rating=p["rating"],
        wins=p["wins"],
        losses=p["losses"],
        ties=p["ties"],
        games_played=p["games_played"],
    )


# -----------------------------
# Routes: Matches
# -----------------------------
@app.post("/v1/matches", response_model=MatchState)
def create_match(req: MatchCreateRequest):
    match_id = "m_" + secrets.token_hex(3)
    m = MatchState(
        match_id=match_id,
        scenario=req.scenario,
        crop_region=req.crop_region,
        status="waiting_for_players",
        created_at=time.time(),
    )
    MATCHES[match_id] = m
    return m


@app.post("/v1/matches/{match_id}/join", response_model=JoinResponse)
def join_match(
    match_id: str,
    req: JoinRequest,
    x_player_token: Optional[str] = Header(default=None),
):
    require_player_token(req.player_id, x_player_token)

    m = MATCHES.get(match_id)
    if not m:
        raise HTTPException(404, "match not found")
    if m.status == "completed":
        raise HTTPException(409, "match already completed")

    current = m.slots[req.slot]
    if current and current != req.player_id:
        raise HTTPException(409, "slot already taken")

    # Prevent same player from taking both slots
    other_slot: Slot = "B" if req.slot == "A" else "A"
    if m.slots[other_slot] == req.player_id:
        raise HTTPException(409, "player already joined in the other slot")

    m.slots[req.slot] = req.player_id
    MATCHES[match_id] = m
    return JoinResponse(match_id=match_id, slot=req.slot, player_id=req.player_id, status="joined")


@app.post("/v1/matches/{match_id}/strategy")
def submit_strategy(
    match_id: str,
    req: StrategySubmitRequest,
    x_player_token: Optional[str] = Header(default=None),
):
    require_player_token(req.player_id, x_player_token)

    m = MATCHES.get(match_id)
    if not m:
        raise HTTPException(404, "match not found")
    if m.status == "completed":
        raise HTTPException(409, "match already completed")

    # Determine player's slot
    slot: Optional[Slot] = None
    for s in ("A", "B"):
        if m.slots[s] == req.player_id:
            slot = s  # type: ignore
            break
    if slot is None:
        raise HTTPException(409, "player is not joined to this match")

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

    MATCHES[match_id] = m
    return {"match_id": match_id, "status": "strategy_saved", "slot": slot}


@app.post("/v1/matches/{match_id}/run", response_model=MatchRunResponse)
def run_match(match_id: str):
    m = MATCHES.get(match_id)
    if not m:
        raise HTTPException(404, "match not found")
    if m.status == "completed" and m.result:
        return m.result
    if not m.strategies["A"] or not m.strategies["B"]:
        raise HTTPException(409, "both players must submit strategies before running")
    if not m.slots["A"] or not m.slots["B"]:
        raise HTTPException(409, "both slots must be filled before running")

    pA_id = m.slots["A"]
    pB_id = m.slots["B"]
    pA = PLAYERS.get(pA_id)
    pB = PLAYERS.get(pB_id)
    if not pA or not pB:
        raise HTTPException(404, "one or more players not found")

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

    outA = PlayerOutcome(
        player_id=pA_id,
        name=pA["name"],
        strategy=sA,
        sim=simA,
        economics=econA,
        why=explain(sA, simA, econA, m.scenario),
    )
    outB = PlayerOutcome(
        player_id=pB_id,
        name=pB["name"],
        strategy=sB,
        sim=simB,
        economics=econB,
        why=explain(sB, simB, econB, m.scenario),
    )

    result = MatchRunResponse(
        match_id=match_id,
        status="completed",
        winner=winner,
        winner_player_id=winner_player_id,
        scenario=m.scenario,
        crop_region=m.crop_region,
        players={"A": outA, "B": outB},
    )

    # Update Elo + stats once (only if not already completed)
    update_player_stats_after_match(m, winner)

    m.status = "completed"
    m.result = result
    MATCHES[match_id] = m
    return result


@app.get("/v1/matches/{match_id}", response_model=MatchState)
def get_match(match_id: str):
    m = MATCHES.get(match_id)
    if not m:
        raise HTTPException(404, "match not found")
    return m


# -----------------------------
# Leaderboard
# -----------------------------
@app.get("/v1/leaderboard")
def leaderboard(limit: int = 10):
    limit = max(1, min(limit, 50))
    leaders = []
    for pid, p in PLAYERS.items():
        leaders.append({
            "player_id": pid,
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
