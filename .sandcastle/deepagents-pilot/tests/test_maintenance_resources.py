"""历史监督失败的精确资源终态对账，Docker 仅用隔离假实现。"""
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from types import SimpleNamespace

import pytest

from pilot1742 import external_review as module
from pilot1742.external_review import MODELS, ExternalReview, ReviewTarget
from pilot1742.github_app import IdentityError
from pilot1742.maintenance import Owner


@pytest.fixture
def failed_review(tmp_path, monkeypatch):
    target = ReviewTarget(1, 1, 1, 'main', 'a'*40, 1, 'feature', 'b'*40, 'a'*40,
                          '11111111-1111-1111-1111-111111111111', 1, 'test-policy', 'c'*40, 1)
    lane = ExternalReview(None, state_root=tmp_path / 'reviews', source=tmp_path / 'source')
    lane.checkout_root = tmp_path / 'checkouts'
    folder = lane.state_root / 'runs' / target.key
    worker = folder / MODELS[0]
    worker.mkdir(parents=True)
    folder.chmod(0o700)
    (folder / 'target.json').write_text(json.dumps(asdict(target)))
    launch = lane._resource_identity(target, MODELS[0], {'launch_id': '22222222-2222-2222-2222-222222222222'})
    (worker / 'launch.json').write_text(json.dumps(launch))
    (worker / 'process.json').write_text(json.dumps(dict(pid=999999, launch_id=launch['launch_id'])))
    (worker / 'receipt.json').write_text(json.dumps(dict(launch, container_closed=False,
            failure_reason='SupervisorExitedWithoutReceipt', status='failed')))
    monkeypatch.setattr(module, '_ps_rows', lambda: [])
    calls = []
    def docker(args):
        calls.append(args)
        assert args[0] in ('info', 'ps', 'volume') and 'rm' not in args
        return SimpleNamespace(returncode=0, stdout='fixture-daemon' if args[0] == 'info' else '')
    lane.docker = docker
    # 模拟已有 reaper 在实际对象仍存在时记录的绑定来源。
    lane._record_resource_observation(worker, launch, 'fixture-daemon', ['a'*64], [])
    return lane, target, worker, launch, calls


def test_historical_failed_receipt_recovers_scope_without_rewriting_or_resuming(failed_review, tmp_path):
    lane, target, worker, launch, calls = failed_review
    original = (worker / 'receipt.json').read_bytes()
    owners = [Owner(k, tmp_path / 'gate') for k in ('decision', 'wayfinder', 'executor', 'review')]
    gate = owners[0].gate
    generation = gate.request()
    for owner in owners: owner.poll()
    owners[-1].coverage(lane.maintenance_idle())
    assert gate.status([])['state'] == 'unknown'
    args = (target.run_id, MODELS[0], launch['launch_id'])
    assert lane.reconcile_review_resources(*args)['result'] == 'resources_reconciled'
    proof = (worker / 'resource-closure.json').read_bytes()
    assert lane.reconcile_review_resources(*args)['result'] == 'resources_reconciled'
    assert (worker / 'resource-closure.json').read_bytes() == proof
    assert (worker / 'receipt.json').read_bytes() == original
    assert lane.maintenance_idle(target) and lane.maintenance_idle()
    owners[-1].coverage(lane.maintenance_idle())
    assert gate.status([])['state'] == 'drained'
    assert gate.status([])['generation'] == generation
    assert all('rm' not in command for command in calls)
    gate.resume(generation)
    gate.request()
    assert gate.status([])['state'] == 'unknown'  # 旧资源证明不确认新维护代次


@pytest.mark.parametrize('case', ['container', 'volume', 'docker_error', 'daemon_changed', 'live',
                                  'wrong_receipt', 'wrong_process', 'missing_launch', 'missing_origin', 'wrong_origin'])
def test_resource_reconcile_refuses_missing_or_mismatched_evidence(failed_review, monkeypatch, case):
    lane, target, worker, launch, _ = failed_review
    original = lane.docker
    count = 0
    def docker(args):
        nonlocal count
        count += 1
        if case == 'docker_error': return SimpleNamespace(returncode=1, stdout='')
        if case == 'container' and args[0] == 'ps': return SimpleNamespace(returncode=0, stdout='active')
        if case == 'volume' and args[0] == 'volume': return SimpleNamespace(returncode=0, stdout='retained')
        if case == 'daemon_changed' and count == 4: return SimpleNamespace(returncode=0, stdout='other-daemon')
        return original(args)
    lane.docker = docker
    if case == 'live': monkeypatch.setattr(module, 'supervisor_alive', lambda *a: True)
    if case == 'wrong_receipt':
        p = worker / 'receipt.json'
        p.write_text(json.dumps(dict(json.loads(p.read_text()), launch_id='other')))
    if case == 'wrong_process': (worker / 'process.json').write_text('{"pid":999999,"launch_id":"other"}')
    if case == 'missing_launch': (worker / 'launch.json').unlink()
    if case == 'missing_origin': (worker / 'resource-observation.json').unlink()
    if case == 'wrong_origin':
        p = worker / 'resource-observation.json'
        p.write_text(json.dumps(dict(json.loads(p.read_text()), daemon_id='wrong-daemon')))
    with pytest.raises((IdentityError, module.EffectPending, OSError)):
        lane.reconcile_review_resources(target.run_id, MODELS[0], launch['launch_id'])
    assert not (worker / 'resource-closure.json').exists()
    assert not lane.maintenance_idle()


def test_old_closure_cannot_clear_replaced_launch(failed_review):
    lane, target, worker, launch, _ = failed_review
    lane.reconcile_review_resources(target.run_id, MODELS[0], launch['launch_id'])
    for name in ('launch.json', 'receipt.json'):
        p = worker / name
        p.write_text(json.dumps(dict(json.loads(p.read_text()), launch_id='33333333-3333-3333-3333-333333333333')))
    assert not lane.maintenance_idle()


def test_resource_cli_is_local_and_does_not_register_owner(failed_review, monkeypatch, capsys):
    lane, target, worker, launch, _ = failed_review
    monkeypatch.setattr(module, 'ExternalReview', lambda _: lane)
    monkeypatch.setattr(module, 'load_identity', lambda *a: pytest.fail('no credential access'))
    assert module.main(['reconcile-resources', '--run-id', target.run_id, '--model', MODELS[0],
                        '--launch-id', launch['launch_id']]) == 0
    assert json.loads(capsys.readouterr().out)['result'] == 'resources_reconciled'


def test_concurrent_resource_reconcile_preserves_receipt(failed_review):
    lane, target, worker, launch, _ = failed_review
    original = (worker / 'receipt.json').read_bytes()
    def reconcile(_):
        try:
            return lane.reconcile_review_resources(target.run_id, MODELS[0], launch['launch_id'])['result']
        except module.EffectPending:
            return 'busy'
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(reconcile, range(2)))
    assert 'resources_reconciled' in results
    assert set(results) <= {'resources_reconciled', 'busy'}
    assert (worker / 'receipt.json').read_bytes() == original
    assert lane.maintenance_idle()


def test_existing_reaper_records_origin_then_resource_cli_closes_failed_history(failed_review):
    lane, target, worker, launch, _ = failed_review
    (worker / 'resource-observation.json').unlink()
    present = True
    def docker(args):
        nonlocal present
        if args[0] == 'info': return SimpleNamespace(returncode=0, stdout='fixture-daemon')
        if args[0] == 'rm':
            present = False
            return SimpleNamespace(returncode=0, stdout='')
        if args[0] == 'ps':
            out = ('a'*64 + '\t' + launch['launch_id']) if '--format' in args else 'a'*64
            return SimpleNamespace(returncode=0, stdout=out if present else '')
        assert args[:2] == ['volume', 'ls']
        return SimpleNamespace(returncode=0, stdout='')
    lane.docker = docker
    original = (worker / 'receipt.json').read_bytes()
    assert not lane.maintenance_idle()
    lane.reap_review_volumes()
    assert not present
    assert (worker / 'resource-observation.json').exists()
    lane.reconcile_review_resources(target.run_id, MODELS[0], launch['launch_id'])
    assert lane.maintenance_idle()
    assert (worker / 'receipt.json').read_bytes() == original

@pytest.mark.parametrize('retained', ['volume', 'checkout'])
def test_closed_container_does_not_hide_retained_resources(failed_review, retained):
    lane, target, worker, launch, _ = failed_review
    volume = module.REVIEW_VOLUME_PREFIX + launch['launch_id']
    receipt = dict(launch, container_closed=True, volume=volume, volume_removed=retained != 'volume')
    (worker / 'receipt.json').write_text(json.dumps(receipt))
    checkout = lane.checkout_root / target.run_id / MODELS[0]
    if retained == 'checkout':
        checkout.mkdir(parents=True)
    cleanup = dict(state='removed', checkout=str(checkout), volume=volume,
                   volume_state='retained' if retained == 'volume' else 'removed')
    (worker / 'checkout-cleanup.json').write_text(json.dumps(cleanup))
    assert not lane.maintenance_idle(target)
    assert not lane.maintenance_idle()
    if retained == 'checkout':
        checkout.rmdir()
    else:
        cleanup['volume_state'] = 'removed'
        (worker / 'checkout-cleanup.json').write_text(json.dumps(cleanup))
    assert lane.maintenance_idle(target) and lane.maintenance_idle()
    assert json.loads((worker / 'receipt.json').read_text()) == receipt

@pytest.mark.parametrize('damage', ['missing-cleanup', 'wrong-path', 'retained', 'missing-volume-result', 'wrong-volume'])
def test_resource_terminal_evidence_is_bound_and_complete(failed_review, damage):
    lane, target, worker, launch, _ = failed_review
    checkout = lane.checkout_root / target.run_id / MODELS[0]
    volume = module.REVIEW_VOLUME_PREFIX + launch['launch_id']
    receipt = dict(launch, container_closed=True, volume=volume, volume_removed=True)
    cleanup = dict(state='removed', checkout=str(checkout))
    (worker / 'prepare.json').write_text(json.dumps(dict(run_id=target.run_id, checkout=str(checkout))))
    if damage == 'wrong-path': cleanup['checkout'] += '-other'
    if damage == 'retained': cleanup['state'] = 'retained'
    if damage == 'missing-volume-result': del receipt['volume_removed']
    if damage == 'wrong-volume': receipt['volume'] += '-other'
    if damage != 'missing-cleanup':
        (worker / 'checkout-cleanup.json').write_text(json.dumps(cleanup))
    (worker / 'receipt.json').write_text(json.dumps(receipt))
    assert not lane.maintenance_idle(target) and not lane.maintenance_idle()


def test_strict_resource_closure_allows_original_checkout_cleanup(failed_review):
    lane, target, worker, launch, _ = failed_review
    checkout = lane.checkout_root / target.run_id / MODELS[0]
    checkout.mkdir(parents=True)
    (worker / 'prepare.json').write_text(json.dumps(dict(run_id=target.run_id, checkout=str(checkout))))
    receipt = (worker / 'receipt.json').read_bytes()
    assert not lane.cleanup_checkout(target, MODELS[0], worker.parent)
    assert checkout.exists() and not lane.maintenance_idle()
    lane.reconcile_review_resources(target.run_id, MODELS[0], launch['launch_id'])
    assert not lane.maintenance_idle()  # closure 不伪造 checkout removed。
    assert lane.cleanup_checkout(target, MODELS[0], worker.parent)
    assert lane.maintenance_idle()
    assert (worker / 'receipt.json').read_bytes() == receipt
