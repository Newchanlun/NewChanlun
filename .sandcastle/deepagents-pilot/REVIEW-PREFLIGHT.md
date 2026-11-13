# #1742：正式独审 attempt 的启动前预检

**当前阻断：CLIProxy v8.0.63 文本日志不能提供可信路由证明。宿主与容器入口均返回无证明，正式预检不会放行。恢复依赖见“可信证据缺口”。**

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

两种入口保留参数与报告合同，但 `_review_preflight_log.py` 不再解析现有文本。宿主返回 `None`；容器返回 `{"session": "<本次session>", "complete_stable": false, "routes": []}`。宿主据此报告 `route:<model>.ok=false`、`actual=[]`、`log_found=false`。这里的 `log_found` 表示未取得可用证据，不证明文件不存在。未知真实路线不能凭文本猜测为 `other`；`other` 仍是协议中未知路线的唯一允许枚举。

容器协议消费端继续校验精确字段集合、session、布尔完成状态和路线白名单，保留全部有序尝试；任何失败不退回宿主目录读取。原始日志、URL 路径、auth_id、Docker stdout/stderr 自由文本都不进报告。容器任务仍受总工作预算与自身到期退出约束，不创建文件、挂载或容器。此版本不会读取代理日志内容。

## 可信证据缺口

核查版本为 Blackhole Dockerfile 固定的 CLIProxy `v8.0.63`，公开源码提交 `6db7d4b839d86c5b24e17bbe73bcd4db18ef1b1a`：

- [logging_helpers.go:175–190](https://github.com/router-for-me/CLIProxyAPI/blob/6db7d4b839d86c5b24e17bbe73bcd4db18ef1b1a/internal/runtime/executor/helps/logging_helpers.go#L175-L190) 写文本段头与 `Body:`；[同文件:247–288](https://github.com/router-for-me/CLIProxyAPI/blob/6db7d4b839d86c5b24e17bbe73bcd4db18ef1b1a/internal/runtime/executor/helps/logging_helpers.go#L247-L288) 将响应 chunk 原样追加，未转义正文中的段头，也没有正文长度帧。
- [request_logger_format.go:127–166](https://github.com/router-for-me/CLIProxyAPI/blob/6db7d4b839d86c5b24e17bbe73bcd4db18ef1b1a/internal/logging/request_logger_format.go#L127-L166) 原样复制请求正文；空行分隔并不排除正文含相同空行与段头。
- [request_logger_streaming.go:242–258](https://github.com/router-for-me/CLIProxyAPI/blob/6db7d4b839d86c5b24e17bbe73bcd4db18ef1b1a/internal/logging/request_logger_streaming.go#L242-L258) 直接创建最终文件再写入，不是写完后原子发布；[同文件:306–333](https://github.com/router-for-me/CLIProxyAPI/blob/6db7d4b839d86c5b24e17bbe73bcd4db18ef1b1a/internal/logging/request_logger_streaming.go#L306-L333) 先写全部 API REQUEST，再写全部 API RESPONSE，最后写 RESPONSE。旧 fake 的交错排列不是该版本的完整布局。

因此正文可生成与结构相同的字节；稳定文件也可能是写入暂停或失败的前缀。正则、编号连续性、末尾段头、两次大小稳定都不能证明完整性或来源。两个独审反例分别伪造最终 RESPONSE 并留下未闭合第二次尝试，以及在响应正文注入 API REQUEST 99。正常多 attempt 文本同样缺少可信完成证据，当前也必须拦截。

**最小恢复路径由代理生产者提供，与正文分离。** 在代理内部收集本次 session 的实际路由尝试，在请求生命周期结束、尝试列表冻结后原子发布一条结构化记录，至少包含版本、session、请求标识/起点、完成状态、attempt 总数及有序 provider/hostname 枚举。记录不得携带正文、URL 路径或 auth_id；不从现有文本重新解析生成。发布失败或记录不完整就没有证明。可以由代理自身提供窄只读接口，或在原状态卷中原子发布、仍仅在代理容器内读取，不扩大挂载权限。

上述生产者改动不在本 PR 的四文件 scope 内，尚未实现或部署。主控需先落实该可信来源及其原子完成合同，再接入当前白名单协议并重新独审。不得手工编造记录、mock 正式预检或跳过操作门恢复生产。当前交付只消除错误放行，未恢复生产部署验收。

## 检查什么

每项检查对应一次真实发生过的正式 attempt 启动失败。

| 检查 | 拦下的真实失败 | 做法 |
|---|---|---|
| `checkout_root_free_space` | PR1866 A1/A2、PR1868 A3（f9）：快照需 2.60GB，HOME 只剩 1.40–1.65GB | 逐字节复刻 `prepare_review` 的快照字节公式，要求 checkout_root 所在卷剩余 ≥ 2 份（两位 reviewer） |
| `checkout_root_container_mount` | PR1868 A1：checkout 在未共享进 colima 的路径，容器里看到的是 VM 本地空目录 | 在 checkout_root 写一次性 nonce，用审阅镜像 `--network none --read-only` 只读 bind 挂载 checkout_root 读回；读不到或不一致即拦。探针目录与容器随即删除，删不掉报 `probe_cleanup`；`docker run` 超时或 docker 自身出错（退出 125）时，daemon 可能在 `rm -f` 之后才建出容器，也报 `probe_cleanup`（回收未确认） |
| `route:<model>` | PR1883 A1：claude-opus-5-5 新会话被选到 Antigravity | 当前拒绝文本日志证明，因此始终拦截；未来可信来源的每次尝试仍要求 Sol=`codex@chatgpt.com`，Kimi=`kimi@api.kimi.com` 或 `kimi-ai@api.kimi.ai`（CLIProxy 在国内、国际两个上游间切换），Opus=`claude@api.anthropic.com`；只探测 `external_review.MODELS` 当前的两位。找不到日志也拦 |
| `roundtrip:<model>` | 同上，上游 400 `tool_choice ... not supported` | 每家一次最小 `/v1/responses` 往返，带 tools、`tool_choice=auto`、JSON 输出格式、新会话，必须读到 `response.completed`/`incomplete` |
| `credential:codex-host` | #1323：宿主缺 `CLIPROXY_LOCAL_KEY`，回合在调模型前报 `Missing environment variable` | 去掉该环境变量后，按 `$CODEX_HOME/config.toml` 的 `model_providers.cliproxy-local` 取 key（`auth.command` / `env_key`）。provider 配置是否合法以宿主自己的 codex 为准：先离线跑一次 `codex features list`（约 50ms，不发请求），Codex 拒绝加载就拦（如 `auth` 与 `env_key` 并存），报告只取 Codex 报错里的字段名。两家往返都用这把 key，所以通过即证明没有该变量时 provider 也能完成往返 |

模型探测每家只发一次、提示极短（effort=low），这是预检唯一的模型花费。

## 时限与回收

所有子进程（git、`auth.command`、docker）只经过一个有界原语 `run_bounded` 启动：独立进程组、最多等给定秒数、返回前无论成败都杀掉整个进程组（包装脚本留在后台的子进程一并结束）。时间只有一个来源 `Deadline`：检查用到总时限减 min(3 秒, 总时限/2)，余下留给 `docker rm -f` 与输出报告。两次往返不留本地产物，在守护线程里与空间、挂载检查并行，到时未完成即判失败。

不要把 effort 降到 `minimal`：2026-11-05 实测 Sol 在 `minimal` 下返回 400（codex 后端注入的 `image_gen` 工具不能与 `minimal` 同用），预检会因此误报。旧实现等待 request-log 落盘再判定的方式已撤回；当前文本入口立即返回无可信证据。容器协议读取的预算仍不得越过工作期限。

## 局限

- 预检是某一时刻的快照。CLIProxy 是 fill-first + 会话亲和，正式 attempt 的新会话仍可能在几秒后被选到别的凭据；路由的根治在共享 proxy 配置（当前已用 `oauth-excluded-models.antigravity` 排除两个 Claude 模型），预检只负责发现回归。
- JSON 围栏类失败需要真实模型完整输出才能复现，预检不覆盖。
- 以下检查没有对应的真实失败，已移出本版、留作后续单独 PR：正式 worker 的 key 来源（进程环境 / launchctl）、实际服务模型（Claude fallback 到 4.8）、CLIProxy `request-log` 开关、目标 commit 缺失时的 `needs_source_sync`、空间不足时 VM 持有已删除文件的诊断、宿主 `base_url` 与预检代理是否同一端点。

## 测量

拦截率与误报按冻结语料在隔离环境注入同样故障测得：小容量卷模拟 HOME、VM 内同名空目录、本地假 proxy 返回同样的 400、修前形态的 Codex provider 配置。不碰共享 proxy 与真实账号。结果见 PR 描述。
