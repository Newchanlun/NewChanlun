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


if __name__ == "__main__":
    unittest.main()
