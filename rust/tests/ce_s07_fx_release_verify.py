#!/usr/bin/env python3
"""#1407 C3 CE-S07 integrated formal Linux verification & #1416 handoff generator.

Drives real compiled Linux binaries (`production_session`, `s_structure_session`,
`e_economic_session`, `b_chong_session`, `x_execution_session`) over Unix sockets
in isolated temp directories:
  - Arm 1 (`ce_s07_main_lifecycle`):
      tb03b-finance/6 + fx-valuation/2 + x-execution-profile/3 + logical-bar/1 + s-session/3.
      Verifies E cut 10 = 90/100 (r1), 8 pre-release tamper/drop/placeholder negative controls,
      cut 11 alpha release + real X AcceptExact (no fake S stub), cut 12 r2 = 110/100 +
      original receipt priority (same/new message_id) + beta/gamma blocked, cut 15 r3 + r2
      retirement = 90/100, cut 16 beta release + real X AcceptExact, cut 17 gamma reserve = 95/100,
      exact S3 SQLite raw_history market mapping + relevant/unrelated revision matching,
      real #1416 S3 RequestConditionalExecution gap probe (NO forged S receipt),
      and epoch-2 cold recovery + audits.
  - Arm 2 (`unrelated_revision_healthy_chong`):
      Proves unrelated market revision (OTHER-FX/TEST-CASH) in S3 does NOT block an
      unrelated healthy empty-FX-boundary chong release + X AcceptExact, while unattributed
      direct E capture conservatively remains `account:*` and refuses silent clearance.
  - Arm 3 (`pure_non_fx_legacy_v6`):
      Proves pure non-FX tb03b-finance/6 + x-execution-profile/3 preserves exact legacy
      static condition equality (no `fx_valuation` in ReadView) and verifies config-level
      refusal of FX placeholders and non-FX marker leakage via `e_economic_session init`.
  - Arm 4: static FIN/5+FX first imports, old receipt priority, and cold recovery.
  - Arm 5: single/batched commands at the same r2 overcap cut and original alpha receipt.
  - Arm 6 (with --parent-bin): first imports on a non-empty FIN/6+FX/1 parent DB,
      cold replay of the parent release, and exact parent/candidate reply comparisons.
"""
from __future__ import annotations

import argparse
import copy
import errno
import hashlib
import json
import os
import socket
import sqlite3
import subprocess
import sys
import time
from contextlib import closing
from pathlib import Path

from history_fixture_model import model as base_sim_model

SRC = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SRC / "s_session"))
sys.path.insert(0, str(SRC / "s_session/tests"))
from r4_anchor_fixture import TestAnchor  # noqa: E402
from s_socket_client import canonical, decode_frame, digest, validate_reply  # noqa: E402

FX_MARKER = "fx-valuation/2:release-bound"
FX_PROOF_PREFIX = "fx-valuation/2:"
FIN_NS = "testonly.ce-s07.fin"
FIN_EPOCH = "1"
MARKET_NS = "testonly.ce-s07.fx"
MARKET_EPOCH = "1"
X_NS = "testonly.ce-s07.x"
X_EPOCH = "1"

EXPECTED_FIXTURE_SHA256 = {
    "fx-obligations.json": "5dc071e5708e39cfbae98d5956f7f1d9e63d641dd1e59afd301492d93030afa1",
    "fx-r1.json": "2821d4d4e3768ed9c2740f3879843804d6ba65c461b2ff8dfe84be0a14592ce3",
    "fx-r2.json": "33a459e011b2bb6dfbabe46bac651468be6845cb9b3e51d64f6475d5f44aa66a",
    "fx-r3.json": "0c95b37313dab37ec158f20a999cbfde45b92cd5986677467702f10efe8c7736",
}
FORBIDDEN_PLACEHOLDERS = (
    "TestOnly-market/",
    "controlled-dependency",
    "controlled-invalidation",
    "controlled-evidence",
    "controlled-coverage",
    "fx-valuation/1:release-bound",
    FX_MARKER,
)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_digest(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def write_canon(path: Path, obj) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical(obj))
    return path


def write_pretty(path: Path, obj) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
    return path


def run_cli(args: list[str], *, env: dict[str, str] | None = None, timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, env=env, timeout=timeout)


def wait_ready(proc: subprocess.Popen, address: str, label: str, stderr_path: Path) -> None:
    limit = time.monotonic() + 20
    while time.monotonic() < limit:
        if proc.poll() is not None:
            raise AssertionError(
                f"{label} exited early rc={proc.returncode}\nstderr:\n{stderr_path.read_text(errors='replace')}"
            )
        with socket.socket(socket.AF_UNIX) as s:
            s.settimeout(1.0)
            try:
                s.connect(address)
            except (FileNotFoundError, ConnectionRefusedError):
                time.sleep(0.03)
                continue
            try:
                s.shutdown(socket.SHUT_WR)
            except OSError as exc:
                if exc.errno != errno.ENOTCONN:
                    raise
            raw = s.makefile("rb").readline()
            if raw:
                return
    raise TimeoutError(f"timeout waiting for {label} socket {address}")


def send_frame(sock_path: str, req: dict, *, wire_log: list[dict] | None = None, label: str = "") -> tuple[bytes, bytes, dict]:
    raw_req = canonical(req) + b"\n"
    with socket.socket(socket.AF_UNIX) as s:
        s.settimeout(60.0)
        s.connect(sock_path)
        s.sendall(raw_req)
        s.shutdown(socket.SHUT_WR)
        raw_rep = s.makefile("rb").readline(16777217)
    assert raw_rep.endswith(b"\n") and len(raw_rep) <= 16777216, (label, raw_rep[:200])
    rep = decode_frame(raw_rep)
    if wire_log is not None:
        wire_log.append({"label": label, "socket": sock_path, "request": req, "reply": rep})
    return raw_req, raw_rep, rep


def make_fx_conditions_template() -> list[dict]:
    return [
        {
            "condition_id": "released-exact/1",
            "authority_revision": "released-exact/1",
            "dependency_set": [FX_MARKER],
            "invalidation_sources": [FX_MARKER],
            "required_check_stages": ["E.ReleaseExact"],
            "evidence_refs": [FX_MARKER],
            "coverage_proof": FX_MARKER,
            "validator_capability": "released-exact/1",
            "failure_result": "Denied",
        },
        {
            "condition_id": "execute-committed/1",
            "authority_revision": "execute-committed/1",
            "dependency_set": [FX_MARKER],
            "invalidation_sources": [FX_MARKER],
            "required_check_stages": ["S.RequestConditionalExecution"],
            "evidence_refs": [FX_MARKER],
            "coverage_proof": FX_MARKER,
            "validator_capability": "execute-committed/1",
            "failure_result": "Denied",
        },
        {
            "condition_id": "simulation-local-transaction/1",
            "authority_revision": "simulation-local-transaction/1",
            "dependency_set": [FX_MARKER],
            "invalidation_sources": [FX_MARKER],
            "required_check_stages": ["X.OwnAttemptAndCall"],
            "evidence_refs": [FX_MARKER],
            "coverage_proof": FX_MARKER,
            "validator_capability": "simulation-local-transaction/1",
            "failure_result": "Denied",
        },
        {
            "condition_id": "model_coverage",
            "authority_revision": "model-coverage/1",
            "dependency_set": [FX_MARKER],
            "invalidation_sources": [FX_MARKER],
            "required_check_stages": ["E.ReleaseExact"],
            "evidence_refs": [FX_MARKER],
            "coverage_proof": FX_MARKER,
            "validator_capability": "model-coverage/1",
            "failure_result": "Denied",
        },
    ]


def make_legacy_conditions() -> list[dict]:
    return [
        {
            "condition_id": "released-exact/1",
            "authority_revision": "released-exact/1",
            "dependency_set": ["controlled-dependency"],
            "invalidation_sources": ["controlled-invalidation"],
            "required_check_stages": ["E.ReleaseExact"],
            "evidence_refs": ["controlled-evidence"],
            "coverage_proof": "controlled-coverage",
            "validator_capability": "released-exact/1",
            "failure_result": "Denied",
        },
        {
            "condition_id": "execute-committed/1",
            "authority_revision": "execute-committed/1",
            "dependency_set": ["controlled-dependency"],
            "invalidation_sources": ["controlled-invalidation"],
            "required_check_stages": ["S.RequestConditionalExecution"],
            "evidence_refs": ["controlled-evidence"],
            "coverage_proof": "controlled-coverage",
            "validator_capability": "execute-committed/1",
            "failure_result": "Denied",
        },
        {
            "condition_id": "simulation-local-transaction/1",
            "authority_revision": "simulation-local-transaction/1",
            "dependency_set": ["controlled-dependency"],
            "invalidation_sources": ["controlled-invalidation"],
            "required_check_stages": ["X.OwnAttemptAndCall"],
            "evidence_refs": ["controlled-evidence"],
            "coverage_proof": "controlled-coverage",
            "validator_capability": "simulation-local-transaction/1",
            "failure_result": "Denied",
        },
        {
            "condition_id": "model_coverage",
            "authority_revision": "model-coverage/1",
            "dependency_set": ["controlled-dependency"],
            "invalidation_sources": ["controlled-invalidation"],
            "required_check_stages": ["E.ReleaseExact"],
            "evidence_refs": ["controlled-evidence"],
            "coverage_proof": "controlled-coverage",
            "validator_capability": "model-coverage/1",
            "failure_result": "Denied",
        },
    ]


def change_for_plan(plan: dict) -> dict:
    x = plan["exact"]
    return {
        "kind": "submit",
        "order": {
            "command_id": x["command_id"],
            "family_id": x["logical_order_family"],
            "chong_id": x["chong_id"],
            "revision": x["revision"],
            "side": x["side"],
            "quantity": plan["quantity"],
            "kind": {"kind": "limit", "price": plan["limit_price"]},
            "eligibility_ref": x["eligibility_ref"],
            "projection_manifest": x["projection_manifest"],
        },
    }


def build_fx_certificate_from_query(
    session_id: str,
    session_generation: str,
    fin_data: dict,
    plan: dict,
    grant_id: str,
    query_reply: dict,
) -> dict:
    """Derives the exact certificate that E requires at this cut from real QueryFxValuation."""
    fx = query_reply["fx_valuation"]
    cut = query_reply["cut"]
    prev_seq = cut["commit_seq"]
    prev_root = cut["root_hash"]
    cap = fx["cap_policy"]
    boundary = fx["boundary"]
    summary = fx["summary"]
    owner = plan["owner"]

    grant_row = next(
        r for r in fx["cash_responsibilities"] if r["responsibility_id"] == grant_id and r["owner"] == owner
    )
    grant_amount = grant_row["amount"]

    other_resps = set()
    for r in fx["cash_responsibilities"]:
        if r["responsibility_id"] != grant_id:
            other_resps.add(r["responsibility_id"])
    applied_fact_keys = set()
    foreign_obs = []
    for ob in fx["foreign_responsibilities"]:
        if ob["responsibility_id"] != grant_id:
            other_resps.add(ob["responsibility_id"])
        assert ob["valuation_status"] == "Evaluated", ob
        applied_fact_keys.add(ob["applied_fact_key"])
        foreign_obs.append(ob)
    foreign_obs.sort(key=lambda o: o["responsibility_id"])
    responsibility_refs = [grant_id] + sorted(other_resps)

    active_quotes = []
    active_chains = set()
    for rev in fx["revisions"]:
        if rev["fact_key"] in applied_fact_keys:
            chain_id = f"{rev['source_namespace']}|{rev['source_epoch']}|{rev['instrument']}|{rev['event_id']}"
            active_chains.add(chain_id)
            active_quotes.append((chain_id, rev))
    active_quotes.sort(key=lambda pair: (pair[0], int(pair[1]["revision"])))

    retired_quotes = []
    for rev in fx["revisions"]:
        if rev["coverage_status"] == "RetiredBySupersession":
            chain_id = f"{rev['source_namespace']}|{rev['source_epoch']}|{rev['instrument']}|{rev['event_id']}"
            if chain_id in active_chains:
                retired_quotes.append((chain_id, rev))
    retired_quotes.sort(key=lambda pair: (pair[0], int(pair[1]["revision"])))

    s = fin_data["exact_release"]
    x = plan["exact"]
    m = s["model_coverage"]
    mref = m["model_ref"]
    structure_dep = f"{plan['s_ref']['object_id']}@{plan['s_ref']['object_hash']}"
    e_cut_ref = f"e-cut:E:{prev_seq}:{prev_root}"
    policy_ref = (
        f"cap-policy:{cap['policy_id']}@v{cap['policy_version']}:"
        f"cap={cap['cap']}:{cap['currency']}:valid_through={cap['valid_through_ns']}"
    )
    boundary_ref = (
        f"fx-boundary:{boundary['source_id']}|{boundary['source_epoch']}:"
        f"input_sha256={boundary['obligation_input_sha256']}"
    )
    empty_boundary_dep = (
        f"fx-boundary-empty:{boundary['source_id']}|{boundary['source_epoch']}:"
        f"input_sha256={boundary['obligation_input_sha256']}"
    )
    exposure_ref = (
        f"e-exposure:cash={summary['cash_subtotal']};foreign={summary['foreign_evaluated_subtotal']};"
        f"total={summary['evaluated_total']};cap={cap['cap']};currency={cap['currency']}"
    )
    model_ref_str = f"{mref['model_id']}@{mref['revision']}#{mref['content_hash']}"
    domain_id = m["domain_id"]
    x_id = s["x_target"]["x_id"]
    x_epoch = s["x_target"]["x_epoch"]
    allocation_policy_id = fin_data["policy"]["allocation_policy_id"]

    quote_deps = []
    quote_invs = []
    quote_covs = []
    quote_raws = []
    for chain_id, rev in active_quotes:
        sup = rev["supersedes_revision"] if rev["supersedes_revision"] is not None else "none"
        quote_deps.append(
            f"fx-quote:{chain_id}@rev={rev['revision']};coord={rev['source_coord']};"
            f"supersedes={sup};rate={rev['price_numerator']}/{rev['price_denominator']};"
            f"raw_sha256={rev['raw_sha256']};fact_key={rev['fact_key']}"
        )
        quote_invs.append(f"market-supersession:{chain_id}:after_rev={rev['revision']}")
        quote_covs.append(
            f"e-quote-coverage:{chain_id}@rev={rev['revision']}:"
            f"evidence_id={rev['evidence_id']}:evidence_hash={rev['evidence_hash']}"
        )
        quote_raws.append(
            f"market-raw:{chain_id}@rev={rev['revision']}:raw_sha256={rev['raw_sha256']}"
        )

    market_dependencies = quote_deps if quote_deps else [empty_boundary_dep]
    retired_refs = [
        f"fx-retired:{chain_id}@rev={rev['revision']}:retired_by_rev={rev['retired_by_revision']}:"
        f"evidence_id={rev['evidence_id']}:evidence_hash={rev['evidence_hash']}"
        for chain_id, rev in retired_quotes
    ]
    ob_deps = [
        f"foreign-responsibility:{ob['responsibility_id']}:owner={ob['owner']}:"
        f"qty={ob['quantity']}:{ob['unit']}:instrument={ob['valuation_instrument']}:"
        f"source={ob['quote_source']['source_namespace']}|{ob['quote_source']['source_epoch']}:"
        f"input_sha256={ob['input_sha256']}"
        for ob in foreign_obs
    ]
    chain_proof_summary = (
        ",".join(f"{chain_id}@rev={rev['revision']}" for chain_id, rev in active_quotes)
        if active_quotes
        else "empty-boundary"
    )

    built_conditions = []
    for tpl in s["conditions"]:
        vc = tpl["validator_capability"]
        if vc == "released-exact/1":
            deps = [
                f"grant:{grant_id}:owner={owner}:amount={grant_amount}:{cap['currency']}",
                policy_ref,
                boundary_ref,
            ] + ob_deps + market_dependencies
            invs = [
                f"e-pending:E:{cap['policy_id']}:{cap['currency']}",
                f"cap-policy-change:{cap['policy_id']}@v{cap['policy_version']}",
                f"fx-boundary-change:{boundary['source_id']}|{boundary['source_epoch']}:{boundary['obligation_input_sha256']}",
            ] + quote_invs
            evs = [e_cut_ref, exposure_ref]
            if quote_covs:
                evs += quote_covs
            else:
                evs.append(
                    f"e-empty-fx-boundary:{boundary['source_id']}|{boundary['source_epoch']}:{boundary['obligation_input_sha256']}"
                )
            evs += retired_refs
            proof = (
                f"{FX_PROOF_PREFIX}e-release-cut=E:{prev_seq}:{prev_root};"
                f"cap={cap['policy_id']}@v{cap['policy_version']}:{summary['evaluated_total']}/{cap['cap']};"
                f"chains={chain_proof_summary}"
            )
        elif vc == "execute-committed/1":
            deps = [f"structure-object:{structure_dep}"] + market_dependencies
            invs = [f"structure-withdrawal:{structure_dep}"] + (
                quote_invs
                if quote_invs
                else [
                    f"fx-boundary-change:{boundary['source_id']}|{boundary['source_epoch']}:{boundary['obligation_input_sha256']}"
                ]
            )
            evs = [e_cut_ref, f"structure-ref:{structure_dep}"] + (
                quote_raws + quote_covs if quote_raws else [boundary_ref]
            )
            proof = (
                f"{FX_PROOF_PREFIX}s-market-closure:e-cut=E:{prev_seq}:{prev_root};"
                f"structure={structure_dep};chains={chain_proof_summary}"
            )
        elif vc == "simulation-local-transaction/1":
            deps = [
                f"x-target:{x_id}@epoch={x_epoch}",
                f"session:{session_id}@gen={session_generation}",
                f"command:{x['command_id']}:alloc={x['allocation_id']}:first_qty={x['first_quantity']}",
                f"model-ref:{model_ref_str}",
            ]
            invs = [
                f"x-epoch-change:{x_id}:after={x_epoch}",
                f"command-identity:{x['command_id']}:alloc={x['allocation_id']}",
            ]
            evs = [
                e_cut_ref,
                f"projection-manifest:{x['projection_manifest']}",
                f"eligibility-ref:{x['eligibility_ref']}",
            ]
            proof = f"{FX_PROOF_PREFIX}x-local-tx:{x_id}@{x_epoch}:e-cut=E:{prev_seq}:{prev_root}"
        elif vc == "model-coverage/1":
            deps = [
                f"model-ref:{model_ref_str}",
                f"domain-id:{domain_id}",
                f"order-domain:limit:{x['concurrency']}:{allocation_policy_id}",
            ]
            invs = [
                f"model-ref-change:{model_ref_str}",
                f"domain-id-change:{domain_id}",
            ]
            evs = [e_cut_ref, f"model-ref:{model_ref_str}"]
            proof = f"{FX_PROOF_PREFIX}model-coverage:{domain_id}:{model_ref_str}:e-cut=E:{prev_seq}:{prev_root}"
        else:
            raise AssertionError(f"unexpected capability {vc}")

        built_conditions.append(
            {
                "condition_id": tpl["condition_id"],
                "authority_revision": tpl["authority_revision"],
                "dependency_set": deps,
                "invalidation_sources": invs,
                "required_check_stages": tpl["required_check_stages"],
                "evidence_refs": evs,
                "coverage_proof": proof,
                "validator_capability": vc,
                "failure_result": tpl["failure_result"],
            }
        )

    return {
        "rd11_policy": s["rd11_policy"],
        "responsibility_refs": responsibility_refs,
        "structure_dependencies": [structure_dep],
        "market_dependencies": market_dependencies,
        "rule_revision": s["rule_revision"],
        "conditions": built_conditions,
    }


def assert_no_fx_placeholders(obj, path: str = "root") -> None:
    if isinstance(obj, str):
        for pat in FORBIDDEN_PLACEHOLDERS:
            assert pat not in obj, f"forbidden placeholder {pat!r} found at {path}: {obj!r}"
        assert obj != "latest" and ":latest" not in obj, f"latest found at {path}: {obj!r}"
        assert (
            obj != "admissible" and not obj.startswith("admissible:") and not obj.startswith("admissible=")
        ), f"admissible bool token found at {path}: {obj!r}"
    elif isinstance(obj, list):
        for idx, item in enumerate(obj):
            assert_no_fx_placeholders(item, f"{path}[{idx}]")
    elif isinstance(obj, dict):
        for k, v in obj.items():
            assert_no_fx_placeholders(v, f"{path}.{k}")


def make_opening_doc(chong_name: str, symbol: str, op_level: str, fixed: str, qty: str) -> dict:
    return {
        "format": "neutral TestOnly economic raw originals; not production transport wire",
        "units": {
            "quantity": {"unit": "TEST-UNIT", "quantum": "1"},
            "money": {"unit": "TEST-CASH", "currency": "TEST-CASH", "quantum": "1"},
            "numeric_encoding": "exact_decimal_integer_text",
        },
        "events": [
            {
                "event": "known-opening",
                "source": {
                    "source_namespace": FIN_NS,
                    "source_epoch": FIN_EPOCH,
                    "source_cursor": "1",
                    "external_fact_id": f"opening-{chong_name}",
                    "received_time": "source-received",
                    "claimed_origin": "TestOnly source",
                },
                "allocation_id": f"allocation-{chong_name}",
                "family_id": "family-one",
                "book_identity": {
                    "chong_id": chong_name,
                    "symbol": symbol,
                    "op_level": op_level,
                    "fixed_q": fixed,
                    "side": "long",
                },
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
                "stable_point": {"profile": "TestOnly", "seq": "1", "source_ref": "sp"},
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


def book_fact_key(ev: dict) -> str:
    s = ev["source"]
    return digest([s["source_namespace"], s["source_epoch"], s["external_fact_id"]])


def build_session_artifacts(
    run_dir: Path,
    *,
    session_id: str,
    chongs: list[str],
    x_model: dict,
    fx_obligations_bytes: bytes | None,
    clock_messages: dict[str, str],
    recover_bars: list[str],
    s_clock_events: dict[str, dict],
    s_socket_for_x: str,
    baseline_amount: str = "0",
    cap_amount: str = "100",
    use_fx_marker_in_input: bool | None = None,
    finance_schema: str = "tb03b-finance/6",
    fx_schema: str = "fx-valuation/2",
    authorize_x_query: bool = True,
    plan_overrides: dict[str, dict] | None = None,
    slot_main_members: list[str] | None = None,
) -> dict:
    """Writes all files needed by `production_session` and returns paths + data."""
    run_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    sid = session_id
    gen = "1"
    fx_enabled = fx_obligations_bytes is not None
    use_fx_marker = (fx_enabled and fx_schema == "fx-valuation/2") if use_fx_marker_in_input is None else use_fx_marker_in_input
    symbol = x_model["symbol"]

    src_fin = {
        "source_namespace": FIN_NS,
        "source_epoch": FIN_EPOCH,
        "producer_id": "fin-coord",
        "producer_epoch": "1",
    }
    src_market = {
        "source_namespace": MARKET_NS,
        "source_epoch": MARKET_EPOCH,
        "producer_id": "ce-s07-testonly",
        "producer_epoch": "1",
    }
    src_x = {
        "source_namespace": X_NS,
        "source_epoch": X_EPOCH,
        "producer_id": "X",
        "producer_epoch": "1",
    }

    # Structure basis stub for E/B financial checks (separate from live S3)
    s_obj = {
        "object_id": "unit-S-object",
        "kind": "UnitStructuralTrustRoot",
        "branch": "RISING",
    }
    s_basis_path = write_canon(
        run_dir / "s-basis.json",
        {
            "kind": "FinancialBasis",
            "session_id": sid,
            "session_generation": gen,
            "writer_epoch": "1",
            "pending_revision": False,
            "commit_ns": "1",
            "snapshot": {"profile_id": "unit", "objects": [s_obj]},
        },
    )
    stub_path = run_dir / "s-stub.sh"
    assert "'" not in str(s_basis_path)
    stub_body = f"#!/bin/sh\nexec /bin/cat '{s_basis_path}'\n"
    stub_path.write_text(stub_body, encoding="utf-8")
    stub_path.chmod(0o700)
    stub_sha = sha256_bytes(stub_body.encode("utf-8"))
    s_ref = {
        "object_id": "unit-S-object",
        "object_hash": digest(s_obj),
        "profile_id": "unit",
    }

    # Matches fx_valuation_tests.rs / AC2 R3 exactly:
    # alpha=30 (2*14+2), beta=40 (3*12+4), gamma=5 (1*5+0)
    all_specs = {
        "alpha": ("2", "12", "4", "40", "2", "14", "2", "slot-main"),
        "beta": ("3", "20", "15", "50", "3", "12", "4", "slot-main"),
        "gamma": ("4", "10", "2", "20", "1", "5", "0", "slot-gamma"),
    }

    openers: dict[str, str] = {}
    voice_bindings: dict[str, dict] = {}
    authorities: list[dict] = []
    rights: list[dict] = []
    plans: list[dict] = []
    routes: list[dict] = []
    covered: list[dict] = []

    for cname in chongs:
        op_level, fixed, qty, cash, new_qty, price, fee, slot_id = all_specs[cname]
        db_path = run_dir / f"b-{cname}.db"
        sock_path = run_dir / f"b-{cname}.sock"
        doc = make_opening_doc(cname, symbol, op_level, fixed, qty)
        raw_bytes = canonical(doc)
        raw_str = raw_bytes.decode("utf-8")
        raw_hash = sha256_bytes(raw_bytes)
        openers[cname] = raw_str
        ev_ref = doc["events"][0]
        fk = book_fact_key(ev_ref)
        fh = digest(
            {
                "raw_sha256": raw_hash,
                "json_pointer": "/events/0",
                "event": ev_ref,
                "units": doc["units"],
            }
        )
        covered.append({"fact_key": fk, "fact_hash": fh, "token": f"tok-opening-{cname}"})

        def ref_obj(oid: str, aid: str = cname) -> dict:
            return {
                "authority_id": aid,
                "object_id": oid,
                "revision": "0",
                "content_hash": digest(oid),
            }

        vp = {
            "op": "BindVoice",
            "binding_id": f"voice-{cname}",
            "evidence_id": cname,
            "carrier_ref": ref_obj("unit-carrier"),
            "gamma_ref": ref_obj("unit-gamma"),
            "parent_voice_id": None,
            "sigma": "Long",
            "n": "0",
            "opening_basis": {
                "fact_key": fk,
                "expected_fact_hash": fh,
                "allocation_id": ev_ref["allocation_id"],
            },
        }
        voice_bindings[cname] = vp

        binding = {
            "evidence_id": cname,
            "instrument": symbol,
            "chong_id": cname,
            "operation_level": op_level,
            "carrier_ref": vp["carrier_ref"],
            "gamma_ref": vp["gamma_ref"],
            "sigma": "Long",
            "n": "0",
            "parent_voice_id": None,
            "structure_view": {
                "profile_id": "unit",
                "execution_level": op_level,
                "confirmation_level": str(int(op_level) + 1),
                "nest_depth": "1",
            },
            "opening_source": {
                "fact_key": fk,
                "fact_hash": fh,
                "allocation_id": ev_ref["allocation_id"],
                "raw_sha256": raw_hash,
                "json_pointer": "/events/0",
                "quantity": qty,
                "units": doc["units"],
            },
        }
        artifacts = []
        for art in [
            "input",
            "controlled_gammas",
            "carrier_objects",
            "instrument_declaration",
            "opening_raw",
        ]:
            val = doc if art == "opening_raw" else {"scope": "unit trust root only", "name": art}
            ap = write_canon(run_dir / f"{cname}-{art}.json", val)
            artifacts.append(
                {
                    "name": art,
                    "path": str(ap),
                    "sha256": file_digest(ap),
                    "bytes": str(ap.stat().st_size),
                }
            )
        bundle = {
            "schema": "voice-binding-authority/1",
            "authority_id": cname,
            "source": {
                "instrument": symbol,
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
            "bindings": [binding],
        }
        bp = write_canon(run_dir / f"{cname}-auth.json", bundle)
        bh = file_digest(bp)
        rp = write_canon(
            run_dir / f"{cname}-verify.json",
            {
                "schema": "voice-binding-independent-verification/1",
                "verdict": "APPROVE_CONTROLLED_VOICE_BINDING",
                "authority_id": cname,
                "bundle_sha256": bh,
                "artifacts": bundle["artifacts"],
                "verified_evidence_ids": [cname],
                "scope": "unit trust fixture only",
            },
        )
        authorities.append(
            {
                "authority_id": cname,
                "bundle_path": str(bp),
                "bundle_sha256": bh,
                "verification_path": str(rp),
                "verification_sha256": file_digest(rp),
                "max_bytes": "1048576",
            }
        )
        rights.append(
            {
                "right_id": cname,
                "owner": f"B:{cname}",
                "version": "1",
                "amount": cash,
                "currency": "TEST-CASH",
                "source_ref": f"TestOnly-privately-owned-cash/{cname}",
            }
        )
        plans.append(
            {
                "decision_id": cname,
                "attempt_id": f"attempt-{cname}",
                "plan_id": f"plan-{cname}",
                "owner": f"B:{cname}",
                "voice_binding_id": f"voice-{cname}",
                "right_id": cname,
                "expected_book_version": "2",
                "expected_rights_version": "1",
                "applicant_epoch": "1",
                "applicant_generation": "1",
                "slot_id": slot_id,
                "quantity": new_qty,
                "limit_price": price,
                "fee_tail": fee,
                "quantity_source": f"TestOnly-qty/{cname}",
                "price_source": f"TestOnly-price/{cname}",
                "fee_source": f"TestOnly-fee/{cname}",
                "s_ref": s_ref,
                "o_ref": {
                    "operation_id": f"TestOnly-op-{cname}",
                    "kind": "TestOnlyCashBuy",
                    "source_ref": f"TestOnly-op-sheet/{cname}",
                    "s_object_id": "unit-S-object",
                    "quantity": new_qty,
                },
                "exact": {
                    "command_id": f"cmd-{cname}",
                    "logical_order_family": f"family-{cname}",
                    "chong_id": cname,
                    "revision": "1",
                    "first_quantity": new_qty,
                    "allocation_id": f"alloc-{cname}",
                    "side": "buy",
                    "symbol": symbol,
                    "projection_manifest": f"TestOnly-projection/{cname}",
                    "eligibility_ref": f"S:cmd-{cname}",
                    "concurrency": "single",
                },
            }
        )
        routes.append(
            {
                "chong_id": cname,
                "symbol": symbol,
                "operation_level": op_level,
                "fixed_q": fixed,
                "db": str(db_path),
                "socket": str(sock_path),
            }
        )

    if fx_enabled:
        routes.append(
            {
                "chong_id": "fx-desk",
                "symbol": "TEST-FX/TEST-CASH",
                "operation_level": "2",
                "fixed_q": "100",
                "db": str(run_dir / "b-fx-desk.db"),
                "socket": str(run_dir / "b-fx-desk.sock"),
            }
        )

    def make_slot(slot_id: str, members: list[str]) -> dict:
        return {
            "slot_id": slot_id,
            "applicants": members,
            "input_end": {
                "kind": "ControlledInputEnd",
                "source_id": "ce-s07-fixture",
                "source_epoch": "1",
                "watermark": "2",
                "complete_request_hash": digest(members),
            },
        }

    if plan_overrides:
        for p in plans:
            ov = plan_overrides.get(p["decision_id"])
            if ov:
                for k, v in ov.items():
                    if k == "exact":
                        p["exact"].update(v)
                    elif k == "o_ref":
                        p["o_ref"].update(v)
                    else:
                        p[k] = v
                p["o_ref"]["quantity"] = p["quantity"]

    slots = []
    if slot_main_members is not None:
        slots.append(make_slot("slot-main", slot_main_members))
    else:
        if set(chongs) >= {"alpha", "beta"}:
            slots.append(make_slot("slot-main", ["alpha", "beta"]))
        else:
            slots.append(make_slot("slot-main", [chongs[0]]))
        if "gamma" in chongs:
            slots.append(make_slot("slot-gamma", ["gamma"]))

    conditions = make_fx_conditions_template() if use_fx_marker else make_legacy_conditions()
    market_deps = [FX_MARKER] if use_fx_marker else ["TestOnly-market/nonfx-legacy-v6"]

    fin_data = {
        "schema_revision": finance_schema,
        "kind": "TestOnly",
        "source_id": "ce-s07-fixture",
        "source_epoch": "1",
        "policy": {
            "policy_id": "TestOnly-ce-s07-cap-100" if fx_enabled else "TestOnly-nonfx-cap-100",
            "allocation_policy_id": "#1349/atomic-slot-wait/v1",
            "cap": cap_amount,
            "currency": "TEST-CASH",
            "money_unit": "TEST-CASH",
            "quantity_unit": "TEST-UNIT",
            "quantum": "1",
            "capability_id": "TestOnly-no-leverage-no-venue",
            "model": "TestOnlyUnleveragedCashBuy",
            "valid_through_ns": "9000000000000000000",
        },
        "baseline": {
            "responsibility_id": "r-base",
            "amount": baseline_amount,
            "source_ref": "TestOnly-baseline/r-base",
            "covered_facts": covered,
        },
        "rights": rights,
        "plans": plans,
        "slots": slots,
        "exact_release": {
            "x_target": {"x_id": "X", "x_epoch": "1"},
            "projection_kind": x_model["projection_kind"],
            "rd11_policy": x_model["rd11_policy"],
            "rule_revision": "ce-s07-rule/v1" if fx_enabled else "TestOnly-rule/nonfx-v6",
            "market_dependencies": market_deps,
            "conditions": conditions,
            "model_coverage": {
                "model_ref": {
                    "model_id": x_model["model_id"],
                    "revision": x_model["revision"],
                    "content_hash": digest(x_model),
                },
                "domain_id": "ce-s07-bar-batch/v1",
                "input_domain": [
                    {
                        "order_kind": "limit",
                        "concurrency": "single",
                        "allocation_model": "#1349/atomic-slot-wait/v1",
                    }
                ],
                "unsupported_domains": [
                    {
                        "order_kind": "limit",
                        "concurrency": "batched",
                        "allocation_model": "#1349/atomic-slot-wait/v1",
                    }
                ],
            },
        },
    }
    fin_input_path = write_canon(run_dir / "finance-input.json", fin_data)

    fin_ops = [
        "ImportResponsibility",
        "CaptureExternal",
        "ResolveEvidence",
        "ApplyAllocation",
        "BindVoice",
        "ReadView",
        "QueryFact",
        "QueryDecision",
        "QueryGrant",
        "QueryVoice",
        "PrepareDecision",
        "Reserve",
        "CommitDecision",
        "AbortDecision",
        "CloseApplicants",
        "ActivateCapPolicy",
        "MakeDispatchable",
        "ReleaseExact",
        "QueryCommand",
        "QueryReleasedExact",
    ]
    if fx_enabled:
        fin_ops.extend(["ImportFxResponsibility", "QueryFxValuation"])

    e_node = {"db": str(run_dir / "e.db"), "socket": str(run_dir / "e.sock")}
    authorized_sources = [
        {**src_fin, "operations": fin_ops},
        {**src_market, "operations": ["CaptureExternal", "ResolveEvidence"]},
    ]
    if authorize_x_query:
        authorized_sources.append({**src_x, "operations": ["QueryReleasedExact", "QueryCommand", "ReadView"]})
    manifest = {
        "schema_revision": "economic-manifest/1",
        "book_revision": "tb03c-book/1",
        "session_id": sid,
        "session_generation": gen,
        "e": e_node,
        "chongs": routes,
        "authorized_sources": authorized_sources,
        "resources": {
            "max_frame_bytes": "16777216",
            "read_timeout_ms": "5000",
            "write_timeout_ms": "5000",
            "response_timeout_ms": "60000",
            "queue_capacity": "16",
            "max_connections": "16",
        },
        "clock": {
            "kind": "logical-bar/1",
            "bars": {
                "init": "0",
                "messages": clock_messages,
                "recover": recover_bars,
            },
        },
        "voice_binding": {
            "schema_revision": "voice-binding/1",
            "authorities": authorities,
        },
        "finance": {
            "schema_revision": finance_schema,
            "input_path": str(fin_input_path),
            "input_sha256": file_digest(fin_input_path),
            "coordinator_source": src_fin,
            "structure": {
                "binary": str(stub_path),
                "binary_sha256": stub_sha,
                "db": str(run_dir / "s-unit.db"),
                "session_id": sid,
                "session_generation": gen,
                "writer_epoch": "1",
            },
        },
    }

    if fx_obligations_bytes is not None:
        fx_ob_path = run_dir / "fx-obligations.json"
        fx_ob_path.write_bytes(fx_obligations_bytes)
        manifest["fx_valuation"] = {
            "schema_revision": fx_schema,
            "kind": "TestOnly",
            "obligation_input_path": str(fx_ob_path),
            "obligation_input_sha256": sha256_bytes(fx_obligations_bytes),
        }

    manifest_path = write_canon(run_dir / "manifest.json", manifest)

    # X profile (x-execution-profile/3)
    x_socket = str(run_dir / "x.sock")
    x_profile_path = write_canon(
        run_dir / "x-profile.json",
        {
            "profile_revision": "x-execution-profile/3",
            "mode": "simulation",
            "credential_scope": {"env": "UNUSED_SIMULATION_CREDENTIAL"},
            "history_simulation": {
                "model": x_model,
                "session_id": sid,
                "session_generation": gen,
                "x_id": "X",
                "source_namespace": X_NS,
                "source_epoch": X_EPOCH,
                "socket": x_socket,
                "timeout_ms": 5000,
                "max_frame_bytes": 1048576,
                "conditions": fin_data["exact_release"]["conditions"],
                "e": {
                    "socket": e_node["socket"],
                    "authority_id": "E",
                    "authority_epoch": "1",
                    "schema_revision": "economic-session/1",
                    "reply_namespace": "economic-session/replies",
                    "producer_id": f"E:{sid}",
                },
                "s": {
                    "socket": s_socket_for_x,
                    "authority_id": "S",
                    "authority_epoch": "1",
                    "schema_revision": "s-session/3",
                    "reply_namespace": "s-session/3",
                    "producer_id": f"S:{sid}",
                },
            },
        },
    )

    # S3 structure session config
    sd = run_dir / "sd"
    sd.mkdir(parents=True, exist_ok=True)
    sdb = sd / "s.db"
    decl = {"category": "TestOnlyStructure", "namespaces": [MARKET_NS]}
    decl_path = write_canon(run_dir / "structure-source.json", decl)
    sclock_path = write_canon(
        run_dir / "sclock.json",
        {
            "schema_revision": "s-clock-plan/1",
            "clock_plan_id": f"ce-s07-{sid}",
            "origin_utc": "2026-11-19T00:00:00Z",
            "unit": "ns",
            "events": s_clock_events,
        },
    )
    sres_path = write_canon(
        run_dir / "s-resources.json",
        {
            "schema_revision": "s-structure-resources/1",
            "s_resources": {
                "max_frame_bytes": "1048576",
                "read_timeout_ms": "1000",
                "write_timeout_ms": "1000",
                "response_timeout_ms": "30000",
                "audit_cache_source_bytes": "1048576",
                "queue_capacity": "4",
                "max_connections": "4",
            },
        },
    )

    return {
        "sid": sid,
        "gen": gen,
        "src_fin": src_fin,
        "src_market": src_market,
        "src_x": src_x,
        "fin_data": fin_data,
        "plans": {p["decision_id"]: p for p in plans},
        "slots": {sl["slot_id"]: sl for sl in slots},
        "openers": openers,
        "voice_bindings": voice_bindings,
        "manifest_path": manifest_path,
        "manifest": manifest,
        "e_node": e_node,
        "b_nodes": {n["chong_id"]: n for n in routes},
        "active_chongs": chongs,
        "x_socket": x_socket,
        "x_db": run_dir / "x.db",
        "x_profile_path": x_profile_path,
        "sd": sd,
        "sdb": sdb,
        "decl": decl,
        "decl_path": decl_path,
        "sclock_path": sclock_path,
        "sres_path": sres_path,
        "s_socket": str(run_dir / "structure.sock"),
    }


class LiveProductionSession:
    """Supervises one real `production_session` (S3 + E + B* + X)."""

    def __init__(self, name: str, bins: Path, run_dir: Path, cfg: dict):
        self.name = name
        self.bins = bins
        self.run_dir = run_dir
        self.cfg = cfg
        self.wire_log: list[dict] = []
        self.proc: subprocess.Popen | None = None
        self.out_f = None
        self.err_f = None
        self.env: dict[str, str] = {}

    def start(self) -> None:
        cfg = self.cfg
        catalog = SRC / "s_session/catalog/signed-catalog.json"
        sprofile = SRC / "s_session/profiles/ohlc_integer_tb02a_v1.json"

        init_res = run_cli(
            [
                str(self.bins / "s_structure_session"),
                "init",
                "--protocol-revision",
                "s-session/3",
                "--db",
                str(cfg["sdb"]),
                "--session",
                cfg["sid"],
                "--catalog",
                str(catalog),
                "--profile",
                str(sprofile),
                "--session-generation",
                cfg["gen"],
                "--clock-plan",
                str(cfg["sclock_path"]),
                "--delivery-retain-generations",
                "4",
                "--structure-source",
                str(cfg["decl_path"]),
            ]
        )
        assert init_res.returncode == 0, (init_res.stdout, init_res.stderr)

        sstate = cfg["sd"] / "state"
        sstate.mkdir(parents=True, exist_ok=True)
        anchor = TestAnchor(
            cfg["sdb"],
            sstate,
            limits={
                "max_total_wire_bytes": "1073741824",
                "max_total_node_bytes": "1073741824",
                "max_total_nodes": "10000000",
                "max_total_records": "10000000",
                "max_total_requests": "1000000",
                "max_elapsed_ms": "600000",
                "max_staged_bytes": "67108864",
                "max_store_bytes": "1073741824",
            },
        )
        self.env = dict(os.environ, **anchor.env())

        prod_manifest_path = write_canon(
            self.run_dir / "production.json",
            {
                "manifest_revision": "production-session-manifest/1",
                "profile": "simulation",
                "state_dir": str(self.run_dir / "launcher-state"),
                "execution_capabilities": {"namespaces": ["x-sim"]},
                "structure_source": cfg["decl"],
                "s": {
                    "db": str(cfg["sdb"]),
                    "session": cfg["sid"],
                    "catalog": str(catalog),
                    "profile": str(sprofile),
                    "clock_plan": str(cfg["sclock_path"]),
                    "session_generation": cfg["gen"],
                    "delivery_retain_generations": "4",
                    "admission_job_limits": str(anchor.limits_path),
                    "writer_epoch": "1",
                    "socket": cfg["s_socket"],
                    "resource_config": str(cfg["sres_path"]),
                },
                "economic": {
                    "manifest": str(cfg["manifest_path"]),
                    "e": {"db": cfg["e_node"]["db"], "epoch": "1"},
                    "b": [
                        {"chong": cid, "db": cfg["b_nodes"][cid]["db"], "epoch": "1"}
                        for cid in cfg["active_chongs"]
                    ],
                },
                "x": {
                    "db": str(cfg["x_db"]),
                    "profile": str(cfg["x_profile_path"]),
                    "writer_epoch": "1",
                },
            },
        )
        self.out_f = (self.run_dir / "outer.stdout").open("wb")
        self.err_f = (self.run_dir / "outer.stderr").open("wb")
        self.proc = subprocess.Popen(
            [str(self.bins / "production_session"), "--manifest", str(prod_manifest_path)],
            stdin=subprocess.DEVNULL,
            stdout=self.out_f,
            stderr=self.err_f,
            env=self.env,
        )
        err_path = self.run_dir / "outer.stderr"
        sockets = (
            [cfg["s_socket"], cfg["e_node"]["socket"]]
            + [cfg["b_nodes"][cid]["socket"] for cid in cfg["active_chongs"]]
            + [cfg["x_socket"]]
        )
        for addr in sockets:
            wait_ready(self.proc, addr, f"{self.name}:{Path(addr).name}", err_path)

    def stop(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        if self.out_f is not None:
            self.out_f.close()
        if self.err_f is not None:
            self.err_f.close()

    def ewire(
        self,
        domain: str,
        message_id: str,
        payload: dict,
        *,
        expected: str | None = None,
        source: dict | None = None,
        producer_epoch: str = "1",
    ) -> dict:
        cfg = self.cfg
        sock = cfg["e_node"]["socket"] if domain == "E" else cfg["b_nodes"][domain.split(":", 1)[1]]["socket"]
        src = source if source is not None else cfg["src_fin"]
        req = {
            "schema_revision": "economic-session/1",
            "session_id": cfg["sid"],
            "session_generation": cfg["gen"],
            **src,
            "message_id": message_id,
            "payload_hash": digest(payload),
            "causal_refs": [],
            "payload": payload,
        }
        _, _, rep = send_frame(sock, req, wire_log=self.wire_log, label=f"{domain}:{message_id}")
        result = validate_reply(req, rep, producer=domain, producer_epoch=producer_epoch)
        if expected is not None:
            assert result.get("kind") == expected, (domain, message_id, expected, result)
        return result

    def xwire(self, label: str, op: str, payload, *, expected: str | None = None) -> dict:
        req = {"protocol": "x-exact-simulation/1", "op": op, "payload": payload}
        _, _, rep = send_frame(self.cfg["x_socket"], req, wire_log=self.wire_log, label=f"X:{label}")
        if expected is not None:
            assert rep.get("kind") == expected, (label, expected, rep)
        return rep

    def swire(self, message_id: str, payload: dict) -> tuple[bytes, bytes, dict]:
        cfg = self.cfg
        req = {
            "schema_revision": "s-session/3",
            "session_id": cfg["sid"],
            "session_generation": cfg["gen"],
            **cfg["src_market"],
            "message_id": message_id,
            "payload_hash": digest(payload),
            "causal_refs": [],
            "payload": payload,
        }
        return send_frame(cfg["s_socket"], req, wire_log=self.wire_log, label=f"S:{message_id}")

    def s_ingest_quote(self, msg_id: str, quote_text: str) -> dict:
        q = json.loads(quote_text)
        price = q["price_numerator"]
        payload = {
            "op": "ingest",
            "clock_event_id": msg_id,
            "target_session_id": self.cfg["sid"],
            "target_session_generation": self.cfg["gen"],
            "writer_epoch": "1",
            "raw_input": {
                "schema_revision": "s-ohlc/1",
                "profile": "ohlc_integer_tb02a_v1",
                "session_id": self.cfg["sid"],
                "source_namespace": q["source_namespace"],
                "source_epoch": q["source_epoch"],
                "instrument": q["instrument"],
                "events": [
                    {
                        "event_id": q["event_id"],
                        "revision": q["revision"],
                        "seq": q["source_coord"],
                        "timestamp": q["timestamp"],
                        "received_at": q["received_at"],
                        "open": price,
                        "high": price,
                        "low": price,
                        "close": price,
                        "volume": "1",
                        "raw_text": quote_text,
                    }
                ],
            },
        }
        _, _, rep = self.swire(msg_id, payload)
        assert rep.get("payload", rep).get("ok") is True, (msg_id, rep)
        return rep

    def s_ingest_prefix(self, msg_id: str, seq_num: int, price: str) -> dict:
        payload = {
            "op": "ingest",
            "clock_event_id": msg_id,
            "target_session_id": self.cfg["sid"],
            "target_session_generation": self.cfg["gen"],
            "writer_epoch": "1",
            "raw_input": {
                "schema_revision": "s-ohlc/1",
                "profile": "ohlc_integer_tb02a_v1",
                "session_id": self.cfg["sid"],
                "source_namespace": MARKET_NS,
                "source_epoch": MARKET_EPOCH,
                "instrument": "TEST-FX/TEST-CASH",
                "events": [
                    {
                        "event_id": msg_id,
                        "revision": "1",
                        "seq": str(seq_num),
                        "timestamp": str(seq_num),
                        "received_at": "2026-11-19T00:00:00Z",
                        "open": price,
                        "high": price,
                        "low": price,
                        "close": price,
                        "volume": "1",
                        "raw_text": f"TestOnly FX prefix {msg_id}",
                    }
                ],
            },
        }
        _, _, rep = self.swire(msg_id, payload)
        assert rep.get("payload", rep).get("ok") is True, (msg_id, rep)
        return rep

    def flush_wire_log(self) -> Path:
        p = self.run_dir / "wire.jsonl"
        with p.open("w", encoding="utf-8") as f:
            for item in self.wire_log:
                f.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")
        return p


def read_s3_raw_history(sdb: Path) -> list[dict]:
    with closing(sqlite3.connect(sdb.as_uri() + "?mode=ro", uri=True)) as c:
        rows = c.execute(
            """
            SELECT e.seq, e.receipt_id, e.source_namespace, e.source_epoch, e.instrument,
                   e.event_id, e.source_coord, e.revision, e.supersedes_revision,
                   o.open, o.high, o.low, o.close, e.raw_text, e.identity_key,
                   m.first_published_generation, m.status
            FROM raw_events e
            JOIN raw_ohlc o
              ON o.identity_key = e.identity_key AND o.revision = e.revision
            LEFT JOIN s_input_messages m
              ON m.receipt_id = e.receipt_id
            ORDER BY e.seq ASC
            """
        ).fetchall()
    out = []
    for r in rows:
        raw_text = r[13]
        out.append(
            {
                "seq": r[0],
                "receipt_id": r[1],
                "source_namespace": r[2],
                "source_epoch": r[3],
                "instrument": r[4],
                "event_id": r[5],
                "source_coord": r[6],
                "revision": str(r[7]),
                "supersedes_revision": None if r[8] is None else str(r[8]),
                "open": r[9],
                "high": r[10],
                "low": r[11],
                "close": r[12],
                "identity_key": r[14],
                "first_published_generation": r[15],
                "status": r[16],
                "raw_sha256": sha256_bytes(raw_text.encode("utf-8")),
                "raw_text": raw_text,
            }
        )
    return out


def make_bar(i: int, changes: list[dict] | None = None) -> dict:
    return {
        "request_id": f"bar-{i}",
        "known_frontier_cut": f"frontier-{i}",
        "bar": {"index": i, "open": 14, "low": 13, "high": 15, "close": 14},
        "capacity": {"kind": "none"},
        "close_changes": changes or [],
        "scenario_busts": [],
    }


def make_unrelated_quote(revision: str, supersedes: str | None, num: str, coord: str = "71") -> str:
    return canonical(
        {
            "schema_revision": "testonly-fx-quote/1",
            "source_namespace": MARKET_NS,
            "source_epoch": MARKET_EPOCH,
            "instrument": "OTHER-FX/TEST-CASH",
            "event_id": "fx-quote-unrelated-999",
            "source_coord": coord,
            "timestamp": coord,
            "received_at": f"2026-11-19T00:01:0{revision}Z",
            "revision": revision,
            "supersedes_revision": supersedes,
            "base_unit": "OTHER-FX",
            "quote_unit": "TEST-CASH",
            "price_numerator": num,
            "price_denominator": "1",
        }
    ).decode("utf-8")


def matches_invalidation_sources(inv_sources: list[str], chain_id: str, revision: int) -> bool:
    prefix = f"market-supersession:{chain_id}:after_rev="
    for item in inv_sources:
        if item.startswith(prefix):
            bound_rev = int(item[len(prefix) :])
            if revision > bound_rev:
                return True
    return False


def run_arm1_main_lifecycle(bins: Path, fixtures: Path, out: Path) -> dict:
    run_dir = out / "arm1_ce_s07_main"
    ob_bytes = (fixtures / "fx-obligations.json").read_bytes()
    r1_utf8 = (fixtures / "fx-r1.json").read_text(encoding="utf-8")
    r2_utf8 = (fixtures / "fx-r2.json").read_text(encoding="utf-8")
    r3_utf8 = (fixtures / "fx-r3.json").read_text(encoding="utf-8")
    unrel_r1_utf8 = make_unrelated_quote("1", None, "5")
    unrel_r2_utf8 = make_unrelated_quote("2", "1", "9")

    x_model = {**base_sim_model(), "symbol": "TEST"}

    # Monotonic logical-bar/1 schedule (init=0, setup=1, alpha release=2, r2/r3/beta release=3, recover=4)
    setup_msgs = [
        "imp-base",
        "imp-fx",
        "cap-r1",
        "res-r1",
        "cap-open-alpha",
        "apply-open-alpha",
        "bind-alpha",
        "prep-alpha",
        "cap-open-beta",
        "apply-open-beta",
        "bind-beta",
        "prep-beta",
        "cap-open-gamma",
        "apply-open-gamma",
        "bind-gamma",
        "prep-gamma",
        "reserve-main",
        "commit-alpha",
        "commit-beta",
        "dispatch-alpha",
        "dispatch-beta",
        "q-cut10",
    ]
    neg_msgs = [
        "neg-placeholder-market",
        "neg-placeholder-cond",
        "neg-latest",
        "neg-admissible-bool",
        "neg-marker-leak",
        "neg-drop-fx-resp",
        "neg-tamper-rate",
        "neg-stale-cut",
    ]
    clock_messages = {m: "1" for m in setup_msgs}
    for m in neg_msgs:
        clock_messages[m] = "2"
    clock_messages.update(
        {
            "release-alpha": "2",
            "cap-r2": "3",
            "q-cut12": "3",
            "release-alpha-new-msg": "3",
            "release-alpha-tampered-retry": "3",
            "release-beta-overcap": "3",
            "reserve-gamma-overcap": "3",
            "res-r2-overcap": "3",
            "cap-r3": "3",
            "res-r3": "3",
            "q-cut14": "3",
            "release-beta-before-retire": "3",
            "retire-r2": "3",
            "q-cut15": "3",
            "release-beta-stale-r1": "3",
            "release-beta": "3",
            "reserve-gamma": "3",
            "q-cut17": "3",
            "q-ep2-cur": "4",
            "q-ep2-hist12": "4",
            "q-ep2-alpha": "4",
            "q-ep2-beta": "4",
        }
    )

    s_clock_events = {
        "prefix-1": {"accept_ns": "10", "attempts": [{"begin_ns": "11", "commit_ns": "12"}]},
        "prefix-2": {"accept_ns": "20", "attempts": [{"begin_ns": "21", "commit_ns": "22"}]},
        "prefix-3": {"accept_ns": "30", "attempts": [{"begin_ns": "31", "commit_ns": "32"}]},
        "fx-r1": {"accept_ns": "40", "attempts": [{"begin_ns": "41", "commit_ns": "42"}]},
        "unrel-r1": {"accept_ns": "45", "attempts": [{"begin_ns": "46", "commit_ns": "47"}]},
        "fx-r2": {"accept_ns": "50", "attempts": [{"begin_ns": "51", "commit_ns": "52"}]},
        "unrel-r2": {"accept_ns": "55", "attempts": [{"begin_ns": "56", "commit_ns": "57"}]},
        "fx-r3": {"accept_ns": "60", "attempts": [{"begin_ns": "61", "commit_ns": "62"}]},
    }

    cfg = build_session_artifacts(
        run_dir,
        session_id="ce-s07-integrated-main",
        chongs=["alpha", "beta", "gamma"],
        x_model=x_model,
        fx_obligations_bytes=ob_bytes,
        clock_messages=clock_messages,
        recover_bars=["4"],
        s_clock_events=s_clock_events,
        s_socket_for_x=str(run_dir / "structure.sock"),
        baseline_amount="0",
        cap_amount="100",
    )

    sess = LiveProductionSession("arm1", bins, run_dir, cfg)
    sess.start()
    try:
        # 1. Real S3 ingests prefix + r1 + unrelated r1
        sess.s_ingest_prefix("prefix-1", 10, "4")
        sess.s_ingest_prefix("prefix-2", 20, "4")
        sess.s_ingest_prefix("prefix-3", 30, "4")
        sess.s_ingest_quote("fx-r1", r1_utf8)
        sess.s_ingest_quote("unrel-r1", unrel_r1_utf8)

        # 2. E cuts 1..10 (alpha=30, beta=40, fx ob=20*1=20 -> 90/100)
        c1 = sess.ewire("E", "imp-base", {"op": "ImportResponsibility", "responsibility_id": "r-base", "writer_epoch": "1"}, expected="ResponsibilityImportedReceipt")
        assert c1["cut"]["commit_seq"] == "1"

        c2 = sess.ewire(
            "E",
            "imp-fx",
            {"op": "ImportFxResponsibility", "responsibility_id": "ob-fx-unclosed-20", "writer_epoch": "1"},
            expected="FxResponsibilityImportedReceipt",
        )
        assert c2["cut"]["commit_seq"] == "2"

        c3 = sess.ewire(
            "E",
            "cap-r1",
            {"op": "CaptureExternal", "raw_utf8": r1_utf8, "json_pointer": "", "token": "fx-r1", "source_event_time": "70"},
            expected="Recorded",
            source=cfg["src_market"],
        )
        assert c3["cut"]["commit_seq"] == "3"
        r1_fk = c3["fact_key"]

        c4 = sess.ewire(
            "E",
            "res-r1",
            {
                "op": "ResolveEvidence",
                "evidence_id": "ev-r1",
                "covered": [{"fact_key": r1_fk, "token": "fx-r1", "fact_hash": c3["fact_hash"]}],
                "frontier": {"source_namespace": MARKET_NS, "source_epoch": MARKET_EPOCH, "cursor": "70"},
                "dependency_version": "ce-s07-r1/1",
            },
            expected="Resolved",
            source=cfg["src_market"],
        )
        assert c4["cut"]["commit_seq"] == "4"

        for cid, expected_seq in [("alpha", "5"), ("beta", "6"), ("gamma", "7")]:
            cap_open = sess.ewire(
                "E",
                f"cap-open-{cid}",
                {
                    "op": "CaptureExternal",
                    "raw_utf8": cfg["openers"][cid],
                    "json_pointer": "/events/0",
                    "token": f"tok-opening-{cid}",
                    "source_event_time": None,
                },
                expected="Recorded",
            )
            assert cap_open["cut"]["commit_seq"] == expected_seq
            sess.ewire(
                f"B:{cid}",
                f"apply-open-{cid}",
                {
                    "op": "ApplyAllocation",
                    "fact_key": cap_open["fact_key"],
                    "allocation_id": f"allocation-{cid}",
                    "expected_fact_hash": cap_open["fact_hash"],
                },
                expected="Applied",
            )
            sess.ewire(f"B:{cid}", f"bind-{cid}", cfg["voice_bindings"][cid], expected="VoiceBound")
            sess.ewire(
                f"B:{cid}",
                f"prep-{cid}",
                {"op": "PrepareDecision", "decision_id": cid, "plan_hash": digest(cfg["plans"][cid]), "writer_epoch": "1"},
                expected="PreparedReceipt",
            )

        res_main = sess.ewire(
            "E",
            "reserve-main",
            {
                "op": "Reserve",
                "slot_id": "slot-main",
                "request_set_hash": digest(cfg["slots"]["slot-main"]["applicants"]),
                "writer_epoch": "1",
            },
            expected="ReserveReceipt",
        )
        assert res_main["cut"]["commit_seq"] == "8"
        grants = {g["decision_id"]: g["grant_id"] for g in res_main["record"]["grants"]}

        for cid in ("alpha", "beta"):
            sess.ewire(
                f"B:{cid}",
                f"commit-{cid}",
                {
                    "op": "CommitDecision",
                    "decision_id": cid,
                    "plan_hash": digest(cfg["plans"][cid]),
                    "grant_id": grants[cid],
                    "writer_epoch": "1",
                },
                expected="LocalCommitReceipt",
            )

        c9 = sess.ewire(
            "E",
            "dispatch-alpha",
            {"op": "MakeDispatchable", "decision_id": "alpha", "plan_hash": digest(cfg["plans"]["alpha"]), "writer_epoch": "1"},
            expected="DispatchableReceipt",
        )
        assert c9["cut"]["commit_seq"] == "9"

        c10 = sess.ewire(
            "E",
            "dispatch-beta",
            {"op": "MakeDispatchable", "decision_id": "beta", "plan_hash": digest(cfg["plans"]["beta"]), "writer_epoch": "1"},
            expected="DispatchableReceipt",
        )
        assert c10["cut"]["commit_seq"] == "10"

        q10 = sess.ewire("E", "q-cut10", {"op": "QueryFxValuation", "as_known_ns": None, "cut": None}, expected="EconomicFxValuation")
        assert q10["cut"]["commit_seq"] == "10"
        assert q10["fx_valuation"]["summary"]["evaluated_total"] == "90"
        assert q10["fx_valuation"]["summary"]["cap"] == "100"
        assert q10["fx_valuation"]["summary"]["gate_status"] == "AdmissibleWithinCap"
        write_pretty(out / "e_cut10_fx_valuation.json", q10)

        # 3. 8 pre-release tamper/drop/placeholder negative controls at E cut 10
        alpha_plan = cfg["plans"]["alpha"]
        alpha_cert = build_fx_certificate_from_query(cfg["sid"], cfg["gen"], cfg["fin_data"], alpha_plan, grants["alpha"], q10)
        assert_no_fx_placeholders(alpha_cert)
        alpha_change = change_for_plan(alpha_plan)

        def release_req(decision_id: str, cert: dict) -> dict:
            p = cfg["plans"][decision_id]
            return {
                "op": "ReleaseExact",
                "decision_id": decision_id,
                "command_id": p["exact"]["command_id"],
                "plan_hash": digest(change_for_plan(p)),
                "certificate": cert,
                "x_id": "X",
                "x_epoch": "1",
                "writer_epoch": "1",
            }

        neg_cases: list[tuple[str, dict]] = []
        c_ph_m = copy.deepcopy(alpha_cert)
        c_ph_m["market_dependencies"] = ["TestOnly-market/1407-c1"]
        neg_cases.append(("neg-placeholder-market", c_ph_m))

        c_ph_c = copy.deepcopy(alpha_cert)
        c_ph_c["conditions"][0]["dependency_set"] = ["controlled-dependency"]
        neg_cases.append(("neg-placeholder-cond", c_ph_c))

        c_latest = copy.deepcopy(alpha_cert)
        c_latest["market_dependencies"] = [f"fx-quote:{MARKET_NS}|1|TEST-FX/TEST-CASH|fx-quote-007:latest"]
        neg_cases.append(("neg-latest", c_latest))

        c_adm = copy.deepcopy(alpha_cert)
        c_adm["conditions"][0]["coverage_proof"] = "admissible:true"
        neg_cases.append(("neg-admissible-bool", c_adm))

        c_mark = copy.deepcopy(alpha_cert)
        c_mark["market_dependencies"] = [FX_MARKER]
        neg_cases.append(("neg-marker-leak", c_mark))

        c_drop = copy.deepcopy(alpha_cert)
        c_drop["responsibility_refs"] = [grants["alpha"]]
        neg_cases.append(("neg-drop-fx-resp", c_drop))

        c_rate = copy.deepcopy(alpha_cert)
        c_rate["market_dependencies"] = [s.replace("rate=1/1", "rate=2/1") for s in c_rate["market_dependencies"]]
        neg_cases.append(("neg-tamper-rate", c_rate))

        c_stale = copy.deepcopy(alpha_cert)
        c_stale["conditions"][0]["evidence_refs"] = [
            s.replace("e-cut:E:10:", "e-cut:E:9:") for s in c_stale["conditions"][0]["evidence_refs"]
        ]
        neg_cases.append(("neg-stale-cut", c_stale))

        neg_results = {}
        for msg_id, bad_cert in neg_cases:
            err = sess.ewire("E", msg_id, release_req("alpha", bad_cert), expected="Error")
            assert err["error"].startswith("IdentityConflict："), (msg_id, err)
            neg_results[msg_id] = err["error"]

        # Confirm E stayed at cut 10 after all 8 rejected attempts
        q10_check = sess.ewire("E", "q-cut10", {"op": "QueryFxValuation", "as_known_ns": None, "cut": None}, expected="EconomicFxValuation")
        assert q10_check["cut"]["commit_seq"] == "10"

        # 4. E cut 11: real ReleaseExact(alpha)
        rel_alpha = sess.ewire("E", "release-alpha", release_req("alpha", alpha_cert), expected="ReleasedExactReceipt")
        assert rel_alpha["cut"]["commit_seq"] == "11"
        cmd_alpha = rel_alpha["record"]["command"]
        assert_no_fx_placeholders(cmd_alpha)
        assert cmd_alpha["model_ref"]["content_hash"] == digest(x_model)
        assert "ob-fx-unclosed-20" in cmd_alpha["certificate"]["responsibility_refs"]
        assert any(
            d.startswith(f"fx-quote:{MARKET_NS}|1|TEST-FX/TEST-CASH|fx-quote-007@rev=1;")
            and f"raw_sha256={EXPECTED_FIXTURE_SHA256['fx-r1.json']}" in d
            for d in cmd_alpha["certificate"]["market_dependencies"]
        ), cmd_alpha["certificate"]["market_dependencies"]
        write_pretty(out / "receipt_alpha_cut11.json", rel_alpha)
        write_pretty(out / "cmd_alpha_cut11.json", cmd_alpha)

        # 5. Real X (x-execution-profile/3) verifies cmd-alpha against real E
        sess.xwire("bar-0", "AdvanceBar", make_bar(0), expected="SimulationBatch")
        x_early = sess.xwire("accept-alpha-early", "AcceptExact", cmd_alpha, expected="Error")
        assert x_early["error"].startswith("InvalidDomain：X 接纳时钟早于 E 持久交付"), x_early

        sess.xwire("bar-1", "AdvanceBar", make_bar(1), expected="SimulationBatch")
        forged_model = copy.deepcopy(cmd_alpha)
        forged_model["model_ref"]["content_hash"] = "0" * 64
        x_forged_model = sess.xwire("accept-alpha-forged-model", "AcceptExact", forged_model, expected="Error")
        assert x_forged_model["error"].startswith("IdentityConflict："), x_forged_model

        tampered_cert = copy.deepcopy(cmd_alpha)
        tampered_cert["certificate"]["market_dependencies"] = ["TestOnly-market/1407-c1"]
        tampered_cert["certificate_hash"] = digest(tampered_cert["certificate"])
        x_tampered_ph = sess.xwire("accept-alpha-placeholder", "AcceptExact", tampered_cert, expected="Error")
        assert (
            x_tampered_ph["error"]
            == "Unsupported：FX 精确命令证书不得保留模板标记或占位名（TestOnly-market/1407-c1）"
        ), x_tampered_ph

        tampered_e_mismatch = copy.deepcopy(cmd_alpha)
        tampered_e_mismatch["certificate"]["market_dependencies"] = [
            s.replace("rate=1/1", "rate=9/1") for s in tampered_e_mismatch["certificate"]["market_dependencies"]
        ]
        tampered_e_mismatch["certificate_hash"] = digest(tampered_e_mismatch["certificate"])
        x_tampered_e = sess.xwire("accept-alpha-e-mismatch", "AcceptExact", tampered_e_mismatch, expected="Error")
        assert "IdentityConflict" in x_tampered_e["error"], x_tampered_e

        x_acc_alpha = sess.xwire("accept-alpha", "AcceptExact", cmd_alpha, expected="ExactCommandState")
        assert x_acc_alpha["state"] == "Accepted", x_acc_alpha

        # 6. Real S3 ingests fx-r2 + unrelated r2; E cut 12 captures fx-r2 -> 110/100
        sess.s_ingest_quote("fx-r2", r2_utf8)
        sess.s_ingest_quote("unrel-r2", unrel_r2_utf8)

        c12 = sess.ewire(
            "E",
            "cap-r2",
            {"op": "CaptureExternal", "raw_utf8": r2_utf8, "json_pointer": "", "token": "fx-r2", "source_event_time": "70"},
            expected="Recorded",
            source=cfg["src_market"],
        )
        assert c12["cut"]["commit_seq"] == "12"
        r2_fk = c12["fact_key"]

        q12 = sess.ewire("E", "q-cut12", {"op": "QueryFxValuation", "as_known_ns": None, "cut": None}, expected="EconomicFxValuation")
        assert q12["cut"]["commit_seq"] == "12"
        assert q12["fx_valuation"]["summary"]["evaluated_total"] == "110"
        assert q12["fx_valuation"]["summary"]["gate_status"] == "BlockedExceedsCap"
        write_pretty(out / "e_cut12_fx_valuation.json", q12)

        # Original receipt priority at 110/100: same message_id AND new message_id return exact cut-11 receipt
        retry_same = sess.ewire("E", "release-alpha", release_req("alpha", alpha_cert), expected="ReleasedExactReceipt")
        assert canonical(retry_same) == canonical(rel_alpha)
        retry_new = sess.ewire("E", "release-alpha-new-msg", release_req("alpha", alpha_cert), expected="ReleasedExactReceipt")
        assert retry_new["cut"] == rel_alpha["cut"]
        assert retry_new["receipt_key"] == rel_alpha["receipt_key"]
        assert canonical(retry_new["record"]) == canonical(rel_alpha["record"])

        # Tampered retry of alpha must fail IdentityConflict
        retry_tampered = sess.ewire("E", "release-alpha-tampered-retry", release_req("alpha", c_drop), expected="Error")
        assert retry_tampered["error"].startswith("IdentityConflict："), retry_tampered

        # Old alpha receipt cannot act as new eligibility for beta or gamma
        beta_plan = cfg["plans"]["beta"]
        beta_cert_r1 = build_fx_certificate_from_query(cfg["sid"], cfg["gen"], cfg["fin_data"], beta_plan, grants["beta"], q10)
        beta_overcap = sess.ewire("E", "release-beta-overcap", release_req("beta", beta_cert_r1), expected="Error")
        assert beta_overcap["error"].startswith("AwaitingPolicy："), beta_overcap

        gamma_overcap = sess.ewire(
            "E",
            "reserve-gamma-overcap",
            {
                "op": "Reserve",
                "slot_id": "slot-gamma",
                "request_set_hash": digest(cfg["slots"]["slot-gamma"]["applicants"]),
                "writer_epoch": "1",
            },
            expected="Error",
        )
        assert gamma_overcap["error"].startswith("AwaitingPolicy："), gamma_overcap

        res_r2_overcap = sess.ewire(
            "E",
            "res-r2-overcap",
            {
                "op": "ResolveEvidence",
                "evidence_id": "ev-r2-overcap",
                "covered": [{"fact_key": r2_fk, "token": "fx-r2", "fact_hash": c12["fact_hash"]}],
                "frontier": {"source_namespace": MARKET_NS, "source_epoch": MARKET_EPOCH, "cursor": "70"},
                "dependency_version": "ce-s07-r2/1",
            },
            expected="Error",
            source=cfg["src_market"],
        )
        assert res_r2_overcap["error"].startswith("AwaitingPolicy："), res_r2_overcap

        # 7. Real S3 ingests fx-r3; E cuts 13..15 capture r3, resolve r3, retire r2 -> 90/100
        sess.s_ingest_quote("fx-r3", r3_utf8)
        c13 = sess.ewire(
            "E",
            "cap-r3",
            {"op": "CaptureExternal", "raw_utf8": r3_utf8, "json_pointer": "", "token": "fx-r3", "source_event_time": "70"},
            expected="Recorded",
            source=cfg["src_market"],
        )
        assert c13["cut"]["commit_seq"] == "13"
        r3_fk = c13["fact_key"]

        c14 = sess.ewire(
            "E",
            "res-r3",
            {
                "op": "ResolveEvidence",
                "evidence_id": "ev-r3",
                "covered": [{"fact_key": r3_fk, "token": "fx-r3", "fact_hash": c13["fact_hash"]}],
                "frontier": {"source_namespace": MARKET_NS, "source_epoch": MARKET_EPOCH, "cursor": "70"},
                "dependency_version": "ce-s07-r3/1",
            },
            expected="Resolved",
            source=cfg["src_market"],
        )
        assert c14["cut"]["commit_seq"] == "14"
        q14 = sess.ewire("E", "q-cut14", {"op": "QueryFxValuation", "as_known_ns": None, "cut": None}, expected="EconomicFxValuation")
        assert q14["fx_valuation"]["summary"]["evidence_coverage_status"] == "PendingRetirement"
        beta_before_retire = sess.ewire("E", "release-beta-before-retire", release_req("beta", beta_cert_r1), expected="Error")
        assert beta_before_retire["error"].startswith("AwaitingPolicy："), beta_before_retire

        c15 = sess.ewire(
            "E",
            "retire-r2",
            {
                "op": "ResolveEvidence",
                "evidence_id": "ev-retire-r2",
                "covered": [{"fact_key": r2_fk, "token": "fx-r2", "fact_hash": c12["fact_hash"]}],
                "frontier": {"source_namespace": MARKET_NS, "source_epoch": MARKET_EPOCH, "cursor": "70"},
                "dependency_version": "ce-s07-retire-r2/1",
            },
            expected="Resolved",
            source=cfg["src_market"],
        )
        assert c15["cut"]["commit_seq"] == "15"
        q15 = sess.ewire("E", "q-cut15", {"op": "QueryFxValuation", "as_known_ns": None, "cut": None}, expected="EconomicFxValuation")
        assert q15["cut"]["commit_seq"] == "15"
        assert q15["fx_valuation"]["summary"]["evaluated_total"] == "90"
        assert q15["fx_valuation"]["summary"]["gate_status"] == "AdmissibleWithinCap"
        r2_row = next(r for r in q15["fx_valuation"]["revisions"] if r["revision"] == "2")
        assert r2_row["coverage_status"] == "RetiredBySupersession"
        write_pretty(out / "e_cut15_fx_valuation.json", q15)

        # Stale r1 certificate for beta must fail IdentityConflict at cut 15
        beta_stale_r1 = sess.ewire("E", "release-beta-stale-r1", release_req("beta", beta_cert_r1), expected="Error")
        assert beta_stale_r1["error"].startswith("IdentityConflict："), beta_stale_r1

        # 8. E cut 16: ReleaseExact(beta) with rev=3 + retired rev=2 + cut 15
        beta_cert_r3 = build_fx_certificate_from_query(cfg["sid"], cfg["gen"], cfg["fin_data"], beta_plan, grants["beta"], q15)
        assert_no_fx_placeholders(beta_cert_r3)
        rel_beta = sess.ewire("E", "release-beta", release_req("beta", beta_cert_r3), expected="ReleasedExactReceipt")
        assert rel_beta["cut"]["commit_seq"] == "16"
        cmd_beta = rel_beta["record"]["command"]
        assert_no_fx_placeholders(cmd_beta)
        assert any(
            d.startswith(f"fx-quote:{MARKET_NS}|1|TEST-FX/TEST-CASH|fx-quote-007@rev=3;")
            and "supersedes=2;" in d
            and f"raw_sha256={EXPECTED_FIXTURE_SHA256['fx-r3.json']}" in d
            for d in cmd_beta["certificate"]["market_dependencies"]
        ), cmd_beta["certificate"]["market_dependencies"]
        assert any(
            e.startswith(f"fx-retired:{MARKET_NS}|1|TEST-FX/TEST-CASH|fx-quote-007@rev=2:retired_by_rev=3:evidence_id=ev-retire-r2:")
            for e in cmd_beta["certificate"]["conditions"][0]["evidence_refs"]
        ), cmd_beta["certificate"]["conditions"][0]["evidence_refs"]
        write_pretty(out / "receipt_beta_cut16.json", rel_beta)
        write_pretty(out / "cmd_beta_cut16.json", cmd_beta)

        # Same real X (same static x-profile/3!) advances bar 2 and AcceptExacts cmd-beta
        sess.xwire("bar-2", "AdvanceBar", make_bar(2), expected="SimulationBatch")
        x_acc_beta = sess.xwire("accept-beta", "AcceptExact", cmd_beta, expected="ExactCommandState")
        assert x_acc_beta["state"] == "Accepted", x_acc_beta

        # 9. E cut 17: dynamic Reserve(slot-gamma) -> 95/100
        res_gamma = sess.ewire(
            "E",
            "reserve-gamma",
            {
                "op": "Reserve",
                "slot_id": "slot-gamma",
                "request_set_hash": digest(cfg["slots"]["slot-gamma"]["applicants"]),
                "writer_epoch": "1",
            },
            expected="ReserveReceipt",
        )
        assert res_gamma["cut"]["commit_seq"] == "17"
        q17 = sess.ewire("E", "q-cut17", {"op": "QueryFxValuation", "as_known_ns": None, "cut": None}, expected="EconomicFxValuation")
        assert q17["cut"]["commit_seq"] == "17"
        assert q17["fx_valuation"]["summary"]["evaluated_total"] == "95"
        assert q17["fx_valuation"]["summary"]["gate_status"] == "AdmissibleWithinCap"
        write_pretty(out / "e_cut17_fx_valuation.json", q17)

        # 10. Real #1416 S3 gap probe: send RequestConditionalExecution directly to real S3
        #     (NO forged S ExecuteCommitted receipt!)
        s3_cond_req_payload = {
            "op": "RequestConditionalExecution",
            "command_id": cmd_alpha["command_id"],
            "command_hash": rel_alpha["record"]["command_hash"],
            "release_receipt_id": rel_alpha["receipt_key"],
            "command": cmd_alpha,
        }
        raw_s3_req, raw_s3_rep, s3_gap_rep = sess.swire("probe-1416-s3-cond-exec", s3_cond_req_payload)
        assert s3_gap_rep.get("payload", s3_gap_rep).get("ok") is False, s3_gap_rep
        assert "SchemaUnsupported" in str(s3_gap_rep), s3_gap_rep
        (out / "s3_gap_probe.request.wire").write_bytes(raw_s3_req)
        (out / "s3_gap_probe.reply.wire").write_bytes(raw_s3_rep)

        # Also probe real X AdvanceBar(close_changes=[alpha]) against real S3 socket (must fail closed, 0 fills)
        order = alpha_change["order"]
        local_change = {
            "kind": "submit",
            "order": {
                **order,
                "revision": int(order["revision"]),
                "quantity": int(order["quantity"]),
                "kind": {"kind": "limit", "price": int(order["kind"]["price"])},
            },
        }
        x_exec_against_real_s3 = sess.xwire(
            "probe-x-exec-real-s3", "AdvanceBar", make_bar(3, [local_change]), expected="Error"
        )
        with closing(sqlite3.connect(cfg["x_db"].as_uri() + "?mode=ro", uri=True)) as xc:
            x_accepted_cnt = xc.execute("SELECT count(*) FROM x_exact_commands").fetchone()[0]
            x_observed_cnt = xc.execute(
                "SELECT count(*) FROM x_exact_commands WHERE state='Observed'"
            ).fetchone()[0]
        assert x_accepted_cnt == 2 and x_observed_cnt == 0, (x_accepted_cnt, x_observed_cnt)

        s3_gap_doc = {
            "issue": "#1416",
            "s_protocol_revision": "s-session/3",
            "forged_s_receipt": False,
            "direct_s3_probe_op": "RequestConditionalExecution",
            "direct_s3_reply": s3_gap_rep,
            "x_exec_against_real_s3_error": x_exec_against_real_s3["error"],
            "x_accepted_commands": x_accepted_cnt,
            "x_observed_executions": x_observed_cnt,
            "exact_gap_summary": (
                "s_structure_session (s-session/3) currently implements only `ready`, `receipt`, and `ingest`; "
                "it rejects `RequestConditionalExecution` with `SchemaUnsupported`. "
                "Real S execution eligibility consumption belongs to #1416 and is not forged here."
            ),
        }
        write_pretty(out / "s3_gap_probe.json", s3_gap_doc)

        # 11. S3 SQLite raw_history market mapping + relevance vs irrelevance scope verification
        s3_rows = read_s3_raw_history(cfg["sdb"])
        s3_by_key_rev = {(r["identity_key"], r["revision"]): r for r in s3_rows}
        fx_chain = f"{MARKET_NS}|1|TEST-FX/TEST-CASH|fx-quote-007"
        unrel_chain = f"{MARKET_NS}|1|OTHER-FX/TEST-CASH|fx-quote-unrelated-999"
        for rev_num, fname in [("1", "fx-r1.json"), ("2", "fx-r2.json"), ("3", "fx-r3.json")]:
            row = s3_by_key_rev[(fx_chain, rev_num)]
            assert row["raw_sha256"] == EXPECTED_FIXTURE_SHA256[fname], (rev_num, row)
            assert row["source_coord"] == "70"
        assert (unrel_chain, "1") in s3_by_key_rev and (unrel_chain, "2") in s3_by_key_rev

        alpha_s_cond = next(c for c in cmd_alpha["certificate"]["conditions"] if c["condition_id"] == "execute-committed/1")
        beta_s_cond = next(c for c in cmd_beta["certificate"]["conditions"] if c["condition_id"] == "execute-committed/1")
        relevance_matrix = {
            "fx_r1_vs_cmd_alpha": matches_invalidation_sources(alpha_s_cond["invalidation_sources"], fx_chain, 1),
            "fx_r2_vs_cmd_alpha": matches_invalidation_sources(alpha_s_cond["invalidation_sources"], fx_chain, 2),
            "fx_r3_vs_cmd_alpha": matches_invalidation_sources(alpha_s_cond["invalidation_sources"], fx_chain, 3),
            "unrelated_r1_vs_cmd_alpha": matches_invalidation_sources(alpha_s_cond["invalidation_sources"], unrel_chain, 1),
            "unrelated_r2_vs_cmd_alpha": matches_invalidation_sources(alpha_s_cond["invalidation_sources"], unrel_chain, 2),
            "fx_r3_vs_cmd_beta": matches_invalidation_sources(beta_s_cond["invalidation_sources"], fx_chain, 3),
            "unrelated_r1_vs_cmd_beta": matches_invalidation_sources(beta_s_cond["invalidation_sources"], unrel_chain, 1),
            "unrelated_r2_vs_cmd_beta": matches_invalidation_sources(beta_s_cond["invalidation_sources"], unrel_chain, 2),
        }
        assert relevance_matrix == {
            "fx_r1_vs_cmd_alpha": False,
            "fx_r2_vs_cmd_alpha": True,
            "fx_r3_vs_cmd_alpha": True,
            "unrelated_r1_vs_cmd_alpha": False,
            "unrelated_r2_vs_cmd_alpha": False,
            "fx_r3_vs_cmd_beta": False,
            "unrelated_r1_vs_cmd_beta": False,
            "unrelated_r2_vs_cmd_beta": False,
        }, relevance_matrix

        market_mapping = {
            "session_id": cfg["sid"],
            "session_generation": cfg["gen"],
            "source_namespace": MARKET_NS,
            "source_epoch": MARKET_EPOCH,
            "relevant_chain_id": fx_chain,
            "unrelated_chain_id": unrel_chain,
            "s3_raw_history": [
                {k: v for k, v in r.items() if k != "raw_text"} for r in s3_rows
            ],
            "e_to_s3_alignment": {
                "cmd_alpha_cut11": {
                    "command_id": cmd_alpha["command_id"],
                    "e_cut": rel_alpha["cut"],
                    "bound_e_prev_cut": q10["cut"],
                    "e_fact_key": r1_fk,
                    "s3_receipt_id": s3_by_key_rev[(fx_chain, "1")]["receipt_id"],
                    "s3_seq": s3_by_key_rev[(fx_chain, "1")]["seq"],
                    "s3_first_published_generation": s3_by_key_rev[(fx_chain, "1")]["first_published_generation"],
                    "identity_key": fx_chain,
                    "revision": "1",
                    "raw_sha256": s3_by_key_rev[(fx_chain, "1")]["raw_sha256"],
                    "market_dependencies": cmd_alpha["certificate"]["market_dependencies"],
                    "execute_committed_invalidation_sources": alpha_s_cond["invalidation_sources"],
                },
                "cmd_beta_cut16": {
                    "command_id": cmd_beta["command_id"],
                    "e_cut": rel_beta["cut"],
                    "bound_e_prev_cut": q15["cut"],
                    "e_fact_key": r3_fk,
                    "s3_receipt_id": s3_by_key_rev[(fx_chain, "3")]["receipt_id"],
                    "s3_seq": s3_by_key_rev[(fx_chain, "3")]["seq"],
                    "s3_first_published_generation": s3_by_key_rev[(fx_chain, "3")]["first_published_generation"],
                    "identity_key": fx_chain,
                    "revision": "3",
                    "supersedes_revision": "2",
                    "retired_revision_2_s3_receipt_id": s3_by_key_rev[(fx_chain, "2")]["receipt_id"],
                    "retired_revision_2_s3_first_published_generation": s3_by_key_rev[(fx_chain, "2")]["first_published_generation"],
                    "raw_sha256": s3_by_key_rev[(fx_chain, "3")]["raw_sha256"],
                    "market_dependencies": cmd_beta["certificate"]["market_dependencies"],
                    "execute_committed_invalidation_sources": beta_s_cond["invalidation_sources"],
                },
            },
            "relevance_vs_irrelevance_matrix": relevance_matrix,
        }
        write_pretty(out / "market_mapping.json", market_mapping)
        sess.flush_wire_log()
    finally:
        sess.stop()

    # 12. Cold recovery (epoch 1 -> 2, which internally runs full audit) + X read-only inspection
    rec_e = run_cli(
        [
            str(bins / "e_economic_session"),
            "recover",
            "--manifest",
            str(cfg["manifest_path"]),
            "--db",
            cfg["e_node"]["db"],
        ]
    )
    assert rec_e.returncode == 0, (rec_e.stdout, rec_e.stderr)
    rec_e_doc = json.loads(rec_e.stdout)
    assert rec_e_doc["kind"] == "Recovered" and rec_e_doc["writer_epoch"] == "2", rec_e_doc

    for cid in ("alpha", "beta", "gamma"):
        rec_b = run_cli(
            [
                str(bins / "b_chong_session"),
                "recover",
                "--manifest",
                str(cfg["manifest_path"]),
                "--chong",
                cid,
                "--db",
                cfg["b_nodes"][cid]["db"],
            ]
        )
        assert rec_b.returncode == 0, (cid, rec_b.stdout, rec_b.stderr)
        rec_b_doc = json.loads(rec_b.stdout)
        assert rec_b_doc["kind"] == "Recovered" and rec_b_doc["writer_epoch"] == "2", (cid, rec_b_doc)

    x_hist = run_cli([str(bins / "x_execution_session"), "query-history", "--db", str(cfg["x_db"])])
    assert x_hist.returncode == 0, (x_hist.stdout, x_hist.stderr)
    write_pretty(out / "x_query_history.json", json.loads(x_hist.stdout))

    expected_x_rows = [
        ("cmd-alpha", "ExecutionRequested", rel_alpha, cmd_alpha),
        ("cmd-beta", "Accepted", rel_beta, cmd_beta),
    ]
    with closing(sqlite3.connect(cfg["x_db"].as_uri() + "?mode=ro", uri=True)) as xc:
        for cmd_id, expected_state, rel_rcpt, expected_cmd in expected_x_rows:
            xcmd = run_cli(
                [
                    str(bins / "x_execution_session"),
                    "query-command",
                    "--db",
                    str(cfg["x_db"]),
                    "--command-id",
                    cmd_id,
                ]
            )
            assert xcmd.returncode == 0, (cmd_id, xcmd.stdout, xcmd.stderr)
            xcmd_doc = json.loads(xcmd.stdout)
            write_pretty(out / f"x_query_{cmd_id}.json", xcmd_doc)
            assert xcmd_doc["state"] == expected_state, (cmd_id, expected_state, xcmd_doc)
            assert xcmd_doc.get("execute_evidence") is None, (cmd_id, xcmd_doc)
            assert xcmd_doc.get("has_execute_evidence") is False, (cmd_id, xcmd_doc)
            assert xcmd_doc["profile_revision"] == "x-execution-profile/3", (cmd_id, xcmd_doc)
            assert xcmd_doc["condition_audit_policy"] == "verified_current_condition_semantics_and_completeness", (cmd_id, xcmd_doc)
            assert xcmd_doc["condition_audit_unproven"] == [], (cmd_id, xcmd_doc)
            assert xcmd_doc["causal_refs"][0]["command_hash"] == rel_rcpt["record"]["command_hash"], (cmd_id, xcmd_doc)
            assert xcmd_doc["causal_refs"][0]["receipt_id"] == rel_rcpt["receipt_key"], (cmd_id, xcmd_doc)
            row = xc.execute(
                "SELECT command, state, execute_evidence FROM x_exact_commands WHERE id = ?",
                (cmd_id,),
            ).fetchone()
            assert row is not None, cmd_id
            assert canonical(json.loads(row[0])) == canonical(expected_cmd), (cmd_id, "X stored command mismatch")
            assert row[1] == expected_state, (cmd_id, row[1])
            assert row[2] is None, (cmd_id, row[2])

    # Restart standalone E at epoch 2 and verify historical cut 12 (110/100), current cut 17 (95/100), and QueryReleasedExact
    e_ep2_sock = str(run_dir / "e.sock")
    if Path(e_ep2_sock).exists():
        Path(e_ep2_sock).unlink()
    e_ep2_err = run_dir / "e-ep2.stderr"
    with (run_dir / "e-ep2.stdout").open("wb") as eo, e_ep2_err.open("wb") as ee:
        e_ep2 = subprocess.Popen(
            [
                str(bins / "e_economic_session"),
                "serve",
                "--manifest",
                str(cfg["manifest_path"]),
                "--db",
                cfg["e_node"]["db"],
                "--epoch",
                "2",
            ],
            stdin=subprocess.DEVNULL,
            stdout=eo,
            stderr=ee,
        )
        try:
            wait_ready(e_ep2, e_ep2_sock, "E-epoch2", e_ep2_err)
            q_ep2_cur = sess.ewire("E", "q-ep2-cur", {"op": "QueryFxValuation", "as_known_ns": None, "cut": None}, expected="EconomicFxValuation", producer_epoch="2")
            assert q_ep2_cur["cut"] == q17["cut"]
            assert q_ep2_cur["fx_valuation"]["summary"]["evaluated_total"] == "95"

            q_ep2_12 = sess.ewire("E", "q-ep2-hist12", {"op": "QueryFxValuation", "as_known_ns": None, "cut": q12["cut"]}, expected="EconomicFxValuation", producer_epoch="2")
            assert q_ep2_12["cut"] == q12["cut"]
            assert q_ep2_12["fx_valuation"]["summary"]["evaluated_total"] == "110"

            qa = sess.ewire(
                "E",
                "q-ep2-alpha",
                {"op": "QueryCommand", "command_id": "cmd-alpha", "cut": None, "as_known_ns": None},
                expected="EconomicCommand",
                producer_epoch="2",
            )
            assert canonical(qa["record"]["command"]) == canonical(cmd_alpha)
            qb = sess.ewire(
                "E",
                "q-ep2-beta",
                {"op": "QueryCommand", "command_id": "cmd-beta", "cut": None, "as_known_ns": None},
                expected="EconomicCommand",
                producer_epoch="2",
            )
            assert canonical(qb["record"]["command"]) == canonical(cmd_beta)
        finally:
            e_ep2.terminate()
            e_ep2.wait(timeout=8)

    # Assemble #1416 handoff bundle
    handoff = {
        "schema_revision": "ce-s07-handoff-to-1416/1",
        "finance_schema_revision": "tb03b-finance/6",
        "fx_valuation_schema_revision": "fx-valuation/2",
        "x_profile_revision": "x-execution-profile/3",
        "s_protocol_revision": "s-session/3",
        "session_id": cfg["sid"],
        "session_generation": cfg["gen"],
        "model_ref": cmd_alpha["model_ref"],
        "cuts": {
            "r1_pre_release_cut10": q10["cut"],
            "alpha_release_cut11": rel_alpha["cut"],
            "r2_overcap_cut12": q12["cut"],
            "r3_retired_r2_cut15": q15["cut"],
            "beta_release_cut16": rel_beta["cut"],
            "gamma_reserve_cut17": q17["cut"],
        },
        "released_commands": [
            {
                "command_id": cmd_alpha["command_id"],
                "command_hash": rel_alpha["record"]["command_hash"],
                "release_receipt_key": rel_alpha["receipt_key"],
                "release_cut": rel_alpha["cut"],
                "x_accept_state": x_acc_alpha["state"],
                "command": cmd_alpha,
            },
            {
                "command_id": cmd_beta["command_id"],
                "command_hash": rel_beta["record"]["command_hash"],
                "release_receipt_key": rel_beta["receipt_key"],
                "release_cut": rel_beta["cut"],
                "x_accept_state": x_acc_beta["state"],
                "command": cmd_beta,
            },
        ],
        "market_mapping": market_mapping,
        "s3_gap_for_1416": s3_gap_doc,
    }
    write_pretty(out / "handoff_1416.json", handoff)

    return {
        "status": "PASS",
        "session_id": cfg["sid"],
        "cut10_eval": "90/100",
        "cut11_alpha_release": rel_alpha["cut"],
        "cut11_alpha_command_hash": rel_alpha["record"]["command_hash"],
        "cut11_alpha_receipt_key": rel_alpha["receipt_key"],
        "cut12_overcap_eval": "110/100",
        "cut12_original_receipt_priority_same_and_new_msg": True,
        "cut12_beta_overcap_error": beta_overcap["error"],
        "cut12_gamma_overcap_error": gamma_overcap["error"],
        "cut15_restored_eval": "90/100",
        "cut16_beta_release": rel_beta["cut"],
        "cut16_beta_command_hash": rel_beta["record"]["command_hash"],
        "cut16_beta_receipt_key": rel_beta["receipt_key"],
        "cut17_gamma_reserve_eval": "95/100",
        "pre_release_negative_controls": neg_results,
        "x_negative_controls": {
            "early_bar0": x_early["error"],
            "forged_model_ref": x_forged_model["error"],
            "placeholder_cert": x_tampered_ph["error"],
            "e_authority_mismatch": x_tampered_e["error"],
        },
        "x_accept_states": {"cmd-alpha": x_acc_alpha["state"], "cmd-beta": x_acc_beta["state"]},
        "relevance_matrix": relevance_matrix,
        "s3_gap": s3_gap_doc,
        "epoch2_recovery_and_audits": "PASS",
    }


def run_arm2_unrelated_revision_control(bins: Path, out: Path) -> dict:
    """Proves unrelated market revision in S3 does not block healthy empty-FX-boundary chong,
    while direct unattributed E capture remains conservatively guarded at account:*."""
    run_dir = out / "arm2_unrelated_healthy_chong"
    x_model = {**base_sim_model(), "symbol": "TEST"}
    empty_ob_bytes = canonical(
        {
            "schema_revision": "testonly-fx-obligation-input/1",
            "kind": "TestOnly",
            "source_id": "testonly-ce-s07-empty-boundary",
            "source_epoch": "1",
            "obligations": [],
        }
    )
    unrel_r1_utf8 = make_unrelated_quote("1", None, "5")
    unrel_r2_utf8 = make_unrelated_quote("2", "1", "9")

    msgs = {
        "imp-base": "1",
        "cap-open-alpha": "1",
        "apply-open-alpha": "1",
        "bind-alpha": "1",
        "prep-alpha": "1",
        "reserve-main": "1",
        "commit-alpha": "1",
        "dispatch-alpha": "1",
        "q-pre": "1",
        "release-alpha": "2",
        "cap-unrel-e": "3",
        "res-unrel-e": "3",
        "q-unrel-e": "3",
    }
    s_clock = {
        "prefix-1": {"accept_ns": "10", "attempts": [{"begin_ns": "11", "commit_ns": "12"}]},
        "unrel-r1": {"accept_ns": "20", "attempts": [{"begin_ns": "21", "commit_ns": "22"}]},
        "unrel-r2": {"accept_ns": "30", "attempts": [{"begin_ns": "31", "commit_ns": "32"}]},
    }
    cfg = build_session_artifacts(
        run_dir,
        session_id="ce-s07-unrelated-healthy",
        chongs=["alpha"],
        x_model=x_model,
        fx_obligations_bytes=empty_ob_bytes,
        clock_messages=msgs,
        recover_bars=["4"],
        s_clock_events=s_clock,
        s_socket_for_x=str(run_dir / "structure.sock"),
        baseline_amount="20",
        cap_amount="100",
    )

    sess = LiveProductionSession("arm2", bins, run_dir, cfg)
    sess.start()
    try:
        sess.s_ingest_prefix("prefix-1", 10, "4")
        sess.s_ingest_quote("unrel-r1", unrel_r1_utf8)
        sess.s_ingest_quote("unrel-r2", unrel_r2_utf8)

        sess.ewire("E", "imp-base", {"op": "ImportResponsibility", "responsibility_id": "r-base", "writer_epoch": "1"}, expected="ResponsibilityImportedReceipt")
        cap = sess.ewire(
            "E",
            "cap-open-alpha",
            {"op": "CaptureExternal", "raw_utf8": cfg["openers"]["alpha"], "json_pointer": "/events/0", "token": "tok-opening-alpha", "source_event_time": None},
            expected="Recorded",
        )
        sess.ewire(
            "B:alpha",
            "apply-open-alpha",
            {"op": "ApplyAllocation", "fact_key": cap["fact_key"], "allocation_id": "allocation-alpha", "expected_fact_hash": cap["fact_hash"]},
            expected="Applied",
        )
        sess.ewire("B:alpha", "bind-alpha", cfg["voice_bindings"]["alpha"], expected="VoiceBound")
        sess.ewire("B:alpha", "prep-alpha", {"op": "PrepareDecision", "decision_id": "alpha", "plan_hash": digest(cfg["plans"]["alpha"]), "writer_epoch": "1"}, expected="PreparedReceipt")
        res = sess.ewire("E", "reserve-main", {"op": "Reserve", "slot_id": "slot-main", "request_set_hash": digest(cfg["slots"]["slot-main"]["applicants"]), "writer_epoch": "1"}, expected="ReserveReceipt")
        grant_id = res["record"]["grants"][0]["grant_id"]
        sess.ewire("B:alpha", "commit-alpha", {"op": "CommitDecision", "decision_id": "alpha", "plan_hash": digest(cfg["plans"]["alpha"]), "grant_id": grant_id, "writer_epoch": "1"}, expected="LocalCommitReceipt")
        sess.ewire("E", "dispatch-alpha", {"op": "MakeDispatchable", "decision_id": "alpha", "plan_hash": digest(cfg["plans"]["alpha"]), "writer_epoch": "1"}, expected="DispatchableReceipt")
        q_pre = sess.ewire("E", "q-pre", {"op": "QueryFxValuation", "as_known_ns": None, "cut": None}, expected="EconomicFxValuation")
        assert q_pre["fx_valuation"]["summary"]["evaluated_total"] == "50"  # baseline 20 + alpha 30
        assert q_pre["fx_valuation"]["summary"]["gate_status"] == "AdmissibleWithinCap"

        cert = build_fx_certificate_from_query(cfg["sid"], cfg["gen"], cfg["fin_data"], cfg["plans"]["alpha"], grant_id, q_pre)
        assert_no_fx_placeholders(cert)
        assert cert["market_dependencies"][0].startswith("fx-boundary-empty:")
        rel = sess.ewire(
            "E",
            "release-alpha",
            {
                "op": "ReleaseExact",
                "decision_id": "alpha",
                "command_id": "cmd-alpha",
                "plan_hash": digest(change_for_plan(cfg["plans"]["alpha"])),
                "certificate": cert,
                "x_id": "X",
                "x_epoch": "1",
                "writer_epoch": "1",
            },
            expected="ReleasedExactReceipt",
        )
        cmd = rel["record"]["command"]
        sess.xwire("bar-0", "AdvanceBar", make_bar(0), expected="SimulationBatch")
        sess.xwire("bar-1", "AdvanceBar", make_bar(1), expected="SimulationBatch")
        x_acc = sess.xwire("accept-healthy", "AcceptExact", cmd, expected="ExactCommandState")
        assert x_acc["state"] == "Accepted"

        # Conservative E unknown-domain guard: direct E capture of unattributed OTHER-FX stays account:*
        cap_unrel = sess.ewire(
            "E",
            "cap-unrel-e",
            {"op": "CaptureExternal", "raw_utf8": unrel_r1_utf8, "json_pointer": "", "token": "unrel-e-1", "source_event_time": "71"},
            expected="Recorded",
            source=cfg["src_market"],
        )
        res_unrel = sess.ewire(
            "E",
            "res-unrel-e",
            {
                "op": "ResolveEvidence",
                "evidence_id": "ev-unrel-should-fail",
                "covered": [{"fact_key": cap_unrel["fact_key"], "token": "unrel-e-1", "fact_hash": cap_unrel["fact_hash"]}],
                "frontier": {"source_namespace": MARKET_NS, "source_epoch": MARKET_EPOCH, "cursor": "71"},
                "dependency_version": "unrel/1",
            },
            expected="Error",
            source=cfg["src_market"],
        )
        assert res_unrel["error"].startswith("MissingDependency："), res_unrel
        q_unrel = sess.ewire("E", "q-unrel-e", {"op": "QueryFxValuation", "as_known_ns": None, "cut": None}, expected="EconomicFxValuation")
        assert q_unrel["fx_valuation"]["summary"]["gate_status"] == "BlockedUnverifiable"
        assert q_unrel["fx_valuation"]["revisions"][0]["initial_pending_scope"] == "account:*"
        sess.flush_wire_log()

        return {
            "status": "PASS",
            "healthy_chong_release_cut": rel["cut"],
            "healthy_chong_market_dependencies": cmd["certificate"]["market_dependencies"],
            "healthy_chong_x_accept_state": x_acc["state"],
            "s3_unrelated_revisions_ingested": 2,
            "direct_unattributed_e_capture_scope": "account:*",
            "direct_unattributed_e_resolve_error": res_unrel["error"],
            "direct_unattributed_e_gate_status": q_unrel["fx_valuation"]["summary"]["gate_status"],
        }
    finally:
        sess.stop()


def run_arm3_pure_non_fx_legacy_and_config_guards(bins: Path, fixtures: Path, out: Path) -> dict:
    run_dir = out / "arm3_pure_nonfx_legacy"
    x_model = {**base_sim_model(), "symbol": "TEST"}
    msgs = {
        "imp-base": "1",
        "cap-open-alpha": "1",
        "apply-open-alpha": "1",
        "bind-alpha": "1",
        "prep-alpha": "1",
        "reserve-main": "1",
        "commit-alpha": "1",
        "dispatch-alpha": "1",
        "view-nonfx": "1",
        "release-alpha": "2",
    }
    s_clock = {
        "prefix-1": {"accept_ns": "10", "attempts": [{"begin_ns": "11", "commit_ns": "12"}]},
    }
    cfg = build_session_artifacts(
        run_dir,
        session_id="ce-s07-nonfx-legacy-v6",
        chongs=["alpha"],
        x_model=x_model,
        fx_obligations_bytes=None,
        clock_messages=msgs,
        recover_bars=["3"],
        s_clock_events=s_clock,
        s_socket_for_x=str(run_dir / "structure.sock"),
        baseline_amount="20",
        cap_amount="100",
    )

    sess = LiveProductionSession("arm3", bins, run_dir, cfg)
    sess.start()
    try:
        sess.ewire("E", "imp-base", {"op": "ImportResponsibility", "responsibility_id": "r-base", "writer_epoch": "1"}, expected="ResponsibilityImportedReceipt")
        cap = sess.ewire(
            "E",
            "cap-open-alpha",
            {"op": "CaptureExternal", "raw_utf8": cfg["openers"]["alpha"], "json_pointer": "/events/0", "token": "tok-opening-alpha", "source_event_time": None},
            expected="Recorded",
        )
        sess.ewire(
            "B:alpha",
            "apply-open-alpha",
            {"op": "ApplyAllocation", "fact_key": cap["fact_key"], "allocation_id": "allocation-alpha", "expected_fact_hash": cap["fact_hash"]},
            expected="Applied",
        )
        sess.ewire("B:alpha", "bind-alpha", cfg["voice_bindings"]["alpha"], expected="VoiceBound")
        sess.ewire("B:alpha", "prep-alpha", {"op": "PrepareDecision", "decision_id": "alpha", "plan_hash": digest(cfg["plans"]["alpha"]), "writer_epoch": "1"}, expected="PreparedReceipt")
        res = sess.ewire("E", "reserve-main", {"op": "Reserve", "slot_id": "slot-main", "request_set_hash": digest(cfg["slots"]["slot-main"]["applicants"]), "writer_epoch": "1"}, expected="ReserveReceipt")
        grant_id = res["record"]["grants"][0]["grant_id"]
        sess.ewire("B:alpha", "commit-alpha", {"op": "CommitDecision", "decision_id": "alpha", "plan_hash": digest(cfg["plans"]["alpha"]), "grant_id": grant_id, "writer_epoch": "1"}, expected="LocalCommitReceipt")
        sess.ewire("E", "dispatch-alpha", {"op": "MakeDispatchable", "decision_id": "alpha", "plan_hash": digest(cfg["plans"]["alpha"]), "writer_epoch": "1"}, expected="DispatchableReceipt")
        view = sess.ewire("E", "view-nonfx", {"op": "ReadView", "cut": None, "as_known_ns": None}, expected="EconomicView")
        assert "fx_valuation" not in view["image"], view["image"].keys()

        freeze = cfg["fin_data"]["exact_release"]
        q = cfg["plans"]["alpha"]
        legacy_cert = {
            "rd11_policy": freeze["rd11_policy"],
            "responsibility_refs": [grant_id],
            "structure_dependencies": [f"{q['s_ref']['object_id']}@{q['s_ref']['object_hash']}"],
            "market_dependencies": freeze["market_dependencies"],
            "rule_revision": freeze["rule_revision"],
            "conditions": freeze["conditions"],
        }
        rel = sess.ewire(
            "E",
            "release-alpha",
            {
                "op": "ReleaseExact",
                "decision_id": "alpha",
                "command_id": "cmd-alpha",
                "plan_hash": digest(change_for_plan(q)),
                "certificate": legacy_cert,
                "x_id": "X",
                "x_epoch": "1",
                "writer_epoch": "1",
            },
            expected="ReleasedExactReceipt",
        )
        cmd = rel["record"]["command"]
        sess.xwire("bar-0", "AdvanceBar", make_bar(0), expected="SimulationBatch")
        sess.xwire("bar-1", "AdvanceBar", make_bar(1), expected="SimulationBatch")
        x_acc = sess.xwire("accept-nonfx", "AcceptExact", cmd, expected="ExactCommandState")
        assert x_acc["state"] == "Accepted"
        sess.flush_wire_log()
    finally:
        sess.stop()

    # Config-level guard negative controls via real e_economic_session init + first ImportResponsibility
    def probe_first_import_error(neg_dir: Path, neg_cfg: dict, label: str) -> str:
        init_res = run_cli(
            [
                str(bins / "e_economic_session"),
                "init",
                "--manifest",
                str(neg_cfg["manifest_path"]),
                "--db",
                neg_cfg["e_node"]["db"],
            ]
        )
        assert init_res.returncode == 0, (label, init_res.stdout, init_res.stderr)
        err_path = neg_dir / "e.stderr"
        with (neg_dir / "e.stdout").open("wb") as eo, err_path.open("wb") as ee:
            proc = subprocess.Popen(
                [
                    str(bins / "e_economic_session"),
                    "serve",
                    "--manifest",
                    str(neg_cfg["manifest_path"]),
                    "--db",
                    neg_cfg["e_node"]["db"],
                    "--epoch",
                    "1",
                ],
                stdin=subprocess.DEVNULL,
                stdout=eo,
                stderr=ee,
            )
            try:
                wait_ready(proc, neg_cfg["e_node"]["socket"], label, err_path)
                payload = {"op": "ImportResponsibility", "responsibility_id": "r-base", "writer_epoch": "1"}
                req = {
                    "schema_revision": "economic-session/1",
                    "session_id": neg_cfg["sid"],
                    "session_generation": neg_cfg["gen"],
                    **neg_cfg["src_fin"],
                    "message_id": "imp-base",
                    "payload_hash": digest(payload),
                    "causal_refs": [],
                    "payload": payload,
                }
                _, _, rep = send_frame(neg_cfg["e_node"]["socket"], req, label=label)
                res = validate_reply(req, rep, producer="E", producer_epoch="1")
                assert res.get("kind") == "Error", (label, res)
                assert res["error"].startswith("Unsupported"), (label, res)
                return res["error"]
            finally:
                proc.terminate()
                proc.wait(timeout=8)

    neg_fx_dir = out / "arm3_neg_fx_v6_v2_with_placeholders"
    neg_fx_cfg = build_session_artifacts(
        neg_fx_dir,
        session_id="ce-s07-neg-fx-v6-v2-placeholder",
        chongs=["alpha"],
        x_model=x_model,
        fx_obligations_bytes=(fixtures / "fx-obligations.json").read_bytes(),
        clock_messages={"imp-base": "1"},
        recover_bars=[],
        s_clock_events=s_clock,
        s_socket_for_x=str(neg_fx_dir / "structure.sock"),
        use_fx_marker_in_input=False,
        finance_schema="tb03b-finance/6",
        fx_schema="fx-valuation/2",
    )
    bad_fx_v6_err = probe_first_import_error(neg_fx_dir, neg_fx_cfg, "neg-fx-v6-v2-placeholders")

    neg_nonfx_dir = out / "arm3_neg_nonfx_v6_with_fx_marker"
    neg_nonfx_cfg = build_session_artifacts(
        neg_nonfx_dir,
        session_id="ce-s07-neg-nonfx-v6-marker",
        chongs=["alpha"],
        x_model=x_model,
        fx_obligations_bytes=None,
        clock_messages={"imp-base": "1"},
        recover_bars=[],
        s_clock_events=s_clock,
        s_socket_for_x=str(neg_nonfx_dir / "structure.sock"),
        use_fx_marker_in_input=True,
        finance_schema="tb03b-finance/6",
    )
    bad_nonfx_v6_err = probe_first_import_error(neg_nonfx_dir, neg_nonfx_cfg, "neg-nonfx-v6-marker")

    neg_fin6_v1_dir = out / "arm3_neg_fin6_fx_v1_with_v2_marker"
    neg_fin6_v1_cfg = build_session_artifacts(
        neg_fin6_v1_dir,
        session_id="ce-s07-neg-fin6-v1-marker",
        chongs=["alpha"],
        x_model=x_model,
        fx_obligations_bytes=(fixtures / "fx-obligations.json").read_bytes(),
        clock_messages={"imp-base": "1"},
        recover_bars=[],
        s_clock_events=s_clock,
        s_socket_for_x=str(neg_fin6_v1_dir / "structure.sock"),
        use_fx_marker_in_input=True,
        finance_schema="tb03b-finance/6",
        fx_schema="fx-valuation/1",
    )
    bad_fin6_v1_marker_err = probe_first_import_error(neg_fin6_v1_dir, neg_fin6_v1_cfg, "neg-fin6-v1-marker")

    neg_fin5_v1_dir = out / "arm3_neg_fin5_fx_v1_with_v2_marker"
    neg_fin5_v1_cfg = build_session_artifacts(
        neg_fin5_v1_dir,
        session_id="ce-s07-neg-fin5-v1-marker",
        chongs=["alpha"],
        x_model=x_model,
        fx_obligations_bytes=(fixtures / "fx-obligations.json").read_bytes(),
        clock_messages={"imp-base": "1"},
        recover_bars=[],
        s_clock_events=s_clock,
        s_socket_for_x=str(neg_fin5_v1_dir / "structure.sock"),
        use_fx_marker_in_input=True,
        finance_schema="tb03b-finance/5",
        fx_schema="fx-valuation/1",
        authorize_x_query=False,
    )
    bad_fin5_marker_err = probe_first_import_error(neg_fin5_v1_dir, neg_fin5_v1_cfg, "neg-fin5-v1-marker")

    neg_fin5_v2_dir = out / "arm3_neg_fin5_with_fx_v2"
    neg_fin5_v2_cfg = build_session_artifacts(
        neg_fin5_v2_dir,
        session_id="ce-s07-neg-fin5-fx-v2",
        chongs=["alpha"],
        x_model=x_model,
        fx_obligations_bytes=(fixtures / "fx-obligations.json").read_bytes(),
        clock_messages={"imp-base": "1"},
        recover_bars=[],
        s_clock_events=s_clock,
        s_socket_for_x=str(neg_fin5_v2_dir / "structure.sock"),
        use_fx_marker_in_input=True,
        finance_schema="tb03b-finance/5",
        fx_schema="fx-valuation/2",
        authorize_x_query=False,
    )
    bad_fin5_v2_init = run_cli(
        [
            str(bins / "e_economic_session"),
            "init",
            "--manifest",
            str(neg_fin5_v2_cfg["manifest_path"]),
            "--db",
            neg_fin5_v2_cfg["e_node"]["db"],
        ]
    )
    assert bad_fin5_v2_init.returncode != 0 and "SchemaUnsupported" in bad_fin5_v2_init.stderr, (
        bad_fin5_v2_init.returncode,
        bad_fin5_v2_init.stderr,
    )

    return {
        "status": "PASS",
        "fx_valuation_absent_in_read_view": True,
        "legacy_release_cut": rel["cut"],
        "legacy_x_accept_state": x_acc["state"],
        "config_guard_fx_v6_v2_with_placeholders_refused": bad_fx_v6_err,
        "config_guard_nonfx_v6_with_fx_marker_refused": bad_nonfx_v6_err,
        "config_guard_fin6_fx_v1_with_v2_marker_refused": bad_fin6_v1_marker_err,
        "config_guard_fin5_fx_v1_with_v2_marker_refused": bad_fin5_marker_err,
        "config_guard_fin5_with_fx_v2_init_refused": bad_fin5_v2_init.stderr.strip(),
    }


def run_arm4_fin5_fx_compat_and_old_db_recovery(bins: Path, fixtures: Path, out: Path) -> dict:
    """Proves unmodified legacy tb03b-finance/5 + fx-valuation/1 (static conditions, NO release-bound marker)
    passes ImportResponsibility, ReleaseExact, overcap original-receipt retry, epoch-2 cold recovery,
    audit, and historical/receipt reread without forcing old callers to add the new marker."""
    run_dir = out / "arm4_fin5_fx_compat"
    ob_bytes = (fixtures / "fx-obligations.json").read_bytes()
    r1_utf8 = (fixtures / "fx-r1.json").read_text(encoding="utf-8")
    r2_utf8 = (fixtures / "fx-r2.json").read_text(encoding="utf-8")
    x_model = {**base_sim_model(), "symbol": "TEST"}

    msgs = {
        "imp-base": "1",
        "imp-fx": "1",
        "cap-r1": "1",
        "res-r1": "1",
        "cap-open-alpha": "1",
        "apply-open-alpha": "1",
        "bind-alpha": "1",
        "prep-alpha": "1",
        "cap-open-beta": "1",
        "apply-open-beta": "1",
        "bind-beta": "1",
        "prep-beta": "1",
        "reserve-main": "1",
        "commit-alpha": "1",
        "commit-beta": "1",
        "dispatch-alpha": "1",
        "dispatch-beta": "1",
        "q-cut9": "1",
        "release-alpha": "2",
        "cap-r2": "3",
        "q-cut11": "3",
        "release-alpha-new-msg": "3",
        "release-beta-overcap": "3",
        "q-ep2-cur": "4",
        "q-ep2-hist9": "4",
        "q-ep2-cmd": "4",
    }
    s_clock = {
        "prefix-1": {"accept_ns": "10", "attempts": [{"begin_ns": "11", "commit_ns": "12"}]},
    }
    cfg = build_session_artifacts(
        run_dir,
        session_id="ce-s07-fin5-fx-compat",
        chongs=["alpha", "beta"],
        x_model=x_model,
        fx_obligations_bytes=ob_bytes,
        clock_messages=msgs,
        recover_bars=["4"],
        s_clock_events=s_clock,
        s_socket_for_x=str(run_dir / "structure.sock"),
        baseline_amount="0",
        cap_amount="100",
        use_fx_marker_in_input=False,
        finance_schema="tb03b-finance/5",
        fx_schema="fx-valuation/1",
        authorize_x_query=False,
    )
    assert cfg["fin_data"]["exact_release"]["market_dependencies"] == ["TestOnly-market/nonfx-legacy-v6"]

    # Standalone E + B:alpha + B:beta (no X on FIN/5)
    for cmd_args, label in [
        ([str(bins / "e_economic_session"), "init", "--manifest", str(cfg["manifest_path"]), "--db", cfg["e_node"]["db"]], "init-E"),
        ([str(bins / "b_chong_session"), "init", "--manifest", str(cfg["manifest_path"]), "--chong", "alpha", "--db", cfg["b_nodes"]["alpha"]["db"]], "init-B-alpha"),
        ([str(bins / "b_chong_session"), "init", "--manifest", str(cfg["manifest_path"]), "--chong", "beta", "--db", cfg["b_nodes"]["beta"]["db"]], "init-B-beta"),
    ]:
        res = run_cli(cmd_args)
        assert res.returncode == 0, (label, res.stdout, res.stderr)

    wire_log: list[dict] = []

    def ewire_direct(domain: str, msg_id: str, payload: dict, *, expected: str, source: dict | None = None, producer_epoch: str = "1") -> dict:
        sock = cfg["e_node"]["socket"] if domain == "E" else cfg["b_nodes"][domain.split(":", 1)[1]]["socket"]
        src = source if source is not None else cfg["src_fin"]
        req = {
            "schema_revision": "economic-session/1",
            "session_id": cfg["sid"],
            "session_generation": cfg["gen"],
            **src,
            "message_id": msg_id,
            "payload_hash": digest(payload),
            "causal_refs": [],
            "payload": payload,
        }
        _, _, rep = send_frame(sock, req, wire_log=wire_log, label=f"arm4:{domain}:{msg_id}")
        res = validate_reply(req, rep, producer=domain, producer_epoch=producer_epoch)
        assert res.get("kind") == expected, (domain, msg_id, expected, res)
        return res

    procs: list[tuple[subprocess.Popen, object, object]] = []

    def spawn(cmd_args: list[str], sock: str, tag: str) -> None:
        out_f = (run_dir / f"{tag}.stdout").open("wb")
        err_p = run_dir / f"{tag}.stderr"
        err_f = err_p.open("wb")
        p = subprocess.Popen(cmd_args, stdin=subprocess.DEVNULL, stdout=out_f, stderr=err_f)
        procs.append((p, out_f, err_f))
        wait_ready(p, sock, f"arm4:{tag}", err_p)

    try:
        spawn([str(bins / "e_economic_session"), "serve", "--manifest", str(cfg["manifest_path"]), "--db", cfg["e_node"]["db"], "--epoch", "1"], cfg["e_node"]["socket"], "e-ep1")
        for cid in ("alpha", "beta"):
            spawn([str(bins / "b_chong_session"), "serve", "--manifest", str(cfg["manifest_path"]), "--chong", cid, "--db", cfg["b_nodes"][cid]["db"], "--epoch", "1", "--e-epoch", "1"], cfg["b_nodes"][cid]["socket"], f"b-{cid}-ep1")

        # 1. Legacy FIN/5+FX first ImportResponsibility MUST succeed (regression fix proof)
        imp_base = ewire_direct("E", "imp-base", {"op": "ImportResponsibility", "responsibility_id": "r-base", "writer_epoch": "1"}, expected="ResponsibilityImportedReceipt")
        assert imp_base["cut"]["commit_seq"] == "1"

        ewire_direct("E", "imp-fx", {"op": "ImportFxResponsibility", "responsibility_id": "ob-fx-unclosed-20", "writer_epoch": "1"}, expected="FxResponsibilityImportedReceipt")
        c3 = ewire_direct("E", "cap-r1", {"op": "CaptureExternal", "raw_utf8": r1_utf8, "json_pointer": "", "token": "fx-r1", "source_event_time": "70"}, expected="Recorded", source=cfg["src_market"])
        ewire_direct(
            "E",
            "res-r1",
            {
                "op": "ResolveEvidence",
                "evidence_id": "ev-r1",
                "covered": [{"fact_key": c3["fact_key"], "token": "fx-r1", "fact_hash": c3["fact_hash"]}],
                "frontier": {"source_namespace": MARKET_NS, "source_epoch": MARKET_EPOCH, "cursor": "70"},
                "dependency_version": "fin5-r1/1",
            },
            expected="Resolved",
            source=cfg["src_market"],
        )

        for cid in ("alpha", "beta"):
            cap = ewire_direct("E", f"cap-open-{cid}", {"op": "CaptureExternal", "raw_utf8": cfg["openers"][cid], "json_pointer": "/events/0", "token": f"tok-opening-{cid}", "source_event_time": None}, expected="Recorded")
            ewire_direct(f"B:{cid}", f"apply-open-{cid}", {"op": "ApplyAllocation", "fact_key": cap["fact_key"], "allocation_id": f"allocation-{cid}", "expected_fact_hash": cap["fact_hash"]}, expected="Applied")
            ewire_direct(f"B:{cid}", f"bind-{cid}", cfg["voice_bindings"][cid], expected="VoiceBound")
            ewire_direct(f"B:{cid}", f"prep-{cid}", {"op": "PrepareDecision", "decision_id": cid, "plan_hash": digest(cfg["plans"][cid]), "writer_epoch": "1"}, expected="PreparedReceipt")

        res_main = ewire_direct("E", "reserve-main", {"op": "Reserve", "slot_id": "slot-main", "request_set_hash": digest(cfg["slots"]["slot-main"]["applicants"]), "writer_epoch": "1"}, expected="ReserveReceipt")
        grants = {g["decision_id"]: g["grant_id"] for g in res_main["record"]["grants"]}
        for cid in ("alpha", "beta"):
            ewire_direct(f"B:{cid}", f"commit-{cid}", {"op": "CommitDecision", "decision_id": cid, "plan_hash": digest(cfg["plans"][cid]), "grant_id": grants[cid], "writer_epoch": "1"}, expected="LocalCommitReceipt")
        for cid in ("alpha", "beta"):
            ewire_direct("E", f"dispatch-{cid}", {"op": "MakeDispatchable", "decision_id": cid, "plan_hash": digest(cfg["plans"][cid]), "writer_epoch": "1"}, expected="DispatchableReceipt")

        q9 = ewire_direct("E", "q-cut9", {"op": "QueryFxValuation", "as_known_ns": None, "cut": None}, expected="EconomicFxValuation")
        assert q9["fx_valuation"]["summary"]["evaluated_total"] == "90"

        freeze = cfg["fin_data"]["exact_release"]
        def legacy_rel_req(cid: str) -> dict:
            q = cfg["plans"][cid]
            cert = {
                "rd11_policy": freeze["rd11_policy"],
                "responsibility_refs": [grants[cid]],
                "structure_dependencies": [f"{q['s_ref']['object_id']}@{q['s_ref']['object_hash']}"],
                "market_dependencies": freeze["market_dependencies"],
                "rule_revision": freeze["rule_revision"],
                "conditions": freeze["conditions"],
            }
            return {
                "op": "ReleaseExact",
                "decision_id": cid,
                "command_id": q["exact"]["command_id"],
                "plan_hash": digest(change_for_plan(q)),
                "certificate": cert,
                "x_id": "X",
                "x_epoch": "1",
                "writer_epoch": "1",
            }

        rel_alpha = ewire_direct("E", "release-alpha", legacy_rel_req("alpha"), expected="ReleasedExactReceipt")
        assert "model_ref" not in rel_alpha["record"]["command"]
        assert rel_alpha["record"]["command"]["certificate"]["market_dependencies"] == ["TestOnly-market/nonfx-legacy-v6"]

        # r2 -> 110/100 overcap: original receipt priority preserved, beta blocked
        ewire_direct("E", "cap-r2", {"op": "CaptureExternal", "raw_utf8": r2_utf8, "json_pointer": "", "token": "fx-r2", "source_event_time": "70"}, expected="Recorded", source=cfg["src_market"])
        q11 = ewire_direct("E", "q-cut11", {"op": "QueryFxValuation", "as_known_ns": None, "cut": None}, expected="EconomicFxValuation")
        assert q11["fx_valuation"]["summary"]["evaluated_total"] == "110"
        assert q11["fx_valuation"]["summary"]["gate_status"] == "BlockedExceedsCap"

        retry_same = ewire_direct("E", "release-alpha", legacy_rel_req("alpha"), expected="ReleasedExactReceipt")
        assert canonical(retry_same) == canonical(rel_alpha)
        retry_new = ewire_direct("E", "release-alpha-new-msg", legacy_rel_req("alpha"), expected="ReleasedExactReceipt")
        assert retry_new["cut"] == rel_alpha["cut"] and canonical(retry_new["record"]) == canonical(rel_alpha["record"])

        beta_overcap = ewire_direct("E", "release-beta-overcap", legacy_rel_req("beta"), expected="Error")
        assert beta_overcap["error"].startswith("AwaitingPolicy："), beta_overcap
    finally:
        for p, out_f, err_f in procs:
            if p.poll() is None:
                p.terminate()
                try:
                    p.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    p.kill()
                    p.wait()
            out_f.close()
            err_f.close()
        procs.clear()

    # Cold recover non-empty FIN/5+FX DB to epoch 2 (internally runs full audit) + reread
    rec = run_cli(
        [
            str(bins / "e_economic_session"),
            "recover",
            "--manifest",
            str(cfg["manifest_path"]),
            "--db",
            cfg["e_node"]["db"],
        ]
    )
    assert rec.returncode == 0, (rec.stdout, rec.stderr)
    rec_doc = json.loads(rec.stdout)
    assert rec_doc["kind"] == "Recovered" and rec_doc["writer_epoch"] == "2", rec_doc
    for cid in ("alpha", "beta"):
        rec_b = run_cli(
            [
                str(bins / "b_chong_session"),
                "recover",
                "--manifest",
                str(cfg["manifest_path"]),
                "--chong",
                cid,
                "--db",
                cfg["b_nodes"][cid]["db"],
            ]
        )
        assert rec_b.returncode == 0, (cid, rec_b.stdout, rec_b.stderr)
        rec_b_doc = json.loads(rec_b.stdout)
        assert rec_b_doc["kind"] == "Recovered" and rec_b_doc["writer_epoch"] == "2", (cid, rec_b_doc)

    if Path(cfg["e_node"]["socket"]).exists():
        Path(cfg["e_node"]["socket"]).unlink()
    try:
        spawn([str(bins / "e_economic_session"), "serve", "--manifest", str(cfg["manifest_path"]), "--db", cfg["e_node"]["db"], "--epoch", "2"], cfg["e_node"]["socket"], "e-ep2")
        q_ep2_cur = ewire_direct("E", "q-ep2-cur", {"op": "QueryFxValuation", "as_known_ns": None, "cut": None}, expected="EconomicFxValuation", producer_epoch="2")
        assert q_ep2_cur["cut"] == q11["cut"] and q_ep2_cur["fx_valuation"]["summary"]["evaluated_total"] == "110"
        q_ep2_hist = ewire_direct("E", "q-ep2-hist9", {"op": "QueryFxValuation", "as_known_ns": None, "cut": q9["cut"]}, expected="EconomicFxValuation", producer_epoch="2")
        assert q_ep2_hist["cut"] == q9["cut"] and q_ep2_hist["fx_valuation"]["summary"]["evaluated_total"] == "90"
        q_ep2_cmd = ewire_direct("E", "q-ep2-cmd", {"op": "QueryCommand", "command_id": "cmd-alpha", "cut": None, "as_known_ns": None}, expected="EconomicCommand", producer_epoch="2")
        assert canonical(q_ep2_cmd["record"]["command"]) == canonical(rel_alpha["record"]["command"])
    finally:
        for p, out_f, err_f in procs:
            if p.poll() is None:
                p.terminate()
                p.wait(timeout=8)
            out_f.close()
            err_f.close()
        procs.clear()

    with (run_dir / "wire.jsonl").open("w", encoding="utf-8") as f:
        for item in wire_log:
            f.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")

    return {
        "status": "PASS",
        "finance_schema": "tb03b-finance/5",
        "first_import_responsibility_cut": imp_base["cut"],
        "legacy_release_alpha_cut": rel_alpha["cut"],
        "overcap_eval": "110/100",
        "overcap_original_receipt_retry_same_and_new_msg": True,
        "overcap_beta_blocked": beta_overcap["error"],
        "epoch2_recovery_audit_and_reread": "PASS",
    }


def run_arm5_r2_overcap_model_coverage_precedes_fx_gate(bins: Path, fixtures: Path, out: Path) -> dict:
    """Proves BLOCK #2 under explicit tb03b-finance/6 + fx-valuation/2:
    During r2=110/100 overcap in the same session:
      - Already released `alpha` (same & new message_id) still prioritizes original ReleasedExactReceipt;
      - Out-of-domain `batched` command `gamma` hits model_coverage FIRST (bypasses FX gate) and persists
        `Unsupported / ModelOrderUnspecified` (ReleaseUnsupportedReceipt, QueryCommand == Unsupported);
      - In-domain `single` command `beta` enters FX policy gate and is blocked with `AwaitingPolicy`
        (QueryCommand remains `Dispatchable`);
      - Cold recovery to epoch 2 preserves all three states and refuses downgrade to `fx-valuation/1`."""
    run_dir = out / "arm5_r2_overcap_model_order"
    ob_bytes = (fixtures / "fx-obligations.json").read_bytes()
    r1_utf8 = (fixtures / "fx-r1.json").read_text(encoding="utf-8")
    r2_utf8 = (fixtures / "fx-r2.json").read_text(encoding="utf-8")
    x_model = {**base_sim_model(), "symbol": "TEST"}

    msgs = {
        "imp-base": "1",
        "imp-fx": "1",
        "cap-r1": "1",
        "res-r1": "1",
        "cap-open-alpha": "1",
        "apply-open-alpha": "1",
        "bind-alpha": "1",
        "prep-alpha": "1",
        "cap-open-beta": "1",
        "apply-open-beta": "1",
        "bind-beta": "1",
        "prep-beta": "1",
        "cap-open-gamma": "1",
        "apply-open-gamma": "1",
        "bind-gamma": "1",
        "prep-gamma": "1",
        "reserve-main": "1",
        "commit-alpha": "1",
        "commit-beta": "1",
        "commit-gamma": "1",
        "dispatch-alpha": "1",
        "dispatch-beta": "1",
        "dispatch-gamma": "1",
        "q-r1": "1",
        "release-alpha": "2",
        "cap-r2": "3",
        "q-r2": "3",
        "release-alpha-new-msg": "3",
        "release-gamma-batched-overcap": "3",
        "release-beta-single-overcap": "3",
        "q-cmd-gamma": "3",
        "q-cmd-beta": "3",
        "q-ep2-gamma": "4",
        "q-ep2-beta": "4",
        "q-ep2-alpha": "4",
    }
    s_clock = {"prefix-1": {"accept_ns": "10", "attempts": [{"begin_ns": "11", "commit_ns": "12"}]}}
    # alpha=30 (2*14+2, single), beta=25 (2*12+1, single), gamma=15 (3*5+0, batched) -> cash 70 + fx 20 = 90/100; r2 -> 110/100
    cfg = build_session_artifacts(
        run_dir,
        session_id="ce-s07-r2-model-order",
        chongs=["alpha", "beta", "gamma"],
        x_model=x_model,
        fx_obligations_bytes=ob_bytes,
        clock_messages=msgs,
        recover_bars=["4"],
        s_clock_events=s_clock,
        s_socket_for_x=str(run_dir / "structure.sock"),
        baseline_amount="0",
        cap_amount="100",
        finance_schema="tb03b-finance/6",
        fx_schema="fx-valuation/2",
        plan_overrides={
            "beta": {
                "quantity": "2",
                "limit_price": "12",
                "fee_tail": "1",
                "exact": {"first_quantity": "2", "concurrency": "single"},
            },
            "gamma": {
                "slot_id": "slot-main",
                "quantity": "3",
                "limit_price": "5",
                "fee_tail": "0",
                "exact": {"first_quantity": "3", "concurrency": "batched"},
            },
        },
        slot_main_members=["alpha", "beta", "gamma"],
    )

    for cmd_args, label in [
        ([str(bins / "e_economic_session"), "init", "--manifest", str(cfg["manifest_path"]), "--db", cfg["e_node"]["db"]], "arm5-init-E"),
        ([str(bins / "b_chong_session"), "init", "--manifest", str(cfg["manifest_path"]), "--chong", "alpha", "--db", cfg["b_nodes"]["alpha"]["db"]], "arm5-init-B-alpha"),
        ([str(bins / "b_chong_session"), "init", "--manifest", str(cfg["manifest_path"]), "--chong", "beta", "--db", cfg["b_nodes"]["beta"]["db"]], "arm5-init-B-beta"),
        ([str(bins / "b_chong_session"), "init", "--manifest", str(cfg["manifest_path"]), "--chong", "gamma", "--db", cfg["b_nodes"]["gamma"]["db"]], "arm5-init-B-gamma"),
    ]:
        res = run_cli(cmd_args)
        assert res.returncode == 0, (label, res.stdout, res.stderr)

    wire_log: list[dict] = []

    def ewire_direct(domain: str, msg_id: str, payload: dict, *, expected: str, source: dict | None = None, producer_epoch: str = "1") -> dict:
        sock = cfg["e_node"]["socket"] if domain == "E" else cfg["b_nodes"][domain.split(":", 1)[1]]["socket"]
        src = source if source is not None else cfg["src_fin"]
        req = {
            "schema_revision": "economic-session/1",
            "session_id": cfg["sid"],
            "session_generation": cfg["gen"],
            **src,
            "message_id": msg_id,
            "payload_hash": digest(payload),
            "causal_refs": [],
            "payload": payload,
        }
        _, _, rep = send_frame(sock, req, wire_log=wire_log, label=f"arm5:{domain}:{msg_id}")
        res = validate_reply(req, rep, producer=domain, producer_epoch=producer_epoch)
        assert res.get("kind") == expected, (domain, msg_id, expected, res)
        return res

    procs: list[tuple[subprocess.Popen, object, object]] = []

    def spawn(cmd_args: list[str], sock: str, tag: str) -> None:
        out_f = (run_dir / f"{tag}.stdout").open("wb")
        err_p = run_dir / f"{tag}.stderr"
        err_f = err_p.open("wb")
        p = subprocess.Popen(cmd_args, stdin=subprocess.DEVNULL, stdout=out_f, stderr=err_f)
        procs.append((p, out_f, err_f))
        wait_ready(p, sock, f"arm5:{tag}", err_p)

    try:
        spawn([str(bins / "e_economic_session"), "serve", "--manifest", str(cfg["manifest_path"]), "--db", cfg["e_node"]["db"], "--epoch", "1"], cfg["e_node"]["socket"], "e-ep1")
        for cid in ("alpha", "beta", "gamma"):
            spawn([str(bins / "b_chong_session"), "serve", "--manifest", str(cfg["manifest_path"]), "--chong", cid, "--db", cfg["b_nodes"][cid]["db"], "--epoch", "1", "--e-epoch", "1"], cfg["b_nodes"][cid]["socket"], f"b-{cid}-ep1")

        ewire_direct("E", "imp-base", {"op": "ImportResponsibility", "responsibility_id": "r-base", "writer_epoch": "1"}, expected="ResponsibilityImportedReceipt")
        ewire_direct("E", "imp-fx", {"op": "ImportFxResponsibility", "responsibility_id": "ob-fx-unclosed-20", "writer_epoch": "1"}, expected="FxResponsibilityImportedReceipt")
        c3 = ewire_direct("E", "cap-r1", {"op": "CaptureExternal", "raw_utf8": r1_utf8, "json_pointer": "", "token": "fx-r1", "source_event_time": "70"}, expected="Recorded", source=cfg["src_market"])
        ewire_direct(
            "E",
            "res-r1",
            {
                "op": "ResolveEvidence",
                "evidence_id": "ev-r1",
                "covered": [{"fact_key": c3["fact_key"], "token": "fx-r1", "fact_hash": c3["fact_hash"]}],
                "frontier": {"source_namespace": MARKET_NS, "source_epoch": MARKET_EPOCH, "cursor": "70"},
                "dependency_version": "arm5-r1/1",
            },
            expected="Resolved",
            source=cfg["src_market"],
        )
        for cid in ("alpha", "beta", "gamma"):
            cap = ewire_direct("E", f"cap-open-{cid}", {"op": "CaptureExternal", "raw_utf8": cfg["openers"][cid], "json_pointer": "/events/0", "token": f"tok-opening-{cid}", "source_event_time": None}, expected="Recorded")
            ewire_direct(f"B:{cid}", f"apply-open-{cid}", {"op": "ApplyAllocation", "fact_key": cap["fact_key"], "allocation_id": f"allocation-{cid}", "expected_fact_hash": cap["fact_hash"]}, expected="Applied")
            ewire_direct(f"B:{cid}", f"bind-{cid}", cfg["voice_bindings"][cid], expected="VoiceBound")
            ewire_direct(f"B:{cid}", f"prep-{cid}", {"op": "PrepareDecision", "decision_id": cid, "plan_hash": digest(cfg["plans"][cid]), "writer_epoch": "1"}, expected="PreparedReceipt")

        res_main = ewire_direct("E", "reserve-main", {"op": "Reserve", "slot_id": "slot-main", "request_set_hash": digest(cfg["slots"]["slot-main"]["applicants"]), "writer_epoch": "1"}, expected="ReserveReceipt")
        grants = {g["decision_id"]: g["grant_id"] for g in res_main["record"]["grants"]}
        for cid in ("alpha", "beta", "gamma"):
            ewire_direct(f"B:{cid}", f"commit-{cid}", {"op": "CommitDecision", "decision_id": cid, "plan_hash": digest(cfg["plans"][cid]), "grant_id": grants[cid], "writer_epoch": "1"}, expected="LocalCommitReceipt")
        for cid in ("alpha", "beta", "gamma"):
            ewire_direct("E", f"dispatch-{cid}", {"op": "MakeDispatchable", "decision_id": cid, "plan_hash": digest(cfg["plans"][cid]), "writer_epoch": "1"}, expected="DispatchableReceipt")

        q_r1 = ewire_direct("E", "q-r1", {"op": "QueryFxValuation", "as_known_ns": None, "cut": None}, expected="EconomicFxValuation")
        assert q_r1["fx_valuation"]["schema_revision"] == "fx-valuation/2"
        assert q_r1["fx_valuation"]["summary"]["evaluated_total"] == "90"

        alpha_cert = build_fx_certificate_from_query(cfg["sid"], cfg["gen"], cfg["fin_data"], cfg["plans"]["alpha"], grants["alpha"], q_r1)
        alpha_req = {
            "op": "ReleaseExact",
            "decision_id": "alpha",
            "command_id": "cmd-alpha",
            "plan_hash": digest(change_for_plan(cfg["plans"]["alpha"])),
            "certificate": alpha_cert,
            "x_id": "X",
            "x_epoch": "1",
            "writer_epoch": "1",
        }
        rel_alpha = ewire_direct("E", "release-alpha", alpha_req, expected="ReleasedExactReceipt")

        # r2 -> 110/100 overcap
        ewire_direct("E", "cap-r2", {"op": "CaptureExternal", "raw_utf8": r2_utf8, "json_pointer": "", "token": "fx-r2", "source_event_time": "70"}, expected="Recorded", source=cfg["src_market"])
        q_r2 = ewire_direct("E", "q-r2", {"op": "QueryFxValuation", "as_known_ns": None, "cut": None}, expected="EconomicFxValuation")
        assert q_r2["fx_valuation"]["summary"]["evaluated_total"] == "110"
        assert q_r2["fx_valuation"]["summary"]["gate_status"] == "BlockedExceedsCap"

        # 1) Original receipt priority for alpha
        retry_same = ewire_direct("E", "release-alpha", alpha_req, expected="ReleasedExactReceipt")
        assert canonical(retry_same) == canonical(rel_alpha)
        retry_new = ewire_direct("E", "release-alpha-new-msg", alpha_req, expected="ReleasedExactReceipt")
        assert canonical(retry_new) == canonical(rel_alpha)

        # 2) The in-domain command is denied without advancing E; gamma sees the same cut.
        beta_cert_r1 = build_fx_certificate_from_query(cfg["sid"], cfg["gen"], cfg["fin_data"], cfg["plans"]["beta"], grants["beta"], q_r1)
        rel_beta = ewire_direct(
            "E",
            "release-beta-single-overcap",
            {
                "op": "ReleaseExact",
                "decision_id": "beta",
                "command_id": "cmd-beta",
                "plan_hash": digest(change_for_plan(cfg["plans"]["beta"])),
                "certificate": beta_cert_r1,
                "x_id": "X",
                "x_epoch": "1",
                "writer_epoch": "1",
            },
            expected="Error",
        )
        assert rel_beta["error"].startswith("AwaitingPolicy：fx_cap_gate"), rel_beta

        # 3) At the same input cut the out-of-domain command persists Unsupported, not AwaitingPolicy.
        freeze = cfg["fin_data"]["exact_release"]
        q_g = cfg["plans"]["gamma"]
        gamma_tpl_cert = {
            "rd11_policy": freeze["rd11_policy"],
            "responsibility_refs": [grants["gamma"]],
            "structure_dependencies": [f"{q_g['s_ref']['object_id']}@{q_g['s_ref']['object_hash']}"],
            "market_dependencies": freeze["market_dependencies"],
            "rule_revision": freeze["rule_revision"],
            "conditions": freeze["conditions"],
        }
        rel_gamma = ewire_direct(
            "E",
            "release-gamma-batched-overcap",
            {
                "op": "ReleaseExact",
                "decision_id": "gamma",
                "command_id": "cmd-gamma",
                "plan_hash": digest(change_for_plan(q_g)),
                "certificate": gamma_tpl_cert,
                "x_id": "X",
                "x_epoch": "1",
                "writer_epoch": "1",
            },
            expected="ReleaseUnsupportedReceipt",
        )
        assert int(rel_gamma["cut"]["commit_seq"]) == int(q_r2["cut"]["commit_seq"]) + 1
        assert rel_gamma["record"]["state"] == "Unsupported"
        assert rel_gamma["record"]["unsupported"]["reason"] == "ModelOrderUnspecified"
        assert rel_gamma["record"]["execution_eligibility"] == "None"
        write_pretty(out / "arm5_gamma_batched_unsupported_receipt.json", rel_gamma)

        q_cmd_gamma = ewire_direct("E", "q-cmd-gamma", {"op": "QueryCommand", "command_id": "cmd-gamma", "cut": None, "as_known_ns": None}, expected="EconomicCommand")
        assert q_cmd_gamma["state"] == "Unsupported"
        q_cmd_beta = ewire_direct("E", "q-cmd-beta", {"op": "QueryCommand", "command_id": "cmd-beta", "cut": None, "as_known_ns": None}, expected="EconomicCommand")
        assert q_cmd_beta["state"] == "Dispatchable"
    finally:
        for p, out_f, err_f in procs:
            if p.poll() is None:
                p.terminate()
                p.wait(timeout=8)
            out_f.close()
            err_f.close()
        procs.clear()

    rec = run_cli([str(bins / "e_economic_session"), "recover", "--manifest", str(cfg["manifest_path"]), "--db", cfg["e_node"]["db"]])
    assert rec.returncode == 0 and json.loads(rec.stdout)["writer_epoch"] == "2", (rec.stdout, rec.stderr)

    # Verify persisted fx-valuation/2 refuses downgrade recovery to fx-valuation/1
    dg_manifest = copy.deepcopy(cfg["manifest"])
    dg_manifest["fx_valuation"]["schema_revision"] = "fx-valuation/1"
    dg_mpath = write_canon(run_dir / "downgrade-v1-manifest.json", dg_manifest)
    dg_rec = run_cli([str(bins / "e_economic_session"), "recover", "--manifest", str(dg_mpath), "--db", cfg["e_node"]["db"]])
    assert dg_rec.returncode != 0 and "IdentityConflict" in dg_rec.stderr, (dg_rec.returncode, dg_rec.stderr)

    if Path(cfg["e_node"]["socket"]).exists():
        Path(cfg["e_node"]["socket"]).unlink()
    try:
        spawn([str(bins / "e_economic_session"), "serve", "--manifest", str(cfg["manifest_path"]), "--db", cfg["e_node"]["db"], "--epoch", "2"], cfg["e_node"]["socket"], "e-ep2")
        assert ewire_direct("E", "q-ep2-gamma", {"op": "QueryCommand", "command_id": "cmd-gamma", "cut": None, "as_known_ns": None}, expected="EconomicCommand", producer_epoch="2")["state"] == "Unsupported"
        assert ewire_direct("E", "q-ep2-beta", {"op": "QueryCommand", "command_id": "cmd-beta", "cut": None, "as_known_ns": None}, expected="EconomicCommand", producer_epoch="2")["state"] == "Dispatchable"
        assert ewire_direct("E", "q-ep2-alpha", {"op": "QueryCommand", "command_id": "cmd-alpha", "cut": None, "as_known_ns": None}, expected="EconomicCommand", producer_epoch="2")["state"] == "ReleasedExact"
    finally:
        for p, out_f, err_f in procs:
            if p.poll() is None:
                p.terminate()
                p.wait(timeout=8)
            out_f.close()
            err_f.close()
        procs.clear()

    with (run_dir / "wire.jsonl").open("w", encoding="utf-8") as f:
        for item in wire_log:
            f.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")

    return {
        "status": "PASS",
        "finance_schema": "tb03b-finance/6",
        "fx_schema": "fx-valuation/2",
        "overcap_eval": "110/100",
        "shared_input_cut": q_r2["cut"],
        "alpha_original_receipt_priority_same_and_new_msg": True,
        "gamma_batched_receipt_kind": rel_gamma["kind"],
        "gamma_batched_state": rel_gamma["record"]["state"],
        "gamma_batched_reason": rel_gamma["record"]["unsupported"]["reason"],
        "gamma_batched_cut": rel_gamma["cut"],
        "beta_single_overcap_error": rel_beta["error"],
        "beta_single_query_state": q_cmd_beta["state"],
        "downgrade_v2_to_v1_recovery_refused": dg_rec.stderr.strip(),
        "epoch2_recovery_and_reread": "PASS",
    }


def run_arm6_parent_bd0933e97e_fin6_fx_v1_recovery(
    parent_bins: Path, candidate_bins: Path, fixtures: Path, out: Path
) -> dict:
    """Proves BLOCK #1 with REAL parent (`bd0933e97e`) binaries:
    A parent-written r1 capture makes the pre-import DB non-empty. Parent and candidate
    import from that same snapshot with the same manifest, requests and clock.
    Candidate also recovers the original parent DB including a static release and r2."""
    run_dir = out / "arm6_parent_bd0933e97e_fin6_fx_v1"
    ob_bytes = (fixtures / "fx-obligations.json").read_bytes()
    r1_utf8 = (fixtures / "fx-r1.json").read_text(encoding="utf-8")
    r2_utf8 = (fixtures / "fx-r2.json").read_text(encoding="utf-8")
    x_model = {**base_sim_model(), "symbol": "TEST"}

    msgs = {
        "cap-r1": "1",
        "imp-base": "1",
        "imp-fx": "1",
        "res-r1": "1",
        "cap-open-alpha": "1",
        "apply-open-alpha": "1",
        "bind-alpha": "1",
        "prep-alpha": "1",
        "cap-open-beta": "1",
        "apply-open-beta": "1",
        "bind-beta": "1",
        "prep-beta": "1",
        "reserve-main": "1",
        "commit-alpha": "1",
        "commit-beta": "1",
        "dispatch-alpha": "1",
        "dispatch-beta": "1",
        "q-pre-r2": "1",
        "release-alpha": "2",
        "cap-r2": "3",
        "q-r2": "3",
        "parent-q-cmd": "3",
        "parent-malformed-beta": "3",
        "cand-q-cur": "4",
        "cand-q-hist": "4",
        "cand-q-cmd": "4",
        "cand-malformed-beta": "4",
        "cand-retry-alpha-new-msg": "4",
    }
    s_clock = {"prefix-1": {"accept_ns": "10", "attempts": [{"begin_ns": "11", "commit_ns": "12"}]}}
    # NOTE: Parent bd0933e97e fx-valuation/1 only accepted clock.kind=="TestOnly" before our logical-bar/1 extension,
    # so we build a standard TestOnly clock manifest matching parent bd0933e97e!
    cfg = build_session_artifacts(
        run_dir,
        session_id="ce-s07-parent-fin6-fx-v1",
        chongs=["alpha", "beta"],
        x_model=x_model,
        fx_obligations_bytes=ob_bytes,
        clock_messages=msgs,
        recover_bars=["4"],
        s_clock_events=s_clock,
        s_socket_for_x=str(run_dir / "structure.sock"),
        baseline_amount="0",
        cap_amount="100",
        use_fx_marker_in_input=False,
        finance_schema="tb03b-finance/6",
        fx_schema="fx-valuation/1",
    )
    # Patch clock to TestOnly plan (monotonic ns) so parent bd0933e97e accepts fx-valuation/1!
    t = 10
    tc_msgs = {}
    for m in msgs:
        if m.startswith("cand-"):
            t = max(t, 10010)  # epoch 2 begins at recover_ns=10000
        tc_msgs[m] = {"received_ns": str(t), "first_known_ns": str(t + 1), "commit_ns": str(t + 2)}
        t += 10
    cfg["manifest"]["clock"] = {
        "kind": "TestOnly",
        "plan": {"init_ns": "1", "recover_ns": ["10000", "20000"], "messages": tc_msgs},
    }
    write_canon(cfg["manifest_path"], cfg["manifest"])

    # Phase 1: Write non-empty FIN/6 + fx-valuation/1 DB using REAL PARENT bd0933e97e binaries!
    for cmd_args, label in [
        ([str(parent_bins / "e_economic_session"), "init", "--manifest", str(cfg["manifest_path"]), "--db", cfg["e_node"]["db"]], "parent-init-E"),
        ([str(parent_bins / "b_chong_session"), "init", "--manifest", str(cfg["manifest_path"]), "--chong", "alpha", "--db", cfg["b_nodes"]["alpha"]["db"]], "parent-init-B-alpha"),
        ([str(parent_bins / "b_chong_session"), "init", "--manifest", str(cfg["manifest_path"]), "--chong", "beta", "--db", cfg["b_nodes"]["beta"]["db"]], "parent-init-B-beta"),
    ]:
        res = run_cli(cmd_args)
        assert res.returncode == 0, (label, res.stdout, res.stderr)

    wire_log: list[dict] = []

    phase = "parent"

    def ewire_direct(domain: str, msg_id: str, payload: dict, *, expected: str, source: dict | None = None, producer_epoch: str = "1") -> dict:
        sock = cfg["e_node"]["socket"] if domain == "E" else cfg["b_nodes"][domain.split(":", 1)[1]]["socket"]
        src = source if source is not None else cfg["src_fin"]
        req = {
            "schema_revision": "economic-session/1",
            "session_id": cfg["sid"],
            "session_generation": cfg["gen"],
            **src,
            "message_id": msg_id,
            "payload_hash": digest(payload),
            "causal_refs": [],
            "payload": payload,
        }
        _, _, rep = send_frame(sock, req, wire_log=wire_log, label=f"arm6:{phase}:{domain}:{msg_id}")
        res = validate_reply(req, rep, producer=domain, producer_epoch=producer_epoch)
        assert res.get("kind") == expected, (phase, domain, msg_id, expected, res)
        return res

    procs: list[tuple[subprocess.Popen, object, object]] = []

    def spawn(cmd_args: list[str], sock: str, tag: str) -> None:
        out_f = (run_dir / f"{tag}.stdout").open("wb")
        err_p = run_dir / f"{tag}.stderr"
        err_f = err_p.open("wb")
        p = subprocess.Popen(cmd_args, stdin=subprocess.DEVNULL, stdout=out_f, stderr=err_f)
        procs.append((p, out_f, err_f))
        wait_ready(p, sock, f"arm6:{tag}", err_p)

    def stop() -> None:
        for p, out_f, err_f in procs:
            if p.poll() is None:
                p.terminate()
                p.wait(timeout=8)
            out_f.close()
            err_f.close()
        procs.clear()

    db = Path(cfg["e_node"]["db"])
    sock = Path(cfg["e_node"]["socket"])
    manifest_path = str(cfg["manifest_path"])
    pre_import = run_dir / "parent-pre-import.db"
    base_import = {"op": "ImportResponsibility", "responsibility_id": "r-base", "writer_epoch": "1"}
    fx_import = {"op": "ImportFxResponsibility", "responsibility_id": "ob-fx-unclosed-20", "writer_epoch": "1"}
    query_alpha = {"op": "QueryCommand", "command_id": "cmd-alpha", "cut": None, "as_known_ns": None}

    try:
        spawn([str(parent_bins / "e_economic_session"), "serve", "--manifest", str(cfg["manifest_path"]), "--db", cfg["e_node"]["db"], "--epoch", "1"], cfg["e_node"]["socket"], "parent-e-ep1")
        for cid in ("alpha", "beta"):
            spawn([str(parent_bins / "b_chong_session"), "serve", "--manifest", str(cfg["manifest_path"]), "--chong", cid, "--db", cfg["b_nodes"][cid]["db"], "--epoch", "1", "--e-epoch", "1"], cfg["b_nodes"][cid]["socket"], f"parent-b-{cid}-ep1")

        c3 = ewire_direct("E", "cap-r1", {"op": "CaptureExternal", "raw_utf8": r1_utf8, "json_pointer": "", "token": "fx-r1", "source_event_time": "70"}, expected="Recorded", source=cfg["src_market"])
        assert c3["cut"]["commit_seq"] == "1"
        with closing(sqlite3.connect(db.as_uri() + "?mode=ro", uri=True)) as src:
            with closing(sqlite3.connect(pre_import)) as dst:
                src.backup(dst)
        parent_imp_base = ewire_direct("E", "imp-base", base_import, expected="ResponsibilityImportedReceipt")
        parent_imp_fx = ewire_direct("E", "imp-fx", fx_import, expected="FxResponsibilityImportedReceipt")
        ewire_direct(
            "E",
            "res-r1",
            {
                "op": "ResolveEvidence",
                "evidence_id": "ev-r1",
                "covered": [{"fact_key": c3["fact_key"], "token": "fx-r1", "fact_hash": c3["fact_hash"]}],
                "frontier": {"source_namespace": MARKET_NS, "source_epoch": MARKET_EPOCH, "cursor": "70"},
                "dependency_version": "parent-r1/1",
            },
            expected="Resolved",
            source=cfg["src_market"],
        )
        for cid in ("alpha", "beta"):
            cap = ewire_direct("E", f"cap-open-{cid}", {"op": "CaptureExternal", "raw_utf8": cfg["openers"][cid], "json_pointer": "/events/0", "token": f"tok-opening-{cid}", "source_event_time": None}, expected="Recorded")
            ewire_direct(f"B:{cid}", f"apply-open-{cid}", {"op": "ApplyAllocation", "fact_key": cap["fact_key"], "allocation_id": f"allocation-{cid}", "expected_fact_hash": cap["fact_hash"]}, expected="Applied")
            ewire_direct(f"B:{cid}", f"bind-{cid}", cfg["voice_bindings"][cid], expected="VoiceBound")
            ewire_direct(f"B:{cid}", f"prep-{cid}", {"op": "PrepareDecision", "decision_id": cid, "plan_hash": digest(cfg["plans"][cid]), "writer_epoch": "1"}, expected="PreparedReceipt")

        res_main = ewire_direct("E", "reserve-main", {"op": "Reserve", "slot_id": "slot-main", "request_set_hash": digest(cfg["slots"]["slot-main"]["applicants"]), "writer_epoch": "1"}, expected="ReserveReceipt")
        grants = {g["decision_id"]: g["grant_id"] for g in res_main["record"]["grants"]}
        for cid in ("alpha", "beta"):
            ewire_direct(f"B:{cid}", f"commit-{cid}", {"op": "CommitDecision", "decision_id": cid, "plan_hash": digest(cfg["plans"][cid]), "grant_id": grants[cid], "writer_epoch": "1"}, expected="LocalCommitReceipt")
        for cid in ("alpha", "beta"):
            ewire_direct("E", f"dispatch-{cid}", {"op": "MakeDispatchable", "decision_id": cid, "plan_hash": digest(cfg["plans"][cid]), "writer_epoch": "1"}, expected="DispatchableReceipt")

        q_pre_r2 = ewire_direct("E", "q-pre-r2", {"op": "QueryFxValuation", "as_known_ns": None, "cut": None}, expected="EconomicFxValuation")
        assert q_pre_r2["fx_valuation"]["schema_revision"] == "fx-valuation/1"
        assert q_pre_r2["fx_valuation"]["summary"]["evaluated_total"] == "90"

        freeze = cfg["fin_data"]["exact_release"]
        q_a = cfg["plans"]["alpha"]
        static_alpha_req = {
            "op": "ReleaseExact",
            "decision_id": "alpha",
            "command_id": "cmd-alpha",
            "plan_hash": digest(change_for_plan(q_a)),
            "certificate": {
                "rd11_policy": freeze["rd11_policy"],
                "responsibility_refs": [grants["alpha"]],
                "structure_dependencies": [f"{q_a['s_ref']['object_id']}@{q_a['s_ref']['object_hash']}"],
                "market_dependencies": freeze["market_dependencies"],
                "rule_revision": freeze["rule_revision"],
                "conditions": freeze["conditions"],
            },
            "x_id": "X",
            "x_epoch": "1",
            "writer_epoch": "1",
        }
        parent_rel_alpha = ewire_direct("E", "release-alpha", static_alpha_req, expected="ReleasedExactReceipt")
        assert parent_rel_alpha["record"]["command"]["model_ref"]["content_hash"] == digest(x_model)
        assert parent_rel_alpha["record"]["command"]["certificate"]["market_dependencies"] == ["TestOnly-market/nonfx-legacy-v6"]
        write_pretty(out / "arm6_parent_bd0933e97e_alpha_receipt.json", parent_rel_alpha)

        ewire_direct("E", "cap-r2", {"op": "CaptureExternal", "raw_utf8": r2_utf8, "json_pointer": "", "token": "fx-r2", "source_event_time": "70"}, expected="Recorded", source=cfg["src_market"])
        q_parent_r2 = ewire_direct("E", "q-r2", {"op": "QueryFxValuation", "as_known_ns": None, "cut": None}, expected="EconomicFxValuation")
        assert q_parent_r2["fx_valuation"]["summary"]["evaluated_total"] == "110"
        parent_cmd = ewire_direct("E", "parent-q-cmd", query_alpha, expected="EconomicCommand")
        q_b = cfg["plans"]["beta"]
        bad_beta = {
            **static_alpha_req,
            "decision_id": "beta",
            "command_id": "cmd-beta",
            "plan_hash": digest(change_for_plan(q_b)),
            "certificate": {
                **static_alpha_req["certificate"],
                "responsibility_refs": [grants["beta"]],
                "structure_dependencies": [f"{q_b['s_ref']['object_id']}@{q_b['s_ref']['object_hash']}"],
                "rule_revision": "wrong-static-rule",
            },
        }
        parent_bad_beta = ewire_direct("E", "parent-malformed-beta", bad_beta, expected="Error")
        assert parent_bad_beta["error"].startswith("IdentityConflict：证书内容"), parent_bad_beta
    finally:
        stop()

    # The DB path is in the frozen manifest. Swap the stopped store and its sidecars
    # as a unit so the pre-import fork uses the very same manifest bytes and clock.
    parked = run_dir / "parent-after-r2"
    parked.mkdir()
    originals = [p for p in (db, Path(f"{db}-wal"), Path(f"{db}-shm")) if p.exists()]
    for p in originals:
        p.rename(parked / p.name)
    pre_import.rename(db)
    phase = "candidate-first-import"
    try:
        sock.unlink(missing_ok=True)
        spawn([str(candidate_bins / "e_economic_session"), "serve", "--manifest", manifest_path, "--db", str(db), "--epoch", "1"], str(sock), "candidate-first-import")
        cand_imp_base = ewire_direct("E", "imp-base", base_import, expected="ResponsibilityImportedReceipt")
        cand_imp_fx = ewire_direct("E", "imp-fx", fx_import, expected="FxResponsibilityImportedReceipt")
        assert canonical(cand_imp_base) == canonical(parent_imp_base)
        assert canonical(cand_imp_fx) == canonical(parent_imp_fx)
    finally:
        stop()
        for suffix in ("", "-wal", "-shm"):
            p = Path(f"{db}{suffix}")
            if p.exists():
                p.rename(run_dir / f"candidate-first-import.db{suffix}")
        for p in originals:
            (parked / p.name).rename(p)

    # Phase 2: Recover the original parent-written store, not the import fork.
    phase = "candidate-replay"
    cand_rec_e = run_cli([str(candidate_bins / "e_economic_session"), "recover", "--manifest", str(cfg["manifest_path"]), "--db", cfg["e_node"]["db"]])
    assert cand_rec_e.returncode == 0, (cand_rec_e.stdout, cand_rec_e.stderr)
    cand_rec_e_doc = json.loads(cand_rec_e.stdout)
    assert cand_rec_e_doc["kind"] == "Recovered" and cand_rec_e_doc["writer_epoch"] == "2", cand_rec_e_doc
    assert cand_rec_e_doc["cut"] == q_parent_r2["cut"], cand_rec_e_doc
    for cid in ("alpha", "beta"):
        rb = run_cli([str(candidate_bins / "b_chong_session"), "recover", "--manifest", str(cfg["manifest_path"]), "--chong", cid, "--db", cfg["b_nodes"][cid]["db"]])
        assert rb.returncode == 0 and json.loads(rb.stdout)["writer_epoch"] == "2", (cid, rb.stdout, rb.stderr)

    # Candidate MUST refuse silent migration of parent fx-valuation/1 DB to fx-valuation/2
    up_manifest = copy.deepcopy(cfg["manifest"])
    up_manifest["fx_valuation"]["schema_revision"] = "fx-valuation/2"
    up_mpath = write_canon(run_dir / "upgrade-v2-manifest.json", up_manifest)
    up_rec = run_cli([str(candidate_bins / "e_economic_session"), "recover", "--manifest", str(up_mpath), "--db", cfg["e_node"]["db"]])
    assert up_rec.returncode != 0 and "IdentityConflict" in up_rec.stderr, (up_rec.returncode, up_rec.stderr)

    if Path(cfg["e_node"]["socket"]).exists():
        Path(cfg["e_node"]["socket"]).unlink()
    try:
        spawn([str(candidate_bins / "e_economic_session"), "serve", "--manifest", str(cfg["manifest_path"]), "--db", cfg["e_node"]["db"], "--epoch", "2"], cfg["e_node"]["socket"], "cand-e-ep2")
        cq_cur = ewire_direct("E", "cand-q-cur", {"op": "QueryFxValuation", "as_known_ns": None, "cut": None}, expected="EconomicFxValuation", producer_epoch="2")
        assert canonical(cq_cur) == canonical({**q_parent_r2, "writer_epoch": "2"})

        cq_hist = ewire_direct("E", "cand-q-hist", {"op": "QueryFxValuation", "as_known_ns": None, "cut": q_pre_r2["cut"]}, expected="EconomicFxValuation", producer_epoch="2")
        assert canonical(cq_hist) == canonical({**q_pre_r2, "writer_epoch": "2"})

        cq_cmd = ewire_direct("E", "cand-q-cmd", query_alpha, expected="EconomicCommand", producer_epoch="2")
        assert canonical(cq_cmd) == canonical(parent_cmd)
        cand_bad_beta = ewire_direct("E", "cand-malformed-beta", {**bad_beta, "writer_epoch": "2"}, expected="Error", producer_epoch="2")
        assert canonical(cand_bad_beta) == canonical(parent_bad_beta), (cand_bad_beta, parent_bad_beta)

        # Same & new message_id retry on candidate returns exact parent original ReleasedExactReceipt
        cand_retry_same = ewire_direct("E", "release-alpha", static_alpha_req, expected="ReleasedExactReceipt", producer_epoch="2")
        assert canonical(cand_retry_same) == canonical(parent_rel_alpha)
        cand_retry_new = ewire_direct("E", "cand-retry-alpha-new-msg", static_alpha_req, expected="ReleasedExactReceipt", producer_epoch="2")
        assert canonical(cand_retry_new) == canonical(parent_rel_alpha)
    finally:
        stop()

    with (run_dir / "wire.jsonl").open("w", encoding="utf-8") as f:
        for item in wire_log:
            f.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")

    return {
        "status": "PASS",
        "parent_bin": str(parent_bins),
        "finance_schema": "tb03b-finance/6",
        "fx_schema": "fx-valuation/1",
        "parent_pre_import_cut": c3["cut"],
        "first_import_cuts": [parent_imp_base["cut"], parent_imp_fx["cut"]],
        "candidate_first_import_receipts_exact_match": True,
        "static_invalid_certificate_before_fx_gate": parent_bad_beta["error"],
        "parent_written_alpha_release_cut": parent_rel_alpha["cut"],
        "parent_written_overcap_cut": q_parent_r2["cut"],
        "candidate_recover_epoch": cand_rec_e_doc["writer_epoch"],
        "candidate_reread_and_original_receipt_retry_exact_match": True,
        "silent_migration_v1_to_v2_refused": up_rec.stderr.strip(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bin", type=Path, required=True)
    parser.add_argument("--fixtures", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--parent-bin", type=Path, default=None)
    parser.add_argument("--arm", type=int, choices=(5, 6), help="run only one regression arm")
    args = parser.parse_args()
    if args.arm == 6 and args.parent_bin is None:
        parser.error("--arm 6 requires --parent-bin")

    bins = args.bin.resolve()
    fixtures = args.fixtures.resolve()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)

    # Verify exact byte-for-byte SHA-256 of upstream fixtures
    fixture_hashes = {}
    for fname, expected_sha in EXPECTED_FIXTURE_SHA256.items():
        actual = file_digest(fixtures / fname)
        assert actual == expected_sha, f"fixture {fname} sha256 mismatch: {actual} != {expected_sha}"
        fixture_hashes[fname] = actual

    arms = {}
    if args.arm is None:
        arms.update({
            "arm1_ce_s07_main": run_arm1_main_lifecycle(bins, fixtures, out),
            "arm2_unrelated_healthy_chong": run_arm2_unrelated_revision_control(bins, out),
            "arm3_pure_nonfx_legacy": run_arm3_pure_non_fx_legacy_and_config_guards(bins, fixtures, out),
            "arm4_fin5_fx_compat_and_old_db_recovery": run_arm4_fin5_fx_compat_and_old_db_recovery(bins, fixtures, out),
        })
    if args.arm in (None, 5):
        arms["arm5_r2_overcap_model_coverage_precedes_fx_gate"] = run_arm5_r2_overcap_model_coverage_precedes_fx_gate(bins, fixtures, out)
    if args.arm in (None, 6) and args.parent_bin is not None:
        arms["arm6_parent_bd0933e97e_fin6_fx_v1_recovery"] = run_arm6_parent_bd0933e97e_fin6_fx_v1_recovery(
            args.parent_bin.resolve(), bins, fixtures, out
        )

    summary = {
        "issue": "#1407 C3 CE-S07",
        "status": "PASS",
        "bin": str(bins),
        "fixtures_sha256": fixture_hashes,
        "arms": arms,
    }
    write_pretty(out / "summary.json", summary)
    print("PASS CE-S07 integrated verification:", json.dumps({"status": "PASS", "out": str(out)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
