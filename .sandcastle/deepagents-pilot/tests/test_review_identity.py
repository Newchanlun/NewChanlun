"""external_review 可换用审查专用 App：身份来自显式 JSON，安装权限按该身份的期望集合精确比较。"""
import json
from pathlib import Path

import httpx
import pytest

import pilot1742.github_app as app
from pilot1742 import external_review as module
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


def test_default_identity_unchanged_and_rejects_narrow_installation():
    identity = load_identity(None, KEY)
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
    with pytest.raises(IdentityError, match="无法读取"):
        load_identity(Path("/nonexistent-review-identity/x.json"), KEY)


@pytest.mark.parametrize("command", ["review-pr", "migrate-stale"])
def test_cli_passes_selected_identity(tmp_path, monkeypatch, command):
    seen = []
    class Stop(IdentityError):
        pass
    def client(identity, **kwargs):
        seen.append((identity, kwargs["permissions"]))
        raise Stop("stop before network")
    monkeypatch.setattr(module, "GitHubAppClient", client)
    assert module.main([command, "--pr", "1810", "--private-key", str(KEY)]) == 2
    assert module.main([command, "--pr", "1810", "--private-key", str(KEY),
                        "--app-identity", str(write(tmp_path, REVIEWER))]) == 2
    assert [(i.app_id, i.app_slug, i.installation_permissions, p) for i, p in seen] == [
        (5486877, "newchanlun-deepagents-1742", INSTALLATION_PERMISSIONS, TOKEN_PERMISSIONS),
        (5664795, "newchanlun-review-gate", TOKEN_PERMISSIONS, TOKEN_PERMISSIONS),
    ]


def test_cli_bad_config_fails_before_client(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "GitHubAppClient", lambda *a, **kw: pytest.fail("must not build client"))
    path = write(tmp_path, {**REVIEWER, "extra": 1})
    assert module.main(["review-pr", "--pr", "1810", "--private-key", str(KEY), "--app-identity", str(path)]) == 2
