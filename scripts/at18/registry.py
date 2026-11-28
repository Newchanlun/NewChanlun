"""AT-18 登记册 R02–R05 静态门。"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from adapter import profile, validate_adapter
from common import (ADAPTER, CENSUS, CROSSWALK, DEFER, LEDGERS, NAME, P0, RECORD, REGISTRY, SPECIAL,
                    TABLES, TB, git, git_blob, pointer, read_regular, require, sha,
                    strict_json, tree_entry, unique, validate_schema)
from check_selector import annotation, command

# #2132 会登记正式清册和 landings；这里只钉住已审 r5 的入口摘要，不把草稿当 F 原件。
OPENING_CENSUS = "36c76a9cfa4ec39f518184ba91d61988027a775b0e319ea9eb719012ad0a3a00"
FIXED_CURES = {
    1392: ("8619a20f2800095e6bb9ec20ba2607a744740f91", "m3_partition_synthetic_holds"),
    1404: ("f95a7f3ebc0ce84ec2d2f8a8d71b5030b19f89b9", "calibration_sweep_finds_non_collapsed_segments"),
    1414: ("465174240b989a1d99f99a047fbb46b3ee215f49", "seam_btc_tick_bars_yield_non_trivial_structure"),
}


def canonical_bases(root, crosswalk):
    expansion, boundaries, ids, dsts = {}, set(), {}, {}
    for kind, (table, id_field, _) in TABLES.items():
        known = ids[kind] = {}
        for i, row in enumerate(crosswalk[table]):
            identity = row[id_field]
            require(isinstance(identity, str) and identity and identity not in known
                    and not any(c.isspace() for c in identity), "COVERAGE_SOURCE", table)
            known[identity] = row
            slices = row["success_closure_slice_ids"]
            require(isinstance(slices, list) and slices and len(unique(slices, "COVERAGE_SOURCE", identity)) == len(slices)
                    and set(slices) <= set(TB), "COVERAGE_SOURCE", identity)
            if kind == "family":
                require(type(row.get("exclusion_boundary", False)) is bool, "COVERAGE_SOURCE", identity)
                if row.get("exclusion_boundary"):
                    boundaries.add(identity)
            for slice_id in slices:
                expansion[(slice_id, kind, identity)] = (CROSSWALK, f"/{table}/{i}")
    for row in crosswalk["family_entry_links"]:
        require(set(row["user_story_ids"]) <= ids["story"].keys()
                and set(row.get("acceptance_point_ids", [])) <= ids["detail"].keys(), "COVERAGE_SOURCE", row["id"])
    for row in crosswalk["detailed_acceptance_links"]:
        require(row["family_entry_id"] in ids["family"]
                and set(row["user_story_ids"]) <= ids["story"].keys(), "COVERAGE_SOURCE", row["id"])
    for row in crosswalk["destination_success_obligations"]:
        identity = row["destination_id"]
        require(identity not in dsts, "COVERAGE_SOURCE", identity)
        dsts[identity] = row
        for kind, (_, _, field) in TABLES.items():
            linked = unique(row[field], "COVERAGE_SOURCE", identity)
            require(all(member in ids[kind] and identity in ids[kind][member]["destination_ids"]
                        for member in linked), "COVERAGE_SOURCE", f"{identity}.{field} ownership")
    require(set(dsts) == {f"DST-{i:02d}" for i in range(1, 7)}, "COVERAGE_SOURCE", "Destination")
    for table in ids.values():
        for row in table.values():
            require(set(row["destination_ids"]) <= dsts.keys(), "COVERAGE_SOURCE", "Destination link")
    # 所有切片账命中优先；无命中才读取 TB-01 贡献账，再无命中才用展开原节点。
    split, contrib = defaultdict(set), defaultdict(set)
    for path in LEDGERS[:3]:
        units = strict_json(read_regular(root, path), path)["units"]
        for i, unit in enumerate(units):
            for kind, (_, _, field) in TABLES.items():
                for identity in unit[field]:
                    key = (unit["parent_tb"], kind, identity)
                    if key in expansion:
                        split[key].add((path, f"/units/{i}"))
    path = LEDGERS[3]
    for i, row in enumerate(strict_json(read_regular(root, path), path)["rows"]):
        for kind, values in (("family", [row["family_entry_id"]]),
                             ("detail", row.get("parent_detailed_acceptance_ids", []))):
            for identity in values:
                key = ("TB-01", kind, identity)
                if key in expansion:
                    contrib[key].add((path, f"/rows/{i}"))
    return {key: split.get(key) or contrib.get(key) or {basis} for key, basis in expansion.items()}, boundaries


def identities(registry):
    result = {}
    for binding in registry["bindings"]:
        path, ptr = binding["basis"]["path"], binding["basis"]["pointer"]
        for key in binding["keys"]:
            identity = (binding["slice_id"], key["kind"], key["id"], path, ptr)
            require(identity not in result, "BASIS_MISMATCH", identity)
            result[identity] = {(d["evidence_class"], d["profile_id"]): d["result"] for d in binding["domains"]}
    return result


def monotonic(old, new):
    current = identities(new)
    for identity, before in identities(old).items():
        after = current.get(identity)
        require(after is not None and before.keys() <= after.keys()
                and all(result == "BOUNDED_DEFERRED" or after[domain] == result
                        for domain, result in before.items()), "DOMAIN_SHRINK", identity)
    current_cures = {(row["ticket"], cure["commit"], cure["run_id"], cure["kind"], cure["target"])
                     for row in new["pregate"]["landings"] for cure in row["cure_checks"]}
    for landing in old["pregate"]["landings"]:
        for cure in landing["cure_checks"]:
            key = (landing["ticket"], cure["commit"], cure["run_id"], cure["kind"], cure["target"])
            require(key in current_cures, "DEVIATION_NOT_CURED", key)


def domain_profile(evidence, value, registered):
    require((value is None or profile(value)) and (evidence == "simulation" or value is not None)
            and (evidence != "experiment" or value == registered), "DOMAIN_INVALID", "profile_id")


def verify_pregate(root, reg, checks, used):
    pregate = reg["pregate"]
    landings = pregate["landings"]
    if not (root / CENSUS).exists() and not (root / CENSUS).is_symlink():
        require(not landings and pregate["census_sha256"] == OPENING_CENSUS, "PREGATE_LANDINGS", CENSUS)
        return
    data = read_regular(root, CENSUS)
    require(sha(data) == pregate["census_sha256"], "PREGATE_LANDINGS", "census_sha256")
    doc = strict_json(data, CENSUS)
    require(doc.keys() == {"schema_version", "p0", "sources", "attributions"}
            and doc["schema_version"] == "at18-landing-census/1" and doc["p0"] == P0
            and isinstance(doc["sources"], list) and isinstance(doc["attributions"], list),
            "PREGATE_LANDINGS", CENSUS)
    roles = set()
    for source in doc["sources"]:
        require(source.keys() == {"role", "path", "sha256"} and source["role"] not in roles
                and sha(read_regular(root, source["path"])) == source["sha256"], "PREGATE_LANDINGS", CENSUS)
        roles.add(source["role"])
    require(roles == {"history", "relations", "signals", "adjudication"}, "PREGATE_LANDINGS", "roles")
    def scopes_valid(scopes):
        return scopes and scopes == sorted(set(scopes)) and set(scopes) <= set(TB[:10]) | {"GRAPH"} and (
            "GRAPH" not in scopes or len(scopes) == 1)
    last = 0
    for row in doc["attributions"]:
        require(row.keys() == {"ticket", "attribution_scopes", "sources"} and type(row["ticket"]) is int
                and row["ticket"] > last and scopes_valid(row["attribution_scopes"]) and row["sources"]
                and all(isinstance(s, str) and s for s in row["sources"])
                and row["sources"] == sorted(set(row["sources"]), key=str.encode), "PREGATE_LANDINGS", "attributions")
        last = row["ticket"]
    unique((r["ticket"] for r in landings), "PREGATE_LANDINGS", "ticket")
    fixed = set()
    for row in landings:
        require(scopes_valid(row["attribution_scopes"]), "PREGATE_LANDINGS", row["ticket"])
        for cure in row["cure_checks"]:
            check = checks.get(cure["check_id"])
            require(check is not None and cure["commit"] in row["commits"], "DEVIATION_NOT_CURED", row["ticket"])
            if cure["kind"] == "test":
                suffix = cure["target"]
                runner = check["runner"]
                selector = check["selector"]
                name = selector.rsplit("/", 1)[-1] if runner == "cargo-test" else selector
                require(runner != "command" and check["expected_count"] == 1
                        and (name == suffix or name.endswith("::" + suffix)),
                        "DEVIATION_NOT_CURED", suffix)
                if cure["run_id"] is None and FIXED_CURES.get(row["ticket"]) == (cure["commit"], suffix):
                    fixed.add(row["ticket"])
            else:
                require(check["runner"] == "command", "DEVIATION_NOT_CURED", cure["target"])
            used.add(check["check_id"])
    require(not landings or fixed == FIXED_CURES.keys(), "DEVIATION_NOT_CURED", "R11 fixed locks")


def load(root, *, base=None):
    root = Path(root).resolve()
    raw = read_regular(root, REGISTRY)
    reg = strict_json(raw, REGISTRY)
    validate_schema(root, "registry", reg, "REGISTRY_INVALID")
    require(reg["experiment_profile_id"] is None or profile(reg["experiment_profile_id"]),
            "REGISTRY_INVALID", "experiment_profile_id")
    contract = validate_adapter(root, read_regular(root, ADAPTER), reg["adapter_contract_sha256"])
    crosswalk_data = read_regular(root, CROSSWALK)
    require(sha(crosswalk_data) == reg["crosswalk_sha256"], "REGISTRY_INVALID", "crosswalk_sha256")
    bases, boundaries = canonical_bases(root, strict_json(crosswalk_data, CROSSWALK))
    if base is not None:
        git(root, "cat-file", "-e", base + "^{commit}")  # 缺 base 不等于历史没有登记册。
        if tree_entry(root, base, REGISTRY) is not None:
            old = strict_json(git_blob(root, base, REGISTRY), REGISTRY)
            validate_schema(root, "registry", old, "REGISTRY_INVALID")
            monotonic(old, reg)
    checks, groups, records, annotations, used = {}, {}, set(), {}, set()
    active_keys = defaultdict(set)
    source_cache, basis_docs = {}, {}
    def checked_source(rule, code):
        path = rule["path"]
        if path not in source_cache:
            data = read_regular(root, path)
            source_cache[path] = (data, sha(data))
        data, digest = source_cache[path]
        require(digest == rule["sha256"], code, path)
        return data
    for check in reg["checks"]:
        cid, group, evidence, pfid = (check[k] for k in ("check_id", "group", "evidence_class", "profile_id"))
        require(cid not in checks and NAME.fullmatch(cid) and NAME.fullmatch(group)
                and type(check["expected_count"]) is int, "REGISTRY_INVALID", "check_id/group/expected_count")
        require(evidence != "production", "PRODUCTION_SCOPE_CHANGED", cid)
        domain_profile(evidence, pfid, reg["experiment_profile_id"])
        require(groups.setdefault(group, (evidence, pfid)) == (evidence, pfid), "DOMAIN_INVALID", group)
        check_source = checked_source(check["source"], "CHECK_SOURCE_DRIFT")
        command(check, root)
        require(check["runner"] != "command" or check["key_aware"] and check["expected_count"] == 1,
                "CHECK_SELECTOR", cid)
        annotations[cid] = annotation(check, check_source, root)
        if (record := check["record"]) is not None:
            tb = RECORD.fullmatch(record)
            require(((record in SPECIAL and evidence == "experiment") or (tb and tb[1] == evidence))
                    and (record, pfid) not in records, "RECORD_UNSEALED", cid)
            records.add((record, pfid))
            used.add(cid)
        checks[cid] = check
    identities(reg)
    unique((b["binding_id"] for b in reg["bindings"]), "REGISTRY_INVALID", "binding_id")
    registered_bases = defaultdict(set)
    for binding in reg["bindings"]:
        bid, slice_id, basis = binding["binding_id"], binding["slice_id"], binding["basis"]
        require(NAME.fullmatch(bid), "REGISTRY_INVALID", bid)
        keys = [(slice_id, k["kind"], k["id"]) for k in binding["keys"]]
        for key in keys:
            require(key in bases and slice_id != "TB-11", "KEY_NOT_EXPECTED", key)
            actual = (basis["path"], basis["pointer"])
            require(actual in bases[key], "BASIS_MISMATCH", key)
            registered_bases[key].add(actual)
        data = checked_source(basis, "BASIS_MISMATCH")
        if basis["path"] not in basis_docs:
            basis_docs[basis["path"]] = strict_json(data, basis["path"])
        pointer(basis_docs[basis["path"]], basis["pointer"])
        unique(((d["evidence_class"], d["profile_id"]) for d in binding["domains"]), "DOMAIN_INVALID", bid)
        require(any(d["result"] != "BOUNDED_DEFERRED" for d in binding["domains"]), "DOMAIN_INVALID", bid)
        for d in binding["domains"]:
            result, names, gate, evidence, pfid = (d[k] for k in ("result", "checks", "deferred_gate",
                                                                   "evidence_class", "profile_id"))
            domain_profile(evidence, pfid, reg["experiment_profile_id"])
            boundary_flags = {kind == "family" and identity in boundaries for _, kind, identity in keys}
            require(boundary_flags == {result == "PRESERVED_BOUNDARY"}, "DOMAIN_INVALID", bid)
            if result == "BOUNDED_DEFERRED":
                require(not names and DEFER.get(gate) == evidence, "DOMAIN_INVALID", bid)
                continue
            require(names and gate is None and evidence != "production", "DOMAIN_INVALID", bid)
            for name in names:
                check = checks.get(name)
                require(check and (check["evidence_class"], check["profile_id"]) == (evidence, pfid),
                        "DOMAIN_INVALID", bid)
                require(check["key_aware"] or all(key in annotations[name][1] for key in keys),
                        "CHECK_NOT_ANNOTATED", name)
                active_keys[name].update((*key, basis["path"], basis["pointer"]) for key in keys)
                used.add(name)
    # 骨架可不登记某个键；一旦登记，就必须一次交齐该键的全部规范出处。
    for key, registered in registered_bases.items():
        require(registered == bases[key], "BASIS_INCOMPLETE", key)
    experiment_groups = {group for group, (evidence, _) in groups.items() if evidence == "experiment"}
    auth = contract["experiment_authorization"]
    require(auth["group_actions"].keys() == experiment_groups, "DOMAIN_INVALID", "experiment group scope")
    for signature in (auth, auth["send_authorization"]):
        require((signature["comment_id"] is None) == (signature["body_sha256"] is None),
                "REGISTRY_INVALID", "authorization pin")
    verify_pregate(root, reg, checks, used)
    require(used == checks.keys(), "DOMAIN_INVALID", "unreferenced check")
    return reg, contract, sha(raw), active_keys, {cid: v[0] for cid, v in annotations.items()}
