#!/usr/bin/env python3
"""下载固定公开源、应用补丁，在指定 Docker context 离线验证并导出 Linux 产物。"""
import argparse
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
from pathlib import Path

COMMIT = "6db7d4b839d86c5b24e17bbe73bcd4db18ef1b1a"
ASSETS = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docker-context", required=True)
    parser.add_argument("--output", required=True, type=Path, help="新的产物目录；不得覆盖已有目录")
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        parser.error("output 必须是新目录")
    with tempfile.TemporaryDirectory(prefix="cliproxy-preflight-build-") as temp:
        root = Path(temp)
        source = root / "source"
        archive = root / "source.tar.gz"
        with urllib.request.urlopen(f"https://codeload.github.com/router-for-me/CLIProxyAPI/tar.gz/{COMMIT}", timeout=60) as response:
            with archive.open("wb") as destination:
                shutil.copyfileobj(response, destination)
        with tarfile.open(archive) as bundle:
            bundle.extractall(root, filter="data")
        (root / f"CLIProxyAPI-{COMMIT}").rename(source)
        subprocess.run(["patch", "--batch", "--forward", "-p1", "-i", str(ASSETS / "preflight-v1.patch")], cwd=source, check=True)
        subprocess.run(["docker", "--context", args.docker_context, "build", "--target", "artifacts",
                        "-f", str(ASSETS / "Dockerfile"), "--output", f"type=local,dest={output}", str(source)], check=True)


if __name__ == "__main__":
    main()
