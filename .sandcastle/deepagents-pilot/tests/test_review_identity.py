"""external_review 可换用审查专用 App：身份只来自 IDENTITY_CONFIG，安装权限按该身份的期望集合精确比较。"""
import json
import os
from pathlib import Path

import httpx
import pytest

import pilot1742.github_app as app
from pilot1742 import external_review as module
from pilot1742 import review_sweep
from pilot1742.external_review import DEFAULT_IDENTITY, TOKEN_PERMISSIONS, load_identity
from pilot1742.github_app import (
    INSTALLATION_PERMISSIONS,
    AppIdentity,
    GitHubAppClient,
    IdentityError,
)

REVIEWER = {"app_id": 5664795, "installation_id": 179776757, "app_slug": "newchanlun-review-gate",
            "installation_permissions": TOKEN_PERMISSIONS}
KEY = Path("/unused-fixture.pem")


def write(folder: Path, value) -> Path:
    path = folder / "review-app.json"
    path.write_text(json.dumps(value))
    return path


def fake_github(identity: AppIdentity, installed: dict[str, str]):
    def transport(request):
        path = request.url.path
        if path == "/app":
            value = {"id": identity.app_id, "slug": identity.app_slug}
        elif path.endswith("/access_tokens"):
            value = {"token": "fixture", "permissions": json.loads(request.content)["permissions"],
                     "expires_at": "2099-01-01T00:00:00Z"}
        elif path == f"/app/installations/{identity.installation_id}":
            value = {"id": identity.installation_id, "app_id": identity.app_id, "app_slug": identity.app_slug,
                     "account": {"login": "Newchanlun"}, "repository_selection": "selected",
                     "suspended_at": None, "permissions": installed}
        elif path == "/installation/repositories":
            value = {"total_count": 1, "repositories": [{"id": 1150335160, "full_name": "Newchanlun/NewChanlun"}]}
        elif path == "/repos/Newchanlun/NewChanlun":
            value = {"id": 1150335160, "full_name": "Newchanlun/NewChanlun"}
        else:
            pytest.fail(f"unexpected {path}")
        return httpx.Response(200, json=value)
    return httpx.MockTransport(transport)


@pytest.fixture(autouse=True)
def no_key(monkeypatch):
    monkeypatch.setattr(app, "_read_private_key", lambda path: b"fixture")
    monkeypatch.setattr(app.jwt, "encode", lambda *a, **kw: "fixture-jwt")


def test_reviewer_identity_with_narrow_permissions_verifies(tmp_path):
    identity = load_identity(write(tmp_path, REVIEWER), KEY)
    assert (identity.app_id, identity.installation_id, identity.app_slug) == (5664795, 179776757,
                                                                               "newchanlun-review-gate")
    assert identity.installation_permissions == TOKEN_PERMISSIONS
    with GitHubAppClient(identity, permissions=TOKEN_PERMISSIONS,
                         transport=fake_github(identity, TOKEN_PERMISSIONS)) as client:
        result = client.verify()
        assert client.bot_login == "newchanlun-review-gate[bot]"
    assert result["app_id"] == 5664795 and result["token_permissions"] == TOKEN_PERMISSIONS


@pytest.mark.parametrize("installed", [
    INSTALLATION_PERMISSIONS,                               # 安装比期望宽
    {**TOKEN_PERMISSIONS, "contents": "write"},             # 同名权限升级
    {k: v for k, v in TOKEN_PERMISSIONS.items() if k != "metadata"},  # 少一项
])
def test_reviewer_identity_rejects_mismatched_installation(tmp_path, installed):
    identity = load_identity(write(tmp_path, REVIEWER), KEY)
    with GitHubAppClient(identity, permissions=TOKEN_PERMISSIONS,
                         transport=fake_github(identity, installed)) as client:
        with pytest.raises(IdentityError, match="permissions"):
            client.verify()


def test_default_identity_unchanged_and_rejects_narrow_installation(tmp_path):
    identity = load_identity(tmp_path / "absent.json", KEY)
    assert identity == AppIdentity(5486877, 179444545, 1150335160, "Newchanlun/NewChanlun",
                                   "newchanlun-deepagents-1742", KEY)
    assert identity.installation_permissions == INSTALLATION_PERMISSIONS
    with GitHubAppClient(identity, permissions=TOKEN_PERMISSIONS,
                         transport=fake_github(identity, INSTALLATION_PERMISSIONS)) as client:
        assert client.verify()["app_id"] == 5486877
    with GitHubAppClient(identity, permissions=TOKEN_PERMISSIONS,
                         transport=fake_github(identity, TOKEN_PERMISSIONS)) as client:
        with pytest.raises(IdentityError, match="permissions"):
            client.verify()


def test_token_request_cannot_exceed_identity_permissions():
    identity = AppIdentity(5664795, 179776757, 1150335160, "Newchanlun/NewChanlun", "newchanlun-review-gate",
                           KEY, dict(TOKEN_PERMISSIONS))
    with pytest.raises(IdentityError, match="超出"):
        GitHubAppClient(identity, permissions={**TOKEN_PERMISSIONS, "contents": "write"})
    with pytest.raises(IdentityError, match="超出"):
        GitHubAppClient(identity)  # 缺省只读集合含 actions/issues，审查 App 没有


def test_identity_permissions_are_copied():
    source = dict(TOKEN_PERMISSIONS)
    identity = AppIdentity(5664795, 179776757, 1150335160, "Newchanlun/NewChanlun", "newchanlun-review-gate",
                           KEY, source)
    source["administration"] = "write"
    assert identity.installation_permissions == TOKEN_PERMISSIONS
    with pytest.raises(TypeError):
        identity.installation_permissions["administration"] = "write"  # type: ignore[index]
    assert DEFAULT_IDENTITY["installation_permissions"] == INSTALLATION_PERMISSIONS


@pytest.mark.parametrize("value", [
    {**REVIEWER, "repository": "other/repo"},
    {k: v for k, v in REVIEWER.items() if k != "installation_permissions"},
    {**REVIEWER, "installation_permissions": {}},
    {**REVIEWER, "installation_permissions": {"statuses": "admin"}},
    {**REVIEWER, "installation_permissions": ["statuses"]},
    {**REVIEWER, "app_id": "5664795"},
    {**REVIEWER, "app_id": True},
    {**REVIEWER, "app_slug": 7},
    [REVIEWER],
])
def test_malformed_config_fails_closed(tmp_path, value):
    with pytest.raises(IdentityError):
        load_identity(write(tmp_path, value), KEY)


def test_config_path_must_be_absolute_and_outside_git(tmp_path):
    with pytest.raises(IdentityError, match="绝对"):
        load_identity(Path("review-app.json"), KEY)
    (tmp_path / ".git").mkdir()
    with pytest.raises(IdentityError, match="Git"):
        load_identity(write(tmp_path, REVIEWER), KEY)
    dangling = tmp_path / "outside" / "dangling.json"
    dangling.parent.mkdir()
    os.symlink(tmp_path / "missing-target.json", dangling)
    (tmp_path / ".git").rmdir()
    with pytest.raises(IdentityError, match="无法读取"):
        load_identity(dangling, KEY)  # 存在但读不了：拒绝，不回退缺省


def capture_clients(monkeypatch):
    seen = []
    def client(identity, **kwargs):
        seen.append((identity.app_id, identity.app_slug, identity.installation_permissions, kwargs["permissions"]))
        raise IdentityError("stop before network")
    monkeypatch.setattr(module, "GitHubAppClient", client)
    return seen


DEFAULT_SEEN = (5486877, "newchanlun-deepagents-1742", INSTALLATION_PERMISSIONS, TOKEN_PERMISSIONS)
REVIEWER_SEEN = (5664795, "newchanlun-review-gate", TOKEN_PERMISSIONS, TOKEN_PERMISSIONS)


@pytest.mark.parametrize("command", ["review-pr", "migrate-stale"])
def test_cli_reads_identity_config(tmp_path, monkeypatch, command):
    seen = capture_clients(monkeypatch)
    assert module.main([command, "--pr", "1810", "--private-key", str(KEY)]) == 2
    monkeypatch.setattr(module, "IDENTITY_CONFIG", write(tmp_path, REVIEWER))
    assert module.main([command, "--pr", "1810", "--private-key", str(KEY)]) == 2
    assert seen == [DEFAULT_SEEN, REVIEWER_SEEN]


def test_cli_has_no_identity_override_flag(tmp_path):
    with pytest.raises(SystemExit) as caught:
        module.main(["review-pr", "--pr", "1810", "--private-key", str(KEY),
                     "--app-identity", str(write(tmp_path, REVIEWER))])
    assert caught.value.code == 2


def test_cli_bad_config_fails_before_client(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "GitHubAppClient", lambda *a, **kw: pytest.fail("must not build client"))
    monkeypatch.setattr(module, "IDENTITY_CONFIG", write(tmp_path, {**REVIEWER, "extra": 1}))
    assert module.main(["review-pr", "--pr", "1810", "--private-key", str(KEY)]) == 2


def test_sweep_review_uses_configured_reviewer_identity(tmp_path, monkeypatch):
    """review_sweep 派出的审查（run-review 子进程入口）与手动 review-pr 读同一个身份文件。"""
    seen = capture_clients(monkeypatch)
    class GitHub:
        def pr(self, number):
            return {"head": "a" * 40}
    argv = ["--pr", "1810", "--attempt", "1", "--expect-head", "a" * 40, "--private-key", str(KEY)]
    assert review_sweep.run_review(argv, GitHub()) == 2
    monkeypatch.setattr(module, "IDENTITY_CONFIG", write(tmp_path, REVIEWER))
    assert review_sweep.run_review(argv, GitHub()) == 2
    assert seen == [DEFAULT_SEEN, REVIEWER_SEEN]
