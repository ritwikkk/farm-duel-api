PY=python3
UVICORN=uvicorn

.PHONY: run test lint

run:
	$(UVICORN) farm_duel_api.main:app --reload

test:
	$(PY) -m pytest -q

