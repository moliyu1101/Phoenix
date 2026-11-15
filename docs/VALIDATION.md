# Phoenix 0.1.0 验证

2026-11-15。Phoenix 首个源码发布版本（0.1.0）：原生证据优先 CTF 智能体运行时，FastAPI + SQLite/WAL 蜂群后端，简体中文 Next.js 指挥台前端。构建与测试在目标虚拟机（192.168.10.20，Ubuntu 24.04，Python 3.12.3，Node 22.19.0）上完成。验证在独立目录进行，未切换线上 current 符号链接、未重启服务，线上运行保持不变。

## 后端

- 独立 venv 内安装 `-e .[dev]` 成功，全量测试 **202 项通过**（含 test_swarm、test_competition、test_extensions、test_writeup、test_providers_tools、test_runtime_evolution、test_fusion 等）。
- 原生蜂群运行时：运行/任务/证据/模型用量账本事件溯源；编队角色/类别准入、按 Worker 模型配置、按运行共享预算；知识与记忆蒸馏选取不可变证据片段并核对完整哈希；策略进化经留出配对评估、门禁晋级与回滚。
- 模型配置热更新（Chat Completions 兼容协议 / Anthropic Messages），密钥留后端、不回显浏览器；原生 MCP 服务器与插件注册（stdio / streamable-http / sse）桥接工具总线、记录证据、扫描 flag；比赛批量调度（队列注册/同步、准入策略、并发控制、手动准入/跳过/重排、门禁自动提交）。
- 错误映射 NotFound→404、Conflict→409、ValueError→422、PhoenixError→400。

## 前端

- 全量 TypeScript 类型检查通过（`tsc --noEmit`）；生产构建通过（`next build`）。
- 全部路由编译成功：`/`、`/ctf`、`/ctf/workers`、`/swarm`、`/knowledge`、`/memory`、`/evolution`、`/competition`、`/competition/scheduler`、`/settings`、`/settings/appearance`、`/settings/extensions`、`/settings/integrations`、`/settings/shortcuts`、`/run/[id]`、`/run/[id]/collaboration`。
- 版本号统一 0.1.0：pyproject.toml、phoenix/__init__.py、frontend/package.json、页脚 PHOENIX · 0.1.0。
- 本轮验证类型为类型检查与生产构建及路由编译；实时浏览器交互验收未在本轮重复执行。

## 原生纯净审计

- `scripts/audit_native.py` 报告 application=Phoenix，外部导入 141 项，导入中无任何遗留上游名。子进程站点报告供人工核查（引擎/容器驱动固有），属源码 inspection，非动态沙箱或安全认证。

## 身份与边界

- 源码自包含，无上游项目名或身份痕迹。题面、模型输出、工具原始证据、模型名、命令、路径与接口标识原样保留，底层参数值不翻译。
- 密钥不回显前端、不写入记忆；授权为 implicit，无"已授权"勾选；不暴力破解平台 flag。
- 源码分发不含依赖、编译后 UI、模型凭据、用户数据与构建镜像。源码包以 SOURCE_MANIFEST.json / SOURCE_SHA256SUMS.txt 校验，由 scripts/package_source.py 重生成。

本轮验证使用脚本化模型 fixture，不调用付费模型，不表示真实比赛账号验收或模型解题能力评测，也不构成 CTF 排名。