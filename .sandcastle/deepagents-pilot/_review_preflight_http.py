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
TERMINAL_EVENTS = ("response.completed", "response.incomplete", "response.failed", "error")
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


def _round_trip_http(url: str, key: str, model: str, session: str, deadline) -> dict:
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
    request = urllib.request.Request(
        url.rstrip("/") + "/v1/responses",
        data=json.dumps(body).encode(),
        method="POST",
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "Session-Id": session,
            "X-Client-Request-Id": session,
        },
    )
    timeout = work_left()  # 只受总工作时限约束，不另设更短的固定上限
    if timeout <= 0:
        return {"http_status": None, "terminal": None, "ok": False, "error": {"not_sent": "总时限已到"}}
    try:
        with _open_http(request, timeout=timeout) as response:
            terminal, detail, error_code, status, returned_model = None, "流在终态事件前结束", None, None, None
            for raw in response.read().splitlines():
                if work_left() <= 0:
                    detail = "总时限内无终态事件"
                    break
                line = raw.decode("utf-8", "replace").strip()
                if line.startswith("data:"):
                    event = json.loads(line[5:]) if line[5:].strip().startswith("{") else {}
                    if event.get("type") in TERMINAL_EVENTS:
                        if terminal is not None:
                            detail = "终态事件后出现另一终态"
                            break
                        terminal = event.get("type")
                        inner = event.get("response") if isinstance(event.get("response"), dict) else {}
                        # 只报已知枚举：上游任意值（可能以各种编码夹带 key）一律归一成 "other"，不进报告
                        status = inner.get("status") if inner.get("status") in RESPONSE_STATUSES else (
                            None if inner.get("status") is None else "other")
                        raw_model = inner.get("model")
                        returned_model = raw_model if raw_model in MODELS else (
                            None if raw_model is None else "other")
                        inner_err = inner.get("error")
                        event_err = event.get("error")
                        error_code = next(
                            (value for value in (
                                inner_err.get("code") if isinstance(inner_err, dict) else None,
                                event_err.get("code") if isinstance(event_err, dict) else None,
                                inner.get("code"),
                                event.get("code"),
                            ) if isinstance(value, str) and value),
                            None,
                        )
                        detail = next(
                            (value for value in (inner_err, event_err, event.get("message"), error_code)
                             if value is not None),
                            None,
                        )
                        # 终态数据不等于代理 lifecycle 已收尾；读到 EOF 才关闭连接。
            if work_left() <= 0:
                detail = "总时限内流未收尾"
            elif detail is None and terminal == "response.completed" and status == "completed" and returned_model != model:
                detail = "响应模型与请求模型不符"
            # 只接受唯一 completed 终态、内层 completed、精确响应模型匹配、无错误及完整 HTTP 消息。
            ok = (response.status == 200 and terminal == "response.completed" and status == "completed"
                  and returned_model == model and detail is None)
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


if __name__ == "__main__":
    url, key, model, session, work_seconds = json.load(sys.stdin)
    print(json.dumps(_round_trip_http(url, key, model, session, work_seconds)))
