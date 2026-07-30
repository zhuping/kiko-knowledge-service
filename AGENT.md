# AGENT.md

## 项目简介

本项目是独立的课程知识底座后端服务，用于管理版本化教材知识包，并向当前产品及未来业务产品提供可追溯的题目归属判断能力。

服务采用文档驱动开发。产品范围、领域边界、接口契约、数据模型和发布规则必须以本仓库的产品 PRD 与后端技术方案为依据，不能根据单个题目或单个调用方临时增加硬编码规则。

首期目标架构是：

```text
模块化单体 FastAPI
  + 独立 MySQL
  + Celery / Redis
  + 独立管理 API 与客户端 API
```

## 快速导航

| 你想做什么 | 去哪里看 |
|---|---|
| 了解产品定位、术语和业务流程 | `docs/product/01-课程知识底座产品PRD.md` |
| 了解后端架构、数据模型和实施计划 | `docs/backend/01-课程知识底座后端技术方案.md` |
| 了解当前产品后端接入约束 | 后端技术方案第 14～16 章 |
| 了解管理 API 和 Client API | 后端技术方案第 12～13 章 |
| 了解测试和质量门禁 | 后端技术方案第 18～19 章 |
| 了解部署、配置和安全要求 | 后端技术方案第 20～24 章 |
| 修改知识底座中后台 | 进入同级仓库 `../kiko-knowledge-admin/` 并先读其 `AGENT.md` |
| 修改当前产品接入 | 进入同级仓库 `../kiko-backend/` 并先读其 `AGENT.md` |

## 产品与服务边界

知识服务负责：

- 教材知识包、课程目录和教学目标；
- 教学目标关系、稳定 ID 和外部 ID 映射；
- 原型题、边界题、反例、标准答案和标准解法；
- 草稿、审核、发布、弃用和回滚；
- 题目候选召回、受约束模型比较和程序校验；
- 课程范围状态计算；
- 判断反馈和教研审核；
- 黄金测试集、发布门禁和审计；
- Client App、API Key 和知识包访问权限。

知识服务不负责：

- 用户、孩子和学生档案；
- 完整 OCR 和题目确认流程；
- 学生掌握度和推荐策略；
- 生成权限；
- 错题、变式题生成和 PDF；
- 当前产品页面或小程序流程；
- 通用题库、组卷或计费平台。

当前产品只能通过 HTTP API 调用知识服务。两个系统不得共享数据库、ORM Model、跨库外键或分布式事务。

## 目标目录结构

工程初始化后，代码按以下职责组织：

```text
kiko-knowledge-service/
├── app/
│   ├── main.py
│   ├── celery_app.py
│   ├── api/
│   │   ├── http.py
│   │   └── v1/
│   ├── core/
│   ├── domains/
│   │   ├── catalog/
│   │   ├── releases/
│   │   ├── classification/
│   │   ├── feedback/
│   │   ├── access/
│   │   ├── audit/
│   │   └── gold_regression/
│   ├── models/
│   ├── providers/
│   ├── repositories/
│   ├── schemas/
│   └── workers/
├── migrations/
├── scripts/
├── tests/
│   ├── unit/
│   ├── api/
│   ├── integration/
│   └── fixtures/
├── docs/
├── pyproject.toml
├── alembic.ini
└── Dockerfile
```

该目录是职责指引，不要求为了匹配树形结构创建没有代码的空目录。

## 开始工作前

1. 阅读与任务相关的 PRD 和后端技术方案章节；
2. 检查仓库实际结构和工作区状态；
3. 搜索现有实现、调用方、测试、迁移和文档；
4. 从 API 到 Service、Repository、Provider 或 Worker 追踪完整调用链；
5. 确认修改是否影响管理中后台或当前产品 Provider；
6. 选择能够解决根因的最小改动；
7. 实现后执行与风险相称的测试和质量检查。

不要只修改用户报告的表面路径。共享逻辑的问题应在所有调用方共同经过的正确边界修复。

## 最小修改原则

优先修改已有实现。

不要：

- 重写整个模块；
- 创建第二套相同逻辑；
- 为一个实现创建接口、工厂或 DI 容器；
- 创建通用 BaseService 或通用 Repository；
- 将一行转发包装成类；
- 为首期引入微服务、Kafka、图数据库、向量数据库或工作流引擎；
- 因单个数学题添加学科专属硬编码；
- 在真实性能指标出现前替换既定技术方案。

重复代码已经在两个以上真实场景出现时再提取公共能力。

## Python 分层边界

依赖方向固定为：

```text
app/main.py
  -> app/api/v1/
    -> app/domains/*/service.py
      -> app/repositories/、app/providers/、app/models/
```

必须遵守：

- `app/main.py` 只负责应用创建、生命周期、中间件和 Router 注册；
- FastAPI Route Handler 只处理 HTTP 参数、依赖注入、调用 Service 和响应包装；
- 业务规则、权限复核、状态迁移和事务提交放在领域 Service；
- Repository 只负责查询、持久化和数据库锁，不提交事务；
- Provider 只封装模型、对象存储和其他外部服务；
- Worker 只接收稳定任务 ID，并调用 Runtime 或 Service；
- Pydantic Schema 负责信任边界上的输入输出校验；
- Service 不得导入 `app.main` 或 API Router；
- Router 之间不得互相导入；
- Worker、API 和脚本不得各自实现一套判断或发布逻辑。

外部模型、OSS 和 HTTP 调用不得在数据库事务或行锁期间执行。

## 领域边界

| 领域 | 职责 |
|---|---|
| Catalog | 知识包、目录、目标、关系、样题、外部映射 |
| Releases | 草稿克隆、完整性校验、审核、发布、回滚、弃用 |
| Classification | 任务、候选召回、模型比较、范围计算、结果 |
| Feedback | 调用方反馈、教研审核、知识缺口和候选动作 |
| Access | 管理身份、RBAC、Client App、API Key、包权限 |
| Audit | 关键编辑、审核、发布和密钥操作审计 |
| Gold Regression | 黄金用例、指标计算和发布门禁 |

新增职责前先判断应归属哪个现有领域。不要以“方便调用”为由跨领域直接操作对方的数据表。

## 业务不变量

以下规则不能被前端校验、临时脚本或模型输出替代：

- MySQL 是知识内容、发布版本和判断任务状态的唯一事实来源；
- Redis 和 Celery Result Backend 不是业务状态事实来源；
- Published 版本不可 UPDATE 或 DELETE；
- 回滚只切换当前发布版本，不修改或删除历史版本；
- `logical_id` 跨版本稳定且永不复用；
- 拆分、合并、替代和弃用必须保留关系与历史；
- 每次判断冻结知识包、判断器、Prompt 和任务特征版本；
- 模型只能从候选 ID 中选择，不能创建教学目标；
- `scope_status` 由程序计算，不由模型自由判断；
- `unmatched` 不等于 `later_scope`；
- Counterexample 不能作为正向证据；
- Evidence 必须经过调用方权限和教材授权过滤；
- 低置信度结果不得自动确认为正式知识点；
- 未审核反馈不得参与线上检索；
- 接受反馈仍需经过知识包发布流程才能影响线上判断；
- 当前产品最终的生成权限仍由当前产品后端决定。

修改这些规则必须先更新设计文档、测试和相关状态说明。

## API 规则

统一规范：

- API 前缀为 `/api/v1`；
- 管理 API 位于 `/api/v1/admin`；
- JSON 字段使用 `snake_case`；
- 成功响应包含 `data` 和 `request_id`；
- 错误响应包含 `error.code`、`error.message`、`error.details` 和 `request_id`；
- 响应头包含 `X-Request-ID`；
- 时间使用 ISO 8601 UTC；
- 对外任务状态来自数据库；
- 创建任务、反馈、导入和发布等写操作必须支持幂等；
- 错误码是公共契约，不得用不稳定文案代替。

修改 API 时同步检查：

- Route；
- Request/Response Schema；
- Domain Service；
- OpenAPI 构建产物；
- API 和契约测试；
- `kiko-knowledge-admin` 的管理端调用；
- `kiko-backend` 的 `KnowledgeServiceProvider`；
- 版本兼容和发布顺序；
- 对应文档。

跨仓库改动必须在各自仓库独立提交，不把其他仓库代码复制到本仓库。

## 数据库与迁移

修改数据库时同步更新：

- Alembic Migration；
- SQLAlchemy Model；
- Repository；
- Pydantic Schema；
- 索引和约束；
- MySQL 集成测试；
- 数据模型文档；
- 必要的导入、导出和回滚方案。

必须遵守：

- 生产数据库是独立 MySQL 8.0+；
- SQLite 只用于快速单元测试，不作为 MySQL 行为验收依据；
- 不创建跨服务外键；
- Repository 不提交事务；
- 关键状态变化和审计在同一事务完成；
- 破坏性字段删除至少跨两个应用版本；
- 不使用手工改库代替 Migration；
- 不为没有查询依据的字段提前创建索引。

涉及索引和查询性能时，用真实 SQL 和 `EXPLAIN` 验证。

## 状态机与并发

知识包版本状态：

```text
draft -> in_review -> published -> deprecated
  ^          |
  |          v
  +------ rejected
```

判断任务状态：

```text
received -> processing -> completed
                      \-> needs_review
                      \-> failed
```

状态迁移必须：

- 由对应领域 Service 执行；
- 校验当前状态和操作者权限；
- 在事务内更新相关记录；
- 写必要的审计日志；
- 有单元测试和 API 测试；
- 不允许 Route、Repository、Worker 或脚本直接绕过；
- 不通过删除历史数据“回到上一状态”。

Draft 编辑使用整数 `lock_version` 乐观锁，冲突返回 `409`，不得静默覆盖。

## 异步任务与幂等

- `classification_task` 的数据库状态是唯一事实；
- Celery 消息只传稳定 `task_id`；
- Worker 开始工作前锁定并抢占任务；
- 模型调用期间不持有数据库锁；
- Worker 重复执行必须安全；
- 消息投递失败后由维护任务扫描恢复；
- 不依赖 Celery Result Backend 恢复任务；
- 不在 HTTP 请求或 Worker 中使用阻塞 `sleep` 等待状态；
- 重试必须有次数上限、超时和可观测错误；
- Provider 失败不得伪造高置信度结果。

关键幂等键：

- 创建判断：`client_app_id + client_request_id`；
- 判断结果：`task_id`；
- 反馈：调用方 `feedback_request_id`；
- 发布：`package_id + version`；
- 导入：`package_version_id + source_hash`。

## 鉴权与安全

Client API：

- 使用高熵 API Key；
- 只保存 Secret 的 HMAC/SHA-256 摘要；
- 使用 constant-time compare；
- 校验调用方状态、有效期、知识包权限和限流；
- 日志只记录 `key_id`，绝不记录完整 Secret。

管理 API：

- 使用公司 SSO 或可信身份代理；
- 管理身份 Header 只能由代理注入；
- Service 层必须再次执行 RBAC；
- 非 development 环境必须关闭本地测试身份；
- 不能只依赖中后台隐藏按钮。

媒体与模型：

- 媒体 URL 默认只允许 HTTPS 和 Client App allowlist；
- 禁止重定向、内网、localhost 和云元数据地址；
- 设置连接超时、读取超时、大小和 MIME 限制；
- 教材媒体使用私有 OSS 和最小授权；
- 不向模型发送 API Secret、管理员信息或未授权教材原文；
- 不记录完整模型响应、教材受限全文或个人敏感信息；
- 所有 Secret 通过环境或 Secret Manager 注入，不进入代码和默认配置。

环境变量统一使用 `KIKO_KNOWLEDGE_` 前缀。

## 代码质量硬性要求

所有新增或修改的 Python 代码必须：

- 通过 `ruff check .`；
- 通过 `ruff format --check .`，格式化时使用 `ruff format .`；
- 通过 pytest；
- 通过 pre-commit 提交钩子；
- 总测试覆盖率不低于 80%；
- 每个 Python 文件最多 500 行，包括空行和注释；
- 对安全、状态机、事务、幂等和解析逻辑留下可运行测试。

代码工程建立后，交付前至少执行：

```bash
ruff check .
ruff format --check .
pytest
find app migrations scripts tests -name '*.py' -print0 | xargs -0 wc -l
```

如果命令或目录尚未建立，不得伪造执行结果；先完成与当前阶段相符的静态检查，并在交付说明中明确未执行项。

发现文件超过 500 行时，按实际职责边界拆分。不得通过压缩代码、合并语句、删除必要注释或排除文件规避限制。

## 测试要求

测试优先覆盖：

- 知识包和判断状态机；
- Published 不可变；
- 目录和前置关系防环；
- 版本克隆、发布和回滚事务；
- `logical_id` 稳定性；
- 任务规范化、召回评分和模型输出校验；
- 范围状态和置信度门槛；
- 幂等创建、Worker 重复执行和超时恢复；
- API Key、RBAC 和授权过滤；
- SSRF、媒体 URL 和教材版权边界；
- OpenAPI 契约；
- 当前产品 Provider 契约；
- 第二套结构不同教材包的通用性。

数据库事务、锁、唯一约束和 MySQL 专属行为必须使用 MySQL 集成测试验证。

不要：

- 删除或跳过失败测试来完成任务；
- 只断言 HTTP 200 而不验证业务结果；
- 用 SQLite 通过代替 MySQL 集成验收；
- 为覆盖率编写没有行为价值的测试；
- 为了通过测试降低业务约束。

## 跨仓库协作

| 仓库 | 与本服务的关系 |
|---|---|
| `kiko-knowledge-admin` | 通过管理 API 建设、审核和发布知识包 |
| `kiko-backend` | 通过 Client API 提交判断、轮询结果和反馈 |
| `kiko-weapp` | 只访问当前产品后端，不直接访问知识服务 |

修改公共契约前先搜索真实调用方。

- 管理 API 变化要评估 `kiko-knowledge-admin`；
- Client API 变化要评估 `kiko-backend`；
- 不要求小程序保存知识服务 API Key；
- 知识服务故障不能阻断当前产品保存题目；
- 跨服务一致性使用幂等键、结果快照、重试查询和最终一致性；
- 不引入分布式事务。

## 文档同步

修改以下内容时必须同步文档：

| 修改内容 | 至少同步 |
|---|---|
| 产品范围或业务流程 | 产品 PRD、后端方案、测试 |
| API 字段、枚举或错误码 | OpenAPI、调用方、契约测试 |
| 数据模型或索引 | Migration、模型章节、集成测试 |
| 状态机 | 状态说明、Service、调用方、测试 |
| 判断规则或门槛 | 判断架构、classifier 版本、黄金集 |
| 发布门禁 | 发布流程、回归指标、审核页面契约 |
| 配置或 Secret | 配置表、部署说明、环境示例 |

文档和代码冲突时不要自行选择对自己最方便的一方。先查清最新决策，再让两者恢复一致。

## Forbidden Behaviors

禁止：

- 不阅读产品 PRD 和后端方案直接开发；
- 擅自扩大首期范围；
- 为单个题目增加一次性判断补丁；
- 将教材样题退化为简单关键词标签；
- 让模型创建目标 ID 或自由判断课程范围；
- 将未匹配直接判定为超范围；
- 修改 Published 内容或删除历史判断；
- 让未审核反馈直接进入线上知识库；
- 绕过状态机、Service、Repository 或统一 API；
- 在数据库事务中调用模型、OSS 或远端 HTTP；
- 使用 Celery 状态代替数据库业务状态；
- 修改 API 不同步 OpenAPI、调用方和测试；
- 修改数据库不更新 Migration；
- 引入未经设计的新技术栈；
- 重复实现已有能力；
- 提交临时调试代码、Secret 或敏感数据；
- 使用不安全的媒体 URL 抓取；
- 删除失败测试或降低业务约束；
- 提交未通过 Ruff、pytest 或格式化校验的代码；
- 创建或保留超过 500 行的 Python 文件。

## Guiding Principles

始终遵循：

1. 文档优先于代码；
2. 教材证据优先于表面特征；
3. 稳定 ID 和版本可追溯优先于短期便利；
4. 确定性校验优先于模型自由输出；
5. 数据库业务状态优先于任务框架状态；
6. 权限和版权边界不能由前端代替；
7. 复用优先于重写；
8. 最小修改优先于大规模重构；
9. 测试和黄金集是判断与发布的质量门禁；
10. 新教材接入应通过数据配置完成，而不是修改核心代码。

## 交付检查

提交结果前确认：

- 修改位于正确仓库和正确领域；
- 产品与服务边界未被扩大；
- 没有创建重复实现或不必要抽象；
- API、Schema、OpenAPI、调用方和测试保持一致；
- Migration、Model、Repository 和文档保持一致；
- 状态迁移、事务、幂等和审计完整；
- 权限、Secret、SSRF 和版权边界未退化；
- 相关测试和质量命令已执行；
- 未执行的检查已明确说明；
- 工作区中用户原有改动未被覆盖。
