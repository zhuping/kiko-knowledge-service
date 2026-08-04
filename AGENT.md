# AGENT.md

## 项目定位

本仓库实现“乐学知低年级教育辅助 App——知识体系平台”V1.0 后端。它是内部知识内容管理与发布服务，为业务端提供已发布知识内容、教材映射、知识关系和政策规则依据。

当前 V1 以以下文档为准：

- 产品范围、运营流程和交互语义：`docs/product/01-知识体系平台产品需求文档（PRD）.md`
- 技术实现、接口、数据模型和实施顺序：`docs/backend/01-知识体系平台后端技术方案.md`
- 知识体系平台接口契约文档：`docs/backend/02-知识体系平台接口契约文档.md`

后端技术方案对接口路径、字段、发布模型、任务执行和错误处理优先于 PRD 中的接口示例。文档与代码冲突时先确认最新决策并恢复一致，不要用现有代码的行为反推产品方案。

## V1 范围

### 必须支持

- 人教版小学数学 2024 审定新版（六三制）一年级、二年级上下册；
- 五级知识结构：领域、主题、单元、知识点组、原子知识点；
- 通用知识对象、教材目录、教材映射、政策规则映射和知识关联；
- 草稿编辑、Excel 批量导入、结构校验、发布批次、正式快照、版本预览、版本差异和回滚；
- 内部运营后台接口；
- 面向业务端的已发布内容只读接口；
- MySQL 任务表驱动的导入、导出和发布校验任务；
- 操作审计、AppKey/HMAC 鉴权、限流和接口契约测试。

### V1 不做

- 题库、OCR、题目最终知识点匹配、学生掌握度和推荐算法；
- C 端用户功能或学习页面；
- 复杂知识图谱可视化编辑；
- 三年级以上或其他教材版本的首期内容；
- 复杂多级审核流程；V1 只区分编辑者、发布者和管理员；
- 微服务、分库分表、读写分离、搜索引擎、消息队列或 Redis/Celery；
- 将 `supplement`、`未掌握` 或缺少匹配直接当成永久“超纲”结论。

不要为了未来可能的题库同步、复杂审核或高并发提前建设抽象和基础设施。

## 技术基线

- Python 3.9；
- FastAPI；
- SQLAlchemy 2.x + Alembic；
- PyMySQL + MySQL 8/InnoDB/`utf8mb4`；
- Pydantic 请求/响应模型和领域服务校验；
- openpyxl 仅用于 Excel 导入、导出和模板生成；
- MySQL `job` 表 + 独立 worker；任务状态以数据库为准；
- HTTPS 网关/Nginx → FastAPI，MySQL 独立部署。

实现从本方案重新建立，不能为了迁就任何既有实现而恢复已删除的技术栈或业务边界。

## 代码结构和依赖方向

推荐结构：

```text
kiko-knowledge-service/
├── app/
│   ├── main.py
│   ├── core/
│   │   ├── config.py
│   │   ├── db.py
│   │   ├── auth.py
│   │   ├── response.py
│   │   └── errors.py
│   ├── api/
│   │   ├── admin.py
│   │   └── open.py
│   ├── modules/
│   │   ├── catalog/
│   │   ├── knowledge/
│   │   ├── mapping/
│   │   ├── relation/
│   │   ├── release/
│   │   ├── import_export/
│   │   └── audit/
│   └── jobs/
│       ├── worker.py
│       └── handlers.py
├── migrations/
├── scripts/
├── tests/
│   ├── unit/
│   ├── integration/
│   └── contract/
└── docs/
```

依赖方向固定为：

```text
main → api → module service → repository → model/database
                                      ↘ schema when needed
jobs → module service
```

规则：

- `main.py` 只负责应用创建、生命周期和路由注册；
- `api/admin.py`、`api/open.py` 只负责 HTTP 参数、鉴权依赖、调用 Service 和统一响应；
- 业务规则、权限复核、状态迁移、快照构建和事务边界放在对应模块 Service；
- Repository 只负责查询、持久化和数据库锁，不提交事务、不承载业务规则；
- 每个业务模块只保留 `router`、`service`、`repository`、`schema`、`model` 五类职责；
- `jobs` 只领取任务并调用已有 Service，不复制导入、校验或发布逻辑；
- 不创建通用 Repository、BaseService、事件总线、复杂 DDD 框架或单实现工厂；
- 模块不得直接操作其他模块的表，跨模块协作通过 Service 或明确的查询边界完成；
- 数据库事务或行锁期间不得调用远端 HTTP、对象存储或其他慢外部服务。

## 领域和数据模型

### 领域职责

| 模块 | 职责 |
|---|---|
| `catalog` | 教材版本、1～4 级目录节点和五级挂载 |
| `knowledge` | 通用知识对象和独立词项 |
| `mapping` | 教材映射、政策规则和政策映射 |
| `relation` | 前置、后继、平行、交叉关系 |
| `release` | 变更、发布批次、校验、正式快照、版本历史和回滚 |
| `import_export` | Markdown/Excel 初始导入、Excel 预校验、导入导出任务 |
| `audit` | 登录、编辑、导入、导出、停用、发布和回滚审计 |

### 五级结构

- 1～4 级存入 `catalog_node`，通过 `parent_id` 建立相邻层级父子关系；
- 5 级存入 `catalog_knowledge_node`，只能挂到四级知识点组；
- 目录节点属于教材版本/编辑空间；知识对象不等同于某一版本教材目录；
- 同一个知识对象可映射多个教材位置，教材目录和通用知识对象通过映射连接。

### 核心表

按技术方案维护以下模型：

`content_space`、`textbook_edition`、`knowledge_object`、`knowledge_term`、`catalog_node`、`catalog_knowledge_node`、`textbook_mapping`、`knowledge_relation`、`policy_rule`、`knowledge_policy_mapping`、`change_log`、`release_batch`、`release_batch_item`、`release_version`、`release_current`、各类 `release_*` 快照表、`job`、`api_client`、`api_nonce`、`api_rate_bucket`、`audit_log`。

不要把别名、场景、方法、易错点或 `review_set` 建成新的 `canonical_id`；它们应作为词项、标签、集合或映射维护。

## 不可破坏的业务规则

### 稳定 ID和内容

- `canonical_id` 是跨教材稳定的全局知识对象 ID，创建后不可修改、不可复用；
- ID 不包含出版社、年份、册次、单元顺序或教材路径；接口统一映射为 `canonicalId`，不得新增或使用 `knowledgeCode`；
- 推荐格式为 `^[a-z][a-z0-9_]*(\.[a-z0-9_]+)+$`；名称、教材位置或发布版本变化不修改 ID；
- 只有学习目标、数值范围或解法要求发生实质变化时才新建 ID，并保留关系；
- 别名、核心关键词、衍生词使用数组或独立记录，不用逗号拼接字符串；
- 正式版本只追加，不 UPDATE、不 DELETE；已引用内容只能停用/废弃并保留历史。

### 关系和映射

- `prerequisite` 只保存有方向的一条关系；`successors` 由反向查询计算，不单独落库；
- `parallel`、`cross` 保存规范化的单条记录，查询时按两端返回；禁止自关联；
- 前置关系必须无环；平行和交叉关系不按有向环处理；跨年级/跨学期关系必须有依据；
- 启用知识对象至少有一条有效教材映射；同一知识对象、教材位置和映射类型不可重复；
- 教材映射和政策规则映射独立维护，解除教材映射不能自动删除政策映射；
- `scope=core/supplement` 用于组织、召回和展示，不直接等价于超纲；范围接口返回依据、规则版本和状态，由业务端完成最终业务判断。

### 草稿、发布和回滚

- 后台读写当前编辑空间；开放接口只读正式快照，绝不从草稿表拼装数据；
- 草稿使用整数 `row_version` 乐观锁，冲突返回 `409`，禁止静默覆盖；
- 草稿保存必须在同一事务写业务数据、词项/关系、`change_log` 和必要的 `audit_log`；
- 发布批次只包含选中的变更；发布时校验 `selected_hash`，未选中的其他草稿不得混入；
- 发布前检查层级、必填字段、ID、引用、映射、关系、摘要和快照一致性；错误阻止发布，风险需发布者确认；
- 发布事务锁定唯一一行 `release_current`，复制基础正式快照、应用批次变更、计算 `content_hash`、写入新版本和快照，再更新 current 指针；
- 发布失败整体回滚；正式版本生成后不可变；
- 回滚不是修改旧版本，而是以历史正式快照创建新的 `rollback` 发布批次和新正式版本，中间版本、来源和审计链全部保留。

## 任务、幂等和并发

- `job` 表是导入、导出、校验和发布任务的唯一业务状态来源；
- worker 使用 MySQL 8 行锁领取任务，例如 `SELECT ... FOR UPDATE SKIP LOCKED`；领取后改为 `running`；
- 任务处理器必须幂等，重复执行不得产生重复映射、版本或审计结果；
- 任务失败支持有限次数重试和人工重试，超过次数进入 `failed` 并保留错误明细；
- Excel 流程固定为：上传 → 大小/扩展名/MIME/表头校验 → 逐行业务预校验 → 错误报告 → 确认提交 → 整批事务写入；
- 单次 Excel 最多 1000 行；预校验不写业务表，确认提交不允许部分成功；
- 提交时校验文件摘要和编辑空间版本，防止重复提交或覆盖新修改；
- worker 只传稳定任务 ID，不在 HTTP 请求中阻塞等待任务完成。

Markdown 初始导入必须解析标题、表格、`canonical_id`、教材路径、前置关系和词项；按源文件摘要幂等执行。同一源文件不得重复导入，目标内容已被人工修改时必须停止并报告冲突。

## API 契约

### 路径

- 管理端：`/api/v1/admin/...`；
- 开放端：`/api/v1/open/...`；
- 健康检查：`/healthz`、`/readyz`；
- API 长期引用使用 `canonicalId`，不使用内部目录 ID、教材路径或展示名称；
- V1 的业务端接口只返回已发布内容；指定 `releaseVersion` 时读取对应历史正式快照。

### 管理端核心接口

```text
GET        /api/v1/admin/catalog/tree
POST/PATCH /api/v1/admin/catalog/nodes
POST       /api/v1/admin/catalog/nodes/{id}/move
POST       /api/v1/admin/knowledge
GET/PATCH  /api/v1/admin/knowledge/{canonicalId}
POST       /api/v1/admin/imports
GET        /api/v1/admin/jobs/{jobId}
POST       /api/v1/admin/textbook-mappings/batch
POST       /api/v1/admin/policy-mappings/batch
POST       /api/v1/admin/relations/batch
POST       /api/v1/admin/release-batches
POST       /api/v1/admin/release-batches/{id}/validate
POST       /api/v1/admin/release-batches/{id}/publish
POST       /api/v1/admin/releases/{version}/rollback
GET        /api/v1/admin/releases
GET        /api/v1/admin/releases/{version}/diff
GET        /api/v1/admin/audit-logs
```

### 开放端核心接口

```text
GET  /api/v1/open/knowledge/tree
POST /api/v1/open/knowledge/search
POST /api/v1/open/knowledge/details:batch
GET  /api/v1/open/knowledge/{canonicalId}/relations
GET  /api/v1/open/knowledge/filter
POST /api/v1/open/scope:check
```

### 字段、响应和错误

- 数据库/内部 Python 字段使用 `snake_case`，API 字段使用 `camelCase`；
- 数组保持 JSON 数组，不序列化成逗号字符串；时间以 UTC 存储并返回 ISO 8601；
- 成功响应至少包含 `code`、`message`、`requestId`、`data`，查询响应携带 `releaseVersion`；
- 分页默认 `pageNum=1`、`pageSize=10`，最大 `pageSize=100`；
- 错误必须包含稳定业务码、可读消息、必要的详情和 `requestId`；批量错误包含行号/对象 ID、字段、原因和修复建议；
- 重点错误码：`PARAM_INVALID`、`AUTH_FAILED`、`FORBIDDEN`、`NOT_FOUND`、`CONFLICT`、`VALIDATION_FAILED`、`RATE_LIMITED`、`INTERNAL_ERROR`、`SERVICE_UNAVAILABLE`；
- 修改接口必须同步更新 Schema、Service、OpenAPI、契约测试和对应调用方；不复制其他仓库代码到本仓库。

## 鉴权和安全

### 管理端

- 优先接入公司 SSO/OIDC；服务只负责令牌校验和角色映射；
- V1 角色为编辑者、发布者、管理员；路由依赖和领域 Service 都要校验权限；
- 不使用前端按钮隐藏代替后端授权。

| 角色 | 允许操作 |
|---|---|
| 编辑者 | 草稿编辑、导入/导出、创建发布批次、发起校验 |
| 发布者 | 编辑者全部权限，以及确认发布、创建回滚批次 |
| 管理员 | 发布者全部权限，以及停用内容、版本管理和异常处理 |

### 开放端

请求头：

```text
X-App-Key: app_xxx
X-Timestamp: 1780000000
X-Nonce: random-string
X-Signature: base64(hmac_sha256(secret, canonical_request))
```

签名原文固定为：

```text
HTTP_METHOD\n
REQUEST_PATH\n
SHA256(QUERY_STRING)\n
SHA256(REQUEST_BODY)\n
TIMESTAMP\n
NONCE
```

服务端按顺序校验时间窗口（默认 ±300 秒）、AppKey 状态和权限、`(app_key, nonce)` 唯一性、HMAC 签名和请求参数。签名比较使用 constant-time compare。Secret 以加密形式保存，解密密钥来自部署密钥管理，不进入代码或日志。

限流优先由网关按 AppKey 执行，V1 基线为每分钟 1000 次；无网关时使用 MySQL 分钟桶兜底。高并发时再替换限流实现，不改变接口协议。

通用安全要求：

- 所有传输使用 HTTPS；SQL 使用参数化查询；
- 上传限制扩展名、MIME、大小、行数并使用随机文件名；
- 导出文件使用短期下载地址并按权限控制；
- 审计登录、编辑、映射、关系、停用、导入、导出、发布和回滚，包含操作者、对象、摘要、结果和 `requestId`；
- 日志不得记录 Secret、完整签名、敏感请求体或敏感教材内容；
- 数据库账号按迁移、读写和只读接口拆分最小权限。

## 测试和质量门禁

至少覆盖：

- `canonical_id` 格式、唯一性、稳定性和不可复用；
- 五级父子关系、同层排序和前置关系成环检测；
- 映射去重、政策映射独立性和发布前完整性校验；
- 草稿乐观锁、批量导入整批提交/整批回滚；
- 发布后开放接口只读新正式快照，未选草稿不混入；
- 正式版本不可变，回滚生成新版本且历史版本不变；
- MySQL 事务、唯一约束、行锁和 `SKIP LOCKED` 必须用 MySQL 8 集成测试；
- HMAC、时间窗口、Nonce 重放、角色权限和限流；
- OpenAPI 响应字段、`canonicalId`、数组、分页、错误码和历史 `releaseVersion` 查询；
- 树查询、检索、批量详情和发布校验的性能基线：常规查询 P95 ≤ 500ms，条件检索 P95 ≤ 800ms；
- 批量详情最多 100 个 `canonicalId`，Excel 单批最多 1000 行，发布校验单批最多 5000 个变更对象。

不要只断言 HTTP 200；不要用 SQLite 代替 MySQL 事务、锁和约束验收；不要删除失败测试或降低业务约束来通过检查。提交前运行仓库已配置的格式、静态检查、单元测试、集成测试和契约测试，并明确未执行项。

## 文档同步规则

| 变更 | 必须同步 |
|---|---|
| 产品范围、层级或流程 | PRD、后端方案、测试 |
| API 路径、字段、枚举、错误码 | OpenAPI、Schema、调用方、契约测试 |
| 表、字段、索引或约束 | Alembic Migration、模型、数据文档、MySQL 集成测试 |
| 状态机、发布或回滚 | Service、快照/审计逻辑、测试 |
| 鉴权、Secret、限流或审计 | 配置、部署说明、安全测试 |
| 导入格式或数据校验 | 模板、脚本、错误报告和回归数据 |

## 禁止行为

- 以题目样例或单个调用方为依据增加业务硬编码；
- 把教材路径、名称或 `knowledgeCode` 当作长期知识对象 ID；
- 把五级原子知识点直接塞进四级目录表，或建立跨层级父子关系；
- 让开放接口读取草稿，或修改已发布快照；
- 通过修改旧版本实现回滚，或删除中间版本和审计记录；
- 让未确认的导入部分写入数据库；
- 让 worker、脚本和 API 各自实现一套发布/校验逻辑；
- 恢复 Celery、Redis、消息队列、搜索引擎或微服务拆分，除非新的技术方案明确批准；
- 在事务或行锁期间调用外部服务；
- 把模型、前端校验或缓存状态当作业务事实来源；
- 记录 Secret、完整签名、敏感请求参数或未授权教材内容；
- 修改公共契约、数据库或状态机而不更新文档、迁移和测试。

## 开发流程

1. 先阅读本文件及与任务相关的 PRD、后端方案章节；
2. 明确任务属于哪个模块，并确认没有扩大 V1 范围；
3. 追踪完整调用链和所有调用方，优先复用已有模块能力；
4. 在正确的 Service/Repository/事务边界修改根因，保持最小 diff；
5. 对状态、事务、鉴权、导入和发布逻辑补最小可运行测试；
6. 同步 OpenAPI、Migration、文档和契约测试；
7. 执行与风险相称的质量检查，交付时说明未执行项和兼容影响。

最短可行实现优先：不为单一实现添加抽象，不为未来场景预留空模块，不重复建设已有能力。
