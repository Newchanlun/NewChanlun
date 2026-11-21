"""ADR 0064 的数据合同读取与验收用解码原语。"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import urlsplit

from common import (ADAPTER, COMMIT, NAME, RECORD, REGISTRY, SHA, SPECIAL, Invalid, git, git_blob, json_bytes, key_token,
                    path_name, pointer, require, sha, strict_json, tree_entry, validate_schema)

def timestamp(value):
    # 比较以原始精度进行；不把纳秒或更细时间截到 Python datetime 的微秒。
    match = re.fullmatch(r"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.([0-9]+))?Z", value) if isinstance(value, str) else None
    if not match:
        raise Invalid("SCHEMA: UTC timestamp")
    from decimal import Decimal
    try:
        whole = datetime.strptime(match[1], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError as error:
        raise Invalid("SCHEMA: UTC timestamp") from error
    return whole, Decimal("0." + (match[2] or "0"))


def string(value):
    return isinstance(value, str) and bool(value)


def profile(value):
    return string(value) and NAME.fullmatch(value) is not None and value != "none"


def typed(value, kind):
    if kind.startswith("nullable-"):
        return value is None or typed(value, kind[9:])
    if kind.endswith("-array"):
        return isinstance(value, list) and all(typed(item, kind[:-6]) for item in value)
    if kind == "utc-timestamp":
        timestamp(value)
        return True
    return {
        "string": string, "profile-id": profile, "object": lambda v: isinstance(v, dict),
        "positive-integer": lambda v: type(v) is int and v > 0,
        "boolean": lambda v: type(v) is bool, "sha256": lambda v: string(v) and SHA.fullmatch(v),
        "git-commit": lambda v: string(v) and COMMIT.fullmatch(v),
        "evidence-class": lambda v: v in ("simulation", "experiment", "production"),
        "pointer": lambda v: isinstance(v, str) and (v == "" or v.startswith("/")) and not re.search(r"~(?![01])", v),
        "https-url": lambda v: string(v) and urlsplit(v).scheme == "https" and bool(urlsplit(v).hostname),
        "decimal-string": lambda v: string(v) and re.fullmatch(r"-?(0|[1-9]\d*)(\.\d+)?", v),
        "bytes": lambda v: isinstance(v, bytes),
    }[kind](value)


def validate_adapter(root, data, expected_sha, *, commit=None):
    require(bool(data) and sha(data) == expected_sha, "REGISTRY_INVALID", "adapter_contract_sha256")
    try:
        contract = strict_json(data, ADAPTER)
        validate_schema(root, "adapter-contract", contract, "REGISTRY_INVALID", commit=commit)
    except (ValueError, OSError) as error:
        raise Invalid(f"REGISTRY_INVALID: {ADAPTER}") from error
    return contract


def decode_fields(contract, fields, obj):
    result = {}
    for identity, rule in fields.items():
        value = pointer(obj, rule["pointer"])
        require(typed(value, rule["type"]), "SCHEMA", rule["pointer"])
        if rule.get("decode_as"):
            target = contract["item_sources"][rule["decode_as"]]
            value = ([decode_fields(contract, target, v) for v in value] if isinstance(value, list)
                     else decode_fields(contract, target, value))
        result[identity] = value
    return result


def decode_payload(contract, record, obj):
    rule = contract["run_records"][record if record in SPECIAL else "tb"]
    require(pointer(obj, rule["version_pointer"]) == rule["version"], "SCHEMA", rule["version_pointer"])
    return decode_fields(contract, rule["fields"], obj)



# R07 公开协议：从固定字段指针构建闭合对象；只有显式列出的业务容器可作叶。
PUBLIC_TOKEN = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._:/+@~=%#\[\]-]{0,191}")


def _public_fields(contract, fields, obj, *, version_pointer=None, item_source=None):
    rules = {}
    if version_pointer is not None:
        rules[version_pointer] = {}
    rules.update((rule["pointer"], rule) for rule in fields.values())
    tree = {}
    for path, rule in rules.items():
        branch = tree
        for part in path.split("/")[1:]:
            branch = branch.setdefault(part.replace("~1", "/").replace("~0", "~"), {})
        branch[None] = rule

    def walk(shape, value, field=None):
        rule = shape.get(None, {})
        keys = shape.keys() - {None}
        if keys:
            require(isinstance(value, dict) and value.keys() == keys,
                    "RECORD_PUBLIC_SCHEMA", "unknown or missing fields")
            for key in keys:
                walk(shape[key], value[key], key)
        elif child := rule.get("decode_as"):
            if rule["type"] == "object-array":
                for item in value:
                    _public_fields(contract, contract["item_sources"][child], item, item_source=child)
            else:
                _public_fields(contract, contract["item_sources"][child], value, item_source=child)
        elif rule.get("type") == "object":
            validators = {
                "conditions": lambda v: v.keys() <= {"processes"} and
                all(type(n) is int and n > 0 for n in v.values()),
                "output": lambda v: v.keys() <= {"samples"} and
                all(isinstance(seq, list) and all(type(n) in (int, float) for n in seq)
                    for seq in v.values()),
            }
            require(field in validators and validators[field](value), "RECORD_PUBLIC_SCHEMA", "business object")
        elif field == "send_refusal_detail":
            # 仅收枚举式 refusal class；详细错误可能含请求或凭据。
            require(value is None, "RECORD_PUBLIC_SCHEMA", "refusal detail")
        elif item_source == "tb.key" and field == "basis_path":
            # R03 出处是仓内路径（可从 .chanlun 开始），不是业务 token。
            try:
                path_name(value)
            except Invalid as error:
                raise Invalid("RECORD_PUBLIC_SCHEMA: basis path") from error
            require(not re.match(r"[A-Za-z]:", value) and not re.search(r"[\x7f-\x9f]", value),
                    "RECORD_PUBLIC_SCHEMA", "basis path")
        elif item_source == "tb.key" and field == "basis_pointer":
            require(typed(value, "pointer") and not re.search(r"[\x00-\x1f\x7f-\x9f]", value),
                    "RECORD_PUBLIC_SCHEMA", "basis pointer")
        elif rule.get("type") in ("string", "nullable-string", "profile-id", "nullable-profile-id", "pointer"):
            require(value is None or (value == "" and rule["type"] == "pointer") or
                    (isinstance(value, str) and PUBLIC_TOKEN.fullmatch(value.lstrip("/") if rule["type"] == "pointer" else value)),
                    "RECORD_PUBLIC_SCHEMA", "business token")

    walk(tree, obj)


def record_r03_bindings(registry, record, profile_id):
    """从已通过静态门的 F 登记册选择该记录 TB 与运行域的出处。"""
    if not (tb := RECORD.fullmatch(record or "")):
        return set()
    return {
        (binding["slice_id"], key["kind"], key["id"], binding["basis"]["path"], binding["basis"]["pointer"])
        for binding in registry["bindings"] if binding["slice_id"] == tb[2]
        if any((d["evidence_class"], d["profile_id"]) == (tb[1], profile_id) and d["result"] != "BOUNDED_DEFERRED"
               for d in binding["domains"])
        for key in binding["keys"]
    }


def public_payload(contract, record, obj, *, allowed_r03=()):
    payload = decode_payload(contract, record, obj)
    rule = contract["run_records"][record if record in SPECIAL else "tb"]
    _public_fields(contract, rule["fields"], obj, version_pointer=rule["version_pointer"])
    if tb := RECORD.fullmatch(record):
        for key in payload["keys"]:
            identity = (key["slice_id"], key["kind"], key["id"], key["basis_path"], key["basis_pointer"])
            require(key["slice_id"] == tb[2] and identity in allowed_r03, "BASIS_MISMATCH", "TB record key provenance")
    return payload

def decode_legacy(root, contract, identity, issues, comments):
    # issues/comments 以 GitHub 记录身份索引；调用方须完整取回分页。
    rule = contract["legacy_sources"][identity]
    if rule["kind"] == "git-blob":
        raw = git_blob(root, rule["commit"], rule["path"])
        require(sha(raw) == rule["sha256"], "LEGACY_DISPOSITION", identity)
        value = raw if rule["pointer"] is None else pointer(strict_json(raw, identity), rule["pointer"])
    else:
        ticket, comment = rule["ticket"], rule["comment_id"]
        document = issues.get(ticket) if comment is None else comments.get((ticket, comment))
        require(isinstance(document, dict), "LEGACY_DISPOSITION", identity)
        value = pointer(document, rule["pointer"])
        require(isinstance(value, str) and sha(value.encode()) == rule["sha256"],
                "LEGACY_DISPOSITION", identity)
    require(typed(value, rule["type"]), "LEGACY_DISPOSITION", identity)
    return value


def own_1279_obligations(root, contract, issues, comments):
    """只生成自有清单身份；业务是否实测完成仍由 #1391/#1403 判断。"""
    section = contract["issue_1279"]
    issue = issues.get(1279, {})
    state = section["state_source"]
    require(pointer(issue, state["pointer"]) == state["expected"], "LEGACY_DISPOSITION", "ticket:1279")
    sources = [*section["release_disposition"]["known_historical_comments"], "i1279"]
    expected = {(1279, contract["legacy_sources"][s]["comment_id"]) for s in sources if s != "i1279"}
    require({key for key in comments if key[0] == 1279} == expected, "LEGACY_DISPOSITION", "ticket:1279/comments")
    documents = {s: decode_legacy(root, contract, s, issues, comments) for s in sources}
    result = []
    for row in section["own_checklist"]:
        comment = contract["legacy_sources"][row["source"]]["comment_id"]
        lines = documents[row["source"]].splitlines()
        require(len(lines) >= row["line"] and lines[row["line"] - 1].strip(), "LEGACY_DISPOSITION", "ticket:1279")
        result.append(f"ISSUE_1279:{comment}/{row['entry']}")
    return sorted(result, key=str.encode)


def scope_key(slice_id, kind, identity, *, basis=None, domain=None):
    key = f"key:{slice_id}/{kind}/{key_token(identity)}"
    if basis is not None:
        key += f"@basis:{key_token(basis[0])}@{key_token(basis[1])}"
    if domain is not None:
        key += f"@{domain[0]}@{profile_token(domain[1])}"
    return key


def profile_token(value):
    require(value is None or profile(value), "SCHEMA", "profile_id")
    return "none" if value is None else value


def scope_ticket(number, obligation=None):
    suffix = "" if obligation is None else "@" + obligation.replace("%", "%25").replace("@", "%40")
    return f"ticket:{number}{suffix}"


def scope_slot(record, profile_id):
    return f"slot:{record}@{profile_token(profile_id)}"


def anchor(root, head, p0, g0, path):
    """定位 F 第一父链上最近的路径 mode/blob 修改，不替代 R09 的服务端等价核。"""
    commits = git(root, "rev-list", "--first-parent", head, "^" + p0).decode().splitlines()
    require(commits and commits[-1] == g0
            and git(root, "rev-parse", f"{g0}^1").decode().strip() == p0,
            "REGISTRY_INVALID", path)
    git_blob(root, head, path)  # 普通文件且必须存在。
    previous = tree_entry(root, head, path)
    for commit, parent in zip(commits, commits[1:] + [p0]):
        entry = tree_entry(root, parent, path)
        if entry != previous:
            return commit
    raise Invalid(f"REGISTRY_INVALID: {path} has no G0..F anchor")


def from_f(root, head, p0, g0, accepted_anchors):
    # accepted_anchors 来自消费者各自的 R09，不是报告或调用者自报的布尔值。
    try:
        raw = git_blob(root, head, REGISTRY)
        reg = strict_json(raw, REGISTRY)
        validate_schema(root, "registry", reg, "REGISTRY_INVALID", commit=head)
        adapter_raw = git_blob(root, head, ADAPTER)
    except (ValueError, OSError) as error:
        raise Invalid("REGISTRY_INVALID: F registry or adapter blob") from error
    data = validate_adapter(root, adapter_raw, reg["adapter_contract_sha256"], commit=head)
    for path in (REGISTRY, ADAPTER):
        changed_at = anchor(root, head, p0, g0, path)
        require(changed_at in accepted_anchors, "REVIEW_FINAL_PRODUCT", path)
    return data


def _signed_authority(contract, rule, comment, *, repo, profile_id, now):
    require(rule["comment_id"] is not None and rule["body_sha256"] is not None, "AUTH_REQUIRED", f"ticket:{rule['ticket']}")
    require(isinstance(comment, dict) and comment.get("id") == rule["comment_id"]
            and str(comment.get("issue_url", "")).casefold() ==
            f"https://api.github.com/repos/{repo}/issues/{rule['ticket']}".casefold(), "AUTH_REQUIRED", f"ticket:{rule['ticket']}")
    body = comment.get("body")
    require(isinstance(body, str) and sha(body.encode()) == rule["body_sha256"], "AUTH_REQUIRED", f"ticket:{rule['ticket']}")
    fence = rule["signature_fence"]
    match = re.fullmatch(r"```" + re.escape(fence) + r"\n(.+)\n```\n?", body, re.DOTALL)
    require(match is not None, "AUTH_REQUIRED", f"ticket:{rule['ticket']}")
    raw = strict_json(match[1].encode(), f"ticket:{rule['ticket']}")
    require(raw.keys() == contract["experiment_authorization"]["fields"].keys(), "AUTH_REQUIRED", f"ticket:{rule['ticket']}")
    auth = decode_fields(contract, contract["experiment_authorization"]["fields"], raw)
    require(auth["schema_version"] == fence and auth["profile_id"] == profile_id
            and auth["runner_group"] != "Default" and auth["runner_label"] != "self-hosted"
            and all(NAME.fullmatch(auth[k]) for k in ("runner_group", "runner_label"))
            and auth["actions"] and len(auth["actions"]) == len(set(auth["actions"]))
            and set(auth["actions"]) <= {"query", "place", "cancel", "reduce_only_close"}
            and timestamp(auth["not_before"]) <= timestamp(now) < timestamp(auth["expires_at"]),
            "AUTH_REQUIRED", f"ticket:{rule['ticket']}")
    return auth


def require_query_only(contract, groups):
    rule = contract["experiment_authorization"]
    declared = rule["group_actions"]
    require(groups and all(group in declared for group in groups), "AUTH_REQUIRED", "experiment group scope")
    # pin 只固定授权原文。接入 #1412 的实际逐动作调用门之前，不能解锁任何外效。
    require(all(declared[group] == ["query"] for group in groups),
            "AUTH_REQUIRED", "ticket:1412/per-action gate not connected")


def experiment_authority(contract, comments, *, repo, profile_id, now, groups):
    require_query_only(contract, groups)
    rule = contract["experiment_authorization"]
    auth = _signed_authority(contract, rule, comments.get(2133), repo=repo, profile_id=profile_id, now=now)
    require("query" in auth["actions"], "AUTH_REQUIRED", "ticket:2133/actions")
    return auth


def canonical_rows(rows, identity):
    """去精确重项；身份相同但内容不同的证据不靠分页顺序决胜。"""
    by_key = {}
    conflict = set()
    for row in rows:
        key = identity(row)
        if key in by_key and json_bytes(by_key[key]) != json_bytes(row):
            conflict.add(key)
        by_key[key] = row
    return [by_key[k] for k in sorted(by_key) if k not in conflict], sorted(conflict)


def report_mismatches(actual, expected, ptr=""):
    def token(s):
        return s.replace("~", "~0").replace("/", "~1")
    if type(actual) is not type(expected):
        return [ptr]
    if isinstance(actual, dict):
        return [entry for key in sorted(actual.keys() | expected.keys(), key=str.encode)
                for entry in (report_mismatches(actual[key], expected[key], ptr + "/" + token(key))
                              if key in actual and key in expected else [ptr + "/" + token(key)])]
    if isinstance(actual, list):
        return ([ptr] if len(actual) != len(expected) else
                [entry for i, (a, b) in enumerate(zip(actual, expected))
                 for entry in report_mismatches(a, b, ptr + "/" + str(i))])
    return [] if actual == expected else [ptr]
