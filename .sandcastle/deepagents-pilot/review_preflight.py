#!/usr/bin/env python3
"""#1742 正式独审 attempt 的启动前预检。只报告环境能否启动，不是审阅结果。

每项检查对应一种真实发生过的启动失败（对照表见 REVIEW-PREFLIGHT.md）：
  checkout_root_free_space       PR1866 A1/A2、PR1868 A3：双快照空间不足
  checkout_root_container_mount  PR1868 A1：容器里看到的 checkout_root 是空的
  route / roundtrip              PR1883 A1：Opus 被路由到 Antigravity，tool_choice=auto 上游 400
  credential:codex-host          #1323：宿主进程缺 CLIPROXY_LOCAL_KEY
"""
import argparse
import hashlib
import http.client
import importlib.util
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import tomllib

# 与 pilot1742.external_review.SPACE_RESERVE 相同；预检不导入控制器，避免改变其加载面。
SPACE_RESERVE = 256 * 1024 * 1024
# 与 pilot1742.external_review.MODELS 相同（测试核对）。
MODELS = ("kimi-k3.1-pro", "claude-opus-5-5")
CLIPROXY_LOG_DIR = Path.home() / "Library/Application Support/CLIProxyLocal/auth/logs"
# 每个模型可接受的上游路线。Sol 走 Codex OAuth（chatgpt.com）；Kimi 走国内 kimi（api.kimi.com）或国际 kimi-ai
# （api.kimi.ai），CLIProxy 在两者间按同型号候选池切换（CLIProxyLocal ROUTING-KIMI-1696.md）；Opus 走 Claude OAuth。
ROUTES = {"gpt-6.1-sol": {("codex", "chatgpt.com")},
          "gpt-6.2-sol": {("codex:gpt-6.2-sol", "chatgpt.com")},
          "gpt-6.2-astra": {("codex:gpt-6.2-astra", "chatgpt.com")},
          "kimi-k3.1-pro": {("kimi", "api.kimi.com"), ("kimi-ai", "api.kimi.ai")},
          "claude-opus-5-5": {("claude", "api.anthropic.com")}}
# 报告里只回显这些已知路由，其余记作 "other"：日志字段来自上游，不能原样进报告
KNOWN_ROUTES = {*(route for routes in ROUTES.values() for route in routes),
                ("antigravity", "daily-cloudcode-pa.googleapis.com")}
PROVIDER = "cliproxy-local"
SCRUBBED_ENV = "CLIPROXY_LOCAL_KEY"
SHA_RE = re.compile(r"[0-9a-f]{40}")
RESPONSE_STATUSES = ("completed", "incomplete", "failed", "cancelled", "canceled", "in_progress", "queued")
CLEANUP_RESERVE = 3.0  # 总时限里留给回收与输出报告的秒数
OUTPUT_MARGIN = 0.5  # 回收之后杀进程组、删目录、输出报告所留的秒数（机器忙时也够）
# 上游错误只按固定词表分类，不把原文抄进报告（原文可能回显 key，且转义形态无法穷举）
ERROR_CLASSES = (("tool_choice", "tool_choice_unsupported"), ("预扣额度", "quota"), ("quota", "quota"),
                 ("insufficient", "quota"), ("invalid api key", "auth"), ("invalid bearer", "auth"), ("unauthorized", "auth"),
                 ("authentication", "auth"), ("rate limit", "rate_limit"), ("overloaded", "overloaded"),
                 ("model_not_found", "model_not_found"), ("not supported", "unsupported"))


TERMINAL_EVENTS = ("response.completed", "response.done", "response.incomplete", "response.failed", "response.cancelled", "response.canceled", "error")
CREDENTIAL_SOURCES = ("auth.command", "experimental_bearer_token", "env_key")
# 报告协议词表：字段名与枚举值都由本脚本写死、与 key 无关，原样输出不透露 key 的任何信息。
# 合法 key 可以是任意可见 ASCII（如 "ok"），与它们相同或是其子串时，脱敏也不能改写它们（调用方按字段与枚举读结论）。
PROTOCOL_FIELDS = frozenset({
    "kind", "is_review_result", "ready", "checks", "wall_seconds", "usage", "usage_error",
    "name", "class", "ok", "detail",
    "checkout_root", "free_bytes", "required_bytes", "per_snapshot_bytes", "snapshots",
    "image", "nonce_match", "docker_rc", "stderr",
    "scrubbed_env", "source", "proven_by", "error",
    "expected", "actual", "log_found", "session",
    "http_status", "terminal", "status", "length", "sha256_12", "exception", "errno", "not_sent"})
PROTOCOL_VALUES = frozenset({
    "review-preflight", "review-preflight-help",
    "checkout_root_free_space", "checkout_root_container_mount", "credential:codex-host", "probe_cleanup",
    "preflight_internal", *(f"{kind}:{model}" for kind in ("route", "roundtrip") for model in MODELS),
    "space", "mount", "credential", "route", "roundtrip", "cleanup", "tool",
    *TERMINAL_EVENTS, *RESPONSE_STATUSES, "other", *(label for _, label in ERROR_CLASSES), "unclassified",
    *(f"{provider}@{host}" for provider, host in KNOWN_ROUTES), *CREDENTIAL_SOURCES})


class Deadline:
    """一次预检的唯一时间来源：检查用到 work，回收与输出用到 total。"""

    def __init__(self, seconds: float):
        self.total = time.monotonic() + seconds
        self.work = self.total - min(CLEANUP_RESERVE, seconds / 2)

    def work_left(self) -> float:
        return max(0.0, self.work - time.monotonic())

    def total_left(self) -> float:
        return max(0.0, self.total - time.monotonic())


def run_bounded(cmd: list[str], timeout: float, *, data: bytes | None = None,
                env: dict | None = None, deadline: Deadline | None = None) -> subprocess.CompletedProcess:
    """预检里唯一的子进程原语：在独立进程组里运行，最多等 timeout 秒（超时抛 TimeoutExpired）；
    无论成败，返回前都杀掉整个进程组，包装脚本留下的后台子进程也一并结束。"""
    if timeout <= 0:
        raise subprocess.TimeoutExpired(cmd, 0)
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE if data is not None else subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, start_new_session=True)
    try:
        out, err = proc.communicate(data, timeout=min(timeout, deadline.work_left()) if deadline else timeout)
    finally:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:  # 组内已无进程
            pass
        proc.wait()
        for stream in (proc.stdin, proc.stdout, proc.stderr):
            if stream:
                stream.close()
    return subprocess.CompletedProcess(cmd, proc.returncode, out, err)


def git_environment() -> dict[str, str]:
    """与 external_review.git_environment 相同：不读系统/全局配置、不跟随 replace 引用。"""
    env = {k: os.environ[k] for k in ("PATH", "LANG", "LC_ALL", "TMPDIR") if k in os.environ}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT="0",
               GIT_OPTIONAL_LOCKS="0", GIT_NO_REPLACE_OBJECTS="1")
    return env


def snapshot_bytes(source: Path, base: str, head: str, merge_base: str, deadline: Deadline | None = None) -> int:
    """单个模型审阅快照的所需字节，逐项复刻 external_review.prepare_review 的公式。"""
    deadline = deadline or Deadline(60)

    def git(*args: str, data: bytes | None = None) -> bytes:
        result = run_bounded(["git", "-C", str(source), *args], deadline.work_left(), data=data, env=git_environment())
        if result.returncode:
            raise subprocess.CalledProcessError(result.returncode, result.args)
        return result.stdout

    objects = {line.split(b" ", 1)[0] for line in git("rev-list", "--objects", "--no-walk", base, head, merge_base).splitlines()}
    objects.update(git("rev-list", base, head).splitlines())
    sizes = git("cat-file", "--buffer", "--batch-check=%(objectsize)", data=b"\n".join(sorted(objects)) + b"\n").splitlines()
    worktree = sum(int(line.split(b"\t", 1)[0].split()[-1]) for line in git("ls-tree", "-rl", head).splitlines()
                   if line.split()[1] == b"blob")
    return sum(int(size) for size in sizes) + worktree + SPACE_RESERVE


def check_space(args, deadline: Deadline) -> dict:
    per = snapshot_bytes(Path(args.source), args.base, args.head, args.merge_base, deadline)
    need = per * len(MODELS)
    existing = Path(args.checkout_root).absolute()
    while not existing.exists():
        existing = existing.parent
    free = shutil.disk_usage(existing).free
    return {"name": "checkout_root_free_space", "class": "space", "ok": free >= need,
            "detail": {"required_bytes": need, "per_snapshot_bytes": per, "snapshots": len(MODELS), "free_bytes": free}}


def check_mount(args, deadline: Deadline) -> tuple[dict, list[str]]:
    """宿主写一次性 nonce，审阅镜像经同样的只读 bind 挂载 checkout_root 读回；读不到即容器看见的不是真实文件。
    返回 (检查结果, 回收失败列表)。"""
    root = Path(args.checkout_root).absolute()  # docker bind 只接受绝对路径
    nonce = os.urandom(16).hex()
    container = f"preflight-{nonce[:16]}"
    probe = root / container
    detail: dict = {"checkout_root": str(root), "image": args.image}
    ok, cleanup, docker_called, container_done = False, [], False, False
    try:
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        probe.mkdir(mode=0o700)
        (probe / "nonce").write_text(nonce)
        docker_called = True
        # 与正式审阅容器相同，以宿主 uid:gid 运行（docker-isolation.mts）：探针目录是 0700，镜像用户与宿主不同时
        # 不带 --user 会因 EACCES 误拦健康环境
        result = run_bounded([*docker_command(getattr(args, "review_docker_context", None)), "run", "--rm", "--name", container, "--network", "none", "--read-only",
                              "--user", f"{os.getuid()}:{os.getgid()}",
                              "--mount", f"type=bind,src={root},dst=/checkouts,readonly",
                              "--entrypoint", "cat", args.image, f"/checkouts/{container}/nonce"],
                             deadline.work_left())  # 只受总工作时限约束，不另设固定上限
        seen = result.stdout.decode("utf-8", "replace").strip()
        # docker 约定：125 是 docker 自身出错（容器可能没跑完）；其余退出码来自容器里的命令，容器已跑完、--rm 已删
        container_done = result.returncode >= 0 and result.returncode != 125
        ok = result.returncode == 0 and seen == nonce
        detail.update(docker_rc=result.returncode, nonce_match=seen == nonce,
                      # daemon/registry 的自由文本不进报告，与上游错误正文同样只给分类、长度、摘要
                      stderr=_error_info(result.stderr.decode("utf-8", "replace").strip()))
    except subprocess.TimeoutExpired:
        detail["error"] = "docker run 超时"
    except Exception as error:
        detail["error"] = type(error).__name__
    finally:
        # docker run 被杀或非 0 退出时容器可能已建，--rm 不会清：总是 rm -f（容器不存在时也返回 0）。
        try:
            removed = run_bounded([*docker_command(getattr(args, "review_docker_context", None)), "rm", "-f", container], deadline.total_left() - OUTPUT_MARGIN)
            if removed.returncode:
                cleanup.append(f"docker rm -f {container} 退出 {removed.returncode}")
        except (OSError, subprocess.TimeoutExpired) as error:
            cleanup.append(f"docker rm -f {container} {type(error).__name__}")
        if docker_called and not container_done:
            # 客户端超时被杀或 docker 自身出错时，daemon 可能已收下创建请求并在 rm -f 之后才建出容器：如实报未确认
            cleanup.append(f"docker run 未正常结束，daemon 可能稍后仍建出容器 {container}；请稍后 docker rm -f {container} 确认")
        shutil.rmtree(probe, ignore_errors=True)
        if probe.exists():
            cleanup.append(f"探针目录 {probe} 未删净")
    return {"name": "checkout_root_container_mount", "class": "mount", "ok": ok, "detail": detail}, cleanup


class CredentialError(RuntimeError):
    pass


def _clean_key(value, source: str) -> str:
    """去掉首尾空白；只接受可见 ASCII（0x21–0x7E）的 key（HTTP 头安全）。不设长度或字符子集门槛——
    正式 worker 不设，预检多设就是误报；短 key、含转义的 key 由脱敏形态覆盖。不回显值。"""
    if not isinstance(value, str):
        raise CredentialError(f"{source} 的 key 不是字符串")
    key = value.strip()
    if not key:
        raise CredentialError(f"{source} 的 key 为空")
    if any(not 0x21 <= ord(ch) <= 0x7E for ch in key):
        raise CredentialError(f"{source} 的 key 含非可见 ASCII 字符")
    return key


def codex_accepts_config(codex_bin: str, codex_home: Path, env: dict, deadline: Deadline) -> None:
    """让宿主自己的 codex 离线加载这份配置（`codex features list`，约 50ms、不发请求）：
    provider/auth 字段组合与取值以 Codex 为准，预检不再自己抄一份校验规则。"""
    try:
        result = run_bounded([codex_bin, "features", "list"], deadline.work_left(), env=env)
    except subprocess.TimeoutExpired:
        raise CredentialError("codex 加载配置超时") from None
    except OSError as error:
        raise CredentialError(f"无法运行 codex（{type(error).__name__}）") from None
    if result.returncode != 0:
        # 只取 Codex 报错里的字段名，其余文本可能含配置取值，不进报告
        stderr = result.stderr.decode("utf-8", "replace")
        field = re.search(r"cannot be combined with ([A-Za-z_]+)", stderr)
        reason = f"provider auth cannot be combined with {field.group(1)}" if field else "配置无效"
        raise CredentialError(f"Codex 拒绝加载该配置（退出 {result.returncode}）：{reason}")


def provider_key(codex_home: Path, deadline: Deadline, codex_bin: str = "codex") -> tuple[str, str]:
    """按 Codex 宿主的 provider 配置取 key，且进程环境去掉 CLIPROXY_LOCAL_KEY（#1323 宿主就缺这个变量）。"""
    # 校验与 auth.command 用同一个环境：去掉 CLIPROXY_LOCAL_KEY、CODEX_HOME 指向被检查的配置目录
    env = {**{k: v for k, v in os.environ.items() if k != SCRUBBED_ENV}, "CODEX_HOME": str(codex_home)}
    codex_accepts_config(codex_bin, codex_home, env, deadline)
    path = codex_home / "config.toml"
    if not path.is_file():  # FIFO 等特殊文件读起来会无界阻塞
        raise CredentialError("Codex config.toml 不是普通文件")
    try:
        config = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise CredentialError(f"读不到或解析不了 Codex config.toml（{type(error).__name__}）") from None
    providers = config.get("model_providers")
    entry = providers.get(PROVIDER) if isinstance(providers, dict) else None
    if not isinstance(entry, dict):
        raise CredentialError(f"{codex_home}/config.toml 没有 model_providers.{PROVIDER}")
    auth = entry.get("auth")
    if isinstance(auth, dict) and auth.get("command"):
        command, args, timeout_ms = auth["command"], auth.get("args", []), auth.get("timeout_ms", 5000)
        if (not isinstance(command, str) or not isinstance(args, list) or not all(isinstance(a, str) for a in args)
                or isinstance(timeout_ms, bool) or not isinstance(timeout_ms, int | float) or timeout_ms <= 0):
            raise CredentialError("model_providers.auth 的 command/args/timeout_ms 类型无效")
        timeout = min(timeout_ms / 1000, deadline.work_left())
        try:
            result = run_bounded([command, *args], timeout, env=env)
        except subprocess.TimeoutExpired:
            raise CredentialError(f"auth.command 超过 {timeout:g}s 未返回") from None
        except OSError as error:
            raise CredentialError(f"auth.command 无法执行（{type(error).__name__}）") from None
        if result.returncode != 0:
            raise CredentialError(f"auth.command 退出 {result.returncode}")
        return _clean_key(result.stdout.decode("utf-8", "replace"), "auth.command"), "auth.command"
    if entry.get("experimental_bearer_token"):
        return _clean_key(entry["experimental_bearer_token"], "experimental_bearer_token"), "experimental_bearer_token"
    if entry.get("env_key"):
        if not isinstance(entry["env_key"], str) or not env.get(entry["env_key"]):
            # 只回显已知变量名：误填的 key 本身也可能长得像变量名
            name = SCRUBBED_ENV if entry["env_key"] == SCRUBBED_ENV else "<配置的 env_key，不回显>"
            raise CredentialError(f"Missing environment variable: {name}")
        return _clean_key(env[entry["env_key"]], "env_key"), "env_key"
    raise CredentialError(f"model_providers.{PROVIDER} 未配置任何凭据来源")


def check_credential(args, deadline: Deadline) -> tuple[dict, str | None]:
    detail: dict = {"scrubbed_env": SCRUBBED_ENV}
    try:
        key, detail["source"] = provider_key(Path(args.codex_home), deadline, args.codex_bin)
    except CredentialError as error:
        key, detail["error"] = None, str(error)
    else:
        detail["proven_by"] = "两家 roundtrip 都用这把 key"
    return {"name": "credential:codex-host", "class": "credential", "ok": key is not None, "detail": detail}, key


def _secret_forms(secrets) -> list[str]:
    forms = set()
    for secret in secrets:
        if not secret:
            continue
        forms.add(secret.encode("utf-8", "surrogateescape").decode("utf-8", "replace"))
        try:  # key 里的 \uXXXX 之类转义被上游 JSON/TOML 解码后的形态
            decoded = json.loads(f'"{secret}"')
            if isinstance(decoded, str):
                forms.add(decoded)
        except ValueError:
            pass
        forms.update({secret, json.dumps(secret, ensure_ascii=False)[1:-1], json.dumps(secret)[1:-1],
                      repr(secret)[1:-1], secret.strip()})
    # 不按长度过滤：短 key 宁可过度脱敏也不漏（报告里已不含上游原文，剩下的几乎都是本脚本自己的文字）
    return sorted((f for f in forms if f), key=len, reverse=True)


def redact(text: str, secrets, limit: int | None = None) -> str:
    """抹掉 key 的各种形态（原文、JSON/repr 转义），长者优先；再截断，并清掉截断处残留的 key 前缀。"""
    if isinstance(secrets, str) or secrets is None:
        secrets = [secrets]
    forms = _secret_forms(secrets)
    for form in forms:
        text = text.replace(form, "<redacted>")
    if limit is not None and len(text) > limit:
        text = text[:limit]
        # 只有真的截断了，末尾才可能残留 key 前缀；未截断的协议字段不动。
        tail = max((k for form in forms for k in range(len(form) - 1, 1, -1) if text.endswith(form[:k])), default=0)
        if tail:
            text = text[:-tail] + "<redacted>"
    return text


def sanitize(value, secrets, limit: int = 500):
    """对报告逐字段脱敏后截断；在序列化之前做，保证输出仍是合法 JSON。"""
    if isinstance(value, dict):
        return {k if k in PROTOCOL_FIELDS else redact(str(k), secrets, limit): sanitize(v, secrets, limit)
                for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize(v, secrets, limit) for v in value]
    if isinstance(value, str):
        return value if value in PROTOCOL_VALUES else redact(value, secrets, limit)
    return value


def _error_info(body: str) -> dict:
    """上游错误正文只给长度、sha256 前 12 位与固定词表分类，不抄原文。"""
    lowered = body.lower()
    kind = next((label for needle, label in ERROR_CLASSES if needle in lowered), "unclassified")
    return {"class": kind, "length": len(body), "sha256_12": hashlib.sha256(body.encode("utf-8", "replace")).hexdigest()[:12]}


def round_trip(url: str, key: str, model: str, session: str, deadline: Deadline) -> dict:
    """整个 HTTP 请求在独立进程组中运行，绝对工作期限到达后先回收再返回。"""
    if deadline.work_left() <= 0:
        return {"http_status": None, "terminal": None, "ok": False, "error": {"not_sent": "总时限已到"}}
    try:
        result = run_bounded(
            [sys.executable, "-I", str(Path(__file__).resolve()), "--http-worker"],
            deadline.work_left(), deadline=deadline,
            data=json.dumps([url, key, model, session, deadline.work, deadline.total]).encode())
        if result.returncode:
            raise RuntimeError("HTTP worker failed")
        return json.loads(result.stdout)
    except Exception as error:
        return {"http_status": None, "terminal": None, "ok": False,
                "error": {"exception": type(error).__name__, "errno": None}}


_SSE_EVENT_SCHEMA_KEYS = frozenset({
    "type", "response_id", "model", "error", "response", "message",
    "item", "item_id", "output_index", "content_index", "text", "delta", "refusal", "part",
    "arguments", "input", "code", "name", "call_id",
})
_SSE_RESPONSE_SCHEMA_KEYS = frozenset({"id", "model", "status", "error", "output"})
_SSE_ITEM_SCHEMA_KEYS = frozenset({
    "id", "type", "role", "phase", "status", "content", "response_id",
    "call_id", "name", "server_label", "arguments", "input", "code", "action", "queries",
})
_SSE_CONTENT_PART_SCHEMA_KEYS = frozenset({"type", "text", "refusal"})


def _no_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    out: dict[str, object] = {}
    for key, value in pairs:
        if key in out:
            raise ValueError("duplicate JSON key")
        out[key] = value
    return out


def _check_canonical_schema_keys(obj: object, schema_keys: frozenset[str]) -> None:
    if not isinstance(obj, dict):
        return
    seen_lower: set[str] = set()
    for key in obj:
        lower = key.lower()
        if lower in seen_lower:
            raise ValueError(f"case-duplicate protocol JSON key: {key}")
        if key != lower and lower in schema_keys:
            raise ValueError(f"non-canonical protocol key case: {key}")
        seen_lower.add(lower)


def _validate_sse_protocol_key_casing(event: object) -> None:
    if not isinstance(event, dict):
        return
    _check_canonical_schema_keys(event, _SSE_EVENT_SCHEMA_KEYS)
    resp = event.get("response")
    if isinstance(resp, dict):
        _check_canonical_schema_keys(resp, _SSE_RESPONSE_SCHEMA_KEYS)
        output = resp.get("output")
        if isinstance(output, list):
            for item in output:
                if isinstance(item, dict):
                    _check_canonical_schema_keys(item, _SSE_ITEM_SCHEMA_KEYS)
                    content = item.get("content")
                    if isinstance(content, list):
                        for part in content:
                            _check_canonical_schema_keys(part, _SSE_CONTENT_PART_SCHEMA_KEYS)
    item = event.get("item")
    if isinstance(item, dict):
        _check_canonical_schema_keys(item, _SSE_ITEM_SCHEMA_KEYS)
        content = item.get("content")
        if isinstance(content, list):
            for part in content:
                _check_canonical_schema_keys(part, _SSE_CONTENT_PART_SCHEMA_KEYS)
    part = event.get("part")
    if isinstance(part, dict):
        _check_canonical_schema_keys(part, _SSE_CONTENT_PART_SCHEMA_KEYS)


def _reject_json_constant(token: str) -> object:
    raise ValueError(f"non-JSON constant: {token}")


def _contains_surrogate(value: object) -> bool:
    if isinstance(value, str):
        return any(0xD800 <= ord(ch) <= 0xDFFF for ch in value)
    if isinstance(value, list):
        return any(_contains_surrogate(item) for item in value)
    if isinstance(value, dict):
        return any(_contains_surrogate(k) or _contains_surrogate(v) for k, v in value.items())
    return False


MAX_SSE_RESPONSE_BYTES = 4 * 1024 * 1024
MAX_SSE_EVENT_BYTES = 256 * 1024
SSE_READ_CHUNK_BYTES = 8192
MAX_HTTP_ERROR_BYTES = 65536
_CHUNK_SIZE_HEX_RE = re.compile(rb"[0-9A-Fa-f]{1,16}")


class _SSEReadLimitError(Exception):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """拒绝所有 3xx 重定向，避免跟随重定向时无界读体或向跨源地址转发 Authorization。"""

    def http_error_302(self, req, fp, code, msg, headers):
        raise urllib.error.HTTPError(req.full_url, code, msg, headers, fp)

    http_error_301 = http_error_303 = http_error_307 = http_error_308 = http_error_302


def _open_http(request: urllib.request.Request, timeout: float):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    return opener.open(request, timeout=timeout)


def _read_exact_fp(fp, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        part = fp.read(n - len(buf))
        if not part:
            raise http.client.IncompleteRead(bytes(buf))
        buf.extend(part)
    return bytes(buf)


def _iter_strict_http_body(
    response,
    deadline: Deadline | None,
    *,
    max_total_bytes: int,
    chunk_bytes: int = SSE_READ_CHUNK_BYTES,
):
    """严格有界读取 HTTP 响应体：对真实 chunked 响应绕过 CPython 宽松分块解码，
    在读块体前强制校验无符号 16 进制块长、块尾 \\r\\n 与 trailer 终结空行，避免负块长无界分配或坏分帧放行。"""
    total_bytes = 0
    if isinstance(response, http.client.HTTPResponse) and getattr(response, "chunked", False):
        fp = getattr(response, "fp", None)
        if fp is None:
            raise http.client.IncompleteRead(b"")
        while True:
            if deadline is not None and deadline.work_left() <= 0:
                return
            size_line = fp.readline(http.client._MAXLINE + 1)
            if len(size_line) > http.client._MAXLINE:
                raise http.client.LineTooLong("chunk size")
            if not size_line or not size_line.endswith(b"\r\n"):
                raise http.client.IncompleteRead(b"")
            size_head, sep, _ext = size_line[:-2].partition(b";")
            size_token = size_head.rstrip(b" \t") if sep else size_head
            if not _CHUNK_SIZE_HEX_RE.fullmatch(size_token):
                raise http.client.HTTPException("invalid chunk size")
            chunk_size = int(size_token, 16)
            if chunk_size == 0:
                total_trailer_bytes = 0
                while True:
                    if deadline is not None and deadline.work_left() <= 0:
                        return
                    tline = fp.readline(http.client._MAXLINE + 1)
                    if len(tline) > http.client._MAXLINE:
                        raise http.client.LineTooLong("trailer line")
                    if not tline:
                        raise http.client.IncompleteRead(b"")
                    total_trailer_bytes += len(tline)
                    if total_trailer_bytes > 65536:
                        raise http.client.LineTooLong("trailer section")
                    if tline == b"\r\n":
                        break
                    if not tline.endswith(b"\r\n"):
                        raise http.client.IncompleteRead(b"")
                response.close()
                return
            chunk_rem = chunk_size
            while chunk_rem > 0:
                if deadline is not None and deadline.work_left() <= 0:
                    return
                remaining = max_total_bytes - total_bytes
                read_size = min(chunk_bytes, chunk_rem, remaining + 1)
                data = fp.read(read_size)
                if not data:
                    raise http.client.IncompleteRead(b"")
                chunk_rem -= len(data)
                total_bytes += len(data)
                if total_bytes > max_total_bytes:
                    raise _SSEReadLimitError("SSE 响应超过大小上限")
                yield data
            if _read_exact_fp(fp, 2) != b"\r\n":
                raise http.client.HTTPException("invalid chunk terminator")
        return

    while True:
        if deadline is not None and deadline.work_left() <= 0:
            return
        remaining = max_total_bytes - total_bytes
        read_size = min(chunk_bytes, remaining + 1)
        chunk = response.read(read_size)
        if not chunk:
            if (getattr(response, "length", None) or 0) > 0 or (
                getattr(response, "chunked", False) and (
                    getattr(response, "chunk_left", None) is not None
                    or (isinstance(response, http.client.HTTPResponse) and not response.isclosed())
                )
            ):
                raise http.client.IncompleteRead(b"")
            break
        total_bytes += len(chunk)
        if total_bytes > max_total_bytes:
            raise _SSEReadLimitError("SSE 响应超过大小上限")
        yield chunk


def _read_bounded_error_body(error: urllib.error.HTTPError, *, max_bytes: int = MAX_HTTP_ERROR_BYTES) -> bytes:
    """严格有界读取 HTTPError 正文，对 chunked 错误响应同样校验块长与上限。"""
    raw_resp = getattr(error, "fp", None)
    if isinstance(raw_resp, http.client.HTTPResponse):
        buf = bytearray()
        try:
            for chunk in _iter_strict_http_body(raw_resp, None, max_total_bytes=max_bytes, chunk_bytes=min(SSE_READ_CHUNK_BYTES, max_bytes)):
                buf.extend(chunk)
                if len(buf) >= max_bytes:
                    break
        except (_SSEReadLimitError, http.client.HTTPException, OSError):
            pass
        return bytes(buf[:max_bytes])
    try:
        return error.read(max_bytes)[:max_bytes]
    except http.client.IncompleteRead as inc:
        return inc.partial[:max_bytes]
    except Exception:
        return b""


def _iter_bounded_sse_lines(
    response,
    deadline: Deadline,
    *,
    max_total_bytes: int = MAX_SSE_RESPONSE_BYTES,
    max_line_bytes: int = MAX_SSE_EVENT_BYTES,
    chunk_bytes: int = SSE_READ_CHUNK_BYTES,
):
    """增量按块读取 SSE 流并执行总字节数与单行上限，未超限时必须读至 EOF 以保留截断传输检测。"""
    bom_checked = False
    bom_buf = bytearray()
    pending_cr = False
    line_buf = bytearray()

    for chunk in _iter_strict_http_body(response, deadline, max_total_bytes=max_total_bytes, chunk_bytes=chunk_bytes):
        if not bom_checked:
            need = 3 - len(bom_buf)
            bom_buf.extend(chunk[:need])
            rest = chunk[need:]
            if len(bom_buf) < 3 and b"\xef\xbb\xbf".startswith(bom_buf):
                continue
            bom_checked = True
            if bom_buf == b"\xef\xbb\xbf":
                chunk = rest
            else:
                chunk = bytes(bom_buf) + rest
            bom_buf.clear()
            if not chunk:
                continue

        idx = 0
        if pending_cr:
            pending_cr = False
            if chunk[0] == 10:
                idx = 1

        n = len(chunk)
        start = idx
        while idx < n:
            b = chunk[idx]
            if b == 13 or b == 10:
                if idx > start:
                    if len(line_buf) + (idx - start) > max_line_bytes:
                        raise _SSEReadLimitError("SSE 单行超过大小上限")
                    line_buf.extend(chunk[start:idx])
                yield bytes(line_buf)
                line_buf.clear()
                if b == 13:
                    if idx + 1 < n and chunk[idx + 1] == 10:
                        idx += 2
                    else:
                        if idx + 1 == n:
                            pending_cr = True
                        idx += 1
                else:
                    idx += 1
                start = idx
            else:
                idx += 1

        if start < n:
            if len(line_buf) + (n - start) > max_line_bytes:
                raise _SSEReadLimitError("SSE 单行超过大小上限")
            line_buf.extend(chunk[start:n])

    if not bom_checked and bom_buf:
        if len(line_buf) + len(bom_buf) > max_line_bytes:
            raise _SSEReadLimitError("SSE 单行超过大小上限")
        line_buf.extend(bom_buf)
    if line_buf:
        yield bytes(line_buf)


def _round_trip_http(url: str, key: str, model: str, session: str, deadline: Deadline) -> dict:
    """一次最小往返，只探连通：responses + tools + tool_choice=auto + json_schema 输出格式。
    不代表 kimi 的生产请求形状（正式独审对 kimi 不带 --output-schema），也不验证回合内真实工具调用。"""
    body = {"model": model, "stream": True, "store": False, "reasoning": {"effort": "low"},
            "instructions": "Preflight connectivity check. Do not call tools.",
            "input": [{"role": "user", "content": [{"type": "input_text", "text": 'Return {"ok": true}.'}]}],
            "tools": [{"type": "function", "name": "noop", "description": "Never call this.", "strict": False,
                       "parameters": {"type": "object", "properties": {}, "additionalProperties": False}}],
            "tool_choice": "auto", "parallel_tool_calls": True,
            "text": {"format": {"type": "json_schema", "name": "preflight", "strict": True,
                                "schema": {"type": "object", "properties": {"ok": {"type": "boolean"}},
                                           "required": ["ok"], "additionalProperties": False}}}}
    request = urllib.request.Request(url.rstrip("/") + "/v1/responses", data=json.dumps(body).encode(), method="POST",
                                     headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                                              "Accept": "text/event-stream", "Session-Id": session,
                                              "X-Client-Request-Id": session})
    timeout = deadline.work_left()  # 只受总工作时限约束，不另设更短的固定上限
    if timeout <= 0:
        return {"http_status": None, "terminal": None, "ok": False, "error": {"not_sent": "总时限已到"}}
    try:
        with _open_http(request, timeout=timeout) as response:
            terminal, detail, status = None, "流在终态事件前结束", None
            has_response_dict = False
            data_lines: list[str] = []
            event_data_bytes = 0
            event_name: str | None = None
            try:
                for raw in _iter_bounded_sse_lines(response, deadline):
                    if deadline.work_left() <= 0:
                        detail = "总时限内无终态事件"
                        break
                    try:
                        line = raw.decode("utf-8")
                    except UnicodeDecodeError:
                        detail = "SSE 包含非法 UTF-8 字节"
                        break
                    if line == "":
                        ev_name = event_name
                        event_name = None
                        if data_lines:
                            joined = "\n".join(data_lines).strip(" \t\r\n")
                            data_lines = []
                            event_data_bytes = 0
                            if joined == "[DONE]":
                                if ev_name is not None or terminal is None:
                                    detail = "SSE 存在提前或带事件名的 [DONE]"
                                    break
                                continue
                            if not joined:
                                if ev_name is not None:
                                    detail = "SSE 存在空数据事件"
                                    break
                                continue
                            if terminal is not None:
                                detail = "终态事件后出现多余数据事件"
                                break
                            if not joined.startswith("{"):
                                detail = "SSE 存在非 JSON 对象数据事件"
                                break
                            try:
                                event = json.loads(
                                    joined,
                                    object_pairs_hook=_no_duplicate_keys,
                                    parse_constant=_reject_json_constant,
                                )
                                if _contains_surrogate(event):
                                    raise ValueError("unpaired UTF-16 surrogate")
                                _validate_sse_protocol_key_casing(event)
                            except (ValueError, RecursionError):
                                detail = "SSE 数据帧 JSON 解析失败"
                                break
                            if not isinstance(event, dict) or not isinstance(event.get("type"), str) or not event["type"].strip():
                                detail = "SSE 数据事件缺少合法 type"
                                break
                            if ev_name is not None and event.get("type") != ev_name:
                                detail = "SSE 事件名与数据 type 不一致"
                                break
                            raw_inner = event.get("response")
                            if raw_inner is not None and not isinstance(raw_inner, dict):
                                detail = "SSE 响应字段须为 JSON 对象"
                                break
                            inner = raw_inner if isinstance(raw_inner, dict) else {}
                            if event.get("type") in TERMINAL_EVENTS:
                                terminal = event.get("type")
                                has_response_dict = isinstance(raw_inner, dict)
                                # 只报已知枚举：上游任意值（可能以各种编码夹带 key）一律归一成 "other"，不进报告
                                status = inner.get("status") if inner.get("status") in RESPONSE_STATUSES else (
                                    None if inner.get("status") is None else "other")
                                detail = next(
                                    (val for val in (inner.get("error"), event.get("error"), event.get("message"))
                                     if val is not None),
                                    None,
                                )
                                # 终态数据不等于代理 lifecycle 已收尾；读到 EOF 才关闭连接。
                            else:
                                ev_err = next(
                                    (val for val in (inner.get("error"), event.get("error")) if val is not None),
                                    None,
                                )
                                if ev_err is not None:
                                    detail = ev_err
                                    break
                                ev_status = inner.get("status")
                                ev_type = event.get("type")
                                if ev_status is not None and (
                                    ev_status not in ("in_progress", "queued")
                                    or (ev_type == "response.queued" and ev_status != "queued")
                                    or (ev_type == "response.in_progress" and ev_status != "in_progress")
                                ):
                                    detail = "非终态事件携带非法状态"
                                    break
                        elif ev_name is not None:
                            detail = "SSE 存在无数据事件头"
                            break
                        continue
                    if line == "event" or line.startswith("event:"):
                        val = "" if line == "event" else line[6:]
                        if val.startswith(" "):
                            val = val[1:]
                        event_name = val
                    elif line == "data" or line.startswith("data:"):
                        val = "" if line == "data" else line[5:]
                        if val.startswith(" "):
                            val = val[1:]
                        event_data_bytes += len(val.encode("utf-8")) + (1 if data_lines else 0)
                        if event_data_bytes > MAX_SSE_EVENT_BYTES:
                            detail = "SSE 单事件超过大小上限"
                            data_lines = []
                            event_data_bytes = 0
                            break
                        data_lines.append(val)
                    elif line in ("id", "retry") or line.startswith((":", "id:", "retry:")):
                        continue
                    else:
                        detail = "SSE 存在非法非协议行"
                        break
            except _SSEReadLimitError as limit_err:
                detail = str(limit_err)
                data_lines = []
                event_name = None
            if data_lines:
                trailing = "\n".join(data_lines).strip(" \t\r\n")
                if (trailing and (trailing != "[DONE]" or terminal is None)) or event_name is not None:
                    detail = "流尾存在未闭合 SSE 事件"
            elif event_name is not None:
                detail = "流尾存在未闭合 SSE 事件头"
            if deadline.work_left() <= 0:
                detail = "总时限内流未收尾"
            # 事件名成功还不够：须存在合法 response 对象且 status 与终态事件一致，且 error/message 均须为 null/缺省。
            ok = (detail is None and has_response_dict and (
                (terminal == "response.completed" and status == "completed")
                or (terminal == "response.incomplete" and status == "incomplete")
            ))
            text = detail if isinstance(detail, str) else json.dumps(detail, ensure_ascii=False) if detail is not None else ""
            return {"http_status": response.status, "terminal": terminal, "status": status, "ok": ok,
                    "error": None if ok else _error_info(text)}
    except urllib.error.HTTPError as error:
        try:
            err_body = _read_bounded_error_body(error, max_bytes=MAX_HTTP_ERROR_BYTES)
        finally:
            try:
                error.close()
            except Exception:
                pass
        return {"http_status": error.code, "terminal": None, "ok": False,
                "error": _error_info(err_body.decode("utf-8", "replace"))}
    except Exception as error:  # 连接、协议等任何异常都只记类型与 errno，不带异常原文
        reason = getattr(error, "reason", None)
        return {"http_status": None, "terminal": None, "ok": False,
                "error": {"exception": type(error).__name__, "errno": getattr(reason, "errno", getattr(error, "errno", None))}}


# -I 不把脚本目录放入 sys.path；按当前脚本的相邻路径加载唯一解析实现。
_LOG_READER = Path(__file__).with_name("_review_preflight_log.py")
_log_spec = importlib.util.spec_from_file_location("_review_preflight_log", _LOG_READER)
_log_module = importlib.util.module_from_spec(_log_spec)
_log_spec.loader.exec_module(_log_module)
route_from_log = _log_module.route_from_log


def docker_command(context: str | None) -> list[str]:
    return ["docker", "--context", context] if context else ["docker"]


def _decode_routes(raw: bytes, session: str, labels: dict) -> list[tuple[str, str]] | None:
    payload = json.loads(raw, object_pairs_hook=_log_module._unique_object)
    if (not isinstance(payload, dict) or set(payload) != {"session", "complete_stable", "routes"}
            or payload["session"] != session or payload["complete_stable"] is not True
            or not isinstance(payload["routes"], list) or len(payload["routes"]) > 64
            or any(not isinstance(route, str) or route not in {*labels, "other"} for route in payload["routes"])):
        return None
    return [labels.get(route, ("other", "other")) for route in payload["routes"]]


def route_from_container(args, session: str, since: float, wait: float,
                         deadline: Deadline) -> list[tuple[str, str]] | None:
    """只接受完整白名单协议；读取失败、超时或多余输出均不能证明路由。"""
    budget = min(wait, deadline.work_left() - 0.25)
    if budget <= 0:
        return None
    labels = {"@".join(route): route for route in KNOWN_ROUTES}
    receipt = getattr(args, "proxy_receipt_container", None)
    cmd = [*docker_command(args.proxy_docker_context), "exec", receipt or args.proxy_log_container,
           "python3", "-I", "-c", _LOG_READER.read_text(),
           *(["--receipt", args.proxy_container_receipt_dir] if receipt else [args.proxy_container_log_dir]),
           session, str(since), str(time.time() + budget), str(budget), json.dumps(sorted(KNOWN_ROUTES))]
    try:
        result = run_bounded(cmd, budget)
        if result.returncode or result.stderr:
            return None
        return _decode_routes(result.stdout, session, labels)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def route_from_host_receipt(directory: str, session: str, since: float, wait: float,
                            deadline: Deadline) -> list[tuple[str, str]] | None:
    budget = min(wait, deadline.work_left() - 0.25)
    if budget <= 0:
        return None
    labels = {"@".join(route): route for route in KNOWN_ROUTES}
    try:
        result = run_bounded([sys.executable, "-I", "-c", _LOG_READER.read_text(), "--receipt", directory,
                              session, str(since), str(time.time() + budget), str(budget),
                              json.dumps(sorted(KNOWN_ROUTES))], budget)
        if result.returncode or result.stderr:
            return None
        return _decode_routes(result.stdout, session, labels)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def probe_model(args, model: str, key: str, deadline: Deadline) -> list[dict]:
    session = f"preflight-{uuid.uuid4()}"
    since = time.time()
    trip = round_trip(args.proxy_url, key, model, session, deadline)
    # 成功后等生产者完成收尾并原子发布；往返失败时只给证据读取 0.3 秒。
    wait = max(0.0, deadline.work_left() - 0.25)
    if not trip["ok"]:
        wait = min(wait, 0.3)
    if getattr(args, "proxy_log_container", None) or getattr(args, "proxy_receipt_container", None):
        attempts = route_from_container(args, session, since, wait, deadline)
    elif getattr(args, "proxy_receipt_dir", None):
        attempts = route_from_host_receipt(args.proxy_receipt_dir, session, since, wait, deadline)
    else:
        attempts = route_from_log(Path(args.proxy_log_dir), session, since, wait)
    expected = ROUTES[model]
    return [{"name": f"route:{model}", "class": "route", "ok": bool(attempts) and all(a in expected for a in attempts),
             "detail": {"expected": sorted("@".join(route) for route in expected), "actual": [f"{p}@{h}" if (p, h) in KNOWN_ROUTES else "other" for p, h in attempts or []],
                        "log_found": attempts is not None, "session": session}},
            {"name": f"roundtrip:{model}", "class": "roundtrip", "ok": trip["ok"], "detail": trip}]


def _guarded(name: str, kind: str, fn) -> dict:
    """检查自身异常按未通过处理，只记异常类型（不带可能含参数的原文）。"""
    try:
        return fn()
    except Exception as error:
        return {"name": name, "class": kind, "ok": False, "detail": {"error": type(error).__name__}}


def _deadline(text: str) -> float:
    value = float(text)
    if not 0 < value <= 60:  # 承诺单次墙钟 ≤60 秒；0 或负数只会让所有检查超时
        raise argparse.ArgumentTypeError("必须满足 0 < deadline ≤ 60")
    return value


def _sha(text: str) -> str:
    if not SHA_RE.fullmatch(text):
        raise argparse.ArgumentTypeError("必须是 40 位小写十六进制 commit SHA")
    return text


def _emit(report: dict, secrets=()) -> None:
    # ensure_ascii：孤立代理项、surrogateescape 参数都转成 \uXXXX，stdout 永远是合法 ASCII JSON
    print(json.dumps(sanitize(report, list(secrets)), ensure_ascii=True), flush=True)


class _Parser(argparse.ArgumentParser):
    def error(self, message):  # 退出码 2 专指“拦截”，用法错误用 3；stdout 仍给 JSON，stderr 同样脱敏
        secrets = [os.environ.get(SCRUBBED_ENV)]
        print(redact(f"review_preflight: {message}", secrets), file=sys.stderr)
        _emit({"kind": "review-preflight", "is_review_result": False, "ready": False, "usage_error": message}, secrets)
        sys.exit(3)

    def print_help(self, file=None):
        _emit({"kind": "review-preflight-help", "is_review_result": False, "usage": self.format_help()})


def main(argv=None) -> int:
    ap = _Parser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", required=True, help="控制器读取候选对象的仓库（ExternalReview.source）")
    ap.add_argument("--base", required=True, type=_sha)
    ap.add_argument("--head", required=True, type=_sha)
    ap.add_argument("--merge-base", required=True, type=_sha)
    ap.add_argument("--checkout-root", required=True, help="正式 attempt 将传给 ExternalReview 的 checkout_root")
    ap.add_argument("--image", default="sandcastle:newchanlun", help="与 external-review-worker.mts REVIEW_IMAGE 相同")
    ap.add_argument("--proxy-url", default="http://127.0.0.1:8318")  # DevSkim: ignore DS162092 有意使用本机回环（本地 CLIProxy / 测试假服务），非调试残留
    logs = ap.add_mutually_exclusive_group()
    logs.add_argument("--proxy-log-dir", default=str(CLIPROXY_LOG_DIR))
    logs.add_argument("--proxy-log-container", help="旧文本日志入口；不可信，不能证明路由")
    logs.add_argument("--proxy-receipt-dir", help="宿主可信结构化收据目录；不接受旧文本日志")
    logs.add_argument("--proxy-receipt-container", help="在代理容器内读取可信收据；不读取状态卷")
    ap.add_argument("--proxy-container-receipt-dir", help="容器内收据目录绝对路径")
    ap.add_argument("--proxy-docker-context", help="容器日志后端的显式 Docker context")
    ap.add_argument("--proxy-container-log-dir", help="代理容器内日志目录的绝对路径")
    ap.add_argument("--review-docker-context", help="审阅挂载探针的 Docker context；默认沿用当前环境")
    ap.add_argument("--codex-home", default=os.environ.get("CODEX_HOME", str(Path.home() / ".codex")),
                    help="宿主 Codex 配置目录；按其 model_providers.cliproxy-local 取 key")
    ap.add_argument("--codex-bin", default="codex", help="宿主使用的 codex 可执行文件，用于离线校验 provider 配置")
    ap.add_argument("--deadline", type=_deadline, default=55.0, help="总墙钟上限（秒，0 < x ≤ 60），超时的检查判失败")
    args = ap.parse_args(argv)
    if args.proxy_receipt_container:
        if (not args.proxy_docker_context or not args.proxy_container_receipt_dir
                or not args.proxy_container_receipt_dir.startswith("/") or args.proxy_container_log_dir):
            ap.error("收据容器须指定 proxy-docker-context 与绝对 proxy-container-receipt-dir，不得混用日志参数")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", args.proxy_receipt_container):
            ap.error("proxy-receipt-container 必须是容器名称或 ID")
    elif args.proxy_log_container:
        if args.proxy_container_receipt_dir:
            ap.error("旧日志入口不能使用收据目录")
        if (not args.proxy_docker_context or not args.proxy_container_log_dir
                or not args.proxy_container_log_dir.startswith("/")):
            ap.error("容器日志后端须指定 proxy-docker-context 与绝对 proxy-container-log-dir")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", args.proxy_log_container):
            ap.error("proxy-log-container 必须是容器名称或 ID")
    elif args.proxy_docker_context or args.proxy_container_log_dir or args.proxy_container_receipt_dir:
        ap.error("容器日志参数须与 proxy-log-container 一起使用")
    t0 = time.monotonic()
    deadline = Deadline(args.deadline)
    secrets = [os.environ.get(SCRUBBED_ENV)]
    try:
        checks = run_checks(args, deadline, secrets)
    except Exception as error:  # 主流程意外异常也要给出合法报告，退出码仍是 2
        checks = [{"name": "preflight_internal", "class": "tool", "ok": False, "detail": type(error).__name__}]
    ready = all(c["ok"] for c in checks)
    _emit({"kind": "review-preflight", "is_review_result": False, "ready": ready, "checks": checks,
           "wall_seconds": round(time.monotonic() - t0, 3)}, secrets)
    return 0 if ready else 2


def run_checks(args, deadline: Deadline, secrets: list) -> list[dict]:
    credential, key = check_credential(args, deadline)
    secrets.append(key)
    checks = [credential]
    # HTTP 子进程与挂载探针共享工作期限；线程须完成子进程回收后才能返回。
    probes: dict = {}
    threads = []
    try:
        if key is not None:
            for model in MODELS:
                def probe(m=model):
                    probes[m] = _guarded(f"roundtrip:{m}", "roundtrip", lambda: probe_model(args, m, key, deadline))
                thread = threading.Thread(target=probe)
                thread.start()
                threads.append(thread)
        checks.append(_guarded("checkout_root_free_space", "space", lambda: check_space(args, deadline)))
        mount, cleanup = check_mount(args, deadline)
        checks.append(mount)
        if cleanup:
            checks.append({"name": "probe_cleanup", "class": "cleanup", "ok": False, "detail": cleanup})
    finally:
        for thread in threads:
            thread.join()  # 各外部操作有界；包括异常出口也须先回收请求。
    for model in MODELS:
        result = probes.get(model)
        if result is None:
            reason = "凭据不可用，未发探测" if key is None else "总时限内未完成"
            result = [{"name": f"roundtrip:{model}", "class": "roundtrip", "ok": False, "detail": reason}]
        checks.extend(result if isinstance(result, list) else [result])
    return checks


if __name__ == "__main__":
    if sys.argv[1:] == ["--http-worker"]:
        url, key, model, session, work, total = json.load(sys.stdin)
        deadline = Deadline.__new__(Deadline)
        deadline.work, deadline.total = work, total
        print(json.dumps(_round_trip_http(url, key, model, session, deadline)))
    else:
        sys.exit(main())
