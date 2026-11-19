#!/usr/bin/env python3
"""#1425 TB-04-F 单一明确原责任域正式多进程入口：
从空库启动真实 E/B:alpha/B:beta/X/受控 S/Q，执行：
  开账 → Prepare → Reserve → Commit → MakeDispatchable → ReleaseExact(bar 2)
  → X AcceptExact & ExecuteCommitted(bar 2) → X bar 3 产出 fill(2*14=28,fee=1) 与独立 fee(1)
  → E.CaptureExternal(双件，不预列未来 key) → 负控(早 Apply / 先 Resolve fee)
  → E.ResolveEvidence(先 fill 后 fee，同游标 3 不吞费) → 负控(早 Apply fee / 错重 B:beta / 错 allocation_id)
  → B:alpha.ApplyAllocation(fill→6/80028, fee→6/80029, K=80029, B:beta 不动, E 责任维持 90)
  → HTTP EconomicQuery 同切面快照与原件校验 → 停服冷恢复(writer_epoch=2)逐值对拍 → --twice 确定性重放。
不触碰原 C3 冻结库，不替上游伪造归属，不提前减责。
"""
import argparse
import errno
import hashlib
import json
import shutil
import socket
import sqlite3
import subprocess
import sys
import threading
import time
from contextlib import closing
from pathlib import Path
from urllib.request import Request, urlopen

from history_fixture_model import model

parser = argparse.ArgumentParser(
    description="#1425 TB-04-F 单一明确原责任域正式 E/B/X/Q 非真空工作例（独立新库）。"
)
parser.add_argument("--bin", type=Path, required=True)
parser.add_argument("--out", type=Path, required=True)
parser.add_argument(
    "--twice",
    action="store_true",
    help="同一路径两次从空库运行，对比 E/B/X 恢复前业务全表逐字节一致",
)
args = parser.parse_args()

src = Path(__file__).resolve().parents[2]
bins, run = args.bin.resolve(), args.out.resolve()
run.mkdir(mode=0o700)

if args.twice:
    child = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--bin",
        str(bins),
        "--out",
        str(run / "case"),
    ]
    for name in ("a", "b"):
        subprocess.run(child, check=True)
        (run / "case").rename(run / name)
    first = (run / "a/business.json").read_bytes()
    second = (run / "b/business.json").read_bytes()
    assert first == second, "两次空库重放的 E/B/X 全表不一致"
    print(f"PASS: 两次空库 E/B/X 业务全表逐字节相同，{len(first)} 字节")
    sys.exit(0)

sys.path.insert(0, str(src / "s_session"))
from s_socket_client import (
    canonical,
    decode_frame,
    digest,
    read_economic_pages,
    reply_envelope,
    validate_reply,
)


def write(name, obj):
    p = run / name
    with p.open("xb") as f:
        f.write(canonical(obj))
    return p


def file_digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def same(left, right):
    return canonical(left) == canonical(right)


def source_key(source):
    return digest([source["source_namespace"], source["source_epoch"], source["external_fact_id"]])


sid, gen = "tb1425-single-owner", "1"
model_config = {**model(), "symbol": "alpha"}
model_hash = digest(model_config)
x_db_path = run / "x.db"
x_socket = str(run / "x.sock")

# 构造独立的 tb03c-book/1 + tb03b-finance/5 冻结输入（baseline 仅覆盖开账，不预列未来成交）
s_object = {"object_id": "unit-S-object", "kind": "UnitStructuralTrustRoot", "branch": "RISING"}
s_basis = {
    "kind": "FinancialBasis",
    "session_id": sid,
    "session_generation": gen,
    "writer_epoch": "1",
    "pending_revision": False,
    "commit_ns": "1",
    "snapshot": {"profile_id": "unit", "objects": [s_object]},
}
basis_path = write("s-basis.json", s_basis)
stub_path = run / "s-unit-stub.sh"
assert "'" not in str(basis_path)
stub_path.write_text(f"#!/bin/sh\nexec /bin/cat '{basis_path}'\n")
stub_path.chmod(0o700)

units = {
    "quantity": {"unit": "TEST-UNIT", "quantum": "1"},
    "money": {"unit": "TEST-CASH", "currency": "TEST-CASH", "quantum": "1"},
    "numeric_encoding": "exact_decimal_integer_text",
}

covered, authorities, rights, plans_list, routes = [], [], [], [], []
opener, binding = {}, {}
for name, family, fixed, qty, cash, new_qty, price, fee, concurrency in [
    ("alpha", "family-alpha", "12", "4", "40", "2", "14", "2", "single"),
    ("beta", "family-beta", "20", "15", "50", "3", "12", "4", "batched"),
]:
    doc = {
        "format": "neutral TestOnly economic raw originals; not production transport wire",
        "units": units,
        "events": [
            {
                "event": "known-opening",
                "source": {
                    "source_namespace": "test",
                    "source_epoch": "one",
                    "source_cursor": "1",
                    "external_fact_id": f"opening-{name}",
                    "received_time": "source-received",
                    "claimed_origin": "TestOnly source",
                },
                "allocation_id": f"allocation-{name}",
                "family_id": family,
                "book_identity": {
                    "chong_id": name,
                    "symbol": name,
                    "op_level": "2",
                    "fixed_q": fixed,
                    "side": "long",
                },
                "stable_point": {"profile": "TestOnly", "seq": "1", "source_ref": "sp"},
                "observed_existing_book": {
                    "units": qty,
                    "Pi": "900",
                    "A": "200",
                    "W": "100",
                    "witness_refs": {"units": "u", "Pi": "p", "A": "a", "W": "w"},
                },
                "known_cost_components": [
                    {
                        "kind": "acquisition_cash",
                        "amount_text": "80000",
                        "canonical_amount": "80000",
                        "source_ref": "cost",
                        "currency": "TEST-CASH",
                        "quantum": "1",
                    }
                ],
            }
        ],
        "evidence_index": {
            "fragments": {
                "u": [{"json_pointer": "/events/0/observed_existing_book/units"}],
                "p": [{"json_pointer": "/events/0/observed_existing_book/Pi"}],
                "a": [{"json_pointer": "/events/0/observed_existing_book/A"}],
                "w": [{"json_pointer": "/events/0/observed_existing_book/W"}],
                "cost": [{"json_pointer": "/events/0/known_cost_components/0"}],
                "sp": [{"json_pointer": "/events/0/stable_point"}],
            }
        },
    }
    raw_bytes = canonical(doc)
    raw_sha = hashlib.sha256(raw_bytes).hexdigest()
    ev = doc["events"][0]
    fk = source_key(ev["source"])
    fh = digest({"raw_sha256": raw_sha, "json_pointer": "/events/0", "event": ev, "units": units})
    covered.append({"fact_key": fk, "fact_hash": fh, "token": f"token-{name}"})
    opener[name] = raw_bytes.decode("utf-8")

    def ref(obj_id):
        return {
            "authority_id": name,
            "object_id": obj_id,
            "revision": "0",
            "content_hash": digest(obj_id),
        }

    bind = {
        "op": "BindVoice",
        "binding_id": f"voice-{name}",
        "evidence_id": name,
        "carrier_ref": ref("unit-carrier"),
        "gamma_ref": ref("unit-gamma"),
        "parent_voice_id": None,
        "sigma": "Long",
        "n": "0",
        "opening_basis": {
            "fact_key": fk,
            "expected_fact_hash": fh,
            "allocation_id": f"allocation-{name}",
        },
    }
    binding[name] = bind
    artifacts = []
    for art in ("input", "controlled_gammas", "carrier_objects", "instrument_declaration", "opening_raw"):
        val = doc if art == "opening_raw" else {"scope": "unit trust root only, not formal gamma proof", "name": art}
        ap = write(f"{name}-{art}.json", val)
        artifacts.append(
            {"name": art, "path": str(ap), "sha256": file_digest(ap), "bytes": str(ap.stat().st_size)}
        )
    bundle = {
        "schema": "voice-binding-authority/1",
        "authority_id": name,
        "source": {
            "instrument": name,
            "input_sha256": artifacts[0]["sha256"],
            "profile_id": "unit",
            "first_confirming_observation_source": "1",
            "clock_mapping": {
                "kind": "TestOnlyAffineOrdinalToNs",
                "source_origin": "0",
                "nanosecond_origin": "0",
                "nanoseconds_per_ordinal": "1",
            },
        },
        "artifacts": artifacts,
        "bindings": [
            {
                "evidence_id": name,
                "instrument": name,
                "chong_id": name,
                "operation_level": "2",
                "carrier_ref": bind["carrier_ref"],
                "gamma_ref": bind["gamma_ref"],
                "sigma": "Long",
                "n": "0",
                "parent_voice_id": None,
                "structure_view": {
                    "profile_id": "unit",
                    "execution_level": "2",
                    "confirmation_level": "3",
                    "nest_depth": "1",
                },
                "opening_source": {
                    "fact_key": fk,
                    "fact_hash": fh,
                    "allocation_id": f"allocation-{name}",
                    "raw_sha256": raw_sha,
                    "json_pointer": "/events/0",
                    "quantity": qty,
                    "units": units,
                },
            }
        ],
    }
    bp = write(f"{name}-authority.json", bundle)
    bh = file_digest(bp)
    review = {
        "schema": "voice-binding-independent-verification/1",
        "verdict": "APPROVE_CONTROLLED_VOICE_BINDING",
        "authority_id": name,
        "bundle_sha256": bh,
        "artifacts": artifacts,
        "verified_evidence_ids": [name],
        "scope": "unit trust fixture only; no independent acceptance",
    }
    rp = write(f"{name}-unit-review.json", review)
    authorities.append(
        {
            "authority_id": name,
            "bundle_path": str(bp),
            "bundle_sha256": bh,
            "verification_path": str(rp),
            "verification_sha256": file_digest(rp),
            "max_bytes": "1048576",
        }
    )
    rights.append(
        {
            "right_id": name,
            "owner": f"B:{name}",
            "version": "1",
            "amount": cash,
            "currency": "TEST-CASH",
            "source_ref": f"TestOnly-privately-owned-cash-original/{name}",
        }
    )
    plans_list.append(
        {
            "decision_id": name,
            "attempt_id": f"attempt-{name}",
            "plan_id": f"plan-{name}",
            "owner": f"B:{name}",
            "voice_binding_id": f"voice-{name}",
            "right_id": name,
            "expected_book_version": "2",
            "expected_rights_version": "1",
            "applicant_epoch": "1",
            "applicant_generation": "1",
            "slot_id": "slot",
            "quantity": new_qty,
            "limit_price": price,
            "fee_tail": fee,
            "quantity_source": f"TestOnly-quantity/{name}",
            "price_source": f"TestOnly-price/{name}",
            "fee_source": f"TestOnly-tail/{name}",
            "s_ref": {"object_id": "unit-S-object", "object_hash": digest(s_object), "profile_id": "unit"},
            "o_ref": {
                "operation_id": f"TestOnly-operation-{name}",
                "kind": "TestOnlyCashBuy",
                "source_ref": f"TestOnly-operation-sheet/{name}",
                "s_object_id": "unit-S-object",
                "quantity": new_qty,
            },
            "exact": {
                "command_id": f"cmd-{name}",
                "logical_order_family": f"family-{name}",
                "chong_id": name,
                "revision": "1",
                "first_quantity": new_qty,
                "allocation_id": f"alloc-{name}",
                "side": "buy",
                "symbol": name,
                "projection_manifest": f"TestOnly-projection/{name}",
                "eligibility_ref": f"S:cmd-{name}",
                "concurrency": concurrency,
            },
        }
    )
    routes.append(
        {
            "chong_id": name,
            "symbol": name,
            "operation_level": "2",
            "fixed_q": fixed,
            "db": str(run / f"{name}.db"),
            "socket": str(run / f"{name}.sock"),
        }
    )

conditions = [
    {
        "condition_id": cid,
        "authority_revision": cap,
        "dependency_set": ["controlled-dependency"],
        "invalidation_sources": ["controlled-invalidation"],
        "required_check_stages": [stage],
        "evidence_refs": ["controlled-evidence"],
        "coverage_proof": "controlled-coverage",
        "validator_capability": cap,
        "failure_result": "Denied",
    }
    for cid, cap, stage in [
        ("released-exact/1", "released-exact/1", "E.ReleaseExact"),
        ("execute-committed/1", "execute-committed/1", "S.RequestConditionalExecution"),
        ("simulation-local-transaction/1", "simulation-local-transaction/1", "X.OwnAttemptAndCall"),
        ("model_coverage", "model-coverage/1", "E.ReleaseExact"),
    ]
]
applicants = ["alpha", "beta"]
data = {
    "schema_revision": "tb03b-finance/6",
    "kind": "TestOnly",
    "source_id": "tb1425-fixture",
    "source_epoch": "1",
    "policy": {
        "policy_id": "TestOnly-cash-cap-100",
        "allocation_policy_id": "#1349/atomic-slot-wait/v1",
        "cap": "100",
        "currency": "TEST-CASH",
        "money_unit": "TEST-CASH",
        "quantity_unit": "TEST-UNIT",
        "quantum": "1",
        "capability_id": "TestOnly-no-leverage-no-venue",
        "model": "TestOnlyUnleveragedCashBuy",
        "valid_through_ns": "100000",
    },
    "baseline": {
        "responsibility_id": "existing20",
        "amount": "20",
        "source_ref": "TestOnly-existing-full-liability-original",
        "covered_facts": covered,
    },
    "rights": rights,
    "plans": plans_list,
    "slots": [
        {
            "slot_id": "slot",
            "applicants": applicants,
            "input_end": {
                "kind": "ControlledInputEnd",
                "source_id": "tb1425-fixture",
                "source_epoch": "1",
                "watermark": "2",
                "complete_request_hash": digest(applicants),
            },
        }
    ],
    "exact_release": {
        "x_target": {"x_id": "X", "x_epoch": "1"},
        "projection_kind": "per_leg",
        "rd11_policy": "controlled-fixture-rd11",
        "rule_revision": "TestOnly-rule/1425",
        "market_dependencies": ["TestOnly-market/1425"],
        "conditions": conditions,
        "model_coverage": {
            "model_ref": {
                "model_id": model_config["model_id"],
                "revision": model_config["revision"],
                "content_hash": model_hash,
            },
            "domain_id": "TestOnly-domain/1425",
            "input_domain": [
                {"order_kind": "limit", "concurrency": "single", "allocation_model": "#1349/atomic-slot-wait/v1"}
            ],
            "unsupported_domains": [
                {"order_kind": "limit", "concurrency": "batched", "allocation_model": "#1349/atomic-slot-wait/v1"}
            ],
        },
    },
}
data_path = write("input.json", data)
plans = {q["decision_id"]: q for q in plans_list}

src_biz = {"source_namespace": "test", "source_epoch": "one", "producer_id": "unit", "producer_epoch": "1"}
src_x = {"source_namespace": "x-sim", "source_epoch": "epoch1", "producer_id": "X", "producer_epoch": "1"}
src_resolver = {"source_namespace": "x-sim", "source_epoch": "epoch1", "producer_id": "resolver", "producer_epoch": "1"}
src_q = {"source_namespace": "test-query", "source_epoch": "fixture-1", "producer_id": "reader", "producer_epoch": "1"}

messages = {
    "capture-alpha": "1",
    "apply-alpha": "1",
    "bind-alpha": "1",
    "capture-beta": "1",
    "apply-beta": "1",
    "bind-beta": "1",
    "ImportResponsibility-existing20": "1",
    "PrepareDecision-alpha": "1",
    "PrepareDecision-beta": "1",
    "Reserve-slot": "1",
    "CommitDecision-alpha": "1",
    "CommitDecision-beta": "1",
    "MakeDispatchable-alpha": "1",
    "ReleaseExact-alpha": "2",
    "capture-sim-fill": "3",
    "capture-sim-fill-retry": "3",
    "capture-sim-fee": "3",
    "apply-fill-before-resolve": "3",
    "resolve-fee-before-fill": "3",
    "resolve-sim-fill": "3",
    "resolve-sim-fill-retry": "3",
    "resolve-sim-fee": "3",
    "apply-fee-before-fill": "3",
    "apply-fill-wrong-chong": "3",
    "apply-fill-bad-id": "3",
    "apply-sim-fill": "3",
    "apply-sim-fill-retry": "3",
    "apply-sim-fee": "3",
    "apply-sim-fee-retry": "3",
}

manifest = {
    "schema_revision": "economic-manifest/1",
    "session_id": sid,
    "session_generation": gen,
    "book_revision": "tb03c-book/1",
    "e": {"db": str(run / "e.db"), "socket": str(run / "e.sock")},
    "chongs": routes,
    "authorized_sources": [
        {
            **src_biz,
            "operations": [
                "ImportResponsibility",
                "CaptureExternal",
                "ApplyAllocation",
                "BindVoice",
                "ReadView",
                "Watch",
                "QueryFact",
                "QueryAllocation",
                "QueryDecision",
                "QueryGrant",
                "QueryVoice",
                "PrepareDecision",
                "Reserve",
                "CommitDecision",
                "MakeDispatchable",
                "ReleaseExact",
                "QueryCommand",
                "QueryReleasedExact",
            ],
        },
        {**src_x, "operations": ["QueryReleasedExact", "CaptureExternal"]},
        {**src_resolver, "operations": ["ResolveEvidence"]},
        {
            **src_q,
            "operations": [
                "ReadView",
                "Watch",
                "QueryFact",
                "QueryAllocation",
                "QueryCommand",
                "QueryGrant",
                "QueryDecision",
                "QueryVoice",
                "EconomicReadOpen",
                "EconomicReadPage",
                "EconomicReadClose",
            ],
        },
    ],
    "history_simulation_source": {
        **src_x,
        "x_db": str(x_db_path),
        "model_content_hash": model_hash,
    },
    "resources": {
        "max_frame_bytes": "16777216",
        "read_timeout_ms": "2000",
        "write_timeout_ms": "2000",
        "response_timeout_ms": "30000",
        "queue_capacity": "8",
        "max_connections": "8",
    },
    "clock": {"kind": "logical-bar/1", "bars": {"init": "0", "recover": ["3", "3"], "messages": messages}},
    "voice_binding": {"schema_revision": "voice-binding/1", "authorities": authorities},
    "finance": {
        "schema_revision": "tb03b-finance/6",
        "input_path": str(data_path),
        "input_sha256": file_digest(data_path),
        "coordinator_source": src_biz,
        "structure": {
            "binary": str(stub_path),
            "binary_sha256": file_digest(stub_path),
            "db": str(run / "s-unit.db"),
            "session_id": sid,
            "session_generation": gen,
            "writer_epoch": "1",
        },
    },
}
manifest_path = write("manifest.json", manifest)
nodes = {"E": manifest["e"], **{f"B:{x['chong_id']}": x for x in routes}}
eb, bb, xb = [str(bins / x) for x in ("e_economic_session", "b_chong_session", "x_execution_session")]


def write_control_configs(suffix, epoch_str):
    ep = {d: epoch_str for d in nodes}
    lc = write(
        f"economic-launcher-{suffix}.json",
        {
            "schema_revision": "economic-launcher/1",
            "manifest": str(manifest_path),
            "manifest_hash": digest(manifest),
            "python": sys.executable,
            "e_binary": eb,
            "b_binary": bb,
            "state_root": str(run / "control"),
            "startup_timeout_ms": "15000",
            "probe_source": src_q,
            "expected_epochs": ep,
        },
    )
    qc = write(
        f"economic-query-{suffix}.json",
        {
            "schema_revision": "economic-query/1",
            "manifest": str(manifest_path),
            "manifest_hash": digest(manifest),
            "query_source": src_q,
            "producer_epoch": "1",
            "expected_epochs": ep,
            "resources": {
                "max_frame_bytes": "16777216",
                "timeout_ms": "10000",
                "operation_timeout_ms": "30000",
                "max_reply_bytes": "16777216",
                "max_cached_bytes": "16777216",
                "max_snapshots": "4",
                "max_domains": "3",
                "max_changes": "10",
            },
        },
    )
    return lc, qc, ep


lc1, qc1, epochs1 = write_control_configs("ep1", "1")
lc2, qc2, epochs2 = write_control_configs("ep2", "2")

processes = []
trace = (run / "steps.jsonl").open("x", buffering=1)
ctl_trace = (run / "commands.jsonl").open("x", buffering=1)


def command(label, argv, *, expected=0):
    argv = list(map(str, argv))
    with (run / f"{label}.stdout").open("xb") as out, (run / f"{label}.stderr").open("xb") as err:
        if expected is None:
            p = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=out, stderr=err)
            processes.append((label, p))
            info = {"pid": p.pid}
        else:
            p = subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=out, stderr=err, timeout=30)
            info = {"exit": p.returncode}
    ctl_trace.write(json.dumps({"step": label, "argv": argv, **info}) + "\n")
    if expected is not None:
        assert p.returncode == expected, (label, p.returncode, (run / f"{label}.stderr").read_text())
    return p


def launcher(action, domain, lc_path, tag=None):
    label = tag or f"{action}-{domain.replace(':', '-')}"
    return command(
        label,
        [sys.executable, src / "s_session/economic_service_control.py", action, "--config", lc_path, "--domain", domain],
    )


def wait_ready(p, address, label):
    limit = time.monotonic() + 10
    while time.monotonic() < limit:
        assert p.poll() is None, (label, p.returncode, (run / f"{label}.stderr").read_text())
        with socket.socket(socket.AF_UNIX) as s:
            s.settimeout(1)
            try:
                s.connect(address)
            except (FileNotFoundError, ConnectionRefusedError):
                time.sleep(0.02)
                continue
            try:
                s.shutdown(socket.SHUT_WR)
            except OSError as exc:
                if exc.errno != errno.ENOTCONN:
                    raise
            raw = s.makefile("rb").readline()
            if raw:
                assert decode_frame(raw).get("ok") is False, (label, raw)
                return
    raise TimeoutError((label, address))


def wire(domain, label, request, *, expected=None, producer_epoch="1"):
    message = canonical(request) + b"\n"
    (run / f"{label}.request.wire").write_bytes(message)
    address = x_socket if domain == "X" else nodes[domain]["socket"]
    with socket.socket(socket.AF_UNIX) as s:
        s.settimeout(12)
        s.connect(address)
        s.sendall(message)
        s.shutdown(socket.SHUT_WR)
        raw = s.makefile("rb").readline(16777217)
    (run / f"{label}.reply.wire").write_bytes(raw)
    assert raw.endswith(b"\n") and len(raw) <= 16777216, (label, raw[:200])
    result = decode_frame(raw)
    if domain != "X":
        result = validate_reply(request, result, producer=domain, producer_epoch=producer_epoch)
    trace.write(
        json.dumps(
            {
                "label": label,
                "domain": domain,
                "kind": result.get("kind"),
                "state": result.get("state") or (result.get("record") or {}).get("state"),
                "cut": result.get("cut"),
                "error": result.get("error"),
            }
        )
        + "\n"
    )
    if expected is not None:
        assert result.get("kind") == expected, (label, result)
    return result


def ewire(domain, message, payload, expected=None, source=src_biz, producer_epoch="1"):
    return wire(
        domain,
        message,
        {
            "schema_revision": "economic-session/1",
            "session_id": sid,
            "session_generation": gen,
            **source,
            "message_id": message,
            "payload_hash": digest(payload),
            "causal_refs": [],
            "payload": payload,
        },
        expected=expected,
        producer_epoch=producer_epoch,
    )


def xwire(message, op, payload, expected):
    return wire("X", message, {"protocol": "x-exact-simulation/1", "op": op, "payload": payload}, expected=expected)


def business_dump(db):
    with closing(sqlite3.connect(db.as_uri() + "?mode=ro", uri=True)) as c:
        names = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]

        def cell(v):
            return {"blob": v.hex()} if isinstance(v, bytes) else v

        return {
            n: sorted(
                ([cell(v) for v in r] for r in c.execute('SELECT * FROM "' + n.replace('"', '""') + '"')),
                key=canonical,
            )
            for n in names
        }


def query_http_snapshot(qc_path, expected_epochs, tag, *, cuts=None, expect_complete=True):
    from economic_query import EconomicQuery
    from s_readonly_server import Handler, QueryHTTPServer

    resources = decode_frame((src / "s_session/tests/fixtures/tb01c/query-resources.json").read_bytes())
    Handler.browser_path = str(src / "s_session/browser/index.html")
    http = QueryHTTPServer(("127.0.0.1", 0), Handler, str(run / "unused-structure.db"), resources, 1)
    http.economic_query = EconomicQuery(qc_path)
    thread = threading.Thread(target=http.serve_forever, daemon=True)
    thread.start()
    idx = [0]
    try:
        base = f"http://127.0.0.1:{http.server_port}/api/economic/"

        def qcall(op, payload):
            idx[0] += 1
            frame = {
                "schema_revision": "economic-session/1",
                "session_id": sid,
                "session_generation": gen,
                **src_q,
                "message_id": f"http-{tag}-{op}-{idx[0]}",
                "causal_refs": [],
                "payload_hash": digest(payload),
                "payload": payload,
            }
            raw_req = canonical(frame)
            req = Request(base + op, data=raw_req, headers={"Content-Type": "application/json"})
            with urlopen(req, timeout=30) as stream:
                raw = stream.read()
            return validate_reply(frame, decode_frame(raw), producer="Q", producer_epoch="1")

        snap = read_economic_pages(
            {"op": "snapshot", "cuts": cuts, "as_known_ns": None, "snapshot_token": None},
            lambda payload, remaining_ms: qcall("read", payload),
            session_id=sid,
            session_generation=gen,
            producer_id="Q:" + sid,
            producer_epoch="1",
            manifest_hash=digest(manifest),
            owner_epochs=expected_epochs,
            deadline=time.monotonic() + 30,
        )
        if expect_complete:
            assert snap["completeness"] == "CompleteVector", snap
            snap_cuts = {d: v["cut"] for d, v in snap["domains"].items()}
            cmd_orig = qcall(
                "original",
                {"op": "original", "kind": "command", "object_id": "cmd-alpha", "domain_id": "E", "cuts": snap_cuts},
            )
            assert cmd_orig["cuts"] == snap_cuts
            return snap, cmd_orig
        return snap, None
    finally:
        http.shutdown()
        http.server_close()


def probe_post_applied_public_query_gap(qc_path, expected_epochs, fill_cuts, final_cuts, resolved_cuts, tag):
    """实测同一最终 Applied cut（与单笔 fill 后 cut 5）在既有公开端与既有浏览器客户端下的真实首拒。"""
    import shutil
    from urllib.error import HTTPError
    from economic_query import EconomicQuery
    from s_readonly_server import Handler, QueryHTTPServer

    evidence = {"tag": tag, "limits": {"read_cache_bytes": 4 * 1048576, "single_frame_http_bytes": 1048576}}
    # 1) B:alpha owner 直连分页 EconomicReadOpen(ReadView) 在最终 cut 6 的真实首拒
    owner_open_cut6 = ewire(
        "B:alpha",
        f"probe-owner-open-cut6-{tag}",
        {
            "schema_revision": "economic-read-pages/1",
            "op": "EconomicReadOpen",
            "query": {"op": "ReadView", "cut": final_cuts["B:alpha"], "as_known_ns": None},
            "requested_remaining_ms": "15000",
        },
        "EconomicReadError",
        source=src_q,
        producer_epoch=expected_epochs["B:alpha"],
    )
    evidence["owner_b_alpha_cut6_paged_open"] = owner_open_cut6

    # 2) HTTP Q 公开端实测
    resources = decode_frame((src / "s_session/tests/fixtures/tb01c/query-resources.json").read_bytes())
    Handler.browser_path = str(src / "s_session/browser/index.html")
    http = QueryHTTPServer(("127.0.0.1", 0), Handler, str(run / "unused-structure.db"), resources, 1)
    http.economic_query = EconomicQuery(qc_path)
    thread = threading.Thread(target=http.serve_forever, daemon=True)
    thread.start()
    idx = [0]
    try:
        base = f"http://127.0.0.1:{http.server_port}/api/economic/"

        def raw_http(op, payload):
            idx[0] += 1
            frame = {
                "schema_revision": "economic-session/1",
                "session_id": sid,
                "session_generation": gen,
                **src_q,
                "message_id": f"probe-{tag}-{op}-{idx[0]}",
                "causal_refs": [],
                "payload_hash": digest(payload),
                "payload": payload,
            }
            req = Request(base + op, data=canonical(frame), headers={"Content-Type": "application/json"})
            try:
                with urlopen(req, timeout=30) as stream:
                    raw = stream.read()
                decoded = decode_frame(raw)
                return {"http_status": 200, "payload": decoded.get("payload", decoded)}
            except HTTPError as exc:
                body = exc.read()
                try:
                    decoded = decode_frame(body)
                except Exception:
                    decoded = body.decode("utf-8", errors="replace")
                return {"http_status": exc.code, "body": decoded}

        # 2a) 中间态 cut 5（仅 apply 1 笔 fill，B:alpha < 4MiB，但 Q 聚合三域 > 4MiB）
        evidence["http_q_read_open_cut5"] = raw_http(
            "read",
            {
                "schema_revision": "economic-read-pages/1",
                "op": "EconomicReadOpen",
                "query": {"op": "snapshot", "cuts": fill_cuts, "as_known_ns": None, "snapshot_token": None},
                "requested_remaining_ms": "15000",
            },
        )
        # 2b) 终态 cut 6（fill + fee 后，B:alpha 单域 > 4MiB → Q 返回 PartialVector，B:alpha Unavailable）
        snap_cut6 = read_economic_pages(
            {"op": "snapshot", "cuts": final_cuts, "as_known_ns": None, "snapshot_token": None},
            lambda payload, remaining_ms: raw_http("read", payload)["payload"],
            session_id=sid,
            session_generation=gen,
            producer_id="Q:" + sid,
            producer_epoch="1",
            manifest_hash=digest(manifest),
            owner_epochs=expected_epochs,
            deadline=time.monotonic() + 30,
        )
        evidence["http_q_read_cut6_completeness"] = snap_cut6["completeness"]
        evidence["http_q_read_cut6_b_alpha"] = snap_cut6["domains"]["B:alpha"]
        # 2c) 旧单帧 /api/economic/snapshot（1MiB 上限）
        evidence["http_q_single_frame_snapshot_cut6"] = raw_http(
            "snapshot",
            {"op": "snapshot", "cuts": final_cuts, "as_known_ns": None, "snapshot_token": None},
        )
        # 2d) /api/economic/original：allocation 未开放，B:alpha decision 因 self.view 读全图被 4MiB 拒绝
        evidence["http_q_original_allocation_cut6"] = raw_http(
            "original",
            {"op": "original", "kind": "allocation", "domain_id": "B:alpha", "object_id": "probe", "cuts": final_cuts},
        )
        evidence["http_q_original_decision_alpha_cut6"] = raw_http(
            "original",
            {"op": "original", "kind": "decision", "domain_id": "B:alpha", "object_id": "alpha", "cuts": final_cuts},
        )
        # 2e) 既有浏览器客户端 s_session/browser/tb03a-client.js 真实连本机 HTTP Q（Node + 原生 fetch）
        node_bin = shutil.which("node")
        if node_bin:
            js = r"""
const TB03A = require(process.argv[1]);
const base = process.argv[2];
const resolvedCuts = JSON.parse(process.argv[3]);
const finalCuts = JSON.parse(process.argv[4]);
async function main() {
  const client = new TB03A.Client({
    fetcher: (path, opts) => fetch(base + path, opts),
  });
  const out = {};
  out.discovery = await client.discover();
  try {
    await client.load({ cuts: finalCuts });
    out.final_cut6 = { ok: true };
  } catch (e) {
    out.final_cut6 = { ok: false, error: e.message };
  }
  try {
    await client.load({ cuts: resolvedCuts });
    out.resolved_cuts = { ok: true };
  } catch (e) {
    out.resolved_cuts = { ok: false, error: e.message };
  }
  console.log(JSON.stringify(out));
}
main().catch((e) => { console.error(e.stack || String(e)); process.exit(1); });
"""
            proc = subprocess.run(
                [
                    node_bin,
                    "-e",
                    js,
                    str(src / "s_session/browser/tb03a-client.js"),
                    f"http://127.0.0.1:{http.server_port}",
                    json.dumps(resolved_cuts),
                    json.dumps(final_cuts),
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            assert proc.returncode == 0, proc.stderr
            evidence["browser_tb03a_client"] = json.loads(proc.stdout)
        else:
            evidence["browser_tb03a_client"] = {"skipped": "node not installed"}
    finally:
        http.shutdown()
        http.server_close()
    return evidence


started_domains = []
try:
    # 1. 启动正式 E, B:alpha, B:beta
    for d in nodes:
        launcher("start", d, lc1)
        started_domains.append(d)

    # 2. 开账 → BindVoice → ImportResponsibility(existing20)
    for a, raw in opener.items():
        cap = ewire(
            "E",
            f"capture-{a}",
            {"op": "CaptureExternal", "raw_utf8": raw, "json_pointer": "/events/0", "token": f"token-{a}", "source_event_time": None},
            "Recorded",
        )
        ewire(
            f"B:{a}",
            f"apply-{a}",
            {"op": "ApplyAllocation", "fact_key": cap["fact_key"], "allocation_id": f"allocation-{a}", "expected_fact_hash": cap["fact_hash"]},
            "Applied",
        )
        ewire(f"B:{a}", f"bind-{a}", binding[a], "VoiceBound")
    ewire("E", "ImportResponsibility-existing20", {"op": "ImportResponsibility", "responsibility_id": "existing20", "writer_epoch": "1"}, "ResponsibilityImportedReceipt")

    # 3. Prepare → Reserve → Commit → MakeDispatchable → ReleaseExact(cmd-alpha @ bar 2)
    for a, q in plans.items():
        ewire(f"B:{a}", f"PrepareDecision-{a}", {"op": "PrepareDecision", "decision_id": a, "plan_hash": digest(q), "writer_epoch": "1"}, "PreparedReceipt")
    res = ewire("E", "Reserve-slot", {"op": "Reserve", "slot_id": "slot", "request_set_hash": digest(applicants), "writer_epoch": "1"}, "ReserveReceipt")
    grants = {g["decision_id"]: g["grant_id"] for g in res["record"]["grants"]}
    for a, q in plans.items():
        ewire(f"B:{a}", f"CommitDecision-{a}", {"op": "CommitDecision", "decision_id": a, "plan_hash": digest(q), "grant_id": grants[a], "writer_epoch": "1"}, "LocalCommitReceipt")
    q = plans["alpha"]
    ewire("E", "MakeDispatchable-alpha", {"op": "MakeDispatchable", "decision_id": "alpha", "plan_hash": digest(q), "writer_epoch": "1"}, "DispatchableReceipt")
    x_cfg, freeze = q["exact"], data["exact_release"]
    change = {
        "kind": "submit",
        "order": {
            "command_id": x_cfg["command_id"],
            "family_id": x_cfg["logical_order_family"],
            "chong_id": x_cfg["chong_id"],
            "revision": x_cfg["revision"],
            "side": x_cfg["side"],
            "quantity": q["quantity"],
            "kind": {"kind": "limit", "price": q["limit_price"]},
            "eligibility_ref": x_cfg["eligibility_ref"],
            "projection_manifest": x_cfg["projection_manifest"],
        },
    }
    certificate = {
        "rd11_policy": freeze["rd11_policy"],
        "responsibility_refs": [grants["alpha"]],
        "structure_dependencies": [q["s_ref"]["object_id"] + "@" + q["s_ref"]["object_hash"]],
        "market_dependencies": freeze["market_dependencies"],
        "rule_revision": freeze["rule_revision"],
        "conditions": freeze["conditions"],
    }
    rel = ewire(
        "E",
        "ReleaseExact-alpha",
        {
            "op": "ReleaseExact",
            "decision_id": "alpha",
            "command_id": "cmd-alpha",
            "plan_hash": digest(change),
            "certificate": certificate,
            "x_id": "X",
            "x_epoch": "1",
            "writer_epoch": "1",
        },
        "ReleasedExactReceipt",
    )
    exact = rel["record"]["command"]
    assert same(exact["model_ref"], freeze["model_coverage"]["model_ref"]), exact["model_ref"]

    # 4. 启动真实 X 进程（x-execution-profile/3）与受控 S，推进至 bar 3 产出 fill + fee 两件原件
    pp = write(
        "x-profile.json",
        {
            "profile_revision": "x-execution-profile/3",
            "mode": "simulation",
            "credential_scope": {"env": "UNUSED_SIMULATION_CREDENTIAL"},
            "history_simulation": {
                "model": model_config,
                "session_id": sid,
                "session_generation": gen,
                "x_id": "X",
                "source_namespace": src_x["source_namespace"],
                "source_epoch": src_x["source_epoch"],
                "socket": x_socket,
                "timeout_ms": 5000,
                "max_frame_bytes": 1048576,
                "conditions": freeze["conditions"],
                "e": {
                    "socket": nodes["E"]["socket"],
                    "authority_id": "E",
                    "authority_epoch": "1",
                    "schema_revision": "economic-session/1",
                    "reply_namespace": "economic-session/replies",
                    "producer_id": f"E:{sid}",
                },
                "s": {
                    "socket": str(run / "s.sock"),
                    "authority_id": "S",
                    "authority_epoch": "1",
                    "schema_revision": "s-authority-fixture/1",
                    "reply_namespace": "s-authority-fixture/replies",
                    "producer_id": "S:fixture",
                },
            },
        },
    )
    xp = command("serve-x", [xb, "serve", "--db", x_db_path, "--profile", pp, "--writer-epoch", "1"], expected=None)
    wait_ready(xp, x_socket, "serve-x")

    def sign_once(listener):
        with listener, listener.accept()[0] as sock:
            frame = decode_frame(sock.makefile("rb").readline(1048577))
            req_p = frame["payload"]
            assert req_p["op"] == "RequestConditionalExecution" and same(req_p["command"], exact)
            receipt = {k: v for k, v in req_p.items() if k != "op"}
            receipt.update(state="ExecuteCommitted", receipt_id=x_cfg["eligibility_ref"], commit_ns="2")
            resp = reply_envelope(
                frame,
                receipt,
                session_id=sid,
                session_generation=gen,
                namespace="s-authority-fixture/replies",
                producer_id="S:fixture",
                producer_epoch="1",
            )
            sock.sendall(canonical(resp) + b"\n")

    listener = socket.socket(socket.AF_UNIX)
    listener.bind(str(run / "s.sock"))
    listener.listen(1)
    signer = threading.Thread(target=sign_once, args=(listener,), daemon=True)
    signer.start()

    def bar(i, changes=()):
        return {
            "request_id": f"b{i}",
            "known_frontier_cut": f"frontier{i}",
            "bar": {"index": i, "open": 14, "low": 13, "high": 15, "close": 14},
            "capacity": {"kind": "none"},
            "close_changes": list(changes),
            "scenario_busts": [],
        }

    xwire("x-bar-0", "AdvanceBar", bar(0), "SimulationBatch")
    early = xwire("x-accept-early", "AcceptExact", exact, "Error")
    assert early["error"].startswith("InvalidDomain：X 接纳时钟早于 E 持久交付"), early
    xwire("x-bar-1", "AdvanceBar", bar(1), "SimulationBatch")
    acc = xwire("x-accept-bar2", "AcceptExact", exact, "ExactCommandState")
    assert acc["state"] == "Accepted" and acc["x_accept"]["commit_ns"] == "2"
    ord_in = change["order"]
    local_change = {
        **change,
        "order": {
            **ord_in,
            "revision": int(ord_in["revision"]),
            "quantity": int(ord_in["quantity"]),
            "kind": {"kind": "limit", "price": int(ord_in["kind"]["price"])},
        },
    }
    xwire("x-bar-2", "AdvanceBar", bar(2, [local_change]), "SimulationBatch")
    signer.join(5)
    b3 = xwire("x-bar-3", "AdvanceBar", bar(3), "SimulationBatch")
    assert [o["event"]["kind"] for o in b3["originals"]] == ["fill", "fee"]
    fill_doc, fee_doc = b3["originals"]

    # 5. X 来源送两件原件进 E.CaptureExternal（幂等重试核验）
    fill_cap = ewire(
        "E",
        "capture-sim-fill",
        {
            "op": "CaptureExternal",
            "raw_utf8": canonical(fill_doc).decode("utf-8"),
            "json_pointer": "/event",
            "token": "tok-sim-fill",
            "source_event_time": fill_doc["event"]["source"]["source_event_time"],
        },
        "Recorded",
        source=src_x,
    )
    assert same(
        ewire(
            "E",
            "capture-sim-fill-retry",
            {
                "op": "CaptureExternal",
                "raw_utf8": canonical(fill_doc).decode("utf-8"),
                "json_pointer": "/event",
                "token": "tok-sim-fill",
                "source_event_time": fill_doc["event"]["source"]["source_event_time"],
            },
            "Recorded",
            source=src_x,
        ),
        fill_cap,
    )
    fee_cap = ewire(
        "E",
        "capture-sim-fee",
        {
            "op": "CaptureExternal",
            "raw_utf8": canonical(fee_doc).decode("utf-8"),
            "json_pointer": "/event",
            "token": "tok-sim-fee",
            "source_event_time": fee_doc["event"]["source"]["source_event_time"],
        },
        "Recorded",
        source=src_x,
    )

    # 负控 A：Resolve 前 B:alpha.ApplyAllocation 被拒
    alpha_db, beta_db, e_db = Path(nodes["B:alpha"]["db"]), Path(nodes["B:beta"]["db"]), Path(nodes["E"]["db"])
    alpha_before = business_dump(alpha_db)
    err_early_apply = ewire(
        "B:alpha",
        "apply-fill-before-resolve",
        {"op": "ApplyAllocation", "fact_key": fill_cap["fact_key"], "allocation_id": "alloc-alpha", "expected_fact_hash": fill_cap["fact_hash"]},
        "Error",
    )
    assert err_early_apply["error"].startswith("AwaitingDependency"), err_early_apply
    assert same(business_dump(alpha_db), alpha_before)

    # 负控 B：fill 未 Resolve 前先 Resolve fee 被拒
    e_before = business_dump(e_db)
    err_early_fee_res = ewire(
        "E",
        "resolve-fee-before-fill",
        {
            "op": "ResolveEvidence",
            "evidence_id": "ev-fee-early",
            "covered": [{"fact_key": fee_cap["fact_key"], "fact_hash": fee_cap["fact_hash"], "token": fee_cap["token"]}],
            "frontier": {"source_namespace": "x-sim", "source_epoch": "epoch1", "cursor": "3"},
            "dependency_version": "tb1425-deps/1",
        },
        "Error",
        source=src_resolver,
    )
    assert err_early_fee_res["error"].startswith("AwaitingDependency"), err_early_fee_res
    assert same(business_dump(e_db), e_before)

    # 6. 具名工作方 resolver 调用 E.ResolveEvidence（先 fill 后 fee，同游标 3 不吞费）
    res_fill_payload = {
        "op": "ResolveEvidence",
        "evidence_id": "ev-sim-fill",
        "covered": [{"fact_key": fill_cap["fact_key"], "fact_hash": fill_cap["fact_hash"], "token": fill_cap["token"]}],
        "frontier": {"source_namespace": "x-sim", "source_epoch": "epoch1", "cursor": "3"},
        "dependency_version": "tb1425-deps/1",
    }
    res_fill = ewire("E", "resolve-sim-fill", res_fill_payload, "Resolved", source=src_resolver)
    assert same(ewire("E", "resolve-sim-fill-retry", res_fill_payload, "Resolved", source=src_resolver), res_fill)
    res_fee = ewire(
        "E",
        "resolve-sim-fee",
        {
            "op": "ResolveEvidence",
            "evidence_id": "ev-sim-fee",
            "covered": [{"fact_key": fee_cap["fact_key"], "fact_hash": fee_cap["fact_hash"], "token": fee_cap["token"]}],
            "frontier": {"source_namespace": "x-sim", "source_epoch": "epoch1", "cursor": "3"},
            "dependency_version": "tb1425-deps/1",
        },
        "Resolved",
        source=src_resolver,
    )

    e_view = ewire("E", "read-e-after-resolve", {"op": "ReadView", "cut": None, "as_known_ns": None}, "EconomicView")
    rows = e_view["image"]["fill_allocations"]
    assert len(rows) == 2 and not e_view["image"]["pending"]
    fill_aid = rows[0]["allocations"][0]["allocation_id"]
    fee_aid = rows[1]["allocations"][0]["allocation_id"]
    assert fill_aid.startswith("sim-command:") and fee_aid.startswith("sim-command-fee:")
    assert rows[0]["plan_hash"] != rows[0]["command_plan_hash"]
    assert sum(int(r["amount"]) for r in e_view["image"]["finance"]["responsibilities"]) == 90

    # 6b. 在 E Resolve 双件后（三域总快照 ~1.9MB < 4MiB），核验正式 HTTP 分页 CompleteVector + original(command)
    snap_resolved_ep1, cmd_before = query_http_snapshot(qc1, epochs1, "resolved-ep1")
    write("snapshot-resolved-ep1.json", snap_resolved_ep1)
    resolved_cuts = {d: v["cut"] for d, v in snap_resolved_ep1["domains"].items()}
    assert len(snap_resolved_ep1["domains"]["E"]["image"]["fill_allocations"]) == 2
    assert snap_resolved_ep1["domains"]["E"]["image"]["fill_allocations"][0]["source_kind"] == "history_sim_fill"
    assert snap_resolved_ep1["domains"]["E"]["image"]["fill_allocations"][1]["source_kind"] == "history_sim_fee"
    assert same(cmd_before["original"]["record"], rel["record"])

    # 负控 C/D/E：早 Apply fee / 错重 B:beta / 用 alloc-alpha 申请
    beta_before = business_dump(beta_db)
    assert ewire(
        "B:alpha",
        "apply-fee-before-fill",
        {"op": "ApplyAllocation", "fact_key": fee_cap["fact_key"], "allocation_id": fee_aid, "expected_fact_hash": fee_cap["fact_hash"]},
        "Error",
    )["error"].startswith("AwaitingDependency")
    assert ewire(
        "B:beta",
        "apply-fill-wrong-chong",
        {"op": "ApplyAllocation", "fact_key": fill_cap["fact_key"], "allocation_id": fill_aid, "expected_fact_hash": fill_cap["fact_hash"]},
        "Error",
    )["error"].startswith("IdentityConflict")
    assert ewire(
        "B:alpha",
        "apply-fill-bad-id",
        {"op": "ApplyAllocation", "fact_key": fill_cap["fact_key"], "allocation_id": "alloc-alpha", "expected_fact_hash": fill_cap["fact_hash"]},
        "Error",
    )["error"].startswith("IdentityConflict")
    assert same(business_dump(beta_db), beta_before)

    # 7. B:alpha 唯一应用 fill（重试幂等）
    fill_apply_payload = {
        "op": "ApplyAllocation",
        "fact_key": fill_cap["fact_key"],
        "allocation_id": fill_aid,
        "expected_fact_hash": fill_cap["fact_hash"],
    }
    fill_app = ewire("B:alpha", "apply-sim-fill", fill_apply_payload, "Applied")
    assert same(ewire("B:alpha", "apply-sim-fill-retry", fill_apply_payload, "Applied"), fill_app)
    mid_view = ewire("B:alpha", "read-alpha-after-fill", {"op": "ReadView", "cut": None, "as_known_ns": None}, "EconomicView")
    assert mid_view["image"]["book"]["actual_quantity"] == "6"
    assert mid_view["image"]["book"]["cost_basis"]["K"] == "80028"
    assert mid_view["image"]["book"]["cost_totals"]["fee_only"] == "0"

    # 8. B:alpha 唯一应用独立因果 fee（重试幂等）
    fee_apply_payload = {
        "op": "ApplyAllocation",
        "fact_key": fee_cap["fact_key"],
        "allocation_id": fee_aid,
        "expected_fact_hash": fee_cap["fact_hash"],
    }
    fee_app = ewire("B:alpha", "apply-sim-fee", fee_apply_payload, "Applied")
    assert same(ewire("B:alpha", "apply-sim-fee-retry", fee_apply_payload, "Applied"), fee_app)

    # 核验 B:alpha 最终账面、B:beta 不动、E 总责任维持 90
    views_before = {
        d: ewire(d, f"read-final-ep1-{d.replace(':', '-')}", {"op": "ReadView", "cut": None, "as_known_ns": None}, "EconomicView")
        for d in nodes
    }
    bk = views_before["B:alpha"]["image"]["book"]
    assert bk["actual_quantity"] == "6"
    assert bk["cost_totals"]["acquisition_cash"] == "80028"
    assert bk["cost_totals"]["commission"] == "0"
    assert bk["cost_totals"]["fee_only"] == "1"
    assert bk["cost_basis"]["K"] == "80029"
    assert bk["cost_remaining"] == {"status": "Known", "value": "80029"}
    assert bk["principal"]["status"] == "NotEvaluable"
    assert bk["phase"]["growth_enabled"]["status"] == "NotEvaluable"
    assert same(business_dump(beta_db), beta_before)
    assert sum(int(r["amount"]) for r in views_before["E"]["image"]["finance"]["responsibilities"]) == 90

    # 保存恢复前的 E/B/X 全表快照供 --twice 逐字节对拍
    dbs = {d: Path(n["db"]) for d, n in nodes.items()}
    dbs["X"] = x_db_path
    write("business.json", {d: business_dump(p) for d, p in dbs.items()})

    # 9. 停服冷恢复（writer_epoch 1 → 2）并对拍三域最终 ReadView 与 resolved_cuts HTTP 分页快照逐值一致
    for d in reversed(started_domains):
        launcher("stop", d, lc1, tag=f"stop-ep1-{d.replace(':', '-')}")
    started_domains.clear()
    for d in nodes:
        launcher("recover", d, lc2, tag=f"recover-ep2-{d.replace(':', '-')}")
        launcher("start", d, lc2, tag=f"start-ep2-{d.replace(':', '-')}")
        started_domains.append(d)

    for d in nodes:
        v_after = ewire(
            d,
            f"read-final-ep2-{d.replace(':', '-')}",
            {"op": "ReadView", "cut": None, "as_known_ns": None},
            "EconomicView",
            producer_epoch="2",
        )
        assert same(views_before[d]["image"], v_after["image"]), (d, "冷恢复业务镜像漂移")
        assert same(views_before[d]["cut"], v_after["cut"]), (d, "冷恢复 cut 漂移")

    snap_resolved_ep2, cmd_after = query_http_snapshot(qc2, epochs2, "resolved-ep2", cuts=resolved_cuts)
    write("snapshot-resolved-ep2.json", snap_resolved_ep2)
    for d in nodes:
        assert same(snap_resolved_ep1["domains"][d]["image"], snap_resolved_ep2["domains"][d]["image"]), (d, "HTTP 冷恢复镜像漂移")
        assert same(snap_resolved_ep1["domains"][d]["cut"], snap_resolved_ep2["domains"][d]["cut"]), (d, "HTTP 冷恢复 cut 漂移")
    assert same(cmd_before["original"], cmd_after["original"])

    # 10. 同一最终 Applied cut（cut 6）与中间态 fill cut（cut 5）实测公开端与既有浏览器首拒（不抬上限、不丢字段、不用 resolved_cuts 顶替验收）
    fill_cuts = {**resolved_cuts, "B:alpha": mid_view["cut"]}
    final_cuts = {d: views_before[d]["cut"] for d in nodes}
    gap_evidence = probe_post_applied_public_query_gap(qc2, epochs2, fill_cuts, final_cuts, resolved_cuts, "ep2")
    write("public-query-gap-evidence.json", gap_evidence)
    assert gap_evidence["owner_b_alpha_cut6_paged_open"]["code"] == "QueryBudgetExceeded", gap_evidence
    assert gap_evidence["owner_b_alpha_cut6_paged_open"]["detail"].startswith("Incomplete：完整持久图像超出读取逻辑字节帽"), gap_evidence
    assert gap_evidence["http_q_read_open_cut5"]["payload"].get("code") == "QueryBudgetExceeded" or gap_evidence["http_q_read_open_cut5"]["payload"].get("error") == "QueryBudgetExceeded", gap_evidence
    assert gap_evidence["http_q_read_cut6_completeness"] == "PartialVector", gap_evidence
    assert gap_evidence["http_q_read_cut6_b_alpha"]["status"] == "Unavailable", gap_evidence
    assert gap_evidence["http_q_single_frame_snapshot_cut6"]["http_status"] in (400, 503), gap_evidence
    assert "QueryBudgetExceeded" in canonical(gap_evidence["http_q_single_frame_snapshot_cut6"]).decode("utf-8"), gap_evidence
    assert gap_evidence["http_q_original_allocation_cut6"]["http_status"] == 400, gap_evidence
    assert gap_evidence["http_q_original_decision_alpha_cut6"]["http_status"] == 400, gap_evidence
    if "final_cut6" in gap_evidence["browser_tb03a_client"]:
        assert gap_evidence["browser_tb03a_client"]["final_cut6"]["ok"] is False, gap_evidence
        assert gap_evidence["browser_tb03a_client"]["resolved_cuts"]["ok"] is False, gap_evidence

    write(
        "summary.json",
        {
            "finance_revision": "tb03b-finance/6",
            "x_profile_revision": "x-execution-profile/3",
            "model_content_hash": model_hash,
            "grant_alpha": grants["alpha"],
            "fill_fact_key": fill_cap["fact_key"],
            "fee_fact_key": fee_cap["fact_key"],
            "fill_allocation_id": fill_aid,
            "fee_allocation_id": fee_aid,
            "alpha_quantity_after": bk["actual_quantity"],
            "alpha_K_after": bk["cost_basis"]["K"],
            "alpha_fee_only_after": bk["cost_totals"]["fee_only"],
            "e_liability_retained": 90,
            "recovered_epoch": "2",
            "e_cut10_image_bytes": len(canonical(views_before["E"]["image"])),
            "b_beta_cut4_image_bytes": len(canonical(views_before["B:beta"]["image"])),
            "b_alpha_cut5_image_bytes": len(canonical(mid_view["image"])),
            "b_alpha_cut6_image_bytes": len(canonical(views_before["B:alpha"]["image"])),
            "http_read_cache_limit_bytes": 4 * 1048576,
            "public_query_scope": "legacy_full_snapshot_and_legacy_client",
            "public_query_final_cut_status": "BLOCKED_BY_4MIB_AND_BROWSER_TB03C_CONTRACT",
        },
    )
    print(
        "CORE-PASS (LEGACY-FULL-SNAPSHOT-LIMIT): #1425 FIN/6+X/3 单一明确原责任域 E/B/X 实账与冷恢复通过 "
        f"(fill={fill_aid[:24]}..., fee={fee_aid[:28]}..., B:alpha qty=4->6 K=80000->80029, "
        "B:beta 不动, E 责任维持 90, 冷恢复 epoch=2 三域逐值一致; "
        "旧全图接口与旧客户端在 cut 6 的首拒见 public-query-gap-evidence.json；固定切面投影另验)"
    )
finally:
    for d in reversed(started_domains):
        try:
            subprocess.run(
                [sys.executable, str(src / "s_session/economic_service_control.py"), "stop", "--config", str(lc2), "--domain", d],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
            )
        except Exception:
            pass
    for label, p in reversed(processes):
        if p.poll() is None:
            p.terminate()
        try:
            p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait()
        ctl_trace.write(json.dumps({"step": label + "-exit", "pid": p.pid, "exit": p.returncode}) + "\n")
