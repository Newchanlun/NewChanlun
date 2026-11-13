# #1742：正式独审 attempt 的启动前预检

每次启动正式 attempt（`ExternalReview.review_pr`）之前运行一次。预检只回答“现在的环境能不能让两位 reviewer 跑完”，**不是审阅结果**：报告固定写 `"is_review_result": false`，不写 App 状态、不进 `external-review/runs`、不占 attempt 号。预检拦下时修环境，修好后再预检，通过了才启动新 attempt。

## 用法

在要启动正式 attempt 的 controller checkout 根目录，用启动 attempt 的同一宿主账户运行（Python ≥ 3.11，只用标准库）：

```sh
python3 -I .sandcastle/deepagents-pilot/review_preflight.py \
  --source . \
  --base <base_sha> --head <head_sha> --merge-base <merge_base_sha> \
  --checkout-root /Volumes/AgentStorage/issue1742-deepagents-pilot-20261027/checkouts/external-review
```

- `--checkout-root` 填正式 attempt 将传给 `ExternalReview(checkout_root=...)` 的同一路径；示例是其缺省值 `external_review.CHECKOUT_ROOT`，位于外卷。
- 三个 SHA 与 attempt 的 target 相同；`--source` 是 controller 读候选对象的仓库。
- 其余参数有默认值：`--image sandcastle:newchanlun`、`--proxy-url http://127.0.0.1:8318`、`--proxy-log-dir ~/Library/Application Support/CLIProxyLocal/auth/logs`、`--codex-home $CODEX_HOME 或 ~/.codex`、`--codex-bin codex`、`--deadline 55`。

退出码：`0` 可以启动；`2` 拦截（看 `checks` 里 `ok:false` 的项）；`3` 用法错误。任何退出路径（含用法错误与 `--help`）stdout 都是一行 ASCII JSON。上游错误正文与 docker/daemon 的 stderr 不进报告，只给 HTTP 状态、终态、固定词表分类（如 `tool_choice_unsupported`、`quota`、`auth`）、长度与 sha256 前 12 位，以免回显的 key 经各种转义漏出；其余来自上游或 proxy 日志的字段也只取已知枚举（响应 status、路由 provider@host，其余记 `other`）；报告其余字段输出前按全部已知 key 的各种形态脱敏。

## 代理与审阅镜像位于不同 Docker context

代理日志只存在状态卷时，在原命令中增加以下参数，替换 `--proxy-log-dir`：

```sh
  --proxy-log-container blackhole-cliproxy \
  --proxy-docker-context orbstack \
  --proxy-container-log-dir <代理容器内日志绝对路径> \
  --review-docker-context colima
```

日志目录须由部署方确认，不读取代理配置猜路径。代理容器需要 Python 3.11+；Blackhole 的 `Dockerfile.cliproxy` 已安装 Python 3。宿主执行 `docker --context orbstack exec … python3 -I -c …`，使用容器原有用户在代理容器内解析。不启动旁路容器，不新增状态卷挂载，不复制原始日志。审阅的 `run` 和回收的 `rm -f` 都使用 `--review-docker-context`。未指定审阅 context 时沿用原 Docker 环境；原 `--proxy-log-dir` 用法不变。

两种读取入口共享 `_review_preflight_log.py`。只读本次 session、请求起点前一秒以来的普通文件；拒绝符号链接与 FIFO。完整 `RESPONSE` 段出现后，相邻两次轮询的设备、inode、大小与修改时间必须一致，读取期间文件也不得变化。每个 API REQUEST 段保留一次路由，顺序与重复项均保留；响应正文中的同名字段不参与提取。所有尝试都必须通过该模型的 allowlist。

容器只输出以下协议，宿主再次校验字段集合、类型、session 与枚举。非零退出、stderr 非空、协议外输出、未完成或超时均拦截，不退回宿主目录读取。

| 字段 | 来源与允许值 |
|---|---|
| `session` | 本次预检生成的 session，必须逐字匹配 |
| `complete_stable` | 解析器的完成且稳定状态，只有布尔 `true` 可作证明 |
| `routes` | 有序的 `KNOWN_ROUTES` 枚举数组；未知 provider/hostname 归一为 `other` |

原始日志、URL 路径、auth_id、解析异常以及 Docker 的任意 stdout/stderr 都不进入报告。报告沿用 `route:<model>` 的 `actual`、`log_found` 和 `session`，不增加自由文本诊断字段。

容器读取共用总 `Deadline` 的工作预算，预留线程返回时间。解析进程自身用绝对到期时间和 `SIGALRM` 限制读取与输出，即使宿主 Docker 客户端超时退出也会自行终止；daemon 迟启动到期任务时立即退出。代理 VM 的时钟应与宿主同步；剩余时长超出宿主给定预算也拦截。该后端不创建文件或容器，因而无需对代理执行删除或停止操作。

离线验收覆盖双 context、读取失败/超时、重试顺序、半写/迟写/轮转、响应体字段伪造、未知枚举与自由文本不回显。上线前仍须由主控完成非作者独审，并在真实双 context、真实日志路径上运行正式预检；fake 测试不能代替该操作门。

## 检查什么

每项检查对应一次真实发生过的正式 attempt 启动失败。

| 检查 | 拦下的真实失败 | 做法 |
|---|---|---|
| `checkout_root_free_space` | PR1866 A1/A2、PR1868 A3（f9）：快照需 2.60GB，HOME 只剩 1.40–1.65GB | 逐字节复刻 `prepare_review` 的快照字节公式，要求 checkout_root 所在卷剩余 ≥ 2 份（两位 reviewer） |
| `checkout_root_container_mount` | PR1868 A1：checkout 在未共享进 colima 的路径，容器里看到的是 VM 本地空目录 | 在 checkout_root 写一次性 nonce，用审阅镜像 `--network none --read-only` 只读 bind 挂载 checkout_root 读回；读不到或不一致即拦。探针目录与容器随即删除，删不掉报 `probe_cleanup`；`docker run` 超时或 docker 自身出错（退出 125）时，daemon 可能在 `rm -f` 之后才建出容器，也报 `probe_cleanup`（回收未确认） |
| `route:<model>` | PR1883 A1：claude-opus-5-5 新会话被选到 Antigravity | 按本次唯一 `Session-Id` 在 CLIProxy request-log 里读每次上游尝试的 `Auth: provider` 与上游主机；要求 Sol=`codex@chatgpt.com`，Kimi=`kimi@api.kimi.com` 或 `kimi-ai@api.kimi.ai`（CLIProxy 在国内、国际两个上游间切换），Opus=`claude@api.anthropic.com`；只探测 `external_review.MODELS` 当前的两位。找不到日志也拦 |
| `roundtrip:<model>` | 同上，上游 400 `tool_choice ... not supported` | 每家一次最小 `/v1/responses` 往返，带 tools、`tool_choice=auto`、JSON 输出格式、新会话，必须读到 `response.completed`/`incomplete` |
| `credential:codex-host` | #1323：宿主缺 `CLIPROXY_LOCAL_KEY`，回合在调模型前报 `Missing environment variable` | 去掉该环境变量后，按 `$CODEX_HOME/config.toml` 的 `model_providers.cliproxy-local` 取 key（`auth.command` / `env_key`）。provider 配置是否合法以宿主自己的 codex 为准：先离线跑一次 `codex features list`（约 50ms，不发请求），Codex 拒绝加载就拦（如 `auth` 与 `env_key` 并存），报告只取 Codex 报错里的字段名。两家往返都用这把 key，所以通过即证明没有该变量时 provider 也能完成往返 |

模型探测每家只发一次、提示极短（effort=low），这是预检唯一的模型花费。

## 时限与回收

所有子进程（git、`auth.command`、docker）只经过一个有界原语 `run_bounded` 启动：独立进程组、最多等给定秒数、返回前无论成败都杀掉整个进程组（包装脚本留在后台的子进程一并结束）。时间只有一个来源 `Deadline`：检查用到总时限减 min(3 秒, 总时限/2)，余下留给 `docker rm -f` 与输出报告。两次往返不留本地产物，在守护线程里与空间、挂载检查并行，到时未完成即判失败。

不要把 effort 降到 `minimal`：2026-11-05 实测 Sol 在 `minimal` 下返回 400（codex 后端注入的 `image_gen` 工具不能与 `minimal` 同用），预检会因此误报。路由要读 request-log，而 proxy 在响应完成后才写日志（实测 14–85ms）；预检在往返成功后一直等到工作时限前 0.25 秒找日志，往返已失败时只等 0.3 秒。

## 局限

- 预检是某一时刻的快照。CLIProxy 是 fill-first + 会话亲和，正式 attempt 的新会话仍可能在几秒后被选到别的凭据；路由的根治在共享 proxy 配置（当前已用 `oauth-excluded-models.antigravity` 排除两个 Claude 模型），预检只负责发现回归。
- JSON 围栏类失败需要真实模型完整输出才能复现，预检不覆盖。
- 以下检查没有对应的真实失败，已移出本版、留作后续单独 PR：正式 worker 的 key 来源（进程环境 / launchctl）、实际服务模型（Claude fallback 到 4.8）、CLIProxy `request-log` 开关、目标 commit 缺失时的 `needs_source_sync`、空间不足时 VM 持有已删除文件的诊断、宿主 `base_url` 与预检代理是否同一端点。

## 测量

拦截率与误报按冻结语料在隔离环境注入同样故障测得：小容量卷模拟 HOME、VM 内同名空目录、本地假 proxy 返回同样的 400、修前形态的 Codex provider 配置。不碰共享 proxy 与真实账号。结果见 PR 描述。
