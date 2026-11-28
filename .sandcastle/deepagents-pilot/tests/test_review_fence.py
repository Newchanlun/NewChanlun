import json
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import test_external_review as _external_review
from conftest import Env, git

from pilot1742 import external_review as _module
from pilot1742.external_review import ExternalReview, unwrap_json_fence

# 与 .sandcastle/codex-child.test.ts 的 FENCE_CASES 同一组用例。
CASES = [
    ('{"a":1}', '{"a":1}'),
    ('```json\n{"a":1}\n```', '{"a":1}'),
    ('  ```\n{"a":1}\n```\n', '{"a":1}'),
    ('```json\r\n{"a":1}\r\n```', '{"a":1}'),
    ('说明\n```json\n{"a":1}\n```', '说明\n```json\n{"a":1}\n```'),
    ('```json\n{"a":1}\n```\n补充', '```json\n{"a":1}\n```\n补充'),
    ('```json\n{"a":1}\n```\n```json\n{"b":2}\n```', '{"a":1}\n```\n```json\n{"b":2}'),
]


@pytest.fixture(scope="module")
def _lane_template(tmp_path_factory):
    env = Env(tmp_path_factory.mktemp("review-fence-tpl"))
    for i in range(2):
        (env.source / f"changed-{i}").write_text(str(i))
        git(env.source, "add", ".")
        git(env.source, "commit", "-qm", f"change-{i}")
    head = git(env.source, "rev-parse", "HEAD")
    return SimpleNamespace(source=env.source, home=env.home, base=env.base, head=head)


@pytest.fixture
def lane(_lane_template, tmp_path, monkeypatch):
    source = tmp_path / "source"
    home = tmp_path / "home"
    shutil.copytree(_lane_template.source, source)
    shutil.copytree(_lane_template.home, home)
    monkeypatch.setattr(_module, "SOURCE_REPO", source)
    gateway = object.__new__(_external_review.Gateway)
    gateway.client = SimpleNamespace(identity=SimpleNamespace(repository_id=1150335160))
    gateway.pr = {
        "number": 1810,
        "state": "open",
        "draft": False,
        "user": {"login": "business-owner"},
        "base": {"repo": {"id": 1150335160}, "ref": "main", "sha": _lane_template.base},
        "head": {"repo": {"id": 1150335160}, "ref": "feature/business", "sha": _lane_template.head},
    }
    gateway.rows, gateway.sent = [], []
    gateway.fault, gateway.hide, gateway.after_write = False, False, None
    return ExternalReview(
        gateway,
        source=source,
        state_root=home / "review",
        checkout_root=home / "clones",
        poll_seconds=0.01,
        launcher=[sys.executable, str(Path(__file__).with_name("external_review_child.py"))],
    )


@pytest.mark.parametrize(("text", "expected"), CASES)
def test_only_a_whole_single_fence_is_unwrapped(text, expected):
    assert unwrap_json_fence(text) == expected


@pytest.mark.parametrize(("fence", "verdict", "reason"), [
    ("whole", "PASS", None),
    ("prose", "FAILED", "缺日志、解析失败或日志不符"),  # 围栏外有文字：json.loads 抛 ValueError
    ("nonstring", "FAILED", "结果与监督 stdout 不符"),  # text 不是字符串：按缺最终消息
])
def test_fenced_final_message_is_validated_like_plain_json(lane, fence, verdict, reason):
    (lane.state_root / "runs").mkdir(parents=True, exist_ok=True)
    (lane.state_root / "runs" / "fake-fence").write_text(fence)
    result = lane.review_pr(1810)
    assert result["verdict"] == verdict
    if reason is not None:
        assert result["reviews"][0]["reason"] == reason
        json.dumps(result)  # 失败结论原样可序列化
