"""维护恢复的生命周期适配；只读取既有本地证据，不启动/恢复工作。"""
from pathlib import Path


def executor_idle(binding: dict) -> bool:
    from .executor import load_unit
    from .queue import worker_activity
    from .run import PilotRun
    root = Path(binding['state_root'])
    unit, _ = load_unit(root, binding['run_id'])
    if unit.run_id != binding['run_id'] or f'ticket:{unit.ticket}' != binding['work']:
        return False
    folder = PilotRun.run_dir(root, unit.run_id)
    # 不接受尚未生成 run 的空目录作为已执行证明。
    if not (folder / 'run.json').is_file():
        return False
    return worker_activity({folder}, Path(binding['source_repo'])) is None


def executor_preflight_idle(binding: dict) -> bool:
    """仅用于入口明确未进入 run 的返回证明；仍不能放过先前遗留的 worker 状态。"""
    from .executor import load_unit
    from .queue import worker_activity
    from .run import PilotRun
    root = Path(binding['state_root'])
    unit, _ = load_unit(root, binding['run_id'])
    if unit.run_id != binding['run_id'] or f'ticket:{unit.ticket}' != binding['work']:
        return False
    return worker_activity({PilotRun.run_dir(root, unit.run_id)}, Path(binding['source_repo'])) is None


def executor_scope_idle(scope: dict) -> bool:
    from .queue import worker_activity
    try:
        root = Path(scope['state_root'])
        if not root.is_dir():
            return False
        runs = root / 'runs'
        folders = set(runs.iterdir()) if runs.exists() else set()
        if any(not p.is_dir() for p in folders):
            return False
        return worker_activity(folders, Path(scope['source_repo'])) is None
    except (OSError, ValueError, KeyError, TypeError, RuntimeError):
        return False


def review_idle(binding: dict) -> bool:
    from .external_review import ExternalReview, ReviewTarget
    target = ReviewTarget(**binding['target'])
    lane = ExternalReview(None, state_root=Path(binding['state_root']), source=Path(binding['source_repo']))
    return lane.maintenance_idle(target)


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
        from .external_review import ExternalReview
        lane = ExternalReview(None, state_root=Path(scope['state_root']), source=Path(scope['source_repo']))
        return lane.maintenance_idle()
    return False
