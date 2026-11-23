import os
import shlex
import shutil
import subprocess
from types import SimpleNamespace

import pytest
from conftest import Env, git

from pilot1742.boat_execution import _at_base
from pilot1742.cloud_package import build_project_context, export_repository

FILTERED_SKILL = '.agents/skills/project/SKILL.md'
FILTERED_CONTENTS = {
    'filtered': b'hello\n',
    'AGENTS.md': b'project rules\n',
    FILTERED_SKILL: b'project skill\n',
}
LFS_TRACKED = '.chanlun/block-topology/relations.jsonl'
LFS_DATA = b'{"from":"a","to":"b"}\n' * 1000
LFS_CONFIG = (
    '[filter "lfs"]\n'
    '    clean = git-lfs clean -- %f\n'
    '    smudge = git-lfs smudge -- %f\n'
    '    process = git-lfs filter-process\n'
    '    required = true\n'
)


def vm_git(root, *args):
    env = {key: os.environ[key] for key in ('PATH', 'LANG') if key in os.environ}
    env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull)
    return subprocess.run(['git', '-C', str(root), *args], env=env,
                          check=True, capture_output=True).stdout


@pytest.fixture(scope='module')
def base_env_template(tmp_path_factory):
    return Env(tmp_path_factory.mktemp('cloud-pkg-base'))


@pytest.fixture
def env(tmp_path, base_env_template):
    source = tmp_path / 'source'
    home = tmp_path / 'home'
    shutil.copytree(base_env_template.source, source)
    shutil.copytree(base_env_template.home, home)
    cloned = object.__new__(Env)
    cloned.home = home
    cloned.source = source
    cloned.base = base_env_template.base
    return cloned


@pytest.fixture(scope='module')
def filtered_source_template(tmp_path_factory, base_env_template):
    root = tmp_path_factory.mktemp('cloud-pkg-filtered')
    source = root / 'source'
    shutil.copytree(base_env_template.source, source)
    for name, data in FILTERED_CONTENTS.items():
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    (source / '.gitattributes').write_text('* filter=fx\n')
    git(source, 'add', '.')
    git(source, 'commit', '-qm', 'filtered content')
    head = git(source, 'rev-parse', 'HEAD')
    return SimpleNamespace(source=source, base=base_env_template.base, head=head)


@pytest.fixture(scope='module')
def lfs_source_template(tmp_path_factory, base_env_template):
    root = tmp_path_factory.mktemp('cloud-pkg-lfs')
    source = root / 'source'
    shutil.copytree(base_env_template.source, source)
    config = root / 'host.gitconfig'
    config.write_text(LFS_CONFIG)
    clean_env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    clean_env.update(HOME=str(root), GIT_CONFIG_GLOBAL=str(config), GIT_CONFIG_NOSYSTEM='1')

    def lfs_git(*args):
        return subprocess.run(['git', '-C', str(source), *args], env=clean_env,
                              check=True, capture_output=True, text=True).stdout.strip()

    lfs_git('lfs', 'version')
    lfs_git('config', 'lfs.url', 'http://127.0.0.1:9/never')
    entity = source / LFS_TRACKED
    entity.parent.mkdir(parents=True)
    entity.write_bytes(LFS_DATA)
    (source / '.gitattributes').write_text('*.jsonl filter=lfs diff=lfs merge=lfs -text\n')
    lfs_git('add', '.')
    lfs_git('commit', '-qm', 'real LFS entity')
    head = lfs_git('rev-parse', 'HEAD')
    pointer = lfs_git('show', f'{head}:{LFS_TRACKED}')
    assert pointer.startswith('version https://git-lfs.github.com/spec/v1\n')
    assert entity.read_bytes() == LFS_DATA
    assert lfs_git('status', '--porcelain') == ''
    return SimpleNamespace(source=source, head=head, pointer=pointer)


@pytest.mark.parametrize('scope', ['local', 'global', 'system', 'environment'])
@pytest.mark.parametrize('exporter', ['repository', 'context'])
def test_frozen_exports_do_not_execute_host_filters(
    filtered_source_template, tmp_path, monkeypatch, scope, exporter,
):
    source = tmp_path / 'source'
    shutil.copytree(filtered_source_template.source, source)
    head = filtered_source_template.head
    base = filtered_source_template.base
    marker = tmp_path / 'filter-executed'
    command = f'printf invoked >> {shlex.quote(str(marker))}; tr a-z A-Z'
    monkeypatch.setenv('GIT_CONFIG_GLOBAL', str(tmp_path / 'global.config'))
    monkeypatch.setenv('GIT_CONFIG_SYSTEM', str(tmp_path / 'system.config'))
    monkeypatch.delenv('GIT_CONFIG_NOSYSTEM', raising=False)
    if scope == 'environment':
        monkeypatch.setenv('GIT_CONFIG_COUNT', '1')
        monkeypatch.setenv('GIT_CONFIG_KEY_0', 'filter.fx.smudge')
        monkeypatch.setenv('GIT_CONFIG_VALUE_0', command)
    else:
        git(source, 'config', '--' + scope, 'filter.fx.smudge', command)
    destination = tmp_path / 'export'
    if exporter == 'repository':
        export_repository(source, head, destination)
        snapshot = destination
    else:
        build_project_context(source, head, destination, tmp_path / 'pstack', tmp_path / 'models')
        snapshot = destination / 'repo'
    assert not marker.exists(), 'frozen export executed a host filter'
    for name in FILTERED_CONTENTS if exporter == 'repository' else ('AGENTS.md', FILTERED_SKILL):
        assert (snapshot / name).read_bytes() == FILTERED_CONTENTS[name]
    if exporter == 'repository':
        assert vm_git(destination, 'rev-parse', 'HEAD').decode().strip() == head
        assert vm_git(destination, 'status', '--porcelain') == b''
        assert vm_git(destination, 'show', 'HEAD:filtered') == FILTERED_CONTENTS['filtered']
        assert vm_git(destination, 'cat-file', '-t', base) == b'commit\n'
        assert vm_git(destination, 'show', f'{base}:README') == b'x\n'
        assert 'filter' not in (destination / '.git/config').read_text()
        (destination / 'filtered').write_bytes(b'changed\n')
        assert vm_git(destination, 'status', '--porcelain') == b' M filtered\n'
    else:
        assert (destination / 'project-skills/project/SKILL.md').read_bytes() == FILTERED_CONTENTS[FILTERED_SKILL]


def test_frozen_lfs_pointer_does_not_require_host_lfs_object(env, tmp_path):
    pointer = b'version https://git-lfs.github.com/spec/v1\noid sha256:' + b'a' * 64 + b'\nsize 125000000\n'
    (env.source / 'relations.jsonl').write_bytes(pointer)
    (env.source / '.gitattributes').write_text('*.jsonl filter=lfs diff=lfs merge=lfs -text\n')
    git(env.source, 'add', '.')
    git(env.source, 'commit', '-qm', 'lfs pointer without local payload')
    head = git(env.source, 'rev-parse', 'HEAD')
    marker = tmp_path / 'lfs-started'
    git(env.source, 'config', 'filter.lfs.process', f'touch {shlex.quote(str(marker))}; exit 1')
    git(env.source, 'config', 'filter.lfs.required', 'true')
    destination = tmp_path / 'export'
    export_repository(env.source, head, destination)
    assert not marker.exists()
    assert (destination / 'relations.jsonl').read_bytes() == pointer
    assert vm_git(destination, 'show', 'HEAD:relations.jsonl') == pointer
    assert vm_git(destination, 'status', '--porcelain') == b''


def test_export_linked_worktree_uses_shared_objects_not_local_attributes(env, tmp_path, monkeypatch):
    source = tmp_path / '源 repo'
    env.source.rename(source)
    worktree = tmp_path / 'linked worktree'
    git(source, 'worktree', 'add', '--detach', str(worktree), env.base)
    (source / '.git/info/attributes').write_text('README export-ignore\n')
    monkeypatch.setenv('GIT_DIR', str(tmp_path / 'unrelated.git'))
    monkeypatch.setenv('GIT_WORK_TREE', str(tmp_path / 'unrelated'))
    destination = tmp_path / 'export'
    export_repository(worktree, env.base, destination)
    assert (destination / 'README').read_bytes() == b'x\n'
    assert vm_git(destination, 'rev-parse', 'HEAD').decode().strip() == env.base
    assert vm_git(destination, 'status', '--porcelain') == b''
    assert not (destination / '.git/objects/info/alternates').exists()


@pytest.mark.parametrize('dirty', [False, True])
def test_host_directory_check_uses_lfs_clean_filter_after_stat_invalidation(
    lfs_source_template, tmp_path, monkeypatch, dirty,
):
    for key in tuple(os.environ):
        if key.startswith('GIT_'):
            monkeypatch.delenv(key)
    config = tmp_path / 'host.gitconfig'
    config.write_text(LFS_CONFIG)
    monkeypatch.setenv('HOME', str(tmp_path))
    monkeypatch.setenv('GIT_CONFIG_GLOBAL', str(config))
    monkeypatch.setenv('GIT_CONFIG_NOSYSTEM', '1')
    source = tmp_path / 'source'
    shutil.copytree(lfs_source_template.source, source)
    head = lfs_source_template.head
    entity = source / LFS_TRACKED
    assert lfs_source_template.pointer.startswith('version https://git-lfs.github.com/spec/v1\n')
    assert entity.read_bytes() == LFS_DATA
    if dirty:
        entity.write_bytes(LFS_DATA.replace(b'"b"', b'"c"'))
    before = entity.stat()
    os.utime(entity, ns=(before.st_atime_ns, before.st_mtime_ns + 2_000_000_000))
    assert entity.stat().st_mtime_ns != before.st_mtime_ns
    assert _at_base(source, head, '.chanlun/block-topology') is (not dirty)
    expected = f'M {LFS_TRACKED}' if dirty else ''
    assert git(source, 'status', '--porcelain') == expected
