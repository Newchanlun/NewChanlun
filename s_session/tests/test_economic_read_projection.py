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
                 manifest_hash="a" * 64, read_projection_available=True)
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


if __name__ == "__main__":
    unittest.main()
