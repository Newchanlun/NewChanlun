from __future__ import annotations

import errno
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


def _run_git_raw(repo: Path, *args: str) -> str:
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
    return proc.stdout


def _run_git(repo: Path, *args: str) -> str:
    return _run_git_raw(repo, *args).strip()


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
        diff_output = _run_git_raw(
            self.repo,
            "diff",
            "--no-ext-diff",
            "--no-textconv",
            "--no-color",
            "--src-prefix=a/",
            "--dst-prefix=b/",
            mb,
            head_sha,
        )
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
            result_payload: dict[str, Any] = {
                "status": result_status,
                "summary": summary,
                "findings": [],
                "validation": ["ok"],
            }
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
                    "result": result_payload,
                },
            )
            session_path = worker / "session.jsonl"
            session_path.write_text(
                json.dumps({"type": "session_meta", "payload": {"id": session_id}}) + "\n",
                encoding="utf-8",
            )
            os.chmod(session_path, 0o600)
            events_path = worker / "events.jsonl"
            events_payload = [
                {"type": "thread.started", "thread_id": session_id},
                {
                    "type": "item.completed",
                    "item": {
                        "type": "command_execution",
                        "command": f"/bin/bash -lc 'git diff --no-ext-diff --no-textconv {mb} {head_sha}'",
                        "status": "completed",
                        "exit_code": 0,
                        "aggregated_output": diff_output,
                    },
                },
                {
                    "type": "item.completed",
                    "item": {
                        "type": "agent_message",
                        "text": json.dumps(result_payload, ensure_ascii=False),
                    },
                },
                {"type": "turn.completed"},
            ]
            events_path.write_text(
                "\n".join(json.dumps(e, ensure_ascii=False) for e in events_payload) + "\n",
                encoding="utf-8",
            )
            os.chmod(events_path, 0o600)
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
    worker_dir = folder / DEFAULT_EXPECTED_MODELS[0]
    receipt_path = worker_dir / "receipt.json"
    receipt_data = json.loads(receipt_path.read_text(encoding="utf-8"))
    updated_result = {
        "status": "completed",
        "summary": "VERDICT: PASS\n经核查无阻断问题（非 VERDICT: BLOCK）",
        "findings": [],
        "validation": ["ok"],
    }
    receipt_data["result"] = updated_result
    receipt_path.write_text(json.dumps(receipt_data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.chmod(receipt_path, 0o600)

    events_path = worker_dir / "events.jsonl"
    existing_events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    events = [
        existing_events[0],  # thread.started
        existing_events[1],  # command_execution reading frozen patch
        {"type": "item.completed", "item": {"type": "agent_message", "text": "检查是否应返回 VERDICT: BLOCK"}},
        {
            "type": "item.completed",
            "item": {
                "type": "agent_message",
                "text": json.dumps(updated_result, ensure_ascii=False),
            },
        },
        {"type": "turn.completed"},
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
    # 使用标准 JSON 转义写入 events.jsonl（ensure_ascii=True），使 JSONL 保持单行合法且解码后 text 含原始 Unicode 行分隔符
    events_path.write_text(
        json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": msg}}, ensure_ascii=True)
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
    """Nit：严格按 Git check-ref-format --branch 规则拒绝非法分支名。"""
    with pytest.raises(MergeGroupError):
        parse_merge_group_ref(
            f"gh-readonly-queue/{bad_branch}/pr-1-{LOW_ENTROPY_SHA_A}",
            expected_base_branch=bad_branch,
        )


@pytest.mark.parametrize("valid_branch", ["feat./ok", "dir./branch"])
def test_branch_name_allows_interior_trailing_dot_segment(valid_branch: str) -> None:
    """Nit：对齐 git check-ref-format --branch，允许非末尾路径段以 '.' 结尾。"""
    parsed = parse_merge_group_ref(
        f"refs/heads/gh-readonly-queue/{valid_branch}/pr-1-{LOW_ENTROPY_SHA_A}",
        expected_base_branch=valid_branch,
    )
    assert parsed.base_branch == valid_branch
    assert parsed.lead_pr == 1
    assert parsed.base_sha == LOW_ENTROPY_SHA_A


# ---------------------------------------------------------------------------
# 6. Codex R2 全量 6 项 Important + 1 项 Nit 离线回归测试（含 5 项现场探针固化）
# ---------------------------------------------------------------------------


def test_r2_events_fixture_passes_both_external_review_and_merge_group(
    mq_fixture: MergeQueueFixture,
) -> None:
    """Important 1（探针 events）：正例夹具下 events.jsonl 存在，且 external_review 与 merge_group 均 PASS。"""
    head = mq_fixture.create_branch_commit("pr-ev", from_ref=mq_fixture.base_sha, files={"f": "v1"})
    folder, _, _ = mq_fixture.write_direct_pass_run(pr_number=1, base_sha=mq_fixture.base_sha, head_sha=head)
    target_json = json.loads((folder / "target.json").read_text(encoding="utf-8"))
    for model in DEFAULT_EXPECTED_MODELS:
        worker = folder / model
        assert (worker / "events.jsonl").is_file()
        outcome = external_review.validate_review(
            external_review.ReviewTarget(**target_json),
            json.loads((worker / "launch.json").read_text(encoding="utf-8")),
            json.loads((worker / "receipt.json").read_text(encoding="utf-8")),
            worker,
            mq_fixture.repo,
        )
        assert outcome.verdict == "PASS", f"{model}: {outcome.reason}"

    decision = evaluate_merge_group(
        mq_fixture.make_target(base_sha=mq_fixture.base_sha, head_sha=head, members=[MergeGroupMember(1, head)]),
        source_repo=mq_fixture.repo,
        state_root=mq_fixture.state_root,
        policy=mq_fixture.policy(),
    )
    assert decision.verdict == "PASS"
    assert decision.status_state == "success"

    # 合法 Reconnecting... k/n (...)（1 <= k <= n）且之后重新输出 fenced JSON + turn.completed 仍 PASS
    worker0 = folder / DEFAULT_EXPECTED_MODELS[0]
    ev_lines = [
        json.loads(line)
        for line in (worker0 / "events.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    receipt_result = json.loads((worker0 / "receipt.json").read_text(encoding="utf-8"))["result"]
    fenced_text = "```json\n" + json.dumps(receipt_result, ensure_ascii=False) + "\n```"
    reconnected_events = [
        ev_lines[0],
        {"type": "item.completed", "item": {"type": "agent_message", "text": "stale partial"}},
        {"type": "turn.completed"},
        {"type": "error", "message": "Reconnecting... 1/3 (rate limit)"},
        ev_lines[1],
        {"type": "item.completed", "item": {"type": "agent_message", "text": fenced_text}},
        {"type": "turn.completed"},
    ]
    (worker0 / "events.jsonl").write_text(
        "\n".join(json.dumps(e, ensure_ascii=False) for e in reconnected_events) + "\n",
        encoding="utf-8",
    )
    os.chmod(worker0 / "events.jsonl", 0o600)
    reconnected_decision = evaluate_merge_group(
        mq_fixture.make_target(base_sha=mq_fixture.base_sha, head_sha=head, members=[MergeGroupMember(1, head)]),
        source_repo=mq_fixture.repo,
        state_root=mq_fixture.state_root,
        policy=mq_fixture.policy(),
    )
    assert reconnected_decision.verdict == "PASS"


@pytest.mark.parametrize(
    ("tamper", "expected_code"),
    [
        ("missing_events", "member_events_invalid"),
        ("missing_turn_completed", "member_events_invalid"),
        ("thread_id_mismatch", "member_events_invalid"),
        ("missing_thread_started", "member_events_invalid"),
        ("zero_patch_reads", "member_events_invalid"),
        ("patch_read_nonzero_exit", "member_events_invalid"),
        ("agent_message_mismatch", "member_events_invalid"),
        ("agent_message_non_json", "member_evidence_corrupted"),
        ("non_reconnect_error", "member_events_invalid"),
        ("reconnect_out_of_range", "member_events_invalid"),
        ("reconnect_without_followup_turn_completed", "member_events_invalid"),
        ("turn_failed", "member_events_invalid"),
        ("turn_cancelled", "member_events_invalid"),
        ("receipt_result_extra_key", "member_receipt_invalid"),
        ("receipt_result_bad_findings_type", "member_receipt_invalid"),
        ("events_symlink", "member_evidence_corrupted"),
        ("events_oversized", "member_evidence_corrupted"),
    ],
)
def test_r2_events_tamper_matrix_rejected_direct_and_reuse_origin(
    mq_fixture: MergeQueueFixture,
    tamper: str,
    expected_code: str,
) -> None:
    """Important 1：直审与 1 跳 reused_from 原件对 events.jsonl 与 receipt.result 缺损/篡改一律 ERROR/error。"""
    head_v1 = mq_fixture.create_branch_commit("pr-ev-v1", from_ref=mq_fixture.base_sha, files={"f.py": "A = 1\n"})
    folder, orig_rid, orig_pid = mq_fixture.write_direct_pass_run(
        pr_number=1,
        base_sha=mq_fixture.base_sha,
        head_sha=head_v1,
        run_id="orig-ev-1",
    )
    base1 = mq_fixture.create_branch_commit("main", from_ref=mq_fixture.base_sha, files={"unrelated.txt": "u\n"})
    head_v2 = mq_fixture.create_branch_commit("pr-ev-v2", from_ref=base1, files={"f.py": "A = 1\n"})
    mq_fixture.write_reused_pass_run(
        pr_number=1,
        base_sha=base1,
        head_sha=head_v2,
        origin_run_id=orig_rid,
        origin_patch_id=orig_pid,
        run_id="reuse-ev-1",
    )

    worker = folder / DEFAULT_EXPECTED_MODELS[0]
    events_path = worker / "events.jsonl"
    receipt_path = worker / "receipt.json"
    events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def write_events(new_events: list[dict[str, Any]]) -> None:
        events_path.write_text(
            "\n".join(json.dumps(e, ensure_ascii=False) for e in new_events) + "\n",
            encoding="utf-8",
        )
        os.chmod(events_path, 0o600)

    size_patch_ctx: Any = None
    if tamper == "missing_events":
        events_path.unlink()
    elif tamper == "missing_turn_completed":
        write_events([e for e in events if e.get("type") != "turn.completed"])
    elif tamper == "thread_id_mismatch":
        events[0]["thread_id"] = "sess-other-thread"
        write_events(events)
    elif tamper == "missing_thread_started":
        write_events([e for e in events if e.get("type") != "thread.started"])
    elif tamper == "zero_patch_reads":
        events[1]["item"]["command"] = "/bin/bash -lc 'echo hello'"
        events[1]["item"]["aggregated_output"] = "hello\n"
        write_events(events)
    elif tamper == "patch_read_nonzero_exit":
        events[1]["item"]["exit_code"] = 1
        write_events(events)
    elif tamper == "agent_message_mismatch":
        events[2]["item"]["text"] = json.dumps(
            {"status": "completed", "summary": "VERDICT: PASS\n不同摘要", "findings": [], "validation": ["ok"]},
            ensure_ascii=False,
        )
        write_events(events)
    elif tamper == "agent_message_non_json":
        events[2]["item"]["text"] = "plain pass without json"
        write_events(events)
    elif tamper == "non_reconnect_error":
        events.insert(1, {"type": "error", "message": "fatal upstream error"})
        write_events(events)
    elif tamper == "reconnect_out_of_range":
        events.insert(1, {"type": "error", "message": "Reconnecting... 4/3 (rate limit)"})
        write_events(events)
    elif tamper == "reconnect_without_followup_turn_completed":
        events.append({"type": "error", "message": "Reconnecting... 1/3 (rate limit)"})
        write_events(events)
    elif tamper == "turn_failed":
        events.append({"type": "turn.failed", "error": {"message": "failed"}})
        write_events(events)
    elif tamper == "turn_cancelled":
        events.append({"type": "turn.cancelled"})
        write_events(events)
    elif tamper == "receipt_result_extra_key":
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipt["result"]["extra"] = "unexpected"
        receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.chmod(receipt_path, 0o600)
        events[2]["item"]["text"] = json.dumps(receipt["result"], ensure_ascii=False)
        write_events(events)
    elif tamper == "receipt_result_bad_findings_type":
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipt["result"]["findings"] = [123]
        receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.chmod(receipt_path, 0o600)
        events[2]["item"]["text"] = json.dumps(receipt["result"], ensure_ascii=False)
        write_events(events)
    elif tamper == "events_symlink":
        ext = mq_fixture.root / "ext-events.jsonl"
        ext.write_text(events_path.read_text(encoding="utf-8"), encoding="utf-8")
        events_path.unlink()
        events_path.symlink_to(ext)
    elif tamper == "events_oversized":
        size_patch_ctx = patch.object(mgr, "MAX_LOG_EVIDENCE_BYTES", 32)

    q_direct = mq_fixture.create_queue_head(base_sha=mq_fixture.base_sha, member_heads=[head_v1], branch_name="q-d")
    q_reuse = mq_fixture.create_queue_head(base_sha=base1, member_heads=[head_v2], branch_name="q-r")
    t_direct = mq_fixture.make_target(
        base_sha=mq_fixture.base_sha, head_sha=q_direct, members=[MergeGroupMember(1, head_v1)]
    )
    t_reuse = mq_fixture.make_target(base_sha=base1, head_sha=q_reuse, members=[MergeGroupMember(1, head_v2)])

    def _run_checks() -> None:
        d_direct = evaluate_merge_group(
            t_direct, source_repo=mq_fixture.repo, state_root=mq_fixture.state_root, policy=mq_fixture.policy()
        )
        assert d_direct.verdict == "ERROR"
        assert d_direct.status_state == "error"
        assert d_direct.reason_code == expected_code

        d_reuse = evaluate_merge_group(
            t_reuse, source_repo=mq_fixture.repo, state_root=mq_fixture.state_root, policy=mq_fixture.policy()
        )
        assert d_reuse.verdict == "ERROR"
        assert d_reuse.status_state == "error"
        assert d_reuse.reason_code == expected_code

    if size_patch_ctx is not None:
        with size_patch_ctx:
            _run_checks()
    else:
        _run_checks()


def test_r2_binding_exact_description_four_field_reuse_pub_and_registered_at_ns(
    mq_fixture: MergeQueueFixture,
) -> None:
    """Important 2 & 3（探针 binding）：精确等值校验 description、4 字段比对 reused_from.publication 与 registered_at_ns。"""
    head1 = mq_fixture.create_branch_commit("pr-b1", from_ref=mq_fixture.base_sha, files={"f": "v1"})
    orig_folder, orig_rid, orig_pid = mq_fixture.write_direct_pass_run(
        pr_number=1, base_sha=mq_fixture.base_sha, head_sha=head1
    )
    b2 = mq_fixture.create_branch_commit("b2", from_ref=mq_fixture.base_sha, files={"other": "other"})
    head2 = mq_fixture.create_branch_commit("h2", from_ref=b2, files={"f": "v1"})
    reuse_folder, _ = mq_fixture.write_reused_pass_run(
        pr_number=1, base_sha=b2, head_sha=head2, origin_run_id=orig_rid, origin_patch_id=orig_pid
    )

    class Watch(dict[str, Any]):
        def __init__(self, value: dict[str, Any]) -> None:
            super().__init__(value)
            self.keys_read: set[str] = set()

        def get(self, k: str, *args: Any) -> Any:
            self.keys_read.add(k)
            return super().get(k, *args)

        def __getitem__(self, k: str) -> Any:
            self.keys_read.add(k)
            return super().__getitem__(k)

    observed: dict[str, Any] = {}
    real_read = mgr._safe_read_json_dict

    class Desc(str):
        def __contains__(self, sub: object) -> bool:
            observed["description_matching"] = "substring"
            return super().__contains__(str(sub))

    def track(*args: Any, **kwargs: Any) -> dict[str, Any]:
        data = real_read(*args, **kwargs)
        if args[1].name == "outcome.json":
            data["publication"]["description"] = Desc(data["publication"]["description"])
            data["target"] = Watch(data["target"])
            observed["target"] = data["target"]
            if "reused_from" in data:
                rf = data["reused_from"]
                rf["publication"] = Watch(rf["publication"])
                observed["source_publication"] = rf["publication"]
        return data

    with patch.object(mgr, "_safe_read_json_dict", side_effect=track):
        res = verify_member_pass(
            MergeGroupMember(1, head2),
            repository_id=REPO_ID,
            source_repo=mq_fixture.repo,
            state_root=mq_fixture.state_root,
            policy=mq_fixture.policy(),
        )
    assert res.passed is True
    assert "description_matching" not in observed
    assert sorted(observed["source_publication"].keys_read) == ["description", "id", "sha", "state"]
    assert "registered_at_ns" in observed["target"].keys_read

    # 负测 1：直审 publication.description 添加前后缀多余字符必须拒收
    orig_outcome_path = orig_folder / "outcome.json"
    orig_outcome_bak = orig_outcome_path.read_text(encoding="utf-8")
    orig_data = json.loads(orig_outcome_bak)
    orig_data["publication"]["description"] = "prefix " + orig_data["publication"]["description"] + " suffix"
    orig_outcome_path.write_text(json.dumps(orig_data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.chmod(orig_outcome_path, 0o600)
    res_extra_direct = verify_member_pass(
        MergeGroupMember(1, head1),
        repository_id=REPO_ID,
        source_repo=mq_fixture.repo,
        state_root=mq_fixture.state_root,
        policy=mq_fixture.policy(),
    )
    assert res_extra_direct.passed is False
    assert res_extra_direct.reason_code == "member_publication_invalid"
    orig_outcome_path.write_text(orig_outcome_bak, encoding="utf-8")
    os.chmod(orig_outcome_path, 0o600)

    # 负测 2：1 跳 reused_from 篡改 publication.description / id / reviews 及顶层 publication.description 多余后缀
    reuse_outcome_path = reuse_folder / "outcome.json"
    reuse_outcome_bak = reuse_outcome_path.read_text(encoding="utf-8")
    for field_case, expected in (
        ("top_desc_suffix", "member_publication_invalid"),
        ("reused_pub_id", "member_reuse_binding_invalid"),
        ("reused_pub_desc", "member_reuse_binding_invalid"),
        ("reused_reviews", "member_reuse_binding_invalid"),
    ):
        data = json.loads(reuse_outcome_bak)
        if field_case == "top_desc_suffix":
            data["publication"]["description"] += " extra"
        elif field_case == "reused_pub_id":
            data["reused_from"]["publication"]["id"] = 999_999_999
        elif field_case == "reused_pub_desc":
            data["reused_from"]["publication"]["description"] += " forged"
        elif field_case == "reused_reviews":
            data["reused_from"]["reviews"] = []
        reuse_outcome_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.chmod(reuse_outcome_path, 0o600)
        r_bad = verify_member_pass(
            MergeGroupMember(1, head2),
            repository_id=REPO_ID,
            source_repo=mq_fixture.repo,
            state_root=mq_fixture.state_root,
            policy=mq_fixture.policy(),
        )
        assert r_bad.passed is False
        assert r_bad.reason_code == expected
    reuse_outcome_path.write_text(reuse_outcome_bak, encoding="utf-8")
    os.chmod(reuse_outcome_path, 0o600)


def test_r2_registered_at_ns_tampering_rejected_before_sorting(mq_fixture: MergeQueueFixture) -> None:
    """Important 3：篡改任一 run 的 outcome.target.registered_at_ns（含历史 run 或 bool）必须拒收为 member_evidence_corrupted。"""
    head = mq_fixture.create_branch_commit("pr-ts", from_ref=mq_fixture.base_sha, files={"ts.txt": "1\n"})
    folder1, _, _ = mq_fixture.write_direct_pass_run(
        pr_number=1, base_sha=mq_fixture.base_sha, head_sha=head, attempt=1, registered_at_ns=500
    )
    # 1. 直接篡改当前 PASS run 的 outcome.target.registered_at_ns（含 bool 伪装）
    out1 = folder1 / "outcome.json"
    bak1 = out1.read_text(encoding="utf-8")
    for bad_ts in (499, True, None):
        data = json.loads(bak1)
        data["target"]["registered_at_ns"] = bad_ts
        out1.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.chmod(out1, 0o600)
        res = verify_member_pass(
            MergeGroupMember(1, head),
            repository_id=REPO_ID,
            source_repo=mq_fixture.repo,
            state_root=mq_fixture.state_root,
            policy=mq_fixture.policy(),
        )
        assert res.passed is False
        assert res.reason_code == "member_evidence_corrupted"
    out1.write_text(bak1, encoding="utf-8")
    os.chmod(out1, 0o600)

    # 2. 更晚失败 run 的 target.json 时间戳被倒改（attempt=2 实际 outcome 记录 600，但 target.json 改为 100 企图排在 PASS 之前）
    folder2, _, _ = mq_fixture.write_direct_pass_run(
        pr_number=1,
        base_sha=mq_fixture.base_sha,
        head_sha=head,
        attempt=2,
        verdict="FAILED",
        state="error",
        publication_state="error",
        registered_at_ns=600,
    )
    t2_path = folder2 / "target.json"
    t2 = json.loads(t2_path.read_text(encoding="utf-8"))
    t2["registered_at_ns"] = 100
    t2_path.write_text(json.dumps(t2, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.chmod(t2_path, 0o600)

    res_hist = verify_member_pass(
        MergeGroupMember(1, head),
        repository_id=REPO_ID,
        source_repo=mq_fixture.repo,
        state_root=mq_fixture.state_root,
        policy=mq_fixture.policy(),
    )
    assert res_hist.passed is False
    assert res_hist.reason_code == "member_evidence_corrupted"


def test_r2_crisscross_multibase_no_spurious_overlap(mq_fixture: MergeQueueFixture) -> None:
    """Important 4（探针 overlap）：criss-cross 多 merge-base 场景按每步树差异统计重叠，无虚假重叠。"""
    head = mq_fixture.create_branch_commit("pr-cc", from_ref=mq_fixture.base_sha, files={"f": "v1"})
    b = mq_fixture.create_branch_commit("b-cc", from_ref=mq_fixture.base_sha, files={"base-only": "v"})
    ab = mq_fixture.create_queue_head(base_sha=head, member_heads=[b], branch_name="ab-cc")
    queue = mq_fixture.create_queue_head(base_sha=b, member_heads=[head, ab], branch_name="q-cc")

    s1 = _run_git(mq_fixture.repo, "rev-parse", f"{queue}^1")
    merge_bases = [x for x in _run_git(mq_fixture.repo, "merge-base", "--all", s1, ab).splitlines() if x.strip()]
    assert len(merge_bases) == 2
    assert _run_git(mq_fixture.repo, "diff", "--name-only", s1, queue) == ""

    target = mq_fixture.make_target(
        base_sha=b,
        head_sha=queue,
        members=[MergeGroupMember(1, head), MergeGroupMember(2, ab)],
    )
    tree_res = verify_merge_group_tree(target, source_repo=mq_fixture.repo)
    assert tree_res.matched is True
    assert tree_res.overlapping_files == ()

    # 开启 reject_overlapping_files=True 且两名成员均有真实 PASS 证据时应 PASS，不误拒
    mq_fixture.write_direct_pass_run(pr_number=1, base_sha=mq_fixture.base_sha, head_sha=head)
    mq_fixture.write_direct_pass_run(pr_number=2, base_sha=b, head_sha=ab)
    decision = evaluate_merge_group(
        target,
        source_repo=mq_fixture.repo,
        state_root=mq_fixture.state_root,
        policy=mq_fixture.policy(reject_overlapping_files=True),
    )
    assert decision.verdict == "PASS"
    assert decision.status_state == "success"
    assert decision.overlapping_files == ()


def test_r2_replay_io_enospc_and_subprocess_errors_caught_without_leaks(
    mq_fixture: MergeQueueFixture,
) -> None:
    """Important 5（探针 io）：隔离仓创建 ENOSPC / Git I/O 异常全路径捕获转为 replay_env_error 且零信息泄漏。"""
    head = mq_fixture.create_branch_commit("pr-io", from_ref=mq_fixture.base_sha, files={"f": "v1"})
    mq_fixture.write_direct_pass_run(pr_number=1, base_sha=mq_fixture.base_sha, head_sha=head)
    member = MergeGroupMember(1, head)
    target = mq_fixture.make_target(base_sha=mq_fixture.base_sha, head_sha=head, members=[member])

    with patch.object(
        mgr.tempfile,
        "TemporaryDirectory",
        side_effect=OSError(errno.ENOSPC, "tmp full /private/secret/disk"),
    ):
        dec = evaluate_merge_group(
            target,
            source_repo=mq_fixture.repo,
            state_root=mq_fixture.state_root,
            policy=mq_fixture.policy(),
        )
        assert dec.verdict == "ERROR"
        assert dec.status_state == "error"
        assert dec.reason_code == "replay_env_error"
        assert "ENOSPC" not in dec.status_description
        assert "tmp full" not in dec.status_description
        assert "/private/secret/disk" not in dec.status_description
        assert len(dec.status_description) <= MAX_STATUS_DESCRIPTION_LEN

        tr = verify_merge_group_tree(target, source_repo=mq_fixture.repo)
        assert tr.matched is False
        assert tr.reason_code == "replay_env_error"

        mv = verify_member_pass(
            member,
            repository_id=REPO_ID,
            source_repo=mq_fixture.repo,
            state_root=mq_fixture.state_root,
            policy=mq_fixture.policy(),
        )
        assert mv.passed is False
        assert mv.reason_code == "replay_env_error"

    with patch.object(mgr, "_run_git", side_effect=subprocess.TimeoutExpired(["git"], 10)):
        dec_to = evaluate_merge_group(
            target,
            source_repo=mq_fixture.repo,
            state_root=mq_fixture.state_root,
            policy=mq_fixture.policy(),
        )
        assert dec_to.verdict == "ERROR"
        assert dec_to.status_state == "error"
        assert dec_to.reason_code == "replay_env_error"


@pytest.mark.parametrize(
    "corrupt_payload",
    [
        b"{\n",
        b"\xff\xfe\n",
        b"[1, 2, 3]\n",
        b'{"type": "item.completed", "item": {"type": "agent_message", "text": 123}}\n',
    ],
)
def test_r2_corrupted_or_truncated_events_attributed_to_evidence_corrupted_not_blocked(
    mq_fixture: MergeQueueFixture,
    corrupt_payload: bytes,
) -> None:
    """Important 6（探针 decode）：截断/损坏 events.jsonl 必须归因 member_evidence_corrupted，绝不得误报 member_blocked。"""
    head = mq_fixture.create_branch_commit("pr-dec", from_ref=mq_fixture.base_sha, files={"f": "v1"})
    folder, _, _ = mq_fixture.write_direct_pass_run(pr_number=1, base_sha=mq_fixture.base_sha, head_sha=head)
    events_path = folder / DEFAULT_EXPECTED_MODELS[0] / "events.jsonl"
    events_path.write_bytes(corrupt_payload)
    os.chmod(events_path, 0o600)

    target = mq_fixture.make_target(base_sha=mq_fixture.base_sha, head_sha=head, members=[MergeGroupMember(1, head)])
    dec = evaluate_merge_group(
        target,
        source_repo=mq_fixture.repo,
        state_root=mq_fixture.state_root,
        policy=mq_fixture.policy(),
    )
    assert dec.verdict == "ERROR"
    assert dec.status_state == "error"
    assert dec.reason_code == "member_evidence_corrupted"


# ---------------------------------------------------------------------------
# 7. Codex R3 全量 3 项 Important 离线回归测试（含 .gitattributes 正向回归）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("sep", ["\u2028", "\u2029", "\u0085"])
def test_r3_unicode_line_separator_in_events_jsonl_aligned_with_external_review(
    mq_fixture: MergeQueueFixture,
    sep: str,
) -> None:
    """Important 1（unicode_log）：events.jsonl 含裸 Unicode 行分隔符时按 str.splitlines() 切行，与 external_review 逐案一致拒绝 PASS。"""
    content = f"first normal changed line\nsecond{sep}third\n"
    head = mq_fixture.create_branch_commit("pr-r3-uni", from_ref=mq_fixture.base_sha, files={"text.dat": content})
    folder, _, _ = mq_fixture.write_direct_pass_run(pr_number=1, base_sha=mq_fixture.base_sha, head_sha=head)
    worker = folder / DEFAULT_EXPECTED_MODELS[0]

    target_json = json.loads((folder / "target.json").read_text(encoding="utf-8"))
    ext_outcome = external_review.validate_review(
        external_review.ReviewTarget(**target_json),
        json.loads((worker / "launch.json").read_text(encoding="utf-8")),
        json.loads((worker / "receipt.json").read_text(encoding="utf-8")),
        worker,
        mq_fixture.repo,
    )
    assert ext_outcome.verdict == "FAILED"

    target = mq_fixture.make_target(base_sha=mq_fixture.base_sha, head_sha=head, members=[MergeGroupMember(1, head)])
    dec = evaluate_merge_group(
        target,
        source_repo=mq_fixture.repo,
        state_root=mq_fixture.state_root,
        policy=mq_fixture.policy(),
    )
    assert dec.verdict == "ERROR"
    assert dec.status_state == "error"
    assert dec.reason_code == "member_evidence_corrupted"


@pytest.mark.parametrize(
    "bad_event",
    [
        {"type": "item.completed", "item": None},
        {"type": "item.completed"},
        {"type": "item.completed", "item": "not-a-dict"},
        {"type": "item.completed", "item": 123},
        {"type": "item.completed", "item": []},
        {"type": "error", "message": None},
        {"type": "error", "message": 404},
    ],
)
def test_r3_malformed_item_completed_and_error_message_fail_closed(
    mq_fixture: MergeQueueFixture,
    bad_event: dict[str, Any],
) -> None:
    """Important 2（bad_item）：损坏的 item.completed（item 非 dict）与非法 error.message 在直审与历史 BLOCK 扫描均 fail-closed 报 member_evidence_corrupted。"""
    head_v1 = mq_fixture.create_branch_commit("pr-r3-bad-v1", from_ref=mq_fixture.base_sha, files={"a.py": "x = 1\n"})
    folder, orig_rid, orig_pid = mq_fixture.write_direct_pass_run(
        pr_number=1, base_sha=mq_fixture.base_sha, head_sha=head_v1, run_id="r3-orig-bad"
    )
    worker = folder / DEFAULT_EXPECTED_MODELS[0]
    events_path = worker / "events.jsonl"
    with events_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(bad_event, ensure_ascii=False) + "\n")
    os.chmod(events_path, 0o600)

    # 1. 与 external_review.validate_review 对拍：含显式非 dict item 或非法 error.message 时绝不产出 PASS
    if "item" in bad_event or bad_event.get("type") == "error":
        target_json = json.loads((folder / "target.json").read_text(encoding="utf-8"))
        try:
            ext_verdict = external_review.validate_review(
                external_review.ReviewTarget(**target_json),
                json.loads((worker / "launch.json").read_text(encoding="utf-8")),
                json.loads((worker / "receipt.json").read_text(encoding="utf-8")),
                worker,
                mq_fixture.repo,
            ).verdict
        except AttributeError:
            ext_verdict = "AttributeError"
        assert ext_verdict != "PASS"

    # 2. 直审与历史 BLOCK 扫描（_run_has_block）均直接报错为 member_evidence_corrupted
    record = mgr._load_run_record(
        mq_fixture.state_root,
        folder,
        expected_models=DEFAULT_EXPECTED_MODELS,
        check_ownership=True,
    )
    with pytest.raises(mgr._EvidenceError):
        mgr._run_has_block(record)

    t_direct = mq_fixture.make_target(
        base_sha=mq_fixture.base_sha, head_sha=head_v1, members=[MergeGroupMember(1, head_v1)]
    )
    dec_direct = evaluate_merge_group(
        t_direct,
        source_repo=mq_fixture.repo,
        state_root=mq_fixture.state_root,
        policy=mq_fixture.policy(),
    )
    assert dec_direct.verdict == "ERROR"
    assert dec_direct.status_state == "error"
    assert dec_direct.reason_code == "member_evidence_corrupted"

    # 3. 作为 1 跳 reused_from 原件同样归因 member_evidence_corrupted
    base1 = mq_fixture.create_branch_commit("main", from_ref=mq_fixture.base_sha, files={"other.txt": "o\n"})
    head_v2 = mq_fixture.create_branch_commit("pr-r3-bad-v2", from_ref=base1, files={"a.py": "x = 1\n"})
    mq_fixture.write_reused_pass_run(
        pr_number=1,
        base_sha=base1,
        head_sha=head_v2,
        origin_run_id=orig_rid,
        origin_patch_id=orig_pid,
        run_id="r3-reuse-bad",
    )
    t_reuse = mq_fixture.make_target(base_sha=base1, head_sha=head_v2, members=[MergeGroupMember(1, head_v2)])
    dec_reuse = evaluate_merge_group(
        t_reuse,
        source_repo=mq_fixture.repo,
        state_root=mq_fixture.state_root,
        policy=mq_fixture.policy(),
    )
    assert dec_reuse.verdict == "ERROR"
    assert dec_reuse.status_state == "error"
    assert dec_reuse.reason_code == "member_evidence_corrupted"


def test_r3_git_signal_exit_mapped_to_replay_env_error(mq_fixture: MergeQueueFixture) -> None:
    """Important 3（signal）：_frozen_patch 与 _run_git 被信号中止（负 returncode 如 -15）全路径归因 replay_env_error。"""
    head = mq_fixture.create_branch_commit("pr-r3-sig", from_ref=mq_fixture.base_sha, files={"sig.txt": "1\n"})
    mq_fixture.write_direct_pass_run(pr_number=1, base_sha=mq_fixture.base_sha, head_sha=head)
    member = MergeGroupMember(1, head)
    target = mq_fixture.make_target(base_sha=mq_fixture.base_sha, head_sha=head, members=[member])
    kw = dict(source_repo=mq_fixture.repo, state_root=mq_fixture.state_root, policy=mq_fixture.policy())

    # 1. _frozen_patch 抛出负返回码 CalledProcessError(-15) / OSError / TimeoutExpired -> replay_env_error
    for exc in (
        subprocess.CalledProcessError(-15, "git"),
        OSError(errno.EIO, "git io error"),
        subprocess.TimeoutExpired(["git"], 5),
    ):
        with patch.object(mgr, "_frozen_patch", side_effect=exc):
            dec = evaluate_merge_group(target, **kw)
            assert dec.verdict == "ERROR"
            assert dec.status_state == "error"
            assert dec.reason_code == "replay_env_error"

            mv = verify_member_pass(member, repository_id=REPO_ID, **kw)
            assert mv.passed is False
            assert mv.reason_code == "replay_env_error"

    # 2. _frozen_patch 抛出正退出码 CalledProcessError(128) 仍归因 member_patch_id_mismatch
    with patch.object(mgr, "_frozen_patch", side_effect=subprocess.CalledProcessError(128, "git")):
        dec_pos = evaluate_merge_group(target, **kw)
        assert dec_pos.verdict == "ERROR"
        assert dec_pos.reason_code == "member_patch_id_mismatch"

    # 3. _run_git / _frozen_patch 内部 subprocess.run 返回负退出码 -15（跨 cat-file / merge-base / merge-tree / diff-tree / diff 全路径）-> replay_env_error
    real_subprocess_run = mgr.subprocess.run
    for target_cmd in ("cat-file", "merge-base", "merge-tree", "diff-tree", "diff"):
        def _kill_on_cmd(
            cmd: list[str],
            *args: Any,
            _target_cmd: str = target_cmd,
            **kwargs: Any,
        ) -> subprocess.CompletedProcess[bytes]:
            if _target_cmd in cmd:
                return subprocess.CompletedProcess(cmd, -15, b"", b"")
            return real_subprocess_run(cmd, *args, **kwargs)

        with patch.object(mgr.subprocess, "run", side_effect=_kill_on_cmd):
            dec_sig = evaluate_merge_group(target, **kw)
            assert dec_sig.verdict == "ERROR"
            assert dec_sig.status_state == "error"
            assert dec_sig.reason_code == "replay_env_error", f"cmd={target_cmd} got {dec_sig.reason_code}"

            if target_cmd in ("cat-file", "merge-tree", "diff-tree"):
                tr_sig = verify_merge_group_tree(target, source_repo=mq_fixture.repo)
                assert tr_sig.matched is False
                assert tr_sig.reason_code == "replay_env_error", f"tree cmd={target_cmd} got {tr_sig.reason_code}"


def test_r3_gitattributes_nodiff_positive_regression(mq_fixture: MergeQueueFixture) -> None:
    """R3/R5 回归：.gitattributes (*.dat -diff) 在 main 真正生效时，普通仓与 bare 仓均 PASS，伪造/删除二进制 diff 仍 fail-closed。"""
    base = mq_fixture.create_branch_commit(
        "main",
        from_ref=mq_fixture.base_sha,
        files={".gitattributes": "*.dat -diff\n", "text.dat": "initial line\n"},
    )
    head = mq_fixture.create_branch_commit("doc-attr", from_ref=base, files={"text.dat": "first normal changed line\n"})

    # 生成直审证据前，显式断言 -diff 在当前工作区真正生效
    attr_status = _run_git(mq_fixture.repo, "check-attr", "diff", "--", "text.dat")
    assert attr_status.endswith("diff: unset"), f"预期 diff: unset，实际：{attr_status!r}"

    folder, _, _ = mq_fixture.write_direct_pass_run(pr_number=1, base_sha=base, head_sha=head)
    worker = folder / DEFAULT_EXPECTED_MODELS[0]

    # 显式断言 events.jsonl 补丁输出为 Git 二进制 diff 而非文本 hunk
    events_lines = (worker / "events.jsonl").read_text(encoding="utf-8").splitlines()
    cmd_outputs = [
        str(ev["item"]["aggregated_output"])
        for line in events_lines
        if (ev := json.loads(line)).get("type") == "item.completed"
        and ev.get("item", {}).get("type") == "command_execution"
    ]
    assert len(cmd_outputs) == 1
    assert "Binary files a/text.dat and b/text.dat differ" in cmd_outputs[0]
    assert "+first normal changed line" not in cmd_outputs[0]

    target_json = json.loads((folder / "target.json").read_text(encoding="utf-8"))
    ext_outcome = external_review.validate_review(
        external_review.ReviewTarget(**target_json),
        json.loads((worker / "launch.json").read_text(encoding="utf-8")),
        json.loads((worker / "receipt.json").read_text(encoding="utf-8")),
        worker,
        mq_fixture.repo,
    )
    assert ext_outcome.verdict == "PASS"

    target = mq_fixture.make_target(base_sha=base, head_sha=head, members=[MergeGroupMember(1, head)])
    dec = evaluate_merge_group(
        target,
        source_repo=mq_fixture.repo,
        state_root=mq_fixture.state_root,
        policy=mq_fixture.policy(),
    )
    assert dec.verdict == "PASS"
    assert dec.status_state == "success"
    assert dec.reason_code == "merge_group_pass_reused"

    # bare 克隆仓无工作区 .gitattributes，同样通过 --attr-source=<head_sha> 准确 PASS
    bare_repo = mq_fixture.root / "repo-attr-bare.git"
    _run_git(mq_fixture.root, "clone", "--bare", "-q", str(mq_fixture.repo), str(bare_repo))
    dec_bare = evaluate_merge_group(
        target,
        source_repo=bare_repo,
        state_root=mq_fixture.state_root,
        policy=mq_fixture.policy(),
    )
    assert dec_bare.verdict == "PASS"
    assert dec_bare.status_state == "success"
    assert dec_bare.reason_code == "merge_group_pass_reused"

    # 负向断言：删除/替换 events.jsonl 中的二进制 diff 输出后，补丁读取证明仍严格拒绝
    tampered_lines: list[str] = []
    for line in events_lines:
        ev = json.loads(line)
        if ev.get("type") == "item.completed" and ev.get("item", {}).get("type") == "command_execution":
            ev["item"]["aggregated_output"] = "unrelated output without patch header\n"
        tampered_lines.append(json.dumps(ev, ensure_ascii=False))
    events_path = worker / "events.jsonl"
    events_path.write_text("\n".join(tampered_lines) + "\n", encoding="utf-8")
    os.chmod(events_path, 0o600)

    for repo_path in (mq_fixture.repo, bare_repo):
        dec_tampered = evaluate_merge_group(
            target,
            source_repo=repo_path,
            state_root=mq_fixture.state_root,
            policy=mq_fixture.policy(),
        )
        assert dec_tampered.verdict == "ERROR"
        assert dec_tampered.status_state == "error"
        assert dec_tampered.reason_code == "member_events_invalid"


def test_r5_subdir_gitattributes_on_non_main_branch_isolated_bare(mq_fixture: MergeQueueFixture) -> None:
    """R5 加固：非 main 分支（含子目录 sub/.gitattributes）下，--attr-source=<head_sha> 在普通仓与 bare 仓均精确生效。"""
    # main 不含 sub/.gitattributes；分支基线引入 sub/.gitattributes 与 sub/data.dat，PR 仅修改 sub/data.dat
    branch_base = mq_fixture.create_branch_commit(
        "feature-base",
        from_ref=mq_fixture.base_sha,
        files={"sub/.gitattributes": "*.dat -diff\n", "sub/data.dat": "before\n"},
    )
    head = mq_fixture.create_branch_commit(
        "feature-pr",
        from_ref=branch_base,
        files={"sub/data.dat": "after subdir change\n"},
    )

    # 确认 main 工作区无 sub/.gitattributes（check-attr 为 unspecified），而 head 树中生效（diff: unset）
    assert _run_git(mq_fixture.repo, "check-attr", "diff", "--", "sub/data.dat").endswith("diff: unspecified")
    assert _run_git(mq_fixture.repo, "--attr-source=" + head, "check-attr", "diff", "--", "sub/data.dat").endswith(
        "diff: unset"
    )

    # 模拟真实审查容器（检出于 target.head_sha）产出的二进制 diff 证据
    container_diff = _run_git_raw(
        mq_fixture.repo,
        f"--attr-source={head}",
        "diff",
        "--no-ext-diff",
        "--no-textconv",
        "--no-color",
        "--src-prefix=a/",
        "--dst-prefix=b/",
        branch_base,
        head,
    )
    assert "Binary files a/sub/data.dat and b/sub/data.dat differ" in container_diff
    assert "+after subdir change" not in container_diff

    folder, _, _ = mq_fixture.write_direct_pass_run(pr_number=2, base_sha=branch_base, head_sha=head)
    for model in DEFAULT_EXPECTED_MODELS:
        ev_path = folder / model / "events.jsonl"
        updated: list[str] = []
        for line in ev_path.read_text(encoding="utf-8").splitlines():
            ev = json.loads(line)
            if ev.get("type") == "item.completed" and ev.get("item", {}).get("type") == "command_execution":
                ev["item"]["aggregated_output"] = container_diff
            updated.append(json.dumps(ev, ensure_ascii=False))
        ev_path.write_text("\n".join(updated) + "\n", encoding="utf-8")
        os.chmod(ev_path, 0o600)

    bare_repo = mq_fixture.root / "repo-subdir-attr-bare.git"
    _run_git(mq_fixture.root, "clone", "--bare", "-q", str(mq_fixture.repo), str(bare_repo))

    target = mq_fixture.make_target(base_sha=branch_base, head_sha=head, members=[MergeGroupMember(2, head)])
    for repo_path in (mq_fixture.repo, bare_repo):
        dec = evaluate_merge_group(
            target,
            source_repo=repo_path,
            state_root=mq_fixture.state_root,
            policy=mq_fixture.policy(),
        )
        assert dec.verdict == "PASS"
        assert dec.status_state == "success"
        assert dec.reason_code == "merge_group_pass_reused"
