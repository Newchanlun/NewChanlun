from __future__ import annotations

import json
import os
import re
import stat
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from pilot1742 import external_review
from pilot1742 import merge_group_review as mgr
from pilot1742.merge_group_review import (
    DEFAULT_EXPECTED_MODELS,
    MAX_STATUS_DESCRIPTION_LEN,
    MERGE_GROUP_STATUS_CONTEXT,
    MergeGroupError,
    MergeGroupMember,
    MergeGroupPolicy,
    MergeGroupTarget,
    compute_patch_identity,
    evaluate_merge_group,
    parse_merge_group_event,
    parse_merge_group_ref,
    parse_merge_queue_entries,
    verify_member_pass,
    verify_merge_group_tree,
)

REPO_ID = 1150335160
REPO_NAME = "Newchanlun/NewChanlun"
POLICY_VERSION = "external-pr-v1-kimi"
REVIEW_CONTRACT = "sha256:" + ("1" * 64)
IMAGE_ID = "sha256:" + ("2" * 64)
ALT_IMAGE_ID = "sha256:" + ("3" * 64)
LOW_ENTROPY_SHA_A = "a" * 40
LOW_ENTROPY_SHA_B = "b" * 40
LOW_ENTROPY_SHA_C = "c" * 40
LOW_ENTROPY_SHA_64 = "d" * 64


def _run_git(repo: Path, *args: str) -> str:
    env = {k: os.environ[k] for k in ("PATH", "LANG", "LC_ALL", "TMPDIR") if k in os.environ}
    env.update(
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_TERMINAL_PROMPT="0",
        GIT_AUTHOR_NAME="Test Fixture",
        GIT_AUTHOR_EMAIL="fixture@invalid.local",
        GIT_AUTHOR_DATE="1700000000 +0000",
        GIT_COMMITTER_NAME="Test Fixture",
        GIT_COMMITTER_EMAIL="fixture@invalid.local",
        GIT_COMMITTER_DATE="1700000000 +0000",
    )
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return proc.stdout.strip()


def _snapshot_objects(git_dir: Path) -> set[str]:
    objects_dir = git_dir / "objects"
    return {
        str(path.relative_to(objects_dir))
        for path in objects_dir.rglob("*")
        if path.is_file()
    }


class MergeQueueFixture:
    """离线本地 git 仓库 + 审查状态目录测试夹具。"""

    def __init__(self, tmp_path: Path) -> None:
        resolved_root = tmp_path.resolve()
        self.root = resolved_root
        self.repo = resolved_root / "repo"
        self.state_root = resolved_root / "state"
        self.repo.mkdir(mode=0o700)
        self.state_root.mkdir(mode=0o700)
        _run_git(self.repo, "init", "-q", "-b", "main")
        (self.repo / "README.md").write_text("base\n", encoding="utf-8")
        (self.repo / "shared.txt").write_text(
            "line1\nline2\nline3\nline4\nline5\nline6\nline7\nline8\n",
            encoding="utf-8",
        )
        _run_git(self.repo, "add", ".")
        _run_git(self.repo, "commit", "-qm", "initial base")
        self.base_sha = _run_git(self.repo, "rev-parse", "HEAD")
        self.controller_head = self.base_sha
        self._reg_seq = 1_000_000

    def policy(self, **overrides: Any) -> MergeGroupPolicy:
        params: dict[str, Any] = {
            "policy_version": POLICY_VERSION,
            "review_contract": REVIEW_CONTRACT,
            "controller_code_head": self.controller_head,
            "deployment_image_id": IMAGE_ID,
            "expected_models": DEFAULT_EXPECTED_MODELS,
        }
        params.update(overrides)
        return MergeGroupPolicy(**params)

    def create_branch_commit(
        self,
        branch: str,
        *,
        from_ref: str,
        files: dict[str, str | None],
        executable_files: set[str] | None = None,
        message: str = "branch commit",
    ) -> str:
        _run_git(self.repo, "checkout", "-q", "-B", branch, from_ref)
        for rel_path, content in files.items():
            full = self.repo / rel_path
            if content is None:
                if full.exists():
                    full.unlink()
            else:
                full.parent.mkdir(parents=True, exist_ok=True)
                full.write_text(content, encoding="utf-8")
                if executable_files and rel_path in executable_files:
                    os.chmod(full, 0o755)
        _run_git(self.repo, "add", "-A")
        _run_git(self.repo, "commit", "-qm", message)
        sha = _run_git(self.repo, "rev-parse", "HEAD")
        _run_git(self.repo, "checkout", "-q", "main")
        return sha

    def create_queue_head(
        self,
        *,
        base_sha: str,
        member_heads: list[str],
        branch_name: str = "queue-head",
        extra_files: dict[str, str] | None = None,
        chmod_files: dict[str, int] | None = None,
    ) -> str:
        _run_git(self.repo, "checkout", "-q", "-B", branch_name, base_sha)
        for idx, member_head in enumerate(member_heads, start=1):
            _run_git(self.repo, "merge", "--no-ff", "-m", f"merge step {idx}", member_head)
        if extra_files or chmod_files:
            if extra_files:
                for rel_path, content in extra_files.items():
                    full = self.repo / rel_path
                    full.parent.mkdir(parents=True, exist_ok=True)
                    full.write_text(content, encoding="utf-8")
            if chmod_files:
                for rel_path, mode in chmod_files.items():
                    os.chmod(self.repo / rel_path, mode)
            _run_git(self.repo, "add", "-A")
            _run_git(self.repo, "commit", "--amend", "--no-edit", "-q")
        sha = _run_git(self.repo, "rev-parse", "HEAD")
        _run_git(self.repo, "checkout", "-q", "main")
        return sha

    def write_direct_pass_run(
        self,
        *,
        pr_number: int,
        base_sha: str,
        head_sha: str,
        merge_base_sha: str | None = None,
        run_id: str | None = None,
        attempt: int = 1,
        repository_id: int = REPO_ID,
        policy_version: str = POLICY_VERSION,
        review_contract: str = REVIEW_CONTRACT,
        controller_code_head: str | None = None,
        image_id: str = IMAGE_ID,
        models: tuple[str, ...] = DEFAULT_EXPECTED_MODELS,
        verdict: str = "PASS",
        state: str = "success",
        publication_state: str | None = "success",
        patch_id_override: str | None = None,
        extra_outcome: dict[str, Any] | None = None,
        registered_at_ns: int | None = None,
    ) -> tuple[Path, str, str]:
        mb = merge_base_sha or _run_git(self.repo, "merge-base", base_sha, head_sha)
        pid = patch_id_override if patch_id_override is not None else compute_patch_identity(self.repo, mb, head_sha)
        rid = run_id or f"run-pr{pr_number}-a{attempt}"
        if registered_at_ns is None:
            self._reg_seq += 10
            registered_at_ns = self._reg_seq
        ctrl = controller_code_head or self.controller_head
        key = f"r{repository_id}-p{pr_number}-{base_sha}-{head_sha}-{policy_version}-a{attempt}"
        folder = self.state_root / "runs" / key
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)

        target_data = {
            "repository_id": repository_id,
            "pr_number": pr_number,
            "base_repository_id": repository_id,
            "base_ref": "main",
            "base_sha": base_sha,
            "head_repository_id": repository_id,
            "head_ref": f"pr-{pr_number}",
            "head_sha": head_sha,
            "merge_base_sha": mb,
            "run_id": rid,
            "attempt": attempt,
            "policy_version": policy_version,
            "controller_code_head": ctrl,
            "registered_at_ns": registered_at_ns,
            "patch_id": pid,
            "review_contract": review_contract,
        }
        self._write_json(folder / "target.json", target_data)

        reviews = []
        safe_rid = re.sub(r"[^a-zA-Z0-9-]", "-", rid)[:80]
        for idx, model in enumerate(models, start=1):
            worker = folder / model
            worker.mkdir(parents=True, exist_ok=True, mode=0o700)
            launch_id = f"launch-{rid}-{idx}"
            session_id = f"sess-{safe_rid}-{idx}"
            self._write_json(
                worker / "launch.json",
                {
                    "run_id": rid,
                    "launch_id": launch_id,
                    "pr_number": pr_number,
                    "model": model,
                    "head_sha": head_sha,
                    "base_sha": base_sha,
                    "merge_base_sha": mb,
                    "controller_code_head": ctrl,
                    "checkout": str(self.root / "checkouts" / rid / model),
                    "prompt": f"review PR #{pr_number}",
                    "mode": "review",
                },
            )
            result_status = "completed" if verdict == "PASS" else ("blocked" if verdict == "BLOCK" else "failed")
            summary = f"VERDICT: {verdict}\n审查完成"
            self._write_json(
                worker / "receipt.json",
                {
                    "run_id": rid,
                    "launch_id": launch_id,
                    "model": model,
                    "head_sha": head_sha,
                    "base_sha": base_sha,
                    "merge_base_sha": mb,
                    "controller_code_head": ctrl,
                    "status": "completed",
                    "mode": "review",
                    "sandbox": "docker-read-only",
                    "exit_code": 0,
                    "turn_completed": True,
                    "image_id": image_id,
                    "container_id": f"{idx:012x}" + ("a" * 52),
                    "session_id": session_id,
                    "before": {"head": head_sha, "status": "", "branch": "HEAD"},
                    "after": {"head": head_sha, "status": "", "branch": "HEAD"},
                    "filesystem": {
                        "source_write": "EROFS",
                        "git_write": "EROFS",
                        "host_read": "ENOENT",
                        "state_write": "EROFS",
                    },
                    "result": {
                        "status": result_status,
                        "summary": summary,
                        "findings": [],
                        "validation": ["ok"],
                    },
                },
            )
            session_path = worker / "session.jsonl"
            session_path.write_text(
                json.dumps({"type": "session_meta", "payload": {"id": session_id}}) + "\n",
                encoding="utf-8",
            )
            os.chmod(session_path, 0o600)
            reviews.append({"model": model, "verdict": verdict, "session_id": session_id, "reason": summary})

        outcome: dict[str, Any] = {
            "run_id": rid,
            "verdict": verdict,
            "state": state,
            "target": target_data,
            "reviews": reviews,
        }
        if publication_state is not None:
            outcome["publication"] = {
                "id": 900_000 + registered_at_ns,
                "state": publication_state,
                "sha": head_sha,
                "description": f"run={rid} b={base_sha[:12]} h={head_sha[:12]} {publication_state}",
            }
        if extra_outcome:
            outcome.update(extra_outcome)
        self._write_json(folder / "outcome.json", outcome)
        return folder, rid, pid

    def _find_run_artifacts(self, run_id: str) -> tuple[dict[str, Any], dict[str, Any]] | None:
        runs_dir = self.state_root / "runs"
        if not runs_dir.is_dir():
            return None
        for child in runs_dir.iterdir():
            target_file = child / "target.json"
            outcome_file = child / "outcome.json"
            if target_file.is_file() and outcome_file.is_file():
                target_obj = json.loads(target_file.read_text(encoding="utf-8"))
                if target_obj.get("run_id") == run_id:
                    outcome_obj = json.loads(outcome_file.read_text(encoding="utf-8"))
                    return target_obj, outcome_obj
        return None

    def write_reused_pass_run(
        self,
        *,
        pr_number: int,
        base_sha: str,
        head_sha: str,
        origin_run_id: str,
        origin_patch_id: str,
        merge_base_sha: str | None = None,
        run_id: str | None = None,
        attempt: int = 1,
        repository_id: int = REPO_ID,
        policy_version: str = POLICY_VERSION,
        review_contract: str = REVIEW_CONTRACT,
        controller_code_head: str | None = None,
        admission_image_id: str = IMAGE_ID,
        registered_at_ns: int | None = None,
        origin_head_sha: str | None = None,
        origin_base_sha: str | None = None,
        origin_merge_base_sha: str | None = None,
        origin_publication: dict[str, Any] | None = None,
        include_admission: bool = True,
    ) -> tuple[Path, str]:
        mb = merge_base_sha or _run_git(self.repo, "merge-base", base_sha, head_sha)
        rid = run_id or f"reuse-pr{pr_number}-a{attempt}"
        if registered_at_ns is None:
            self._reg_seq += 10
            registered_at_ns = self._reg_seq
        ctrl = controller_code_head or self.controller_head
        key = f"r{repository_id}-p{pr_number}-{base_sha}-{head_sha}-{policy_version}-a{attempt}"
        folder = self.state_root / "runs" / key
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)

        found_origin = self._find_run_artifacts(origin_run_id)
        if found_origin is not None:
            orig_target, orig_outcome = found_origin
            resolved_orig_head = origin_head_sha or str(orig_target["head_sha"])
            resolved_orig_base = origin_base_sha or str(orig_target["base_sha"])
            resolved_orig_mb = origin_merge_base_sha or str(orig_target["merge_base_sha"])
            resolved_orig_pub = origin_publication or dict(orig_outcome.get("publication") or {})
            resolved_orig_reviews = list(orig_outcome.get("reviews") or [])
        else:
            resolved_orig_head = origin_head_sha or head_sha
            resolved_orig_base = origin_base_sha or base_sha
            resolved_orig_mb = origin_merge_base_sha or mb
            resolved_orig_pub = origin_publication or {
                "id": 800_000 + registered_at_ns,
                "state": "success",
                "sha": resolved_orig_head,
                "description": f"run={origin_run_id} b={resolved_orig_base[:12]} h={resolved_orig_head[:12]} success",
            }
            resolved_orig_reviews = []

        target_data = {
            "repository_id": repository_id,
            "pr_number": pr_number,
            "base_repository_id": repository_id,
            "base_ref": "main",
            "base_sha": base_sha,
            "head_repository_id": repository_id,
            "head_ref": f"pr-{pr_number}",
            "head_sha": head_sha,
            "merge_base_sha": mb,
            "run_id": rid,
            "attempt": attempt,
            "policy_version": policy_version,
            "controller_code_head": ctrl,
            "registered_at_ns": registered_at_ns,
            "patch_id": origin_patch_id,
            "review_contract": review_contract,
        }
        self._write_json(folder / "target.json", target_data)
        reused_from: dict[str, Any] = {
            "run_id": origin_run_id,
            "reviews": resolved_orig_reviews,
            "publication": resolved_orig_pub,
            "head_sha": resolved_orig_head,
            "base_sha": resolved_orig_base,
            "merge_base_sha": resolved_orig_mb,
            "patch_id": origin_patch_id,
        }
        if include_admission:
            reused_from["admission"] = {"controller_code_head": ctrl, "image_id": admission_image_id}
        outcome: dict[str, Any] = {
            "run_id": rid,
            "verdict": "PASS",
            "state": "success",
            "target": target_data,
            "reviews": [],
            "publication": {
                "id": 900_000 + registered_at_ns,
                "state": "success",
                "sha": head_sha,
                "description": (
                    f"run={rid} b={base_sha[:12]} h={head_sha[:12]} success "
                    f"reuse={origin_run_id} p={origin_patch_id[7:19]}"
                ),
            },
            "reused_from": reused_from,
        }
        self._write_json(folder / "outcome.json", outcome)
        return folder, rid

    @staticmethod
    def _write_json(path: Path, payload: dict[str, Any]) -> None:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.chmod(path, 0o600)

    def make_target(
        self,
        *,
        base_sha: str,
        head_sha: str,
        members: list[MergeGroupMember],
        expected_head_tree_sha: str | None = None,
    ) -> MergeGroupTarget:
        lead_pr = members[-1].pr_number
        return MergeGroupTarget(
            repository_id=REPO_ID,
            repository=REPO_NAME,
            base_branch="main",
            base_sha=base_sha,
            head_sha=head_sha,
            head_ref=f"refs/heads/gh-readonly-queue/main/pr-{lead_pr}-{base_sha}",
            members=tuple(members),
            expected_head_tree_sha=expected_head_tree_sha,
        )


@pytest.fixture
def mq_fixture(tmp_path: Path) -> MergeQueueFixture:
    return MergeQueueFixture(tmp_path)


# ---------------------------------------------------------------------------
# 1. Ref / Domain / Webhook / GraphQL 解析器正负测试
# ---------------------------------------------------------------------------


def test_parse_merge_group_ref_valid_and_normalization() -> None:
    upper_sha = LOW_ENTROPY_SHA_A.upper()
    ref1 = parse_merge_group_ref(f"gh-readonly-queue/main/pr-42-{upper_sha}")
    assert ref1.base_branch == "main"
    assert ref1.lead_pr == 42
    assert ref1.base_sha == LOW_ENTROPY_SHA_A
    assert ref1.canonical_ref == f"refs/heads/gh-readonly-queue/main/pr-42-{LOW_ENTROPY_SHA_A}"

    ref2 = parse_merge_group_ref(
        f"refs/heads/gh-readonly-queue/release/2026/pr-7-{LOW_ENTROPY_SHA_64.upper()}",
        expected_base_branch="release/2026",
    )
    assert ref2.base_branch == "release/2026"
    assert ref2.lead_pr == 7
    assert ref2.base_sha == LOW_ENTROPY_SHA_64


@pytest.mark.parametrize(
    "bad_ref",
    [
        "",
        f" gh-readonly-queue/main/pr-1-{LOW_ENTROPY_SHA_A}",
        f"gh-readonly-queue/main/pr-1-{LOW_ENTROPY_SHA_A} ",
        f"gh-readonly-queue/main/pr-1-{LOW_ENTROPY_SHA_A}\n",
        f"gh-readonly-queue/../main/pr-1-{LOW_ENTROPY_SHA_A}",
        f"gh-readonly-queue/main/../pr-1-{LOW_ENTROPY_SHA_A}",
        f"gh-readonly-queue/other/pr-1-{LOW_ENTROPY_SHA_A}",
        f"gh-readonly-queue/main/pr-0-{LOW_ENTROPY_SHA_A}",
        f"gh-readonly-queue/main/pr-01-{LOW_ENTROPY_SHA_A}",
        "gh-readonly-queue/main/pr-1-abcdef1234",
        f"refs/tags/gh-readonly-queue/main/pr-1-{LOW_ENTROPY_SHA_A}",
    ],
)
def test_parse_merge_group_ref_rejects_invalid(bad_ref: str) -> None:
    with pytest.raises(MergeGroupError):
        parse_merge_group_ref(bad_ref, expected_base_branch="main")


def test_domain_models_reject_bool_duplicates_and_mismatches() -> None:
    with pytest.raises(MergeGroupError):
        MergeGroupMember(pr_number=True, head_sha=LOW_ENTROPY_SHA_A)  # type: ignore[arg-type]
    with pytest.raises(MergeGroupError):
        MergeGroupMember(pr_number=0, head_sha=LOW_ENTROPY_SHA_A)
    with pytest.raises(MergeGroupError):
        MergeGroupMember(pr_number=1, head_sha="deadbeef")

    m1 = MergeGroupMember(1, LOW_ENTROPY_SHA_A)
    m2 = MergeGroupMember(2, LOW_ENTROPY_SHA_B)
    ref_for_2 = f"refs/heads/gh-readonly-queue/main/pr-2-{LOW_ENTROPY_SHA_A}"

    # bool 伪装 repository_id
    with pytest.raises(MergeGroupError):
        MergeGroupTarget(
            repository_id=True,  # type: ignore[arg-type]
            repository=REPO_NAME,
            base_sha=LOW_ENTROPY_SHA_A,
            head_sha=LOW_ENTROPY_SHA_C,
            head_ref=ref_for_2,
            members=(m1, m2),
        )
    # 重复 PR 号
    with pytest.raises(MergeGroupError):
        MergeGroupTarget(
            repository_id=REPO_ID,
            repository=REPO_NAME,
            base_sha=LOW_ENTROPY_SHA_A,
            head_sha=LOW_ENTROPY_SHA_C,
            head_ref=f"refs/heads/gh-readonly-queue/main/pr-1-{LOW_ENTROPY_SHA_A}",
            members=(m1, MergeGroupMember(1, LOW_ENTROPY_SHA_B)),
        )
    # lead PR 与最后一位不匹配
    with pytest.raises(MergeGroupError):
        MergeGroupTarget(
            repository_id=REPO_ID,
            repository=REPO_NAME,
            base_sha=LOW_ENTROPY_SHA_A,
            head_sha=LOW_ENTROPY_SHA_C,
            head_ref=ref_for_2,
            members=(m2, m1),
        )
    # head_ref 中 base_sha 与 target.base_sha 不一致
    with pytest.raises(MergeGroupError):
        MergeGroupTarget(
            repository_id=REPO_ID,
            repository=REPO_NAME,
            base_sha=LOW_ENTROPY_SHA_B,
            head_sha=LOW_ENTROPY_SHA_C,
            head_ref=ref_for_2,
            members=(m1, m2),
        )
    # repository 含路径穿越
    with pytest.raises(MergeGroupError):
        MergeGroupTarget(
            repository_id=REPO_ID,
            repository="owner/../repo",
            base_sha=LOW_ENTROPY_SHA_A,
            head_sha=LOW_ENTROPY_SHA_C,
            head_ref=ref_for_2,
            members=(m1, m2),
        )
    # policy 校验
    with pytest.raises(MergeGroupError):
        MergeGroupPolicy(
            policy_version=POLICY_VERSION,
            review_contract=REVIEW_CONTRACT,
            controller_code_head=LOW_ENTROPY_SHA_A,
            deployment_image_id="not-sha256",
        )
    with pytest.raises(MergeGroupError):
        MergeGroupPolicy(
            policy_version=POLICY_VERSION,
            review_contract=REVIEW_CONTRACT,
            controller_code_head=LOW_ENTROPY_SHA_A,
            deployment_image_id=IMAGE_ID,
            expected_models=("same-model", "same-model"),
        )


def test_parse_merge_group_event_valid_and_negative() -> None:
    m1 = MergeGroupMember(10, LOW_ENTROPY_SHA_B)
    m2 = MergeGroupMember(20, LOW_ENTROPY_SHA_C)
    payload: dict[str, Any] = {
        "action": "checks_requested",
        "repository": {"id": REPO_ID, "full_name": REPO_NAME},
        "merge_group": {
            "base_ref": "refs/heads/main",
            "base_sha": LOW_ENTROPY_SHA_A.upper(),
            "head_ref": f"gh-readonly-queue/main/pr-20-{LOW_ENTROPY_SHA_A}",
            "head_sha": LOW_ENTROPY_SHA_C.upper(),
            "head_commit": {
                "id": LOW_ENTROPY_SHA_C,
                "tree_id": LOW_ENTROPY_SHA_B.upper(),
            },
        },
    }
    target = parse_merge_group_event(
        payload,
        members=[m1, m2],
        expected_base_branch="main",
        expected_repository_id=REPO_ID,
        expected_repository=REPO_NAME,
    )
    assert target.repository_id == REPO_ID
    assert target.base_sha == LOW_ENTROPY_SHA_A
    assert target.head_sha == LOW_ENTROPY_SHA_C
    assert target.expected_head_tree_sha == LOW_ENTROPY_SHA_B
    assert target.head_ref == f"refs/heads/gh-readonly-queue/main/pr-20-{LOW_ENTROPY_SHA_A}"

    # 拒绝 destroyed action
    destroyed = {**payload, "action": "destroyed"}
    with pytest.raises(MergeGroupError):
        parse_merge_group_event(destroyed, members=[m1, m2])

    # 拒绝 head_commit.id != head_sha
    bad_commit = {
        **payload,
        "merge_group": {
            **payload["merge_group"],
            "head_commit": {"id": LOW_ENTROPY_SHA_A, "tree_id": LOW_ENTROPY_SHA_B},
        },
    }
    with pytest.raises(MergeGroupError):
        parse_merge_group_event(bad_commit, members=[m1, m2])

    # 拒绝 bool 伪装 repository.id
    bool_repo = {**payload, "repository": {"id": True, "full_name": REPO_NAME}}
    with pytest.raises(MergeGroupError):
        parse_merge_group_event(bool_repo, members=[m1, m2])


def test_parse_merge_queue_entries_valid_and_negative() -> None:
    def make_entry(
        pos: int,
        pr: int,
        head_oid: str,
        pr_head: str,
        *,
        base_oid: str = LOW_ENTROPY_SHA_A,
        state: str = "AWAITING_CHECKS",
        head_ref_name: str | None = None,
    ) -> dict[str, Any]:
        node: dict[str, Any] = {
            "position": pos,
            "state": state,
            "baseCommit": {"oid": base_oid},
            "headCommit": {"oid": head_oid, "tree": {"oid": LOW_ENTROPY_SHA_B}},
            "pullRequest": {"number": pr, "headRefOid": pr_head},
        }
        if head_ref_name is not None:
            node["headRefName"] = head_ref_name
        return node

    # 即使 nodes 乱序且含后续条目（position=3），也精确按 1..2 升序提取
    gql_payload: dict[str, Any] = {
        "data": {
            "repository": {
                "databaseId": REPO_ID,
                "nameWithOwner": REPO_NAME,
                "mergeQueue": {
                    "entries": {
                        "pageInfo": {"hasNextPage": False},
                        "nodes": [
                            make_entry(3, 30, "3" * 40, "6" * 40, state="QUEUED"),
                            make_entry(
                                2,
                                20,
                                "2" * 40,
                                "5" * 40,
                                state="AWAITING_CHECKS",
                                head_ref_name=f"gh-readonly-queue/main/pr-20-{LOW_ENTROPY_SHA_A}",
                            ),
                            make_entry(1, 10, "1" * 40, "4" * 40, state="MERGEABLE"),
                        ],
                    }
                },
            }
        }
    }
    target = parse_merge_queue_entries(
        gql_payload,
        target_head_sha="2" * 40,
        expected_repository_id=REPO_ID,
        expected_repository=REPO_NAME,
    )
    assert [m.pr_number for m in target.members] == [10, 20]
    assert [m.head_sha for m in target.members] == ["4" * 40, "5" * 40]
    assert target.expected_head_tree_sha == LOW_ENTROPY_SHA_B

    # 直接传 repository 节点字典也支持
    direct = parse_merge_queue_entries(
        gql_payload["data"]["repository"],
        target_head_sha="1" * 40,
    )
    assert [m.pr_number for m in direct.members] == [10]

    # 位置缺口（缺 position 1）必须拒绝
    gap_payload = {
        "databaseId": REPO_ID,
        "nameWithOwner": REPO_NAME,
        "mergeQueue": {
            "entries": {
                "pageInfo": {"hasNextPage": False},
                "nodes": [make_entry(2, 20, "2" * 40, "5" * 40)],
            }
        },
    }
    with pytest.raises(MergeGroupError, match="不连续"):
        parse_merge_queue_entries(gap_payload, target_head_sha="2" * 40)

    # hasNextPage 截断导致未覆盖 1..T.position 必须拒绝
    truncated_payload = {
        "databaseId": REPO_ID,
        "nameWithOwner": REPO_NAME,
        "mergeQueue": {
            "entries": {
                "pageInfo": {"hasNextPage": True},
                "nodes": [
                    make_entry(1, 10, "1" * 40, "4" * 40),
                    make_entry(3, 30, "3" * 40, "6" * 40),
                ],
            }
        },
    }
    with pytest.raises(MergeGroupError, match="hasNextPage"):
        parse_merge_queue_entries(truncated_payload, target_head_sha="3" * 40)

    # hasNextPage 截断导致根本找不到 target_head_sha
    with pytest.raises(MergeGroupError, match="截断"):
        parse_merge_queue_entries(truncated_payload, target_head_sha="9" * 40)

    # 非法/已移除队列状态
    bad_state_payload = {
        "databaseId": REPO_ID,
        "nameWithOwner": REPO_NAME,
        "mergeQueue": {
            "entries": {
                "nodes": [
                    make_entry(1, 10, "1" * 40, "4" * 40, state="UNMERGEABLE"),
                    make_entry(2, 20, "2" * 40, "5" * 40, state="AWAITING_CHECKS"),
                ]
            }
        },
    }
    with pytest.raises(MergeGroupError, match="状态非法"):
        parse_merge_queue_entries(bad_state_payload, target_head_sha="2" * 40)

    # 前缀 baseCommit.oid 不一致
    bad_base_payload = {
        "databaseId": REPO_ID,
        "nameWithOwner": REPO_NAME,
        "mergeQueue": {
            "entries": {
                "nodes": [
                    make_entry(1, 10, "1" * 40, "4" * 40, base_oid=LOW_ENTROPY_SHA_B),
                    make_entry(2, 20, "2" * 40, "5" * 40, base_oid=LOW_ENTROPY_SHA_A),
                ]
            }
        },
    }
    with pytest.raises(MergeGroupError, match="baseCommit.oid"):
        parse_merge_queue_entries(bad_base_payload, target_head_sha="2" * 40)

    # 重复 PR 号
    dup_pr_payload = {
        "databaseId": REPO_ID,
        "nameWithOwner": REPO_NAME,
        "mergeQueue": {
            "entries": {
                "nodes": [
                    make_entry(1, 10, "1" * 40, "4" * 40),
                    make_entry(2, 10, "2" * 40, "5" * 40),
                ]
            }
        },
    }
    with pytest.raises(MergeGroupError, match="重复 PR"):
        parse_merge_queue_entries(dup_pr_payload, target_head_sha="2" * 40)

    # bool 伪装 position
    bool_pos_payload = {
        "databaseId": REPO_ID,
        "nameWithOwner": REPO_NAME,
        "mergeQueue": {
            "entries": {
                "nodes": [make_entry(True, 10, "1" * 40, "4" * 40)],  # type: ignore[arg-type]
            }
        },
    }
    with pytest.raises(MergeGroupError):
        parse_merge_queue_entries(bool_pos_payload, target_head_sha="1" * 40)


# ---------------------------------------------------------------------------
# 2. 正向 PASS 场景：单成员 / 多成员 / 堆叠 PR / 1 跳 reused_from / 零污染 & worktree
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("member_count", [1, 2, 3])
def test_evaluate_merge_group_independent_members_pass_and_zero_pollution(
    mq_fixture: MergeQueueFixture,
    member_count: int,
) -> None:
    members: list[MergeGroupMember] = []
    member_heads: list[str] = []
    for idx in range(1, member_count + 1):
        head = mq_fixture.create_branch_commit(
            f"pr-{idx}",
            from_ref=mq_fixture.base_sha,
            files={f"mod_{idx}.py": f"VALUE = {idx}\n"},
            message=f"PR #{idx}",
        )
        mq_fixture.write_direct_pass_run(pr_number=idx, base_sha=mq_fixture.base_sha, head_sha=head)
        members.append(MergeGroupMember(idx, head))
        member_heads.append(head)

    queue_head = mq_fixture.create_queue_head(base_sha=mq_fixture.base_sha, member_heads=member_heads)
    expected_tree = _run_git(mq_fixture.repo, "rev-parse", f"{queue_head}^{{tree}}")
    target = mq_fixture.make_target(
        base_sha=mq_fixture.base_sha,
        head_sha=queue_head,
        members=members,
        expected_head_tree_sha=expected_tree,
    )

    before_objects = _snapshot_objects(mq_fixture.repo / ".git")
    before_status = _run_git(mq_fixture.repo, "status", "--porcelain")

    decision = evaluate_merge_group(
        target,
        source_repo=mq_fixture.repo,
        state_root=mq_fixture.state_root,
        policy=mq_fixture.policy(),
        published_statuses={m.head_sha: "success" for m in members},
    )

    after_objects = _snapshot_objects(mq_fixture.repo / ".git")
    after_status = _run_git(mq_fixture.repo, "status", "--porcelain")
    assert after_objects == before_objects
    assert after_status == before_status == ""

    assert decision.verdict == "PASS"
    assert decision.status_context == MERGE_GROUP_STATUS_CONTEXT
    assert decision.status_state == "success"
    assert decision.reason_code == "merge_group_pass_reused"
    assert len(decision.status_description) <= MAX_STATUS_DESCRIPTION_LEN
    assert decision.actual_tree_sha == decision.expected_tree_sha == expected_tree
    assert decision.overlapping_files == ()
    assert decision.failed_members == ()
    assert len(decision.member_proofs) == member_count

    status_payload = decision.to_status_payload(target_url="https://example.invalid/runs/1")
    assert status_payload["state"] == "success"
    assert status_payload["context"] == MERGE_GROUP_STATUS_CONTEXT
    assert status_payload["target_url"] == "https://example.invalid/runs/1"

    outcome_record = decision.to_outcome_record()
    assert outcome_record["kind"] == "merge_group"
    assert outcome_record["verdict"] == "PASS"
    assert outcome_record["state"] == "success"
    assert len(outcome_record["reused_members"]) == member_count
    assert outcome_record["policy_version"] == POLICY_VERSION
    assert outcome_record["deployment_image_id"] == IMAGE_ID


def test_stacked_prs_pass_without_spurious_overlap(mq_fixture: MergeQueueFixture) -> None:
    pr1_head = mq_fixture.create_branch_commit(
        "pr-1",
        from_ref=mq_fixture.base_sha,
        files={"stack_a.py": "A = 1\n"},
        message="stacked PR 1",
    )
    pr2_head = mq_fixture.create_branch_commit(
        "pr-2",
        from_ref=pr1_head,
        files={"stack_b.py": "B = 2\n"},
        message="stacked PR 2",
    )
    mq_fixture.write_direct_pass_run(pr_number=1, base_sha=mq_fixture.base_sha, head_sha=pr1_head)
    mq_fixture.write_direct_pass_run(pr_number=2, base_sha=mq_fixture.base_sha, head_sha=pr2_head)

    queue_head = mq_fixture.create_queue_head(base_sha=mq_fixture.base_sha, member_heads=[pr1_head, pr2_head])
    target = mq_fixture.make_target(
        base_sha=mq_fixture.base_sha,
        head_sha=queue_head,
        members=[MergeGroupMember(1, pr1_head), MergeGroupMember(2, pr2_head)],
    )
    decision = evaluate_merge_group(
        target,
        source_repo=mq_fixture.repo,
        state_root=mq_fixture.state_root,
        policy=mq_fixture.policy(),
    )
    assert decision.verdict == "PASS"
    assert decision.status_state == "success"
    assert decision.overlapping_files == ()


def test_git_worktree_source_repo_zero_pollution(mq_fixture: MergeQueueFixture, tmp_path: Path) -> None:
    pr1_head = mq_fixture.create_branch_commit(
        "pr-1",
        from_ref=mq_fixture.base_sha,
        files={"wt1.txt": "hello\n"},
        message="PR 1",
    )
    pr2_head = mq_fixture.create_branch_commit(
        "pr-2",
        from_ref=mq_fixture.base_sha,
        files={"wt2.txt": "world\n"},
        message="PR 2",
    )
    mq_fixture.write_direct_pass_run(pr_number=1, base_sha=mq_fixture.base_sha, head_sha=pr1_head)
    mq_fixture.write_direct_pass_run(pr_number=2, base_sha=mq_fixture.base_sha, head_sha=pr2_head)
    queue_head = mq_fixture.create_queue_head(base_sha=mq_fixture.base_sha, member_heads=[pr1_head, pr2_head])

    worktree_dir = mq_fixture.root / "linked-wt"
    _run_git(mq_fixture.repo, "worktree", "add", "-q", "--detach", str(worktree_dir), mq_fixture.base_sha)

    before_objects = _snapshot_objects(mq_fixture.repo / ".git")
    before_wt_status = _run_git(worktree_dir, "status", "--porcelain")

    target = mq_fixture.make_target(
        base_sha=mq_fixture.base_sha,
        head_sha=queue_head,
        members=[MergeGroupMember(1, pr1_head), MergeGroupMember(2, pr2_head)],
    )
    decision = evaluate_merge_group(
        target,
        source_repo=worktree_dir,
        state_root=mq_fixture.state_root,
        policy=mq_fixture.policy(),
    )

    assert decision.verdict == "PASS"
    assert decision.status_state == "success"
    assert _snapshot_objects(mq_fixture.repo / ".git") == before_objects
    assert _run_git(worktree_dir, "status", "--porcelain") == before_wt_status == ""


def test_single_hop_reused_pass_succeeds_and_two_hop_rejected(mq_fixture: MergeQueueFixture) -> None:
    # 1. PR #1 基于 base0 通过真实双审
    pr1_v1 = mq_fixture.create_branch_commit(
        "pr-1-v1",
        from_ref=mq_fixture.base_sha,
        files={"feature.py": "X = 42\n"},
        message="PR 1 original",
    )
    _, orig_run_id, orig_patch_id = mq_fixture.write_direct_pass_run(
        pr_number=1,
        base_sha=mq_fixture.base_sha,
        head_sha=pr1_v1,
        run_id="orig-run-1",
    )

    # 2. main 前进（无关文件），PR #1 rebase 到新 base1 产生相同 patch_id
    base1 = mq_fixture.create_branch_commit(
        "main",
        from_ref=mq_fixture.base_sha,
        files={"unrelated.txt": "main advanced\n"},
        message="advance main",
    )
    pr1_v2 = mq_fixture.create_branch_commit(
        "pr-1-v2",
        from_ref=base1,
        files={"feature.py": "X = 42\n"},
        message="PR 1 rebased",
    )
    assert compute_patch_identity(mq_fixture.repo, base1, pr1_v2) == orig_patch_id

    _, hop1_run_id = mq_fixture.write_reused_pass_run(
        pr_number=1,
        base_sha=base1,
        head_sha=pr1_v2,
        origin_run_id=orig_run_id,
        origin_patch_id=orig_patch_id,
        run_id="reuse-hop1",
    )

    queue_head_v2 = mq_fixture.create_queue_head(base_sha=base1, member_heads=[pr1_v2])
    target_v2 = mq_fixture.make_target(
        base_sha=base1,
        head_sha=queue_head_v2,
        members=[MergeGroupMember(1, pr1_v2)],
    )
    decision = evaluate_merge_group(
        target_v2,
        source_repo=mq_fixture.repo,
        state_root=mq_fixture.state_root,
        policy=mq_fixture.policy(),
    )
    assert decision.verdict == "PASS"
    assert decision.status_state == "success"
    assert decision.member_proofs[0].reused is True
    assert decision.member_proofs[0].source_run_id == orig_run_id
    assert decision.member_proofs[0].member_run_id == hop1_run_id

    # 若策略关闭单跳沿用，则拒收
    disallowed = evaluate_merge_group(
        target_v2,
        source_repo=mq_fixture.repo,
        state_root=mq_fixture.state_root,
        policy=mq_fixture.policy(allow_single_hop_reused_pass=False),
    )
    assert disallowed.verdict == "ERROR"
    assert disallowed.status_state == "error"
    assert disallowed.reason_code == "member_reuse_not_allowed"

    # 3. 再构造第 2 跳 reused_from（指向 hop1_run_id）必须被拦截
    base2 = mq_fixture.create_branch_commit(
        "main",
        from_ref=base1,
        files={"unrelated2.txt": "main advanced again\n"},
        message="advance main 2",
    )
    pr1_v3 = mq_fixture.create_branch_commit(
        "pr-1-v3",
        from_ref=base2,
        files={"feature.py": "X = 42\n"},
        message="PR 1 rebased 2",
    )
    mq_fixture.write_reused_pass_run(
        pr_number=1,
        base_sha=base2,
        head_sha=pr1_v3,
        origin_run_id=hop1_run_id,
        origin_patch_id=orig_patch_id,
        run_id="reuse-hop2",
    )
    queue_head_v3 = mq_fixture.create_queue_head(base_sha=base2, member_heads=[pr1_v3])
    target_v3 = mq_fixture.make_target(
        base_sha=base2,
        head_sha=queue_head_v3,
        members=[MergeGroupMember(1, pr1_v3)],
    )
    two_hop = evaluate_merge_group(
        target_v3,
        source_repo=mq_fixture.repo,
        state_root=mq_fixture.state_root,
        policy=mq_fixture.policy(),
    )
    assert two_hop.verdict == "ERROR"
    assert two_hop.status_state == "error"
    assert two_hop.reason_code == "member_chained_reuse_not_allowed"


# ---------------------------------------------------------------------------
# 3. 成员 PASS 核验负向全集（Fail-Closed）
# ---------------------------------------------------------------------------


def test_member_missing_pass_and_migrated_rejected(mq_fixture: MergeQueueFixture) -> None:
    pr1_head = mq_fixture.create_branch_commit("pr-1", from_ref=mq_fixture.base_sha, files={"a.txt": "1\n"})
    queue_head = mq_fixture.create_queue_head(base_sha=mq_fixture.base_sha, member_heads=[pr1_head])
    target = mq_fixture.make_target(
        base_sha=mq_fixture.base_sha,
        head_sha=queue_head,
        members=[MergeGroupMember(1, pr1_head)],
    )

    missing = evaluate_merge_group(
        target,
        source_repo=mq_fixture.repo,
        state_root=mq_fixture.state_root,
        policy=mq_fixture.policy(),
    )
    assert missing.verdict == "ERROR"
    assert missing.status_state == "error"
    assert missing.reason_code == "member_missing_pass"

    # 写入 migrated PASS，仍必须拒绝
    mq_fixture.write_direct_pass_run(
        pr_number=1,
        base_sha=mq_fixture.base_sha,
        head_sha=pr1_head,
        extra_outcome={"migrated": {"review_controller": mq_fixture.controller_head}},
    )
    migrated = evaluate_merge_group(
        target,
        source_repo=mq_fixture.repo,
        state_root=mq_fixture.state_root,
        policy=mq_fixture.policy(),
    )
    assert migrated.verdict == "ERROR"
    assert migrated.status_state == "error"
    assert migrated.reason_code == "member_migrated_not_allowed"


@pytest.mark.parametrize("block_source", ["outcome", "receipt", "events_json", "events_plain"])
def test_member_blocked_three_forms_rejected(mq_fixture: MergeQueueFixture, block_source: str) -> None:
    pr1_head = mq_fixture.create_branch_commit("pr-1", from_ref=mq_fixture.base_sha, files={"b.txt": "1\n"})
    folder, _, _ = mq_fixture.write_direct_pass_run(
        pr_number=1,
        base_sha=mq_fixture.base_sha,
        head_sha=pr1_head,
    )
    model0 = DEFAULT_EXPECTED_MODELS[0]
    if block_source == "outcome":
        outcome_path = folder / "outcome.json"
        data = json.loads(outcome_path.read_text(encoding="utf-8"))
        data["reviews"][0]["verdict"] = "BLOCK"
        outcome_path.write_text(json.dumps(data), encoding="utf-8")
    elif block_source == "receipt":
        receipt_path = folder / model0 / "receipt.json"
        data = json.loads(receipt_path.read_text(encoding="utf-8"))
        data["result"]["status"] = "blocked"
        data["result"]["summary"] = "VERDICT: BLOCK\n有阻断项"
        receipt_path.write_text(json.dumps(data), encoding="utf-8")
    elif block_source == "events_json":
        events_path = folder / model0 / "events.jsonl"
        events = [
            {"type": "item.completed", "item": {"type": "agent_message", "text": "讨论一下 VERDICT: PASS"}},
            {
                "type": "item.completed",
                "item": {
                    "type": "agent_message",
                    "text": json.dumps({"status": "blocked", "summary": "VERDICT: BLOCK\n阻断", "findings": [], "validation": []}),
                },
            },
        ]
        events_path.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")
        os.chmod(events_path, 0o600)
    else:
        events_path = folder / model0 / "events.jsonl"
        events = [
            {"type": "item.completed", "item": {"type": "agent_message", "text": "VERDICT: BLOCK 无法通过"}},
        ]
        events_path.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")
        os.chmod(events_path, 0o600)

    queue_head = mq_fixture.create_queue_head(base_sha=mq_fixture.base_sha, member_heads=[pr1_head])
    target = mq_fixture.make_target(
        base_sha=mq_fixture.base_sha,
        head_sha=queue_head,
        members=[MergeGroupMember(1, pr1_head)],
    )
    decision = evaluate_merge_group(
        target,
        source_repo=mq_fixture.repo,
        state_root=mq_fixture.state_root,
        policy=mq_fixture.policy(),
    )
    assert decision.verdict == "ERROR"
    assert decision.status_state == "error"
    assert decision.reason_code == "member_blocked"


def test_events_intermediate_block_mention_not_false_positive(mq_fixture: MergeQueueFixture) -> None:
    pr1_head = mq_fixture.create_branch_commit("pr-1", from_ref=mq_fixture.base_sha, files={"c.txt": "1\n"})
    folder, _, _ = mq_fixture.write_direct_pass_run(
        pr_number=1,
        base_sha=mq_fixture.base_sha,
        head_sha=pr1_head,
    )
    events_path = folder / DEFAULT_EXPECTED_MODELS[0] / "events.jsonl"
    events = [
        {"type": "item.completed", "item": {"type": "agent_message", "text": "检查是否应返回 VERDICT: BLOCK"}},
        {
            "type": "item.completed",
            "item": {
                "type": "agent_message",
                "text": json.dumps(
                    {
                        "status": "completed",
                        "summary": "VERDICT: PASS\n经核查无阻断问题（非 VERDICT: BLOCK）",
                        "findings": [],
                        "validation": ["ok"],
                    },
                    ensure_ascii=False,
                ),
            },
        },
    ]
    events_path.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in events) + "\n", encoding="utf-8")
    os.chmod(events_path, 0o600)

    res = verify_member_pass(
        MergeGroupMember(1, pr1_head),
        repository_id=REPO_ID,
        source_repo=mq_fixture.repo,
        state_root=mq_fixture.state_root,
        policy=mq_fixture.policy(),
    )
    assert res.passed is True


def test_unsettled_run_and_superseded_pass_rejected(mq_fixture: MergeQueueFixture) -> None:
    pr1_head = mq_fixture.create_branch_commit("pr-1", from_ref=mq_fixture.base_sha, files={"u.txt": "1\n"})
    mq_fixture.write_direct_pass_run(
        pr_number=1,
        base_sha=mq_fixture.base_sha,
        head_sha=pr1_head,
        attempt=1,
        registered_at_ns=100,
    )
    # 新增一个未完结 run（已 launch 缺 receipt）
    unsettled_folder, _, _ = mq_fixture.write_direct_pass_run(
        pr_number=1,
        base_sha=mq_fixture.base_sha,
        head_sha=pr1_head,
        attempt=2,
        registered_at_ns=200,
    )
    (unsettled_folder / DEFAULT_EXPECTED_MODELS[1] / "receipt.json").unlink()

    res_unsettled = verify_member_pass(
        MergeGroupMember(1, pr1_head),
        repository_id=REPO_ID,
        source_repo=mq_fixture.repo,
        state_root=mq_fixture.state_root,
        policy=mq_fixture.policy(),
    )
    assert res_unsettled.passed is False
    assert res_unsettled.reason_code == "member_unsettled_run"

    # 补全回执但将 attempt=2 改为 FAILED（旧 PASS 被更晚登记的 FAILED 取代）
    mq_fixture.write_direct_pass_run(
        pr_number=1,
        base_sha=mq_fixture.base_sha,
        head_sha=pr1_head,
        attempt=2,
        verdict="FAILED",
        state="error",
        publication_state="error",
        registered_at_ns=200,
    )
    res_superseded = verify_member_pass(
        MergeGroupMember(1, pr1_head),
        repository_id=REPO_ID,
        source_repo=mq_fixture.repo,
        state_root=mq_fixture.state_root,
        policy=mq_fixture.policy(),
    )
    assert res_superseded.passed is False
    assert res_superseded.reason_code == "member_pass_superseded"

    # 再将 attempt=2 改为 STALE（同样不能复活 attempt=1 的旧 PASS）
    mq_fixture.write_direct_pass_run(
        pr_number=1,
        base_sha=mq_fixture.base_sha,
        head_sha=pr1_head,
        attempt=2,
        verdict="STALE",
        state="error",
        publication_state=None,
        registered_at_ns=200,
    )
    res_stale = verify_member_pass(
        MergeGroupMember(1, pr1_head),
        repository_id=REPO_ID,
        source_repo=mq_fixture.repo,
        state_root=mq_fixture.state_root,
        policy=mq_fixture.policy(),
    )
    assert res_stale.passed is False
    assert res_stale.reason_code == "member_pass_superseded"


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        ("policy_version", "member_policy_mismatch"),
        ("review_contract", "member_contract_mismatch"),
        ("controller_code_head", "member_controller_mismatch"),
        ("deployment_image_id", "member_image_mismatch"),
        ("repository_id", "member_missing_pass"),
        ("patch_id", "member_patch_id_mismatch"),
    ],
)
def test_policy_identity_and_patch_id_mismatches_rejected(
    mq_fixture: MergeQueueFixture,
    mutation: str,
    expected_code: str,
) -> None:
    pr1_head = mq_fixture.create_branch_commit("pr-1", from_ref=mq_fixture.base_sha, files={"m.txt": "1\n"})
    kwargs: dict[str, Any] = {
        "pr_number": 1,
        "base_sha": mq_fixture.base_sha,
        "head_sha": pr1_head,
    }
    if mutation == "policy_version":
        kwargs["policy_version"] = "other-policy-v0"
    elif mutation == "review_contract":
        kwargs["review_contract"] = "sha256:" + ("9" * 64)
    elif mutation == "controller_code_head":
        kwargs["controller_code_head"] = LOW_ENTROPY_SHA_A
    elif mutation == "deployment_image_id":
        kwargs["image_id"] = ALT_IMAGE_ID
    elif mutation == "repository_id":
        kwargs["repository_id"] = REPO_ID + 1
    elif mutation == "patch_id":
        kwargs["patch_id_override"] = "sha256:" + ("f" * 64)

    mq_fixture.write_direct_pass_run(**kwargs)
    res = verify_member_pass(
        MergeGroupMember(1, pr1_head),
        repository_id=REPO_ID,
        source_repo=mq_fixture.repo,
        state_root=mq_fixture.state_root,
        policy=mq_fixture.policy(),
    )
    assert res.passed is False
    assert res.reason_code == expected_code


@pytest.mark.parametrize("tamper", ["symlink_outcome", "group_writable", "corrupt_json"])
def test_filesystem_security_checks_fail_closed(
    mq_fixture: MergeQueueFixture,
    tmp_path: Path,
    tamper: str,
) -> None:
    pr1_head = mq_fixture.create_branch_commit("pr-1", from_ref=mq_fixture.base_sha, files={"sec.txt": "1\n"})
    folder, _, _ = mq_fixture.write_direct_pass_run(
        pr_number=1,
        base_sha=mq_fixture.base_sha,
        head_sha=pr1_head,
    )
    outcome_path = folder / "outcome.json"
    if tamper == "symlink_outcome":
        external = mq_fixture.root / "external_outcome.json"
        external.write_text(outcome_path.read_text(encoding="utf-8"), encoding="utf-8")
        outcome_path.unlink()
        outcome_path.symlink_to(external)
    elif tamper == "group_writable":
        os.chmod(outcome_path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IWGRP | stat.S_IRGRP)
    else:
        outcome_path.write_text("{corrupted json", encoding="utf-8")

    res = verify_member_pass(
        MergeGroupMember(1, pr1_head),
        repository_id=REPO_ID,
        source_repo=mq_fixture.repo,
        state_root=mq_fixture.state_root,
        policy=mq_fixture.policy(),
    )
    assert res.passed is False
    assert res.reason_code == "member_evidence_corrupted"


def test_published_statuses_not_success_rejected(mq_fixture: MergeQueueFixture) -> None:
    pr1_head = mq_fixture.create_branch_commit("pr-1", from_ref=mq_fixture.base_sha, files={"s.txt": "1\n"})
    mq_fixture.write_direct_pass_run(pr_number=1, base_sha=mq_fixture.base_sha, head_sha=pr1_head)
    queue_head = mq_fixture.create_queue_head(base_sha=mq_fixture.base_sha, member_heads=[pr1_head])
    target = mq_fixture.make_target(
        base_sha=mq_fixture.base_sha,
        head_sha=queue_head,
        members=[MergeGroupMember(1, pr1_head)],
    )
    decision = evaluate_merge_group(
        target,
        source_repo=mq_fixture.repo,
        state_root=mq_fixture.state_root,
        policy=mq_fixture.policy(),
        published_statuses={pr1_head: "pending"},
    )
    assert decision.verdict == "ERROR"
    assert decision.status_state == "error"
    assert decision.reason_code == "member_status_not_success"


# ---------------------------------------------------------------------------
# 4. 树不一致、冲突、权限位篡改、顺序错误、对象缺失与重叠文件策略测试
# ---------------------------------------------------------------------------


def test_tree_tampering_smuggled_file_content_and_mode_rejected(mq_fixture: MergeQueueFixture) -> None:
    pr1_head = mq_fixture.create_branch_commit(
        "pr-1",
        from_ref=mq_fixture.base_sha,
        files={"script.sh": "#!/bin/sh\necho ok\n"},
    )
    mq_fixture.write_direct_pass_run(pr_number=1, base_sha=mq_fixture.base_sha, head_sha=pr1_head)

    # 1. 偷渡额外文件
    smuggled_head = mq_fixture.create_queue_head(
        base_sha=mq_fixture.base_sha,
        member_heads=[pr1_head],
        branch_name="q-smuggled",
        extra_files={"backdoor.txt": "evil\n"},
    )
    d1 = evaluate_merge_group(
        mq_fixture.make_target(
            base_sha=mq_fixture.base_sha,
            head_sha=smuggled_head,
            members=[MergeGroupMember(1, pr1_head)],
        ),
        source_repo=mq_fixture.repo,
        state_root=mq_fixture.state_root,
        policy=mq_fixture.policy(),
    )
    assert d1.verdict == "ERROR"
    assert d1.status_state == "error"
    assert d1.reason_code == "tree_mismatch"

    # 2. 文件内容被篡改
    modified_head = mq_fixture.create_queue_head(
        base_sha=mq_fixture.base_sha,
        member_heads=[pr1_head],
        branch_name="q-modified",
        extra_files={"script.sh": "#!/bin/sh\necho tampered\n"},
    )
    d2 = evaluate_merge_group(
        mq_fixture.make_target(
            base_sha=mq_fixture.base_sha,
            head_sha=modified_head,
            members=[MergeGroupMember(1, pr1_head)],
        ),
        source_repo=mq_fixture.repo,
        state_root=mq_fixture.state_root,
        policy=mq_fixture.policy(),
    )
    assert d2.verdict == "ERROR"
    assert d2.reason_code == "tree_mismatch"

    # 3. 文件权限位 100644 -> 100755 篡改
    chmod_head = mq_fixture.create_queue_head(
        base_sha=mq_fixture.base_sha,
        member_heads=[pr1_head],
        branch_name="q-chmod",
        chmod_files={"script.sh": 0o755},
    )
    d3 = evaluate_merge_group(
        mq_fixture.make_target(
            base_sha=mq_fixture.base_sha,
            head_sha=chmod_head,
            members=[MergeGroupMember(1, pr1_head)],
        ),
        source_repo=mq_fixture.repo,
        state_root=mq_fixture.state_root,
        policy=mq_fixture.policy(),
    )
    assert d3.verdict == "ERROR"
    assert d3.reason_code == "tree_mismatch"


def test_tree_conflicts_unrelated_history_ancestor_and_tree_id_checks(mq_fixture: MergeQueueFixture) -> None:
    # 1. 内容冲突：PR1 和 PR2 修改同一行
    pr1_conflict = mq_fixture.create_branch_commit(
        "pr-c1",
        from_ref=mq_fixture.base_sha,
        files={"README.md": "from pr1\n"},
    )
    pr2_conflict = mq_fixture.create_branch_commit(
        "pr-c2",
        from_ref=mq_fixture.base_sha,
        files={"README.md": "from pr2\n"},
    )
    # 构造一个合法后代提交作为伪队列 head
    fake_queue = mq_fixture.create_branch_commit(
        "q-fake-conflict",
        from_ref=mq_fixture.base_sha,
        files={"README.md": "manual resolution\n"},
    )
    res_content = verify_merge_group_tree(
        mq_fixture.make_target(
            base_sha=mq_fixture.base_sha,
            head_sha=fake_queue,
            members=[MergeGroupMember(1, pr1_conflict), MergeGroupMember(2, pr2_conflict)],
        ),
        source_repo=mq_fixture.repo,
    )
    assert res_content.matched is False
    assert res_content.reason_code == "merge_conflict"

    # 2. 删改冲突：PR1 删除 shared.txt，PR2 修改 shared.txt
    pr1_del = mq_fixture.create_branch_commit(
        "pr-del",
        from_ref=mq_fixture.base_sha,
        files={"shared.txt": None},
    )
    pr2_mod = mq_fixture.create_branch_commit(
        "pr-mod",
        from_ref=mq_fixture.base_sha,
        files={"shared.txt": "line1-mod\nline2\n"},
    )
    res_delmod = verify_merge_group_tree(
        mq_fixture.make_target(
            base_sha=mq_fixture.base_sha,
            head_sha=fake_queue,
            members=[MergeGroupMember(1, pr1_del), MergeGroupMember(2, pr2_mod)],
        ),
        source_repo=mq_fixture.repo,
    )
    assert res_delmod.matched is False
    assert res_delmod.reason_code == "merge_conflict"

    # 3. 队列顺序颠倒导致与实际合并树不一致（3 成员中前两位颠倒：PR1 与 PR2 顺序相关）
    # 构造：PR1 改 order.txt="v1"；PR2 改 order.txt="v2"（冲突），伪队列只合了 PR2+PR3 且声明顺序 [PR1, PR2, PR3]
    pr3_ok = mq_fixture.create_branch_commit(
        "pr-3",
        from_ref=mq_fixture.base_sha,
        files={"extra.txt": "ok\n"},
    )
    q_pr2_pr3 = mq_fixture.create_queue_head(
        base_sha=mq_fixture.base_sha,
        member_heads=[pr2_conflict, pr3_ok],
        branch_name="q-order",
    )
    # 顺序少了 PR1 或与真实合入顺序不同：若声明 [PR2, PR3] 实际队列头是只含 [PR3]，也必报 tree_mismatch
    q_only_pr3 = mq_fixture.create_queue_head(
        base_sha=mq_fixture.base_sha,
        member_heads=[pr3_ok],
        branch_name="q-only3",
    )
    res_order = verify_merge_group_tree(
        mq_fixture.make_target(
            base_sha=mq_fixture.base_sha,
            head_sha=q_only_pr3,
            members=[MergeGroupMember(2, pr2_conflict), MergeGroupMember(3, pr3_ok)],
        ),
        source_repo=mq_fixture.repo,
    )
    assert res_order.matched is False
    assert res_order.reason_code == "tree_mismatch"
    assert q_pr2_pr3 != q_only_pr3

    # 4. 无关历史（orphan branch）
    _run_git(mq_fixture.repo, "checkout", "--orphan", "orphan-pr")
    _run_git(mq_fixture.repo, "rm", "-rfq", ".")
    (mq_fixture.repo / "orphan.txt").write_text("unrelated\n", encoding="utf-8")
    _run_git(mq_fixture.repo, "add", "orphan.txt")
    _run_git(mq_fixture.repo, "commit", "-qm", "orphan commit")
    orphan_sha = _run_git(mq_fixture.repo, "rev-parse", "HEAD")
    _run_git(mq_fixture.repo, "checkout", "-q", "main")

    res_orphan = verify_merge_group_tree(
        mq_fixture.make_target(
            base_sha=mq_fixture.base_sha,
            head_sha=q_only_pr3,
            members=[MergeGroupMember(9, orphan_sha)],
        ),
        source_repo=mq_fixture.repo,
    )
    assert res_orphan.matched is False
    assert res_orphan.reason_code == "merge_failed"

    # 5. base_sha 不是 head_sha 的祖先
    res_anc = verify_merge_group_tree(
        mq_fixture.make_target(
            base_sha=mq_fixture.base_sha,
            head_sha=orphan_sha,
            members=[MergeGroupMember(3, pr3_ok)],
        ),
        source_repo=mq_fixture.repo,
    )
    assert res_anc.matched is False
    assert res_anc.reason_code == "base_not_ancestor"

    # 6. expected_head_tree_sha 不匹配
    res_tree_id = verify_merge_group_tree(
        mq_fixture.make_target(
            base_sha=mq_fixture.base_sha,
            head_sha=q_only_pr3,
            members=[MergeGroupMember(3, pr3_ok)],
            expected_head_tree_sha=LOW_ENTROPY_SHA_A,
        ),
        source_repo=mq_fixture.repo,
    )
    assert res_tree_id.matched is False
    assert res_tree_id.reason_code == "head_tree_id_mismatch"

    # 7. 对象缺失 与 非 commit 对象（传 tree SHA）
    res_missing = verify_merge_group_tree(
        mq_fixture.make_target(
            base_sha=mq_fixture.base_sha,
            head_sha=LOW_ENTROPY_SHA_A,
            members=[MergeGroupMember(3, pr3_ok)],
        ),
        source_repo=mq_fixture.repo,
    )
    assert res_missing.matched is False
    assert res_missing.reason_code == "missing_object"

    tree_sha = _run_git(mq_fixture.repo, "rev-parse", f"{pr3_ok}^{{tree}}")
    res_not_commit = verify_merge_group_tree(
        mq_fixture.make_target(
            base_sha=mq_fixture.base_sha,
            head_sha=tree_sha,
            members=[MergeGroupMember(3, pr3_ok)],
        ),
        source_repo=mq_fixture.repo,
    )
    assert res_not_commit.matched is False
    assert res_not_commit.reason_code == "not_commit"


def test_overlapping_files_policy_toggle(mq_fixture: MergeQueueFixture) -> None:
    pr1_head = mq_fixture.create_branch_commit(
        "pr-ov1",
        from_ref=mq_fixture.base_sha,
        files={"shared.txt": "line1-pr1\nline2\nline3\nline4\nline5\nline6\nline7\nline8\n"},
    )
    pr2_head = mq_fixture.create_branch_commit(
        "pr-ov2",
        from_ref=mq_fixture.base_sha,
        files={"shared.txt": "line1\nline2\nline3\nline4\nline5\nline6\nline7\nline8-pr2\n"},
    )
    mq_fixture.write_direct_pass_run(pr_number=1, base_sha=mq_fixture.base_sha, head_sha=pr1_head)
    mq_fixture.write_direct_pass_run(pr_number=2, base_sha=mq_fixture.base_sha, head_sha=pr2_head)
    queue_head = mq_fixture.create_queue_head(base_sha=mq_fixture.base_sha, member_heads=[pr1_head, pr2_head])
    target = mq_fixture.make_target(
        base_sha=mq_fixture.base_sha,
        head_sha=queue_head,
        members=[MergeGroupMember(1, pr1_head), MergeGroupMember(2, pr2_head)],
    )

    allowed = evaluate_merge_group(
        target,
        source_repo=mq_fixture.repo,
        state_root=mq_fixture.state_root,
        policy=mq_fixture.policy(reject_overlapping_files=False),
    )
    assert allowed.verdict == "PASS"
    assert allowed.status_state == "success"
    assert allowed.overlapping_files == ("shared.txt",)

    rejected = evaluate_merge_group(
        target,
        source_repo=mq_fixture.repo,
        state_root=mq_fixture.state_root,
        policy=mq_fixture.policy(reject_overlapping_files=True),
    )
    assert rejected.verdict == "ERROR"
    assert rejected.status_state == "error"
    assert rejected.reason_code == "overlapping_files_rejected"
    assert rejected.overlapping_files == ("shared.txt",)


def test_status_description_strictly_bounded_to_140_chars(mq_fixture: MergeQueueFixture) -> None:
    members: list[MergeGroupMember] = []
    member_heads: list[str] = []
    for pr_num in range(1001, 1026):
        head = mq_fixture.create_branch_commit(
            f"pr-{pr_num}",
            from_ref=mq_fixture.base_sha,
            files={f"f_{pr_num}.txt": f"{pr_num}\n"},
        )
        members.append(MergeGroupMember(pr_num, head))
        member_heads.append(head)
    queue_head = mq_fixture.create_queue_head(base_sha=mq_fixture.base_sha, member_heads=member_heads)
    target = mq_fixture.make_target(
        base_sha=mq_fixture.base_sha,
        head_sha=queue_head,
        members=members,
    )
    # 全部成员均未审，产生 25 个 failed_members，测试截断边界
    decision_err = evaluate_merge_group(
        target,
        source_repo=mq_fixture.repo,
        state_root=mq_fixture.state_root,
        policy=mq_fixture.policy(),
    )
    assert decision_err.verdict == "ERROR"
    assert len(decision_err.failed_members) == 25
    assert len(decision_err.status_description) <= MAX_STATUS_DESCRIPTION_LEN
    assert "\n" not in decision_err.status_description

    # 全部成员补齐 PASS，测试超长 PR 列表的 PASS 文案也 <= 140
    for m in members:
        mq_fixture.write_direct_pass_run(pr_number=m.pr_number, base_sha=mq_fixture.base_sha, head_sha=m.head_sha)
    decision_pass = evaluate_merge_group(
        target,
        source_repo=mq_fixture.repo,
        state_root=mq_fixture.state_root,
        policy=mq_fixture.policy(),
    )
    assert decision_pass.verdict == "PASS"
    assert len(decision_pass.status_description) <= MAX_STATUS_DESCRIPTION_LEN
    assert "\n" not in decision_pass.status_description


def test_historical_same_patch_block_and_sibling_corrupt_run_fail_closed(
    mq_fixture: MergeQueueFixture,
) -> None:
    # 1. PR #1 在旧 base0 上出现过一次 BLOCK，即便同补丁在其他 run 拿过 PASS 且 rebase 复用也必须拦截
    pr1_v1 = mq_fixture.create_branch_commit(
        "pr-1-old",
        from_ref=mq_fixture.base_sha,
        files={"hist.py": "V = 1\n"},
    )
    _, orig_run_id, orig_patch_id = mq_fixture.write_direct_pass_run(
        pr_number=1,
        base_sha=mq_fixture.base_sha,
        head_sha=pr1_v1,
        attempt=1,
        run_id="hist-pass-1",
    )
    mq_fixture.write_direct_pass_run(
        pr_number=1,
        base_sha=mq_fixture.base_sha,
        head_sha=pr1_v1,
        attempt=2,
        run_id="hist-block-2",
        verdict="BLOCK",
        state="failure",
        publication_state="failure",
    )
    base1 = mq_fixture.create_branch_commit(
        "main",
        from_ref=mq_fixture.base_sha,
        files={"other.txt": "advance\n"},
    )
    pr1_v2 = mq_fixture.create_branch_commit(
        "pr-1-new",
        from_ref=base1,
        files={"hist.py": "V = 1\n"},
    )
    mq_fixture.write_reused_pass_run(
        pr_number=1,
        base_sha=base1,
        head_sha=pr1_v2,
        origin_run_id=orig_run_id,
        origin_patch_id=orig_patch_id,
        run_id="hist-reuse-3",
    )
    res_block = verify_member_pass(
        MergeGroupMember(1, pr1_v2),
        repository_id=REPO_ID,
        source_repo=mq_fixture.repo,
        state_root=mq_fixture.state_root,
        policy=mq_fixture.policy(),
    )
    assert res_block.passed is False
    assert res_block.reason_code == "member_blocked"

    # 2. 同 PR 存在一个合法 PASS run，同时存在另一个损坏 run 目录，必须 fail-closed 拒绝
    pr2_head = mq_fixture.create_branch_commit(
        "pr-2",
        from_ref=base1,
        files={"clean.py": "OK = True\n"},
    )
    mq_fixture.write_direct_pass_run(pr_number=2, base_sha=base1, head_sha=pr2_head, attempt=1)
    broken_sibling = mq_fixture.state_root / "runs" / f"r{REPO_ID}-p2-{base1}-{pr2_head}-{POLICY_VERSION}-a99"
    broken_sibling.mkdir(parents=True, mode=0o700)
    (broken_sibling / "target.json").write_text("not-json", encoding="utf-8")
    os.chmod(broken_sibling / "target.json", 0o600)

    res_corrupt = verify_member_pass(
        MergeGroupMember(2, pr2_head),
        repository_id=REPO_ID,
        source_repo=mq_fixture.repo,
        state_root=mq_fixture.state_root,
        policy=mq_fixture.policy(),
    )
    assert res_corrupt.passed is False
    assert res_corrupt.reason_code == "member_evidence_corrupted"


def test_symlink_mode_tampering_in_queue_tree_rejected(mq_fixture: MergeQueueFixture) -> None:
    pr1_head = mq_fixture.create_branch_commit(
        "pr-sym",
        from_ref=mq_fixture.base_sha,
        files={"link_target.txt": "plain file\n"},
    )
    mq_fixture.write_direct_pass_run(pr_number=1, base_sha=mq_fixture.base_sha, head_sha=pr1_head)

    _run_git(mq_fixture.repo, "checkout", "-q", "-B", "q-symlink", mq_fixture.base_sha)
    _run_git(mq_fixture.repo, "merge", "--no-ff", "-m", "merge pr1", pr1_head)
    target_file = mq_fixture.repo / "link_target.txt"
    target_file.unlink()
    target_file.symlink_to("README.md")
    _run_git(mq_fixture.repo, "add", "link_target.txt")
    _run_git(mq_fixture.repo, "commit", "--amend", "--no-edit", "-q")
    symlink_queue_head = _run_git(mq_fixture.repo, "rev-parse", "HEAD")
    _run_git(mq_fixture.repo, "checkout", "-q", "main")

    decision = evaluate_merge_group(
        mq_fixture.make_target(
            base_sha=mq_fixture.base_sha,
            head_sha=symlink_queue_head,
            members=[MergeGroupMember(1, pr1_head)],
        ),
        source_repo=mq_fixture.repo,
        state_root=mq_fixture.state_root,
        policy=mq_fixture.policy(),
    )
    assert decision.verdict == "ERROR"
    assert decision.status_state == "error"
    assert decision.reason_code == "tree_mismatch"



# ---------------------------------------------------------------------------
# 5. Codex R1 全量 10 项 Important + 1 项 Nit 专项离线回归测试
# ---------------------------------------------------------------------------


def test_source_repo_local_merge_config_isolated(mq_fixture: MergeQueueFixture) -> None:
    """Important 1：源仓 local .git/config（如 merge.default=binary）绝不得影响隔离重放。"""
    orig_text = (mq_fixture.repo / "shared.txt").read_text(encoding="utf-8")
    pr1_head = mq_fixture.create_branch_commit(
        "pr-cfg-1",
        from_ref=mq_fixture.base_sha,
        files={"shared.txt": orig_text.replace("line1", "line1-updated")},
    )
    pr2_head = mq_fixture.create_branch_commit(
        "pr-cfg-2",
        from_ref=mq_fixture.base_sha,
        files={"shared.txt": orig_text.replace("line8", "line8-updated")},
    )
    queue_head = mq_fixture.create_queue_head(
        base_sha=mq_fixture.base_sha,
        member_heads=[pr1_head, pr2_head],
    )
    target = mq_fixture.make_target(
        base_sha=mq_fixture.base_sha,
        head_sha=queue_head,
        members=[MergeGroupMember(1, pr1_head), MergeGroupMember(2, pr2_head)],
    )

    baseline = verify_merge_group_tree(target, source_repo=mq_fixture.repo)
    assert baseline.matched is True
    assert baseline.reason_code == "tree_matched"

    # 污染源仓 local .git/config：merge.default=binary 与自定义 merge driver
    _run_git(mq_fixture.repo, "config", "merge.default", "binary")
    _run_git(mq_fixture.repo, "config", "merge.evil.driver", "false")
    before_objects = _snapshot_objects(mq_fixture.repo / ".git")

    isolated = verify_merge_group_tree(target, source_repo=mq_fixture.repo)
    assert isolated.matched is True
    assert isolated.reason_code == "tree_matched"
    assert isolated.expected_tree_sha == baseline.expected_tree_sha
    assert _snapshot_objects(mq_fixture.repo / ".git") == before_objects

    # bare 仓同样兼容且零写入
    bare_repo = mq_fixture.root / "bare-source.git"
    subprocess.run(
        ["git", "clone", "--quiet", "--bare", str(mq_fixture.repo), str(bare_repo)],
        check=True,
    )
    bare_before = _snapshot_objects(bare_repo)
    bare_res = verify_merge_group_tree(target, source_repo=bare_repo)
    assert bare_res.matched is True
    assert bare_res.reason_code == "tree_matched"
    assert _snapshot_objects(bare_repo) == bare_before


def test_member_merge_base_tampered_and_non_unique_rejected(mq_fixture: MergeQueueFixture) -> None:
    """Important 2：重算 patch_id 前必须核验 (base_sha, head_sha) 的真实唯一 merge-base。"""
    base1 = mq_fixture.create_branch_commit(
        "main",
        from_ref=mq_fixture.base_sha,
        files={"advance.txt": "step1\n"},
    )
    pr1_head = mq_fixture.create_branch_commit(
        "pr-mb-1",
        from_ref=base1,
        files={"mb_feat.py": "OK = 1\n"},
    )
    # 篡改 merge_base_sha 指向更早祖先 base0（即便 patch_id 按虚假范围算出匹配也必须拒绝）
    fake_pid = compute_patch_identity(mq_fixture.repo, mq_fixture.base_sha, pr1_head)
    mq_fixture.write_direct_pass_run(
        pr_number=1,
        base_sha=base1,
        head_sha=pr1_head,
        merge_base_sha=mq_fixture.base_sha,
        patch_id_override=fake_pid,
    )
    tampered = verify_member_pass(
        MergeGroupMember(1, pr1_head),
        repository_id=REPO_ID,
        source_repo=mq_fixture.repo,
        state_root=mq_fixture.state_root,
        policy=mq_fixture.policy(),
    )
    assert tampered.passed is False
    assert tampered.reason_code == "member_merge_base_mismatch"

    # Criss-cross 双 merge-base（merge-base --all 返回 2 个提交）必须拒绝
    left = mq_fixture.create_branch_commit("cc-left", from_ref=base1, files={"cc_l.txt": "L\n"})
    right = mq_fixture.create_branch_commit("cc-right", from_ref=base1, files={"cc_r.txt": "R\n"})
    merged_q = mq_fixture.create_queue_head(base_sha=left, member_heads=[right], branch_name="cc-tmp")
    merged_tree = _run_git(mq_fixture.repo, "rev-parse", f"{merged_q}^{{tree}}")
    x_commit = _run_git(mq_fixture.repo, "commit-tree", merged_tree, "-p", left, "-p", right, "-m", "cc-x")
    y_commit = _run_git(mq_fixture.repo, "commit-tree", merged_tree, "-p", right, "-p", left, "-m", "cc-y")
    mq_fixture.write_direct_pass_run(
        pr_number=2,
        base_sha=x_commit,
        head_sha=y_commit,
        merge_base_sha=left,
        patch_id_override=compute_patch_identity(mq_fixture.repo, left, y_commit),
    )
    criss_cross = verify_member_pass(
        MergeGroupMember(2, y_commit),
        repository_id=REPO_ID,
        source_repo=mq_fixture.repo,
        state_root=mq_fixture.state_root,
        policy=mq_fixture.policy(),
    )
    assert criss_cross.passed is False
    assert criss_cross.reason_code == "member_merge_base_mismatch"


@pytest.mark.parametrize(
    ("tamper_case", "expected_code"),
    [
        ("missing_launch", "member_launch_invalid"),
        ("launch_pr_mismatch", "member_launch_invalid"),
        ("launch_mode_mismatch", "member_launch_invalid"),
        ("launch_base_sha_mismatch", "member_launch_invalid"),
        ("launch_id_duplicate", "member_launch_invalid"),
        ("receipt_launch_id_mismatch", "member_receipt_invalid"),
        ("receipt_base_sha_mismatch", "member_receipt_invalid"),
        ("receipt_merge_base_mismatch", "member_receipt_invalid"),
        ("receipt_controller_mismatch", "member_receipt_invalid"),
        ("receipt_sandbox_mismatch", "member_receipt_invalid"),
        ("receipt_exit_code_bool", "member_receipt_invalid"),
        ("receipt_turn_not_completed", "member_receipt_invalid"),
        ("receipt_container_id_invalid", "member_receipt_invalid"),
        ("receipt_before_drift", "member_receipt_invalid"),
        ("receipt_after_drift", "member_receipt_invalid"),
        ("receipt_filesystem_missing", "member_receipt_invalid"),
        ("receipt_session_collision", "member_session_invalid"),
        ("missing_session_jsonl", "member_session_invalid"),
        ("session_jsonl_id_mismatch", "member_session_invalid"),
        ("outcome_run_id_mismatch", "member_outcome_invalid"),
        ("outcome_target_head_mismatch", "member_outcome_invalid"),
        ("publication_sha_mismatch", "member_publication_invalid"),
        ("publication_id_missing", "member_publication_invalid"),
        ("publication_desc_mismatch", "member_publication_invalid"),
    ],
)
def test_direct_pass_full_evidence_binding_tamper_matrix(
    mq_fixture: MergeQueueFixture,
    tamper_case: str,
    expected_code: str,
) -> None:
    """Important 3：直审证据（launch/receipt/session/outcome/publication）全字段强绑定负测。"""
    pr1_head = mq_fixture.create_branch_commit("pr-bind", from_ref=mq_fixture.base_sha, files={"bind.py": "X = 1\n"})
    folder, _, _ = mq_fixture.write_direct_pass_run(
        pr_number=1,
        base_sha=mq_fixture.base_sha,
        head_sha=pr1_head,
    )
    m0, m1 = DEFAULT_EXPECTED_MODELS[0], DEFAULT_EXPECTED_MODELS[1]

    def mutate_json(path: Path, updater: Any) -> None:
        data = json.loads(path.read_text(encoding="utf-8"))
        updater(data)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.chmod(path, 0o600)

    if tamper_case == "missing_launch":
        (folder / m0 / "launch.json").unlink()
    elif tamper_case == "launch_pr_mismatch":
        mutate_json(folder / m0 / "launch.json", lambda d: d.__setitem__("pr_number", 999))
    elif tamper_case == "launch_mode_mismatch":
        mutate_json(folder / m0 / "launch.json", lambda d: d.__setitem__("mode", "execute"))
    elif tamper_case == "launch_base_sha_mismatch":
        mutate_json(folder / m0 / "launch.json", lambda d: d.__setitem__("base_sha", LOW_ENTROPY_SHA_A))
    elif tamper_case == "launch_id_duplicate":
        l0 = json.loads((folder / m0 / "launch.json").read_text(encoding="utf-8"))["launch_id"]
        mutate_json(folder / m1 / "launch.json", lambda d: d.__setitem__("launch_id", l0))
        mutate_json(folder / m1 / "receipt.json", lambda d: d.__setitem__("launch_id", l0))
    elif tamper_case == "receipt_launch_id_mismatch":
        mutate_json(folder / m0 / "receipt.json", lambda d: d.__setitem__("launch_id", "wrong-launch"))
    elif tamper_case == "receipt_base_sha_mismatch":
        mutate_json(folder / m0 / "receipt.json", lambda d: d.__setitem__("base_sha", LOW_ENTROPY_SHA_A))
    elif tamper_case == "receipt_merge_base_mismatch":
        mutate_json(folder / m0 / "receipt.json", lambda d: d.__setitem__("merge_base_sha", LOW_ENTROPY_SHA_A))
    elif tamper_case == "receipt_controller_mismatch":
        mutate_json(folder / m0 / "receipt.json", lambda d: d.__setitem__("controller_code_head", LOW_ENTROPY_SHA_A))
    elif tamper_case == "receipt_sandbox_mismatch":
        mutate_json(folder / m0 / "receipt.json", lambda d: d.__setitem__("sandbox", "host-rw"))
    elif tamper_case == "receipt_exit_code_bool":
        mutate_json(folder / m0 / "receipt.json", lambda d: d.__setitem__("exit_code", False))
    elif tamper_case == "receipt_turn_not_completed":
        mutate_json(folder / m0 / "receipt.json", lambda d: d.__setitem__("turn_completed", False))
    elif tamper_case == "receipt_container_id_invalid":
        mutate_json(folder / m0 / "receipt.json", lambda d: d.__setitem__("container_id", "not-hex"))
    elif tamper_case == "receipt_before_drift":
        mutate_json(folder / m0 / "receipt.json", lambda d: d["before"].__setitem__("status", "M bind.py"))
    elif tamper_case == "receipt_after_drift":
        mutate_json(folder / m0 / "receipt.json", lambda d: d["after"].__setitem__("branch", "main"))
    elif tamper_case == "receipt_filesystem_missing":
        mutate_json(folder / m0 / "receipt.json", lambda d: d.pop("filesystem", None))
    elif tamper_case == "receipt_session_collision":
        s0 = json.loads((folder / m0 / "receipt.json").read_text(encoding="utf-8"))["session_id"]
        mutate_json(folder / m1 / "receipt.json", lambda d: d.__setitem__("session_id", s0))
        (folder / m1 / "session.jsonl").write_text(
            json.dumps({"type": "session_meta", "payload": {"id": s0}}) + "\n",
            encoding="utf-8",
        )
        mutate_json(folder / "outcome.json", lambda d: d["reviews"][1].__setitem__("session_id", s0))
    elif tamper_case == "missing_session_jsonl":
        (folder / m0 / "session.jsonl").unlink()
    elif tamper_case == "session_jsonl_id_mismatch":
        (folder / m0 / "session.jsonl").write_text(
            json.dumps({"type": "session_meta", "payload": {"id": "other-session"}}) + "\n",
            encoding="utf-8",
        )
    elif tamper_case == "outcome_run_id_mismatch":
        mutate_json(folder / "outcome.json", lambda d: d.__setitem__("run_id", "other-run"))
    elif tamper_case == "outcome_target_head_mismatch":
        mutate_json(folder / "outcome.json", lambda d: d["target"].__setitem__("head_sha", LOW_ENTROPY_SHA_A))
    elif tamper_case == "publication_sha_mismatch":
        mutate_json(folder / "outcome.json", lambda d: d["publication"].__setitem__("sha", LOW_ENTROPY_SHA_B))
    elif tamper_case == "publication_id_missing":
        mutate_json(folder / "outcome.json", lambda d: d["publication"].pop("id", None))
    elif tamper_case == "publication_desc_mismatch":
        mutate_json(folder / "outcome.json", lambda d: d["publication"].__setitem__("description", "forged success"))

    res = verify_member_pass(
        MergeGroupMember(1, pr1_head),
        repository_id=REPO_ID,
        source_repo=mq_fixture.repo,
        state_root=mq_fixture.state_root,
        policy=mq_fixture.policy(),
    )
    assert res.passed is False
    assert res.reason_code == expected_code


@pytest.mark.parametrize(
    ("tamper_case", "expected_code"),
    [
        ("missing_admission", "member_reuse_admission_missing"),
        ("wrong_admission_image", "member_image_mismatch"),
        ("wrong_admission_controller", "member_controller_mismatch"),
        ("wrong_origin_head_sha", "member_reuse_binding_invalid"),
        ("wrong_origin_base_sha", "member_reuse_binding_invalid"),
        ("wrong_origin_merge_base", "member_reuse_binding_invalid"),
        ("wrong_origin_pub_sha", "member_reuse_binding_invalid"),
        ("member_pub_missing_reuse_desc", "member_publication_invalid"),
    ],
)
def test_single_hop_reuse_admission_and_source_binding_enforced(
    mq_fixture: MergeQueueFixture,
    tamper_case: str,
    expected_code: str,
) -> None:
    """Important 4：1 跳 reused_from 强制校验生产格式 reused_from.admission 与完整来源绑定。"""
    pr1_v1 = mq_fixture.create_branch_commit("pr-r-v1", from_ref=mq_fixture.base_sha, files={"r.py": "V = 1\n"})
    _, orig_run_id, orig_patch_id = mq_fixture.write_direct_pass_run(
        pr_number=1,
        base_sha=mq_fixture.base_sha,
        head_sha=pr1_v1,
        run_id="orig-reuse-1",
    )
    base1 = mq_fixture.create_branch_commit("main", from_ref=mq_fixture.base_sha, files={"m2.txt": "adv\n"})
    pr1_v2 = mq_fixture.create_branch_commit("pr-r-v2", from_ref=base1, files={"r.py": "V = 1\n"})
    folder, _ = mq_fixture.write_reused_pass_run(
        pr_number=1,
        base_sha=base1,
        head_sha=pr1_v2,
        origin_run_id=orig_run_id,
        origin_patch_id=orig_patch_id,
        run_id="hop1-reuse",
    )
    outcome_path = folder / "outcome.json"
    data = json.loads(outcome_path.read_text(encoding="utf-8"))
    if tamper_case == "missing_admission":
        data["reused_from"].pop("admission", None)
        # 即便顶层放了非生产 admission，也绝不可替代 reused_from.admission
        data["admission"] = {"controller_code_head": mq_fixture.controller_head, "image_id": IMAGE_ID}
    elif tamper_case == "wrong_admission_image":
        data["reused_from"]["admission"]["image_id"] = ALT_IMAGE_ID
    elif tamper_case == "wrong_admission_controller":
        data["reused_from"]["admission"]["controller_code_head"] = LOW_ENTROPY_SHA_A
    elif tamper_case == "wrong_origin_head_sha":
        data["reused_from"]["head_sha"] = LOW_ENTROPY_SHA_A
    elif tamper_case == "wrong_origin_base_sha":
        data["reused_from"]["base_sha"] = LOW_ENTROPY_SHA_A
    elif tamper_case == "wrong_origin_merge_base":
        data["reused_from"]["merge_base_sha"] = LOW_ENTROPY_SHA_A
    elif tamper_case == "wrong_origin_pub_sha":
        data["reused_from"]["publication"]["sha"] = LOW_ENTROPY_SHA_A
    elif tamper_case == "member_pub_missing_reuse_desc":
        data["publication"]["description"] = (
            f"run=hop1-reuse b={base1[:12]} h={pr1_v2[:12]} success"
        )
    outcome_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.chmod(outcome_path, 0o600)

    res = verify_member_pass(
        MergeGroupMember(1, pr1_v2),
        repository_id=REPO_ID,
        source_repo=mq_fixture.repo,
        state_root=mq_fixture.state_root,
        policy=mq_fixture.policy(),
    )
    assert res.passed is False
    assert res.reason_code == expected_code


@pytest.mark.parametrize("sep", ["\u2028", "\u2029", "\u0085"])
def test_unicode_line_separator_block_aligned_with_external_review(
    mq_fixture: MergeQueueFixture,
    sep: str,
) -> None:
    """Important 5：含 Unicode 行分隔符的 BLOCK 判定与 external_review._message_blocks 逐案一致。"""
    msg = json.dumps({"status": "completed", "summary": f"VERDICT: BLOCK{sep}follow-up"}, ensure_ascii=False)
    assert external_review._message_blocks(msg) is True
    assert mgr._message_blocks(msg) is True

    pr1_head = mq_fixture.create_branch_commit("pr-uni", from_ref=mq_fixture.base_sha, files={"uni.txt": "1\n"})
    folder, _, _ = mq_fixture.write_direct_pass_run(
        pr_number=1,
        base_sha=mq_fixture.base_sha,
        head_sha=pr1_head,
    )
    events_path = folder / DEFAULT_EXPECTED_MODELS[0] / "events.jsonl"
    events_path.write_text(
        json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": msg}}, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
    os.chmod(events_path, 0o600)

    res = verify_member_pass(
        MergeGroupMember(1, pr1_head),
        repository_id=REPO_ID,
        source_repo=mq_fixture.repo,
        state_root=mq_fixture.state_root,
        policy=mq_fixture.policy(),
    )
    assert res.passed is False
    assert res.reason_code == "member_blocked"


def test_ancestor_symlink_above_state_root_rejected(mq_fixture: MergeQueueFixture) -> None:
    """Important 6：state_root 上方祖先路径含软链（root/alias/state）必须拒绝。"""
    pr1_head = mq_fixture.create_branch_commit("pr-anc", from_ref=mq_fixture.base_sha, files={"anc.txt": "1\n"})
    mq_fixture.write_direct_pass_run(pr_number=1, base_sha=mq_fixture.base_sha, head_sha=pr1_head)

    alias = mq_fixture.root / "alias"
    alias.symlink_to(mq_fixture.root, target_is_directory=True)
    aliased_state = alias / "state"
    assert not aliased_state.is_symlink()
    assert aliased_state.is_dir()

    res = verify_member_pass(
        MergeGroupMember(1, pr1_head),
        repository_id=REPO_ID,
        source_repo=mq_fixture.repo,
        state_root=aliased_state,
        policy=mq_fixture.policy(),
    )
    assert res.passed is False
    assert res.reason_code == "member_evidence_corrupted"


def test_parse_merge_queue_entries_tail_null_commits_and_tail_pagination() -> None:
    """Important 7：允许目标前缀之后的合法队尾条目 commit 为 null，且前缀已满时不因队尾 hasNextPage 误拒。"""
    n1 = {
        "position": 1,
        "state": "AWAITING_CHECKS",
        "baseCommit": {"oid": LOW_ENTROPY_SHA_A},
        "headCommit": {"oid": LOW_ENTROPY_SHA_B},
        "pullRequest": {"number": 11, "headRefOid": LOW_ENTROPY_SHA_C},
    }
    n2_tail_null = {
        "position": 2,
        "state": "QUEUED",
        "baseCommit": None,
        "headCommit": None,
        "headRefName": None,
        "pullRequest": {"number": 12, "headRefOid": "5" * 40},
    }
    payload_with_tail = {
        "databaseId": REPO_ID,
        "nameWithOwner": REPO_NAME,
        "mergeQueue": {
            "entries": {
                "pageInfo": {"hasNextPage": True},
                "nodes": [n1, n2_tail_null],
            }
        },
    }
    target = parse_merge_queue_entries(payload_with_tail, target_head_sha=LOW_ENTROPY_SHA_B)
    assert [(m.pr_number, m.head_sha) for m in target.members] == [(11, LOW_ENTROPY_SHA_C)]

    # 若空 commit 出现在必需前缀内（position=1 为 null，目标在 position=2），必须拒绝
    n1_null = {
        "position": 1,
        "state": "QUEUED",
        "baseCommit": None,
        "headCommit": None,
        "pullRequest": {"number": 11, "headRefOid": LOW_ENTROPY_SHA_C},
    }
    n2_target = {
        "position": 2,
        "state": "AWAITING_CHECKS",
        "baseCommit": {"oid": LOW_ENTROPY_SHA_A},
        "headCommit": {"oid": LOW_ENTROPY_SHA_B},
        "pullRequest": {"number": 12, "headRefOid": "5" * 40},
    }
    bad_prefix_payload = {
        "databaseId": REPO_ID,
        "nameWithOwner": REPO_NAME,
        "mergeQueue": {"entries": {"nodes": [n1_null, n2_target]}},
    }
    with pytest.raises(MergeGroupError, match="baseCommit"):
        parse_merge_queue_entries(bad_prefix_payload, target_head_sha=LOW_ENTROPY_SHA_B)


def test_overlap_query_failure_fails_closed(mq_fixture: MergeQueueFixture) -> None:
    """Important 8：重叠文件查询失败绝不得静默返回 set()，必须 fail-closed 裁为 overlap_query_failed。"""
    pr1_head = mq_fixture.create_branch_commit("pr-ovf", from_ref=mq_fixture.base_sha, files={"ovf.txt": "1\n"})
    mq_fixture.write_direct_pass_run(pr_number=1, base_sha=mq_fixture.base_sha, head_sha=pr1_head)
    queue_head = mq_fixture.create_queue_head(base_sha=mq_fixture.base_sha, member_heads=[pr1_head])
    target = mq_fixture.make_target(
        base_sha=mq_fixture.base_sha,
        head_sha=queue_head,
        members=[MergeGroupMember(1, pr1_head)],
    )

    real_run_git = mgr._run_git

    def fail_overlap_diff(repo: Path, *args: str, **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        if args and args[0] == "diff-tree" and "--name-only" in args:
            return subprocess.CompletedProcess(list(args), 128, b"", b"fatal: object read failed")
        return real_run_git(repo, *args, **kwargs)

    with patch.object(mgr, "_run_git", fail_overlap_diff):
        tree_res = verify_merge_group_tree(target, source_repo=mq_fixture.repo)
        assert tree_res.matched is False
        assert tree_res.reason_code == "overlap_query_failed"

        decision = evaluate_merge_group(
            target,
            source_repo=mq_fixture.repo,
            state_root=mq_fixture.state_root,
            policy=mq_fixture.policy(reject_overlapping_files=True),
        )
        assert decision.verdict == "ERROR"
        assert decision.status_state == "error"
        assert decision.reason_code == "overlap_query_failed"


def test_public_status_description_never_leaks_git_stderr_or_local_paths(
    mq_fixture: MergeQueueFixture,
) -> None:
    """Important 9：远端 GitHub status_description 严禁泄漏 Git stderr、本地路径或异常原文。"""
    pr1_head = mq_fixture.create_branch_commit("pr-leak", from_ref=mq_fixture.base_sha, files={"leak.txt": "1\n"})
    mq_fixture.write_direct_pass_run(pr_number=1, base_sha=mq_fixture.base_sha, head_sha=pr1_head)
    target = mq_fixture.make_target(
        base_sha=mq_fixture.base_sha,
        head_sha=pr1_head,
        members=[MergeGroupMember(1, pr1_head)],
    )

    real_run_git = mgr._run_git

    def fake_merge_tree_error(repo: Path, *args: str, **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        if args and args[0] == "merge-tree":
            return subprocess.CompletedProcess(
                list(args),
                128,
                b"",
                b"LOCAL_DIAGNOSTIC_ONLY /private/secret/host/path",
            )
        return real_run_git(repo, *args, **kwargs)

    with patch.object(mgr, "_run_git", fake_merge_tree_error):
        decision = evaluate_merge_group(
            target,
            source_repo=mq_fixture.repo,
            state_root=mq_fixture.state_root,
            policy=mq_fixture.policy(),
        )
    payload = decision.to_status_payload()
    assert payload["state"] == "error"
    assert len(payload["description"]) <= MAX_STATUS_DESCRIPTION_LEN
    assert "LOCAL_DIAGNOSTIC_ONLY" not in payload["description"]
    assert "/private/secret/host/path" not in payload["description"]
    assert str(mq_fixture.root) not in payload["description"]
    assert "merge_failed" in payload["description"]


def test_evidence_recursion_error_and_oversized_file_fail_closed(
    mq_fixture: MergeQueueFixture,
) -> None:
    """Important 10：证据解码 RecursionError 与超限文件均不得逃逸，统一转为 member_evidence_corrupted。"""
    pr1_head = mq_fixture.create_branch_commit("pr-rec", from_ref=mq_fixture.base_sha, files={"rec.txt": "1\n"})
    mq_fixture.write_direct_pass_run(pr_number=1, base_sha=mq_fixture.base_sha, head_sha=pr1_head)
    queue_head = mq_fixture.create_queue_head(base_sha=mq_fixture.base_sha, member_heads=[pr1_head])
    target = mq_fixture.make_target(
        base_sha=mq_fixture.base_sha,
        head_sha=queue_head,
        members=[MergeGroupMember(1, pr1_head)],
    )

    with patch.object(mgr.json, "loads", side_effect=RecursionError("decoder depth exceeded")):
        member_res = verify_member_pass(
            MergeGroupMember(1, pr1_head),
            repository_id=REPO_ID,
            source_repo=mq_fixture.repo,
            state_root=mq_fixture.state_root,
            policy=mq_fixture.policy(),
        )
        assert member_res.passed is False
        assert member_res.reason_code == "member_evidence_corrupted"

        decision = evaluate_merge_group(
            target,
            source_repo=mq_fixture.repo,
            state_root=mq_fixture.state_root,
            policy=mq_fixture.policy(),
        )
        assert decision.verdict == "ERROR"
        assert decision.status_state == "error"
        assert decision.reason_code == "member_evidence_corrupted"

    # 超过 MAX_JSON_EVIDENCE_BYTES 的证据文件必须被拒绝（不加载整文件）
    with patch.object(mgr, "MAX_JSON_EVIDENCE_BYTES", 64):
        oversized_res = verify_member_pass(
            MergeGroupMember(1, pr1_head),
            repository_id=REPO_ID,
            source_repo=mq_fixture.repo,
            state_root=mq_fixture.state_root,
            policy=mq_fixture.policy(),
        )
        assert oversized_res.passed is False
        assert oversized_res.reason_code == "member_evidence_corrupted"


@pytest.mark.parametrize(
    "bad_branch",
    [
        ".hidden",
        "dir/.hidden",
        "name.lock",
        "dir/name.lock",
        "main.",
        "dir./branch",
        "main..dev",
        "main@{0}",
        "@",
        "main~1",
        "main^2",
        "a:b",
        "a?b",
        "a*b",
        "a[b",
        "a\\b",
        "/main",
        "main/",
        "a//b",
        "main\x01",
        "main branch",
    ],
)
def test_branch_name_rejects_git_check_ref_format_violations(bad_branch: str) -> None:
    """Nit：严格按 Git check-ref-format 规则拒绝非法分支名。"""
    with pytest.raises(MergeGroupError):
        parse_merge_group_ref(
            f"gh-readonly-queue/{bad_branch}/pr-1-{LOW_ENTROPY_SHA_A}",
            expected_base_branch=bad_branch,
        )
