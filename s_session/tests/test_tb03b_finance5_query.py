"""#1407 C2：公共只读路径识别 tb03b-finance/5，并经 E 的 QueryCommand 读命令原件。"""

import copy
import unittest

import test_tb03a_query as baseline
from economic_query import EconomicQuery, EconomicQueryError, economic_revisions
from s_socket_client import canonical, digest


class Finance5RevisionTests(unittest.TestCase):
    def test_v5_is_selected_only_under_economic_session_1(self):
        manifest = {"protocol_revision": "economic-session/1", "finance": {"schema_revision": "tb03b-finance/5"}}
        self.assertEqual(economic_revisions(manifest), ("economic-session/1", "tb03b-finance/5"))
        manifest["protocol_revision"] = "economic-session/2"
        with self.assertRaisesRegex(EconomicQueryError, "混搭"):
            economic_revisions(manifest)

    def test_older_revisions_keep_their_selection(self):
        for protocol, finance in (("economic-session/1", "tb03b-finance/1"), ("economic-session/2", "tb03b-finance/2"),
                                  ("economic-session/1", "tb03b-finance/3"), ("economic-session/2", "tb03b-finance/4")):
            manifest = {"protocol_revision": protocol, "finance": {"schema_revision": finance}}
            self.assertEqual(economic_revisions(manifest), (protocol, finance))


class CommandOriginalTests(unittest.TestCase):
    tearDown = baseline.EconomicQueryTests.tearDown
    write_config = baseline.EconomicQueryTests.write_config
    view = baseline.EconomicQueryTests.view

    def setUp(self):
        baseline.EconomicQueryTests.setUp(self)
        self.manifest["finance"] = {"schema_revision": "tb03b-finance/5"}
        self.manifest["authorized_sources"][0]["operations"].append("QueryCommand")
        self.q = self.load(self.manifest)
        self.record = {"decision_id": "d1", "command_id": "c1", "state": "Dispatchable", "execution_eligibility": "None"}
        for domain, view in self.states.items():
            view["image"]["finance"] = {"schema_revision": "tb03b-finance/5", "rights": [], "decisions": [],
                                        "slots": [], "responsibilities": [], "commands": []}
            if domain == "E":
                view["cut"]["commit_seq"] = "4"
                view["image"]["history"] = [{"kind":"MakeDispatchable", "record":self.record, "commit_seq":"4",
                                              "commit_ns":"1", "first_known_ns":"1"}]
                view["image"]["finance"]["commands"] = [self.record]
            view["image_hash"] = digest(view["image"])
        self.receipts = [{"kind": "DispatchableReceipt", "domain_id":"E", "commit_ns":"1", "first_known_ns":"1",
                          "receipt_key":"tb03b-finance/5:MakeDispatchable:"+digest("d1"), "record": self.record, "cut": dict(self.states["E"]["cut"])}]
        self.calls = []
        self.q.owner = self.owner

    def load(self, manifest):
        (self.root / "manifest.json").write_bytes(canonical(manifest))
        self.config["manifest_hash"] = digest(manifest)
        self.write_config()
        return EconomicQuery(self.root / "query.json")

    def owner(self, domain, payload):
        self.calls.append((domain, copy.deepcopy(payload)))
        if payload["op"] == "QueryCommand":
            head = {"kind": "EconomicCommand", "domain_id": domain, "command_id": payload["command_id"],
                    "cut": payload["cut"]}
            if payload["command_id"] != self.record["command_id"]:
                return {**head, "state": "NoRecord"}
            return copy.deepcopy({**head, "state": self.record["state"], "record": self.record,
                                  "receipts": self.receipts})
        return copy.deepcopy(self.states[domain])

    def request(self, command_id="c1", domain="E"):
        return {"op": "original", "kind": "command", "domain_id": domain, "object_id": command_id,
                "cuts": {d: v["cut"] for d, v in self.states.items()}}

    def test_query_command_is_an_authorized_read(self):
        self.assertIn("QueryCommand", self.q.authorized_read_ops)

    def test_command_original_binds_e_image_record_at_fixed_cut(self):
        result = self.q.original(self.request())
        self.assertEqual(result["original"]["record"], self.record)
        self.assertEqual(result["domain_id"], "E")
        self.assertEqual(self.calls[-1], ("E", {"op": "QueryCommand", "command_id": "c1",
                                                "cut": self.states["E"]["cut"], "as_known_ns": None}))

    def test_absent_command_reads_as_no_record(self):
        self.assertEqual(self.q.original(self.request("c2"))["original"]["state"], "NoRecord")

    def test_reply_record_differing_from_cut_image_is_rejected(self):
        self.record = {**self.record, "state": "ReleasedExact"}
        self.receipts = [self.receipts[0], {"kind": "ReleasedExactReceipt", "record": self.record,
                                            "cut": dict(self.states["E"]["cut"])}]
        with self.assertRaisesRegex(EconomicQueryError, "命令原件与指定 cut 的已核图像不同"):
            self.q.original(self.request())

    def test_future_receipt_is_not_backfilled_into_old_cut(self):
        self.receipts[0]["cut"]["commit_seq"] = "5"
        with self.assertRaisesRegex(EconomicQueryError, "未来回执"):
            self.q.original(self.request())

    def test_command_belongs_only_to_e(self):
        with self.assertRaisesRegex(EconomicQueryError, "权威域"):
            self.q.original(self.request(domain="B:a"))

    def test_v5_image_must_carry_commands(self):
        del self.states["E"]["image"]["finance"]["commands"]
        self.states["E"]["image_hash"] = digest(self.states["E"]["image"])
        with self.assertRaisesRegex(EconomicQueryError, "财务图像字段"):
            self.q.original(self.request())

    def test_command_original_needs_v5(self):
        self.manifest["finance"]["schema_revision"] = "tb03b-finance/1"
        self.manifest["authorized_sources"][0]["operations"].remove("QueryCommand")
        self.q = self.load(self.manifest)
        with self.assertRaisesRegex(EconomicQueryError, "只属于 tb03b-finance/5"):
            self.q.original(self.request())


if __name__ == "__main__":
    unittest.main()
