"""#1425 方案 1：economic-read-projection/1 与 EconomicReadError 透传单元测试。"""
import base64
import hashlib
import time
import unittest
from unittest.mock import Mock

import economic_query
from s_socket_client import (
    ECONOMIC_PAGE_REVISION,
    ECONOMIC_PROJECTION_REVISION,
    canonical,
    digest,
    read_economic_pages,
)


def _paged_fetch_from_doc(doc, *, session_id="s1", session_generation="1",
                          manifest_hash="a" * 64, producer_id="E:s1",
                          producer_epoch="1", owner_epochs=None, fixed_cuts=None,
                          document_kind="EconomicProjectionView"):
    encoded = canonical(doc)
    owner_epochs = owner_epochs or {"E": "1"}
    fixed_cuts = fixed_cuts or {"E": doc["cut"]}
    transfer_id = "0" * 32

    def fetch(payload, remaining_ms):
        op = payload["op"]
        if op == "EconomicReadOpen":
            descriptor = {
                "schema_revision": ECONOMIC_PAGE_REVISION,
                "transfer_id": transfer_id,
                "session_id": session_id,
                "session_generation": session_generation,
                "manifest_hash": manifest_hash,
                "producer_id": producer_id,
                "producer_epoch": producer_epoch,
                "query_sha256": digest(payload["query"]),
                "document_kind": document_kind,
                "fixed_cuts": fixed_cuts,
                "owner_epochs": owner_epochs,
                "document_bytes": str(len(encoded)),
                "document_sha256": hashlib.sha256(encoded).hexdigest(),
                "chunk_bytes": "262144",
                "page_count": str((len(encoded) + 262143) // 262144),
            }
            return {
                "schema_revision": ECONOMIC_PAGE_REVISION,
                "kind": "EconomicReadOpened",
                "descriptor": descriptor,
                "descriptor_sha256": digest(descriptor),
            }
        if op == "EconomicReadPage":
            offset = int(payload["offset"])
            chunk = encoded[offset:offset + 262144]
            end = offset + len(chunk)
            return {
                "schema_revision": ECONOMIC_PAGE_REVISION,
                "kind": "EconomicReadPage",
                "transfer_id": transfer_id,
                "descriptor_sha256": payload["descriptor_sha256"],
                "offset": str(offset),
                "raw_byte_count": str(len(chunk)),
                "chunk_sha256": hashlib.sha256(chunk).hexdigest(),
                "data_base64": base64.b64encode(chunk).decode("ascii"),
                "next_offset": None if end == len(encoded) else str(end),
                "done": end == len(encoded),
            }
        return {
            "schema_revision": ECONOMIC_PAGE_REVISION,
            "kind": "EconomicReadClosed",
            "transfer_id": transfer_id,
            "descriptor_sha256": payload["descriptor_sha256"],
        }

    return fetch


class EconomicReadProjectionTests(unittest.TestCase):
    def test_open_query_budget_exceeded_not_mistranslated_as_open_fields_error(self):
        def fetch(payload, remaining_ms):
            return {
                "schema_revision": ECONOMIC_PAGE_REVISION,
                "kind": "EconomicReadError",
                "code": "QueryBudgetExceeded",
                "detail": "Incomplete：完整持久图像超出读取逻辑字节帽",
                "transfer_id": None,
            }

        with self.assertRaises(ValueError) as ctx:
            read_economic_pages(
                {"op": "ReadView", "cut": None, "as_known_ns": None},
                fetch,
                session_id="s1",
                session_generation="1",
                producer_id="B:alpha:s1",
                producer_epoch="1",
                manifest_hash="b" * 64,
                owner_epochs={"B:alpha": "1"},
                deadline=time.monotonic() + 10,
            )
        msg = str(ctx.exception)
        self.assertIn("QueryBudgetExceeded", msg)
        self.assertNotIn("Open 字段", msg)

    def test_read_projection_document_validates_and_rejects_tampered_projection_hash(self):
        cut = {"domain_id": "E", "commit_seq": "10", "root_hash": "1" * 64}
        proj = {"book": None, "recorded": [], "pending": [], "applied": [], "unmatched": [], "history": []}
        proj_bytes = canonical(proj)
        doc = {
            "kind": "EconomicProjectionView",
            "projection_revision": ECONOMIC_PROJECTION_REVISION,
            "domain_id": "E",
            "session_id": "s1",
            "session_generation": "1",
            "cut": cut,
            "commit_ns": "10",
            "writer_epoch": "1",
            "audit_verified": True,
            "authoritative_image_hash": "2" * 64,
            "authoritative_image_bytes": "1066564",
            "projection_hash": hashlib.sha256(proj_bytes).hexdigest(),
            "projection_bytes": str(len(proj_bytes)),
            "omitted_peer_images": [],
            "projection": proj,
            "runtime": {},
        }
        q = {"op": "ReadProjection", "projection_revision": ECONOMIC_PROJECTION_REVISION,
             "cut": cut, "as_known_ns": None}
        got = read_economic_pages(
            q,
            _paged_fetch_from_doc(doc),
            session_id="s1",
            session_generation="1",
            producer_id="E:s1",
            producer_epoch="1",
            manifest_hash="a" * 64,
            owner_epochs={"E": "1"},
            deadline=time.monotonic() + 10,
        )
        self.assertEqual(got["authoritative_image_hash"], "2" * 64)
        self.assertNotEqual(got["projection_hash"], got["authoritative_image_hash"])

        # Tamper projection_hash -> must reject!
        bad = dict(doc, projection_hash="3" * 64)
        with self.assertRaises(ValueError) as ctx:
            read_economic_pages(
                q,
                _paged_fetch_from_doc(bad),
                session_id="s1",
                session_generation="1",
                producer_id="E:s1",
                producer_epoch="1",
                manifest_hash="a" * 64,
                owner_epochs={"E": "1"},
                deadline=time.monotonic() + 10,
            )
        self.assertIn("投影视图摘要", str(ctx.exception))

    def test_exact_decimal_text_rejects_floats_and_preserves_large_integers(self):
        big = 9007199254740993  # > Number.MAX_SAFE_INTEGER
        self.assertEqual(
            economic_query._exact_decimal_text({"n": big, "ok": True, "s": "x"}),
            {"n": "9007199254740993", "ok": True, "s": "x"},
        )
        with self.assertRaises(economic_query.EconomicQueryError):
            economic_query._exact_decimal_text({"bad": 1.5})

    def test_original_hashes_bind_exact_utf8_bytes_at_the_selected_cut(self):
        cut = {"domain_id": "E", "commit_seq": "10", "root_hash": "1" * 64}
        q = Mock(session="s1", generation="1", epochs={"E": "1"}, nodes={"E": None},
                 manifest_hash="a" * 64, read_projection_available=True,
                 authorized_read_ops=frozenset({"ReadView", "QueryFact", "QueryCommand"}),
                 lock=None, cache=None, _verified_cuts_cache=set())
        q._verified_vector_cached = lambda cuts: False
        q._check_projection_original_permission = lambda d, k: None
        raw = '{"说明":"成交","数量":2}\n'
        h = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        for kind, original, field in (
            ("fact", {"raw_utf8": raw, "raw_sha256": h, "receipts": []}, "raw_utf8"),
            ("model", {"model_raw_utf8": raw, "model_ref": {"content_hash": h}}, "model_raw_utf8"),
        ):
            with self.subTest(kind=kind):
                req = {"op": "projection_original", "projection_revision": ECONOMIC_PROJECTION_REVISION,
                       "domain_id": "E", "kind": kind, "object_id": "item", "cuts": {"E": cut}}
                q.owner.return_value = {"kind": "EconomicOriginalAtCut", "original": original,
                    "projection_revision": ECONOMIC_PROJECTION_REVISION, "original_kind": kind,
                    "object_id": "item", "domain_id": "E", "session_id": "s1", "session_generation": "1",
                    "writer_epoch": "1", "cut": cut, "audit_verified": True, "commit_ns": "10",
                    "authoritative_image_hash": "2" * 64, "authoritative_image_bytes": "800"}
                read = economic_query.EconomicQuery.projection_original
                self.assertEqual(read(q, req)["original"][field], raw)
                original[field] = raw.rstrip("\n")  # 相同 JSON，不同原件字节
                with self.assertRaisesRegex(economic_query.EconomicQueryError, "不符"):
                    read(q, req)


class ProjectionR4CounterexampleTests(unittest.TestCase):
    """#1425 R4 独审反例锁：固定向量跨域前沿、非目标域错根、原件权限隔离、能力实测与旧快照/Watch 兼容。"""

    def _make_query(self, ops=None):
        import tempfile
        from pathlib import Path
        self._tmp = tempfile.TemporaryDirectory(prefix="r4-proj-")
        root = Path(self._tmp.name)
        src = {"source_namespace": "q-ns", "source_epoch": "1", "producer_id": "reader", "producer_epoch": "1"}
        ops = ops or [
            "ReadView", "Watch", "QueryFact", "QueryAllocation", "QueryDecision",
            "QueryGrant", "QueryCommand", "EconomicReadOpen", "EconomicReadPage", "EconomicReadClose",
        ]
        manifest = {
            "schema_revision": "economic-manifest/1",
            "protocol_revision": "economic-session/1",
            "book_revision": "tb03c-book/1",
            "finance": {"schema_revision": "tb03b-finance/6"},
            "session_id": "sess-r4",
            "session_generation": "1",
            "authorized_sources": [{**src, "operations": ops}],
            "e": {"socket": str(root / "e.sock")},
            "chongs": [
                {"chong_id": "alpha", "socket": str(root / "alpha.sock")},
                {"chong_id": "beta", "socket": str(root / "beta.sock")},
            ],
        }
        (root / "manifest.json").write_bytes(canonical(manifest))
        cfg = {
            "schema_revision": "economic-query/1",
            "manifest": "manifest.json",
            "manifest_hash": digest(manifest),
            "query_source": src,
            "producer_epoch": "1",
            "expected_epochs": {"E": "1", "B:alpha": "1", "B:beta": "1"},
            "resources": {
                "max_frame_bytes": "1048576", "timeout_ms": "1000", "operation_timeout_ms": "4000",
                "max_reply_bytes": "1048576", "max_cached_bytes": "4194304",
                "max_snapshots": "4", "max_domains": "3", "max_changes": "10",
            },
        }
        (root / "query.json").write_bytes(canonical(cfg))
        return economic_query.EconomicQuery(root / "query.json")

    def tearDown(self):
        if hasattr(self, "_tmp"):
            self._tmp.cleanup()

    def _cut(self, domain, seq, tag="ok"):
        return {"domain_id": domain, "commit_seq": str(seq), "root_hash": digest([domain, str(seq), tag])}

    def _proj_view(self, q, domain, cut_obj):
        proj = {
            "book": None, "recorded": [], "pending": [], "applied": [], "unmatched": [], "history": [],
            "finance": {
                "schema_revision": "tb03b-finance/6",
                "rights": [], "decisions": [], "slots": [], "responsibilities": [], "commands": [],
            },
        }
        enc = canonical(proj)
        return {
            "kind": "EconomicProjectionView",
            "projection_revision": ECONOMIC_PROJECTION_REVISION,
            "domain_id": domain,
            "session_id": q.session,
            "session_generation": q.generation,
            "cut": cut_obj,
            "commit_ns": cut_obj["commit_seq"],
            "writer_epoch": q.epochs[domain],
            "audit_verified": True,
            "authoritative_image_hash": digest(["auth", domain, cut_obj["commit_seq"]]),
            "authoritative_image_bytes": "1024",
            "projection_hash": hashlib.sha256(enc).hexdigest(),
            "projection_bytes": str(len(enc)),
            "omitted_peer_images": [],
            "projection": proj,
            "runtime": {},
        }

    def test_r4_2_rejects_e6_vector_returning_e8_receipt_and_non_target_wrong_root_while_e10_succeeds(self):
        q = self._make_query()
        real_cuts = {
            ("E", "6"): self._cut("E", 6),
            ("E", "8"): self._cut("E", 8),
            ("E", "10"): self._cut("E", 10),
            ("B:alpha", "5"): self._cut("B:alpha", 5),
            ("B:alpha", "6"): self._cut("B:alpha", 6),
            ("B:beta", "4"): self._cut("B:beta", 4),
        }
        raw_fee = '{"kind":"fee","amount":1}'
        raw_sha = hashlib.sha256(raw_fee.encode("utf-8")).hexdigest()
        b6_original = {
            "kind": "EconomicAllocationAtCut",
            "domain_id": "B:alpha",
            "allocation_id": "sim-command-fee:1",
            "applied_entry": {"allocation_id": "sim-command-fee:1", "fact_key": "f" * 64, "fact_hash": "e" * 64},
            "application": {"allocation_id": "sim-command-fee:1"},
            "receipt": {"kind": "Applied", "domain_id": "B:alpha", "cut": real_cuts[("B:alpha", "6")]},
            "fact_ref": {"fact_key": "f" * 64, "fact_hash": "e" * 64},
            "fact": {
                "kind": "EconomicFactAtCut",
                "domain_id": "B:alpha",
                "fact_key": "f" * 64,
                "fact_hash": "e" * 64,
                "raw_sha256": raw_sha,
                "json_pointer": "/event",
                "raw_utf8": raw_fee,
                "raw_exact_text": {
                    "representation": "ExactDecimalIntegerTextProjection",
                    "raw_sha256": raw_sha,
                    "value": {"kind": "fee", "amount": "1"},
                },
                "projected_record": {
                    "cut": real_cuts[("E", "8")],
                    "e_receipt": {"kind": "Recorded", "domain_id": "E", "cut": real_cuts[("E", "8")]},
                    "e_resolution_proof": {
                        "receipt": {"kind": "Resolved", "domain_id": "E", "cut": real_cuts[("E", "10")]},
                    },
                },
                "receipts": [
                    {"kind": "Recorded", "domain_id": "E", "cut": real_cuts[("E", "8")]},
                    {"kind": "Applied", "domain_id": "B:alpha", "cut": real_cuts[("B:alpha", "6")]},
                ],
            },
        }
        calls = []

        def fake_owner(domain, payload):
            calls.append((domain, payload["op"], payload.get("cut")))
            req_cut = payload.get("cut")
            expected = real_cuts.get((domain, req_cut["commit_seq"])) if req_cut else None
            if expected is None or req_cut != expected:
                raise economic_query.EconomicQueryError("IdentityConflict：cut根不匹配")
            if payload["op"] == "ReadProjection":
                return self._proj_view(q, domain, expected)
            if payload["op"] == "ReadOriginalAtCut":
                return {
                    "kind": "EconomicOriginalAtCut",
                    "projection_revision": ECONOMIC_PROJECTION_REVISION,
                    "domain_id": domain,
                    "session_id": q.session,
                    "session_generation": q.generation,
                    "cut": expected,
                    "commit_ns": expected["commit_seq"],
                    "writer_epoch": q.epochs[domain],
                    "audit_verified": True,
                    "authoritative_image_hash": digest(["auth", domain, expected["commit_seq"]]),
                    "authoritative_image_bytes": "6800000",
                    "original_kind": payload["kind"],
                    "object_id": payload["object_id"],
                    "original": b6_original,
                }
            raise AssertionError(payload)

        q.owner = fake_owner

        # 反例 2A（REVIEW #2）：真实 E:6 / B:alpha:6 / B:beta:4 不得返回 E:8 Recorded！
        cuts_e6 = {"E": real_cuts[("E", "6")], "B:alpha": real_cuts[("B:alpha", "6")], "B:beta": real_cuts[("B:beta", "4")]}
        with self.assertRaisesRegex(economic_query.EconomicQueryError, "E:8.*晚于固定切面.*E:6"):
            q.projection_original({
                "op": "projection_original", "projection_revision": ECONOMIC_PROJECTION_REVISION,
                "domain_id": "B:alpha", "kind": "allocation", "object_id": "sim-command-fee:1", "cuts": cuts_e6,
            })

        # 反例 2B（REVIEW #2）：非目标域 B:beta 错根必须被拒绝！
        cuts_bad_beta = {
            "E": real_cuts[("E", "10")],
            "B:alpha": real_cuts[("B:alpha", "6")],
            "B:beta": self._cut("B:beta", 4, tag="forged-wrong-root"),
        }
        with self.assertRaisesRegex(economic_query.EconomicQueryError, "非目标域 B:beta"):
            q.projection_original({
                "op": "projection_original", "projection_revision": ECONOMIC_PROJECTION_REVISION,
                "domain_id": "B:alpha", "kind": "allocation", "object_id": "sim-command-fee:1", "cuts": cuts_bad_beta,
            })

        # 正例：E:10 / B:alpha:6 / B:beta:4 全部实核且 E:8 / E:10 <= E:10，应成功！
        cuts_e10 = {"E": real_cuts[("E", "10")], "B:alpha": real_cuts[("B:alpha", "6")], "B:beta": real_cuts[("B:beta", "4")]}
        ok = q.projection_original({
            "op": "projection_original", "projection_revision": ECONOMIC_PROJECTION_REVISION,
            "domain_id": "B:alpha", "kind": "allocation", "object_id": "sim-command-fee:1", "cuts": cuts_e10,
        })
        self.assertEqual(ok["kind"], "EconomicProjectionOriginal")
        self.assertEqual(ok["cuts"], cuts_e10)

    def test_r4_3_q_enforces_per_kind_authorization_and_allocation_without_query_fact(self):
        q = self._make_query(ops=["ReadView", "Watch", "QueryAllocation", "EconomicReadOpen", "EconomicReadPage", "EconomicReadClose"])
        self.assertEqual(q.projection_original_kinds, ("allocation",))
        cuts = {"E": self._cut("E", 10), "B:alpha": self._cut("B:alpha", 6), "B:beta": self._cut("B:beta", 4)}
        # 无 QueryFact 时不得查询 fact 或 model
        with self.assertRaisesRegex(economic_query.EconomicQueryError, "未获准"):
            q.projection_original({
                "op": "projection_original", "projection_revision": ECONOMIC_PROJECTION_REVISION,
                "domain_id": "E", "kind": "fact", "object_id": "a" * 64, "cuts": cuts,
            })
        # 仅 QueryAllocation 时，allocation 可只返回 fact_ref 且 fact=None；若 owner 夹带 fact 原字节则拒！
        q._verified_vector_cached = lambda c: True
        base_reply = {
            "kind": "EconomicOriginalAtCut", "projection_revision": ECONOMIC_PROJECTION_REVISION,
            "domain_id": "B:alpha", "session_id": q.session, "session_generation": q.generation,
            "cut": cuts["B:alpha"], "commit_ns": "6", "writer_epoch": "1", "audit_verified": True,
            "authoritative_image_hash": "2" * 64, "authoritative_image_bytes": "6800000",
            "original_kind": "allocation", "object_id": "aid-1",
            "original": {
                "kind": "EconomicAllocationAtCut", "domain_id": "B:alpha", "allocation_id": "aid-1",
                "receipt": {"kind": "Applied", "domain_id": "B:alpha", "cut": cuts["B:alpha"]},
                "fact_ref": {"fact_key": "a" * 64, "fact_hash": "b" * 64},
                "fact": None,
            },
        }
        q.owner = lambda d, p: base_reply
        got = q.projection_original({
            "op": "projection_original", "projection_revision": ECONOMIC_PROJECTION_REVISION,
            "domain_id": "B:alpha", "kind": "allocation", "object_id": "aid-1", "cuts": cuts,
        })
        self.assertIsNone(got["original"]["fact"])
        self.assertEqual(got["original"]["fact_ref"]["fact_key"], "a" * 64)

        leaked = dict(base_reply, original={**base_reply["original"], "fact": {"raw_utf8": "{}", "raw_sha256": "0" * 64}})
        q.owner = lambda d, p: leaked
        with self.assertRaisesRegex(economic_query.EconomicQueryError, "QueryFact"):
            q.projection_original({
                "op": "projection_original", "projection_revision": ECONOMIC_PROJECTION_REVISION,
                "domain_id": "B:alpha", "kind": "allocation", "object_id": "aid-1", "cuts": cuts,
            })

    def test_r4_5_discovery_probes_owners_and_does_not_claim_projection_on_old_fin6_owner(self):
        from unittest.mock import patch
        from s_socket_client import reply_envelope
        q = self._make_query()

        # 旧 FIN/6 owner（同名配置、有分页权限，但拒绝 ReadProjection）→ 不得宣称有投影！
        def old_owner_exchange(socket_path, request, **kwargs):
            domain = "E" if socket_path.endswith("e.sock") else ("B:alpha" if socket_path.endswith("alpha.sock") else "B:beta")
            err = {
                "schema_revision": ECONOMIC_PAGE_REVISION,
                "kind": "EconomicReadError",
                "code": "SchemaUnsupported",
                "detail": "SchemaUnsupported：分页只接受ReadView/Watch",
                "transfer_id": None,
            }
            return {
                "transport": "Received",
                "response": reply_envelope(
                    request, err, session_id=q.session, session_generation=q.generation,
                    namespace="economic-session/replies", producer_id=domain + ":" + q.session,
                    producer_epoch=q.epochs[domain],
                ),
            }

        with patch("economic_query.exchange", side_effect=old_owner_exchange):
            self.assertIsNone(q.discover_read_projection())

        # 新 FIN/6 owner（Open 返回 EconomicProjectionView 描述符并可 Close）→ 宣称能力与可用动作（watch_supported=False）！
        def new_owner_exchange(socket_path, request, **kwargs):
            domain = "E" if socket_path.endswith("e.sock") else ("B:alpha" if socket_path.endswith("alpha.sock") else "B:beta")
            op = request["payload"]["op"]
            if op == "EconomicReadOpen":
                desc = {
                    "schema_revision": ECONOMIC_PAGE_REVISION, "transfer_id": "0" * 32,
                    "session_id": q.session, "session_generation": q.generation,
                    "manifest_hash": q.manifest_hash, "producer_id": domain + ":" + q.session,
                    "producer_epoch": q.epochs[domain], "query_sha256": digest(request["payload"]["query"]),
                    "document_kind": "EconomicProjectionView", "fixed_cuts": {domain: self._cut(domain, 1)},
                    "owner_epochs": {domain: q.epochs[domain]}, "document_bytes": "128",
                    "document_sha256": "1" * 64, "chunk_bytes": "262144", "page_count": "1",
                }
                payload = {
                    "schema_revision": ECONOMIC_PAGE_REVISION, "kind": "EconomicReadOpened",
                    "descriptor": desc, "descriptor_sha256": digest(desc),
                }
            else:
                payload = {
                    "schema_revision": ECONOMIC_PAGE_REVISION, "kind": "EconomicReadClosed",
                    "transfer_id": request["payload"]["transfer_id"],
                    "descriptor_sha256": request["payload"]["descriptor_sha256"],
                }
            return {
                "transport": "Received",
                "response": reply_envelope(
                    request, payload, session_id=q.session, session_generation=q.generation,
                    namespace="economic-session/replies", producer_id=domain + ":" + q.session,
                    producer_epoch=q.epochs[domain],
                ),
            }

        with patch("economic_query.exchange", side_effect=new_owner_exchange):
            cap = q.discover_read_projection()
            self.assertIsNotNone(cap)
            self.assertEqual(cap["schema_revision"], ECONOMIC_PROJECTION_REVISION)
            self.assertFalse(cap["watch_supported"])
            self.assertEqual(cap["available_actions"], ["projection", "projection_original"])
            self.assertEqual(cap["original_kinds"], ["fact", "allocation", "decision", "grant", "command", "model"])


class R5ReadEntryEnumerationAndBudgetTests(unittest.TestCase):
    """#1425 R5：从路由表/分发表动态枚举全部读侧入口，验证不变量 A、不变量 B 与历史根共享缓存预算。"""

    def setUp(self):
        self._msg_seq = 0
        self._tmps = []

    def tearDown(self):
        for tmp in reversed(self._tmps):
            tmp.cleanup()

    def _make_query(self, ops=None):
        import tempfile
        from pathlib import Path
        tmp = tempfile.TemporaryDirectory(prefix="r5-proj-")
        self._tmps.append(tmp)
        root = Path(tmp.name)
        src = {"source_namespace": "q-ns", "source_epoch": "1", "producer_id": "reader", "producer_epoch": "1"}
        ops = ops or [
            "ReadView", "Watch", "QueryFact", "QueryAllocation", "QueryDecision",
            "QueryGrant", "QueryCommand", "EconomicReadOpen", "EconomicReadPage", "EconomicReadClose",
        ]
        manifest = {
            "schema_revision": "economic-manifest/1",
            "protocol_revision": "economic-session/1",
            "book_revision": "tb03c-book/1",
            "finance": {"schema_revision": "tb03b-finance/6"},
            "session_id": "sess-r5",
            "session_generation": "1",
            "authorized_sources": [{**src, "operations": ops}],
            "e": {"socket": str(root / "e.sock")},
            "chongs": [
                {"chong_id": "alpha", "socket": str(root / "alpha.sock")},
                {"chong_id": "beta", "socket": str(root / "beta.sock")},
            ],
        }
        (root / "manifest.json").write_bytes(canonical(manifest))
        cfg = {
            "schema_revision": "economic-query/1",
            "manifest": "manifest.json",
            "manifest_hash": digest(manifest),
            "query_source": src,
            "producer_epoch": "1",
            "expected_epochs": {"E": "1", "B:alpha": "1", "B:beta": "1"},
            "resources": {
                "max_frame_bytes": "1048576", "timeout_ms": "1000", "operation_timeout_ms": "4000",
                "max_reply_bytes": "1048576", "max_cached_bytes": "4194304",
                "max_snapshots": "4", "max_domains": "3", "max_changes": "10",
            },
        }
        (root / "query.json").write_bytes(canonical(cfg))
        return economic_query.EconomicQuery(root / "query.json")

    def _cut(self, domain, seq, tag="ok"):
        return {"domain_id": domain, "commit_seq": str(seq), "root_hash": digest([domain, str(seq), tag])}

    def _enumerated_http_entries(self):
        import economic_http
        entries = []
        for path, op in economic_http.ECONOMIC_POST_ROUTES.items():
            if op == "read":
                for lop, (_, paged_ok, _) in economic_query.EconomicQuery.PUBLIC_READ_DISPATCH.items():
                    if paged_ok:
                        entries.append((path, lop))
            else:
                entries.append((path, op))
        return entries

    def _call_http_entry(self, q, path, payload, *, paged=False):
        import io
        from types import SimpleNamespace
        import economic_http
        from s_socket_client import decode_frame, validate_reply

        def send_once(body_payload):
            self._msg_seq += 1
            req = {
                "schema_revision": q.protocol_revision,
                "session_id": q.session,
                "session_generation": q.generation,
                **q.source,
                "message_id": f"enum-{self._msg_seq}",
                "causal_refs": [],
                "payload": body_payload,
                "payload_hash": digest(body_payload),
            }
            raw = canonical(req)
            sent = []
            handler = SimpleNamespace(
                path=path,
                rfile=io.BytesIO(raw),
                headers=SimpleNamespace(get_all=lambda name, default: [str(len(raw))], get=lambda name: None),
                connection=SimpleNamespace(settimeout=lambda seconds: None),
                server=SimpleNamespace(
                    economic_query=q,
                    resources={
                        "max_frame_bytes": q.resources["max_frame_bytes"],
                        "max_reply_bytes": q.resources["max_reply_bytes"],
                        "socket_read_timeout_ms": q.resources["timeout_ms"],
                    },
                ),
                _send_json=lambda value, status=200: sent.append((value, status)),
                _send_bytes=lambda value, status=200: sent.append((decode_frame(value), status)),
            )
            self.assertTrue(economic_http.post(handler), f"route {path} not handled")
            resp, status = sent[0]
            if status != 200:
                raise economic_query.EconomicQueryError(resp.get("detail") or resp.get("error") or str(resp))
            reply_payload = validate_reply(req, resp, producer="Q", producer_epoch=q.query_epoch)
            if reply_payload.get("ok") is False or "error" in reply_payload:
                raise economic_query.EconomicQueryError(reply_payload.get("detail") or reply_payload.get("error"))
            return reply_payload

        if paged:
            return read_economic_pages(
                payload,
                lambda page_payload, _rem: send_once(page_payload),
                session_id=q.session,
                session_generation=q.generation,
                producer_id="Q:" + q.session,
                producer_epoch=q.query_epoch,
                manifest_hash=q.manifest_hash,
                owner_epochs=q.epochs,
                deadline=time.monotonic() + 10,
            )
        return send_once(payload)

    def _build_fixture_store(self, q, *, redact_witness_for_no_cmd=True):
        real_cuts = {
            ("E", "4"): self._cut("E", 4),
            ("E", "5"): self._cut("E", 5),
            ("E", "6"): self._cut("E", 6),
            ("E", "8"): self._cut("E", 8),
            ("E", "10"): self._cut("E", 10),
            ("B:alpha", "4"): self._cut("B:alpha", 4),
            ("B:alpha", "5"): self._cut("B:alpha", 5),
            ("B:alpha", "6"): self._cut("B:alpha", 6),
            ("B:beta", "4"): self._cut("B:beta", 4),
        }
        model_obj = {"model_id": "m1", "revision": "r1"}
        model_raw = canonical(model_obj).decode("utf-8")
        model_hash = hashlib.sha256(model_raw.encode("utf-8")).hexdigest()
        fee_doc = {
            "format": "history-sim-economic-originals/1",
            "model": model_obj,
            "model_content_hash": model_hash,
            "event": {"kind": "fee", "command_id": "cmd-alpha", "amount": 1},
        }
        raw_fee = canonical(fee_doc).decode("utf-8")
        raw_sha = hashlib.sha256(raw_fee.encode("utf-8")).hexdigest()
        fk = "f" * 64
        fh = "e" * 64
        aid = "sim-command-fee:1"
        full_cmd = {"command_id": "cmd-alpha", "allocation_id": "alloc-alpha", "model_ref": {"model_id": "m1", "revision": "r1", "content_hash": model_hash}, "secret": "full-e-cmd"}
        cmd_hash = digest(full_cmd)
        cmd_record = {"decision_id": "alpha", "command_id": "cmd-alpha", "state": "ReleasedExact", "command": full_cmd}

        def make_witness(include_cmd):
            rel_ev = {
                "protocol": "x-exact-authority/1", "session_id": q.session, "session_generation": q.generation,
                "authority_id": "E", "command_id": "cmd-alpha", "command_hash": cmd_hash,
                "state": "ReleasedExact", "receipt_id": "rel-1", "release_receipt_id": None, "commit_ns": "2",
            }
            exec_reply = {
                "protocol": "x-exact-authority/1", "session_id": q.session, "session_generation": q.generation,
                "authority_id": "S", "command_id": "cmd-alpha", "command_hash": cmd_hash,
                "state": "ExecuteCommitted", "receipt_id": "elig-1", "release_receipt_id": "rel-1", "commit_ns": "2",
            }
            if include_cmd:
                rel_ev["command"] = full_cmd
                exec_reply["command"] = full_cmd
            else:
                rel_ev["command_ref"] = {"command_id": "cmd-alpha", "command_hash": cmd_hash}
                exec_reply["command_ref"] = {"command_id": "cmd-alpha", "command_hash": cmd_hash}
            return {
                "witness_revision": "x-sim-execution-witness/1",
                "x_profile_revision": "x-execution-profile/3",
                "x_id": "X", "x_epoch": "1", "session_id": q.session, "session_generation": q.generation,
                "source_namespace": "x-sim", "source_epoch": "1", "model_content_hash": model_hash,
                "command_id": "cmd-alpha", "command_hash": cmd_hash,
                "e_release_receipt_key": "rel-1", "e_release_cut": real_cuts[("E", "6")], "e_release_commit_ns": "2",
                "x_release_evidence": rel_ev,
                "x_accept_clock": {"received_ns": "2", "first_known_ns": "2", "commit_ns": "2"},
                "x_command_state": "Observed",
                "x_execute_evidence": {"claimed_ns": "2", "reply": exec_reply},
                "attempt_batch_id": "b2", "attempt_batch_bar_index": "2",
                "attempt_batch_request_sha256": "1" * 64, "attempt_batch_receipt_sha256": "2" * 64,
                "originals_batch_id": "b3", "originals_batch_bar_index": "3",
                "originals_batch_receipt_sha256": "3" * 64, "fact_raw_sha256": raw_sha,
            }

        b6_recorded_item = {
            "fact_key": fk,
            "fact_hash": fh,
            "raw_sha256": raw_sha,
            "json_pointer": "/event",
            "raw_utf8": raw_fee,
            "cut": real_cuts[("E", "8")],
            "e_receipt": {"kind": "Recorded", "domain_id": "E", "fact_key": fk, "cut": real_cuts[("E", "8")]},
            "e_resolution_proof": {
                "receipt": {"kind": "Resolved", "domain_id": "E", "evidence_id": "ev-fee", "cut": real_cuts[("E", "10")]},
            },
            "event": {"event": "history-sim-unresolved/1"},
        }

        def domain_image(domain, seq):
            fin = {
                "schema_revision": "tb03b-finance/6",
                "rights": [], "decisions": [], "slots": [], "responsibilities": [], "commands": [],
            }
            img = {"book": None, "recorded": [], "pending": [], "applied": [], "unmatched": [], "history": [], "finance": fin}
            if domain == "B:alpha" and seq == "6":
                img["recorded"] = [b6_recorded_item]
                img["finance"]["decisions"] = [{"decision_id": "alpha", "state": "Committed", "grant": {"e_cut": real_cuts[("E", "8")]}}]
            elif domain == "E" and seq in ("6", "8", "10"):
                img["finance"]["commands"] = [cmd_record]
                img["history"] = [
                    {"kind": "MakeDispatchable", "record": cmd_record, "commit_seq": "5", "commit_ns": "5", "first_known_ns": "5"},
                    {"kind": "ReleaseExact", "record": cmd_record, "commit_seq": "6", "commit_ns": "6", "first_known_ns": "6"},
                ]
            return img

        def fake_owner(domain, payload):
            op = payload["op"]
            if op == "ReadView":
                req_cut = payload["cut"] or real_cuts[(domain, "6" if domain != "B:beta" else "4")]
                expected = real_cuts.get((domain, req_cut["commit_seq"]))
                if expected is None or req_cut != expected:
                    raise economic_query.EconomicQueryError("IdentityConflict：cut根不匹配")
                img = domain_image(domain, expected["commit_seq"])
                return {"kind": "EconomicView", "domain_id": domain, "cut": expected, "commit_ns": expected["commit_seq"],
                        "image": img, "image_hash": digest(img)}
            if op == "Watch":
                after = payload["after_cut"]
                if domain == "B:alpha" and after["commit_seq"] == "5":
                    img6 = domain_image("B:alpha", "6")
                    return {"kind": "EconomicChanges", "domain_id": domain, "cut": real_cuts[("B:alpha", "6")],
                            "changes": [{"cut": real_cuts[("B:alpha", "6")], "image": img6, "image_hash": digest(img6), "commit_ns": "6"}]}
                if domain == "E" and after["commit_seq"] == "4":
                    img5 = domain_image("E", "5")
                    return {"kind": "EconomicChanges", "domain_id": domain, "cut": real_cuts[("E", "5")],
                            "changes": [{"cut": real_cuts[("E", "5")], "image": img5, "image_hash": digest(img5), "commit_ns": "5"}]}
                return {"kind": "EconomicChanges", "domain_id": domain, "cut": after, "changes": []}
            if op == "QueryDecision":
                return {
                    "kind": "EconomicDecision", "domain_id": domain,
                    "decision": {"decision_id": "alpha", "state": "Committed", "grant": {"e_cut": real_cuts[("E", "8")]}},
                    "receipts": [{"kind": "LocalCommitReceipt", "domain_id": domain, "cut": real_cuts[(domain, "6")]}],
                }
            if op == "ReadProjection":
                req_cut = payload["cut"] or real_cuts[(domain, "10" if domain == "E" else ("6" if domain == "B:alpha" else "4"))]
                expected = real_cuts.get((domain, req_cut["commit_seq"]))
                if expected is None or req_cut != expected:
                    raise economic_query.EconomicQueryError("IdentityConflict：cut根不匹配")
                img = domain_image(domain, expected["commit_seq"])
                enc = canonical(img)
                return {
                    "kind": "EconomicProjectionView", "projection_revision": ECONOMIC_PROJECTION_REVISION,
                    "domain_id": domain, "session_id": q.session, "session_generation": q.generation,
                    "cut": expected, "commit_ns": expected["commit_seq"], "writer_epoch": q.epochs[domain],
                    "audit_verified": True, "authoritative_image_hash": digest(["auth", domain, expected["commit_seq"]]),
                    "authoritative_image_bytes": "1024", "projection_hash": hashlib.sha256(enc).hexdigest(),
                    "projection_bytes": str(len(enc)), "omitted_peer_images": [], "projection": img, "runtime": {},
                }
            if op == "ReadOriginalAtCut":
                req_cut = payload["cut"]
                kind = payload["kind"]
                obj_id = payload["object_id"]
                has_cmd = "QueryCommand" in q.authorized_read_ops
                has_fact = "QueryFact" in q.authorized_read_ops
                has_alloc = "QueryAllocation" in q.authorized_read_ops
                if kind == "fact":
                    orig = {
                        "kind": "EconomicFactAtCut", "domain_id": domain, "fact_key": fk, "fact_hash": fh,
                        "raw_sha256": raw_sha, "json_pointer": "/event", "raw_utf8": raw_fee,
                        "raw_exact_text": {"representation": "ExactDecimalIntegerTextProjection", "raw_sha256": raw_sha, "value": fee_doc},
                        "projected_record": b6_recorded_item,
                        "fill_allocation_row": None,
                        "receipts": [
                            {"kind": "Recorded", "domain_id": "E", "cut": real_cuts[("E", "8")]},
                            {"kind": "Applied", "domain_id": "B:alpha", "cut": real_cuts[("B:alpha", "6")]},
                        ] if domain == "B:alpha" else [{"kind": "Recorded", "domain_id": "E", "cut": real_cuts[("E", "8")]}],
                    }
                elif kind == "allocation":
                    if domain == "E":
                        orig = {
                            "kind": "EconomicAllocationAtCut", "domain_id": "E", "allocation_id": aid,
                            "fill_allocation_row": {
                                "fact_key": fk, "fact_hash": fh, "source_kind": "history_sim_fee",
                                "evidence_id": "ev-fee",
                                "x_execution_witness": make_witness(has_cmd or (not redact_witness_for_no_cmd)),
                                "allocations": [{"allocation_id": aid, "chong_id": "alpha"}],
                            },
                            "resolve_receipt": {"kind": "Resolved", "domain_id": "E", "cut": real_cuts[("E", "10")]},
                            "fact_ref": {"fact_key": fk, "fact_hash": fh},
                            "fact": None if not has_fact else {
                                "kind": "EconomicFactAtCut", "domain_id": "E", "fact_key": fk, "fact_hash": fh,
                                "raw_sha256": raw_sha, "json_pointer": "/event", "raw_utf8": raw_fee,
                                "raw_exact_text": {"representation": "ExactDecimalIntegerTextProjection", "raw_sha256": raw_sha, "value": fee_doc},
                                "projected_record": b6_recorded_item, "fill_allocation_row": None,
                                "receipts": [{"kind": "Recorded", "domain_id": "E", "cut": real_cuts[("E", "8")]}],
                            },
                        }
                    else:
                        orig = {
                            "kind": "EconomicAllocationAtCut", "domain_id": "B:alpha", "allocation_id": aid,
                            "applied_entry": {"allocation_id": aid, "fact_key": fk, "fact_hash": fh},
                            "application": {"allocation_id": aid},
                            "receipt": {"kind": "Applied", "domain_id": "B:alpha", "cut": real_cuts[("B:alpha", "6")]},
                            "fact_ref": {"fact_key": fk, "fact_hash": fh},
                            "fact": None if not has_fact else {
                                "kind": "EconomicFactAtCut", "domain_id": "B:alpha", "fact_key": fk, "fact_hash": fh,
                                "raw_sha256": raw_sha, "json_pointer": "/event", "raw_utf8": raw_fee,
                                "raw_exact_text": {"representation": "ExactDecimalIntegerTextProjection", "raw_sha256": raw_sha, "value": fee_doc},
                                "projected_record": b6_recorded_item, "fill_allocation_row": None,
                                "receipts": [
                                    {"kind": "Recorded", "domain_id": "E", "cut": real_cuts[("E", "8")]},
                                    {"kind": "Applied", "domain_id": "B:alpha", "cut": real_cuts[("B:alpha", "6")]},
                                ],
                            },
                        }
                elif kind == "model":
                    if obj_id == "cmd-alpha" and not has_cmd:
                        raise economic_query.EconomicQueryError("InvalidDomain：未获准 QueryCommand")
                    if obj_id == fk and not has_fact:
                        raise economic_query.EconomicQueryError("InvalidDomain：未获准 QueryFact")
                    orig = {
                        "kind": "EconomicModelAtCut", "domain_id": domain, "object_id": obj_id,
                        "model_ref": {"model_id": "m1", "revision": "r1", "content_hash": model_hash},
                        "model_raw_utf8": model_raw if has_fact else None,
                        "model_exact_text": {"representation": "ExactDecimalIntegerTextProjection", "content_hash": model_hash, "value": model_obj} if has_fact else None,
                        "source_fact_key": fk if has_fact else None,
                    }
                elif kind == "command":
                    if not has_cmd:
                        raise economic_query.EconomicQueryError("InvalidDomain：未获准 QueryCommand")
                    orig = {
                        "kind": "EconomicCommand", "domain_id": "E", "command_id": "cmd-alpha",
                        "state": "ReleasedExact", "record": cmd_record, "cut": req_cut,
                        "receipts": [{"kind": "ReleasedExactReceipt", "domain_id": "E", "cut": real_cuts[("E", "6")]}],
                    }
                else:
                    orig = {"kind": "EconomicDecision", "domain_id": domain, "decision": {"decision_id": "alpha"}, "receipts": [{"kind": "LocalCommitReceipt", "domain_id": domain, "cut": real_cuts[(domain, "6")]}]}
                return {
                    "kind": "EconomicOriginalAtCut", "projection_revision": ECONOMIC_PROJECTION_REVISION,
                    "domain_id": domain, "session_id": q.session, "session_generation": q.generation,
                    "cut": req_cut, "commit_ns": req_cut["commit_seq"], "writer_epoch": q.epochs[domain],
                    "audit_verified": True, "authoritative_image_hash": digest(["auth", domain, req_cut["commit_seq"]]),
                    "authoritative_image_bytes": "2048", "original_kind": kind, "object_id": obj_id, "original": orig,
                }
            raise AssertionError(f"unexpected owner op: {payload}")

        return real_cuts, fk, aid, fake_owner

    def test_enumerates_every_read_entry_from_routes_and_dispatch_for_invariant_a_and_mutation_sensitivity(self):
        q = self._make_query()
        real_cuts, fk, aid, fake_owner = self._build_fixture_store(q)
        q.owner = fake_owner

        cuts_e6 = {"E": real_cuts[("E", "6")], "B:alpha": real_cuts[("B:alpha", "6")], "B:beta": real_cuts[("B:beta", "4")]}
        cuts_watch_e6 = {"E": real_cuts[("E", "6")], "B:alpha": real_cuts[("B:alpha", "5")], "B:beta": real_cuts[("B:beta", "4")]}
        cuts_e10 = {"E": real_cuts[("E", "10")], "B:alpha": real_cuts[("B:alpha", "6")], "B:beta": real_cuts[("B:beta", "4")]}

        request_builders = {
            "snapshot": lambda: {"op": "snapshot", "cuts": cuts_e6, "as_known_ns": None, "snapshot_token": None},
            "watch": lambda: {"op": "watch", "cuts": cuts_watch_e6},
            "original": lambda: {"op": "original", "kind": "decision", "domain_id": "B:alpha", "object_id": "alpha", "cuts": cuts_e6},
            "projection": lambda: {"op": "projection", "projection_revision": ECONOMIC_PROJECTION_REVISION, "cuts": cuts_e6, "as_known_ns": None, "projection_token": None},
            "projection_original": lambda: {"op": "projection_original", "projection_revision": ECONOMIC_PROJECTION_REVISION, "domain_id": "B:alpha", "kind": "allocation", "object_id": aid, "cuts": cuts_e6},
        }

        entries = self._enumerated_http_entries()
        self.assertGreaterEqual(len(entries), 7)

        # Every single route+op exported by ECONOMIC_POST_ROUTES / PUBLIC_READ_DISPATCH MUST reject E:8/E:10 under E:6!
        for path, op in entries:
            self.assertIn(op, request_builders, f"新增读侧入口 ({path}, {op}) 未纳入不变量 A 枚举测试")
            paged = path == "/api/economic/read"
            with self.subTest(path=path, op=op, paged=paged):
                with self.assertRaisesRegex(ValueError, r"MissingDependency.*E:8.*晚于固定切面.*E:6"):
                    self._call_http_entry(q, path, request_builders[op](), paged=paged)

        # Positive controls for EVERY enumerated HTTP entry (all 7 route+op pairs):
        # E:10 / B:alpha:6 / B:beta:4 succeeds for snapshot, original, projection, projection_original (single & paged);
        # E:4->E:5 watch succeeds for single-frame & paged!
        positive_builders = {
            "snapshot": lambda: {"op": "snapshot", "cuts": cuts_e10, "as_known_ns": None, "snapshot_token": None},
            "watch": lambda: {"op": "watch", "cuts": {"E": real_cuts[("E", "4")], "B:alpha": real_cuts[("B:alpha", "4")], "B:beta": real_cuts[("B:beta", "4")]}},
            "original": lambda: {"op": "original", "kind": "decision", "domain_id": "B:alpha", "object_id": "alpha", "cuts": cuts_e10},
            "projection": lambda: {"op": "projection", "projection_revision": ECONOMIC_PROJECTION_REVISION, "cuts": cuts_e10, "as_known_ns": None, "projection_token": None},
            "projection_original": lambda: {"op": "projection_original", "projection_revision": ECONOMIC_PROJECTION_REVISION, "domain_id": "B:alpha", "kind": "allocation", "object_id": aid, "cuts": cuts_e10},
        }
        for path, op in entries:
            paged = path == "/api/economic/read"
            with self.subTest(positive_path=path, op=op, paged=paged):
                ok = self._call_http_entry(q, path, positive_builders[op](), paged=paged)
                if op == "projection":
                    self.assertEqual(ok["projection_completeness"], "CompleteProjectionVector")
                elif op == "snapshot":
                    self.assertEqual(ok["completeness"], "CompleteVector")
                elif op == "watch":
                    self.assertEqual(ok["domains"]["E"]["next_cut"]["commit_seq"], "5")
                elif op == "original":
                    self.assertEqual(ok["kind"], "EconomicOriginal")
                elif op == "projection_original":
                    self.assertEqual(ok["kind"], "EconomicProjectionOriginal")

        # Dispatcher enforcement proof: even if an existing handler is replaced with one that skips _finalize_public_response,
        # dispatch_public_read STILL calls _finalize_public_response and blocks future receipts!
        from unittest.mock import patch
        sample_snap = q.snapshot({"op": "snapshot", "cuts": cuts_e10, "as_known_ns": None, "snapshot_token": None})
        with patch.object(q, "snapshot", return_value=sample_snap), \
             patch.object(economic_query, "_finalize_public_response", wraps=economic_query._finalize_public_response) as spy:
            q.dispatch_public_read("snapshot", {"op": "snapshot", "cuts": cuts_e10, "as_known_ns": None, "snapshot_token": None})
            self.assertGreaterEqual(spy.call_count, 1)

        # Mutation sensitivity proof: if a newly added read entry bypasses _finalize_public_response,
        # the enumeration check catches it as uncovered AND fails the MissingDependency assertion when bypassing dispatch!
        import economic_http
        orig_dispatch = dict(economic_query.EconomicQuery.PUBLIC_READ_DISPATCH)
        orig_routes = dict(economic_http.ECONOMIC_POST_ROUTES)
        try:
            leaky_doc = {
                "kind": "EconomicProjection", "cuts": cuts_e6,
                "domains": {
                    "E": {"status": "Available", "cut": cuts_e6["E"], "projection": {}},
                    "B:alpha": {"status": "Available", "cut": cuts_e6["B:alpha"], "projection": {"recorded": [{"e_receipt": {"kind": "Recorded", "domain_id": "E", "cut": real_cuts[("E", "8")]}}]}},
                    "B:beta": {"status": "Available", "cut": cuts_e6["B:beta"], "projection": {}},
                },
            }
            q.leaky_new_entry = lambda payload: leaky_doc
            economic_query.EconomicQuery.PUBLIC_READ_DISPATCH["leaky_new_entry"] = ("leaky_new_entry", False, True)
            economic_http.ECONOMIC_POST_ROUTES["/api/economic/leaky_new_entry"] = "leaky_new_entry"
            mutated_entries = self._enumerated_http_entries()
            self.assertIn(("/api/economic/leaky_new_entry", "leaky_new_entry"), mutated_entries)
            # 1) Fails because new entry isn't covered in request_builders
            uncovered = [e for e in mutated_entries if e[1] not in request_builders]
            self.assertEqual(uncovered, [("/api/economic/leaky_new_entry", "leaky_new_entry")])
            # 2) Routed through dispatch_public_read, the dispatcher exit itself rejects the leak!
            with self.assertRaisesRegex(ValueError, r"MissingDependency.*E:8.*晚于固定切面.*E:6"):
                self._call_http_entry(q, "/api/economic/leaky_new_entry", {"op": "leaky_new_entry"}, paged=False)
            # R5 原位置：即便整个回执藏在新应答的未知顶层字段，也不得出 Q。
            q.leaky_new_entry = lambda payload: {
                "kind": "EconomicProjection", "cuts": cuts_e6,
                "leaked_receipt": {"kind": "Recorded", "domain_id": "E", "cut": real_cuts["E", "8"]},
            }
            with self.assertRaisesRegex(ValueError, r"MissingDependency.*E:8.*晚于固定切面.*E:6"):
                self._call_http_entry(q, "/api/economic/leaky_new_entry", {"op": "leaky_new_entry", "cuts": cuts_e6}, paged=False)
            # 3) If a handler bypasses dispatch_public_read / _finalize_public_response, the assertion fails immediately!
            with patch.object(q, "dispatch_public_read", side_effect=lambda op, p, **kw: leaky_doc):
                with self.assertRaises(AssertionError):
                    with self.assertRaisesRegex(ValueError, r"MissingDependency"):
                        self._call_http_entry(q, "/api/economic/leaky_new_entry", {"op": "leaky_new_entry"}, paged=False)
        finally:
            economic_query.EconomicQuery.PUBLIC_READ_DISPATCH.clear()
            economic_query.EconomicQuery.PUBLIC_READ_DISPATCH.update(orig_dispatch)
            economic_http.ECONOMIC_POST_ROUTES.clear()
            economic_http.ECONOMIC_POST_ROUTES.update(orig_routes)

    def test_enumerates_three_single_permissions_for_invariant_b(self):
        base_ops = ["ReadView", "Watch", "EconomicReadOpen", "EconomicReadPage", "EconomicReadClose"]
        for perm in ("QueryCommand", "QueryFact", "QueryAllocation"):
            q = self._make_query(ops=base_ops + [perm])
            real_cuts, fk, aid, fake_owner = self._build_fixture_store(q, redact_witness_for_no_cmd=True)
            q.owner = fake_owner
            cuts_e10 = {"E": real_cuts[("E", "10")], "B:alpha": real_cuts[("B:alpha", "6")], "B:beta": real_cuts[("B:beta", "4")]}

            def ask(domain, kind, obj_id):
                return self._call_http_entry(q, "/api/economic/read", {
                    "op": "projection_original", "projection_revision": ECONOMIC_PROJECTION_REVISION,
                    "domain_id": domain, "kind": kind, "object_id": obj_id, "cuts": cuts_e10,
                }, paged=True)["original"]

            with self.subTest(single_permission=perm):
                if perm == "QueryCommand":
                    m = ask("E", "model", "cmd-alpha")
                    self.assertTrue(m["model_ref"])
                    self.assertIsNone(m["model_raw_utf8"])
                    c = ask("E", "command", "cmd-alpha")
                    self.assertEqual(c["kind"], "EconomicCommand")
                    for bad_kind, bad_id in (("fact", fk), ("allocation", aid), ("model", fk)):
                        with self.assertRaises(ValueError):
                            ask("E", bad_kind, bad_id)
                elif perm == "QueryFact":
                    m = ask("E", "model", fk)
                    self.assertTrue(m["model_raw_utf8"])
                    f = ask("E", "fact", fk)
                    self.assertIsNone(f["fill_allocation_row"])
                    for bad_kind, bad_id in (("command", "cmd-alpha"), ("allocation", aid), ("model", "cmd-alpha")):
                        with self.assertRaises(ValueError):
                            ask("E", bad_kind, bad_id)
                elif perm == "QueryAllocation":
                    a = ask("E", "allocation", aid)
                    self.assertIsNone(a["fact"])
                    self.assertEqual(a["fact_ref"]["fact_key"], fk)
                    w = a["fill_allocation_row"]["x_execution_witness"]
                    self.assertIsNone(w["x_release_evidence"].get("command"))
                    self.assertIsNone(w["x_execute_evidence"]["reply"].get("command"))
                    self.assertEqual(w["x_release_evidence"]["command_ref"]["command_id"], "cmd-alpha")
                    for bad_kind, bad_id in (("command", "cmd-alpha"), ("fact", fk), ("model", "cmd-alpha")):
                        with self.assertRaises(ValueError):
                            ask("E", bad_kind, bad_id)
                    # Even if a rogue owner tries to leak command inside witness, Q's single exit rejects it!
                    _, _, _, leaky_owner = self._build_fixture_store(q, redact_witness_for_no_cmd=False)
                    q.owner = leaky_owner
                    with self.assertRaisesRegex(ValueError, "QueryCommand"):
                        ask("E", "allocation", aid)

    def test_verified_cuts_cache_shares_budget_counts_metadata_and_evicts_lru(self):
        q = self._make_query()
        self.assertEqual(q.cached_bytes, 0)
        self.assertEqual(q.metadata_bytes, 0)
        self.assertEqual(len(q._verified_cuts_cache), 0)

        c1 = ("E", "1", "1" * 64)
        c2 = ("E", "2", "2" * 64)
        c3 = ("E", "3", "3" * 64)
        entry_cost = len(canonical(list(c1)))
        self.assertGreater(entry_cost, 64)

        # Restrict shared budget to hold at most 2 historical cut references (2 * entry_cost < limit < 3 * entry_cost).
        q.resources["max_cached_bytes"] = entry_cost * 2 + 20
        economic_query.EconomicQuery._remember_verified_cut(q, c1)
        self.assertEqual(q.metadata_bytes, entry_cost)
        self.assertEqual(list(q._verified_cuts_cache), [c1])

        economic_query.EconomicQuery._remember_verified_cut(q, c2)
        self.assertEqual(q.metadata_bytes, entry_cost * 2)
        self.assertEqual(list(q._verified_cuts_cache), [c1, c2])

        # Touch c1 so c2 becomes LRU; adding c3 must evict c2 and keep total <= max_cached_bytes!
        self.assertTrue(economic_query.EconomicQuery._has_verified_cut(q, c1))
        economic_query.EconomicQuery._remember_verified_cut(q, c3)
        self.assertEqual(list(q._verified_cuts_cache), [c1, c3])
        self.assertEqual(q.metadata_bytes, entry_cost * 2)
        self.assertLessEqual(q.cached_bytes + q.metadata_bytes, q.resources["max_cached_bytes"])

        # Body cache admission shares the SAME budget and evicts oldest verified cut(s) to make room!
        body_bytes = b"x" * (entry_cost + 10)
        with q.lock:
            q._cache_put_locked("snap-1", body_bytes)
        self.assertEqual(q.cached_bytes, len(body_bytes))
        self.assertEqual(list(q._verified_cuts_cache), [c3])
        self.assertEqual(q.metadata_bytes, entry_cost)
        self.assertLessEqual(q.cached_bytes + q.metadata_bytes, q.resources["max_cached_bytes"])

        # Entry count cap (MAX_VERIFIED_CUTS) also evicts oldest cuts even with 4 MiB byte budget.
        q2 = self._make_query()
        for i in range(economic_query.MAX_VERIFIED_CUTS + 5):
            economic_query.EconomicQuery._remember_verified_cut(q2, ("E", str(i), f"{i:064x}"))
        self.assertEqual(len(q2._verified_cuts_cache), economic_query.MAX_VERIFIED_CUTS)
        self.assertEqual(q2.metadata_bytes, sum(q2._verified_cuts_cache.values()))
        self.assertNotIn(("E", "0", f"{0:064x}"), q2._verified_cuts_cache)
        self.assertIn(("E", str(economic_query.MAX_VERIFIED_CUTS + 4), f"{economic_query.MAX_VERIFIED_CUTS + 4:064x}"), q2._verified_cuts_cache)

    def test_r6_source_data_with_protocol_named_keys_allowed_while_protocol_future_cut_rejected(self):
        q = self._make_query()
        real_cuts, fk, aid, base_owner = self._build_fixture_store(q)
        cuts_e10 = {"E": real_cuts[("E", "10")], "B:alpha": real_cuts[("B:alpha", "6")], "B:beta": real_cuts[("B:beta", "4")]}
        cuts_e6 = {"E": real_cuts[("E", "6")], "B:alpha": real_cuts[("B:alpha", "6")], "B:beta": real_cuts[("B:beta", "4")]}
        source_doc = {
            "events": [{"event": "open_chong", "units": "4"}],
            "receipt": {"label": "Delivery note"},
            "cut": {"note": "non-protocol-cut"},
            "e_cut": {"note": "non-protocol-ecut"},
            "witness": {"author": "desk"},
        }
        raw_src = canonical(source_doc).decode("utf-8")
        raw_sha = hashlib.sha256(raw_src.encode("utf-8")).hexdigest()

        def source_note_owner(domain, payload):
            res = base_owner(domain, payload)
            if payload["op"] == "ReadOriginalAtCut" and payload["kind"] == "fact":
                res["original"]["raw_utf8"] = raw_src
                res["original"]["raw_sha256"] = raw_sha
                res["original"]["raw_exact_text"] = {
                    "representation": "ExactDecimalIntegerTextProjection",
                    "raw_sha256": raw_sha,
                    "value": source_doc,
                }
                res["original"]["projected_record"]["event"] = {
                    "event": "open_chong",
                    "receipt": {"label": "event note"},
                    "cut": {"arbitrary": "value"},
                    "witness": {"x": "y"},
                }
            elif payload["op"] == "ReadProjection" and domain == "E":
                rec = {
                    "fact_key": fk, "fact_hash": "e" * 64, "raw_sha256": raw_sha,
                    "json_pointer": "/events/0", "raw_utf8": raw_src,
                    "event": {"event": "open_chong", "receipt": {"label": "Delivery note"}, "cut": {"bad": "1"}},
                }
                res["projection"]["recorded"] = [rec]
                enc = canonical(res["projection"])
                res["projection_hash"] = hashlib.sha256(enc).hexdigest()
                res["projection_bytes"] = str(len(enc))
            return res

        q.owner = source_note_owner
        # Positive: source data with receipt/cut/e_cut/witness succeeds on projection AND projection_original!
        ok_proj = self._call_http_entry(q, "/api/economic/read", {
            "op": "projection", "projection_revision": ECONOMIC_PROJECTION_REVISION,
            "cuts": cuts_e10, "as_known_ns": None, "projection_token": None,
        }, paged=True)
        self.assertEqual(ok_proj["projection_completeness"], "CompleteProjectionVector")
        ok_fact = self._call_http_entry(q, "/api/economic/read", {
            "op": "projection_original", "projection_revision": ECONOMIC_PROJECTION_REVISION,
            "domain_id": "E", "kind": "fact", "object_id": fk, "cuts": cuts_e10,
        }, paged=True)
        self.assertEqual(ok_fact["original"]["raw_utf8"], raw_src)
        # Negative: real protocol receipt E:8 under E:6 MUST still be rejected!
        with self.assertRaisesRegex(ValueError, r"MissingDependency.*E:8.*晚于固定切面.*E:6"):
            self._call_http_entry(q, "/api/economic/read", {
                "op": "projection_original", "projection_revision": ECONOMIC_PROJECTION_REVISION,
                "domain_id": "E", "kind": "fact", "object_id": fk, "cuts": cuts_e6,
            }, paged=True)

    def test_r6_receipt_domain_ownership_binding_enforced_in_q_single_exit(self):
        import copy
        q = self._make_query()
        real_cuts, fk, aid, base_owner = self._build_fixture_store(q)
        cuts_e10 = {"E": real_cuts[("E", "10")], "B:alpha": real_cuts[("B:alpha", "6")], "B:beta": real_cuts[("B:beta", "4")]}

        # Negative 1: B:alpha allocation carries E's valid cut/domain as its Applied receipt -> MUST reject!
        def misplaced_b_alloc_receipt(domain, payload):
            res = base_owner(domain, payload)
            if payload["op"] == "ReadOriginalAtCut" and domain == "B:alpha" and payload["kind"] == "allocation":
                res["original"]["receipt"] = {"kind": "Applied", "domain_id": "E", "cut": cuts_e10["E"]}
            return res

        q.owner = misplaced_b_alloc_receipt
        with self.assertRaisesRegex(ValueError, r"回执域与期望域不符"):
            self._call_http_entry(q, "/api/economic/read", {
                "op": "projection_original", "projection_revision": ECONOMIC_PROJECTION_REVISION,
                "domain_id": "B:alpha", "kind": "allocation", "object_id": aid, "cuts": cuts_e10,
            }, paged=True)

        # Negative 2: B:alpha fact's projected_record.e_receipt claims B:alpha instead of E -> MUST reject!
        def wrong_e_receipt_domain(domain, payload):
            res = copy.deepcopy(base_owner(domain, payload))
            if payload["op"] == "ReadOriginalAtCut" and domain == "B:alpha" and payload["kind"] == "fact":
                res["original"]["projected_record"]["e_receipt"] = {"kind": "Recorded", "domain_id": "B:alpha", "cut": cuts_e10["B:alpha"]}
            return res

        q.owner = wrong_e_receipt_domain
        with self.assertRaisesRegex(ValueError, r"回执域与期望域不符"):
            self._call_http_entry(q, "/api/economic/read", {
                "op": "projection_original", "projection_revision": ECONOMIC_PROJECTION_REVISION,
                "domain_id": "B:alpha", "kind": "fact", "object_id": fk, "cuts": cuts_e10,
            }, paged=True)

        # Positive: honest owner passes both B:alpha allocation and fact!
        q.owner = base_owner
        ok = self._call_http_entry(q, "/api/economic/read", {
            "op": "projection_original", "projection_revision": ECONOMIC_PROJECTION_REVISION,
            "domain_id": "B:alpha", "kind": "allocation", "object_id": aid, "cuts": cuts_e10,
        }, paged=True)
        self.assertEqual(ok["original"]["receipt"]["domain_id"], "B:alpha")

    def test_r6_five_layer_unknown_field_rejected_at_q_exit(self):
        base_ops = ["ReadView", "Watch", "QueryAllocation", "EconomicReadOpen", "EconomicReadPage", "EconomicReadClose"]
        q = self._make_query(ops=base_ops)
        real_cuts, fk, aid, base_owner = self._build_fixture_store(q, redact_witness_for_no_cmd=True)
        cuts_e10 = {"E": real_cuts[("E", "10")], "B:alpha": real_cuts[("B:alpha", "6")], "B:beta": real_cuts[("B:beta", "4")]}
        req = {
            "op": "projection_original", "projection_revision": ECONOMIC_PROJECTION_REVISION,
            "domain_id": "E", "kind": "allocation", "object_id": aid, "cuts": cuts_e10,
        }
        # Positive: clean whitelisted response passes
        q.owner = base_owner
        ok = self._call_http_entry(q, "/api/economic/read", req, paged=True)
        self.assertEqual(ok["original"]["allocation_id"], aid)

        # Negative: unknown key injected at ANY of the five layers MUST be rejected by Q exit!
        def inject(layer):
            def owner(domain, payload):
                res = base_owner(domain, payload)
                if payload["op"] == "ReadOriginalAtCut":
                    row = res["original"]["fill_allocation_row"]
                    w = row["x_execution_witness"]
                    if layer == "row":
                        row["review_new_label"] = "blue"
                    elif layer == "witness":
                        w["review_new_label"] = "blue"
                    elif layer == "release":
                        w["x_release_evidence"]["review_new_label"] = "blue"
                    elif layer == "execute":
                        w["x_execute_evidence"]["review_new_label"] = "blue"
                    elif layer == "reply":
                        w["x_execute_evidence"]["reply"]["review_new_label"] = "blue"
                return res
            return owner

        for layer in ("row", "witness", "release", "execute", "reply"):
            with self.subTest(layer=layer):
                q.owner = inject(layer)
                with self.assertRaisesRegex(ValueError, r"白名单|未声明字段|未知字段"):
                    self._call_http_entry(q, "/api/economic/read", req, paged=True)


    def test_r7_transfer_voice_and_unlisted_cuts_at_public_exit(self):
        q = self._make_query()
        real_cuts, _, _, base_owner = self._build_fixture_store(q)
        vector = {d: real_cuts[d, s] for d, s in (("E", "10"), ("B:alpha", "6"), ("B:beta", "4"))}

        def owner_with(path, seq):
            def owner(domain, payload):
                reply = base_owner(domain, payload)
                if domain != "B:beta" or payload["op"] not in ("ReadProjection", "ReadView"):
                    return reply
                field = "projection" if payload["op"] == "ReadProjection" else "image"
                image = reply[field]
                if path == "transfer":
                    frontier = vector["B:alpha"] if seq == 6 else self._cut("B:alpha", seq)
                    image["recorded"].append({"b_source_debit_proof": {"domain_id": "B:alpha", "receipt": {
                        "kind": "Applied", "domain_id": "B:alpha", "cut": frontier,
                    }}})
                else:
                    image["finance"]["decisions"].append({"decision_id": "beta", "state": "Committed",
                                                          "e_future_proof": {"cut": self._cut("E", seq)}})
                raw = canonical(image)
                reply[field + "_hash"] = hashlib.sha256(raw).hexdigest()
                if field == "projection":
                    reply["projection_bytes"] = str(len(raw))
                return reply
            return owner

        for route, op in [("/api/economic/read", "projection"), ("/api/economic/read", "snapshot"),
                          ("/api/economic/snapshot", "snapshot")]:
            paged = route == "/api/economic/read"
            request = {"op": op, "cuts": vector, "as_known_ns": None, op + "_token": None}
            if op == "projection":
                request["projection_revision"] = ECONOMIC_PROJECTION_REVISION
            with self.subTest(op=op, paged=paged):
                q.owner = owner_with("transfer", 6)
                self.assertEqual(self._call_http_entry(q, route, request, paged=paged)["kind"], "Economic" + op.title())
                for path, seq, domain in [("transfer", 9, "B:alpha"), ("unlisted", 12, "E")]:
                    with self.subTest(path=path):
                        q.owner = owner_with(path, seq)
                        with self.assertRaisesRegex(ValueError, rf"MissingDependency.*{domain}:{seq}"):
                            self._call_http_entry(q, route, request, paged=paged)

        from unittest.mock import patch
        q.owner = base_owner
        request = {"op": "snapshot", "cuts": vector, "as_known_ns": None, "snapshot_token": None}
        source = q.snapshot(request)
        for path in ("voice", "leaked_receipt", "missing_domain"):
            import copy
            reply = copy.deepcopy(source)
            if path == "voice":
                reply["domains"]["B:beta"]["image"]["book"] = {"voice": {"records": [
                    {"opening_basis": {"e_cut": self._cut("E", 12)}}]}}
            elif path == "leaked_receipt":
                reply[path] = {"kind": "Recorded", "domain_id": "E", "cut": self._cut("E", 12)}
            else:
                reply["domains"]["B:beta"]["image"]["recorded"].append({"e_receipt": {"kind": "Recorded", "cut": vector["E"]}})
            with self.subTest(path=path), patch.object(q, "snapshot", return_value=reply):
                with self.assertRaisesRegex(ValueError, r"MissingDependency.*E:12|回执.*domain_id"):
                    self._call_http_entry(q, "/api/economic/snapshot", request)

        # The same shape is opaque inside a source component copied by the writer,
        # but still a protocol dependency inside an E-derived cost component.
        for copied in (True, False):
            reply = copy.deepcopy(source)
            component = {"derivation": {"resolve_cut": self._cut("E", 12)}}
            if copied:
                component.update(source_ref="source-evidence", amount_text="1")
            reply["domains"]["B:beta"]["image"]["book"] = {"known_cost_components": [component]}
            with self.subTest(copied=copied), patch.object(q, "snapshot", return_value=reply):
                if copied:
                    self.assertEqual(self._call_http_entry(q, "/api/economic/snapshot", request), reply)
                else:
                    with self.assertRaisesRegex(ValueError, r"MissingDependency.*E:12"):
                        self._call_http_entry(q, "/api/economic/snapshot", request)

    def test_r7_writer_fields_survive_original_exit(self):
        q = self._make_query()
        real_cuts, fact, allocation, base_owner = self._build_fixture_store(q, redact_witness_for_no_cmd=False)
        vector = {d: real_cuts[d, s] for d, s in (("E", "10"), ("B:alpha", "6"), ("B:beta", "4"))}
        proof = {"domain_id": "B:alpha", "receipt": {"kind": "Applied", "domain_id": "B:alpha", "cut": vector["B:alpha"]}}

        def owner(domain, payload):
            reply = base_owner(domain, payload)
            if payload["op"] == "ReadOriginalAtCut":
                original = reply["original"]
                if payload["kind"] == "fact":
                    original["projected_record"]["b_source_debit_proof"] = proof
                else:
                    witness = original["fill_allocation_row"]["x_execution_witness"]
                    witness["x_release_evidence"]["authority_epoch"] = "1"
                    witness["x_execute_evidence"]["reply"]["authority_epoch"] = "1"
            return reply

        q.owner = owner
        for domain, kind, key in (("B:alpha", "fact", fact), ("E", "allocation", allocation)):
            with self.subTest(kind=kind):
                reply = self._call_http_entry(q, "/api/economic/read", {"op": "projection_original",
                    "projection_revision": ECONOMIC_PROJECTION_REVISION, "domain_id": domain,
                    "kind": kind, "object_id": key, "cuts": vector}, paged=True)["original"]
                if kind == "fact":
                    self.assertEqual(reply["projected_record"]["b_source_debit_proof"], proof)
                else:
                    witness = reply["fill_allocation_row"]["x_execution_witness"]
                    self.assertEqual(witness["x_release_evidence"]["authority_epoch"], "1")
                    self.assertEqual(witness["x_execute_evidence"]["reply"]["authority_epoch"], "1")

    def test_r7_read_field_sets_match_rust_writers(self):
        import re
        from pathlib import Path

        root = Path(__file__).resolve().parents[2]
        rust = root / "rust/src/economic_session"
        projection = (rust / "read_projection.rs").read_text()
        transfer = (rust / "tb03c_transfer.rs").read_text()
        store = (rust / "store.rs").read_text()
        js = (root / "s_session/browser/tb03a-client.js").read_text()
        x = (root / "rust/src/history_simulation/runtime.rs").read_text()

        def keys(block):
            return set(re.findall(r'"([a-z_]+)"', block))

        def block(source, name):
            return re.search(rf"\bconst {name}\b[^=]*= [^\[]*\[(.*?)\]", source, re.S)[1]

        auth_writer = re.search(r"struct Receipt<C, T> \{(.*?)\n\}", x, re.S)[1]
        auth_base = set(re.findall(r"^\s+([a-z_]+):", auth_writer, re.M)) - {"command"}
        js_auth_set = "X_AUTHORITY_EVIDENCE_BASE_ALLOWED" if "X_AUTHORITY_EVIDENCE_BASE_ALLOWED" in js else "X_AUTHORITY_EVIDENCE_ALLOWED"
        for layer, read_keys in {
            "python": economic_query.X_AUTHORITY_EVIDENCE_BASE_ALLOWED,
            "rust": keys(block(projection, "X_AUTHORITY_EVIDENCE_BASE_ALLOWED")),
            "browser": keys(block(js, js_auth_set)) - {"command", "command_ref"},
        }.items():
            with self.subTest(layer=layer, writer="X.Receipt"):
                self.assertEqual(read_keys, auth_base)

        writer = re.search(r"record\[(\w+|\"[^\"]+\")\] = proof;", transfer)[1]
        proof_key = (writer.strip('"') if writer.startswith('"') else
                     re.search(rf'const {writer}: &str = "([^"]+)";', transfer)[1])
        store_fields = re.search(r"let mut original = record.clone\(\);\n\s*for key in \[(.*?)\]", store, re.S)[1]
        writer_fields = keys(store_fields)
        if writer in store_fields:
            writer_fields.add(proof_key)
        self.assertIn(proof_key, writer_fields)
        rust_fields = block(projection, "PROJECTED_RECORD_BASE_ALLOWED")
        rust_read = keys(rust_fields) | ({proof_key} if writer in rust_fields else set())
        for layer, read_keys in {
            "rust": rust_read,
            "python": economic_query.PROJECTED_RECORD_BASE_ALLOWED,
            "browser": keys(block(js, "PROJECTED_RECORD_ALLOWED")),
        }.items():
            with self.subTest(layer=layer, writer="B projected record"):
                self.assertEqual(writer_fields - {"resolved_allocation"} - read_keys, set())


if __name__ == "__main__":
    unittest.main()
