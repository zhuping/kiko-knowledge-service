# kiko-knowledge-service

知识体系平台 V1 后端：通用知识对象、教材映射、不可变发布快照和供 `kiko-backend` 使用的 HMAC 开放只读接口。正式快照冻结教材元数据、目录内知识点顺序、多目录映射、跨知识库关系和内容哈希。

## 本地启动

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
cp .env.example .env
chmod 600 .env
make install
make db-init
make dev
```

`make install` 安装依赖；生产/集成环境使用 MySQL 8，启动前配置
`.env` 中的 `KIKO_KNOWLEDGE_DATABASE_URL`，再执行 `make db-init` 初始化或升级数据库。
`make db-init` 会同时导入 `seed_data/` 中一年级、二年级原子知识点 Excel
及其前置关系；重复执行已完成的种子导入会自动跳过。
知识点 `canonicalId` 统一为以 1 开头的 8 位纯数字字符串；人工新建时由后端自动生成，Excel 导入时由文件提供。
本地快速冒烟可以使用默认 SQLite，但不能代替 MySQL 事务和锁验收。
`make dev` 启动 FastAPI，默认监听 `0.0.0.0:8001`，Swagger UI 地址为
`http://127.0.0.1:8001/docs`。

## APP 客户端凭证

先配置 `KIKO_KNOWLEDGE_API_SECRET_KEY`（Fernet key），再创建只读客户端：

```bash
python -m app.create_api_client kiko-backend
```

命令只显示一次原始 Secret。将 AppKey 和 Secret 通过部署 Secret 注入 `kiko-backend`，不要写入仓库、移动端或业务表。开放列表只返回“已有正式版本且未下线”的知识库；`content` 业务读取应始终显式传 `releaseVersion`。

## 质量检查

```bash
make lint
make format-check
make test
```

API 文档：启动后访问 `/docs`；健康检查为 `/healthz` 和 `/readyz`。

正式接口契约详见 [`docs/backend/02-知识体系平台接口契约文档.md`](docs/backend/02-知识体系平台接口契约文档.md)。执行 `make db-init` 会升级到 `0009_app_release_contract`，为已有映射回填稳定顺序并冻结历史发布元数据。
