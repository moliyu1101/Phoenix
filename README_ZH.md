# Phoenix

**原生、证据优先的 CTF 智能体运行时。** 后端以 FastAPI + SQLite/WAL 控制面调度异构模型
Worker 蜂群；前端为简体中文 Next.js 指挥台，提供对话、运行时时间线与协作图。Phoenix 本身
就是一个运行时，而不是把命令转包给其他智能体项目的中间商。

`版本 0.1.0` · `AGPL-3.0-only` · `Python 3.11+` · `Node.js 20+` · `Linux / WSL`

[English](README.md) · [架构](docs/ARCHITECTURE.md) · [蜂群契约](docs/SWARM.md) ·
[模型](docs/MODELS.md) · [安全](docs/SECURITY.md) · [验证](docs/VALIDATION.md) · [许可与边界](NOTICE.md)

---

## 目录

- [Phoenix 是什么](#phoenix-是什么)
- [设计原则](#设计原则)
- [能力](#能力)
- [架构](#架构)
- [环境要求](#环境要求)
- [快速开始](#快速开始)
- [配置](#配置)
- [命令行参考](#命令行参考)
- [Web 工作区](#web-工作区)
- [HTTP 接口](#http-接口)
- [安全与边界](#安全与边界)
- [测试与验证](#测试与验证)
- [目录结构](#目录结构)
- [文档](#文档)
- [许可](#许可)

---

## Phoenix 是什么

Phoenix 用一群模型 Worker 协作解答**已授权**的 CTF 题目：它们共享同一题目工作区、交接
**不可变证据**，并在一个可度量的晋级门禁下学习可复用的解题流程。每一次运行、任务、事件、
证据与模型调用都以事件溯源方式持久化到 SQLite/WAL 账本——这是唯一权威真相源；前端只是该
账本的投影，绝不是另一套并行状态机。

它面向**可信的单一操作者**运行已授权题目，而不是公开的多用户攻击服务。操作者可信；模型、
题目文件、目标响应与导入文本都不可信。

## 设计原则

**证据优先。** 工具的有界原始输出即*证据*：它有 ID、哈希、运行/任务来源、参数、成功标志与
截断标记。重新读取原文会复核其存储哈希。模型生成的文本**不是**原始证据；某条输出存在，也
不等于它正确、或与目标题目相关。

**四类对象，而不是一条不断膨胀的聊天记录。**

| 对象 | 是什么 | 信任级别 |
| --- | --- | --- |
| **证据 Evidence** | 有界、哈希校验的工具/沙箱/目标原始输出 | 原始记录 |
| **回合 Episodes** | 一次运行实际尝试了什么、如何终止，附证据引用 | 不自动可信 |
| **记忆 Memories** | 带适用条件、步骤、坑点与精确引用的结构化经验 | 审核前隔离为 `draft` |
| **技能 Skills** | 带停止条件的版本化条件指令 | 晋级前为候选 |

**度量式进化，而非自我改写。** 这里的"进化"指通过留出配对评估、门禁晋级与回滚来做版本化的
流程选择。不存在权重训练、LoRA、策略梯度、自我改写的运行时码，也不保证持续变强。

**密钥留在控制面。** 模型凭据在每次调用时于服务端解析，绝不进入 Worker 容器或浏览器。
Worker 快照的是凭据*环境变量名*而非密钥值，因此可以轮换密钥。

**诚实计费。** 用量按模型调用 / Worker / 任务记录，并共享按运行的预算。未知价格是*未计价*，
不是免费。缺少用量报告时按保守预留额度处理，并把该调用标记为不确定。

## 能力

### 蜂群运行时
- 运行、任务、证据与模型用量账本均以 SQLite/WAL 事件溯源持久化。
- **Worker ID / 角色 / 模型**三者分离；角色路由 `planner`、`analyst`、`solver`、`reviewer`、
  `distiller`。具名 Worker 配置可覆盖角色模型。
- 默认编队 `scout · solver-a · solver-b · reviewer`；每 Worker 一个活跃任务；运行并发 1–16，
  编队上限 32，DAG 上限 64 个任务。
- 依赖就绪的任务在 SQLite 事务中连同 Worker/尝试分配一起认领；运行时可基于已完成工作与新证据
  重新规划。
- 中断恢复保留 Worker 亲和性（旧对话绝不被悄悄改走另一个 Worker 的协议/模型）。禁用即排空；
  暂停遵循原生沙箱对账策略。

### 证据、知识与记忆
- 蒸馏选取不可变证据片段，按编号回填原文并复核完整哈希；结构与引用校验在模型**之外**完成。
- 审核后的知识按重叠分块，用 SQLite **FTS5/BM25** 索引，分词含 CJK 二元组，中文技术笔记不会被
  当成一个不可分的 token。
- 可选真实嵌入向量叠加余弦排序，与词法结果用倒数排名融合（RRF）；不兼容的向量命名空间绝不混用，
  稠密检索失败时回退到词法检索。不会把伪嵌入哈希冒充语义检索。
- 只检索运行**冻结**知识快照中已审核的文档；草稿与后续导入不会泄漏进正在进行的运行。

### 度量式策略进化
- 完整 `learn` 闭环：蒸馏 → 提出一个条件候选 → 冻结知识与模型配置 → 在留出用例上跑基线/候选 →
  评估 → 可选晋级。
- 晋级门禁：≥3 个类别匹配的不同 `heldout` 用例、基线无回退、解题数增加（或非零解题数持平且
  token 消耗改善 ≥10%）、已知价格时候选成本 ≤基线的 125%、无不确定计费调用，且必须是真实生产
  HTTP 传输（绝不能用脚本 fixture）。旧版本保留以便回滚。

### 模型供应与计费
- 两种明确传输：**Chat Completions 兼容**工具调用与 **Anthropic Messages** 工具使用。未实现流式
  生成与 OpenAI Responses API。
- 设置页可热更新模型配置、角色路由、Worker 编队与凭据；保存时不发起模型调用。覆盖项重启后生效；
  活跃运行须先结束。
- 调用前按保守 UTF-8 字节估算（消息 + 工具 schema + 输出预算），可能比厂商分词器更早拒绝调用。
  按角色配置 USD 价格驱动账本。

### 工具、沙箱与扩展
- 不可信命令**只**在按类别的一次性 Docker 容器中运行——缺少 Docker 时没有回退到宿主机执行。
  类别：`base`、`web`、`crypto`、`pwn`、`reverse`、`forensics`、`misc`。
- 容器丢弃 capability、禁用网络、限制进程/CPU/内存、挂载只读根文件系统，只暴露题目输入与任务
  工作区。模型凭据与 Docker socket 都不挂载进容器。
- 真实终端接管（PTY 留在容器内）、范围化 Chromium，以及经原生总线的流量录制 / 重放 / 拦截，
  并做精确 origin 校验。
- 原生 **MCP 服务器与智能体插件注册**（`stdio`、`streamable-http`、`sse`）桥接工具总线，记录证据
  并扫描 flag。

### 比赛调度
- **CTFd / GZCTF / rCTF** 适配器桥接到原生题目、附件、租约与回执。
- 批量调度：平台队列注册/同步、准入策略、并发控制、手动准入 / 跳过 / 重排，以及门禁自动提交。
  不确定的远程提交绝不盲目重试。
- ScopeSentry 导入资产引用，**不扩大范围**。

### 指挥台前端
- 简体中文 Next.js 15 / React 19 指挥台，在草稿、运行与管理路由间保持常驻活动栏。
- 对话、活动控制台 / 瀑布 / 账本 / 回放，以及智能体协作画布；知识、记忆、进化与设置共用同一套
  基础组件、配色与检查器。
- `phoenixTrace` 把持久化的事件/任务/模型调用映射为 trace 场景——只显示真实时序，缺失的价格/token
  保持*未知*。

## 架构

```
┌──────────────────────────────────────────────────────────────────┐
│  浏览器 · Next.js 指挥台（简体中文）· :3001                         │
│  对话 · 时间线 · 协作图 · 设置                                      │
└───────────────┬────────────────────────────────────────────────────┘
                │  鉴权同源代理（Bearer 令牌）
┌───────────────▼────────────────────────────────────────────────────┐
│  FastAPI 控制面 · :18750（默认仅回环）                              │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  SQLite/WAL 账本 — 运行 · 任务 · 事件 · 证据 · 用量            │  │
│  │  （权威、事件溯源）                                            │  │
│  └──────────────────────────────────────────────────────────────┘  │
│  蜂群 · 供应 · 知识/记忆 · 进化 · 平台                              │
│  比赛 · 扩展(MCP) · 调查 · ScopeSentry                              │
└───────┬──────────────────────────────────┬─────────────────────────┘
        │ 运行内 UNIX socket               │ Docker API（可信面）
        │ 任务级令牌                       │
┌───────▼─────────────────┐      ┌─────────▼─────────────────────────┐
│  CLI 引擎网关           │      │  按类别一次性沙箱                  │
│  模型密钥绝不入内       │      │  无网络 · 只读根文件系统           │
└─────────────────────────┘      │  PTY 在内 · 输入 + 工作区          │
                                 └────────────────────────────────────┘
```

原生账本是权威。每个运行拥有一个离线类别容器、不可变输入与可写工作区。范围化 HTTP/TCP 与浏览器
流量经原生总线；CLI 引擎网关使用运行内 UNIX 模型/工具 socket 与任务级令牌。平台适配器、沙箱、
MCP 扩展与比赛调度都是原生服务。SQLite 表是增量式的；恢复会中断打开的引擎/PTY 会话并取消待批准
项，不确定的执行需要显式对账。详见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。

## 环境要求

- **Linux 或 WSL**——运行时是 POSIX 专属的（目录描述符、no-follow 遍历、UNIX socket、进程组）。
- **Python 3.11+**
- **Node.js 20+** 与 npm（用于前端）
- **Docker** 且守护进程可达（用于完整工具能力；可信控制面必须被允许控制 Docker）

## 快速开始

```bash
# 1. 创建 .venv、安装包 + dev extras、生成 config.yaml 与 .env，并安装前端依赖。
bash scripts/bootstrap.sh            # 加 --backend-only 可跳过前端

# 2. 构建按类别的工具镜像（需要 Docker + 网络）。
bash scripts/build-tools.sh

# 3. 填写真实模型设置与工作台令牌（见下方"配置"），然后以开发模式启动 API + 前端。
bash scripts/start.sh --dev
```

- **开发：** `bash scripts/start.sh --dev`（Next.js 开发服务器）。
- **生产：** 先 `bash scripts/build-ui.sh` 再 `bash scripts/start.sh`（Next standalone）。
- **仅后端：** `bash scripts/start.sh --backend-only`。
- **零成本冒烟：** `.venv/bin/python -m phoenix swarm-demo`——脚本化模型 fixture 走真实原生工具
  操作；无需联网模型或 Docker 进程。

**端口与令牌。** UI `3001`，原生 API `18750`（默认都仅回环）。工作台令牌存于浏览器 `sessionStorage`、
经请求头传递、绝不放入 URL。把 `PHOENIX_WEB_TOKEN` 留空，`serve` 会生成随机令牌（mode `0600`，存于
`data_dir/.web-token`）并打印一次。模型凭据留在服务端。

## 配置

### config.yaml

把 `config.example.yaml` 复制为 `config.yaml`（bootstrap 会自动完成）。启动工作台**不会**发起任何
模型请求。

```yaml
data_dir: data
host: 127.0.0.1
port: 18750
token_env: PHOENIX_WEB_TOKEN
profiles:
  default:
    protocol: chat                 # chat | anthropic
    base_url: https://your-provider.example/v1
    model: ""                      # 真实运行必填；也可用 PHOENIX_MODEL
    api_key_env: PHOENIX_API_KEY    # 存放密钥的环境变量"名"，绝不写密钥本身
    context_tokens: 32768
    output_tokens: 4096
    chat_token_parameter: max_completion_tokens
    input_usd_per_million: null    # 启用 USD 上限前先填真实价格
    output_usd_per_million: null
roles: {planner: default, analyst: default, solver: default, reviewer: default, distiller: default}
sandbox_image: phoenix-tools:0.1.0
sandbox_memory: 1024m
sandbox_cpus: 1.0
max_output_bytes: 2097152
workers:
  - {id: scout,    name: Recon Analyst,        roles: [analyst]}
  - {id: solver-a, name: Solver Alpha,         roles: [solver]}
  - {id: solver-b, name: Solver Beta,          roles: [solver]}
  - {id: reviewer, name: Independent Reviewer, roles: [reviewer]}
```

另提供面向蜂群的模板 `config.swarm.example.yaml`。

### 环境变量（`.env`）

把 `.env.example` 复制为 `.env`（mode `0600`）。所有密钥都要保密，不要进入题目提示词与源码版本控制。

| 变量 | 用途 |
| --- | --- |
| `PHOENIX_MODEL` | 覆盖 `default` 配置的模型 |
| `PHOENIX_BASE_URL` | 覆盖 `default` 配置的 base URL |
| `PHOENIX_API_KEY` | 默认供应方凭据（由 `api_key_env` 引用） |
| `PHOENIX_WEB_TOKEN` | 工作台 bearer 令牌（≥24 字符）；留空 ⇒ 自动生成 |
| `PHOENIX_EMBEDDING_KEY` | 可选嵌入端点凭据 |
| `PHOENIX_DATA_DIR` | 覆盖数据目录 |

只有 `default` 配置读取 `PHOENIX_MODEL` / `PHOENIX_BASE_URL`；其他配置用各自 YAML 字段。
**绝不要把密钥值写进 YAML**——用环境变量名引用。

### 操作者覆盖与优先级

设置页把模型配置、角色路由、Worker 编队与凭据持久化为数据目录下的文件：

- `data_dir/operator-config.json`——模型/角色/编队覆盖（绝不含端口或数据路径）。
- `data_dir/model-credentials.json`——凭据，mode `0600`，**API 绝不返回**。密码字段留空即保留原密钥。

生效优先级：**YAML → 环境变量 → 操作者覆盖**（重启后应用）。活跃运行处于非终止态时，模型/编队设置
变更会被拒绝。要回到 YAML 主导的配置，停止 API、备份并删除覆盖文件，再重启。

### 模型协议与计价

端点必须实现所选协议、且模型必须支持工具——只给一个通用 base URL 不够。Chat 工具 ID/参数与受支持
的扩展（如 `reasoning_content`）会被持久化并回放；Anthropic 工具使用与签名内容块会保留以便回放。
请求不跟随重定向、不盲目重试。启用 USD 上限前，为每个要跑的角色填入真实的每百万 token 输入/输出
USD 价格；账本基于这些配置值与供应方用量报告，不是发票保证。详见 [docs/MODELS.md](docs/MODELS.md)。

## 命令行参考

`pip install -e .` 后提供 `phoenix` 控制台脚本；各脚本使用 `.venv/bin/python -m phoenix`。所有命令
都接受 `--config <path>`（默认 `config.yaml`）。

| 命令 | 作用 | 成本 |
| --- | --- | --- |
| `serve` | 启动鉴权的原生工作台（API） | — |
| `doctor` | 打印 Python/SQLite 版本、Docker CLI 是否存在与脱敏配置；不发请求 | 免费 |
| `demo` | 脚本化单运行 fixture 走真实原生工具 | 免费 |
| `swarm-demo` | 脚本化并行蜂群 + 证据交接 fixture | 免费 |
| `seed` | 安装原创基线技能与入门知识 | 免费 |
| `ingest <path> [--category C] [--trusted]` | 导入本地文本/Markdown 知识（≤2 MiB；不调用 API） | 免费 |
| `evaluate <skill_id> <suite> --confirm-model-charges` | 执行付费的留出配对基准 | **付费** |
| `learn <run_id> <suite> --confirm-model-charges [--promote]` | 蒸馏 → 提案 → 评估 → 可选晋级 | **付费** |

`evaluate` 与 `learn` 不带 `--confirm-model-charges` 会拒绝运行。脚本 fixture 明确为 `mode=demo`，
不能授权策略晋级，只是管线证据——不是 CTF 解题率基准。

## Web 工作区

指挥台（UI `:3001`）暴露以下路由：

| 区域 | 路由 |
| --- | --- |
| 指挥台 | `/` |
| 题目 | `/ctf`、`/ctf/workers` |
| 蜂群 | `/swarm` |
| 学习 | `/knowledge`、`/memory`、`/evolution` |
| 比赛 | `/competition`、`/competition/scheduler` |
| 运行详情 | `/run/[id]`、`/run/[id]/collaboration` |
| 设置 | `/settings`、`/settings/appearance`、`/settings/extensions`、`/settings/integrations`、`/settings/shortcuts` |

## HTTP 接口

所有受保护接口都需要工作台 bearer 令牌（`Authorization: Bearer <token>`）。UI 把鉴权的同源请求代理
到原生 API。代表性路由：

- **总览 / 设置：** `GET /api/overview`、`GET /api/settings`、`GET /health`
- **题目：** `GET/POST /api/challenges`、`GET /api/challenges/{cid}`、`.../files`、`.../runs`、`.../verifier`
- **运行：** `GET /api/runs/{rid}`、`.../events`、`.../stream`、`.../pause`、`.../resume`、`.../reconcile`、
  `.../distill`、`.../learn`、`.../writeup`（+ `/evidence`、`/export`）、`GET /api/runs/{rid}/evidence/{eid}`
- **蜂群：** `GET /api/swarm/catalog`、`GET /api/runs/{rid}/swarm`、`POST /api/runs/{rid}/swarm/workers`、
  `PATCH .../workers/{wid}`、`PATCH .../swarm`
- **知识 / 记忆 / 技能：** `/api/knowledge`（+ `/search`、`/{did}`、`/{did}/index`、`/{did}/review`）、
  `/api/memories`（+ `/{mid}/review`、`/{mid}/strategy`）、`/api/skills`（+ `/{sid}/evaluate`、`/{sid}/promote`、`/{sid}/rollback`）
- **评估 / 学习：** `/api/evaluations`、`/api/learning`、`/api/candidates/{cid}/receipt`

错误映射：`NotFound → 404`、`Conflict → 409`、`ValueError → 422`、`PhoenixError → 400`。API 响应为
`no-store`；单个上传限 48 MiB、聚合输入清单限 128 MiB（这是上传护栏，不是磁盘配额系统）。

## 安全与边界

只把 Phoenix 用于已授权的 CTF 题目与你有权分析的文件。部署前请阅读 [docs/SECURITY.md](docs/SECURITY.md)。

### 已实现的控制
- **默认仅绑定回环**；要求 **≥24 字符**的 bearer 令牌。
- 拒绝带外来 `Origin` 的写请求；不开启宽泛 CORS；API 响应 `no-store`；静态资源有受限 CSP；生成的
  令牌为 mode `0600`。
- **绝不把模型 API 密钥发给浏览器。**
- 文件操作用 POSIX 目录描述符与 no-follow 遍历；拒绝绝对路径、父级遍历、驱动器路径与符号链接。题目
  输入对模型工具接口只读；Worker 只能写自己的任务工作区。
- 不可信命令只在一次性 Docker 容器中运行（无宿主机回退）：丢弃 capability、禁用网络、资源限制、只读
  根文件系统，模型凭据与 Docker socket 都不挂载进内。
- 网络目标工具校验精确归一化 origin，拒绝 userinfo/编码主机花招，禁用 Host/代理覆盖头，不跟随重定向，
  并按 origin 串行化操作。模型不能选择任意未列出的目标 origin。

### 已知边界（未解决）
- origin 校验**不是**出口防火墙或 DNS/IP 绑定；目标驱动的 SSRF 是另一层范围问题。请在网络层隔离控制面。
- Docker 共享宿主机内核；资源限制不是工作区总磁盘配额。内核漏洞、容器逃逸与被攻陷的 Docker 守护进程
  都在本原型保证之外。请在一次性机器中运行敌意样本。
- 证据哈希检测的是与存储哈希的不一致，而不是同时改写两者的管理员。精确引用证明文本出现过，不证明模型
  的解读。反射式 flag 字面量拒绝是启发式；只有独立验证器或真实平台回执才确立接受（本版本不自动校验
  回执真伪）。
- 附件、Web 响应与知识中的提示注入未被形式化消除。检索文本被明确标为不可信、工具权限留在模型之外，但
  对抗性文本仍可能浪费预算或误导推理。
- 原始记录与运行导出可能含目标数据、输出与密钥；它们是私有本地记录，不是自动脱敏的公开 writeup。启发式
  记忆脱敏不是全面的密钥扫描器。
- POSIX 专属、单控制面进程、单 SQLite 存储。没有多租户隔离、自动高可用、基于队列的付费任务恢复、静态
  数据加密层或生产安全审计。单元测试不是渗透测试，也不是已验证的沙箱保证。

### 授权
授权是**隐式**的：使用项目即按其题目已授权处理。没有"我已授权"勾选框。不要在未经鉴权 TLS 代理、主机
防火墙与单独授权审查的情况下，把服务暴露到不可信网络。

## 测试与验证

```bash
# 后端单元/集成套件（脚本化模型 fixture；无付费调用）。
bash scripts/test.sh                 # == .venv/bin/python -m pytest -q

# 前端门禁。
cd frontend
npm run typecheck                    # tsc --noEmit
npm run check:phoenix                # 原生适配器 / 本地化检查
node scripts/check-trace.mjs         # trace 投影检查
npm run build                        # 生产构建（Next standalone）
node scripts/browser-check.mjs       # 真实浏览器验收套件

# 原生纯净审计（源码 inspection，不是动态沙箱或安全认证）。
.venv/bin/python scripts/audit_native.py
```

0.1.0 源码发布在隔离的目标虚拟机上验证：后端 **202 项测试通过**，前端类型检查 + 生产构建在全部 16 条
路由上通过，原生审计报告 `application=Phoenix`。验证使用脚本化模型 fixture——不代表真实比赛账号验收
或模型解题能力评测，也不构成 CTF 排名。详见 [docs/VALIDATION.md](docs/VALIDATION.md)。

## 目录结构

```
phoenix/            原生运行时：api、swarm、runtime、providers、store、evidence、
                    knowledge、memory、learning、evolution、competition、platforms、
                    extensions、investigation、scopesentry、sandbox、terminal、browser、
                    writeup、cli、vendor/engine（内置引擎实现）
frontend/           简体中文 Next.js 指挥台（app/、components/、lib/、scripts/）
integrations/       phoenix/ — 智能体、技能与按类别沙箱镜像
scripts/            bootstrap、build-tools、build-sandboxes、build-ui、start、serve、
                    test、audit_native、package_source
docs/               ARCHITECTURE、SWARM、MODELS、FRONTEND、LEARNING、SECURITY、VALIDATION
tests/              后端 pytest 套件
examples/           create_challenge.py、knowledge-note.md、payload.txt
benchmarks/         public-wiring-suite.json（管线 fixture，不是能力基准）
licenses/           AGPL-3.0.txt
config.example.yaml · config.swarm.example.yaml · .env.example
SOURCE_MANIFEST.json · SOURCE_SHA256SUMS.txt   （源码包完整性）
```

源码分发**不含**依赖、编译后 UI、模型凭据、用户数据与构建镜像。工具镜像在本地构建并需要网络。
用 `python scripts/package_source.py` 重生成完整性清单。

## 文档

| 文档 | 主题 |
| --- | --- |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 原生服务、账本权威、运行隔离 |
| [docs/SWARM.md](docs/SWARM.md) | 身份/路由、调度、恢复、蜂群 API |
| [docs/MODELS.md](docs/MODELS.md) | 协议、配置、token/金钱计费、设置 UI |
| [docs/LEARNING.md](docs/LEARNING.md) | 证据/记忆/技能、蒸馏、晋级门禁 |
| [docs/FRONTEND.md](docs/FRONTEND.md) | 指挥台视图、适配器、投影 |
| [docs/SECURITY.md](docs/SECURITY.md) | 控制、边界、部署限制 |
| [docs/VALIDATION.md](docs/VALIDATION.md) | 0.1.0 验证范围与结果 |
| [NOTICE.md](NOTICE.md) | 来源声明、许可与边界 |
| [CHANGELOG.md](CHANGELOG.md) | 发布历史 |

## 许可

Phoenix 采用 **AGPL-3.0-only** 许可。许可证文本见 [`licenses/`](licenses/) 与
[`phoenix/vendor/engine/LICENSE.txt`](phoenix/vendor/engine/LICENSE.txt)。内置第三方组件保留各自许可；
前端第三方声明随 UI 依赖分发。详见 [NOTICE.md](NOTICE.md)。