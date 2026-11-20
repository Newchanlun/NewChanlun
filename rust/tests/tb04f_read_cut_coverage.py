"""真实 TB04F 写入→HTTP 读出：锁住结构检查器而不是兜底扫描的协议切面覆盖。"""
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

from economic_http import ECONOMIC_POST_ROUTES
from economic_query import (ECONOMIC_PROJECTION_REVISION, _protocol_cut_candidates,
                            _verify_original_permission_bounds, _verify_protocol_response_cuts)
from s_socket_client import canonical, decode_frame, digest, read_economic_pages


def check(q, qcall, discovery, cuts, previous_e, early_docs, original_objects, out):
    docs, owners, offsets = [], [], []
    saved_owner = q.owner

    def owner(domain, request):
        reply = saved_owner(domain, request)
        if reply.get("kind") in ("EconomicProjectionView", "EconomicOriginalAtCut"):
            owners.append(reply)
        return reply

    def fetch(payload, _remaining):
        if payload["op"] == "EconomicReadPage":
            offsets.append(int(payload["offset"]))
        return qcall("read", payload)

    def paged(request):
        return read_economic_pages(request, fetch, session_id=q.session, session_generation=q.generation,
                                  producer_id="Q:" + q.session, producer_epoch=q.query_epoch,
                                  manifest_hash=q.manifest_hash, owner_epochs=q.epochs, deadline=time.monotonic() + 30)

    def case(route, request, is_paged):
        label = "/".join([route, request["op"], request.get("kind", "")])
        if is_paged:
            doc = paged(request)
        elif route in early_docs:
            doc = early_docs[route]
        else:
            doc = qcall(route, request)
        if doc["kind"] in ("EconomicSnapshot", "EconomicProjection"):
            assert all(v["status"] == "Available" for v in doc["domains"].values()), label
            vector = {d: v["cut"] for d, v in doc["domains"].items()}
        elif doc["kind"] == "EconomicWatch":
            assert all(v["status"] == "Available" for v in doc["domains"].values()), label
            vector = {d: v["next_cut"] for d, v in doc["domains"].items()}
        else:
            vector = cuts
        missed = set()
        _verify_protocol_response_cuts(doc, vector, set(cuts), unlisted_paths=missed)
        assert not missed, (label, sorted(map(str, missed))[:15])
        paths = list(_protocol_cut_candidates(doc))
        assert paths, label
        print("CUT_COVERAGE", label, len(paths), flush=True)
        docs.append({"label": label, "doc": doc, "vector": vector})

    snapshot = {"op": "snapshot", "cuts": cuts, "as_known_ns": None, "snapshot_token": None}
    watch = {"op": "watch", "cuts": {**cuts, "E": previous_e}}
    decision = {"kind": "decision", "domain_id": "B:alpha", "object_id": "alpha"}
    projection = {"op": "projection", "projection_revision": ECONOMIC_PROJECTION_REVISION,
                  "cuts": cuts, "as_known_ns": None, "projection_token": None}
    original = [{"op": "projection_original", "projection_revision": ECONOMIC_PROJECTION_REVISION,
                 "domain_id": d, "kind": kind, "object_id": key, "cuts": cuts}
                for d, kind, key in original_objects]
    requests = {"snapshot": [snapshot], "watch": [watch], "projection": [projection],
                "original": [{"op": "original", "cuts": cuts, **decision}], "projection_original": original}

    q.owner = owner
    try:
        for route, op in ECONOMIC_POST_ROUTES.items():
            if op == "read":
                for name, (_, paged_ok, _) in q.PUBLIC_READ_DISPATCH.items():
                    if paged_ok:
                        for req in requests[name]:
                            case(op, req, True)
            else:
                for req in requests[op]:
                    case(op, req, False)
    finally:
        q.owner = saved_owner

    assert max(offsets) >= 262144, offsets
    counts = Counter(row["original_kind"] for row in owners if row["kind"] == "EconomicOriginalAtCut")
    assert set(counts) == set(q.projection_original_kinds), counts
    assert all(item["doc"]["domains"]["E"]["changes"] for item in docs if item["doc"]["kind"] == "EconomicWatch")
    assert any(path[-1:] == ("e_release_cut",) for item in docs for path, _ in _protocol_cut_candidates(item["doc"]))
    projection = next(item["doc"] for item in docs if item["doc"]["kind"] == "EconomicProjection")
    allocation = next(item["doc"]["original"] for item in docs if item["label"] == "read/projection_original/allocation")
    allocation_id = allocation["allocation_id"]
    row = next(row for row in projection["domains"]["E"]["projection"]["fill_allocations"]
               if any(a["allocation_id"] == allocation_id for a in row["allocations"]))
    # With all read rights the real E witness keeps every field, not just those named by this fix.
    assert row == allocation["fill_allocation_row"], {
        key: (key in row, key in allocation["fill_allocation_row"])
        for key in row.keys() | allocation["fill_allocation_row"].keys()
        if row.get(key) != allocation["fill_allocation_row"].get(key)
    }
    corpus = {"discovery": discovery, "public": docs, "owner": owners}
    out.write_bytes(canonical(corpus))
    subprocess.run(["node", str(Path(__file__).with_suffix(".cjs")), str(out)], check=True)


def check_transfer(owner_corpus, out):
    """以 Q 的聚合外壳转交真实 C5 转入 owner 正文；原像、证明、回执都不重造。"""
    wire = decode_frame(owner_corpus.read_bytes())
    source = wire["original"]
    identity = {k: source[k] for k in ("session_id", "session_generation", "projection_revision")}
    identity["manifest_hash"] = digest("TestOnly C5 writer fixture")
    views = wire["views"]
    cuts = {view["domain_id"]: view["cut"] for view in views}
    discovery = {**identity, "domains": list(cuts), "book_revision": "tb03c-book/1",
                 "read_projection": {"owner_epochs": {d: "1" for d in cuts}, "original_kinds": ["fact"]}}
    domains = {v["domain_id"]: {"status": "Available", **{k: val for k, val in v.items() if k not in
               {"kind", "domain_id", "session_id", "session_generation", "runtime"}}} for v in views}
    projection = {**identity, "kind": "EconomicProjection", "mode": "AsKnown", "as_known_ns": None,
                  "domains": domains, "projection_completeness": "CompleteProjectionVector"}
    projection["projection_token"] = "economic-projection-" + digest(projection)
    original = {**identity, **{k: v for k, v in source.items() if k not in {"cut", "audit_verified"}},
                "kind": "EconomicProjectionOriginal", "cuts": cuts}
    _verify_original_permission_bounds(original["original"], {"QueryFact"})
    docs = []
    for label, doc in (("real-transfer/projection", projection), ("real-transfer/fact", original)):
        missed = set()
        _verify_protocol_response_cuts(doc, cuts, set(cuts), unlisted_paths=missed)
        assert not missed, (label, missed)
        assert any("b_source_debit_proof" in p for p, _ in _protocol_cut_candidates(doc)), label
        print("CUT_COVERAGE", label, len(list(_protocol_cut_candidates(doc))), flush=True)
        docs.append({"label": label, "doc": doc, "vector": cuts})
    out.write_bytes(canonical({"discovery": discovery, "public": docs, "owner": []}))
    subprocess.run(["node", str(Path(__file__).with_suffix(".cjs")), str(out)], check=True)


if __name__ == "__main__":
    check_transfer(*map(Path, sys.argv[1:]))
