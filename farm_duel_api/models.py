from __future__ import annotations

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field

Rotation = Literal["corn", "corn_soy", "wheat_cover"]
NLevel = Literal["low", "medium", "high"]
Irrigation = Literal["off", "on"]
Tillage = Literal["conventional", "reduced", "no_till"]
Scenario = Literal["normal", "drought", "wet"]
Slot = Literal["A", "B"]
Winner = Literal["A", "B", "tie"]


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

