from __future__ import annotations

from .models import Winner


def elo_expected(ra: float, rb: float) -> float:
    return 1.0 / (1.0 + 10 ** ((rb - ra) / 400.0))


def k_factor(games_played: int) -> int:
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

