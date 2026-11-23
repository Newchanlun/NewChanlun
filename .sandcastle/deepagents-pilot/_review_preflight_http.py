#!/usr/bin/env python3
"""#1742 预检 HTTP 往返探针（宿主与审阅容器共用唯一实现，只用标准库）。

- 显式禁用代理环境与 HTTP 重定向（301/302/303/307/308 一律拒绝，防止 Authorization 密钥被重定向带往他处）。
- 校验 HTTP 200、唯一 response.completed、内层 response.status=completed、response.model 与请求一致且读到完整 EOF。
- 独立运行时从 stdin 读取 JSON 数组 `[url, key, model, session, work_seconds]`，stdout 仅输出固定枚举 JSON。
"""
import hashlib
import json
import sys
import time
import urllib.error
import urllib.request

MODELS = ("gpt-6.2-sol", "gpt-6.2-astra")
RESPONSE_STATUSES = ("completed", "incomplete", "failed", "cancelled", "in_progress", "queued")
TERMINAL_EVENTS = ("response.completed", "response.done", "response.incomplete", "response.failed", "error")
# 上游错误只按固定词表分类，不把原文抄进报告（原文可能回显 key，且转义形态无法穷举）
ERROR_CLASSES = (
    ("tool_choice", "tool_choice_unsupported"),
    ("预扣额度", "quota"),
    ("quota", "quota"),
    ("insufficient", "quota"),
    ("invalid api key", "auth"),
    ("invalid bearer", "auth"),
    ("unauthorized", "auth"),
    ("authentication", "auth"),
    ("rate_limit", "rate_limit"),
    ("rate limit", "rate_limit"),
    ("too_many_requests", "rate_limit"),
    ("too many requests", "rate_limit"),
    ("overloaded", "overloaded"),
    ("model_not_found", "model_not_found"),
    ("not supported", "unsupported"),
)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _open_http(request: urllib.request.Request, timeout: float):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    return opener.open(request, timeout=timeout)


def _error_info(body: str, *, code: str | None = None) -> dict:
    """上游错误正文只给长度、sha256 前 12 位与固定词表分类，不抄原文；优先按结构化错误码分类。"""
    code_lower = code.lower() if isinstance(code, str) else ""
    kind = next((label for needle, label in ERROR_CLASSES if needle in code_lower), None)
    if kind is None:
        lowered = body.lower()
        kind = next((label for needle, label in ERROR_CLASSES if needle in lowered), "unclassified")
    return {
        "class": kind,
        "length": len(body),
        "sha256_12": hashlib.sha256(body.encode("utf-8", "replace")).hexdigest()[:12],
    }


def _strict_object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    obj: dict[str, object] = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError(f"duplicate JSON key: {key}")
        obj[key] = value
    return obj


def _strict_loads(text: str) -> object:
    return json.loads(text, object_pairs_hook=_strict_object_pairs)


def _round_trip_http(url: str, key: str, model: str, session: str, deadline,
                     *, review_launch: str | None = None) -> dict:
    """最小连通探针采用 JSON schema，不验证真实审阅或工具调用。"""
    if hasattr(deadline, "work_left"):
        work_left = deadline.work_left
    else:
        end = time.monotonic() + float(deadline)
        work_left = lambda: max(0.0, end - time.monotonic())  # noqa: E731
    body = {
        "model": model,
        "stream": True,
        "store": False,
        "reasoning": {"effort": "low"},
        "instructions": "Preflight connectivity check. Do not call tools.",
        "input": [{"role": "user", "content": [{"type": "input_text", "text": 'Return {"ok": true}.'}]}],
        "tools": [{
            "type": "function",
            "name": "noop",
            "description": "Never call this.",
            "strict": False,
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        }],
        "tool_choice": "auto",
        "parallel_tool_calls": True,
        "text": {
            "format": {
                "type": "json_schema",
                "name": "preflight",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {"ok": {"type": "boolean"}},
                    "required": ["ok"],
                    "additionalProperties": False,
                },
            }
        },
    }
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "Session-Id": session,
        "X-Client-Request-Id": session,
    }
    if review_launch:
        headers["X-NewChanlun-Review-Launch"] = review_launch
    request = urllib.request.Request(
        url.rstrip("/") + "/v1/responses",
        data=json.dumps(body).encode(),
        method="POST",
        headers=headers,
    )
    timeout = work_left()  # 只受总工作时限约束，不另设更短的固定上限
    if timeout <= 0:
        return {"http_status": None, "terminal": None, "ok": False, "error": {"not_sent": "总时限已到"}}
    try:
        with _open_http(request, timeout=timeout) as response:
            terminal, detail, error_code, status, returned_model = None, "流在终态事件前结束", None, None, None
            stream_error, stream_error_code = None, None
            for raw in response.read().splitlines():
                if work_left() <= 0:
                    detail = "总时限内无终态事件"
                    break
                line = raw.decode("utf-8", "replace").strip()
                if line.startswith("data:"):
                    payload = line[5:].strip()
                    if not payload or payload == "[DONE]":
                        continue
                    try:
                        event = _strict_loads(payload)
                    except ValueError:
                        if stream_error is None:
                            stream_error = "非法 SSE 数据帧（JSON 损坏或存在重复键）"
                        continue
                    if not isinstance(event, dict) or not isinstance(event.get("type"), str) or not event["type"].strip():
                        if stream_error is None:
                            stream_error = "非法 SSE 数据帧（须为带非空 type 的 JSON 对象）"
                        continue
                    raw_inner = event.get("response")
                    if raw_inner is not None and not isinstance(raw_inner, dict):
                        if stream_error is None:
                            stream_error = "非法 SSE 响应字段（response 须为 JSON 对象）"
                        continue
                    inner = raw_inner if isinstance(raw_inner, dict) else {}
                    inner_err = inner.get("error")
                    event_err = event.get("error")
                    ev_code = next(
                        (value for value in (
                            inner_err.get("code") if isinstance(inner_err, dict) else None,
                            event_err.get("code") if isinstance(event_err, dict) else None,
                            inner.get("code"),
                            event.get("code"),
                        ) if isinstance(value, str) and value),
                        None,
                    )
                    if stream_error is None and (inner_err is not None or event_err is not None):
                        stream_error = inner_err if inner_err is not None else event_err
                        stream_error_code = ev_code
                    if event.get("type") in TERMINAL_EVENTS:
                        if terminal is not None:
                            detail = "终态事件后出现另一终态"
                            if error_code is None and ev_code is not None:
                                error_code = ev_code
                            break
                        terminal = event.get("type")
                        # 只报已知枚举：上游任意值（可能以各种编码夹带 key）一律归一成 "other"，不进报告
                        status = inner.get("status") if inner.get("status") in RESPONSE_STATUSES else (
                            None if inner.get("status") is None else "other")
                        raw_model = inner.get("model")
                        returned_model = raw_model if raw_model in MODELS else (
                            None if raw_model is None else "other")
                        error_code = ev_code
                        detail = next(
                            (value for value in (inner_err, event_err, event.get("message"), error_code)
                             if value is not None),
                            None,
                        )
                        # 终态数据不等于代理 lifecycle 已收尾；读到 EOF 才关闭连接。
            if work_left() <= 0:
                detail = "总时限内流未收尾"
            elif stream_error is not None:
                if detail is None:
                    detail = stream_error
                if error_code is None:
                    error_code = stream_error_code
            elif detail is None and terminal == "response.completed" and status == "completed" and returned_model != model:
                detail = "响应模型与请求模型不符"
            # 只接受唯一 completed 终态、内层 completed、精确响应模型匹配、全流无错误及完整 HTTP 消息。
            ok = (response.status == 200 and terminal == "response.completed" and status == "completed"
                  and returned_model == model and detail is None and stream_error is None)
            text = detail if isinstance(detail, str) else json.dumps(detail, ensure_ascii=False) if detail is not None else ""
            return {
                "http_status": response.status,
                "terminal": terminal,
                "status": status,
                "returned_model": returned_model,
                "ok": ok,
                "error": None if ok else _error_info(text, code=error_code),
            }
    except urllib.error.HTTPError as error:
        return {
            "http_status": error.code,
            "terminal": None,
            "ok": False,
            "error": _error_info(error.read()[:65536].decode("utf-8", "replace")),
        }
    except Exception as error:  # 连接、协议等任何异常都只记类型与 errno，不带异常原文
        reason = getattr(error, "reason", None)
        return {
            "http_status": None,
            "terminal": None,
            "ok": False,
            "error": {"exception": type(error).__name__, "errno": getattr(reason, "errno", getattr(error, "errno", None))},
        }


def _seal_review_http(url: str, key: str, launch: str, session: str, timeout_seconds: float) -> dict:
    """向宿主侧代理封存端点发起已认证 POST /v1/review-receipts/seal（禁用代理与重定向），
    在独立子进程组中运行以受父进程总墙钟期限强约束。"""
    end = time.monotonic() + max(0.0, float(timeout_seconds))
    seal_url = url.rstrip("/")
    if not seal_url.endswith("/v1/review-receipts/seal"):
        seal_url = seal_url + "/v1/review-receipts/seal"
    headers = {
        "Authorization": f"Bearer {key}",
        "X-NewChanlun-Review-Launch": launch,
        "Session-Id": session,
    }
    while True:
        remaining = end - time.monotonic()
        if remaining <= 0:
            return {"http_status": None, "status": None, "ok": False, "error": {"not_sent": "总时限已到"}}
        request = urllib.request.Request(seal_url, data=b"", method="POST", headers=headers)
        try:
            with _open_http(request, timeout=remaining) as response:
                raw = response.read(4096).decode("utf-8", "replace")
                parsed = _strict_loads(raw)
                status = parsed.get("status") if isinstance(parsed, dict) and isinstance(parsed.get("status"), str) else None
                ok = response.status == 200 and status == "sealed"
                return {
                    "http_status": response.status,
                    "status": "sealed" if ok else ("other" if status is not None else None),
                    "ok": ok,
                    "error": None if ok else _error_info(raw),
                }
        except urllib.error.HTTPError as error:
            raw = error.read(4096).decode("utf-8", "replace")
            status_word = ""
            try:
                parsed = _strict_loads(raw)
                if isinstance(parsed, dict) and isinstance(parsed.get("status"), str):
                    status_word = parsed["status"]
            except ValueError:
                pass
            if error.code == 409 and status_word == "in_flight" and time.monotonic() < end:
                time.sleep(min(0.05, max(0.0, end - time.monotonic())))
                continue
            return {
                "http_status": error.code,
                "status": status_word if status_word in ("in_flight", "rejected", "unavailable") else None,
                "ok": False,
                "error": _error_info(raw),
            }
        except Exception as error:
            reason = getattr(error, "reason", None)
            return {
                "http_status": None,
                "status": None,
                "ok": False,
                "error": {"exception": type(error).__name__, "errno": getattr(reason, "errno", getattr(error, "errno", None))},
            }


if __name__ == "__main__":
    if sys.argv[1:] == ["--seal"]:
        url, key, launch, session, timeout_seconds = json.load(sys.stdin)
        print(json.dumps(_seal_review_http(url, key, launch, session, timeout_seconds)))
    else:
        payload = json.load(sys.stdin)
        if len(payload) == 6:
            url, key, model, session, work_seconds, review_launch = payload
            print(json.dumps(_round_trip_http(url, key, model, session, work_seconds, review_launch=review_launch)))
        else:
            url, key, model, session, work_seconds = payload
            print(json.dumps(_round_trip_http(url, key, model, session, work_seconds)))
