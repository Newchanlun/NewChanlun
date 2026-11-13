"""维护恢复的生命周期适配；只读取既有本地证据，不启动/恢复工作。"""
from pathlib import Path


def executor_idle(binding: dict) -> bool:
    from .executor import load_unit
    from .queue import QueueIntake
    from .run import PilotRun
    root = Path(binding['state_root'])
    unit, _ = load_unit(root, binding['run_id'])
    if unit.run_id != binding['run_id'] or f'ticket:{unit.ticket}' != binding['work']:
        return False
    folder = PilotRun.run_dir(root, unit.run_id)
    # 不接受尚未生成 run 的空目录作为已执行证明。
    if not (folder / 'run.json').is_file():
        return False
    intake = QueueIntake(root, None, None, None, Path(binding['source_repo']))
    return intake._worker_activity({folder}) is None


def executor_scope_idle(scope: dict) -> bool:
    from .queue import QueueIntake
    root = Path(scope['state_root'])
    if not root.is_dir():
        return False
    folders = {p for p in (root / 'runs').iterdir() if p.is_dir()} if (root / 'runs').is_dir() else set()
    intake = QueueIntake(root, None, None, None, Path(scope['source_repo']))
    return intake._worker_activity(folders) is None


def review_idle(binding: dict) -> bool:
    import json
    from .external_review import ExternalReview, ReviewTarget
    target = ReviewTarget(**binding['target'])
    lane = ExternalReview(None, state_root=Path(binding['state_root']), source=Path(binding['source_repo']))
    folder = lane.state_root / 'runs' / target.key
    if json.loads((folder / 'target.json').read_text()) != binding['target']:
        return False
    if not lane.maintenance_idle(target):
        return False
    for model in lane._reviewers(folder):
        worker = folder / model
        if not worker.exists():
            continue
        if not (worker / 'launch.json').exists():
            if any(worker.iterdir()):
                return False
            continue
        launch = json.loads((worker / 'launch.json').read_text())
        receipt = json.loads((worker / 'receipt.json').read_text())
        expected = {key: getattr(target, key) for key in
                    ('run_id', 'head_sha', 'base_sha', 'merge_base_sha', 'controller_code_head')}
        expected.update(model=model, launch_id=launch.get('launch_id'))
        if not expected['launch_id'] or any(launch.get(k) != v or receipt.get(k) != v for k, v in expected.items()):
            return False
        if receipt.get('container_closed') is not True:
            return False
    return True


def bound_idle(binding: dict) -> bool:
    if binding['kind'] == 'executor':
        return executor_idle(binding)
    if binding['kind'] == 'review':
        return review_idle(binding)
    return False


def scope_idle(scope: dict) -> bool:
    if scope['kind'] == 'executor':
        return executor_scope_idle(scope)
    if scope['kind'] == 'review':
        import json
        root = Path(scope['state_root'])
        if not root.is_dir():
            return False
        for folder in (root / 'runs').iterdir() if (root / 'runs').is_dir() else []:
            if not folder.is_dir():
                continue
            target = json.loads((folder / 'target.json').read_text())
            if not review_idle(dict(scope, target=target)):
                return False
        return True
    return False
