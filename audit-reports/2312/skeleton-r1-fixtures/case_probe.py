"""沙箱探针：被审文件在第 6 步构建期用 #eval 起 /bin/sh，探查可读、可写、网络、环境、进程。结果写 .lake/probe.txt。"""
import rf, os
r = rf.repo()
base, files = rf.base_and_files(r)
work = os.path.join(rf.WORK, "w-probe")
script = r'''
exec > .lake/probe.txt 2>&1
echo "## id"; id
echo "## env"; env
echo "## pwd"; pwd
echo "## ps"; ps -ef 2>/dev/null || ls /proc | grep '^[0-9]'
echo "## mountinfo"; cat /proc/self/mountinfo
echo "## ls /"; ls -la / /home /root /run /var /tmp 2>&1
echo "## workdir"; ls -la WORKDIR WORKDIR/* 2>&1
echo "## net"; cat /proc/net/dev; (command -v ip && ip addr) 2>&1; (timeout 3 bash -c 'exec 3<>/dev/tcp/1.1.1.1/53 && echo NET-OPEN' 2>&1 || echo NET-CLOSED)
echo "## read host files"
for f in /etc/passwd /etc/shadow /etc/hostname /etc/environment /etc/ssh/ssh_host_ed25519_key /etc/ssh/ssh_host_ed25519_key.pub /proc/1/environ /proc/1/cmdline /home/workspace/.ssh/id_ed25519 /home/workspace/.config /home/workspace/.gitconfig /home/workspace/.netrc /etc/gitconfig /etc/apt/auth.conf /var/lib/docker /srv /opt /mnt /media /snap /usr/local; do
  if [ -d "$f" ]; then echo "DIR $f: $(ls -A "$f" 2>&1 | head -20 | tr '\n' ' ')"; elif head -c 60 "$f" >/dev/null 2>&1; then echo "READABLE $f"; else echo "NOREAD $f"; fi
done
echo "## write tests"
for d in / /etc /usr /usr/local /opt /srv /mnt /media /dev/shm /var/tmp /tmp /home /home/workspace /root /run /sys /sys/fs/cgroup /proc/sys/kernel WORKDIR WORKDIR/trusted WORKDIR/audited WORKDIR/audited/Chan WORKDIR/audited/.lake WORKDIR/audited/.lake/packages WORKDIR/audited/.lake/packages/mathlib PACKAGES PREFIX PREFIX/bin PREFIX/lib/lean; do
  if (echo x > "$d/rf-probe-sentinel") 2>/dev/null; then echo "WRITABLE $d"; else echo "ro-or-absent $d"; fi
done
(echo x > WORKDIR/audited/lakefile.toml) 2>&1 || echo "lakefile.toml not writable"
echo "## writable anywhere (find, depth<=3, excluding /proc /dev /tmp)"
find / -maxdepth 3 \( -path /proc -o -path /dev -o -path /tmp -o -path /sys \) -prune -o -writable -print 2>/dev/null | head -50
echo "## unshare nested"; (unshare -Urm sh -c 'umount /home 2>&1; ls /home | head -3; mount -o remount,rw / 2>&1; echo nested-done') 2>&1
echo "## fds"; ls -la /proc/self/fd
echo "## suid"; find /usr/bin /bin -perm -4000 2>/dev/null | head
echo "## sockets"; find / -maxdepth 4 -type s 2>/dev/null | head
echo "## done"
'''.replace("WORKDIR", work).replace("PACKAGES", rf.PACKAGES)
lean = ('module\n\npublic section\n\n#eval show IO Unit from do\n'
        '  let pfx ← IO.Process.output {cmd := "lean", args := #["--print-prefix"]}\n'
        '  let script := (%s : String).replace "PREFIX" pfx.stdout.trimAscii.toString\n'
        '  let _ ← IO.Process.output {cmd := "/bin/sh", args := #["-c", script]}\n'
        '  pure ()\n') % ('"' + script.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"')
head = r.commit({**files, "formal_math/ChanExplore/Probe.lean": lean.encode()}, base)
res = rf.run("probe", r, head, base, warm=False, workdir=None)
p = os.path.join(res["work"], "audited", ".lake", "probe.txt")
print(open(p).read() if os.path.exists(p) else "NO PROBE OUTPUT")
for d in ["/dev/shm", "/var/tmp", "/tmp", work, work + "/trusted", rf.PACKAGES]:
    print("host sentinel", d, os.path.lexists(os.path.join(d, "rf-probe-sentinel")))
