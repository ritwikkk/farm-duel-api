from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional

from .models import MatchRunResponse, MatchState, Strategy

DB_PATH = os.getenv("FARM_DUEL_DB", "farm_duel.db")
_conn: Optional[sqlite3.Connection] = None


def get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
    return _conn


def init_db(path: str | None = None) -> None:
    global DB_PATH, _conn
    if path:
        DB_PATH = path
        _conn = None
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS players (
            player_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            token TEXT NOT NULL,
            rating INTEGER NOT NULL,
            wins INTEGER NOT NULL,
            losses INTEGER NOT NULL,
            ties INTEGER NOT NULL,
            games_played INTEGER NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS matches (
            match_id TEXT PRIMARY KEY,
            scenario TEXT NOT NULL,
            crop_region TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at REAL NOT NULL,
            slots_json TEXT NOT NULL,
            strategies_json TEXT NOT NULL,
            result_json TEXT
        )
        """
    )
    conn.commit()


def clear_all():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM players")
    cur.execute("DELETE FROM matches")
    conn.commit()


# ---------------- Players ----------------
def create_player(record: dict) -> None:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO players (player_id, name, token, rating, wins, losses, ties, games_played)
        VALUES (:player_id, :name, :token, :rating, :wins, :losses, :ties, :games_played)
        """,
        record,
    )
    conn.commit()


def get_player(player_id: str) -> Optional[dict]:
    cur = get_conn().cursor()
    cur.execute("SELECT * FROM players WHERE player_id = ?", (player_id,))
    row = cur.fetchone()
    return dict(row) if row else None


def list_players(limit: int, offset: int, search: str | None = None) -> List[dict]:
    cur = get_conn().cursor()
    params = []
    q = "SELECT * FROM players"
    if search:
        q += " WHERE LOWER(name) LIKE ?"
        params.append(f"%{search.lower()}%")
    q += " ORDER BY player_id LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    cur.execute(q, params)
    return [dict(r) for r in cur.fetchall()]


def count_players(search: str | None = None) -> int:
    cur = get_conn().cursor()
    params = []
    q = "SELECT COUNT(*) FROM players"
    if search:
        q += " WHERE LOWER(name) LIKE ?"
        params.append(f"%{search.lower()}%")
    cur.execute(q, params)
    return cur.fetchone()[0]


def update_player_stats(player_id: str, data: dict) -> None:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE players
        SET rating=:rating, wins=:wins, losses=:losses, ties=:ties, games_played=:games_played
        WHERE player_id=:player_id
        """,
        {**data, "player_id": player_id},
    )
    conn.commit()


# ---------------- Matches ----------------
def _encode_match(m: MatchState) -> dict:
    slots_json = json.dumps(m.slots)
    strategies_json = json.dumps({
        k: (v.dict() if v else None) for k, v in m.strategies.items()
    })
    result_json = json.dumps(m.result.dict()) if m.result else None
    return {
        "match_id": m.match_id,
        "scenario": m.scenario,
        "crop_region": m.crop_region,
        "status": m.status,
        "created_at": m.created_at,
        "slots_json": slots_json,
        "strategies_json": strategies_json,
        "result_json": result_json,
    }


def _row_to_match(row: sqlite3.Row) -> MatchState:
    slots = json.loads(row["slots_json"])
    raw_strats = json.loads(row["strategies_json"])
    strategies: Dict[str, Optional[Strategy]] = {}
    for k, v in raw_strats.items():
        strategies[k] = Strategy(**v) if v else None
    result = None
    if row["result_json"]:
        result = MatchRunResponse.parse_obj(json.loads(row["result_json"]))
    return MatchState(
        match_id=row["match_id"],
        scenario=row["scenario"],
        crop_region=row["crop_region"],
        status=row["status"],
        created_at=row["created_at"],
        slots=slots,
        strategies=strategies,
        result=result,
    )


def create_match(m: MatchState) -> None:
    conn = get_conn()
    cur = conn.cursor()
    data = _encode_match(m)
    cur.execute(
        """
        INSERT INTO matches (match_id, scenario, crop_region, status, created_at, slots_json, strategies_json, result_json)
        VALUES (:match_id, :scenario, :crop_region, :status, :created_at, :slots_json, :strategies_json, :result_json)
        """,
        data,
    )
    conn.commit()


def save_match(m: MatchState) -> None:
    conn = get_conn()
    cur = conn.cursor()
    data = _encode_match(m)
    cur.execute(
        """
        UPDATE matches
        SET scenario=:scenario, crop_region=:crop_region, status=:status,
            created_at=:created_at, slots_json=:slots_json, strategies_json=:strategies_json, result_json=:result_json
        WHERE match_id=:match_id
        """,
        data,
    )
    conn.commit()


def get_match(match_id: str) -> Optional[MatchState]:
    cur = get_conn().cursor()
    cur.execute("SELECT * FROM matches WHERE match_id = ?", (match_id,))
    row = cur.fetchone()
    return _row_to_match(row) if row else None


def list_matches(status: Optional[str], limit: int, offset: int) -> List[MatchState]:
    cur = get_conn().cursor()
    params = []
    q = "SELECT * FROM matches"
    if status:
        q += " WHERE status = ?"
        params.append(status)
    q += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    cur.execute(q, params)
    return [_row_to_match(r) for r in cur.fetchall()]


def count_matches(status: Optional[str]) -> int:
    cur = get_conn().cursor()
    params = []
    q = "SELECT COUNT(*) FROM matches"
    if status:
        q += " WHERE status = ?"
        params.append(status)
    cur.execute(q, params)
    return cur.fetchone()[0]
