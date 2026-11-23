<p align="center">
  <img src="assets/icon.svg" width="112" alt="tokusage icon">
</p>
<h1 align="center">tokusage</h1>
<p align="center">收集本机与远端主机的 token 用量，用一个本地网页实时展示。</p>

零依赖（Python 3.11+ 标准库）：每台机器运行一条采集命令输出 JSONL → 汇总写入本地 SQLite → 内置 Web 面板读取展示。

## 功能

- 按模型 / 按日期统计，GitHub 风格热力图
- 基于官方定价的成本计算（缓存命中单独计价）
- 多主机汇总，可按主机筛选
- 「会话」页实时展示各主机正在进行中的 agent session

## 快速开始

1. **环境**：`python` ≥ 3.11，`ssh` 在 PATH（Windows 10+ 自带 OpenSSH）。无需 `pip install`。
2. **配置**：复制 `config.example.toml` 为 `config.toml`，填入本机命令与各主机 SSH 信息。
3. **运行**：

```bash
python tokusage.py                 # 启动采集 + 网页，访问 http://127.0.0.1:8080
python tokusage.py --check         # 校验配置并试采集一轮，打印各主机状态
python tokusage.py --collect-once  # 只采集一轮后退出（可配合计划任务）
python tokusage.py --deploy        # 把 collect_agents.py 推到各远端并装好依赖
```

## 记录格式（JSONL）

采集命令每行输出一个 JSON 对象，字段均可选、缺省按下表：

```jsonl
{"ts": "2026-11-20T14:30:00+08:00", "model": "gpt-4o", "prompt_tokens": 123, "completion_tokens": 456}
{"ts": "2026-11-20T14:31:05+08:00", "model": "claude-sonnet-4", "prompt_tokens": 10, "completion_tokens": 20, "cache_read_tokens": 890, "id": "req-9f2c"}
```

| 字段 | 说明 |
|---|---|
| `ts` / `timestamp` | 时间（ISO-8601 或 Unix 秒），缺省用采集时间 |
| `model` / `model_name` | 模型名，缺省 `unknown` |
| `prompt_tokens` | 输入 token（不含缓存读取 / 写入） |
| `completion_tokens` | 输出 token |
| `cache_read_tokens` / `cache_write_tokens` | 缓存命中读取 / 写入的 token |
| `total_tokens` | 总量；缺省 = 输入 + 输出 + 缓存读 + 缓存写 |
| `id` | 稳定去重键；缺省用内容哈希（对相同内容去重） |

> 建议给每条记录稳定的 `id`（如请求 ID），去重更可靠。

## 从 coding agent 采集（collect_agents.py）

仓库自带的 `collect_agents.py` 直接读取三类 coding agent 的本地记录，输出统一 JSONL；Windows / Linux 通用，目录缺失自动跳过：

| agent | 数据位置 |
|---|---|
| omp | `~/.omp/agent/sessions/**/*.jsonl` |
| codex | `~/.codex/sessions/**/rollout-*.jsonl.zst`（zstd，需 `pyzstd` / `zstandard` / 系统 `zstd` 其一） |
| claude code | `~/.claude/projects/**/*.jsonl` |

- `python collect_agents.py`：输出全部历史用量（含缓存拆分）。
- `--days N`：只输出最近 N 天；`--active`：输出进行中的会话（供「会话」页）。

**部署**：本机把 `local.command` 设为 `python collect_agents.py`；远端直接 `python tokusage.py --deploy`（自动 `scp` + 安装 `pyzstd` + 试跑）。

## 成本计算

每条记录按模型官方定价折算美元，展示在汇总卡片、按模型表、按日期列表与热力图 tooltip。

- **定价**：来自 `aihubmix.com/api/v1/models`（每 1M token 的美元价）。仓库内置 `pricing.json`；更新时运行 `python fetch_pricing.py`。
- **匹配**：去掉 provider 前缀后与模型 ID 精确匹配（`aihubmix/deepseek-v4-pro-0813` → `deepseek-v4-pro-0813`），匹配不到按 0 计。
- **公式**：`(输入×input + 输出×output + 缓存读×cache_read + 缓存写×cache_write) / 1e6`。
- **缓存口径**：缓存单价通常远低于常规输入价，所以缓存命中 / 写入单独统计计价，避免高估成本。

## 进行中的会话

「会话」页按主机分组展示**正在写入 / 返回结果**的 session（不是仅仅「已启动」）。

- **判定**：session 的转录文件在 `active_window`（默认 90s）内被写过即视为进行中；主机面板为空 = 当前没有在干活的会话。
- **结束后保留**：刚结束的 session 保留 `ended_keep`（默认 600s），标灰并注明「X 前结束」，方便看出哪些任务刚结束。
- **轮询**：复用每台主机的命令并追加 ` --active`，按 `active_interval`（默认 5s）独立刷新。
- **卡片内容**：项目目录、agent 类型、模型、本次任务执行时长与任务内容。

## 网页能力

- 顶部主机状态与筛选；范围切换（今日 / 7 / 30 / 90 天 / 全部）
- 汇总卡片（成本、token、缓存）；按模型 / 按日期表格（含成本）
- GitHub 风格热力图（近 30 天，悬停看当日用量与成本）
- 「会话」页：实时展示各主机进行中的会话

## 配置项

| 键 | 默认 | 说明 |
|---|---|---|
| `server.host` / `server.port` | `127.0.0.1` / `8080` | 监听地址 |
| `server.collect_interval` | 60 | 用量采集轮次间隔（秒） |
| `server.refresh_interval` | 10 | 网页自动刷新间隔（秒） |
| `server.active_interval` | 5 | 进行中会话的轮询间隔（秒） |
| `collection.timeout` | 30 | 单条命令 / 单次 ssh 超时（秒） |
| `collection.active_window` | 90 | 会话文件 mtime 在此窗口（秒）内视为进行中 |
| `collection.ended_keep` | 600 | 已结束会话保留展示的时长（秒） |
| `store.path` | `usage.db` | SQLite 文件（相对配置文件目录） |
| `local.command` | 空 | 本机采集命令，空则禁用本机 |
| `hosts[].address` | — | 远端 IP/域名，或 `~/.ssh/config` 的 Host 别名 |
| `hosts[].user` | 空 | SSH 用户名 |
| `hosts[].command` | — | 远端采集命令 |
| `hosts[].port` / `hosts[].key` | 22 / 默认密钥 | SSH 端口与私钥路径 |

> 首次连接新主机会自动接受主机密钥（`StrictHostKeyChecking=accept-new`）；如需严格校验，请手动把主机公钥加入 `known_hosts`。

## 自定义数据源

除 `collect_agents.py`，任何能把用量输出成上面 JSONL 的命令都可以接入：

```bash
cat /var/log/llm-usage.jsonl                 # 已有日志
python3 /opt/scripts/litellm_to_jsonl.py     # 自定义脚本（如 LiteLLM 日志/DB 转 JSONL）
```

命令输出多少就导入多少：首次要完整历史就用 `cat` 全量（去重后累积）；用 `tail -n N` 则只保留最近 N 条。

## 限制

- 历史依赖采集器持续运行；停采集的时段没有数据。
- 时间戳以记录的 `ts` 为准，缺省会记为采集时刻。
