"""#1742/#1911：角色来源、冻结与无 run unit 的恢复，全部离线。"""
from pathlib import Path
from types import SimpleNamespace

import pytest
from conftest import MODELS
from v2env import V2_TASK, V2Env

from pilot1742 import executor, queue
from pilot1742 import run as run_module
from pilot1742.domain import parse_model
from pilot1742.run import PilotRun, plan_roles, read_model_rules


def test_comments_preserve_single_strict_parser():
    commented = '\n'.join(line + ' # 中文注释：说明, 不属于模型' for line in MODELS.splitlines())
    assert plan_roles(commented) == plan_roles(MODELS)
    with pytest.raises(ValueError, match='白名单'):
        plan_roles(commented.replace('gpt-6.1-sol', 'unknown-model'))
    with pytest.raises(ValueError, match='同一家族'):
        plan_roles(MODELS.replace('gpt-6.1-sol', 'claude-opus-5-5'))


def test_default_and_explicit_source(tmp_path, monkeypatch):
    default = tmp_path / 'global.md'
    default.write_text(MODELS)
    monkeypatch.setattr(run_module, 'PSTACK_MODELS', default)
    assert read_model_rules() == MODELS
    project = tmp_path / 'project.md'
    project.write_text(MODELS + '# project\n')
    assert read_model_rules(project) == project.read_text()
    with pytest.raises(FileNotFoundError):
        read_model_rules(tmp_path / 'missing.md')
    with pytest.raises(IsADirectoryError):
        read_model_rules(tmp_path)
    project.write_bytes(b'\xff')
    with pytest.raises(UnicodeDecodeError):
        read_model_rules(project)


@pytest.mark.parametrize('models', [MODELS, (Path(__file__).resolve().parents[1] / 'pstack-models.md').read_text()])
def test_missing_or_invalid_source_leaves_same_unit_recoverable(tmp_path, models):
    v2 = V2Env(tmp_path)
    unit = v2.register()
    source = tmp_path / 'project.md'
    before = (v2.home / 'units' / f'{unit.run_id}.json').read_bytes()

    def start():
        return executor.open_v2_run(v2.home, unit, V2_TASK, v2.executor(unit),
                                    model_rules=source, source_repo=v2.source)

    with pytest.raises(FileNotFoundError):
        start()
    source.write_text('feature, refactoring: unknown\n')
    with pytest.raises(ValueError):
        start()
    assert not (PilotRun.run_dir(v2.home, unit.run_id) / 'run.json').exists()
    assert not (v2.claims_root / f'{unit.ticket}.json').exists()
    source.write_text(models)
    pilot = start()
    frozen = (pilot.dir / 'run.json').read_bytes()
    assert pilot.spec.model_rules_text == models
    pilot.release()
    source.unlink()
    resumed = start()
    assert (resumed.dir / 'run.json').read_bytes() == frozen
    assert (v2.home / 'units' / f'{unit.run_id}.json').read_bytes() == before
    resumed.release()


@pytest.mark.parametrize('explicit', [False, True])
def test_serve_forwards_source_without_changing_environment(tmp_path, monkeypatch, explicit):
    source = tmp_path / 'project.md'
    args = SimpleNamespace(state_root=tmp_path, drain_root=tmp_path, workers_log=tmp_path / 'workers',
                           private_key=tmp_path / 'unused', model_rules=source if explicit else None,
                           review_sweep=False, once=True)
    commands = []
    class Intake:
        def __init__(self, *args):
            pass

        def once(self, child):
            return child(SimpleNamespace(run_id='t1911-1'))

    monkeypatch.setattr(queue, 'QueueIntake', Intake)
    monkeypatch.setattr(executor, 'RepoGateway', lambda client: client)
    monkeypatch.setattr(executor, '_client', lambda _: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(executor.subprocess, 'run',
                        lambda command, **kw: commands.append((command, kw)) or SimpleNamespace(returncode=0))
    monkeypatch.setenv('DOCKER_CONTEXT', 'fixture-context')
    assert executor._serve(args, None, SimpleNamespace(load=lambda: None), tmp_path) == 0
    command, kwargs = commands[0]
    assert ('--model-rules' in command) == explicit
    if explicit:
        assert command[-2:] == ['--model-rules', str(source.resolve())]
    assert kwargs == {'check': False}  # 子进程继承环境，包括 DOCKER_CONTEXT


@pytest.mark.parametrize('slug', ['kimi-k3.1-pro-extra', 'kimi-*', 'fable', 'claude-sonnet-4-6'])
def test_narrow_admission_rejects_other_new_models(slug):
    with pytest.raises(ValueError, match='白名单'):
        parse_model(slug)


def test_v1_cli_source_and_existing_run_ignore_new_source(env, tmp_path, monkeypatch):
    from pilot1742 import cli

    task = tmp_path / 'task.md'
    task.write_text('---\ntitle: fixture\nallowed_prefixes: [demo/]\n---\nfixture\n')
    source = tmp_path / 'project.md'
    source.write_text(MODELS + '# 显式项目来源\n')
    monkeypatch.setattr(cli, 'SOURCE_REPO', env.source)
    monkeypatch.setattr(PilotRun, 'ensure_checkouts', lambda self: None)
    seen = []

    def drive(run, **kwargs):
        seen.append(run.spec)
        run.release()
        return 0

    monkeypatch.setattr(cli, 'drive', drive)
    args = ['run', '--run-id', 'project', '--home', str(env.home), '--model-rules', str(source)]
    assert cli.main(args + ['--task', str(task)]) == 0
    assert seen[0].model_rules_text == source.read_text()
    source.unlink()
    assert cli.main(args) == 0
    assert seen[0] == seen[1]


def test_local_rules_view_is_frozen_and_does_not_write_run(env, monkeypatch, tmp_path):
    from pilot1742 import agent

    run = env.create()
    source = tmp_path / 'global.md'
    source.write_text('不得使用的新全局表\n')
    monkeypatch.setattr(agent, 'PSTACK_MODELS', source)
    monkeypatch.setattr(agent, 'create_deep_agent', lambda **kwargs: kwargs)
    before = {str(p): p.read_bytes() for p in run.dir.rglob('*') if p.is_file()}
    built = agent.build_agent(run, None, model=object())
    source.unlink()
    result = built['backend'].read(str(source.parent / 'pstack-models.md'))
    assert result.error is None
    assert result.file_data['content'] == run.spec.model_rules_text
    assert {str(p): p.read_bytes() for p in run.dir.rglob('*') if p.is_file()} == before
