"""本机进程域的 OS 启动代次。只读取原生身份，不接受命令行提供的退休证明。"""
import os
import plistlib
import re
import subprocess
import sys
from pathlib import Path


def local_epoch() -> tuple[str, str]:
    env = {**os.environ, 'LC_ALL': 'C', 'TZ': 'UTC'}
    if sys.platform == 'darwin':
        data = subprocess.check_output(['/usr/sbin/ioreg', '-a', '-rd1', '-c', 'IOPlatformExpertDevice'],
                                       env=env, stderr=subprocess.DEVNULL, timeout=10)
        records = plistlib.loads(data)
        if not isinstance(records, list) or not records or not isinstance(records[0], dict):
            raise ValueError('invalid local host identity')
        host = records[0].get('IOPlatformUUID')
        boot = subprocess.check_output(['/usr/sbin/sysctl', '-n', 'kern.bootsessionuuid'],
                                       env=env, stderr=subprocess.DEVNULL, timeout=10).decode().strip()
    elif sys.platform.startswith('linux'):
        host = Path('/etc/machine-id').read_text().strip()
        boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    else:
        raise ValueError('unsupported local process domain')
    if not isinstance(host, str) or not isinstance(boot, str):
        raise ValueError('invalid local process domain identity')
    if not all(re.fullmatch(r'[a-fA-F0-9-]{32,36}', value) for value in (host, boot)):
        raise ValueError('invalid local process domain identity')
    return host.lower(), boot.lower()
