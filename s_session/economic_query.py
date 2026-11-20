"""#1374：只读组合独立 E/B 权威图像，不持写连接、不运行经济 reducer。"""

from collections import OrderedDict
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import base64
import copy
import hashlib
import json
from pathlib import Path
import re
import threading
import time
import uuid

from s_socket_client import canonical, decode_frame, digest, exchange, validate_reply


class EconomicQueryError(ValueError):
    pass


def integer(value, field, *, positive=False):
    if type(value) is not str or not re.fullmatch(r"0|[1-9][0-9]*", value):
        raise EconomicQueryError(field + " 须为规范非负整数文本")
    result = int(value)
    if result > 2**63 - 1 or (positive and result == 0):
        raise EconomicQueryError(field + " 越出范围")
    return result


def text(value, field):
    if type(value) is not str or not value:
        raise EconomicQueryError(field + " 缺失")
    return value


def verify_cut(cut, domain):
    if type(cut) is not dict or set(cut) != {"domain_id", "commit_seq", "root_hash"}:
        raise EconomicQueryError("经济 cut 字段不完整或多余")
    if cut["domain_id"] != domain:
        raise EconomicQueryError("经济 cut 属于其他域")
    integer(cut["commit_seq"], "commit_seq")
    if type(cut["root_hash"]) is not str or not re.fullmatch(r"[0-9a-f]{64}", cut["root_hash"]):
        raise EconomicQueryError("经济 cut 缺少完整根摘要")
    return cut


def economic_revisions(manifest: Mapping[str, object]) -> tuple[str, str]:
    """按冻结 manifest 分派，与 Rust Config 域选择同义；不从响应猜版本。"""
    protocol = manifest.get("protocol_revision")
    if protocol is None:
        protocol = "economic-session/1"
    if type(protocol) is not str or protocol not in ("economic-session/1", "economic-session/2"):
        raise EconomicQueryError("未知经济会话版本")
    finance_revision = "tb03b-finance/2" if protocol == "economic-session/2" else "tb03b-finance/1"
    finance = manifest.get("finance")
    if finance is None:
        if protocol == "economic-session/2":
            raise EconomicQueryError("economic-session/2 必须冻结 tb03b-finance/2")
    elif type(finance) is not dict:
        raise EconomicQueryError("经济会话与财务版本混搭或未知")
    elif protocol == "economic-session/1" and finance.get("schema_revision") == "tb03b-finance/3":
        # #1716 I1-C：/1 域显式选择的窄测试臂（签署 cap 原子激活）；/1、/2 不变。
        finance_revision = "tb03b-finance/3"
    elif protocol == "economic-session/2" and finance.get("schema_revision") == "tb03b-finance/4":
        # #1716 I1-C：/2 内容域显式选择的新合同（/2 全部语义 + 签署 cap 原子激活）。
        finance_revision = "tb03b-finance/4"
    elif protocol == "economic-session/1" and finance.get("schema_revision") in ("tb03b-finance/5", "tb03b-finance/6"):
        # #1407 C2/C3：/1 域显式选择的 E 精确命令生产者（/5 保留旧命令与收据；/6 命令体固化 model_ref）。
        finance_revision = finance["schema_revision"]
    elif finance.get("schema_revision") != finance_revision:
        raise EconomicQueryError("经济会话与财务版本混搭或未知")
    return protocol, finance_revision


TB03C_BOOKS = ("tb03c-book/1", "tb03c-book/2", "tb03c-book/3")


def book_revision(manifest):
    """#1406/#1620/#1715：null/缺省仍属旧书账。Rust book::rules 认 tb03c-book/1、/2（C8 资金签署）
    与 /3（/2 + 逐重数量定标）；本读者接受三者——/2、/3 只在公共查询字段上与 /1 等效
    （不处理资金合同或定标，只读取公共图像）。"""
    revision = manifest.get("book_revision")
    if revision is not None and (type(revision) is not str or revision not in TB03C_BOOKS):
        raise EconomicQueryError("未知书账版本")
    return revision


def _exact(value, fields, name):
    if type(value) is not dict or set(value) != fields:
        raise EconomicQueryError(name + " 字段不完整或多余")


def _hash(value, name):
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise EconomicQueryError(name + " 不是完整摘要")


def _signed_integer(value, name):
    if type(value) is not str or re.fullmatch(r"0|-?[1-9][0-9]*", value) is None:
        raise EconomicQueryError(name + " 须为规范整数文本")
    if not -(2**63) <= int(value) < 2**63:
        raise EconomicQueryError(name + " 越出范围")


def allocation_sources(manifest, revision):
    """冻结来源身份，不实现份额或金额 reducer。无政策的清单仍可等待。
    #1620/#1715：tb03c-book/2、/3 在外效分配字段上与 /1 等效（资金签署与数量定标不影响此读者）。"""
    if "fill_manifests" not in manifest and "fill_allocation_policy" not in manifest:
        return None, {}
    if revision not in TB03C_BOOKS:
        raise EconomicQueryError("外效分配来源须冻结 tb03c-book/1、/2 或 /3")
    policy = manifest.get("fill_allocation_policy")
    policies = {"netted": "frozen-manifest-proportional-cumulative/2",
                "per_leg": "per-leg-source-attribution/1"}
    if "fill_allocation_policy" in manifest:
        _exact(policy, {"fill_allocation_policy_id", "policy_revision"}, "分配政策")
        if policy["fill_allocation_policy_id"] not in policies.values():
            raise EconomicQueryError("未知分配政策")
        text(policy["policy_revision"], "policy_revision")
    manifests = manifest.get("fill_manifests")
    if type(manifests) is not list:
        raise EconomicQueryError("fill_manifests 须为数组")
    result = {}
    for source in manifests:
        _exact(source, {"projection_kind", "symbol", "participants", "tie_break_order", "manifest_hash"}, "投影清单")
        kind = source["projection_kind"]
        if type(kind) is not str or kind not in policies:
            raise EconomicQueryError("未知投影类型")
        if policy is not None and policy["fill_allocation_policy_id"] != policies[kind]:
            raise EconomicQueryError("投影与分配政策混搭")
        text(source["symbol"], "symbol")
        _hash(source["manifest_hash"], "manifest_hash")
        if (source["manifest_hash"] != digest({k: v for k, v in source.items() if k != "manifest_hash"})
                or source["manifest_hash"] in result):
            raise EconomicQueryError("投影清单摘要不同或重复")
        if type(source["participants"]) is not list or not source["participants"]:
            raise EconomicQueryError("投影参与重缺失")
        ids = []
        for participant in source["participants"]:
            _exact(participant, {"chong_id", "command_id", "family_id", "revision", "requested_q"}, "参与重")
            for field in ("chong_id", "command_id", "family_id", "revision"):
                text(participant[field], field)
            integer(participant["requested_q"], "requested_q", positive=True)
            matches = [r for r in manifest.get("chongs", []) if type(r) is dict
                       and r.get("chong_id") == participant["chong_id"]]
            if len(matches) != 1 or matches[0].get("symbol") != source["symbol"]:
                raise EconomicQueryError("投影参与重与冻结路由不同")
            ids.append(participant["chong_id"])
        if len(set(ids)) != len(ids) or source["tie_break_order"] != sorted(ids):
            raise EconomicQueryError("投影参与重重复或并列顺序不同")
        result[source["manifest_hash"]] = copy.deepcopy(source)
    return copy.deepcopy(policy), result


_SOURCE_ID = ("source_namespace", "source_epoch", "external_fact_id")


def _source_key(source):
    if type(source) is not dict:
        raise EconomicQueryError("事实来源身份缺失")
    return digest([text(source.get(k), k) for k in _SOURCE_ID])


ECONOMIC_PROJECTION_REVISION = "economic-read-projection/1"
EXACT_TEXT_REPR = "ExactDecimalIntegerTextProjection"
PROJECTION_ORIGINAL_KINDS = ("fact", "allocation", "decision", "grant", "command", "model")
CUT_FIELDS = frozenset({"domain_id", "commit_seq", "root_hash"})
MAX_VERIFIED_CUTS = 64

FILL_ALLOCATION_ROW_ALLOWED = frozenset({
    "fact_key", "fact_hash", "projection_kind", "source_kind", "manifest_hash", "symbol",
    "fill_allocation_policy_id", "policy_revision", "from", "to", "report_kind", "component",
    "original_fact_key", "original_allocation_id", "command_id", "grant_id", "responsibility_ref",
    "plan_hash", "command_plan_hash", "command_hash", "evidence_id", "allocations", "x_execution_witness",
})
ALLOCATION_ITEM_ALLOWED = frozenset({
    "allocation_id", "source_kind", "chong_id", "command_id", "grant_id", "responsibility_ref",
    "family_id", "revision", "symbol", "manifest_hash", "units", "acquisition_cash", "commission",
    "fee_deferred_to_cause_fact", "reported_fill_fee", "fee_only", "fee_type", "cause",
    "original_fact_key", "original_allocation_id", "income_changes", "fill_allocation_policy_id",
    "policy_revision", "component", "reversal", "unmatched_reason", "status", "target_domain",
})
X_EXECUTION_WITNESS_ALLOWED = frozenset({
    "witness_revision", "x_profile_revision", "x_id", "x_epoch", "session_id", "session_generation",
    "source_namespace", "source_epoch", "model_content_hash", "command_id", "command_hash",
    "e_release_receipt_key", "e_release_cut", "e_release_commit_ns", "x_release_evidence",
    "x_accept_clock", "x_command_state", "x_execute_evidence", "attempt_batch_id",
    "attempt_batch_bar_index", "attempt_batch_request_sha256", "attempt_batch_receipt_sha256",
    "originals_batch_id", "originals_batch_bar_index", "originals_batch_receipt_sha256",
    "fact_raw_sha256",
})
X_ACCEPT_CLOCK_ALLOWED = frozenset({"received_ns", "first_known_ns", "commit_ns"})
X_AUTHORITY_EVIDENCE_BASE_ALLOWED = frozenset({
    "protocol", "session_id", "session_generation", "authority_id", "command_id", "command_hash",
    "state", "receipt_id", "release_receipt_id", "commit_ns",
})
X_EXECUTE_EVIDENCE_ALLOWED = frozenset({"claimed_ns", "reply"})
COMMAND_REF_ALLOWED = frozenset({"command_id", "command_hash"})
PROJECTED_RECORD_BASE_ALLOWED = frozenset({
    "fact_key", "fact_hash", "raw_sha256", "raw_utf8", "json_pointer", "event", "token",
    "target_domain", "source_event_time", "source_received_time", "source_producer",
    "origin_message", "origin_request_hash", "received_ns", "first_known_ns", "commit_ns",
    "recorded_seq", "cut", "e_domain_id", "e_session_id", "e_session_generation",
    "e_commit_proof", "e_commit_proof_omitted", "e_receipt", "e_resolution_proof",
    "source_debit_proof", "b_observation", "b_origin_message", "b_origin_request_hash",
})


def _assert_whitelist_keys(obj, allowed, label):
    if type(obj) is not dict:
        raise EconomicQueryError(f"{label} 必须为对象")
    for k in sorted(obj):
        if k not in allowed:
            raise EconomicQueryError(f"{label} 存在未声明字段（不在读权白名单内）：{k}")


def _verify_protocol_response_cuts(
    body,
    vector_cuts,
    known_domains,
    *,
    verify_historical=None,
    own_domain_limit=None,
):
    """不变量 A + 回执域归属（按协议结构位置校验，绝不把来源数据内同名字段当成协议回执）。"""

    def check_cut(node, expected_domain=None):
        if type(node) is not dict or set(node) != CUT_FIELDS:
            raise EconomicQueryError("内嵌 cut 字段不完整或多余")
        rdomain = node.get("domain_id")
        if expected_domain is not None and rdomain != expected_domain:
            raise EconomicQueryError(f"回执域与期望域不符：期望 {expected_domain}，实际 {rdomain}")
        if type(rdomain) is not str or (known_domains is not None and rdomain not in known_domains):
            raise EconomicQueryError(f"回执所属域 {rdomain} 不在固定向量中")
        verified_rcut = verify_cut(node, rdomain)
        rseq = int(verified_rcut["commit_seq"])
        if own_domain_limit is not None and rdomain == own_domain_limit[0]:
            own_cut = own_domain_limit[1]
            own_seq = int(own_cut["commit_seq"])
            if rseq > own_seq:
                raise EconomicQueryError(
                    f"MissingDependency：回执({rdomain}:{rseq})晚于固定切面({rdomain}:{own_seq})，拒绝未来回执（向量未就绪）"
                )
            if rseq == own_seq and verified_rcut != own_cut:
                raise EconomicQueryError(f"IdentityConflict：同序号回执({rdomain}:{rseq})根与固定切面根不符")
        bound = vector_cuts.get(rdomain)
        if bound is not None:
            cseq = int(bound["commit_seq"])
            if rseq > cseq:
                raise EconomicQueryError(
                    f"MissingDependency：回执({rdomain}:{rseq})晚于固定切面({rdomain}:{cseq})，拒绝未来回执（向量未就绪）"
                )
            if rseq == cseq:
                if verified_rcut != bound:
                    raise EconomicQueryError(f"IdentityConflict：同序号回执({rdomain}:{rseq})根与固定切面根不符")
            elif verify_historical is not None:
                verify_historical(rdomain, verified_rcut)

    def check_finance_record(rec, owner_domain):
        if type(rec) is not dict:
            return
        if rec.get("prepared_cut") is not None:
            exp = rec.get("owner") if type(rec.get("owner")) is str else owner_domain
            check_cut(rec["prepared_cut"], exp)
        if rec.get("commit_cut") is not None:
            exp = rec.get("owner") if type(rec.get("owner")) is str else None
            check_cut(rec["commit_cut"], exp)
        grant = rec.get("grant")
        if type(grant) is dict:
            if grant.get("e_cut") is not None:
                check_cut(grant["e_cut"], "E")
            orig_g = grant.get("original")
            if type(orig_g) is dict and orig_g.get("prepared_cut") is not None:
                exp = orig_g.get("owner") if type(orig_g.get("owner")) is str else owner_domain
                check_cut(orig_g["prepared_cut"], exp)
        lcr = rec.get("local_commit_receipt")
        if type(lcr) is dict and lcr.get("e_cut") is not None:
            check_cut(lcr["e_cut"], "E")
        grants = rec.get("grants")
        if type(grants) is list:
            for g in grants:
                if type(g) is dict and g.get("prepared_cut") is not None:
                    exp = g.get("owner") if type(g.get("owner")) is str else None
                    check_cut(g["prepared_cut"], exp)

    def check_receipt(rec, expected_domain=None):
        if type(rec) is not dict:
            raise EconomicQueryError("回执非对象")
        rcut = rec.get("cut")
        if type(rcut) is not dict or set(rcut) != CUT_FIELDS:
            raise EconomicQueryError("回执缺失合法 cut")
        rdomain = rec.get("domain_id")
        if rdomain is not None:
            if type(rdomain) is not str:
                raise EconomicQueryError("回执 domain_id 非文本")
            if rdomain != rcut["domain_id"]:
                raise EconomicQueryError(f"回执域 {rdomain} 与 cut 域 {rcut['domain_id']} 不符")
            if expected_domain is not None and rdomain != expected_domain:
                raise EconomicQueryError(f"回执域与期望域不符：期望 {expected_domain}，实际 {rdomain}")
        check_cut(rcut, expected_domain)
        if type(rec.get("record")) is dict:
            check_finance_record(rec["record"], rdomain or rcut["domain_id"])

    def check_fill_row(row):
        if type(row) is not dict:
            return
        w = row.get("x_execution_witness")
        if type(w) is dict and w.get("e_release_cut") is not None:
            check_cut(w["e_release_cut"], "E")

    def check_peer_proof(p):
        if type(p) is not dict:
            return
        pdom = p.get("domain_id") if type(p.get("domain_id")) is str else None
        if p.get("current_cut") is not None:
            check_cut(p["current_cut"], pdom)
        if p.get("receipt") is not None:
            check_receipt(p["receipt"], pdom)
        if type(p.get("image")) is dict:
            check_image(p["image"], pdom)
        if type(p.get("current_image")) is dict:
            check_image(p["current_image"], pdom)

    def check_record(rec):
        if type(rec) is not dict:
            return
        # 仅检查协议证据路径，绝不解释来源数据（event / raw_utf8 / raw_exact_text）中的同名键。
        if rec.get("cut") is not None:
            check_cut(rec["cut"], "E")
        if rec.get("e_receipt") is not None:
            check_receipt(rec["e_receipt"], "E")
        erp = rec.get("e_resolution_proof")
        if type(erp) is dict:
            if erp.get("receipt") is not None:
                check_receipt(erp["receipt"], "E")
            if type(erp.get("image")) is dict:
                check_image(erp["image"], "E")
            if type(erp.get("previous_image")) is dict:
                check_image(erp["previous_image"], "E")
        ecp = rec.get("e_commit_proof")
        if type(ecp) is dict and type(ecp.get("image")) is dict:
            check_image(ecp["image"], "E")
        sdp = rec.get("source_debit_proof")
        if type(sdp) is dict:
            sd = sdp.get("domain_id") if type(sdp.get("domain_id")) is str else None
            if sdp.get("receipt") is not None:
                check_receipt(sdp["receipt"], sd)
            if type(sdp.get("image")) is dict:
                check_image(sdp["image"], sd)
            if type(sdp.get("previous_image")) is dict:
                check_image(sdp["previous_image"], sd)

    def check_image(img, owner_domain):
        if type(img) is not dict:
            return
        book = img.get("book")
        if type(book) is dict:
            ofr = book.get("opening_fact_ref")
            if type(ofr) is dict and ofr.get("e_cut") is not None:
                check_cut(ofr["e_cut"], "E")
            for list_key in ("known_cost_components", "cost_events"):
                items = book.get(list_key)
                if type(items) is list:
                    for item in items:
                        if type(item) is dict:
                            deriv = item.get("derivation")
                            if type(deriv) is dict and deriv.get("resolve_cut") is not None:
                                check_cut(deriv["resolve_cut"], "E")
            voice = book.get("voice")
            if type(voice) is dict and type(voice.get("identity")) is dict:
                ob = voice["identity"].get("opening_basis")
                if type(ob) is dict and ob.get("e_cut") is not None:
                    check_cut(ob["e_cut"], "E")
        for list_key in ("recorded", "pending"):
            recs = img.get(list_key)
            if type(recs) is list:
                for rec in recs:
                    check_record(rec)
        rows = img.get("fill_allocations")
        if type(rows) is list:
            for row in rows:
                check_fill_row(row)
        fin = img.get("finance")
        if type(fin) is dict:
            if type(fin.get("decisions")) is list:
                for d in fin["decisions"]:
                    check_finance_record(d, owner_domain)
            if type(fin.get("slots")) is list:
                for s in fin["slots"]:
                    if type(s) is dict and type(s.get("grants")) is list:
                        for g in s["grants"]:
                            check_finance_record(g, owner_domain)
            if type(fin.get("commands")) is list:
                for c in fin["commands"]:
                    check_finance_record(c, owner_domain)
        hist = img.get("history")
        if type(hist) is list:
            for h in hist:
                if type(h) is not dict:
                    continue
                ws = h.get("x_execution_witnesses")
                if type(ws) is dict:
                    for w in ws.values():
                        if type(w) is dict and w.get("e_release_cut") is not None:
                            check_cut(w["e_release_cut"], "E")
                if type(h.get("record")) is dict:
                    check_finance_record(h["record"], owner_domain)
                hw = h.get("witness")
                if type(hw) is dict:
                    if type(hw.get("prepared_proofs")) is list:
                        for p in hw["prepared_proofs"]:
                            check_peer_proof(p)
                    if type(hw.get("grant_proof")) is dict:
                        check_peer_proof(hw["grant_proof"])
                    if type(hw.get("commit_proof")) is dict:
                        check_peer_proof(hw["commit_proof"])

    def check_original(orig, domain_id, original_kind):
        if type(orig) is not dict:
            raise EconomicQueryError("原件载荷非对象")
        okind = original_kind or {
            "EconomicFactAtCut": "fact",
            "EconomicAllocationAtCut": "allocation",
            "EconomicModelAtCut": "model",
            "EconomicDecision": "decision",
            "EconomicGrant": "grant",
            "EconomicCommand": "command",
        }.get(orig.get("kind"))
        if okind == "fact":
            if orig.get("domain_id") is not None and orig.get("domain_id") != domain_id:
                raise EconomicQueryError(f"回执域与期望域不符：期望 {domain_id}，实际 {orig.get('domain_id')}")
            receipts = orig.get("receipts")
            if type(receipts) is not list:
                raise EconomicQueryError("同切面事实缺回执列表")
            for r in receipts:
                exp = "E" if domain_id == "E" else ("E" if type(r) is dict and r.get("kind") == "Recorded" else domain_id)
                check_receipt(r, exp)
            if orig.get("projected_record") is not None:
                check_record(orig["projected_record"])
            if orig.get("fill_allocation_row") is not None:
                check_fill_row(orig["fill_allocation_row"])
        elif okind == "allocation":
            if orig.get("domain_id") is not None and orig.get("domain_id") != domain_id:
                raise EconomicQueryError(f"回执域与期望域不符：期望 {domain_id}，实际 {orig.get('domain_id')}")
            if domain_id == "E":
                check_receipt(orig.get("resolve_receipt"), "E")
                if orig.get("fill_allocation_row") is not None:
                    check_fill_row(orig["fill_allocation_row"])
            else:
                check_receipt(orig.get("receipt"), domain_id)
            if orig.get("fact") is not None:
                check_original(orig["fact"], domain_id, "fact")
        elif okind == "model":
            if orig.get("domain_id") is not None and orig.get("domain_id") != domain_id:
                raise EconomicQueryError(f"回执域与期望域不符：期望 {domain_id}，实际 {orig.get('domain_id')}")
        elif okind == "decision":
            if orig.get("domain_id") is not None and orig.get("domain_id") != domain_id:
                raise EconomicQueryError(f"回执域与期望域不符：期望 {domain_id}，实际 {orig.get('domain_id')}")
            receipts = orig.get("receipts")
            if type(receipts) is not list:
                raise EconomicQueryError("决定原件缺回执列表")
            for r in receipts:
                check_receipt(r, domain_id)
            if type(orig.get("decision")) is dict:
                check_finance_record(orig["decision"], domain_id)
        elif okind == "grant":
            if domain_id != "E" or (orig.get("domain_id") is not None and orig.get("domain_id") != "E"):
                raise EconomicQueryError(f"回执域与期望域不符：期望 E，实际 {orig.get('domain_id')}")
            check_receipt(orig.get("receipt"), "E")
            if type(orig.get("grant")) is dict:
                check_finance_record(orig["grant"], "E")
        elif okind == "command":
            if domain_id != "E" or (orig.get("domain_id") is not None and orig.get("domain_id") != "E"):
                raise EconomicQueryError(f"回执域与期望域不符：期望 E，实际 {orig.get('domain_id')}")
            if orig.get("cut") is not None:
                check_cut(orig["cut"], "E")
            if type(orig.get("receipts")) is list:
                for r in orig["receipts"]:
                    check_receipt(r, "E")
            if type(orig.get("record")) is dict:
                check_finance_record(orig["record"], "E")
        else:
            raise EconomicQueryError(f"未知原件类型：{orig.get('kind')}")

    kind = body.get("kind")
    if kind in ("EconomicSnapshot", "EconomicProjection"):
        for domain, view in sorted(body.get("domains", {}).items()):
            if type(view) is dict and view.get("status") == "Available":
                check_cut(view.get("cut"), domain)
                check_image(view.get("image" if kind == "EconomicSnapshot" else "projection"), domain)
    elif kind == "EconomicWatch":
        for domain, view in sorted(body.get("domains", {}).items()):
            if type(view) is dict and view.get("status") == "Available":
                check_cut(view.get("base_cut"), domain)
                check_cut(view.get("next_cut"), domain)
                for change in view.get("changes", []):
                    check_cut(change.get("cut"), domain)
                    check_image(change.get("image"), domain)
    elif kind in ("EconomicProjectionOriginal", "EconomicOriginal"):
        for domain, c in sorted(body.get("cuts", {}).items()):
            check_cut(c, domain)
        check_original(body.get("original"), body.get("domain_id"), body.get("original_kind"))
    elif kind == "_WatchChangeImage":
        check_image(body.get("image"), body.get("domain_id"))


def _verify_fill_allocation_row_whitelist(row, has_cmd):
    _assert_whitelist_keys(row, FILL_ALLOCATION_ROW_ALLOWED, "fill_allocation_row")
    allocs = row.get("allocations")
    if type(allocs) is list:
        for item in allocs:
            _assert_whitelist_keys(item, ALLOCATION_ITEM_ALLOWED, "fill_allocation_row.allocations[]")
    witness = row.get("x_execution_witness")
    if witness is not None:
        _assert_whitelist_keys(witness, X_EXECUTION_WITNESS_ALLOWED, "x_execution_witness")
        if witness.get("e_release_cut") is not None:
            _assert_whitelist_keys(witness["e_release_cut"], CUT_FIELDS, "x_execution_witness.e_release_cut")
        if witness.get("x_accept_clock") is not None:
            _assert_whitelist_keys(witness["x_accept_clock"], X_ACCEPT_CLOCK_ALLOWED, "x_execution_witness.x_accept_clock")
        auth_allowed = (
            X_AUTHORITY_EVIDENCE_BASE_ALLOWED | {"command"}
            if has_cmd
            else X_AUTHORITY_EVIDENCE_BASE_ALLOWED | {"command_ref"}
        )
        rel = witness.get("x_release_evidence")
        if rel is not None:
            if not has_cmd and rel.get("command") is not None:
                raise EconomicQueryError("未获准 QueryCommand 却在内嵌执行见证中返回完整命令")
            _assert_whitelist_keys(rel, auth_allowed, "x_release_evidence")
            if rel.get("command_ref") is not None:
                _assert_whitelist_keys(rel["command_ref"], COMMAND_REF_ALLOWED, "x_release_evidence.command_ref")
        ex = witness.get("x_execute_evidence")
        if ex is not None:
            _assert_whitelist_keys(ex, X_EXECUTE_EVIDENCE_ALLOWED, "x_execute_evidence")
            rep = ex.get("reply")
            if rep is not None:
                if not has_cmd and rep.get("command") is not None:
                    raise EconomicQueryError("未获准 QueryCommand 却在内嵌执行见证中返回完整命令")
                _assert_whitelist_keys(rep, auth_allowed, "x_execute_evidence.reply")
                if rep.get("command_ref") is not None:
                    _assert_whitelist_keys(rep["command_ref"], COMMAND_REF_ALLOWED, "x_execute_evidence.reply.command_ref")


def _verify_original_permission_bounds(original, ops):
    """不变量 B（Q 出口后置校验）：按结构位置与正向白名单核验同切面原件不含未获准类别载荷或未声明字段。"""
    if type(original) is not dict:
        return
    restricted = isinstance(ops, (set, frozenset))
    has_fact = (not restricted) or ("QueryFact" in ops)
    has_cmd = (not restricted) or ("QueryCommand" in ops)
    has_alloc = (not restricted) or ("QueryAllocation" in ops)
    has_dec = (not restricted) or ("QueryDecision" in ops)
    has_grant = (not restricted) or ("QueryGrant" in ops)

    def check_orig(obj):
        if type(obj) is not dict:
            return
        kind = obj.get("kind")
        if not has_fact:
            if (kind == "EconomicFactAtCut"
                    or obj.get("raw_utf8") is not None
                    or obj.get("raw_exact_text") is not None
                    or obj.get("model_raw_utf8") is not None
                    or obj.get("model_exact_text") is not None
                    or obj.get("projected_record") is not None
                    or obj.get("fact") is not None):
                raise EconomicQueryError("未获准 QueryFact 却返回事实或模型原字节")
        if not has_cmd and kind == "EconomicCommand":
            raise EconomicQueryError("未获准 QueryCommand 却返回命令原件")
        if not has_alloc:
            if kind == "EconomicAllocationAtCut" or obj.get("fill_allocation_row") is not None:
                raise EconomicQueryError("未获准 QueryAllocation 却返回分配原件")
        if not has_dec and kind == "EconomicDecision":
            raise EconomicQueryError("未获准 QueryDecision 却返回决定原件")
        if not has_grant and kind == "EconomicGrant":
            raise EconomicQueryError("未获准 QueryGrant 却返回授信原件")

        if obj.get("fill_allocation_row") is not None:
            _verify_fill_allocation_row_whitelist(obj["fill_allocation_row"], has_cmd)
        if obj.get("projected_record") is not None:
            prec = obj["projected_record"]
            if not has_alloc and prec.get("resolved_allocation") is not None:
                raise EconomicQueryError("未获准 QueryAllocation 却返回分配原件")
            allowed_prec = PROJECTED_RECORD_BASE_ALLOWED | (
                {"resolved_allocation"} if has_alloc else {"resolved_allocation_ref"}
            )
            _assert_whitelist_keys(prec, allowed_prec, "projected_record")
        if obj.get("fact") is not None:
            check_orig(obj["fact"])

    check_orig(original)


def _finalize_public_response(query, body, *, requested_cuts=None, verify_historical_roots=False):
    """Python Q 聚合层的唯一出口：所有离开 Q 的读侧应答（主投影、原件、快照、Watch 及一切内嵌对象）
    在缓存与发布之前均须经过此出口统一核验不变量 A（含回执域归属）与不变量 B（含递归白名单）；不满足则整个应答拒绝。"""
    if type(body) is not dict:
        raise EconomicQueryError("应答体必须为对象")
    kind = body.get("kind")
    if kind == "Gap":
        return body

    nodes = getattr(query, "nodes", None)
    known_domains = set(nodes) if isinstance(nodes, Mapping) else None
    vector_cuts = {}
    available_domains = set()

    if kind in ("EconomicProjection", "EconomicSnapshot"):
        if requested_cuts is not None:
            vector_cuts.update(requested_cuts)
        for domain, view in body.get("domains", {}).items():
            if type(view) is dict and view.get("status") == "Available":
                vector_cuts[domain] = verify_cut(view.get("cut"), domain)
                available_domains.add(domain)
    elif kind == "EconomicWatch":
        if requested_cuts is not None:
            vector_cuts.update(requested_cuts)
        for domain, view in body.get("domains", {}).items():
            if type(view) is dict and view.get("status") == "Available":
                vector_cuts[domain] = verify_cut(view.get("next_cut"), domain)
                available_domains.add(domain)
    elif kind in ("EconomicProjectionOriginal", "EconomicOriginal"):
        cuts = body.get("cuts")
        if type(cuts) is not dict:
            raise EconomicQueryError("原件应答缺固定切面向量")
        for domain, c in cuts.items():
            vector_cuts[domain] = verify_cut(c, domain)
            available_domains.add(domain)
    else:
        raise EconomicQueryError(f"未知公开经济应答类型：{kind}")

    local_verified = {(d, c["commit_seq"], c["root_hash"]) for d, c in vector_cuts.items()}

    def verify_historical(rdomain, verified_rcut):
        if not verify_historical_roots or rdomain not in available_domains:
            return
        key = (rdomain, verified_rcut["commit_seq"], verified_rcut["root_hash"])
        if key in local_verified:
            return
        if EconomicQuery._has_verified_cut(query, key):
            local_verified.add(key)
            return
        query.projection_view(rdomain, verified_rcut)
        local_verified.add(key)
        EconomicQuery._remember_verified_cut(query, key)

    if kind == "EconomicProjectionOriginal":
        _verify_original_permission_bounds(body.get("original"), getattr(query, "authorized_read_ops", None))

    _verify_protocol_response_cuts(
        body,
        vector_cuts,
        known_domains,
        verify_historical=verify_historical if verify_historical_roots else None,
    )

    if kind == "EconomicWatch":
        for domain, view in body.get("domains", {}).items():
            if type(view) is dict and view.get("status") == "Available":
                for change in view.get("changes", []):
                    _verify_protocol_response_cuts(
                        {"kind": "_WatchChangeImage", "domain_id": domain, "image": change.get("image")},
                        vector_cuts,
                        known_domains,
                        own_domain_limit=(domain, change["cut"]),
                    )

    return body


def _exact_decimal_text(value):
    if value is None or type(value) is bool or type(value) is str:
        return value
    if type(value) is int:
        return str(value)
    if type(value) is list:
        return [_exact_decimal_text(item) for item in value]
    if type(value) is dict:
        return {k: _exact_decimal_text(v) for k, v in value.items()}
    raise EconomicQueryError("精确十进制文本视图拒绝非整数数值")


def _original_event(record, *, projected=False):
    """book::fact_key + service::record_from_payload 的只读身份核验。"""
    raw = text(record.get("raw_utf8"), "raw_utf8")
    raw_hash = record.get("raw_sha256")
    _hash(raw_hash, "raw_sha256")
    pointer = text(record.get("json_pointer"), "json_pointer")
    try:
        raw_bytes = raw.encode("utf-8")
        if hashlib.sha256(raw_bytes).hexdigest() != raw_hash:
            raise EconomicQueryError("原件字节与 raw_sha256 不同")
        document = decode_frame(raw_bytes)
        # serde_json 的整数域；经济原件不接受浮点或任意精度 JSON 数字。
        pending = [document]
        while pending:
            value = pending.pop()
            if type(value) is dict:
                pending.extend(value.values())
            elif type(value) is list:
                pending.extend(value)
            elif type(value) is int and not -(2**63) <= value < 2**64:
                raise EconomicQueryError("原件 JSON 整数超出生产域")
        if document.get("format") == "history-sim-economic-originals/1":
            if pointer != "/event":
                raise EconomicQueryError("模拟原件须定位 /event")
            model = document.get("model")
            raw_event = document.get("event")
            event = record.get("event")
            if type(model) is not dict or type(raw_event) is not dict or type(event) is not dict:
                raise EconomicQueryError("模拟原件形状缺失")
            if event.get("event") != "history-sim-unresolved/1":
                raise EconomicQueryError("模拟事实事件类型不符")
            if projected:
                tv = event.get("simulation_original_text_view")
                if (type(tv) is not dict
                        or set(tv) != {"representation", "original_sha256", "value"}
                        or tv["representation"] != EXACT_TEXT_REPR
                        or tv["original_sha256"] != digest(raw_event)
                        or canonical(tv["value"]) != canonical(_exact_decimal_text(raw_event))):
                    raise EconomicQueryError("模拟投影精确文本视图与原件 /event 不符")
                reconstructed = {k: v for k, v in event.items() if k != "simulation_original_text_view"}
                reconstructed["simulation_original"] = raw_event
                event_for_hash = reconstructed
            else:
                if canonical(event.get("simulation_original")) != canonical(raw_event):
                    raise EconomicQueryError("模拟事实事件与原件 /event 不同")
                event_for_hash = event
            units = {
                "quantity": {"unit": text(model.get("quantity_unit"), "quantity_unit"), "quantum": "1"},
                "money": {"unit": text(model.get("currency"), "currency"),
                          "currency": text(model.get("currency"), "currency"), "quantum": "1"},
                "numeric_encoding": "exact_decimal_integer_text",
            }
            text(event.get("allocation_id"), "allocation_id")
            if record.get("fact_key") != _source_key(event.get("source")):
                raise EconomicQueryError("事实身份与原来源三元组不同")
            content_hash = digest({"raw_sha256": raw_hash, "json_pointer": pointer,
                                   "event": event_for_hash, "units": units})
            if record.get("fact_hash") != content_hash:
                raise EconomicQueryError("事实内容摘要与原件/指针/事件/单位不同")
            return event
        if not pointer.startswith("/events/"):
            raise EconomicQueryError("事实指针须定位 events 原件")
        if (document.get("format") != "neutral TestOnly economic raw originals; not production transport wire"
                or type(document.get("units")) is not dict):
            raise EconomicQueryError("原件 profile/单位缺失")
        selected = document
        for token in pointer[1:].split("/"):
            token = token.replace("~1", "/").replace("~0", "~")
            if type(selected) is dict and token in selected:
                selected = selected[token]
            elif (type(selected) is list and re.fullmatch(r"0|[1-9][0-9]*", token)
                  and int(token) < len(selected)):
                selected = selected[int(token)]
            else:
                raise EconomicQueryError("事实指针不可解析")
        event = record.get("event")
        if type(selected) is not dict or canonical(selected) != canonical(event):
            raise EconomicQueryError("事实事件与原件指针不同")
        text(event.get("allocation_id"), "allocation_id")
        if record.get("fact_key") != _source_key(event.get("source")):
            raise EconomicQueryError("事实身份与原来源三元组不同")
        content_hash = digest({"raw_sha256": raw_hash, "json_pointer": pointer,
                               "event": event, "units": document["units"]})
        if record.get("fact_hash") != content_hash:
            raise EconomicQueryError("事实内容摘要与原件/指针/事件/单位不同")
        return event
    except (ValueError, UnicodeError, TypeError, OverflowError) as exc:
        raise EconomicQueryError("事实原件绑定无效：" + str(exc)) from exc


def _correction_predecessor(row, event, rows, verified_event):
    """只对应具名前件和政策引用；不重放累计前沿或计算逆份额。"""
    report = event["netted_fill"]
    reference, dependency = report.get("fill_ref"), event.get("depends_on")
    _exact(reference, set(_SOURCE_ID) | {"allocation_id", "manifest_hash",
           "fill_allocation_policy_id", "policy_revision"}, "更正 fill_ref")
    _exact(dependency, set(_SOURCE_ID) | {"source_ref"}, "更正 depends_on")
    for key in reference:
        text(reference[key], key)
    text(dependency["source_ref"], "depends_on.source_ref")
    key = _source_key(dependency)
    if (key != _source_key(reference) or key != row["original_fact_key"]
            or key == row["fact_key"]):
        raise EconomicQueryError("更正具名前件与原件依赖不同")
    original = verified_event(key)
    fill = original.get("netted_fill")
    if (type(fill) is not dict or fill.get("report_kind") not in ("incremental", "cumulative")
            or integer(fill.get("from"), "原 fill.from") >= integer(fill.get("to"), "原 fill.to")):
        raise EconomicQueryError("更正前件不是普通非零净额 fill")
    if (any(reference[k] != original["source"][k] for k in _SOURCE_ID)
            or reference["allocation_id"] != original.get("allocation_id")
            or reference["manifest_hash"] != fill.get("manifest_hash")
            or report["symbol"] != fill.get("symbol")):
        raise EconomicQueryError("更正原 allocation/清单/标的不同")
    original_rows = [r for r in rows if type(r) is dict and r.get("fact_key") == key]
    if len(original_rows) != 1:
        raise EconomicQueryError("更正缺唯一原 fill 分配")
    original_row = original_rows[0]
    for field in ("manifest_hash", "fill_allocation_policy_id", "policy_revision"):
        if reference[field] != original_row.get(field) or reference[field] != row[field]:
            raise EconomicQueryError("更正政策引用与具名原分配不同")


def _verify_x_execution_witness(witness, row):
    _exact(witness, {
        "witness_revision", "x_profile_revision", "x_id", "x_epoch",
        "session_id", "session_generation", "source_namespace", "source_epoch",
        "model_content_hash", "command_id", "command_hash",
        "e_release_receipt_key", "e_release_cut", "e_release_commit_ns",
        "x_release_evidence", "x_accept_clock", "x_command_state",
        "x_execute_evidence", "attempt_batch_id", "attempt_batch_bar_index",
        "attempt_batch_request_sha256", "attempt_batch_receipt_sha256",
        "originals_batch_id", "originals_batch_bar_index",
        "originals_batch_receipt_sha256", "fact_raw_sha256",
    }, "X/3 执行因果见证")
    if witness["witness_revision"] != "x-sim-execution-witness/1":
        raise EconomicQueryError("未知 X 执行因果见证版本")
    if witness["x_profile_revision"] != "x-execution-profile/3":
        raise EconomicQueryError("模拟分配见证仅接受 x-execution-profile/3")
    if witness["command_id"] != row["command_id"] or witness["x_command_state"] != "Observed":
        raise EconomicQueryError("X/3 执行因果见证命令身份或终态不符")
    for key in ("x_id", "session_id", "source_namespace", "source_epoch",
                "e_release_receipt_key", "attempt_batch_id", "originals_batch_id"):
        text(witness[key], key)
    integer(witness["x_epoch"], "x_epoch", positive=True)
    integer(witness["session_generation"], "session_generation", positive=True)
    integer(witness["e_release_commit_ns"], "e_release_commit_ns")
    attempt_bar = integer(witness["attempt_batch_bar_index"], "attempt_batch_bar_index")
    originals_bar = integer(witness["originals_batch_bar_index"], "originals_batch_bar_index")
    if originals_bar < attempt_bar:
        raise EconomicQueryError("X/3 结果批 bar 早于占有批 bar")
    for key in ("model_content_hash", "command_hash", "attempt_batch_request_sha256",
                "attempt_batch_receipt_sha256", "originals_batch_receipt_sha256", "fact_raw_sha256"):
        _hash(witness[key], key)
    verify_cut(witness["e_release_cut"], "E")
    x_rel = witness["x_release_evidence"]
    x_exec = witness["x_execute_evidence"]
    if (type(x_rel) is not dict or x_rel.get("receipt_id") != witness["e_release_receipt_key"]
            or x_rel.get("release_receipt_id") is not None
            or x_rel.get("state") != "ReleasedExact"):
        raise EconomicQueryError("X/3 release_evidence 与 E 原放行回执不符")
    if (type(x_exec) is not dict or type(x_exec.get("reply")) is not dict
            or x_exec["reply"].get("state") != "ExecuteCommitted"
            or x_exec["reply"].get("release_receipt_id") != witness["e_release_receipt_key"]
            or x_exec.get("claimed_ns") != witness["attempt_batch_bar_index"]):
        raise EconomicQueryError("X/3 execute_evidence 与 S 执行及占有批不符")


def _verify_history_sim_allocation_row(row, image, rows, verified, verified_event):
    kind = row["source_kind"]
    if kind == "history_sim_fill":
        expected_fields = {
            "fact_key", "fact_hash", "projection_kind", "source_kind",
            "command_id", "grant_id", "responsibility_ref", "plan_hash",
            "command_plan_hash", "command_hash", "symbol",
            "fill_allocation_policy_id", "policy_revision", "evidence_id",
            "x_execution_witness", "allocations",
        }
    elif kind == "history_sim_fee":
        expected_fields = {
            "fact_key", "fact_hash", "projection_kind", "source_kind",
            "command_id", "grant_id", "responsibility_ref",
            "original_fact_key", "original_allocation_id", "symbol",
            "fill_allocation_policy_id", "policy_revision", "evidence_id",
            "x_execution_witness", "allocations",
        }
    else:
        raise EconomicQueryError("未知模拟分配来源类型")
    _exact(row, expected_fields, "模拟分配记录")
    _verify_x_execution_witness(row["x_execution_witness"], row)
    _hash(row["fact_key"], "fact_key")
    _hash(row["fact_hash"], "fact_hash")
    if row["projection_kind"] != "per_leg":
        raise EconomicQueryError("模拟分配投影类型不符")
    for field in ("command_id", "grant_id", "responsibility_ref", "symbol",
                  "fill_allocation_policy_id", "policy_revision", "evidence_id"):
        text(row[field], field)
    if row["grant_id"] != row["responsibility_ref"]:
        raise EconomicQueryError("模拟分配 grant_id 与 responsibility_ref 不符")
    finance = image.get("finance")
    if type(finance) is not dict or finance.get("schema_revision") != "tb03b-finance/6":
        raise EconomicQueryError("模拟分配仅属于绑定模型摘要的 tb03b-finance/6 域")
    cmd_matches = [c for c in finance.get("commands", []) if type(c) is dict and c.get("command_id") == row["command_id"]]
    if (len(cmd_matches) != 1 or cmd_matches[0].get("state") != "ReleasedExact"
            or cmd_matches[0].get("grant_id") != row["grant_id"]
            or type(cmd_matches[0].get("command", {}).get("model_ref")) is not dict):
        raise EconomicQueryError("模拟分配缺少同域 tb03b-finance/6 ReleasedExact 命令与 model_ref")
    _hash(cmd_matches[0]["command"]["model_ref"].get("content_hash"), "command.model_ref.content_hash")
    event = verified_event(row["fact_key"])
    if verified[row["fact_key"]][1] != row["fact_hash"]:
        raise EconomicQueryError("分配事实内容身份不同")
    if event.get("event") != "history-sim-unresolved/1":
        raise EconomicQueryError("模拟分配原件类型不符")
    evidence = [h for h in image["history"] if type(h) is dict and h.get("kind") == "ResolveEvidence"
                and h.get("evidence_id") == row["evidence_id"]]
    if (len(evidence) != 1 or type(evidence[0].get("covered")) is not list
            or row["fact_key"] not in evidence[0]["covered"]):
        raise EconomicQueryError("分配缺具名 Resolve 原史")
    allocations = row["allocations"]
    if type(allocations) is not list or len(allocations) != 1:
        raise EconomicQueryError("单一明确原责任域须恰有一条逐重分配")
    alloc = allocations[0]
    common_alloc = {
        "allocation_id", "source_kind", "chong_id", "command_id", "grant_id",
        "responsibility_ref", "family_id", "revision", "symbol", "units",
        "income_changes", "fill_allocation_policy_id", "policy_revision",
    }
    if kind == "history_sim_fill":
        _exact(alloc, common_alloc | {
            "acquisition_cash", "commission", "fee_deferred_to_cause_fact", "reported_fill_fee",
        }, "模拟成交逐重分配")
        expected_id = "sim-command:" + digest([
            row["fact_key"], row["grant_id"], row["command_id"], alloc["chong_id"],
        ])
        if alloc["allocation_id"] != expected_id:
            raise EconomicQueryError("模拟成交逐重分配身份摘要不符")
        if int(integer(alloc["units"], "units")) <= 0:
            raise EconomicQueryError("模拟成交数量须为正")
        integer(alloc["acquisition_cash"], "acquisition_cash")
        if alloc["commission"] != "0" or alloc["fee_deferred_to_cause_fact"] is not True:
            raise EconomicQueryError("模拟成交费用延期标记不符")
        integer(alloc["reported_fill_fee"], "reported_fill_fee")
    else:
        _exact(alloc, common_alloc | {
            "fee_only", "fee_type", "cause", "original_fact_key", "original_allocation_id",
        }, "模拟费用逐重分配")
        _hash(row["original_fact_key"], "original_fact_key")
        if (alloc["original_fact_key"] != row["original_fact_key"]
                or alloc["original_allocation_id"] != row["original_allocation_id"]
                or alloc["cause"] != "fill" or alloc["units"] != "0"):
            raise EconomicQueryError("模拟费用前件或数量不符")
        integer(alloc["fee_only"], "fee_only")
        text(alloc["fee_type"], "fee_type")
        expected_id = "sim-command-fee:" + digest([
            row["fact_key"], row["original_fact_key"], row["grant_id"],
            row["command_id"], alloc["chong_id"],
        ])
        if alloc["allocation_id"] != expected_id:
            raise EconomicQueryError("模拟费用逐重分配身份摘要不符")
        pred = [r for r in rows if type(r) is dict and r.get("fact_key") == row["original_fact_key"]
                and r.get("source_kind") == "history_sim_fill"]
        if len(pred) != 1 or pred[0]["allocations"][0]["allocation_id"] != row["original_allocation_id"]:
            raise EconomicQueryError("模拟费用缺唯一前件 fill 分配")
    if alloc["income_changes"] != {"Pi": "0", "A": "0", "W": "0"}:
        raise EconomicQueryError("模拟买单分配收益账变动非零")


def verify_fill_allocations(image, policy, sources, *, projected=False):
    """只核原图像的字段、类型与具名来源；返回时不改写、补齐或重算。"""
    rows = image["fill_allocations"]
    if type(rows) is not list:
        raise EconomicQueryError("fill_allocations 须为数组")
    verified = {}

    def verified_event(key):
        if key not in verified:
            records = [r for r in image["recorded"]
                       if type(r) is dict and r.get("fact_key") == key]
            if len(records) != 1:
                raise EconomicQueryError("分配缺唯一具名事实")
            verified[key] = (_original_event(records[0], projected=projected), records[0]["fact_hash"])
        return verified[key][0]

    seen = set()
    for row in rows:
        if type(row) is not dict:
            raise EconomicQueryError("分配记录须为对象")
        if row.get("source_kind") in ("history_sim_fill", "history_sim_fee"):
            if row.get("fact_key") in seen:
                raise EconomicQueryError("分配事实重复")
            _verify_history_sim_allocation_row(row, image, rows, verified, verified_event)
            seen.add(row["fact_key"])
            continue
        if policy is None:
            raise EconomicQueryError("分配图像缺冻结政策")
        common = {"fact_key", "fact_hash", "manifest_hash", "symbol", "fill_allocation_policy_id",
                  "policy_revision", "evidence_id", "allocations"}
        per_leg = row.get("projection_kind") == "per_leg"
        correction = "report_kind" in row
        extra = {"projection_kind"} if per_leg else {"from", "to"}
        if correction:
            extra |= {"report_kind", "component", "original_fact_key"}
        _exact(row, common | extra, "分配记录")
        for field in ("fact_key", "fact_hash", "manifest_hash"):
            _hash(row[field], field)
        text(row["evidence_id"], "evidence_id")
        source = sources.get(row["manifest_hash"])
        if (source is None or source["symbol"] != row["symbol"]
                or source["projection_kind"] != ("per_leg" if per_leg else "netted")
                or any(row[k] != policy[k] for k in policy)):
            raise EconomicQueryError("分配记录与冻结清单/政策不同")
        if row["fact_key"] in seen:
            raise EconomicQueryError("分配事实重复")
        seen.add(row["fact_key"])
        event = verified_event(row["fact_key"])
        if verified[row["fact_key"]][1] != row["fact_hash"]:
            raise EconomicQueryError("分配事实内容身份不同")
        report = event.get("per_leg_report" if per_leg else "netted_fill") if type(event) is dict else None
        if (type(report) is not dict or report.get("manifest_hash") != row["manifest_hash"]
                or report.get("symbol") != row["symbol"]):
            raise EconomicQueryError("分配记录与原事实投影来源不同")
        evidence = [h for h in image["history"] if type(h) is dict and h.get("kind") == "ResolveEvidence"
                    and h.get("evidence_id") == row["evidence_id"]]
        if (len(evidence) != 1 or type(evidence[0].get("covered")) is not list
                or row["fact_key"] not in evidence[0]["covered"]):
            raise EconomicQueryError("分配缺具名 Resolve 原史")
        if not per_leg:
            integer(row["from"], "from")
            integer(row["to"], "to")
        if correction:
            expected = {"fee_only": "fee_only", "bust": "acquisition_cash", "reverse_component": "commission"}
            if (per_leg or type(row["report_kind"]) is not str
                    or row["report_kind"] not in expected
                    or expected[row["report_kind"]] != row["component"]
                    or report.get("report_kind") != row["report_kind"]
                    or (row["report_kind"] in ("bust", "reverse_component")
                        and report.get("component") != row["component"])):
                raise EconomicQueryError("更正类型与原事实不同")
            _hash(row["original_fact_key"], "original_fact_key")
            _correction_predecessor(row, event, rows, verified_event)
        elif not per_leg and report.get("report_kind") not in ("incremental", "cumulative"):
            raise EconomicQueryError("普通分配原事实类型不同")
        if not per_leg:
            kind = report["report_kind"]
            if kind in ("incremental", "cumulative", "bust"):
                if row["from"] != report.get("from") or row["to"] != report.get("to"):
                    raise EconomicQueryError("分配区间与原报告不同")
                forward = int(row["to"]) > int(row["from"])
                if (kind == "bust" and int(row["to"]) >= int(row["from"])) or (kind != "bust" and not forward):
                    raise EconomicQueryError("分配区间方向与变体不同")
            elif row["from"] != row["to"]:
                raise EconomicQueryError("零数量更正改变了区间")
        allocations = row["allocations"]
        if type(allocations) is not list or len(allocations) != len(source["participants"]):
            raise EconomicQueryError("分配参与重不完整")
        for allocation, participant in zip(allocations, source["participants"]):
            identity = {"allocation_id", "chong_id", "command_id", "family_id", "revision"}
            amounts = {"units", "acquisition_cash", "commission"}
            fields = identity | amounts
            if per_leg:
                fields = identity | {"unmatched_reason", "manifest_hash", "fill_allocation_policy_id", "policy_revision"}
            elif correction:
                fields |= {"component", "reversal", "original_fact_key"}
                if row["component"] == "fee_only":
                    fields = (fields - {"commission"}) | {"fee_only"}
            _exact(allocation, fields, "逐重分配")
            if any(allocation[k] != participant[k] for k in identity - {"allocation_id"}):
                raise EconomicQueryError("逐重分配身份不同")
            prefix = "per-leg:" if per_leg else "netted:"
            expected_id = prefix + digest([row["fact_key"], event.get("allocation_id"), row["manifest_hash"], participant])
            if allocation["allocation_id"] != expected_id:
                raise EconomicQueryError("逐重分配原身份摘要不同")
            if per_leg:
                if (allocation["unmatched_reason"] != "per_leg_attribution_missing"
                        or allocation["manifest_hash"] != row["manifest_hash"]
                        or any(allocation[k] != policy[k] for k in policy)):
                    raise EconomicQueryError("逐腿未匹配来源不同")
            else:
                _signed_integer(allocation["units"], "units")
                units = int(allocation["units"])
                if ((kind in ("incremental", "cumulative") and units < 0)
                        or (kind == "bust" and units > 0)
                        or (kind in ("fee_only", "reverse_component") and units != 0)):
                    raise EconomicQueryError("分配 units 符号域与变体不同")
                for field in fields & {"acquisition_cash", "commission", "fee_only"}:
                    integer(allocation[field], field)
                if correction and (allocation["component"] != row["component"]
                                   or allocation["original_fact_key"] != row["original_fact_key"]
                                   or type(allocation["reversal"]) is not bool
                                   or allocation["reversal"] != (row["report_kind"] != "fee_only")):
                    raise EconomicQueryError("更正分配来源不同")


class EconomicQuery:
    """一个 Q 配置固定可信 owner；固定向量缓存只留完整已核图像。"""

    # 公开读侧唯一分发表：op -> (method_name, paged_supported, single_frame_http_supported)。
    # economic_http 路由表、分页 Open 分派与入口枚举测试均由此处导出。
    PUBLIC_READ_DISPATCH = {
        "snapshot": ("snapshot", True, True),
        "watch": ("watch", True, True),
        "original": ("original", False, True),
        "projection": ("projection", True, False),
        "projection_original": ("projection_original", True, False),
    }

    def __init__(self, config_path, *, wire_evidence=None):
        self.wire_evidence = wire_evidence
        path = Path(config_path).resolve()
        config = decode_frame(path.read_bytes())
        if config.get("schema_revision") != "economic-query/1":
            raise EconomicQueryError("需要 economic-query/1")
        manifest_path = (path.parent / text(config.get("manifest"), "manifest")).resolve()
        raw_manifest = manifest_path.read_bytes()
        manifest = decode_frame(raw_manifest)
        if manifest.get("schema_revision") != "economic-manifest/1":
            raise EconomicQueryError("需要绑定 economic-manifest/1")
        if digest(manifest) != config.get("manifest_hash"):
            raise EconomicQueryError("manifest 与已配置摘要不同")
        self.protocol_revision, self.finance_revision = economic_revisions(manifest)
        self.book_revision = book_revision(manifest)
        self.fill_policy, self.fill_sources = allocation_sources(manifest, self.book_revision)
        self.manifest = manifest
        self.manifest_hash = config["manifest_hash"]
        self.session = text(manifest.get("session_id"), "session_id")
        self.generation = manifest.get("session_generation")
        integer(self.generation, "session_generation", positive=True)
        self.source = config.get("query_source")
        source_fields = {"source_namespace", "source_epoch", "producer_id", "producer_epoch"}
        if type(self.source) is not dict or set(self.source) != source_fields:
            raise EconomicQueryError("Q 连接身份不在获准源内")
        matching = [entry for entry in manifest.get("authorized_sources", [])
                    if type(entry) is dict and {k: entry.get(k) for k in source_fields} == self.source]
        read_ops = {"ReadView", "Watch", "QueryFact", "QueryAllocation", "QueryVoice", "QueryDecision", "QueryGrant",
                    "EconomicReadOpen", "EconomicReadPage", "EconomicReadClose"}
        if self.finance_revision in ("tb03b-finance/5", "tb03b-finance/6"):
            read_ops.add("QueryCommand")
        if (len(matching) != 1 or type(matching[0].get("operations")) is not list
                or any(type(op) is not str for op in matching[0]["operations"])
                or not {"ReadView", "Watch"} <= set(matching[0]["operations"]) <= read_ops):
            raise EconomicQueryError("Q 身份须明确只有只读操作权限")
        self.authorized_read_ops = frozenset(matching[0]["operations"])
        for key, value in self.source.items():
            text(value, key)
        integer(self.source["producer_epoch"], "producer_epoch", positive=True)
        self.query_epoch = config.get("producer_epoch")
        integer(self.query_epoch, "Q producer_epoch", positive=True)
        resources = config.get("resources")
        fields = {"max_frame_bytes", "timeout_ms", "operation_timeout_ms", "max_reply_bytes",
                  "max_cached_bytes", "max_snapshots", "max_domains", "max_changes"}
        if type(resources) is not dict or set(resources) != fields:
            raise EconomicQueryError("Q 资源必须逐项声明")
        self.resources = {k: integer(resources[k], k, positive=True) for k in fields}
        nodes = [("E", manifest.get("e"))]
        chongs = manifest.get("chongs")
        if type(chongs) is not list:
            raise EconomicQueryError("manifest.chongs 必须是数组")
        for node in chongs:
            if type(node) is not dict:
                raise EconomicQueryError("重路由必须是对象")
            nodes.append(("B:" + text(node.get("chong_id"), "chong_id"), node))
        if len(nodes) > self.resources["max_domains"] or len({d for d, _ in nodes}) != len(nodes):
            raise EconomicQueryError("域数量越界或身份重复")
        self.nodes = {}
        for domain, node in nodes:
            if type(node) is not dict:
                raise EconomicQueryError("域路由缺失")
            self.nodes[domain] = str((manifest_path.parent / text(node.get("socket"), "socket")).resolve())
        epochs = config.get("expected_epochs")
        if type(epochs) is not dict or set(epochs) != set(self.nodes):
            raise EconomicQueryError("须分别声明每个 owner 的获准 epoch")
        for domain, epoch in epochs.items():
            integer(epoch, domain + " epoch", positive=True)
        self.epochs = copy.deepcopy(epochs)
        self.lock = threading.Lock()
        self.cache = OrderedDict()
        self.cached_bytes = 0
        self.transfers = {}
        self.open_records = {}
        self.metadata_bytes = 0
        self.budget = threading.local()
        self._probed_projection_epochs = None
        self._verified_cuts_cache = OrderedDict()

    def dispatch_public_read(self, op, payload, *, deadline=None, paged=False, cache=True):
        """按 PUBLIC_READ_DISPATCH 统一分派公开读侧入口，并在分派器出口强制再过单一出口核验。"""
        entry = self.PUBLIC_READ_DISPATCH.get(op)
        if entry is None:
            raise EconomicQueryError(f"SchemaUnsupported：未知公开读操作 {op}")
        method_name, paged_ok, _ = entry
        if paged and not paged_ok:
            raise EconomicQueryError(f"SchemaUnsupported：分页不支持操作 {op}")
        fn = getattr(self, method_name)
        if op == "snapshot":
            result = fn(payload, deadline=deadline, paged=paged, cache=cache)
        elif op == "watch":
            result = fn(payload, deadline=deadline, paged=paged)
        elif op == "projection":
            result = fn(payload, deadline=deadline, cache=cache)
        elif op == "projection_original":
            result = fn(payload, deadline=deadline)
        else:
            result = fn(payload)
        req_cuts = payload.get("cuts") if type(payload) is dict and type(payload.get("cuts")) is dict else None
        return _finalize_public_response(self, result, requested_cuts=req_cuts, verify_historical_roots=False)

    @staticmethod
    def _has_verified_cut(query, key):
        vc = getattr(query, "_verified_cuts_cache", None)
        lock = getattr(query, "lock", None)
        if isinstance(vc, OrderedDict):
            if lock is not None:
                with lock:
                    if key in vc:
                        vc.move_to_end(key)
                        return True
                    return False
            if key in vc:
                vc.move_to_end(key)
                return True
            return False
        return isinstance(vc, set) and key in vc

    @staticmethod
    def _remember_verified_cut(query, key):
        vc = getattr(query, "_verified_cuts_cache", None)
        if not isinstance(vc, OrderedDict):
            if isinstance(vc, set):
                vc.add(key)
            return
        cost = len(canonical(list(key)))
        lock = getattr(query, "lock", None)

        def store_locked():
            if key in vc:
                vc.move_to_end(key)
                return
            try:
                query._admit_locked(cost, extra_verified=1, protected_cuts=(key,))
            except EconomicQueryError:
                # 共享预算被活动/终态固定项占满时不落常驻缓存，确保不突破预算上限。
                return
            vc[key] = cost
            query.metadata_bytes += cost

        if lock is not None:
            with lock:
                store_locked()
        else:
            store_locked()

    @property
    def command_read_pages(self):
        return (self.finance_revision in ("tb03b-finance/5", "tb03b-finance/6")
                and {"EconomicReadOpen", "EconomicReadPage", "EconomicReadClose"} <= self.authorized_read_ops)

    @property
    def read_projection_configured(self):
        return (self.protocol_revision == "economic-session/1"
                and self.finance_revision == "tb03b-finance/6"
                and self.book_revision in TB03C_BOOKS
                and {"EconomicReadOpen", "EconomicReadPage", "EconomicReadClose"} <= self.authorized_read_ops)

    @property
    def read_projection_available(self):
        return self.read_projection_configured

    @property
    def projection_original_kinds(self):
        ops = self.authorized_read_ops
        kinds = []
        if "QueryFact" in ops:
            kinds.append("fact")
        if "QueryAllocation" in ops:
            kinds.append("allocation")
        if "QueryDecision" in ops:
            kinds.append("decision")
        if "QueryGrant" in ops:
            kinds.append("grant")
        if "QueryCommand" in ops:
            kinds.append("command")
        if "QueryFact" in ops or "QueryCommand" in ops:
            kinds.append("model")
        return tuple(kinds)

    def _probe_domain_projection(self, domain):
        """实测单个 owner 是否真正实现 economic-read-projection/1（Open 确认后即 Close，不从配置盲猜）。"""
        query = {
            "op": "ReadProjection",
            "projection_revision": ECONOMIC_PROJECTION_REVISION,
            "cut": None,
            "as_known_ns": None,
        }
        remaining = min(self._remaining_ms(), 30000)
        open_req = self.request({
            "schema_revision": "economic-read-pages/1",
            "op": "EconomicReadOpen",
            "query": query,
            "requested_remaining_ms": str(remaining),
        })
        wire = exchange(self.nodes[domain], open_req,
                        timeout_ms=min(remaining, self.resources["timeout_ms"]),
                        max_frame_bytes=min(1048576, self.resources["max_frame_bytes"]),
                        evidence=getattr(self.budget, "wire_scope", None),
                        logical_deadline=self.budget.deadline)
        if wire["transport"] != "Received":
            return False
        opened = validate_reply(open_req, wire["response"], producer=domain,
                                producer_epoch=self.epochs[domain])
        if (type(opened) is not dict or opened.get("kind") != "EconomicReadOpened"
                or opened.get("schema_revision") != "economic-read-pages/1"):
            return False
        descriptor = opened.get("descriptor")
        if (type(descriptor) is not dict
                or descriptor.get("document_kind") != "EconomicProjectionView"
                or descriptor.get("session_id") != self.session
                or descriptor.get("session_generation") != self.generation
                or descriptor.get("manifest_hash") != self.manifest_hash
                or opened.get("descriptor_sha256") != digest(descriptor)):
            return False
        transfer_id = descriptor.get("transfer_id")
        if type(transfer_id) is str and re.fullmatch(r"[0-9a-f]{32}", transfer_id):
            close_req = self.request({
                "schema_revision": "economic-read-pages/1",
                "op": "EconomicReadClose",
                "transfer_id": transfer_id,
                "descriptor_sha256": opened["descriptor_sha256"],
            })
            try:
                exchange(self.nodes[domain], close_req,
                         timeout_ms=min(self._remaining_ms(), self.resources["timeout_ms"]),
                         max_frame_bytes=min(1048576, self.resources["max_frame_bytes"]),
                         evidence=getattr(self.budget, "wire_scope", None),
                         logical_deadline=self.budget.deadline)
            except (OSError, ValueError, KeyError, TypeError):
                pass
        return True

    def discover_read_projection(self, *, deadline=None):
        """面向 /api/economic/ready：仅当全部 owner 实际探明支持 ReadProjection 时才声明能力与可用动作。"""
        if not self.read_projection_configured:
            return None
        epoch_key = tuple(sorted(self.epochs.items()))
        with self.lock:
            probed = self._probed_projection_epochs == epoch_key
        if not probed:
            self._start(deadline)
            self.budget.paged = True
            results = self._parallel_domains(lambda d: {"status": "Available"} if self._probe_domain_projection(d) else {"status": "Unavailable"})
            if not all(v.get("status") == "Available" for v in results.values()):
                return None
            with self.lock:
                self._probed_projection_epochs = epoch_key
        return {
            "schema_revision": ECONOMIC_PROJECTION_REVISION,
            "transport_revision": "economic-read-pages/1",
            "owner_epochs": dict(self.epochs),
            "original_kinds": list(self.projection_original_kinds),
            "watch_supported": False,
            "available_actions": ["projection", "projection_original"],
        }

    def _start(self, deadline=None):
        own_deadline = time.monotonic() + self.resources["operation_timeout_ms"] / 1000
        self.budget.deadline = own_deadline if deadline is None else min(own_deadline, deadline)
        self._remaining_ms()

    def _drop_transfer_locked(self, transfer_id):
        transfer = self.transfers.pop(transfer_id)
        key = transfer["cache_key"]
        record_key = transfer.get("record_key")
        if record_key is not None:
            record = self.open_records[record_key]
            terminal = {k: record[k] for k in ("identity", "message_id", "payload_hash", "transfer_id")}
            terminal["status"] = "closed"
            self._set_record_locked(record_key, terminal)
        if transfer["temporary"] and not any(t["cache_key"] == key for t in self.transfers.values()):
            encoded = self.cache.pop(key, None)
            if encoded is not None:
                self.cached_bytes -= len(encoded)

    def _expire_transfers_locked(self):
        now = time.monotonic()
        for transfer_id in list(self.transfers):
            if now >= self.transfers[transfer_id]["deadline"]:
                self._drop_transfer_locked(transfer_id)

    def _cache_put_locked(self, key, encoded):
        """Snapshot 与活跃 watch 共用唯一正文账，活跃传输不得被淘汰。"""
        self._expire_transfers_locked()
        if len(encoded) > self.resources["max_cached_bytes"]:
            raise EconomicQueryError("QueryBudgetExceeded：完整经济文档超过聚合容量")
        if key in self.cache:
            if self.cache[key] != encoded:
                raise EconomicQueryError("缓存身份对应不同正文")
            self.cache.move_to_end(key)
            return
        self._admit_locked(len(encoded), 1)
        self.cache[key] = encoded
        self.cached_bytes += len(encoded)

    def _admit_locked(self, extra_bytes, extra_items=0, protected=(), *, extra_verified=0, protected_cuts=()):
        """先算全部驱逐，再修改；正文、Open 终态元数据与历史根缓存同账。"""
        pinned = {t["cache_key"] for t in self.transfers.values()} | set(protected)
        pinned_cuts = set(protected_cuts)
        vc = getattr(self, "_verified_cuts_cache", None)
        has_vc = isinstance(vc, OrderedDict)
        byte_limit = min(4194304, self.resources["max_cached_bytes"])
        item_limit = min(4, self.resources["max_snapshots"])
        size = self.cached_bytes + self.metadata_bytes + extra_bytes
        count = len(self.cache) + extra_items
        vc_count = (len(vc) if has_vc else 0) + extra_verified
        vc_victims = []
        if has_vc:
            for ckey, cost in vc.items():
                if size <= byte_limit and vc_count <= MAX_VERIFIED_CUTS:
                    break
                if ckey not in pinned_cuts:
                    vc_victims.append(ckey)
                    size -= cost
                    vc_count -= 1
        victims = []
        for key, encoded in self.cache.items():
            if size <= byte_limit and count <= item_limit:
                break
            if key not in pinned:
                victims.append(key)
                size -= len(encoded)
                count -= 1
        if size > byte_limit or count > item_limit or vc_count > MAX_VERIFIED_CUTS:
            raise EconomicQueryError("QueryBudgetExceeded：正文或元数据达到共享缓存上限")
        for ckey in vc_victims:
            self.metadata_bytes -= vc.pop(ckey)
        for key in victims:
            self.cached_bytes -= len(self.cache.pop(key))

    def _set_record_locked(self, key, record):
        old = self.open_records.get(key)
        delta = len(canonical(record)) - (len(canonical(old)) if old is not None else 0)
        self._admit_locked(delta)
        self.open_records[key] = record
        self.metadata_bytes += delta

    @staticmethod
    def _read_error(code, detail, transfer_id=None):
        return {"schema_revision": "economic-read-pages/1", "kind": "EconomicReadError",
                "code": code, "detail": detail, "transfer_id": transfer_id}

    def read(self, payload, request, *, deadline=None):
        """#1406：已验证公共头后的只读页入口；错误仍保留合法页信封。"""
        transfer_id = payload.get("transfer_id") if type(payload) is dict else None
        if type(transfer_id) is not str or re.fullmatch(r"[0-9a-f]{32}", transfer_id) is None:
            transfer_id = None
        try:
            return self._read(payload, request, deadline=deadline)
        except (ValueError, KeyError, TypeError, UnicodeError, RecursionError, OSError) as exc:
            detail = str(exc)
            if "QueryBudgetExceeded" in detail:
                code = "QueryBudgetExceeded"
            elif detail.startswith("MissingDependency"):
                code = "MissingDependency"
            else:
                code = "InvalidQuery"
            return self._read_error(code, detail, transfer_id)

    def _read(self, payload, request, *, deadline=None):
        revision = "economic-read-pages/1"
        if type(payload) is not dict or payload.get("schema_revision") != revision:
            return self._read_error("SchemaUnsupported", "需要 economic-read-pages/1")
        op = payload.get("op")
        fields = {
            "EconomicReadOpen": {"schema_revision", "op", "query", "requested_remaining_ms"},
            "EconomicReadPage": {"schema_revision", "op", "transfer_id", "descriptor_sha256", "offset", "requested_remaining_ms"},
            "EconomicReadClose": {"schema_revision", "op", "transfer_id", "descriptor_sha256"},
        }
        if op not in fields:
            return self._read_error("SchemaUnsupported", "未知只读页操作")
        _exact(payload, fields[op], "分页请求")
        identity = {k: request[k] for k in ("session_id", "session_generation", "source_namespace",
                                           "source_epoch", "producer_id", "producer_epoch")}
        if op == "EconomicReadOpen":
            remaining = integer(payload["requested_remaining_ms"], "requested_remaining_ms", positive=True)
            if remaining > 30000:
                raise EconomicQueryError("requested_remaining_ms 超过30000")
            local_deadline = time.monotonic() + remaining / 1000
            self._start(local_deadline if deadline is None else min(local_deadline, deadline))
            logical_query = payload["query"]
            paged_ops = {k for k, (_, paged_ok, _) in self.PUBLIC_READ_DISPATCH.items() if paged_ok}
            if type(logical_query) is not dict or logical_query.get("op") not in paged_ops:
                return self._read_error("SchemaUnsupported", "分页只支持原 snapshot/watch 或显式 projection/projection_original")
            # 请求键保存原文身份，终态不删除；不可让相同 Open 在关闭后复活。
            record_key = tuple(identity.values()) + (request["message_id"],)
            with self.lock:
                self._expire_transfers_locked()
                existing = self.open_records.get(record_key)
                if existing is not None:
                    if existing["payload_hash"] != request["payload_hash"]:
                        return self._read_error("IdentityConflict", "同 Open 身份内容不同")
                    if existing["status"] == "active":
                        return existing["opened"]
                    return self._read_error("SourceUnavailable" if existing["status"] == "opening" else "TransferExpired",
                                            "原 Open 未完成或已经终止", existing["transfer_id"])
                transfer_id = uuid.uuid4().hex
                record = {"identity": identity, "message_id": request["message_id"],
                          "payload_hash": request["payload_hash"], "transfer_id": transfer_id, "status": "opening"}
                self._set_record_locked(record_key, record)
            committed = False
            try:
                operation_deadline = self.budget.deadline
                lop = logical_query["op"]
                body = self.dispatch_public_read(lop, logical_query, deadline=operation_deadline, paged=True, cache=False)
                self._remaining_ms()
                if body.get("kind") == "Gap":
                    return self._read_error("SnapshotExpired", "原 snapshot/projection token 已失效", transfer_id)
                expected_kind = {
                    "snapshot": "EconomicSnapshot",
                    "watch": "EconomicWatch",
                    "projection": "EconomicProjection",
                    "projection_original": "EconomicProjectionOriginal",
                }[lop]
                if body.get("kind") != expected_kind:
                    return self._read_error("IntegrityError", "完整逻辑文档类型错误", transfer_id)
                if lop == "projection_original":
                    if set(body.get("cuts", {})) != set(self.nodes):
                        return self._read_error("IntegrityError", "同切面原件固定切面集合错误", transfer_id)
                    fixed = {d: verify_cut(c, d) for d, c in body["cuts"].items()}
                else:
                    if set(body.get("domains", {})) != set(self.nodes):
                        return self._read_error("IntegrityError", "完整逻辑文档域集合错误", transfer_id)
                    fixed = {}
                    for domain, view in body["domains"].items():
                        if view.get("status") == "Available":
                            cut_field = "cut" if expected_kind in ("EconomicSnapshot", "EconomicProjection") else "next_cut"
                            fixed[domain] = verify_cut(view.get(cut_field), domain)
                        elif view.get("status") == "Unavailable":
                            fixed[domain] = None
                        else:
                            return self._read_error("IntegrityError", "域可用状态非法", transfer_id)
                encoded = canonical(body)
                if len(encoded) > min(4194304, self.resources["max_cached_bytes"]):
                    raise EconomicQueryError("QueryBudgetExceeded：完整逻辑正文超过聚合帽")
                descriptor = {
                    "schema_revision": revision, "transfer_id": transfer_id,
                    "session_id": self.session, "session_generation": self.generation,
                    "manifest_hash": self.manifest_hash, "producer_id": "Q:" + self.session,
                    "producer_epoch": self.query_epoch, "query_sha256": digest(logical_query),
                    "document_kind": expected_kind, "fixed_cuts": fixed,
                    "owner_epochs": dict(self.epochs), "document_bytes": str(len(encoded)),
                    "document_sha256": hashlib.sha256(encoded).hexdigest(), "chunk_bytes": "262144",
                    "page_count": str((len(encoded) + 262143) // 262144),
                }
                opened = {"schema_revision": revision, "kind": "EconomicReadOpened", "descriptor": descriptor,
                          "descriptor_sha256": digest(descriptor)}
                temporary = expected_kind in ("EconomicWatch", "EconomicProjectionOriginal")
                if temporary:
                    cache_key = f"economic-{lop}-" + transfer_id
                elif expected_kind == "EconomicProjection":
                    cache_key = body["projection_token"]
                else:
                    cache_key = body["snapshot_token"]
                active = {**record, "status": "active", "opened": opened, "cache_key": cache_key,
                          "temporary": temporary, "deadline_ns": str(int(operation_deadline * 1000000000))}
                with self.lock:
                    self._expire_transfers_locked()
                    self._remaining_ms()
                    old_bytes = self.cache.get(cache_key)
                    if old_bytes is not None and old_bytes != encoded:
                        return self._read_error("IntegrityError", "正文缓存身份冲突", transfer_id)
                    delta_meta = len(canonical(active)) - len(canonical(self.open_records[record_key]))
                    self._admit_locked(delta_meta + (len(encoded) if old_bytes is None else 0),
                                       int(old_bytes is None), protected=(cache_key,))
                    if old_bytes is None:
                        self.cache[cache_key] = encoded
                        self.cached_bytes += len(encoded)
                    self.cache.move_to_end(cache_key)
                    self.open_records[record_key] = active
                    self.metadata_bytes += delta_meta
                    self.transfers[transfer_id] = {"record_key": record_key, "cache_key": cache_key,
                                                   "temporary": temporary, "deadline": operation_deadline}
                    committed = True
                self._remaining_ms()
                return opened
            finally:
                if not committed:
                    with self.lock:
                        failed = {**record, "status": "closed"}
                        self._set_record_locked(record_key, failed)
        transfer_id, descriptor_hash = payload["transfer_id"], payload["descriptor_sha256"]
        if type(transfer_id) is not str or re.fullmatch(r"[0-9a-f]{32}", transfer_id) is None:
            raise EconomicQueryError("transfer_id 格式错误")
        if type(descriptor_hash) is not str or re.fullmatch(r"[0-9a-f]{64}", descriptor_hash) is None:
            raise EconomicQueryError("descriptor_sha256 格式错误")
        with self.lock:
            self._expire_transfers_locked()
            transfer = self.transfers.get(transfer_id)
            closed = {"schema_revision": revision, "kind": "EconomicReadClosed", "transfer_id": transfer_id,
                      "descriptor_sha256": descriptor_hash}
            if transfer is None:
                return closed if op == "EconomicReadClose" else self._read_error("TransferExpired", "读取传输已失效", transfer_id)
            record = self.open_records[transfer["record_key"]]
            if record["identity"] != identity or record["opened"]["descriptor_sha256"] != descriptor_hash:
                return self._read_error("IdentityConflict", "读取传输来源或描述符不同", transfer_id)
            if op == "EconomicReadClose":
                self._drop_transfer_locked(transfer_id)
                return closed
            remaining = integer(payload["requested_remaining_ms"], "requested_remaining_ms", positive=True)
            if remaining > 30000:
                raise EconomicQueryError("requested_remaining_ms 超过30000")
            page_deadline = min(transfer["deadline"], time.monotonic() + remaining / 1000)
            self._start(page_deadline if deadline is None else min(page_deadline, deadline))
            offset = integer(payload["offset"], "offset")
            encoded = self.cache[transfer["cache_key"]]
            if offset >= len(encoded) or offset % 262144:
                raise EconomicQueryError("页 offset 必须是正文内固定步长边界")
            chunk = encoded[offset:offset + 262144]
            end = offset + len(chunk)
            result = {"schema_revision": revision, "kind": "EconomicReadPage", "transfer_id": transfer_id,
                      "descriptor_sha256": descriptor_hash, "offset": str(offset), "raw_byte_count": str(len(chunk)),
                      "chunk_sha256": hashlib.sha256(chunk).hexdigest(), "data_base64": base64.b64encode(chunk).decode("ascii"),
                      "next_offset": None if end == len(encoded) else str(end), "done": end == len(encoded)}
            self._remaining_ms()
            return result

    def _remaining_ms(self):
        deadline = getattr(self.budget, "deadline", None)
        if deadline is None:
            self._start()
            deadline = self.budget.deadline
        left = int((deadline - time.monotonic()) * 1000)
        if left <= 0:
            raise EconomicQueryError("QueryBudgetExceeded：完整经济查询达到总期限")
        return min(left, self.resources["timeout_ms"])

    @contextmanager
    def capture(self, request, deadline):
        scope = None if self.wire_evidence is None else self.wire_evidence.scope(request, deadline)
        self.budget.wire_scope = scope
        error = None
        try:
            yield
        except BaseException as exc:
            error = exc
            raise
        finally:
            self.budget.wire_scope = None
            if scope is not None:
                try:
                    scope.close(None if error is None else type(error).__name__)
                    if time.monotonic() >= deadline:
                        raise EconomicQueryError("原wire封存达到公共请求原期限")
                except (OSError, ValueError) as evidence_error:
                    if error is None:
                        raise
                    error.add_note("原wire封存也失败：" + str(evidence_error))

    def _parallel_domains(self, operation):
        deadline = self.budget.deadline
        paged = getattr(self.budget, "paged", False)
        wire_scope = getattr(self.budget, "wire_scope", None)

        def run(domain):
            self.budget.deadline = deadline
            self.budget.paged = paged
            self.budget.wire_scope = wire_scope
            try:
                return operation(domain)
            except (ValueError, KeyError, TypeError, OSError, RecursionError) as exc:
                return {"status": "Unavailable", "error": str(exc)}

        # 每域同时开始且各自有界；慢域不会消耗健康域尚未开始的读取机会。
        with ThreadPoolExecutor(max_workers=len(self.nodes)) as pool:
            return dict(zip(self.nodes, pool.map(run, self.nodes)))

    def request(self, payload):
        return {
            "schema_revision": self.protocol_revision, "session_id": self.session,
            "session_generation": self.generation, **self.source,
            "message_id": "query-" + uuid.uuid4().hex, "payload_hash": digest(payload),
            "causal_refs": [], "payload": payload,
        }

    def owner(self, domain, payload):
        op = payload.get("op")
        if op in ("ReadProjection", "ReadOriginalAtCut") and not getattr(self.budget, "paged", False):
            raise EconomicQueryError("经济投影与同切面取证必须经由分页读协议执行，禁止绕过分页")
        if getattr(self.budget, "paged", False) and op in ("ReadView", "Watch", "ReadProjection", "ReadOriginalAtCut"):
            from s_socket_client import read_economic_pages
            required = {"EconomicReadOpen", "EconomicReadPage", "EconomicReadClose"}
            if not required <= self.authorized_read_ops:
                raise EconomicQueryError("Q 来源未明确获准分页只读操作")
            def fetch(page_payload, remaining_ms):
                request = self.request(page_payload)
                wire = exchange(self.nodes[domain], request,
                                timeout_ms=min(remaining_ms, self.resources["timeout_ms"]),
                                max_frame_bytes=min(1048576, self.resources["max_frame_bytes"]),
                                evidence=getattr(self.budget, "wire_scope", None),
                                logical_deadline=self.budget.deadline)
                if wire["transport"] != "Received":
                    raise EconomicQueryError(wire["transport"] + ": " + wire.get("detail", ""))
                return validate_reply(request, wire["response"], producer=domain,
                                      producer_epoch=self.epochs[domain])
            result = read_economic_pages(
                payload, fetch, session_id=self.session, session_generation=self.generation,
                producer_id=domain + ":" + self.session, producer_epoch=self.epochs[domain],
                manifest_hash=self.manifest_hash, owner_epochs={domain: self.epochs[domain]},
                deadline=self.budget.deadline,
                max_frame_bytes=min(1048576, self.resources["max_frame_bytes"]),
                max_document_bytes=min(4194304, self.resources["max_cached_bytes"]))
            if result.get("domain_id") != domain:
                raise EconomicQueryError("权威分页内容与获准连接不同")
            self._remaining_ms()
            return result
        request = self.request(payload)
        result = exchange(self.nodes[domain], request, timeout_ms=self._remaining_ms(),
                          max_frame_bytes=self.resources["max_frame_bytes"],
                          evidence=getattr(self.budget, "wire_scope", None),
                                logical_deadline=self.budget.deadline)
        if result["transport"] != "Received":
            raise EconomicQueryError(result["transport"] + ": " + result.get("detail", ""))
        response = validate_reply(request, result["response"], producer=domain,
                                  producer_epoch=self.epochs[domain])
        if response.get("ok") is False or "error" in response:
            raise EconomicQueryError(str(response.get("error", "权威域不可用")))
        if response.get("domain_id") != domain:
            raise EconomicQueryError("权威域内容与获准连接不同")
        return response

    def view(self, domain, cut=None, as_known_ns=None):
        if cut is not None:
            verify_cut(cut, domain)
        if as_known_ns is not None:
            integer(as_known_ns, "as_known_ns")
        response = self.owner(domain, {"op": "ReadView", "cut": cut, "as_known_ns": as_known_ns})
        if response.get("kind") != "EconomicView":
            raise EconomicQueryError("owner 未返回完整经济图像")
        verify_cut(response.get("cut"), domain)
        commit_ns = response.get("commit_ns")
        integer(commit_ns, "commit_ns")
        if as_known_ns is not None and int(commit_ns) > int(as_known_ns):
            raise EconomicQueryError("owner 返回了获知截止时刻之后的图像")
        if cut is not None and response["cut"] != cut:
            raise EconomicQueryError("owner 回看切面与请求不同")
        image = response.get("image")
        fields = {"book", "recorded", "pending", "applied", "unmatched", "history"}
        fields |= {"finance"} if self.manifest.get("finance") else set()
        allowed = [fields]
        if self.book_revision in TB03C_BOOKS and domain == "E":
            allowed.append(fields | {"fill_allocations"})
        if (type(image) is not dict
                or set(image) not in allowed
                or any(type(image[k]) is not list for k in set(image) - {"book", "finance"})
                or (image["book"] is not None and type(image["book"]) is not dict)):
            raise EconomicQueryError("经济图像字段不完整或类型错误")
        if image["book"] is not None and image["book"].get("book_revision") != self.book_revision:
            raise EconomicQueryError("图像书账版本与冻结域不同")
        if "fill_allocations" in image:
            verify_fill_allocations(image, self.fill_policy, self.fill_sources)
        if "finance" in image:
            finance = image["finance"]
            fields = {"schema_revision", "rights", "decisions", "slots", "responsibilities"}
            if self.finance_revision in ("tb03b-finance/5", "tb03b-finance/6"):
                fields.add("commands")  # #1407：/5、/6 创世图像即带 commands 族。
            if (type(finance) is not dict or set(finance) not in (fields, fields | {"closed_applicants"})
                    or finance.get("schema_revision") != self.finance_revision
                    or any(type(finance[k]) is not list for k in set(finance) - {"schema_revision"})):
                raise EconomicQueryError("财务图像字段、版本或类型错误")
        if response.get("image_hash") != digest(image):
            raise EconomicQueryError("经济图像与完整摘要不同")
        # 当前读取 PID/运行环境/epoch 单列诊断，不改变历史图像或语义 token。
        return {"status": "Available", "cut": response["cut"], "commit_ns": commit_ns, "image": image,
                "image_hash": response["image_hash"]}

    def _store(self, body, *, paged=False, cache=True):
        token = "economic-snapshot-" + digest(body)
        result = {**body, "snapshot_token": token}
        encoded = canonical(result)
        if not paged and len(encoded) > self.resources["max_reply_bytes"]:
            raise EconomicQueryError("QueryBudgetExceeded：旧版单帧经济切面超过容量")
        self._remaining_ms()
        if cache:
            with self.lock:
                self._cache_put_locked(token, encoded)
        return result

    def _fixed_document(self, token, kind, token_field, *, single_frame=False):
        """共享缓存容量，固定 token 只读回签发它的那类文档。"""
        with self.lock:
            self._expire_transfers_locked()
            encoded = self.cache.get(token)
            if encoded is not None:
                self.cache.move_to_end(token)
        if encoded is None:
            self._remaining_ms()
            return {"kind": "Gap", "reason": "SnapshotExpired", "requested_token": token,
                    "session_id": self.session, "session_generation": self.generation}
        if single_frame and len(encoded) > self.resources["max_reply_bytes"]:
            raise EconomicQueryError("QueryBudgetExceeded：旧版单帧经济切面超过容量")
        document = decode_frame(encoded)
        if document.get("kind") != kind or document.get(token_field) != token:
            raise EconomicQueryError("固定 token 与请求的经济文档类型不符")
        self._remaining_ms()
        return document

    def snapshot(self, payload, *, deadline=None, paged=False, cache=True):
        self._start(deadline)
        self.budget.paged = paged
        if type(payload) is not dict or set(payload) != {"op", "cuts", "as_known_ns", "snapshot_token"}:
            raise EconomicQueryError("snapshot 参数不完整或多余")
        if payload["op"] != "snapshot":
            raise EconomicQueryError("请求操作不符")
        token, cuts, as_known = payload["snapshot_token"], payload["cuts"], payload["as_known_ns"]
        if token is not None:
            if type(token) is not str or cuts is not None or as_known is not None:
                raise EconomicQueryError("固定 token 不能混入新 cut 或获知时刻")
            return _finalize_public_response(
                self,
                self._fixed_document(token, "EconomicSnapshot", "snapshot_token", single_frame=not paged),
            )
        if cuts is not None and (type(cuts) is not dict or set(cuts) != set(self.nodes)):
            raise EconomicQueryError("回看须给完整域向量")
        if cuts is not None and as_known is not None:
            raise EconomicQueryError("固定向量与获知时刻不能同时指定")
        if as_known is not None:
            integer(as_known, "as_known_ns")
        if cuts is not None:
            for domain in self.nodes:
                verify_cut(cuts[domain], domain)
        views = self._parallel_domains(lambda domain: self.view(
            domain, None if cuts is None else cuts[domain], as_known))
        body = _finalize_public_response(self, {
            "kind": "EconomicSnapshot", "session_id": self.session, "session_generation": self.generation,
            "manifest_hash": self.manifest_hash,
            "mode": "AsKnown" if cuts is not None or as_known is not None else "Current",
            "as_known_ns": as_known, "domains": views,
            "completeness": "CompleteVector" if all(v["status"] == "Available" for v in views.values()) else "PartialVector",
        }, requested_cuts=cuts)
        return self._store(body, paged=paged, cache=cache)

    def original(self, payload):
        """#1394：沿指定完整经济 cut 向量查原件，绝不用后来回执填旧 cut。"""
        self._start()
        self.budget.paged = self.command_read_pages
        if (type(payload) is not dict
                or set(payload) != {"op", "kind", "domain_id", "object_id", "cuts"}
                or payload["op"] != "original" or payload["kind"] not in ("decision", "grant", "command")):
            raise EconomicQueryError("原件查询参数不完整或多余")
        domain, cuts = payload["domain_id"], payload["cuts"]
        if domain not in self.nodes or type(cuts) is not dict or set(cuts) != set(self.nodes):
            raise EconomicQueryError("原件查询须固定完整域向量和目标 owner")
        for name, cut in cuts.items():
            verify_cut(cut, name)
        kind = payload["kind"]
        if (kind == "decision") == (domain == "E"):
            raise EconomicQueryError("原件类型不属于该权威域")
        if kind == "command" and self.finance_revision not in ("tb03b-finance/5", "tb03b-finance/6"):
            raise EconomicQueryError("命令原件只属于 tb03b-finance/5 与 /6")
        object_id = text(payload["object_id"], "原身份")
        view = self.view(domain, cuts[domain])
        if kind == "command":
            return self._command_original(view, cuts, object_id)
        response = self.owner(domain, {"op": "QueryDecision" if kind == "decision" else "QueryGrant",
                                      "decision_id" if kind == "decision" else "grant_id": object_id,
                                      "cut": cuts[domain], "as_known_ns": None})
        finance = view["image"].get("finance", {})
        candidates = finance.get("decisions", []) if kind == "decision" else [
            grant for slot in finance.get("slots", []) for grant in slot["grants"]]
        selected = next((x for x in candidates if x[kind + "_id"] == object_id), None)
        if selected is None or response.get(kind) != selected:
            raise EconomicQueryError("原件与指定 cut 的已核图像不同")
        receipts = response.get("receipts") if kind == "decision" else [response.get("receipt")]
        if type(receipts) is not list or not receipts:
            raise EconomicQueryError("原件缺实际持久回执")
        for receipt in receipts:
            verify_cut(receipt.get("cut"), domain)
        return _finalize_public_response(self, {
            "kind": "EconomicOriginal", "session_id": self.session,
            "session_generation": self.generation, "manifest_hash": self.manifest_hash,
            "cuts": cuts, "domain_id": domain, "original": response,
        }, requested_cuts=cuts)

    def _command_original(self, view, cuts, command_id):
        """#1407 C2：E 的 QueryCommand 须对应同 cut 已核图像的 commands 记录；无记录只认 NoRecord。"""
        cut = cuts["E"]
        response = self.owner("E", {"op": "QueryCommand", "command_id": command_id,
                                    "cut": cut, "as_known_ns": None})
        selected = next((c for c in view["image"]["finance"]["commands"]
                         if c["command_id"] == command_id), None)
        head = {"kind": "EconomicCommand", "domain_id": "E", "command_id": command_id, "cut": cut}
        if selected is None:
            if response != {**head, "state": "NoRecord"}:
                raise EconomicQueryError("命令原件与指定 cut 的 NoRecord 不同")
        else:
            receipt_kinds = {"Dispatchable": ["DispatchableReceipt"],
                             "ReleasedExact": ["DispatchableReceipt", "ReleasedExactReceipt"],
                             "Unsupported": ["DispatchableReceipt", "ReleaseUnsupportedReceipt"]}
            receipts = response.get("receipts")
            if (set(response) != set(head) | {"state", "record", "receipts"}
                    or any(response[k] != v for k, v in head.items())
                    or response["record"] != selected or response["state"] != selected["state"]
                    or type(receipts) is not list
                    or [type(r) is dict and r.get("kind") for r in receipts] != receipt_kinds.get(selected["state"])
                    or receipts[-1].get("record") != selected):
                raise EconomicQueryError("命令原件与指定 cut 的已核图像不同")
            events = [e for e in view["image"]["history"] if e.get("kind") in ("MakeDispatchable", "ReleaseExact")
                      and e["record"]["command_id"] == command_id]
            if len(events) != len(receipts):
                raise EconomicQueryError("命令回执与当前历史不对应")
            for receipt, event in zip(receipts, events):
                at = verify_cut(receipt.get("cut"), "E")
                if int(at["commit_seq"]) > int(cut["commit_seq"]):
                    raise EconomicQueryError(
                        f"MissingDependency：回执(E:{at['commit_seq']})晚于固定切面(E:{cut['commit_seq']})，拒绝未来回执（向量未就绪）"
                    )
                op = event["kind"]
                key = command_id if op == "ReleaseExact" else selected["decision_id"]
                if receipt != {"kind": receipt["kind"], "cut": at, "record": event["record"], "domain_id": "E",
                               "commit_ns": event["commit_ns"], "first_known_ns": event["first_known_ns"],
                               "receipt_key": f"{self.finance_revision}:{op}:{digest(key)}"} or at["commit_seq"] != event["commit_seq"]:
                    raise EconomicQueryError("命令回执与历史原件不同")
                # 所选 cut 之前的回执也须引用 E 的真根；ReadView 按序号和根一起定位。
                if at["commit_seq"] == cut["commit_seq"]:
                    if at != cut:
                        raise EconomicQueryError("原回执根不同")
                else:
                    self.view("E", at)
        return _finalize_public_response(self, {
            "kind": "EconomicOriginal", "session_id": self.session,
            "session_generation": self.generation, "manifest_hash": self.manifest_hash,
            "cuts": cuts, "domain_id": "E", "original": response,
        }, requested_cuts=cuts)

    def projection_view(self, domain, cut=None, as_known_ns=None):
        """#1425 方案 1：经由显式分页只读投影协议读取单域固定切面投影，严禁退回未限量 ReadView。"""
        if not self.read_projection_available:
            raise EconomicQueryError("当前会话未显式启用 economic-read-projection/1")
        if cut is not None:
            verify_cut(cut, domain)
        if as_known_ns is not None:
            integer(as_known_ns, "as_known_ns")
        response = self.owner(domain, {
            "op": "ReadProjection",
            "projection_revision": ECONOMIC_PROJECTION_REVISION,
            "cut": cut,
            "as_known_ns": as_known_ns,
        })
        if (response.get("kind") != "EconomicProjectionView"
                or response.get("projection_revision") != ECONOMIC_PROJECTION_REVISION
                or response.get("session_id") != self.session
                or response.get("session_generation") != self.generation
                or response.get("writer_epoch") != self.epochs[domain]
                or response.get("audit_verified") is not True):
            raise EconomicQueryError("owner 未返回已核经济投影视图")
        verify_cut(response.get("cut"), domain)
        commit_ns = response.get("commit_ns")
        integer(commit_ns, "commit_ns")
        if as_known_ns is not None and int(commit_ns) > int(as_known_ns):
            raise EconomicQueryError("owner 返回了获知截止时刻之后的投影")
        if cut is not None and response["cut"] != cut:
            raise EconomicQueryError("owner 回看投影切面与请求不同")
        _hash(response.get("authoritative_image_hash"), "authoritative_image_hash")
        integer(response.get("authoritative_image_bytes"), "authoritative_image_bytes", positive=True)
        projection = response.get("projection")
        fields = {"book", "recorded", "pending", "applied", "unmatched", "history"}
        fields |= {"finance"} if self.manifest.get("finance") else set()
        allowed = [fields]
        if self.book_revision in TB03C_BOOKS and domain == "E":
            allowed.append(fields | {"fill_allocations"})
        if (type(projection) is not dict
                or set(projection) not in allowed
                or any(type(projection[k]) is not list for k in set(projection) - {"book", "finance"})
                or (projection["book"] is not None and type(projection["book"]) is not dict)):
            raise EconomicQueryError("经济投影字段不完整或类型错误")
        if projection["book"] is not None and projection["book"].get("book_revision") != self.book_revision:
            raise EconomicQueryError("投影书账版本与冻结域不同")
        if "fill_allocations" in projection:
            verify_fill_allocations(projection, self.fill_policy, self.fill_sources, projected=True)
        if "finance" in projection:
            finance = projection["finance"]
            ffields = {"schema_revision", "rights", "decisions", "slots", "responsibilities", "commands"}
            if (type(finance) is not dict or set(finance) not in (ffields, ffields | {"closed_applicants"})
                    or finance.get("schema_revision") != self.finance_revision
                    or any(type(finance[k]) is not list for k in set(finance) - {"schema_revision"})):
                raise EconomicQueryError("投影财务字段、版本或类型错误")
        proj_encoded = canonical(projection)
        if response.get("projection_hash") != hashlib.sha256(proj_encoded).hexdigest():
            raise EconomicQueryError("经济投影摘要与投影正文不同")
        if integer(response.get("projection_bytes"), "projection_bytes", positive=True) != len(proj_encoded):
            raise EconomicQueryError("经济投影字节数与投影正文不同")
        omitted = response.get("omitted_peer_images")
        if type(omitted) is not list:
            raise EconomicQueryError("经济投影缺少省略证明锚点列表")
        for item in omitted:
            _exact(item, {"path", "omitted_kind", "sha256", "byte_len"}, "省略证明锚点")
            text(item["path"], "omitted path")
            if item["omitted_kind"] != "EmbeddedPeerImage":
                raise EconomicQueryError("未知省略证明锚点类型")
            _hash(item["sha256"], "omitted sha256")
            integer(item["byte_len"], "omitted byte_len", positive=True)
        return {
            "status": "Available",
            "projection_revision": ECONOMIC_PROJECTION_REVISION,
            "cut": response["cut"],
            "commit_ns": commit_ns,
            "writer_epoch": response["writer_epoch"],
            "audit_verified": True,
            "authoritative_image_hash": response["authoritative_image_hash"],
            "authoritative_image_bytes": response["authoritative_image_bytes"],
            "projection_hash": response["projection_hash"],
            "projection_bytes": response["projection_bytes"],
            "omitted_peer_images": omitted,
            "projection": projection,
        }

    def projection(self, payload, *, deadline=None, cache=True):
        """#1425 方案 1：跨域固定切面只读投影；单列 projection_completeness，绝不冒充 CompleteVector。"""
        if not self.read_projection_available:
            raise EconomicQueryError("当前会话未显式启用 economic-read-projection/1")
        self._start(deadline)
        self.budget.paged = True
        _exact(payload, {"op", "projection_revision", "cuts", "as_known_ns", "projection_token"}, "projection 请求")
        if payload["op"] != "projection" or payload["projection_revision"] != ECONOMIC_PROJECTION_REVISION:
            raise EconomicQueryError("投影操作或版本不符")
        token, cuts, as_known = payload["projection_token"], payload["cuts"], payload["as_known_ns"]
        if token is not None:
            if type(token) is not str or cuts is not None or as_known is not None:
                raise EconomicQueryError("固定 projection token 不能混入新 cut 或获知时刻")
            return _finalize_public_response(
                self,
                self._fixed_document(token, "EconomicProjection", "projection_token"),
            )
        if cuts is not None and (type(cuts) is not dict or set(cuts) != set(self.nodes)):
            raise EconomicQueryError("投影回看须给完整域向量")
        if cuts is not None and as_known is not None:
            raise EconomicQueryError("固定向量与获知时刻不能同时指定")
        if as_known is not None:
            integer(as_known, "as_known_ns")
        if cuts is not None:
            for domain in self.nodes:
                verify_cut(cuts[domain], domain)
        views = self._parallel_domains(lambda domain: self.projection_view(
            domain, None if cuts is None else cuts[domain], as_known))
        body = _finalize_public_response(self, {
            "kind": "EconomicProjection",
            "projection_revision": ECONOMIC_PROJECTION_REVISION,
            "session_id": self.session,
            "session_generation": self.generation,
            "manifest_hash": self.manifest_hash,
            "mode": "AsKnown" if cuts is not None or as_known is not None else "Current",
            "as_known_ns": as_known,
            "domains": views,
            "projection_completeness": (
                "CompleteProjectionVector"
                if all(v["status"] == "Available" for v in views.values())
                else "PartialProjectionVector"
            ),
        }, requested_cuts=cuts, verify_historical_roots=True)
        ptoken = "economic-projection-" + digest(body)
        result = {**body, "projection_token": ptoken}
        encoded = canonical(result)
        if len(encoded) > min(4194304, self.resources["max_cached_bytes"]):
            raise EconomicQueryError("QueryBudgetExceeded：完整经济投影超过聚合容量")
        self._remaining_ms()
        if cache:
            with self.lock:
                self._cache_put_locked(ptoken, encoded)
        return result

    def _verified_vector_cached(self, cuts):
        """判断完整域切面向量是否已由本 Q 实核并保留在缓存中（仅认完整向量）。"""
        lock = getattr(self, "lock", None)
        cache = getattr(self, "cache", None)
        if lock is None or cache is None:
            return False
        with lock:
            if hasattr(self, "_expire_transfers_locked"):
                self._expire_transfers_locked()
            entries = list(cache.values())
        for encoded in entries:
            try:
                doc = decode_frame(encoded)
            except (ValueError, UnicodeError, TypeError):
                continue
            kind = doc.get("kind")
            if kind == "EconomicProjection" and doc.get("projection_completeness") == "CompleteProjectionVector":
                cached_cuts = {d: v.get("cut") for d, v in doc.get("domains", {}).items()}
                if cached_cuts == cuts:
                    return True
            elif kind == "EconomicSnapshot" and doc.get("completeness") == "CompleteVector":
                cached_cuts = {d: v.get("cut") for d, v in doc.get("domains", {}).items()}
                if cached_cuts == cuts:
                    return True
        return False

    def _check_projection_original_permission(self, domain, kind):
        ops = getattr(self, "authorized_read_ops", None)
        if not isinstance(ops, (set, frozenset)):
            return
        needed = {
            "fact": {"QueryFact"},
            "allocation": {"QueryAllocation"},
            "decision": {"QueryDecision"},
            "grant": {"QueryGrant"},
            "command": {"QueryCommand"},
            "model": {"QueryCommand", "QueryFact"} if domain == "E" else {"QueryFact"},
        }[kind]
        if not (ops & needed):
            raise EconomicQueryError(f"Q 来源未获准读取 {domain} 的 {kind} 原件")

    def projection_original(self, payload, *, deadline=None):
        """#1425 方案 1：按同一已核固定 cut 向量展开原件，并按每条回执自身域的前沿与真根校验。"""
        if not self.read_projection_available:
            raise EconomicQueryError("当前会话未显式启用 economic-read-projection/1")
        self._start(deadline)
        self.budget.paged = True
        _exact(payload, {"op", "projection_revision", "domain_id", "kind", "object_id", "cuts"}, "同切面原件请求")
        if payload["op"] != "projection_original" or payload["projection_revision"] != ECONOMIC_PROJECTION_REVISION:
            raise EconomicQueryError("同切面原件操作或版本不符")
        domain, kind, cuts = payload["domain_id"], payload["kind"], payload["cuts"]
        object_id = text(payload["object_id"], "object_id")
        if domain not in self.nodes or kind not in PROJECTION_ORIGINAL_KINDS:
            raise EconomicQueryError("同切面原件目标域或类型非法")
        if type(cuts) is not dict or set(cuts) != set(self.nodes):
            raise EconomicQueryError("同切面原件必须固定完整域向量")
        for name, cut in cuts.items():
            verify_cut(cut, name)
        self._check_projection_original_permission(domain, kind)
        # 1. 向量实核：若未命中本 Q 已核完整切面缓存，则实核全部非目标域的固定 cut 真根，禁止放行非目标域错根。
        other_domains = [d for d in self.nodes if d != domain]
        if other_domains and not self._verified_vector_cached(cuts):
            checked = self._parallel_domains(
                lambda d: {"status": "Available"} if d == domain else self.projection_view(d, cuts[d])
            )
            for other in other_domains:
                if checked[other].get("status") != "Available":
                    raise EconomicQueryError(
                        f"非目标域 {other} 固定切面未通过实核：{checked[other].get('error', '不可用')}"
                    )
        response = self.owner(domain, {
            "op": "ReadOriginalAtCut",
            "projection_revision": ECONOMIC_PROJECTION_REVISION,
            "cut": cuts[domain],
            "kind": kind,
            "object_id": object_id,
        })
        if (response.get("kind") != "EconomicOriginalAtCut"
                or response.get("projection_revision") != ECONOMIC_PROJECTION_REVISION
                or response.get("domain_id") != domain
                or response.get("session_id") != self.session
                or response.get("session_generation") != self.generation
                or response.get("writer_epoch") != self.epochs[domain]
                or response.get("audit_verified") is not True
                or response.get("cut") != cuts[domain]
                or response.get("original_kind") != kind
                or response.get("object_id") != object_id):
            raise EconomicQueryError("owner 返回的同切面原件与固定切面或身份不符")
        orig = response.get("original")
        if type(orig) is not dict:
            raise EconomicQueryError("owner 同切面原件载荷非对象")

        ops = getattr(self, "authorized_read_ops", None)
        has_query_fact = not isinstance(ops, (set, frozenset)) or ("QueryFact" in ops)

        result = _finalize_public_response(self, {
            "kind": "EconomicProjectionOriginal",
            "projection_revision": ECONOMIC_PROJECTION_REVISION,
            "session_id": self.session,
            "session_generation": self.generation,
            "manifest_hash": self.manifest_hash,
            "cuts": cuts,
            "domain_id": domain,
            "original_kind": kind,
            "object_id": object_id,
            "authoritative_image_hash": response["authoritative_image_hash"],
            "authoritative_image_bytes": response["authoritative_image_bytes"],
            "commit_ns": response["commit_ns"],
            "writer_epoch": response["writer_epoch"],
            "original": orig,
        }, requested_cuts=cuts, verify_historical_roots=True)

        # 2. 校验原件精确字节绑定与必备回执结构（权限边界与前沿已由单一出口 _finalize_public_response 守门）。
        def check_fact_bytes(fobj):
            if type(fobj) is not dict:
                raise EconomicQueryError("同切面事实原件载荷非对象")
            raw = text(fobj.get("raw_utf8"), "raw_utf8")
            raw_hash = fobj.get("raw_sha256")
            _hash(raw_hash, "raw_sha256")
            if hashlib.sha256(raw.encode("utf-8")).hexdigest() != raw_hash:
                raise EconomicQueryError("同切面事实原件 raw_utf8 与 raw_sha256 不符")
            if type(fobj.get("receipts")) is not list:
                raise EconomicQueryError("同切面事实缺回执列表")

        if kind == "fact":
            check_fact_bytes(orig)
        elif kind == "allocation":
            rec_key = "resolve_receipt" if domain == "E" else "receipt"
            if type(orig.get(rec_key)) is not dict:
                raise EconomicQueryError("同切面分配缺回执")
            fact_obj = orig.get("fact")
            if fact_obj is not None:
                check_fact_bytes(fact_obj)
            else:
                if has_query_fact:
                    raise EconomicQueryError("同切面分配缺事实原件")
                fref = orig.get("fact_ref")
                if type(fref) is not dict:
                    raise EconomicQueryError("同切面分配缺具名 fact_ref")
                _hash(fref.get("fact_key"), "fact_ref.fact_key")
                _hash(fref.get("fact_hash"), "fact_ref.fact_hash")
        elif kind == "model":
            mr = orig.get("model_ref")
            if type(mr) is not dict:
                raise EconomicQueryError("同切面模型原件缺 model_ref")
            mh = mr.get("content_hash")
            _hash(mh, "model_ref.content_hash")
            if orig.get("model_raw_utf8") is not None:
                if hashlib.sha256(orig["model_raw_utf8"].encode("utf-8")).hexdigest() != mh:
                    raise EconomicQueryError("同切面模型原件字节与 model_ref.content_hash 不符")
        elif kind in ("decision", "grant", "command"):
            recs = [orig.get("receipt")] if kind == "grant" else orig.get("receipts", [])
            if type(recs) is not list or any(type(r) is not dict for r in recs):
                raise EconomicQueryError("同切面财务回执非对象")

        return result

    def watch(self, payload, *, deadline=None, paged=False):
        self._start(deadline)
        self.budget.paged = paged
        if type(payload) is not dict or set(payload) != {"op", "cuts"} or payload["op"] != "watch":
            raise EconomicQueryError("watch 参数不完整或多余")
        cuts = payload["cuts"]
        if type(cuts) is not dict or set(cuts) != set(self.nodes):
            raise EconomicQueryError("watch 须给完整域向量")
        for domain, cut in cuts.items():
            verify_cut(cut, domain)
        def read_changes(domain):
            base = self.view(domain, cuts[domain])
            response = self.owner(domain, {"op": "Watch", "after_cut": cuts[domain]})
            if response.get("kind") != "EconomicChanges" or type(response.get("changes")) is not list:
                raise EconomicQueryError("变化响应不完整")
            if len(response["changes"]) > self.resources["max_changes"]:
                raise EconomicQueryError("QueryBudgetExceeded：变化数量超过事前界限")
            verify_cut(response.get("cut"), domain)
            previous, previous_ns = cuts[domain], integer(base["commit_ns"], "base commit_ns")
            for change in response["changes"]:
                if type(change) is not dict or set(change) != {"cut", "image", "image_hash", "commit_ns"}:
                    raise EconomicQueryError("变化项不是完整原子批次")
                verify_cut(change["cut"], domain)
                ns = integer(change["commit_ns"], "change commit_ns")
                if ns < previous_ns or change["image_hash"] != digest(change["image"]):
                    raise EconomicQueryError("变化时间倒退或完整图像摘要不同")
                if integer(change["cut"]["commit_seq"], "commit_seq") != integer(previous["commit_seq"], "commit_seq") + 1:
                    raise EconomicQueryError("变化序号存在缺口或重复")
                fixed = self.view(domain, change["cut"])
                if (fixed["image"] != change["image"] or fixed["image_hash"] != change["image_hash"]
                        or fixed["commit_ns"] != change["commit_ns"]):
                    raise EconomicQueryError("变化与同切面权威图像/时间不同")
                previous, previous_ns = change["cut"], ns
            if previous != response["cut"]:
                raise EconomicQueryError("变化缺少到实际前沿的完整批次")
            return {"status": "Available", "base_cut": cuts[domain],
                    "next_cut": response["cut"], "changes": response["changes"]}

        domains = self._parallel_domains(read_changes)
        result = _finalize_public_response(self, {
            "kind": "EconomicWatch", "session_id": self.session,
            "session_generation": self.generation, "manifest_hash": self.manifest_hash, "domains": domains,
        }, requested_cuts=cuts)
        limit = self.resources["max_cached_bytes" if paged else "max_reply_bytes"]
        if len(canonical(result)) > limit:
            raise EconomicQueryError("QueryBudgetExceeded：完整经济变化超过事前容量")
        self._remaining_ms()
        return result
