"""#2048：宿主相关路径的唯一取值处。缺省值等于 Mac 现役位置，Linux 宿主（Belay）用环境变量覆盖。

- AGENT_STORAGE：存储根，缺省 /Volumes/AgentStorage。
- PILOT1742_WORKERS_LOG：workers.jsonl，缺省 Mac 主仓 .sandcastle/logs/workers.jsonl。
- PSTACK_SKILLS_ROOT：本机 pstack skills 目录（带结尾斜杠），缺省 Mac 上的 codex 安装位置。
- SANDCASTLE_HOST_REPO：旧 sandcastle 宿主仓，缺省 Mac 上的 NewChanlun-sandcastle-host。
- SERVICE_MANAGER：launchctl（缺省）或 systemd。
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

AGENT_STORAGE = Path(os.environ.get("AGENT_STORAGE") or "/Volumes/AgentStorage")
WORKERS_LOG = Path(os.environ.get("PILOT1742_WORKERS_LOG")
                   or "/Users/silencehan/Projects/NewChanlun/.sandcastle/logs/workers.jsonl")
SKILLS_ROOT = os.environ.get("PSTACK_SKILLS_ROOT") or "/Users/silencehan/.codex/pstack-upstream-source/installed/skills/"
LEGACY_HOST_REPO = Path(os.environ.get("SANDCASTLE_HOST_REPO") or "/Users/silencehan/Projects/NewChanlun-sandcastle-host")

ServiceManager = Literal["launchctl", "systemd"]


def service_manager(value: str | None = None) -> ServiceManager:
    raw = (os.environ.get("SERVICE_MANAGER") if value is None else value) or "launchctl"
    if raw == "launchctl":
        return "launchctl"
    if raw == "systemd":
        return "systemd"
    raise ValueError(f"SERVICE_MANAGER 只接受 launchctl 或 systemd，实为 {raw}")


def systemd_unit(label: str) -> str:
    """launchd 标签 com.newchanlun.<名> 对应 systemd 用户单元 newchanlun-<名>.service。"""
    prefix = "com.newchanlun."
    return ("newchanlun-" + label[len(prefix):] if label.startswith(prefix) else label) + ".service"
