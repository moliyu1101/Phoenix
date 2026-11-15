# Phoenix

Phoenix 是原生、证据优先的 CTF 智能体运行时。后端为 FastAPI + SQLite/WAL，调度异构蜂群协作；前端为简体中文 Next.js 指挥台，提供对话、运行时时间线与协作图工作区。

另见 [English](README.md)、[验证](docs/VALIDATION.md) 与 [许可与边界](NOTICE.md)。

## 能力

- 运行、任务、证据与模型用量账本均以 SQLite/WAL 事件溯源持久化。
- 编队支持角色/类别准入、按 Worker 模型配置与按运行共享预算。
- 知识与记忆蒸馏选取不可变证据片段，按编号回填原文并核对完整哈希。
- 策略进化通过留出配对评估、门禁晋级与回滚实现；已开始的运行使用冻结快照。
- 模型配置热更新，支持 Chat Completions 兼容协议与 Anthropic Messages；密钥留在后端，不回显浏览器。
- 原生 MCP 服务器与插件注册（stdio / streamable-http / sse），桥接工具总线并记录证据、扫描 flag。
- 比赛批量调度：平台队列注册/同步、准入策略、并发控制、手动准入/跳过/重排与门禁自动提交。
- CTFd/GZCTF/rCTF 适配器；按运行离线沙箱：真实终端接管、范围化 Chromium、流量录制/重放/拦截与资产覆盖。

## 安装与使用

准备 Linux / WSL、Python 3.11+、Node.js 20+ 和 Docker：

```bash
bash scripts/bootstrap.sh
bash scripts/build-tools.sh
# 在模型设置页与 .env 填写真实服务和工作台令牌，然后：
bash scripts/start.sh --dev
```

开发执行 `bash scripts/start.sh --dev`；生产先 `bash scripts/build-ui.sh` 再 `bash scripts/start.sh`。浏览器端口 3001，后端 18750。工作台令牌仅存当前浏览器会话、经请求头传递、不放入 URL；模型密钥留在服务端。

题面、模型输出、原始证据、模型名、命令与接口标识保留原样。新建题目与平台导入无需授权勾选，使用项目即按已有授权处理。源码分发不含依赖、编译后 UI、模型凭据、用户数据与构建镜像。集成与留出结果不构成 CTF 排名。来源、许可与验收范围见 `NOTICE.md` 与 `docs/VALIDATION.md`。