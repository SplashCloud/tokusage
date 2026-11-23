# tokusage

收集本机（Windows）与远端主机（Linux）的 token 用量，用一个本地网页实时展示。

- 按模型 / 按日期统计
- 基于用量的成本计算（各模型官方定价，缓存命中 cache read/write 单独拆分计价）
- 监控各主机进行中的会话（按主机分组，只显示正在返回结果的 session）
- GitHub 风格热力图（近 30 天，颜色越深用量越多）
- 网页自动刷新
- 核心（`tokusage.py`）零第三方依赖（Python 3.11+ 标准库）；可选的 coding-agent 采集器读 codex 时需要 `pyzstd`

## 原理

1. 采集器对每台主机（含本机）运行一条**你配置的命令**，命令向 stdout 输出 JSONL。
2. 每条记录解析后去重，写入本地 SQLite（`usage.db`），历史持续累积。
3. 内置 Web 服务读取 SQLite，聚合后通过 `/api/dashboard` 提供给网页；网页按 `refresh_interval` 自动轮询。

远端主机通过 **SSH 密钥免密**访问（本机 `ssh` 命令，OpenSSH 客户端）。

## 记录格式（JSONL）

命令每行输出一个 JSON 对象：

```jsonl
{"ts": "2026-11-20T14:30:00+08:00", "model": "gpt-4o", "prompt_tokens": 123, "completion_tokens": 456}
{"ts": "2026-11-20T14:31:05+08:00", "model": "claude-sonnet-4", "prompt_tokens": 10, "completion_tokens": 20, "id": "req-9f2c"}
```

| 字段 | 必填 | 说明 |
|---|---|---|
| `ts` / `timestamp` | 否 | 时间；ISO-8601 字符串或 Unix 时间戳（秒）。缺省用采集时间 |
| `model` / `model_name` | 否 | 模型名；缺省为 `unknown` |
| `prompt_tokens` | 否 | 输入 token 数（不含缓存命中），缺省 0 |
| `completion_tokens` | 否 | 输出 token 数，缺省 0 |
| `cache_read_tokens` | 否 | 缓存命中读取的输入 token 数，缺省 0 |
| `cache_write_tokens` | 否 | 写入缓存的 token 数，缺省 0 |
| `total_tokens` | 否 | 总量；缺省 = prompt + completion + cache_read + cache_write |
| `id` | 否 | 稳定去重键；缺省用内容哈希 |

> 建议给每条记录一个稳定的 `id`（如请求 ID），去重更可靠。缺省的内容哈希对「时间/模型/输入/输出/缓存读/缓存写」完全相同的记录视为同一条。

## 成本计算

每条记录按模型的**官方定价**折算成本（USD），展示在汇总卡片、按模型表、按日期列表与热力图 tooltip。

- **定价来源**：`aihubmix.com/api/v1/models`，价格为每 1M token 的美元价（`input` / `output` / `cache_read` / `cache_write`）。
  仓库内置 `pricing.json`（856 个模型）；定价变动时运行 `python fetch_pricing.py` 重新拉取。
- **模型匹配**：去掉 provider 前缀后与 `pricing.json` 的模型 ID 精确匹配（`aihubmix/deepseek-v4-pro-0813` → `deepseek-v4-pro-0813`）；
  匹配不到的模型（如 `unknown`）成本按 0 计。少量别名在 `tokusage.py` 的 `MODEL_ALIASES` 里维护。
- **公式**：`成本 = (输入 × input + 输出 × output + 缓存读 × cache_read + 缓存写 × cache_write) / 1_000_000`。
- **缓存口径**：缓存命中（cache read）与缓存写入通常远低于常规输入价，因此 `collect_agents.py` 会把它们单独拆出，
  否则成本会被高估。`prompt_tokens` 是「不含缓存命中的输入」，`total_tokens = prompt + completion + cache_read + cache_write`。

## 进行中的会话

「会话」页按主机分组展示各台机器上**正在进行**的 session——即 agent 此刻正在写入 / 返回结果，而非仅仅「已启动」。

- **判定方式**：session 的转录文件（omp 的 `sessions/*/*.jsonl`、codex 的 `sessions/*/rollout-*.jsonl(.zst)`、claude 的 `projects/*/*.jsonl`）在 `active_window`（默认 90 秒）内被写过，即视为进行中。某台主机面板为空，就代表它当前没有在干活的会话，可以去 review 已结束的。
- **结束的会话不会立刻消失**：最近结束的 session 会继续保留 `ended_keep`（默认 600 秒），标灰显示并注明「X 前结束」，方便看出哪些任务刚结束。
- **采集命令**：复用每台主机的 `command`，自动追加 ` --active`（即 `collect_agents.py --active`），按 `active_interval`（默认 15 秒）独立轮询。若某台主机用自定义命令，需保证它接受 `--active` 并输出同样的 JSONL。
- **面板内容**：项目目录（omp 取自 session 的 `cwd`）、agent 类型（omp/codex/claude）、模型名、本次任务执行时长（最近一条用户消息到现在）、本次任务内容（最近一条用户消息，截断展示）。

## 使用

1. 安装：无需安装依赖。确保 `python` ≥ 3.11，`ssh` 在 PATH（Windows 10+ 自带 OpenSSH 客户端）。

2. 配置：复制 `config.toml`，填入每台主机的命令与 SSH 信息（见文件内注释）。

3. 运行：

```bash
python tokusage.py                 # 启动采集 + 网页
python tokusage.py --config my.toml
python tokusage.py --collect-once  # 只采集一轮后退出（可配合计划任务）
python tokusage.py --check         # 校验配置并试采集一轮，打印每台主机状态
python tokusage.py --deploy        # 自动把 collect_agents.py 拷到各远端并装好 pyzstd
```

4. 打开浏览器访问 `http://127.0.0.1:8080`。

## 远端命令示例

不同来源转成统一 JSONL：

- 已有 JSONL 日志：

  ```bash
  cat /var/log/llm-usage.jsonl
  tail -n 50000 /var/log/llm-usage.jsonl
  ```

- 任意工具用脚本包一层，输出 JSONL 即可。例如从 LiteLLM 的日志/DB 里按需投影成上面的记录格式：

  ```bash
  python3 /opt/scripts/litellm_to_jsonl.py
  ```

- 想只取某个时间窗、按模型聚合后再输出，也可直接在命令里完成（采集器只负责收 JSONL）。

## 从 coding agent 目录采集（collect_agents.py）

仓库自带的 `collect_agents.py` 直接读取每台机器上三个 coding agent 的本地目录，输出统一的 JSONL：

| agent | 数据位置 | 读取内容 |
|---|---|---|
| omp | `~/.omp/agent/sessions/**/*.jsonl` | `message.usage`（主 agent 轮次，嵌套在 assistant message 里）+ `compaction`/`branch_summary`/`usage`（计费操作） |
| codex | `~/.codex/sessions/**/rollout-*.jsonl.zst` | `token_usage_record` 行，模型按 `thread_settings_applied` 关联 |
| claude code | `~/.claude/projects/**/*.jsonl` | 带 `usage` 的 assistant 行 |

- Windows 与 Linux 通用；目录不存在会自动跳过。
- codex 的 rollout 是 zstd 压缩的，按优先级自动选择后端：`pyzstd` → `zstandard` → 系统 `zstd`/`zstdcat`/`unzstd` CLI。
  一个都没有则跳过 codex 并在 stderr 提示（omp/claude 不受影响）。
- 可传 `--days N` 只输出最近 N 天（`python collect_agents.py --days 45`）。
- 输出会把缓存命中单独拆成 `cache_read_tokens` / `cache_write_tokens`（`prompt_tokens` 为不含缓存命中的输入），供成本准确计价。
- `python collect_agents.py --active [--window N]` 改为输出进行中的会话（见「进行中的会话」一节）。

部署：本机在 `local.command` 里跑 `python collect_agents.py`；远端不用手动操作，直接

```bash
python tokusage.py --deploy
```

它会依次对每台 `[[hosts]]`：`mkdir ~/tokusage` → `scp collect_agents.py` → 安装 `pyzstd`
（`--user` / `--break-system-packages` / 普通三种依次尝试）→ 试跑一轮报告记录数。
目标目录可用 `hosts[].deploy_dir` 覆盖（默认 `~/tokusage`），需与 `command` 里的路径一致。

## 网页能力

- 顶部状态条：每台主机采集状态（绿=正常 / 红=错误 / 黄=待首次采集）与范围总量
- 机器筛选：下拉选择「全部主机 / 某台主机」，汇总卡片、热力图、按模型、按日期都按所选主机过滤
- 范围切换：近 7 / 30 / 90 天 / 全部
- 成本卡片 + 缓存读取/写入卡片；按模型表有「成本」列（可点击表头排序）
- 热力图：固定近 30 天，按周分列、周一至周日分行，悬停显示当日总量与成本
- 按模型 / 按日期：表格 + 条形占比（含成本）
- 「会话」页：顶部切换，按主机分组展示进行中的会话（agent 正在返回结果），独立轮询自动刷新

## 配置项

| 键 | 默认 | 说明 |
|---|---|---|
| `server.host` / `server.port` | `127.0.0.1` / `8080` | 监听地址 |
| `server.collect_interval` | 60 | 采集轮次间隔（秒） |
| `server.refresh_interval` | 10 | 网页自动刷新间隔（秒） |
| `server.active_interval` | 15 | 进行中会话的轮询间隔（秒） |
| `collection.timeout` | 30 | 单条命令/单次 ssh 超时（秒） |
| `collection.active_window` | 90 | 会话文件 mtime 在此窗口（秒）内视为「进行中」 |
| `collection.ended_keep` | 600 | 已结束会话保留展示的时长（秒） |
| `store.path` | `usage.db` | SQLite 文件（相对配置文件目录） |
| `local.command` | 空 | 本机命令，空则禁用本机采集 |
| `hosts[].address` | — | 远端地址：IP/域名，或 `~/.ssh/config` 的 Host 别名；留空回退到 `name` |
| `hosts[].user` | 空 | SSH 用户名；留空则沿用 ssh config 里该 Host 的 User |
| `hosts[].command` | — | 远端命令 |
| `hosts[].port` / `hosts[].key` | 22 / 默认密钥 | SSH 端口与私钥路径 |

> 首次连接新主机会自动接受主机密钥（`StrictHostKeyChecking=accept-new`）；若要求严格校验，请自行把主机公钥加入 `known_hosts` 后改回严格模式。

## 数据从哪来（重要）

本工具**不会自动发现**你的 token 数据：它只收集每台主机上**你配置的命令**输出的 JSONL。
「采集不到」通常只有一个原因——`local.command` 为空，或远端命令没有指向真正的日志/DB。

- 首次采集就能拿到**全部**历史的前提：命令把完整历史一次性输出（例如 `cat /full/log.jsonl`）。
  命令输出多少，首次采集就导入多少，历史会完整写入 SQLite，**不存在「首次只能拿到最近 N 条」**。
- 若命令是 `tail -n N`，则每次只看到最近 N 条；更早的历史不会进入 SQLite（需要全量历史就 `cat` 全量 + 去重）。
- 本机（Windows）同理：把 `local.command` 指向本机生成 token 用量的来源。
  针对 codex / omp / claude code 这三类 coding agent，仓库已提供现成的 `collect_agents.py`
  （见上一节），直接把 `local.command` 设为 `python collect_agents.py` 即可。
  `local.command` 留空 = 本机不采集。

一句话：数据源在哪、长什么样，工具不知道，需要你用命令告诉它。

## 限制

- 历史累积依赖采集器持续运行；停掉采集器的时段不会有数据。
- 记录的时间戳以 JSONL 里的 `ts` 为准；缺省 `ts` 会记为采集时刻，追溯更早的历史时请务必带上 `ts`。
