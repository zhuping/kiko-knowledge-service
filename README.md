# kiko-knowledge-service

课程知识底座后端：版本化教材知识包、可追溯题目判断和教研反馈闭环。

## 本地启动

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
cp .env.example .env
chmod 600 .env
make setup
make dev
```

`make setup` 会安装依赖，提示输入本机 MySQL `root` 密码，创建
`kiko_knowledge` 数据库和本地 `kiko` 账号，再执行 Alembic 迁移。
`make dev` 会同时启动 FastAPI、Celery Worker 和 Celery Beat；请先确保
本机 MySQL 8 和 Redis 已启动。知识服务默认监听 `0.0.0.0:8001`，
Swagger UI 地址为 `http://127.0.0.1:8001/docs`；临时换端口可运行
`make dev PORT=端口号`。

```bash
make db-init
make test
```

## 质量检查

```bash
ruff check .
ruff format --check .
make test
pre-commit run --all-files
```

API 文档：启动后访问 `/docs`；健康检查为 `/health/live` 和
`/health/ready`。
