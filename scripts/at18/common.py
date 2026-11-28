"""AT-18 的字节、路径与封闭输入公共层。"""
from __future__ import annotations

import hashlib
import json
import math
import re
import subprocess
from pathlib import PurePosixPath

from jsonschema import Draft202012Validator

REGISTRY = ".chanlun/at18/registry.json"
ADAPTER = ".chanlun/at18/adapter-contract.json"
CENSUS = ".chanlun/at18/landing-census.json"
CROSSWALK = (".chanlun/review-results/issue1339-r2-spec-20260909/"
             "payload/spec/IMPLEMENTATION-CROSSWALK.json")
LEDGERS = tuple(".chanlun/review-results/issue1340-publication-20260909/payload/inputs/" + name
                for name in ("TB01-EXECUTION-SLICES.json", "TB02-06-EXECUTION-SLICES.json",
                             "TB07-11-EXECUTION-SLICES.json", "TB01-PARENT-CONTRIBUTION.json"))
TABLES = {"story": ("rows", "story_id", "story_ids"),
          "family": ("family_entry_links", "id", "family_entry_ids"),
          "detail": ("detailed_acceptance_links", "id", "detailed_acceptance_ids")}
TB = tuple(f"TB-{i:02d}" for i in range(1, 12))
P0 = "b5cd3fee352e5f7199233de628da05ff06c5798f"
NAME = re.compile(r"[A-Za-z0-9._-]+")
SHA = re.compile(r"[a-f0-9]{64}")
COMMIT = re.compile(r"[a-f0-9]{40}")
RECORD = re.compile(r"tb\.(simulation|experiment)\.(TB-0[1-9]|TB-10)")
SPECIAL = {"permission.experiment": ["TB-09"], "migration.experiment": ["TB-10"],
           "post_gate.experiment": ["TB-11"]}
DEFER = {"ISSUE_1561_P2_FIRST_SEND": "production", "ADR_0036_POST_GATE_EXPERIMENT": "experiment",
         "ADR_0036_POST_GATE_PRODUCTION": "production"}


class Invalid(ValueError):
    pass


def require(condition, code, identity):
    if not condition:
        raise Invalid(f"{code}: {identity}")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True,
                       separators=(",", ":")) + "\n").encode("utf-8")


def strict_json(data, identity, *, object_root=True):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "JSON_PARSE", identity)
            key.encode("utf-8")
            result[key] = value
        return result

    def number(token):
        value = float(token)
        require(math.isfinite(value), "JSON_PARSE", identity)
        return value

    try:
        result = json.loads(data.decode("utf-8"), object_pairs_hook=unique, parse_float=number,
                            parse_constant=number)
        json_bytes(result)  # 拒绝嵌套字符串中的孤立代理码点。
    except (ValueError, UnicodeError, RecursionError) as error:
        raise Invalid(f"JSON_PARSE: {identity}") from error
    require(not object_root or isinstance(result, dict), "JSON_PARSE", identity)
    return result


def path_name(path):
    require(isinstance(path, str) and path and not path.startswith(("/", "-"))
            and not any(ord(c) < 32 or c == "\\" for c in path)
            and not any(p in ("", "..", ".", ".git") for p in path.split("/")),
            "INVALID_PATH", path)
    return path


def read_regular(root, path):
    target = root
    for part in PurePosixPath(path_name(path)).parts:
        target = target / part
        require(not target.is_symlink(), "INVALID_PATH", path)
    require(target.is_file(), "FILE_READ", path)
    return target.read_bytes()


def git(root, *args, allowed=(0,)):
    result = subprocess.run(["git", *args], cwd=root, capture_output=True)
    require(result.returncode in allowed, "GIT_READ", args[0])
    return result.stdout


def tree_entry(root, commit, path):
    require(COMMIT.fullmatch(commit), "INVALID_COMMIT", commit)
    row = git(root, "--literal-pathspecs", "ls-tree", "-z", commit, "--", path_name(path))
    if not row:
        return None
    metadata, actual = row.removesuffix(b"\0").split(b"\t", 1)
    require(actual == path.encode(), "INVALID_PATH", path)
    return metadata.decode("ascii").split()


def git_blob(root, commit, path):
    entry = tree_entry(root, commit, path)
    require(entry and entry[0] in ("100644", "100755") and entry[1] == "blob", "FILE_READ", path)
    return git(root, "cat-file", "blob", entry[2])


def pointer(document, ptr):
    require(isinstance(ptr, str) and (ptr == "" or ptr.startswith("/"))
            and not re.search(r"~(?![01])", ptr), "BAD_POINTER", ptr)
    node = document
    for token in ptr.split("/")[1:]:
        key = token.replace("~1", "/").replace("~0", "~")
        if isinstance(node, dict) and key in node:
            node = node[key]
        elif isinstance(node, list) and re.fullmatch(r"0|[1-9][0-9]*", key) and len(key) <= 10 and int(key) < len(node):
            node = node[int(key)]
        else:
            raise Invalid(f"BAD_POINTER: {ptr}")
    return node


def validate_schema(root, filename, document, code, *, commit=None):
    path = f".chanlun/at18/{filename}.schema.json"
    schema = strict_json(git_blob(root, commit, path) if commit else read_regular(root, path), path)
    error = next(Draft202012Validator(schema).iter_errors(document), None)
    if error is not None:
        location = "/" + "/".join(map(str, error.absolute_path))
        raise Invalid(f"{code}: {location} ({error.validator})")


def unique(values, code, identity):
    seen = set()
    for value in values:
        require(value not in seen, code, identity)
        seen.add(value)
    return seen


def key_token(s):
    return s.replace("~", "~0").replace("/", "~1").replace("%", "%25").replace("@", "%40")
