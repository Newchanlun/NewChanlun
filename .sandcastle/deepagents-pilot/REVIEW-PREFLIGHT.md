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
- 其余参数有默认值：`--image sandcastle:newchanlun`（由控制器调用时强制传已准入的不可变 `sha256:...` 镜像 ID）、`--proxy-url http://127.0.0.1:8318`（控制器正式调用时强制配 `--probe-in-container --proxy-url http://host.docker.internal:8318`，沿审阅容器实际网络路径探测）、`--proxy-log-dir ~/Library/Application Support/CLIProxyLocal/auth/logs`、`--credential-mode codex-host`（控制器调用时强制传 `worker-env`，与正式 worker 同一 `CLIPROXY_LOCAL_KEY` / `launchctl` 凭据顺序）、`--codex-home $CODEX_HOME 或 ~/.codex`、`--codex-bin codex`、`--deadline 55`。

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

容器外始终只有 `{session, complete_stable, routes}`。`complete_stable=true` 表示生产者收据已封口并原子发布，不再表示两次文件大小相同。routes 是全部有序 HTTP 尝试的白名单枚举或 `other`，保留重复项；两路 GPT 的每次尝试都必须分别匹配各自精确出站模型枚举 `codex:gpt-6.2-sol@chatgpt.com` 与 `codex:gpt-6.2-astra@chatgpt.com`（不绑定模型的旧 `codex@chatgpt.com` 不再放行），且 `roundtrip` 同时校验 `response.completed` 的 `response.model` 与请求模型一致。宿主继续拒绝多余字段、重复 JSON 字段、不匹配 session、自由文本和异常退出。不存在从失败收据降级回文本的路径。报告的既有 `log_found` 字段表示取得可用路由证据，不证明文本文件存在。

### 成功终态之后仍须读到 EOF

预检要求 HTTP 200、唯一的 `response.completed`、内层 `response.status=completed` 和完整 HTTP 消息。缺响应对象、`response.done`（含与 `response.completed` 混合流）、`response.incomplete`、流中任意事件（含中间事件）带非 null `error`/`response.error` 或重复终态都拦截，后续成功终态不得覆盖先前错误。收到终态后继续读完流，避免客户端提前断开而只留下 nonce 目录、不产生收据。消费者使用标准库 `HTTPResponse.read()`（不传 `amt`）验证 Content-Length / chunked 完整性，不把逐行迭代结束当作完整响应。整个 HTTP 往返在独立子进程组内执行，连接、响应头、成功体和错误体共用父进程传入的绝对工作期限。父进程通过 `run_bounded` 到期终止并 wait 回收进程组，不依赖 socket 空闲超时或成功体阶段的计时器。密钥仅通过 stdin 管道传入，stdout 仅返回固定字段的脱敏结果，stderr 不进入报告。只有 HTTP 响应体完整读完、未超总 deadline、无后续错误或冲突终态，往返检查才成功；路由检查仍独立要求完整收据和全部 attempt 通过 allowlist。终态之后一直不结束的流仍按原总 deadline 拦截。

#2055 的离线回归使用原生 Claude executor、首次 503 后重试和受控迟到的终态帧尾：客户端读终态行就断开时无收据；读完 EOF 时产生两条 Claude 路线。生产者封口条件未放宽，真实路线仍须以新正式预检的收据为证。

## 固定生产者构建与离线验证

在 `.sandcastle/deepagents-pilot` 下运行：

```sh
python3 cliproxy/build.py --docker-context colima --output /tmp/cliproxy-preflight-build-01
CLIPROXY_OFFLINE_RECEIPTS=/tmp/cliproxy-preflight-build-01/receipts \
  PYTHONPATH=../approval-signing LANGSMITH_TRACING=false LANGCHAIN_TRACING_V2=false OTEL_SDK_DISABLED=true \
  python -m pytest tests/test_review_preflight.py -q --disable-warnings
python -m ruff check --select F,E9,B,I .
```

`build.py` 使用 Python ≥ 3.12 下载固定 commit，应用 `cliproxy/preflight-v1.patch`；不复制本机配置、凭据或日志。Dockerfile 固定 Go 镜像及摘要，首次准备公开依赖需要网络，测试和 Linux 编译都使用 `RUN --network=none`。输出目录必须不存在，产物为 `cli-proxy-api`（当前构建宿主的 Linux 架构）、`version.txt`、`runtime.txt`、`go-test.txt` 和 fake 生成的 `receipts/`。构建还在 Blackhole 同款 `debian:bookworm-slim` 基础镜像内以 UID 1000、无网络运行 `--help`，确认动态链接和非 root 启动。Blackhole 现有 Dockerfile 下载官方 linux_aarch64 压缩包；主控需让其交付链使用此补丁二进制，并核对目标架构。本脚本不部署、不改 Blackhole、不加载产物到生产容器。

Go `-race` 测试包含实际 `/v1/responses` handler、原生 Kimi/Claude/Codex executor 和失败后重试；只将出站网络替换为本地 fake，分别导出双 attempt Kimi/Claude 成功收据及精确绑定出站模型的 Sol/Astra Codex 收据。Python 直接消费这些 Go 产物，验证成功路径以及别名碰撞、`other`、未收尾、正文伪造尾部的拒绝路径。未提供 `CLIPROXY_OFFLINE_RECEIPTS` 时跨语言测试会 skip，不能把这种运行报告为端到端通过。

### 生产者支持范围与完成合同

本仓 `cliproxy/preflight-v1.patch` 与 `cliproxy/build.py` 已包含原生 `CodexAutoExecutor` OAuth HTTP（`gpt-6.2-sol`、`gpt-6.2-astra`）及历史 Kimi/Claude 的可信收据支持。

- 仅在通过路由认证后、且请求满足以下两类之一时启用收据守卫，普通无标记流量原样透传（未认证请求在进入收据中间件前返回 401，绝不创建目录或写盘；若代理未配置 `CLIPROXY_PREFLIGHT_RECEIPTS`，带预检或正式独审标记的请求直接返回 503 失败闭合，绝不降级放行）：
  1. 预检：`Session-Id` 为严格 `preflight-<UUIDv4>` 的 `POST /v1/responses`，原子发布 `cliproxy-preflight-v1`；
  2. 正式独审：`X-NewChanlun-Review-Launch` 为严格 `review-<UUIDv4>` 且携带 UUID `Session-Id` 的 `POST /v1/responses` 与终态封存 `POST /v1/review-receipts/seal`（关闭无上游模型证据的 `/v1/responses/compact`）：在路由认证之后、模型路由归一化之前即从入站 JSON 提取并锁定请求模型，要求对端 TLS 证书经代理自行构造的受控 `*http.Transport` 与部署 OS 信任库标准校验匹配所记录上游主机名（不克隆 `http.DefaultTransport`，生产构建拒绝任何外部注入 transport 含 `RegisterProtocol("https", ...)`、自定义 `RootCAs`、`InsecureSkipVerify`、`ServerName`、`VerifyPeerCertificate`、`VerifyConnection`、`DialTLS`/`DialTLSContext`，离线测试 transport 经 `preflight_test_roots` 构建标签按指针显式登记、绝不编入生产二进制，流式包装器正常结束先释租约再闭通道防串行重试竞态），跨多轮原子更新 `cliproxy-review-v1` 收据（仅当上游完成响应报告的 `response.model` 与绑定模型完全一致时，才原子写入同一次完成响应的 `last_response_id_sha256`、`last_output_sha256` 与响应完成时刻 `finished_ns`，工具调用轮同步清空前轮输出摘要，不落盘自由文本），在发往插件执行器或上游前硬拦截任何路由归一化偏离、非原生 Codex OAuth HTTP、模型切换、出站/响应模型不符、TLS 对端不符、非预期端点或插件干预并永久标记 `tainted=true`（内存账本保持硬上限，未落盘的污染条目永不因空闲超时淘汰，满载且污染写盘失败时闭锁拒绝新会话与封存，污染写盘失败时同步截断删旧收据；未封存收据不予采信，须在全部在途请求结束后经已认证 `POST /v1/review-receipts/seal` 原子落盘 `sealed=true` 并保留 `finished_ns`、另记 `sealed_at_ns`，代理重启后未封存磁盘收据一律视为污染不可封存，已封存 launch 后续 `/v1/responses` 请求在路由前直接拒绝且不改写终态收据）。
- 本次固定源码仅允许具体的原生 `KimiExecutor`、`ClaudeExecutor`、`AntigravityExecutor`（仅预检）以及限定为原生 OAuth HTTP（非 API key、非上下游 WebSocket）且目标模型为 `gpt-6.2-sol` 或 `gpt-6.2-astra` 的 `CodexAutoExecutor`，不靠可冒名的 `Identifier()` 判覆盖。对于 Codex，收据在 HTTP `RoundTrip` 边界解码出站请求体（明文 / `zstd` / `gzip`，上限 32 MiB）并校对发往 `https://chatgpt.com/backend-api/codex/responses` 的 JSON 顶层唯一 `"model"` 字段与执行模型一致、且 `resp.TLS` 已完成握手并经证书链核验匹配 `chatgpt.com` 后，才记录 `codex:gpt-6.2-sol@chatgpt.com` 或 `codex:gpt-6.2-astra@chatgpt.com`，否则记 `other`（正式独审直接拒绝上游请求并永久污染收据）。插件 executor、未列模型、count-tokens、compact、裸 `HttpRequest`、非标准自定义 RoundTripper、WebSocket/其他入口不在本补丁支持范围，不能得到成功证明。
- 默认空插件宿主可用；活跃插件或请求期间插件快照变化使证据失效。原生标准 HTTP transport 保留原 TLS、代理和连接池策略。收据记录 HTTP `RoundTrip` 边界的 provider 与请求 authority，不声称证明代理后的物理出口 IP；底层 TCP 重传不作为另一个模型请求。OAuth 刷新不是模型尝试。
- collector 从入站头绑定 nonce 与服务端起点，并跨 handler bootstrap 重试共享。全部 Manager 执行调用经过同一 guard；没有任何被观察 HTTP 传输的执行也拒绝证明。传输开始前分配全局序号，失败请求、重定向及重复路线不去重。只存固定枚举，不存正文、URL 路径、auth_id、token 或错误字符串。
- 成功发布要求：HTTP handler 成功结束、请求 lifecycle 成功、所有执行租约结束、全部响应体关闭、至少一个尝试、没有覆盖缺口。最多 64 次传输、50 秒生命周期，超限失败闭合。流式执行在上游 channel 关闭前持有租约；正文里的 `=== RESPONSE ===` 或 `API REQUEST 99` 不参与判定。
- 每个 nonce 在认证后的受支持执行开始时才用独占目录预留，未认证请求不写磁盘，重复请求不覆盖；请求间 collector 独立，同请求并发尝试用锁编号。完成后先写同目录 `pending`、sync/close，再 rename 为 `receipt.json`。读取者只认最终文件；半写、崩溃、错误状态、读取超时、过期时间或缺字段都没有证明。收据不做持久恢复，重启丢失可以拒绝；不会补造成功。旧收据也不能匹配新 UUID。目录不自动删除，部署方可在无活动预检时清理整个专用临时目录；禁止把它配置成原状态卷目录。

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
| `checkout_root_container_mount` | 正式命名卷灌入、属主设置或只读挂载不可用 | 在 checkout_root 写一次性 nonce，按正式 worker 同一命名卷路径（`volume create` → `create`/`docker cp`/`chown` → `--network none --read-only --user uid:gid -v <vol>:/review:ro`）读回；不依赖宿主目录共享。探针目录、容器与临时卷随即删除，删不掉报 `probe_cleanup`；`docker create`/`run` 超时或退出 125 时也报 `probe_cleanup`（回收未确认）。所有 Docker 子进程均剥离 `DOCKER_HOST`、`DOCKER_CONFIG` 与 `CLIPROXY_LOCAL_KEY` |
| `route:<model>` | 旧会话被派到非预期上游或两别名撞同模型 | 两位 GPT 分别要求每次尝试有可信收据且精确匹配 `codex:gpt-6.2-sol@chatgpt.com` / `codex:gpt-6.2-astra@chatgpt.com`；不绑定模型的旧 `codex@chatgpt.com`、旧文本和缺收据都拦截 |
| `roundtrip:<model>` / `seal:<model>` | 上游 400、响应不完整、响应模型不符、重定向、容器代理不可达或宿主封存端点指向另一实例 | 每位一次最小 `/v1/responses` 往返（正式调用加 `--probe-in-container` 与 `--review-seal-url http://127.0.0.1:8318/v1/review-receipts/seal`，在审阅容器内以 `--read-only` 经 `stdin` 传密钥带正式 `X-NewChanlun-Review-Launch` 请求 `http://host.docker.internal:8318`，再由宿主在有界进程组内调用封存端点并读回已封存 `cliproxy-review-v1` 收据）；禁用 HTTP 重定向与环境代理，要求 HTTP 200、唯一完成终态、内层完成且 `response.model` 与请求模型一致、全流无错误、HTTP 消息完整读完 |
| `credential:codex-host` / `credential:worker-env` | #1323 宿主或正式 worker 缺 `CLIPROXY_LOCAL_KEY` | 默认 `codex-host` 去掉 `CLIPROXY_LOCAL_KEY` 后按 `$CODEX_HOME/config.toml` 取 key 并离线跑 `codex features list`；控制器正式调用使用 `--credential-mode worker-env`，按正式 worker 同一顺序取进程 `CLIPROXY_LOCAL_KEY` 或 macOS `launchctl getenv CLIPROXY_LOCAL_KEY`，两家往返都用这把 key |

模型探测每家只发一次、提示极短（effort=low），这是预检唯一的模型花费。

## 时限与回收

所有子进程（git、`auth.command`、docker、HTTP 往返）只经过一个有界原语 `run_bounded` 启动：独立进程组、最多等给定秒数、返回前无论成败都杀掉整个进程组（包装脚本留在后台的子进程一并结束）。时间只有一个来源 `Deadline`：检查用到总时限减 min(3 秒, 总时限/2)，余下留给 `docker rm -f` 与输出报告。两次往返在线程里与空间、挂载检查并行。HTTP 进程启动时间计入原工作期限；到期先终止并回收进程，再返回失败。`run_checks` 的正常和异常出口均等待本次探测线程完成回收，不留下活动 HTTP worker，也不靠 daemon 或 `os._exit` 跳过清理。

不要把 effort 降到 `minimal`：2026-11-05 实测 Sol 在 `minimal` 下返回 400（codex 后端注入的 `image_gen` 工具不能与 `minimal` 同用），预检会因此误报。旧实现等待 request-log 落盘再判定的方式已撤回；文本入口立即返回无可信证据。新收据入口等待原子发布，其读取与子进程收尾不得越过工作期限。

## 局限

- 预检是某一时刻的快照。CLIProxy 是 fill-first + 会话亲和，正式 attempt 的新会话仍可能在几秒后被选到别的凭据；预检只核本次路线；它不能替代实际发审后的模型与会话证据。
- JSON 围栏类失败需要真实模型完整输出才能复现，预检不覆盖。
- 以下检查没有对应的真实失败，已移出本版、留作后续单独 PR：正式 worker 的 key 来源（进程环境 / launchctl）、实际服务模型（Claude fallback 到 4.8）、CLIProxy `request-log` 开关、目标 commit 缺失时的 `needs_source_sync`、空间不足时 VM 持有已删除文件的诊断、宿主 `base_url` 与预检代理是否同一端点。

## 测量

拦截率与误报按冻结语料在隔离环境注入同样故障测得：小容量卷模拟 HOME、VM 内同名空目录、本地假 proxy 返回同样的 400、修前形态的 Codex provider 配置。不碰共享 proxy 与真实账号。结果见 PR 描述。
