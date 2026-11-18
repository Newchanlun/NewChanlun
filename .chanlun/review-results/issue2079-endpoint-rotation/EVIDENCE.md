# #2079 端点交接可行性实证

## Linux：分离名字写权，每一代新建监听器

[原始输出](linux-fresh.log) · [协调器](run_fresh.py) · [端点、域与客户端](fresh_listener.py)

在已有本地 OrbStack Docker 镜像上运行。协调器仅为本用例创建容器；不联网，镜像不拉取，根文件系统只读，全部 capabilities 去除、禁止提权，临时目录为容器私有 tmpfs。容器内 UID 0 只作为本次专用目录 owner，不是宿主账号或产品权限。两代 worker 和客户端均为容器 UID 65534。复跑：

```sh
cd .chanlun/review-results/issue2079-endpoint-rotation
python3 -B run_fresh.py
```

实测退出 0。两个 worker 的容器 PID 分别为 11、31。在同一命名目录内，普通客户端的 create、rename、unlink 两代均被拒绝，同一原地址分别答复 from-1、from-2。原队列已有已写入连接，在第一代最后一个 listener FD 关闭后收到 ECONNRESET。第二代重新 bind 原名，实际接受并识别的是新连接。

测试协调器按顺序等两代退出，受保护父目录在测试中不变，不是“现行产品部署已具备排他”的证据。测试专用 SCM_RIGHTS 通道按夹具调度传 FD；实际实现须受信启动通道及定向角色校验。没有运行业务 writer、协议校验或账目恢复；未实跑 Darwin 的异 UID 新 listener 方案。

## Darwin 与 Linux：跨新进程复用同一 listener

[探针](probe.py) · [Darwin 输出](darwin-fd.jsonl) · [Linux 输出](linux-fd.jsonl)。运行用私有临时目录与 Unix 本地 socket，无 TCP 流量。

```sh
cd .chanlun/review-results/issue2079-endpoint-rotation
python3 -B probe.py keeper
docker --context orbstack run --rm --pull never --network none --read-only \
  --cap-drop ALL --security-opt no-new-privileges --user 65534:65534 \
  --tmpfs /tmp:mode=1777 -v "$PWD:/p:ro" python:3.11-bookworm \
  python -B /p/probe.py keeper
```

独立持有者保存 FD，两个先后启动的 launcher 及其各自的域 worker 通过传入 FD accept。两边实际发送/接受/回包均成功，公开目录项及 inode 均未换；原 launcher 和 worker 已退出，与二代进程 PID 不同。二代收到的正是启动前已排队的 `queued-before-next-generation`。最后持有者关闭后，另行 bind 原名仍被 EADDRINUSE 拒绝。Darwin 上 SO_ACCEPTCONN 的初试返回 ENOPROTOOPT；最终两端以 AF_UNIX、SO_TYPE、getsockname 和真实 accept/往返确认，Linux 另查 SO_ACCEPTCONN。

没有部署或修改 systemd、launchd、业务入口或发布权限。这里验证的是“持有同一 FD”的跨代队列语义，不是对某款部署管理器配置的认证。
