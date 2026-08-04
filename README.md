# kiko-knowledge-service

# kiko-knowledge-service

知识体系平台 V1 后端：五级知识树、通用知识对象、教材映射、发布快照和开放只读接口。

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

`make install` 安装依赖；生产/集成环境使用 MySQL 8，启动前配置
`.env` 中的 `KIKO_KNOWLEDGE_DATABASE_URL`，再执行 `make db-init`。
本地快速冒烟可以使用默认 SQLite，但不能代替 MySQL 事务和锁验收。
`make dev` 启动 FastAPI，默认监听 `0.0.0.0:8001`，Swagger UI 地址为
`http://127.0.0.1:8001/docs`。

```bash
make db-init
make dev
```

## 质量检查

```bash
make lint
make format-check
make test
```

API 文档：启动后访问 `/docs`；健康检查为 `/healthz` 和 `/readyz`。
