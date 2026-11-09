"""独审监督进程替身。只生成测试协议，不发模型请求。"""
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

if sys.argv[1:] == ["--admission-only"]:  # 部署准入替身：controller=cwd 的 HEAD；.git/fake-admission 可注入失败或换镜像
    head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    override = Path(".git/fake-admission").read_text().strip() if Path(".git/fake-admission").exists() else ""
    if override == "fail":
        sys.exit(2)
    print(json.dumps({"controller_code_head": head, "image_id": override or "sha256:" + "1" * 64}))
    sys.exit(0)
folder = Path(sys.argv[sys.argv.index("--output-dir") + 1])
launch = json.loads((folder / "launch.json").read_text())
runs = next(p for p in folder.parents if p.name == "runs")  # 旁听 worker 在 runs/<键>/advisory/<模型>/
with open(runs / "launches", "a") as log:
    log.write(launch["model"] + "\n")
per_model = runs / f"fake-mode-{launch['model']}"  # 按模型覆盖，造混合结论
mode_file = per_model if per_model.exists() else runs / "fake-mode"
mode, _, flag = (mode_file.read_text().strip() if mode_file.exists() else "PASS").partition(":")
if mode == "CRASH":  # 监督进程不写回执就退出
    sys.exit(3)
if mode.startswith("HANG"):  # 卡住前已登记容器（与真实 worker 一样，supervisor.json 记 container_id）
    (folder / "supervisor.json").write_text(json.dumps({"container_id": "c" * 64}))
if mode == "HANGTERM":  # 卡住且忽略 SIGTERM：取消路径失效，快照只能留给回收
    import signal
    import time
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    time.sleep(300)
    sys.exit(4)
if mode == "HANG":  # 监督进程卡住不出回执（SIGTERM 默认即结束）
    import time
    time.sleep(300)
    sys.exit(4)
session = str(uuid.uuid4())
diff = ["diff", "--no-ext-diff", "--no-textconv", launch["merge_base_sha"], launch["head_sha"]]
read = f"/bin/bash -lc 'git {' '.join(diff)}'"
patch = subprocess.run(["git", "-C", launch["checkout"], *diff], capture_output=True, text=True, check=True).stdout
tool = [] if flag == "notool" else [  # 「BLOCK:notool」等：零工具调用的审查员（#1968）
    {"type": "item.completed", "item": {"type": "command_execution", "command": read, "aggregated_output": patch,
                                        "status": "completed", "exit_code": 0}}]
output = {"status": "blocked" if mode == "BLOCK" else "completed", "summary": f"VERDICT: {mode}",
          "findings": [], "validation": ["测试替身"]}
fence = (runs / "fake-fence").read_text().strip() if (runs / "fake-fence").exists() else ""
text = json.dumps(output)
if fence == "nonstring":  # agent_message.text 不是字符串（结构化内容）
    text = output  # type: ignore[assignment]
elif fence:  # whole：整段一个围栏；prose：围栏前有说明文字
    text = ("结论如下\n" if fence == "prose" else "") + "```json\n" + text + "\n```"
events = [{"type": "thread.started", "thread_id": session}, *tool,
          {"type": "item.completed", "item": {"type": "agent_message", "text": text}},
          {"type": "turn.completed"}]
(folder / "events.jsonl").write_text("\n".join(json.dumps(e) for e in events) + "\n")
(folder / "session.jsonl").write_text(json.dumps({"type": "session_meta", "payload": {"id": session}}) + "\n")
record = {**launch, "status": "completed", "sandbox": "docker-read-only", "exit_code": 0, "container_closed": True,
          "image_id": "sha256:" + "1" * 64, "container_id": "a" * 64,
          "filesystem": {"source_write": "EROFS", "git_write": "EROFS", "host_read": "ENOENT", "state_write": "ENOENT"},
          "session_id": session, "turn_completed": True, "result": output,
          "before": {"head": launch["head_sha"], "branch": "HEAD", "status": ""},
          "after": {"head": launch["head_sha"], "branch": "HEAD", "status": ""}}
(folder / "receipt.tmp").write_text(json.dumps(record))
os.replace(folder / "receipt.tmp", folder / "receipt.json")
