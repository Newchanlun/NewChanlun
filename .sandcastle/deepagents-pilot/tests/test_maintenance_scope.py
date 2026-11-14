"""正常调度入口和恢复对账必须使用同一完整资源清点，不调用模型。"""
import json
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import pytest

from pilot1742 import maintenance_recovery as evidence
from pilot1742 import review_sweep
from pilot1742.claims import ClaimStore
from pilot1742.external_review import MODELS, ExternalReview, ReviewTarget
from pilot1742.maintenance import Owner
from pilot1742.queue import QueueIntake, worker_activity


def closed_owners(root):
    owners = {lane: Owner(lane, root) for lane in ('decision', 'wayfinder', 'executor', 'review')}
    owners['executor'].gate.request()
    for owner in owners.values():
        owner.poll()
    return owners


@pytest.mark.parametrize('case', ['orphan', 'nonqueued', 'late_orphan', 'read_failure', 'empty'])
def test_queue_full_scope_without_expanding_dispatch(tmp_path, monkeypatch, case):
    state = tmp_path / 'state'
    runs = state / 'runs'
    runs.mkdir(parents=True)
    orphan = runs / 't4242-1'
    if case in ('orphan', 'nonqueued'):
        (orphan / 'workers').mkdir(parents=True)
        if case == 'nonqueued':
            # 非 queued unit 不参与派票；资源目录仍须清点。
            (state / 'units').mkdir()
            (state / 'units' / 't4242-1.json').write_text('{}')
            monkeypatch.setattr('pilot1742.executor.load_unit', lambda *args:
                                (SimpleNamespace(admission=object()), None))
        assert 'effect_unknown' in worker_activity({orphan}, tmp_path / 'source')
    if case == 'read_failure':
        original = Path.iterdir
        def unreadable(path):
            if path == runs:
                raise PermissionError('isolated read failure')
            return original(path)
        monkeypatch.setattr(Path, 'iterdir', unreadable)
    calls = []
    check = evidence.executor_scope_idle
    def scope_check(scope):
        calls.append(scope)
        if case == 'late_orphan' and len(calls) == 2:
            (orphan / 'workers').mkdir(parents=True)
        return check(scope)
    monkeypatch.setattr(evidence, 'executor_scope_idle', scope_check)
    owners = closed_owners(tmp_path / 'gate')
    owner = owners['executor']
    intake = QueueIntake(state, SimpleNamespace(queue=lambda _: []), ClaimStore(tmp_path / 'claims'),
                        SimpleNamespace(load=lambda: None), tmp_path / 'source', owner)
    intake.once(lambda _: pytest.fail('must not expand dispatch beyond queued work'))
    assert len(calls) == 2
    assert owner.gate.status([])['state'] == ('drained' if case == 'empty' else 'unknown')
    assert check(dict(state_root=str(state), source_repo=str(tmp_path / 'source'))) == (case == 'empty')


@pytest.mark.parametrize('entry', ['serve', 'standalone'])
@pytest.mark.parametrize('case', ['wrong_launch', 'wrong_head', 'missing_launch', 'missing_target',
                                  'wrong_target_path', 'orphan_worker', 'read_failure', 'valid'])
def test_review_entry_uses_strict_scope(tmp_path, monkeypatch, entry, case):
    target = ReviewTarget(1, 1, 1, 'main', 'a'*40, 1, 'feature', 'b'*40, 'a'*40,
                          'test-run', 1, 'test-policy', 'c'*40, 1)
    state = tmp_path / 'reviews'
    folder = state / 'runs' / target.key
    worker = folder / MODELS[0]
    worker.mkdir(parents=True)
    (folder / 'target.json').write_text(json.dumps(asdict(target)))
    fields = {key: getattr(target, key) for key in
              ('run_id', 'head_sha', 'base_sha', 'merge_base_sha', 'controller_code_head')}
    fields.update(model=MODELS[0], launch_id='current-launch')
    (worker / 'launch.json').write_text(json.dumps(fields))
    receipt = dict(fields, container_closed=True)
    if case == 'wrong_launch': receipt['launch_id'] = 'different-launch'
    if case == 'wrong_head': receipt['head_sha'] = 'd'*40
    (worker / 'receipt.json').write_text(json.dumps(receipt))
    if case == 'missing_launch': (worker / 'launch.json').unlink()
    if case == 'missing_target': (folder / 'target.json').unlink()
    if case == 'wrong_target_path': folder.rename(folder.with_name('orphan'))
    if case == 'orphan_worker':
        other = folder / 'retired-reviewer'
        other.mkdir()
        (other / 'process.json').write_text('{}')
    if case == 'read_failure':
        original = Path.iterdir
        def unreadable(path):
            if path == state / 'runs': raise PermissionError('isolated read failure')
            return original(path)
        monkeypatch.setattr(Path, 'iterdir', unreadable)
    lane = ExternalReview(None, state_root=state, source=tmp_path / 'source')
    owners = closed_owners(tmp_path / 'gate')
    sweep = SimpleNamespace(folder=tmp_path / 'sweep', lane=lane, reap_launches=lambda: None,
                            tick=lambda: pytest.fail('closed sweep must not dispatch'))
    if entry == 'serve':
        assert review_sweep.ServeRound(sweep, maintenance=owners['review'])() is None
    else:
        monkeypatch.setattr(review_sweep, 'Owner', lambda _: owners['review'])
        monkeypatch.setattr(review_sweep, 'GhCli', lambda: None)
        monkeypatch.setattr(review_sweep, 'ExternalReview', lambda _: lane)
        monkeypatch.setattr(review_sweep, 'Sweep', lambda *args, **kwargs: sweep)
        assert review_sweep.main(['--private-key', str(tmp_path / 'unused')]) == 0
    assert evidence.scope_idle(dict(kind='review', state_root=str(state),
                                    source_repo=str(tmp_path / 'source'))) == (case == 'valid')
    assert owners['review'].gate.status([])['state'] == ('drained' if case == 'valid' else 'unknown')


def test_serve_round_maintenance_error_keeps_exception_isolation(tmp_path, capsys):
    owner = Owner('review', tmp_path / 'gate')
    def failed(*args): raise OSError('isolated failure')
    owner.coverage = failed
    sweep = SimpleNamespace(folder=tmp_path / 'sweep', tick=lambda: pytest.fail('must not dispatch'))
    assert review_sweep.ServeRound(sweep, maintenance=owner)() is None
    assert 'maintenance unavailable: OSError' in capsys.readouterr().out


def test_run_review_observes_closure_during_already_admitted_work(tmp_path, monkeypatch):
    import threading

    from pilot1742.maintenance import Gate
    owners = {lane: Owner(lane, tmp_path / 'gate') for lane in ('decision', 'wayfinder', 'executor', 'review')}
    parent = owners['review']
    job = parent.reserve('pr:1:' + 'a'*40 + ':1')
    acknowledged = threading.Event()
    original_poll = Gate.poll
    def poll(gate, owner):
        closed = original_poll(gate, owner)
        if closed and owner not in {o.id for o in owners.values()}:
            acknowledged.set()
        return closed
    monkeypatch.setattr(Gate, 'poll', poll)
    def run(args, github, natural, maintenance):
        parent.gate.request()
        for owner in owners.values(): owner.poll()
        assert acknowledged.wait(3), 'detached child did not acknowledge closure'
        assert parent.gate.status([])['state'] == 'draining'
        return 0
    monkeypatch.setattr(review_sweep, '_run_review', run)
    assert review_sweep.run_review(['--pr', '1', '--attempt', '1', '--expect-head', 'a'*40,
        '--private-key', str(tmp_path / 'unused'), '--maintenance-root', str(parent.gate.root),
        '--maintenance-reservation', job]) == 0


@pytest.mark.parametrize('failure', ['factory', 'stop'])
def test_executor_cleanup_covers_initialization_and_stop_errors(tmp_path, monkeypatch, capsys, failure):
    from pilot1742 import executor, maintenance, queue
    events = []
    def stop():
        events.append('stop')
        if failure == 'stop': raise OSError('isolated stop failure')
    owner = SimpleNamespace(coverage=lambda _: None, stop=stop, poll=lambda: False)
    monkeypatch.setattr(maintenance, 'Owner', lambda _: owner)
    def factory(*args, **kwargs):
        if failure == 'factory': raise OSError('isolated factory failure')
        return SimpleNamespace(__call__=lambda: None, close=lambda: events.append('sweep-close'))
    class Sweep:
        def __call__(self): pass
        def close(self): events.append('sweep-close')
    monkeypatch.setattr(review_sweep, 'serve_round', lambda *a, **k: factory() if failure == 'factory' else Sweep())
    monkeypatch.setattr(executor, '_client', lambda _: SimpleNamespace(close=lambda: events.append('client-close')))
    monkeypatch.setattr(executor, 'RepoGateway', lambda c: c)
    monkeypatch.setattr(queue, 'QueueIntake', lambda *a: SimpleNamespace(once=lambda child: {}))
    args = SimpleNamespace(review_sweep=True, review_sweep_auto_merge=False, review_sweep_max_running=2,
                           state_root=tmp_path, once=True)
    assert executor._serve(args, None, SimpleNamespace(load=lambda: None), tmp_path, tmp_path / 'unused') == 0
    assert events == (['stop', 'client-close'] if failure == 'factory' else ['stop', 'sweep-close', 'client-close'])
    assert ('initialization unavailable' if failure == 'factory' else 'stop unavailable') in capsys.readouterr().err
