import os
import pathlib
import subprocess
import sys
import tempfile

root = pathlib.Path(__file__).resolve().parent
with tempfile.TemporaryDirectory(prefix="r5-x-", dir="/var/tmp") as work:
    print("=== E/X isolation environment ===", flush=True)
    subprocess.run(["uname", "-srm"], check=True)
    subprocess.run(["findmnt", "-n", "-T", work, "-o", "TARGET,SOURCE,FSTYPE"], check=True)
    fs = subprocess.check_output(["findmnt", "-n", "-T", work, "-o", "FSTYPE"], text=True).strip()
    print(f"workdir={work} uid={os.geteuid()} python={sys.version.split()[0]}", flush=True)
    assert fs == "ext4"
    for name in ("e_economic_session", "x_execution_session"):
        (root / name).chmod(0o700)
    env = {"PATH": os.defpath, "LANG": "C.UTF-8", "PYTHONUNBUFFERED": "1"}
    subprocess.run([sys.executable, "-u", str(root / "x_epoch_probe.py"),
                    str(root / "x_execution_session"), work], check=True, env=env)
