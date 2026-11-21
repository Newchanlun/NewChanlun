"""AT-18 检查组；以实际执行与逐键见证生成封印输入。"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

from adapter import decode_fields, decode_payload
from check_selector import command, selector_matches
from common import (COMMIT, Invalid, RECORD, SPECIAL, json_bytes, path_name, read_regular, require,
                    sha, strict_json, unique)

KEY_FIELDS = ("kind", "id", "slice_id", "basis_path", "basis_pointer")
RECORD_FIELDS = ("schema_version", "record", "head", "run_id", "run_attempt", "check_id", "profile_id", "payload")


def run_identity(head, run_id, run_attempt):
    require(COMMIT.fullmatch(head) and type(run_id) is int and run_id > 0
            and type(run_attempt) is int and run_attempt > 0, "RUN_IDENTITY", "Actions")
    return {"head": head, "run_id": run_id, "run_attempt": run_attempt}


def rust_rows(output):
    # libtest 使用 --exact 和默认 capture；只认完整框架行/汇总。子进程退出码另行校验。
    try:
        lines = output.decode("utf-8").splitlines()
    except UnicodeError as error:
        raise Invalid("CHECK_EXECUTION: libtest encoding") from error
    summary = re.compile(r"test result: (?:ok|FAILED)\. (\d+) passed; (\d+) failed; (\d+) ignored; (\d+) measured; (\d+) filtered out; finished in [\d.]+s")
    conclusions = [m.groups() for line in lines if (m := summary.fullmatch(line))]
    rows = [{"name": m[1], "status": {"ok": "passed", "FAILED": "failed", "ignored": "ignored"}[m[2]]}
            for line in lines
            if (m := re.fullmatch(r"test ([\w:]+) \.\.\. (ok|FAILED|ignored)(?:, .*)?", line))]
    require(len(conclusions) == 1, "CHECK_EXECUTION", "libtest summary")
    actual = [sum(row["status"] == status for row in rows) for status in ("passed", "failed", "ignored")]
    require(list(map(int, conclusions[0][:4])) == actual + [0], "CHECK_EXECUTION", "libtest counts")
    return rows


def read_execution(check, work, output):
    runner = check["runner"]
    if runner == "cargo-test":
        return rust_rows(output)
    if runner == "command":
        # command 的唯一进程是选择器；键感知见证在另一步强制核验。
        return [{"name": check["selector"], "status": "passed"}]
    result = strict_json(read_regular(work, "framework.json"), "framework.json", object_root=False)
    if runner == "pytest":
        require(isinstance(result, list), "CHECK_EXECUTION", "pytest reporter")
        return result
    require(isinstance(result, dict) and result.keys() == {"rows", "summaries"}
            and len(result["summaries"]) == 1, "CHECK_EXECUTION", "node reporter")
    counts = result["summaries"][0]
    rows = result["rows"]
    require(counts["tests"] == len(rows)
            and counts["skipped"] == sum(row["status"] == "skipped" for row in rows)
            and counts["todo"] == sum(row["status"] == "ignored" for row in rows),
            "CHECK_EXECUTION", "node counts")
    return rows


def witness(work, expected):
    doc = strict_json(read_regular(work, "witness.json"), "witness.json")
    require(doc.keys() == {"schema_version", "entries"} and doc["schema_version"] == "at18-key-witness/1"
            and isinstance(doc["entries"], list), "CHECK_WITNESS", "schema")
    actual = []
    for item in doc["entries"]:
        require(item.keys() == {*KEY_FIELDS, "ok"} and item["ok"] is True
                and all(isinstance(item[k], str) for k in KEY_FIELDS), "CHECK_WITNESS", "entry")
        actual.append(tuple(item[k] for k in KEY_FIELDS))
    require(unique(actual, "CHECK_WITNESS", "duplicate identities") == set(expected),
            "CHECK_WITNESS", "identities")


def validate_record(contract, document, check, identity):
    require(document.keys() == set(RECORD_FIELDS), "RECORD_UNSEALED", "run-record fields")
    fields = decode_fields(contract, contract["run_record_envelope"], document)
    require(check["record"] is not None and all(fields[field] == value for field, value in {
        "schema_version": "at18-run-record/1", "record": check["record"], "check_id": check["check_id"],
        "profile_id": check["profile_id"], **identity,
    }.items()), "RECORD_UNSEALED", "run-record identity")
    payload = decode_payload(contract, check["record"], fields["payload"])
    if (tb := RECORD.fullmatch(check["record"])):
        require((payload["evidence_class"], payload["tb_id"], payload["profile_id"]) ==
                (tb[1], tb[2], check["profile_id"]), "RECORD_UNSEALED", "TB payload identity")
    elif check["record"] in SPECIAL:
        binding = check["record"] == "permission.experiment"
        profile_id = payload["binding_profile_id" if binding else "profile_id"]
        evidence = payload["binding_evidence_class" if binding else "evidence_class"]
        require((profile_id, evidence) == (check["profile_id"], "experiment"),
                "RECORD_UNSEALED", "payload identity")
    return fields


def _records(contract, work, check, identity):
    directory = work / "records"
    require(not directory.is_symlink() and directory.is_dir(), "RECORD_UNSEALED", "records")
    files = sorted(directory.iterdir())
    require(bool(files) == (check["record"] is not None), "RECORD_UNSEALED", check["check_id"])
    records = {}
    for path in files:
        require(path.suffix == ".json", "RECORD_UNSEALED", "record suffix")
        raw = read_regular(work, f"records/{path.name}")
        doc = strict_json(raw, "run record")
        validate_record(contract, doc, check, identity)
        digest = sha(raw)
        require(digest not in records, "RECORD_UNSEALED", "duplicate record bytes")
        records[digest] = raw
    return records


def execute(root, check, contract, identity, keys, line):
    argv = command(check, root)
    metadata = {"check_id": check["check_id"], "argv": argv, "expected": check["expected_count"],
                "executed": None, "ignored": None, "skipped": None, "exit_code": None, "tests": [],
                "status": "FAIL", "diagnostic": None}
    expected_keys = sorted(((kind, name, tb, path, ptr) for tb, kind, name, path, ptr in keys),
                           key=lambda row: tuple(s.encode() for s in row))
    with TemporaryDirectory(prefix="at18-check-") as temp:
        work = Path(temp)
        (work / "records").mkdir()
        (work / "keys.json").write_bytes(json_bytes([dict(zip(KEY_FIELDS, row)) for row in expected_keys]))
        env = os.environ.copy()
        for key in ("PYTEST_ADDOPTS", "PYTEST_PLUGINS", "NODE_OPTIONS"):
            env.pop(key, None)
        env["PYTHONPATH"] = str(Path(__file__).resolve().parent) + (
            os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        env.update(AT18_KEYS_FILE=str(work / "keys.json"), AT18_WITNESS_FILE=str(work / "witness.json"),
                   AT18_RECORD_DIR=str(work / "records"), AT18_FRAMEWORK_FILE=str(work / "framework.json"),
                   AT18_RECORD=check["record"] or "", AT18_PROFILE_ID=check["profile_id"] or "",
                   AT18_CHECK_ID=check["check_id"], AT18_F=identity["head"],
                   AT18_RUN_ID=str(identity["run_id"]), AT18_RUN_ATTEMPT=str(identity["run_attempt"]))
        try:
            result = subprocess.run(argv, cwd=root, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            metadata["exit_code"] = result.returncode
            rows = read_execution(check, work, result.stdout)
            if check["runner"] == "command" and result.returncode != 0:
                rows[0]["status"] = "failed"
            names = []
            for row in rows:
                name = row["name"]
                require(selector_matches(check, name) and
                        row["status"] in ("passed", "failed", "skipped", "ignored", "missing"),
                        "CHECK_EXECUTION", "selector")
                if check["runner"] in ("node-test", "pytest"):
                    source = root / path_name(check["source"]["path"])
                    require(row.get("source") and Path(row["source"]).resolve() == source.resolve()
                            and (check["runner"] == "pytest" and row["line"] in line
                                 or check["runner"] == "node-test" and row["line"] == line[1]),
                            "CHECK_EXECUTION", "source identity")
                names.append(name)
            metadata.update(executed=sum(row["status"] in ("passed", "failed") for row in rows),
                            skipped=sum(row["status"] == "skipped" for row in rows),
                            ignored=sum(row["status"] == "ignored" for row in rows),
                            tests=sorted(rows, key=lambda row: row["name"].encode()))
            require(len(set(names)) == len(names), "CHECK_EXECUTION", "duplicate tests")
            require(result.returncode == 0 and metadata["executed"] == check["expected_count"]
                    and metadata["ignored"] == metadata["skipped"] == 0
                    and all(row["status"] == "passed" for row in rows), "CHECK_EXECUTION", "exit/counts")
            if check["key_aware"]:
                witness(work, expected_keys)
            records = _records(contract, work, check, identity)
            metadata["status"] = "PASS"
            return metadata, records
        except (ValueError, TypeError, KeyError, OSError) as error:
            # 只记诊断分类，不搬运行日志、异常自由文本或凭据。
            metadata["diagnostic"] = (str(error).partition(":")[0] if isinstance(error, Invalid)
                                      else "CHECK_EXECUTION")
    return metadata, {}


def run_group(root, loaded, evidence, group, identity, out, *, before_check=None):
    reg, contract, digest, keys, lines = loaded
    checks = sorted((c for c in reg["checks"] if (c["evidence_class"], c["group"]) == (evidence, group)),
                    key=lambda c: c["check_id"].encode())
    require(checks or group is None and not any(c["evidence_class"] == evidence for c in reg["checks"]),
            "CHECK_JOB_MISSING", str(group))
    out.mkdir(parents=True, exist_ok=False)
    inventory = []
    results = []
    for check in checks:
        if before_check is not None:
            before_check()
        cid = check["check_id"]
        actual, records = execute(root, check, contract, identity, keys.get(cid, set()), lines[cid])
        results.append(actual)
        for content_sha, raw in sorted(records.items()):
            name = "record-" + content_sha + ".json"
            with (out / name).open("xb") as stream:
                stream.write(raw)
            inventory.append({"path": name, "record": check["record"], "sha256": content_sha,
                              "check_id": cid, "profile_id": check["profile_id"]})
    manifest = {"schema_version": "at18-group-execution/1", "registry_sha256": digest, **identity,
                "group": group, "evidence_class": evidence, "checks": results,
                "records": sorted(inventory, key=lambda row: row["path"])}
    (out / "execution.json").write_bytes(json_bytes(manifest))
    return all(row["status"] == "PASS" for row in results)
