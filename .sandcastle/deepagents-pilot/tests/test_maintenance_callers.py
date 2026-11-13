"""99030：真实子入口和各业务消费者的账本收尾故障。"""
import json
import os
import sqlite3
import subprocess
import sys
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from pilot1742 import executor, external_review, maintenance, review_sweep


def fail(*args, **kwargs):
    raise sqlite3.OperationalError('injected ledger failure')


def test_serve_child_busy_is_real_process_exit75(tmp_path):
    owner = maintenance.Owner('executor')
    job = owner.gate.admit_executor(owner.id, 'same-run', 1742, tmp_path, executor.SOURCE_REPO)
    owner.gate.start_bound(job, 'same-run', tmp_path)
    result = subprocess.run([sys.executable, '-m', 'pilot1742.executor', '--state-root', str(tmp_path),
                             'run', '--run-id', 'same-run', '--maintenance-root', str(owner.gate.root),
                             '--maintenance-job', job], capture_output=True, text=True,
                            env={**os.environ, 'PYTHONPATH': str(executor.Path(executor.__file__).parents[1])})
    assert result.returncode == 75, result.stderr
    assert owner.gate.status([])['inflight'][0]['id'] == job


@pytest.mark.parametrize('bound', [False, True])
@pytest.mark.parametrize('outcome', [23, 'business-error'])
@pytest.mark.parametrize('step', ['returned', 'complete_bound', 'settle_current_executor', 'stop'])
def test_executor_cleanup_preserves_outcome(tmp_path, monkeypatch, bound, outcome, step):
    unit = SimpleNamespace(run_id='same-run', ticket=1742)
    monkeypatch.setattr(executor, 'load_unit', lambda *a: (unit, None))
    def main(argv, *, on_execution):
        on_execution()
        if outcome == 'business-error':
            raise RuntimeError('business-error')
        return outcome
    monkeypatch.setattr(executor, '_main', main)
    monkeypatch.setattr(maintenance.Gate, step, fail)
    args = ['--state-root', str(tmp_path), 'run', '--run-id', unit.run_id]
    if bound:
        owner = maintenance.Owner('executor')
        job = owner.gate.admit_executor(owner.id, unit.run_id, unit.ticket, tmp_path, executor.SOURCE_REPO)
        args += ['--maintenance-root', str(owner.gate.root), '--maintenance-job', job]
    if outcome == 'business-error':
        with pytest.raises(RuntimeError, match='business-error'):
            executor.main(args)
    else:
        assert executor.main(args) == outcome
    assert maintenance.Gate(maintenance.ROOT).status([])['inflight']


@pytest.mark.parametrize('outcome', [23, 'business-error'])
@pytest.mark.parametrize('step', ['returned_current', 'finish_review', 'stop'])
def test_review_cleanup_preserves_outcome(tmp_path, monkeypatch, outcome, step):
    monkeypatch.setattr(maintenance.Gate, step, fail)
    def run(*a, **kw):
        if outcome == 'business-error':
            raise RuntimeError('business-error')
        return outcome
    monkeypatch.setattr(external_review, '_run_main', run)
    monkeypatch.setattr(review_sweep, '_run_review',
                        lambda args, github, on_natural, maintenance: external_review._main([], maintenance=maintenance))
    args = ['--pr', '1', '--attempt', '1', '--expect-head', 'a' * 40, '--private-key', str(tmp_path / 'unused')]
    if outcome == 'business-error':
        with pytest.raises(RuntimeError, match='business-error'):
            review_sweep.run_review(args)
    else:
        assert review_sweep.run_review(args) == outcome


def test_review_complete_failure_keeps_result_json(tmp_path, monkeypatch, capsys):
    target = dict(pr=1, attempt=1, run_id='test')
    result = {'target': target, 'verdict': 'BLOCK'}
    owner = SimpleNamespace(gate=SimpleNamespace(complete_bound=fail))
    lane = SimpleNamespace(review_pr=lambda *a: result, maintenance_idle=lambda *a: True,
                           maintenance_witness='w')
    monkeypatch.setattr(external_review, 'load_identity', lambda *a: None)
    monkeypatch.setattr(external_review, 'GitHubAppClient', lambda *a, **kw: nullcontext(SimpleNamespace(verify=lambda: None)))
    monkeypatch.setattr(external_review, 'RepoGateway', lambda *a: None)
    monkeypatch.setattr(external_review, 'ExternalReview', lambda *a: lane)
    monkeypatch.setattr(external_review, 'ReviewTarget', lambda **kw: kw)
    natural = []
    code = external_review._run_main(['review-pr', '--pr', '1', '--private-key', str(tmp_path / 'unused')],
                                     maintenance=(owner, 'j'), on_natural=lambda: natural.append(True))
    assert code == 1
    assert json.loads(capsys.readouterr().out) == result
    assert natural == []


def test_serve_preflight_return_has_owner_before_checks(tmp_path, monkeypatch):
    gate = maintenance.Gate(maintenance.ROOT)
    def preflight(argv, **kwargs):
        report = gate.status([('executor', os.getpid(), maintenance.identity(os.getpid()))])
        assert report['uncovered'] == []
        assert len(report['owners']) == 1
        return 2
    monkeypatch.setattr(executor, '_main', preflight)
    assert executor.main(['serve', '--once', '--private-key', str(tmp_path / 'unused')]) == 2
    assert gate.status([])['owners'][0]['stopped'] == 1


def test_serve_child_preflight_receipt_failure_preserves_exit(tmp_path, monkeypatch):
    owner = maintenance.Owner('executor')
    job = owner.gate.admit_executor(owner.id, 'preflight', 1742, tmp_path, executor.SOURCE_REPO)
    monkeypatch.setattr(executor, '_main', lambda *a, **kw: 2)
    monkeypatch.setattr(maintenance.Gate, 'returned_preflight', fail)
    assert executor.main(['--state-root', str(tmp_path), '--run-id', 'preflight',
                          '--maintenance-job', job, '--maintenance-root', str(owner.gate.root)]) == 2
    with owner.gate.tx() as db:
        assert db.execute('SELECT count(*) FROM returns').fetchone()[0] == 0
        assert db.execute('SELECT count(*) FROM preflight_returns').fetchone()[0] == 0
    assert owner.gate.status([])['inflight']
