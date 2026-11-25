# #1742：正式独审 attempt 的启动前预检

**可信路由使用 CLIProxy 生产者原子发布的结构化收据。旧文本日志入口保留但不能放行；迁移必须显式使用 `--proxy-receipt-dir` 或 `--proxy-receipt-container`。本仓提供固定源码补丁和隔离 Linux 构建入口，生产代理交付与真实验收由主控安排。**

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

代理运行补丁版并设置 `CLIPROXY_PREFLIGHT_RECEIPTS=/tmp/cliproxy-preflight-receipts` 后，在原命令中增加：

```sh
  --proxy-receipt-container blackhole-cliproxy \
  --proxy-docker-context orbstack \
  --proxy-container-receipt-dir /tmp/cliproxy-preflight-receipts \
  --review-docker-context colima
```

收据目录是代理 UID 私有的容器临时目录，不放入 Blackhole 凭据/状态卷，不新增挂载。代理自身写入；宿主用参数数组执行 `docker --context orbstack exec … python3 -I -c … --receipt …`，容器内只读取脱敏收据。Blackhole 当前镜像已装 Python 3。审阅的 `run` 和回收的 `rm -f` 都使用 Colima。两者互不借用 context。

宿主部署的补丁代理可显式使用 `--proxy-receipt-dir <私有收据目录>`；它也在受总 deadline 约束的子进程中读取，防止文件读取阻塞拖住宿主。原 `--proxy-log-dir`、`--proxy-log-container` 和 `--proxy-container-log-dir` 仍表示**旧文本日志**，不能将收据路径填进去冒充迁移。这些旧入口不读取文本并返回无证明，不静默切换格式。

容器外始终只有 `{session, complete_stable, routes}`。`complete_stable=true` 表示生产者收据已封口并原子发布，不再表示两次文件大小相同。routes 是全部有序 HTTP 尝试的白名单枚举或 `other`，保留重复项；每项都必须满足该模型的原 allowlist。宿主继续拒绝多余字段、重复 JSON 字段、不匹配 session、自由文本和异常退出。不存在从失败收据降级回文本的路径。报告的既有 `log_found` 字段表示取得可用路由证据，不证明文本文件存在。

### 成功终态之后仍须读到 EOF

预检收到 `response.completed` / `response.incomplete` 后继续读完流，不能立刻关闭连接。CLIProxy v8.0.63 的 Claude 路径仍需完成上游帧与 lifecycle 收尾；提前断开会取消执行，留下 nonce 目录但没有收据。消费者使用标准库 `HTTPResponse.read()`（不传 `amt`）验证 Content-Length / chunked 完整性，不把逐行迭代结束当作完整响应。整个 HTTP 往返在独立子进程组内执行，连接、响应头、成功体和错误体共用父进程传入的绝对工作期限。父进程通过 `run_bounded` 到期终止并 wait 回收进程组，不依赖 socket 空闲超时或成功体阶段的计时器。密钥仅通过 stdin 管道传入，stdout 仅返回固定字段的脱敏结果，stderr 不进入报告。只有 HTTP 响应体完整读完、未超总 deadline、无后续错误或冲突终态，往返检查才成功；路由检查仍独立要求完整收据和全部 attempt 通过 allowlist。终态之后一直不结束的流仍按原总 deadline 拦截。

#2055 的离线回归使用原生 Claude executor、首次 503 后重试和受控迟到的终态帧尾：客户端读终态行就断开时无收据；读完 EOF 时产生两条 Claude 路线。生产者封口条件未放宽，真实路线仍须以新正式预检的收据为证。

## 固定生产者构建与离线验证

在 `.sandcastle/deepagents-pilot` 下运行：

```sh
python3 cliproxy/build.py --docker-context colima --output /tmp/cliproxy-preflight-build-01
CLIPROXY_OFFLINE_RECEIPTS=/tmp/cliproxy-preflight-build-01/receipts \
  PYTHONPATH=../approval-signing LANGSMITH_TRACING=false LANGCHAIN_TRACING_V2=false OTEL_SDK_DISABLED=true \
  python -m pytest tests/test_review_preflight.py tests/test_cliproxy_receipt_contract.py -q --disable-warnings
python -m ruff check --select F,E9,B,I .
```

`build.py` 使用 Python ≥ 3.12 下载固定 commit，应用 `cliproxy/preflight-v1.patch`；不复制本机配置、凭据或日志。Dockerfile 固定 Go 镜像及摘要，首次准备公开依赖需要网络，测试和 Linux 编译都使用 `RUN --network=none`。输出目录必须不存在，产物为 `cli-proxy-api`（当前构建宿主的 Linux 架构）、`version.txt`、`runtime.txt`、`go-test.txt` 和 fake 生成的 `receipts/`。构建还在 Blackhole 同款 `debian:bookworm-slim` 基础镜像内以 UID 1000、无网络运行 `--help`，确认动态链接和非 root 启动。Blackhole 现有 Dockerfile 下载官方 linux_aarch64 压缩包；主控需让其交付链使用此补丁二进制，并核对目标架构。本脚本不部署、不改 Blackhole、不加载产物到生产容器。

Go `-race` 测试包含实际 `/v1/responses` handler、原生 Kimi/Claude executor 和失败后重试；只将出站网络替换为本地 fake，分别导出双 attempt 成功收据。Python 直接消费这些 Go 产物，验证成功路径及 `other`、未收尾、正文伪造尾部的拒绝路径。未提供 `CLIPROXY_OFFLINE_RECEIPTS` 时跨语言测试会 skip，不能把这种运行报告为端到端通过。

### 生产者支持范围与完成合同

- 补丁同时支持两类显式开启的私有收据，普通请求完全不受影响、未配置收据目录时不产生证据：
  1. **旧预检路由收据（`cliproxy-preflight-v1`）**：由 `POST /v1/responses` 且请求头 `Session-Id: preflight-<UUIDv4>` 触发，覆盖原生 `KimiExecutor`、`ClaudeExecutor`、`AntigravityExecutor` 以及原生 `CodexExecutor`（仅 `gpt-6.2-sol` / `gpt-6.2-astra`，按 `codex:<model>@chatgpt.com` 核验出站请求体模型与受控 TLS transport）。Antigravity 仍会被记录但被 allowlist 拒绝。
  2. **正式独审封存收据（`cliproxy-review-v1`）**：由 `POST /v1/responses`（流式 `stream: true`）携带 `X-NewChanlun-Review-Launch: review-<UUIDv4>`（正式独审）或 `review-preflight-<UUIDv4>`（预检封存探针）及 `Session-Id: <UUID>` 触发，仅允许原生 `CodexExecutor` 的 `gpt-6.2-sol` / `gpt-6.2-astra` 路由；逐帧校验响应模型、响应 ID 一致性与显式 `output_text` 最终答复（排除 `commentary` 过程消息与非最终拒答）。
- **封存确认与消费端分离**：
  - 代理直接对已验证且固定描述符的收据根目录 `<receipt-root>` inode 施加非阻塞独占 `flock` 强制同根目录单写者（不依赖可被轮转的独立锁文件，发现并发实例持有锁时所有预留、写入与封存均失败闭合）；端点 `POST /v1/review-receipts/seal` 在确认同 launch 全部在途请求结束后原子写入 `sealed=true` 与独立摘要文件 `seal.sha256` 并完成 launch、root 与固定父目录 fd 的 `fsync`，**仅在 `SealOK` 时**返回 `{"status":"sealed","launch":...,"session":...,"receipt_sha256":...}`（重复封存始终绑定原已封存目录 inode 并重新执行目录 `fsync`，重启或重复封存亦须与 `seal.sha256` 一致）；目录同步失败或目录被替换返回 `503 unavailable` 且不返回确认摘要。
  - `_review_preflight_log.py` 严格区分两类读取入口：正式验收 `--review-receipt` 仅接受 `review-<UUIDv4>`，必须提供代理封存接口返回的 `expected_receipt_sha256` 以及独立的 `expected_response_id_sha256`、`expected_output_sha256` 与 `min_requests >= 1`（仅工具调用或过程消息无最终答复均拒绝）；预检探针 `--review-preflight-receipt` 仅接受 `review-preflight-<UUIDv4>`，须提供 `expected_receipt_sha256` 并输出 `preflight_sealed`（不输出 `complete_stable`）。
- 插件 executor、`/v1/responses/compact`、`count-tokens`、非流式正式审阅、裸 `HttpRequest`、非标准自定义 RoundTripper、WebSocket 及其他入口均不在支持范围内，直接拒绝并按规则污染 launch。
- 默认空插件宿主可用；活跃插件或请求期间插件快照变化使证据失效。原生受控 HTTP transport 保留严格 TLS 与代理边界；OAuth 刷新不是模型尝试。
- collector 从入站头绑定 nonce/launch 与服务端起点，并跨 handler bootstrap 重试共享。全部 Manager 执行调用经过同一 guard；没有任何被观察 HTTP 传输的执行也拒绝证明。传输开始前分配全局序号，失败请求、重定向及重复路线不去重。只存固定枚举与 SHA-256 摘要，不存正文、URL 路径、auth_id、token 或错误字符串。
- 成功发布要求：HTTP handler 成功结束、请求 lifecycle 成功、所有执行租约结束（含取消路径等待生产者关闭上游流后再释放租约）、全部响应体关闭且达到上游 EOF、至少一个尝试、没有覆盖缺口。预检最多 64 次传输、50 秒生命周期；正式独审每 launch 最多 512 轮响应 ID 且首轮开始到末轮完成不超过 2 小时，超限失败闭合。
- `<receipt-root>` 必须是代理独占写入的专用 `0700` 私有目录（不得与外部并发写进程共享，亦禁止配置为原状态卷目录）。每个 nonce/launch 在认证后的受支持执行开始时通过 `<root>/.staging/` 预构建完整 `0700` 目录与 `producer.json`，再以描述符固定的不覆盖原子重命名（Linux `renameat2(RENAME_NOREPLACE)` / macOS `renameatx_np(RENAME_EXCL)`）发布到根目录，未认证请求不写磁盘且崩溃不会留下无标记空目录；根目录与收据文件均须属当前用户且无 group/other 权限、禁止祖先与末段 symlink（且在路径归一化或相对路径展开前统一拒绝 `..`），加锁后的读写、重命名、硬链接、校验、同步（生产路径仅对已验证的目录及父目录描述符调用 `fsync`，并在返回 `SealOK` 前通过固定父目录 fd 及配置路径复核根目录仍绑定原持锁 inode）与回收均绑定至同一引用计数持锁目录描述符（`*os.Root` / 目录 fd）。临时文件统一写入根目录私有的 `<root>/.staging/`（带随机后缀并在 `EEXIST` 时有界重试、不占用桶配额、新接管根目录 `flock` 及过期扫描时仅清理经严格内容与摘要校验属生产者创建的遗留暂存项与隔离回收目录，不删除已存在的非生产者文件）；旧预检完成后通过绑定源/目标目录描述符的 `linkat` 发布为 `receipt.json`（不覆盖已有目标，拒绝向含非 `producer.json` 文件的脏目录发布）并在以 `O_NONBLOCK` 核对 `producer.json` 文件身份与摘要后清理标记；正式独审保留 `producer.json`（用于故障污染后的不可复用约束与过期回收），封存时在 `.staging/stage-seal-*` 中成对准备 `producer.json`、`seal.pending.json` 与 `seal.sha256` 再按绑定描述符的 `renameat` 三步原子提交（`seal.pending.json` → `seal.sha256` → 原子重命名为 `receipt.json`）后同步目录并复核根目录绑定。旧预检（`preflight-<UUIDv4>`）与正式独审（`review-*`）各自使用独立的目录配额上限（默认各 2048）与独立桶锁，互不阻塞挤占。仅当对应桶触顶时，生产者先以目录 `ModTime` 快速跳过未到期项并按有界轮转配额（单次最多解析 64 项并缓存未到期/不可回收结果）筛选超过保留期（旧预检 30 分钟、正式独审 24 小时）、包含经严格 JSON 类型与协议字段（含旧预检 50 秒生命周期与固定路由白名单）校验的 `receipt.json` 或 `producer.json`（若存在 `seal.sha256` 必须与 `receipt.json` 或中断封存遗留的 `seal.pending.json` 逐字节 64 字节摘要一致，且中断封存须核对除 `sealed`/`sealed_at_ns` 外的全部不可变字段完全一致）且不含任何其他文件的目录；回收时先以原子重命名将已校验目录移出配额桶进入 `.staging/reclaim-<random>` 并立即核对移入目录的 `(dev, ino)` 一致（不匹配则尝试还原并放弃回收），确认一致后再在保持文件描述符打开的条件下复核每个已核验子文件的 `(dev, ino, sha256)` 并经目录 fd 调用 `unlinkat`（在单写者专用私有目录前提下避免误删已存在的非生产者目录与文件，POSIX `unlinkat` 按名解析的同 UID 并发恶意篡改边界超出进程隔离）。部署方亦可在无活动任务时清理整个专用临时目录。

## 可信证据缺口

核查版本为 Blackhole Dockerfile 固定的 CLIProxy `v8.0.63`，公开源码提交 `6db7d4b839d86c5b24e17bbe73bcd4db18ef1b1a`：

- [logging_helpers.go:175–190](https://github.com/router-for-me/CLIProxyAPI/blob/6db7d4b839d86c5b24e17bbe73bcd4db18ef1b1a/internal/runtime/executor/helps/logging_helpers.go#L175-L190) 写文本段头与 `Body:`；[同文件:247–288](https://github.com/router-for-me/CLIProxyAPI/blob/6db7d4b839d86c5b24e17bbe73bcd4db18ef1b1a/internal/runtime/executor/helps/logging_helpers.go#L247-L288) 将响应 chunk 原样追加，未转义正文中的段头，也没有正文长度帧。
- [request_logger_format.go:127–166](https://github.com/router-for-me/CLIProxyAPI/blob/6db7d4b839d86c5b24e17bbe73bcd4db18ef1b1a/internal/logging/request_logger_format.go#L127-L166) 原样复制请求正文；空行分隔并不排除正文含相同空行与段头。
- [request_logger_streaming.go:242–258](https://github.com/router-for-me/CLIProxyAPI/blob/6db7d4b839d86c5b24e17bbe73bcd4db18ef1b1a/internal/logging/request_logger_streaming.go#L242-L258) 直接创建最终文件再写入，不是写完后原子发布；[同文件:306–333](https://github.com/router-for-me/CLIProxyAPI/blob/6db7d4b839d86c5b24e17bbe73bcd4db18ef1b1a/internal/logging/request_logger_streaming.go#L306-L333) 先写全部 API REQUEST，再写全部 API RESPONSE，最后写 RESPONSE。旧 fake 的交错排列不是该版本的完整布局。

因此正文可生成与结构相同的字节；稳定文件也可能是写入暂停或失败的前缀。正则、编号连续性、末尾段头、两次大小稳定都不能证明完整性或来源。两个独审反例分别伪造最终 RESPONSE 并留下未闭合第二次尝试，以及在响应正文注入 API REQUEST 99。正常多 attempt 文本同样缺少可信完成证据，当前也必须拦截。

现在由上述固定生产者补丁提供正文之外的证据：收据含 schema、session、服务端开始/完成纳秒时间、完整布尔状态和有序 routes；routes 长度即 attempt 数。消费者严格检查字段、时间窗口、枚举、数量及格式。旧文本即使看起来正常完整仍被拒绝。

生产启用前仍须完成补丁非作者独审、代理二进制交付和真实正式预检。不得手工编造收据、mock 正式验收或跳过操作门。

## 检查什么

每项检查对应一次真实发生过的正式 attempt 启动失败。

| 检查 | 拦下的真实失败 | 做法 |
|---|---|---|
| `checkout_root_free_space` | PR1866 A1/A2、PR1868 A3（f9）：快照需 2.60GB，HOME 只剩 1.40–1.65GB | 逐字节复刻 `prepare_review` 的快照字节公式，要求 checkout_root 所在卷剩余 ≥ 2 份（两位 reviewer） |
| `checkout_root_container_mount` | PR1868 A1：checkout 在未共享进 colima 的路径，容器里看到的是 VM 本地空目录 | 在 checkout_root 写一次性 nonce，用审阅镜像 `--network none --read-only` 只读 bind 挂载 checkout_root 读回；读不到或不一致即拦。探针目录与容器随即删除，删不掉报 `probe_cleanup`；`docker run` 超时或 docker 自身出错（退出 125）时，daemon 可能在 `rm -f` 之后才建出容器，也报 `probe_cleanup`（回收未确认） |
| `route:<model>` | PR1883 A1：claude-opus-5-5 新会话被选到 Antigravity | 旧文本始终拦截；可信收据的每次尝试要求 Sol=`codex@chatgpt.com`，Kimi=`kimi@api.kimi.com` 或 `kimi-ai@api.kimi.ai`（CLIProxy 在国内、国际两个上游间切换），Opus=`claude@api.anthropic.com`；只探测 `external_review.MODELS` 当前的两位。没有完整收据也拦 |
| `roundtrip:<model>` | 同上，上游 400 `tool_choice ... not supported` | 每家一次最小 `/v1/responses` 往返，带 tools、`tool_choice=auto`、JSON 输出格式、新会话，必须读到 `response.completed`/`incomplete` |
| `credential:codex-host` | #1323：宿主缺 `CLIPROXY_LOCAL_KEY`，回合在调模型前报 `Missing environment variable` | 去掉该环境变量后，按 `$CODEX_HOME/config.toml` 的 `model_providers.cliproxy-local` 取 key（`auth.command` / `env_key`）。provider 配置是否合法以宿主自己的 codex 为准：先离线跑一次 `codex features list`（约 50ms，不发请求），Codex 拒绝加载就拦（如 `auth` 与 `env_key` 并存），报告只取 Codex 报错里的字段名。两家往返都用这把 key，所以通过即证明没有该变量时 provider 也能完成往返 |

模型探测每家只发一次、提示极短（effort=low），这是预检唯一的模型花费。

## 时限与回收

所有子进程（git、`auth.command`、docker、HTTP 往返）只经过一个有界原语 `run_bounded` 启动：独立进程组、最多等给定秒数、返回前无论成败都杀掉整个进程组（包装脚本留在后台的子进程一并结束）。时间只有一个来源 `Deadline`：检查用到总时限减 min(3 秒, 总时限/2)，余下留给 `docker rm -f` 与输出报告。两次往返在线程里与空间、挂载检查并行。HTTP 进程启动时间计入原工作期限；到期先终止并回收进程，再返回失败。`run_checks` 的正常和异常出口均等待本次探测线程完成回收，不留下活动 HTTP worker，也不靠 daemon 或 `os._exit` 跳过清理。

不要把 effort 降到 `minimal`：2026-11-05 实测 Sol 在 `minimal` 下返回 400（codex 后端注入的 `image_gen` 工具不能与 `minimal` 同用），预检会因此误报。旧实现等待 request-log 落盘再判定的方式已撤回；文本入口立即返回无可信证据。新收据入口等待原子发布，其读取与子进程收尾不得越过工作期限。

## 局限

- 预检是某一时刻的快照。CLIProxy 是 fill-first + 会话亲和，正式 attempt 的新会话仍可能在几秒后被选到别的凭据；路由的根治在共享 proxy 配置（当前已用 `oauth-excluded-models.antigravity` 排除两个 Claude 模型），预检只负责发现回归。
- JSON 围栏类失败需要真实模型完整输出才能复现，预检不覆盖。
- 以下检查没有对应的真实失败，已移出本版、留作后续单独 PR：正式 worker 的 key 来源（进程环境 / launchctl）、实际服务模型（Claude fallback 到 4.8）、CLIProxy `request-log` 开关、目标 commit 缺失时的 `needs_source_sync`、空间不足时 VM 持有已删除文件的诊断、宿主 `base_url` 与预检代理是否同一端点。

## 测量

拦截率与误报按冻结语料在隔离环境注入同样故障测得：小容量卷模拟 HOME、VM 内同名空目录、本地假 proxy 返回同样的 400、修前形态的 Codex provider 配置。不碰共享 proxy 与真实账号。结果见 PR 描述。
