.PHONY: install db-init dev test lint format-check

PYTHON ?= python3
PORT ?= 8001

install:
	$(PYTHON) -m pip install -e '.[test,dev]'

db-init:
	$(PYTHON) -m alembic upgrade head

dev:
	$(PYTHON) -m uvicorn app.main:app --host 0.0.0.0 --port $(PORT) --reload

test:
	$(PYTHON) -m pytest

lint:
	$(PYTHON) -m ruff check .

format-check:
	$(PYTHON) -m ruff format --check .
