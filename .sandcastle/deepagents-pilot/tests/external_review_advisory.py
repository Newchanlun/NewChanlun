"""旁听进程替身入口：用测试的状态目录、快照目录、对象来源和 worker 替身运行真实的 run_advisory。
argv：<配置 JSON> advisory --run <运行键>（后三项与生产入口相同）。"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE.parent.parent / "approval-signing")]

from pilot1742 import external_review as module  # noqa: E402

config = json.loads(sys.argv[1])
assert sys.argv[2:4] == ["advisory", "--run"], sys.argv
lane = module.ExternalReview(None, state_root=Path(config["state_root"]), checkout_root=Path(config["checkout_root"]),
                             source=Path(config["source"]), launcher=config["launcher"], poll_seconds=0.01)
lane.advisory_timeout = config.get("timeout", lane.advisory_timeout)
lane.advisory_term_grace = config.get("grace", lane.advisory_term_grace)
print(json.dumps(lane.run_advisory(sys.argv[4]), ensure_ascii=False))
