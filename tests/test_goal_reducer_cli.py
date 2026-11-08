"""goal_reducer 命令行入口：读 events.jsonl → reduce_goal 投影。

接替随 #1952 删除的 scripts/ceremony_scan.py::_load_current_goal（及其测试
scripts/tests/test_ceremony_scan_goal.py）：缺文件/全损坏 → None，单行损坏 → stderr
警告并跳过，结果透出 skipped_event_lines；CLI 用退出码区分这三种情况。
"""
import json
import subprocess
import sys
from pathlib import Path

from goal_reducer import current_goal_state, main

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "goal_reducer.py"
GOAL_SET = ('{"event": "GOAL_SET", "goal_id": "g1", "description": "x", '
            '"acceptance": [{"check": "c", "falsifiable": true}], "base_head": "abc", "ts": "t0"}\n')


def _write(tmp_path, text):
    p = tmp_path / "events.jsonl"
    p.write_text(text, encoding="utf-8")
    return p


def test_missing_file_returns_none(tmp_path):
    assert current_goal_state(str(tmp_path / "nope.jsonl"), git_head="abc") is None


def test_valid_events_project_current_goal(tmp_path):
    out = current_goal_state(str(_write(tmp_path, GOAL_SET)), git_head="abc")
    assert out["current_goal"]["goal_id"] == "g1"
    assert out["current_goal"]["base_head_stale"] is False
    assert "skipped_event_lines" not in out


def test_git_head_mismatch_marks_stale(tmp_path):
    out = current_goal_state(str(_write(tmp_path, GOAL_SET)), git_head="other")
    assert out["current_goal"]["base_head_stale"] is True


def test_corrupt_line_skipped_and_reported(tmp_path, capsys):
    out = current_goal_state(str(_write(tmp_path, GOAL_SET + "{ not json }\n")), git_head="abc")
    assert out["current_goal"]["goal_id"] == "g1"
    assert out["skipped_event_lines"] == 1
    assert "损坏" in capsys.readouterr().err


def test_all_corrupt_returns_none(tmp_path):
    assert current_goal_state(str(_write(tmp_path, "{ bad }\nnot json\n")), git_head="abc") is None


def test_main_exit_codes(tmp_path, capsys):
    assert main(["--events", str(_write(tmp_path, GOAL_SET))]) == 0
    assert json.loads(capsys.readouterr().out)["current_goal"]["goal_id"] == "g1"
    assert main(["--events", str(_write(tmp_path, GOAL_SET + "oops\n"))]) == 1
    assert main(["--events", str(tmp_path / "missing.jsonl")]) == 2


def test_script_runs_as_command(tmp_path):
    """`python scripts/goal_reducer.py --events …` 真的打印投影（不是空输出 exit 0）。"""
    proc = subprocess.run([sys.executable, str(SCRIPT), "--events", str(_write(tmp_path, GOAL_SET))],
                          capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["current_goal"]["goal_id"] == "g1"
