# AGENTS.md — AI 代理工作指引

> 本文件是给 AI 代理（编码助手、自动化工具）看的开发入口；给人看的上手指南见 [README.md](README.md)。

## 项目一句话

"今天吃什么"（YeahWhat2Eat）：千人千面菜谱推荐 RAG Agent。FastAPI 后端 + Vue3 前端，LangChain/LangGraph 编排，DeepSeek 生成，Neo4j 图谱 + Qdrant 向量 + SQLite 业务真源。

## ⚠️ 首要规则

**动手改任何代码前，必须先读 [`doc/design/design.md`](doc/design/design.md)**，且改动必须与设计一致；设计有遗漏或冲突时，先更新设计文档再改代码，并同步本文件（如涉及技术栈/约束）。

## 设计文档章节索引（快速定位）

| 要做什么 | 看哪章 |
|---|---|
| 理解数据源（357 菜/18 tips 结构） | §2 数据源分析 |
| 数据建模（Neo4j 图模型 / Qdrant 集合 / SQLite 表） | §4（含 §4.4 分片容量策略） |
| ETL 管道（md 解析 → 方案B打标（规则优先+LLM补难例）→ 三库写入） | §5 |
| LangGraph 图（节点/状态/条件边） | §6（§6.1 分层 State、§6.2 Mermaid 图、§6.4 查询扩写、§6.5 召回融合算法） |
| 技术选型 / 依赖 / 模型 | §7（§7.1 后端、§7.2 前端、§7.3 LLM 参数） |
| 千人千面（画像/行为/打分） | §8 |
| API / SSE 协议 / JWT / 缓存 | §9（§9.1 流式协议、§9.2 认证、§9.3 缓存、§9.4 购物清单导出、§9.5 响应规范） |
| 前端（页面 / 5 套主题 / 布局规则） | §10（§10.1 多主题、布局 76%/全宽规则、Claude/ChatGPT 风聊天页、§10.2 多 Provider/BYOK/用量预算、会话分组与会话管理） |
| 后端分层与目录结构 | §11（含依赖铁律） |
| 部署 / Docker / Conda / .env | §12（§12.0 存储可替换、§12.1 Lite/企业级两种模式 + 数据隔离备份 + 镜像打包分发） |
| 评测与测试 | §13 |
| 里程碑 / 风险 / 已确认决策 | §14 / §15 / §16 |

## 技术栈速览（版本锁定）

- 后端依赖：**`backend/requirements.txt` 全部精确版本 `==`**，`requirements.lock` 随代码提交；升级 = 显式改版本 + 重跑测试与评测
- Python 3.12（conda 环境名 `yeahwhat2eat`）；前端 TypeScript + create-vue 默认结构，node 由 fnm 管理（v22.23.2），只用 npm（pnpm/yarn 公用禁止），镜像走 frontend/.npmrc
- 模型：LLM=`deepseek-v4-flash`；Embedding=`BAAI/bge-small-zh-v1.5`（512 维）；Reranker=`BAAI/bge-reranker-v2-m3`；本地 sentence-transformers，`device=auto`（有 CUDA 用 CUDA）
- 存储：**可替换（§12.0 / 决策 18）**——关系型 SQLite 默认（`DATABASE_URL` 可换 PostgreSQL，psycopg2-binary）；向量 `VectorStoreClient`（`VECTOR_STORE_PROVIDER`: qdrant 默认 | milvus）；图 `GraphStoreClient`（`GRAPH_STORE_PROVIDER`: neo4j 默认 | **kuzu**——Kùzu 原生 Python API、嵌入式零部署、Cypher 兼容，推荐单机）；工厂在 `core/clients/factory.py`，**新库接入 = 继承 base.py 接口 + 注册 provider**，业务层一律经 factory 获取（禁止直接 `QdrantClient(settings)`/`Neo4jClient(settings)` 实例化）；**勿加 langchain-community / langchain-kuzu**（分别依赖 langchain-classic 旧线与 langchain.chains 旧 API，均与 langchain 1.x 不兼容）；向量库 langchain 集成（langchain-qdrant/milvus）为扩展位（文本级 API 与原始点操作有阻抗，默认保留原生客户端）
- 端口：后端 8000（`BACKEND_PORT`）、前端 8080（`FRONTEND_PORT`）、neo4j 7474/7687、qdrant 6333/6334、Vite dev 5173
- 前端展示名：默认 **"是啊吃什么"**，由 `VITE_APP_NAME` 控制（开发读 `frontend/.env`，生产经 Dockerfile ARG 注入；§10 / §12.3 / §12.4）
- 前端主题：**5 套主流主题**（Solarized 浅/深、GitHub 浅/深、Nord），`tokens.css` 每主题覆盖 Element Plus 变量，暗色挂 `html.dark`（§10.1）
- 聊天模型/强度：前端可选 `model` 与 `strength`（fast/balanced/deep，映射生成温度与 max_tokens，§9.1）；**多 Provider（§10.2）**：model 格式 `接入名::模型`（默认 `deepseek::deepseek-v4-flash` / `deepseek::deepseek-chat`），自定义接入（OpenAI 兼容 / Anthropic）经 `PUT /users/me/ai-providers` 配置，Key 加密存后端、永不回显（`has_key` 脱敏）；BYOK DeepSeek Key 经 `PUT /users/me/ai-key`；每日用量上限 `dailyTokenLimit`（0=不限制）聊天页发送前检查
- **检索场景分流（§6.5 召回④ / 决策 16）**：**意图 agent（intent_router）一次 LLM 调用输出 `intent + confidence + personalize`**——`personalize=true`（开放式推荐）千人千面硬过滤生效；`false`（点名具体菜/做法/技巧/闲聊）全量检索不拦截；LLM 失败时规则兜底（点名 dish_meta 全量菜名→false，recommend/plan_menu→true）；`rule_filter` 只消费标志不自行判定；**点名菜聚焦引用**：intent_router 产出 `query.named_dishes`（规则菜名检测，`app/rag/utils.py` 共享工具），`dish_qa` 时 generate 只引用点名菜（截断 800，不混入其他菜），聚焦为空回退全部；**指代解析**（query_rewriter）："这三个菜/它们/上面"从最近助手消息提取菜名（`_resolve_refs`），拼入 rewritten + 回写 named_dishes，解决多轮追问检索失败
- **会话分组（§16 决策 17）**：`chat_sessions.group`（NULL=默认分组，派生字段无独立表）；PATCH 会话支持 `group`（`model_fields_set` 区分未传/显式 null）；**拖拽移动**（原生 HTML5 DnD，会话拖到分组头，归档会话拖入=取消归档并归组）+ **分组头"+"新建该组会话**（`/chat/stream` body 带 `group`，后端仅新建会话生效）；个人中心历史会话按组展示；`GET /dishes/names` 全量菜名映射供回答正文菜名链接化；**标题策略**：提问即命名（消息前 20 字）→ AI 仅首轮精炼总结一次（≤12 字）→ `title_auto=0` 锁定，后续用户手动改名
- **首页规则推荐（§10，无 LLM）**：`POST /api/v1/recommend` 毫秒级——`services/recommend_service.py` 复用 `rag/rule_engine.py`（硬过滤 + 荤素规划，与 rag 节点单一实现共享）；千人千面打分 `personal_score`（画像/行为动态配置）+ 请求口味/时长匹配；`diversity=true` 换一批（候选池随机交换）；sources 字段为 `name`；**改规则引擎须同步 rule_filter/planner 节点与推荐服务**
- **多轮记忆（§6.2 第 7 条，已实现）**：最近 10 轮全文 + 更早轮次滚动摘要——消息数 >20 条后后台任务把窗口外最旧消息压缩进 `chat_sessions.summary`（LLM 200 字内，失败静默），`ContextState.summary` 注入 generate/query_analyzer（早期约束继承）；消息行不删（历史展示完整）
- **软删除单轮问答（§9）**：`chat_messages.hidden`（迁移 0010）——`PATCH /chat/messages/{id}` `{hidden}` 成对隐藏 user+assistant；聊天加载与 AI 上下文均排除 hidden，数据行保留（导出含全部）；done 帧带 `message_ids` 供前端删除入口
- **rerank→generate 数据契约**：`rerank` 节点输出**扁平结构**（`text`/`name`/`dish_id` 在顶层，无 `payload` 字段）；`generate._build_context_and_sources` 兼容扁平与历史 payload 两种结构（勿只读 `payload.text`，否则 context 恒空、回答恒"检索为空"）；**rerank 合并 text 选取：`dishes` 集合完整摘要优先于 `chunks` 步骤片段**（`source=="dishes"` 无条件覆盖），difficulty 仅非 None 时赋值——否则具体问答会引用步骤片段而非完整做法
- **引用通用性（§9.1）**：sources 参考菜谱适用于所有检索类意图——问答（dish_qa/tips_qa）= 检索命中（dish_qa 聚焦点名菜）；推荐（recommend/plan_menu）= 今日菜单中的菜（source="plan"）；plan 为空 = 检索候选兜底；仅 chitchat 无引用（无检索）
- **前端渲染要点（§10）**：正文菜名全量链接化（`/dishes/names` 模块级缓存）+ **`[n]` 引用替换为菜名链接**（`MdRender.sourceMap`，引用前已出现菜名则保留角标——勿用纯 endsWith 判断，markdown 加粗会失效导致菜名重复）；参考菜谱 `SourceCard` 竖排列表（编号+菜名+箭头）；助手消息纵向排列（正文->菜单->参考菜谱，`.msg` 必须 `flex-direction: column`）；过程状态指示条消费 `status` 帧；软删除单轮问答 hover 按钮
- **菜谱浏览与收藏（§10/§8.2）**：详情接口 `/dishes/{id}` 返回 `is_favorite`（可选鉴权，未登录 false）供前端**初始化收藏状态**；收藏/取消信号由后端内置——`add_favorite` 写 `like`、`remove_favorite` 写 `dislike`（§8.2 对称），**前端禁止重复上报 feedback**；详情页加载成功后上报 `view`（fire-and-forget，热门榜/画像聚合用）；**详情页加载规则**：进入/切换菜谱即清空旧数据（不残留旧内容）、详情先行渲染、**相关菜后台加载不阻塞主内容**、竞态保护（过期响应丢弃）
- **软删除单轮问答（§9）**：`chat_messages.hidden`（迁移 0010）——`PATCH /chat/messages/{id}` `{hidden}` 成对隐藏 user+assistant；聊天加载与 AI 上下文均排除 hidden，数据行保留（导出含全部）；done 帧带 `message_ids` 供前端删除入口

## 常用命令

```bash
# 后端（conda）
conda activate yeahwhat2eat
cd backend && pip install -r requirements.txt
cp .env.example .env && uvicorn app.main:app --reload --port 8000

# 中间件
docker compose -f doc/docker/neo4j/docker-compose.yml up -d
docker compose -f doc/docker/qdrant/docker-compose.yml up -d

# ETL（数据装载，幂等可重跑）
python -m app.pipeline.runner          # 或 POST /api/v1/admin/ingest（admin）
python -m app.pipeline.runner --sqlite-only   # 秒级增量：仅补 dish_meta 的 content/image（§2.2/§12.5；--skip-tag 可再加速）
python -m app.pipeline.runner --skip-tag --no-reset   # 复用已有标签重灌图谱/向量
# 注意：_scan_dish_images 扫描 md 同目录 + 菜名同名子目录（数据源结构 dishes/类/菜名.md + dishes/类/菜名/*.jpg）；
# 数据源有图菜约 170 道（332 张文件），image 字段必须存相对路径（非 md 链接）

# 前端
cd frontend && npm install && npm run dev

# 前端环境约定（本地）
# - node 版本由 fnm 管理，固定 v22.23.2：fnm exec --using=22.23.2 npm ...
# - 只用 npm；pnpm / yarn 是本机公用环境，禁止使用
# - 镜像：frontend/.npmrc 已配 registry=https://registry.npmmirror.com（国内加速）
# - Windows 下 fnm exec 无法 spawn npm.cmd，直接调完整路径：
#   $npm = "$env:APPDATA\fnm\node-versions\v22.23.2\installation\npm.cmd"; & $npm install

# 测试 / 规范 / 分层检查
pytest                                  # 单元 + 集成（需中间件容器）
ruff check .                            # 代码规范
import-linter lint                      # 分层依赖铁律
python tests/eval/run_eval.py           # RAG 评测（golden 集）

# 诊断工具（backend/scripts/diagnostics/，面向人的验收报告，可复用）
python scripts/diagnostics/check_data.py            # 数据完整性：图片覆盖/md链接残留/标签/content/ingest日志
python scripts/diagnostics/debug_retrieve.py "宫保鸡丁怎么做"   # 检索链路：向量命中 + rerank text 合并检查
python scripts/diagnostics/build_graph.py           # 图构建冒烟 + 意图/场景判定用例

# 一键部署（§12 M6，两种模式；推荐用跨平台 Python 脚本，Windows/Linux/macOS 通用）
python doc/docker/deploy.py lite          # Lite 模式（SQLite+Kùzu+Qdrant 文件嵌入，零外部依赖）
python doc/docker/deploy.py enterprise    # 企业级模式（PG+Milvus+Neo4j 每库一容器 + 前后端）
python doc/docker/deploy.py status        # 查看运行状态
python doc/docker/deploy.py down          # 停止两种模式
# 手动方式（等价的底层命令）：
cp doc/docker/.env.example doc/docker/.env        # 填 DEEPSEEK_API_KEY 等
docker compose -f doc/docker/lite/docker-compose.yml up -d --build
# 测试联调可叠加 dev override（复用本机 backend/data 数据）：
#   docker compose -f doc/docker/lite/docker-compose.yml -f doc/docker/lite/docker-compose.dev.yml up -d --build
# 企业级：PG + Milvus + Neo4j 每库一个容器 + 前后端（三库参数均在 doc/docker/.env 自定义）
docker compose -f doc/docker/docker-compose.yml up -d --build
# 访问 http://localhost:8080（端口由 .env 的 FRONTEND_PORT 控制）

# 发布打包 / 离线部署（镜像 = Python 的"jar 包"；构建一次到处运行；脚本跨平台，仅需 Python 3.8+ 与 docker CLI）：
python doc/docker/build_release.py lite        # 构建 + docker save 导出 releases/*.tar.gz
python doc/docker/build_release.py enterprise  # 企业级前后端镜像包
# 目标服务器离线部署：scp 镜像包 -> python doc/docker/build_release.py load <包> -> python doc/docker/deploy.py <模式>
# 同服务器重复 --build：依赖层走 Docker 缓存（pip 层 CACHED），不重复下载依赖
# 备份：python doc/docker/backup.py {lite|enterprise}（卷打包/pg_dump -> backups/，7 天轮转）
```

## 硬性约束（不可违反）

1. **分层依赖**：`api → services → repositories + rag → core/clients`；禁止反向依赖与循环导入（import-linter 把关）；`schemas`（API DTO）/ `db/models`（ORM）/ `rag/state`（Agent State）三套模型互不混用
2. **单 worker**：部署必须 `uvicorn --workers 1`（本地模型只加载一份，防止内存/显存翻倍）
3. **数据源只读**：`data/HowToCook-1.6.0/` 只读，任何修正走 `overrides.json`，不直接改原始 md
4. **SQLite 是唯一业务真源**：Neo4j/Qdrant 均可由 ETL 幂等重建；表结构变更必须走 alembic 迁移
5. **Cypher 不自由生成**：图查询只用预置模板 + 参数填充（§6.5 T1~T4），禁止 LLM 直接写 Cypher
6. **密钥不进版本库**：所有配置走 `.env`（由 `.env.example` 手动复制）；生产必须改 Neo4j 默认密码
7. **流式协议**：AI 回答必须走 SSE（§9.1 事件顺序 `status → sources → tool → text → plan → done`），请求带 `message_id`（幂等）、响应带 `trace_id`
8. **版本锁定**：requirements.txt 用 `==`；前端第三方依赖仅限 §7.2 列出的（markdown-it/DOMPurify/ECharts/axios/dayjs），新增依赖需先更新设计文档
9. **评测回归**：修改 prompt / 检索参数 / 打分配比后必须重跑 `tests/eval/run_eval.py`，指标低于 §13.2 达标线不允许合入
10. **端口约定**：后端固定监听容器内 8000、前端容器内 80，对外映射由 `BACKEND_PORT` / `FRONTEND_PORT` 控制
11. **日志与注释字符规范**（防日志系统/终端字符不兼容与解析异常）：
    - 输出一律用 `logging` 五等级（DEBUG/INFO/WARNING/ERROR/CRITICAL），**禁止 `print()`**（`scripts/`、`tests/` 等面向人的验收报告除外）
    - 日志消息只用：中文、字母数字、空格、中文标点（，。：；（））、ASCII 标点（`- _ / . = | [ ]`）；`|` 作为唯一结构锚点分隔符（与 `core/logging.py` 格式一致）
    - **禁止**出现在日志/生成文本中：emoji（⚠️✅🔥）、箭头（→⇄）、装饰符号（★）、省略号（…）——用 `->`、`<->`、`OK`、`[WARN]`、`...` 替代
    - 注释/docstring 同规则；`§` 章节引用（如 §6.5）作为文档锚点保留；数据源解析所需字符（如 parser 的 ★ 星级正则）属功能必需，不替换
12. **前端强制登录**（§10 千人千面前置）：除 `login`/`register` 外全部路由需登录（游客也是登录态），未登录访问任意页面跳登录页并回跳；已登录访问登录/注册页重定向首页

## 变更规范

- 改设计（模型/接口/算法/流程）→ 先更新 `doc/design/design.md` 对应章节，再改代码
- 改 Prompt → `app/rag/prompts/` 内文件头 `version` 递增 + 重跑评测
- 加依赖 → 更新 §7 与 requirements.txt（精确版本）+ 本文件技术栈段
- 新里程碑 → 对照 §14 验收标准逐项核对（功能 + 测试 + 评测指标）
