"""#1742 私有日志读取器；宿主与容器使用同一解析实现。"""
import json
import os
import signal
import sys
import time
from pathlib import Path


def route_from_log(log_dir: Path, session: str, since: float, wait: float) -> list[tuple[str, str]] | None:
    """v8.0.63 文本日志没有正文帧或可信完成标记，不能用作路由证明。

    保留旧入口与返回合同，但拒绝据此放行。恢复条件见 REVIEW-PREFLIGHT.md
    的“可信证据缺口”；不能用增加正则或等待文件稳定来替代生产者证据。
    """
    return None


def main():
    # 绝对到期时间也约束 daemon 延迟启动的 exec；SIGALRM 覆盖阻塞读取与输出。
    log_dir, session, since, expires, budget, known_json = sys.argv[1:]
    remaining = float(expires) - time.time()
    if not 0 < remaining <= float(budget):
        return 2
    signal.signal(signal.SIGALRM, lambda *_: os._exit(2))
    signal.setitimer(signal.ITIMER_REAL, remaining)
    known = {tuple(route): "@".join(route) for route in json.loads(known_json)}
    attempts = route_from_log(Path(log_dir), session, float(since), remaining)
    print(json.dumps({"session": session, "complete_stable": attempts is not None,
                      "routes": [known.get(route, "other") for route in attempts or []]}), flush=True)
    return 0


if __name__ == "__main__":
    # traceback/路径/日志内容不能越过容器边界。
    try:
        with open(os.devnull, "w") as sink:
            os.dup2(sink.fileno(), 2)
        os._exit(main())
    except BaseException:
        os._exit(2)
