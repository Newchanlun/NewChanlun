"""Prepare the frozen-replay counterexample without mutating the source."""
import json
from pathlib import Path
import sys

source, output = map(Path, sys.argv[1:])
data = json.loads(source.read_bytes())
for issue in data["issues"]:
    state = issue["state"]
    if state not in {"open", "closed"}:
        raise ValueError(f"unexpected issue state: {state}")
    issue["state"], issue["state_reason"] = ("closed", "completed") if state == "open" else ("open", None)
with output.open("x", encoding="utf-8") as stream:
    json.dump(data, stream, ensure_ascii=False)
    stream.write("\n")
