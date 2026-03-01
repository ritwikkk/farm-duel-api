from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

from .models import (
    Economics,
    Scenario,
    SimResult,
    Strategy,
)

PRICES_USD_PER_T = {
    "corn": 190.0,
    "corn_soy": 185.0,
    "wheat_cover": 220.0,
}

N_APPLIED_KG_HA = {"low": 60, "medium": 120, "high": 180}
N_COST_USD_PER_KG = 1.10
IRRIGATION_COST_USD_PER_MM = 0.35

PENALTY_N_LEACH_USD_PER_KG = 3.0
PENALTY_WATER_USD_PER_MM = 0.25
PENALTY_SOILC_LOSS_USD_PER_T = 80.0

# Key: f"{crop_region}|{scenario}|{rotation}|N={n}|irr={irr}|till={till}"
CYCLES_TABLE: Dict[str, dict] = {}


def load_cycles_table(path: Path | str | None = None) -> None:
    """Load precomputed Cycles outputs if present; keep empty otherwise."""
    global CYCLES_TABLE
    path = Path(path) if path else Path(__file__).resolve().parent / "cycles_results.json"
    try:
        with path.open("r") as f:
            CYCLES_TABLE = json.load(f)
    except FileNotFoundError:
        CYCLES_TABLE = {}


load_cycles_table()


def make_key(crop_region: str, scenario: Scenario, s: Strategy) -> str:
    return f"{crop_region}|{scenario}|{s.rotation}|N={s.n_level}|irr={s.irrigation}|till={s.tillage}"


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
    reasons: List[str] = []

    if scenario == "drought" and strategy.irrigation == "off":
        reasons.append("Drought scenario: no irrigation can cap yield but avoids irrigation costs.")
    if scenario == "drought" and strategy.irrigation == "on":
        reasons.append("Drought scenario: irrigation boosts yield but adds water + irrigation costs.")
    if strategy.n_level == "high" and sim.n_leaching_kg_ha > 15:
        reasons.append("High N increased leaching penalty.")
    if strategy.n_level == "low" and sim.yield_t_ha < 7.5 and scenario != "drought":
        reasons.append("Low N likely limited yield potential.")
    if strategy.tillage == "no_till" and sim.soil_c_delta_t_ha >= 0:
        reasons.append("No-till helped maintain or increase soil carbon.")
    if econ.penalty_usd_ha > 0.25 * max(1.0, econ.profit_usd_ha):
        reasons.append("Environmental penalties materially reduced final score.")

    if not reasons:
        reasons.append("Balanced strategy: costs and penalties stayed moderate relative to revenue.")

    return reasons


def lookup_or_precomputed(crop_region: str, scenario: Scenario, s: Strategy) -> SimResult:
    key = make_key(crop_region, scenario, s)
    row = CYCLES_TABLE.get(key)
    if row is not None:
        return SimResult(**row)

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

