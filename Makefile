.PHONY: install db-init dev test lint format-check

PYTHON ?= python3
MYSQL ?= mysql
PORT ?= 8001

install:
	$(PYTHON) -m pip install -e '.[mysql,test,dev]'

db-init:
	@command -v $(MYSQL) >/dev/null || { echo "未找到 mysql 客户端，请先安装并启动 MySQL 8"; exit 1; }
	$(PYTHON) -m alembic upgrade head

dev:
	$(PYTHON) -m uvicorn app.main:app --host 0.0.0.0 --port $(PORT) --reload

test:
	$(PYTHON) -m pytest

lint:
	$(PYTHON) -m ruff check .

format-check:
	$(PYTHON) -m ruff format --check .
