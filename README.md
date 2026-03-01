# Farm Duel API

Head‑to‑head farm strategy duels with Elo ratings. Players join matches, submit 4‑knob strategies, and get scored with precomputed Cycles outputs (or deterministic precomputed fallback) so results are instant and repeatable.

## Quickstart
```bash
pip install -r requirements.txt
uvicorn farm_duel_api.main:app --reload
```
Open Swagger UI: `http://localhost:8000/docs`  
Redoc: `http://localhost:8000/redoc`  
Health: `http://localhost:8000/v1/meta/health`  
Info: `http://localhost:8000/v1/meta/info`

## API essentials
- Base URL: `http://localhost:8000`
- Version: `v1` (app version 1.1)
- Auth: header `X-Player-Token` for join/strategy. Public GETs need no auth.
- Idempotency: `/v1/matches/{id}/run` returns cached result if already completed; Elo updates only once.
- Pagination: `limit` (1–100) and `offset` on list endpoints; leaderboard uses `limit` only.
- Content type: JSON requests/responses.
- Errors: `{ "detail": "<message>" }` with meaningful 4xx codes.
- CORS: default allow-all for local dev; override with env `FARM_DUEL_CORS` (CSV origins).
- State: in-memory only; restart wipes data.

## Core concepts
- **Player**: name, `player_id` (public), `token` (secret), Elo rating (start 1500), wins/losses/ties/games_played.
- **Match**: `match_id`, `scenario` (`normal|drought|wet`), `crop_region` (e.g., `il_cornbelt`), `status` (`waiting_for_players|ready|completed`), slots A/B, strategies A/B, result after run.
- **Strategy (4 knobs)**:
  - rotation: `corn | corn_soy | wheat_cover`
  - n_level: `low | medium | high` (60/120/180 kg N/ha)
  - irrigation: `off | on`
  - tillage: `conventional | reduced | no_till`
- **Scoring**:
  - Revenue = yield_t_ha × price (corn 190, corn_soy 185, wheat_cover 220)
  - Costs = N (1.10/kg) + irrigation (0.35/mm)
  - Penalties = leaching (3.0/kg) + irrigation water (0.25/mm) + soil C loss (80/t, only if negative)
  - Score = profit − penalties; higher score wins; tie if equal.
  - Why bullets explain key drivers.
- **Elo**:
  - Expected: `E = 1 / (1 + 10^((R_opp - R_self)/400))`
  - K-factor: 48 if games_played < 10 else 32
  - Update: `R' = R + K * (S - E)` where S = 1 win, 0.5 tie, 0 loss

## Endpoints (concise)
- Players:  
  - `POST /v1/players` create  
  - `GET /v1/players/{player_id}` fetch  
  - `GET /v1/players?limit=&offset=&search=` list/search
- Matches:  
  - `POST /v1/matches` create  
  - `GET /v1/matches/{match_id}` fetch  
  - `GET /v1/matches?status=&limit=&offset=` list/filter  
  - `POST /v1/matches/{id}/join` (auth) claim slot A/B  
  - `POST /v1/matches/{id}/strategy` (auth) submit strategy  
  - `POST /v1/matches/{id}/run` run match (idempotent)
- Leaderboard: `GET /v1/leaderboard?limit=10`
- Meta: `GET /v1/meta/health`, `GET /v1/meta/info`

## Workflow at a glance
1) POST `/v1/players` → get `player_id`, `token`.
2) POST `/v1/matches` → get `match_id`.
3) POST `/v1/matches/{id}/join` (A/B) with token.
4) POST `/v1/matches/{id}/strategy` (each player) with token.
5) POST `/v1/matches/{id}/run` → winner, scores, why bullets.
6) GET `/v1/leaderboard` → Elo-based ranking.

## Curl flow (end-to-end)
```bash
# 1) Create players
alice=$(curl -s -X POST http://localhost:8000/v1/players -H "Content-Type: application/json" -d '{"name":"Alice"}')
bob=$(curl -s -X POST http://localhost:8000/v1/players -H "Content-Type: application/json" -d '{"name":"Bob"}')
APID=$(echo $alice | jq -r .player_id); ATOK=$(echo $alice | jq -r .token)
BID=$(echo $bob | jq -r .player_id); BTOK=$(echo $bob | jq -r .token)

# 2) Create match
MID=$(curl -s -X POST http://localhost:8000/v1/matches -H "Content-Type: application/json" \
  -d '{"scenario":"normal","crop_region":"il_cornbelt"}' | jq -r .match_id)

# 3) Join slots
curl -s -X POST http://localhost:8000/v1/matches/$MID/join -H "X-Player-Token: $ATOK" \
  -H "Content-Type: application/json" -d "{\"player_id\":\"$APID\",\"slot\":\"A\"}"
curl -s -X POST http://localhost:8000/v1/matches/$MID/join -H "X-Player-Token: $BTOK" \
  -H "Content-Type: application/json" -d "{\"player_id\":\"$BID\",\"slot\":\"B\"}"

# 4) Submit strategies
curl -s -X POST http://localhost:8000/v1/matches/$MID/strategy -H "X-Player-Token: $ATOK" \
  -H "Content-Type: application/json" \
  -d "{\"player_id\":\"$APID\",\"rotation\":\"corn\",\"n_level\":\"low\",\"irrigation\":\"off\",\"tillage\":\"no_till\"}"
curl -s -X POST http://localhost:8000/v1/matches/$MID/strategy -H "X-Player-Token: $BTOK" \
  -H "Content-Type: application/json" \
  -d "{\"player_id\":\"$BID\",\"rotation\":\"corn\",\"n_level\":\"high\",\"irrigation\":\"on\",\"tillage\":\"conventional\"}"

# 5) Run match
curl -s -X POST http://localhost:8000/v1/matches/$MID/run | jq .

# 6) Leaderboard
curl -s http://localhost:8000/v1/leaderboard | jq .
```

## Models (quick reference)
- Player (response): `{ player_id, name, token?, rating, wins, losses, ties, games_played }`
- Strategy (request): `{ rotation, n_level, irrigation, tillage }`
- Match state: `{ match_id, scenario, crop_region, status, slots{A,B}, strategies{A,B}, result? }`
- Match run result: `{ match_id, status, winner, winner_player_id, scenario, crop_region, players{A,B}{player_id,name,strategy,sim,economics,why} }`
- Leaderboard row: `{ rank, player_id, name, rating, wins, losses, ties, games_played }`

## Error model (examples)
- Slot taken: `409 { "detail": "slot A is already taken by another player" }`
- Strategy before join: `409 { "detail": "player must join the match in a slot before submitting a strategy" }`
- Run before ready: `409 { "detail": "cannot run: both slots must have strategies submitted" }`
- Invalid token: `401 { "detail": "invalid or missing X-Player-Token for this player" }`

## Pagination
- Players: `limit` (1–100), `offset`, optional `search` (name substring)
- Matches: `limit` (1–100), `offset`, optional `status`
- Leaderboard: `limit` (1–50)

## Data + simulation
- Precomputed lookup: optional `cycles_results.json` beside the package; key format `"{crop_region}|{scenario}|{rotation}|N={n_level}|irr={irrigation}|till={tillage}"`.
- Fallback: deterministic precomputed values for any missing key so API always responds.
- In-memory store: players/matches live in process memory; restarting the server clears state.

## Testing
```bash
pytest -q
```

## Troubleshooting
- 404 on `/` or `/api/...`: expected; use documented endpoints (see above or `/docs`).
- 401 invalid token: ensure `X-Player-Token` matches the `player_id`.
- 409 slot taken: the other player already claimed that slot.
- 409 run before ready: both slots must be filled and both strategies submitted.

## Environment variables
- `FARM_DUEL_CORS` — CSV of allowed origins for CORS (default `*`).
- (Optional future) `FARM_DUEL_TABLE_PATH` — custom path for `cycles_results.json` if added.

## Tech stack
- FastAPI, Uvicorn, Pydantic v2, HTTPX (testing), Python 3.13
- No DB by default; easy to add SQLite/JSON persistence later.

## Notes
- 404s on `/` or unknown paths are expected—use the documented endpoints.
- Use `FARM_DUEL_CORS` env (csv origins) to override default permissive CORS.
