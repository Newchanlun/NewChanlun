import os, pathlib, platform, subprocess, sys, tempfile

root = pathlib.Path(__file__).resolve().parent
with tempfile.TemporaryDirectory(prefix="p2079-r5-", dir="/var/tmp") as work:
    fs = subprocess.check_output(["findmnt", "-n", "-T", work, "-o", "FSTYPE"], text=True).strip()
    print("workdir=" + work, flush=True)
    subprocess.run(["findmnt", "-n", "-T", work, "-o", "TARGET,SOURCE,FSTYPE"], check=True)
    print(f"filesystem={fs} uid={os.geteuid()} python={platform.python_version()}", flush=True)
    if fs != "ext4" or platform.machine() != "x86_64":
        sys.exit("requires Linux x86_64 ext4")
    for name in ["original_probe.py", "probe2.py"]:
        print("=== " + name + " ===", flush=True)
        subprocess.run([sys.executable, "-I", "-u", str(root / name), work], check=True)
