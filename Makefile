.PHONY: install setup db-init dev test

PYTHON ?= python3
MYSQL ?= $(shell command -v mysql 2>/dev/null || printf /usr/local/mysql/bin/mysql)
PORT ?= 8001

install:
	$(PYTHON) -m pip install -e '.[mysql,test,dev]'

setup: install db-init

db-init:
	@command -v $(MYSQL) >/dev/null || { echo "未找到 mysql 客户端，请先安装并启动 MySQL 8"; exit 1; }
	@$(MYSQL) -h 127.0.0.1 -P 3306 -u root -p -e "CREATE DATABASE IF NOT EXISTS kiko_knowledge CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci; CREATE USER IF NOT EXISTS 'kiko'@'localhost' IDENTIFIED BY 'kiko-development'; ALTER USER 'kiko'@'localhost' IDENTIFIED BY 'kiko-development'; CREATE USER IF NOT EXISTS 'kiko'@'127.0.0.1' IDENTIFIED BY 'kiko-development'; ALTER USER 'kiko'@'127.0.0.1' IDENTIFIED BY 'kiko-development'; GRANT ALL PRIVILEGES ON kiko_knowledge.* TO 'kiko'@'localhost'; GRANT ALL PRIVILEGES ON kiko_knowledge.* TO 'kiko'@'127.0.0.1';"
	$(PYTHON) -m alembic upgrade head

dev:
	@trap 'kill $$api_pid $$worker_pid $$beat_pid 2>/dev/null' EXIT INT TERM; \
	$(PYTHON) -m uvicorn app.main:app --host 0.0.0.0 --port $(PORT) --reload & api_pid=$$!; \
	$(PYTHON) -m celery -A app.celery_app:celery worker -Q knowledge-classification,knowledge-maintenance --loglevel=info & worker_pid=$$!; \
	$(PYTHON) -m celery -A app.celery_app:celery beat --loglevel=info & beat_pid=$$!; \
	wait

test:
	$(PYTHON) -m pytest
