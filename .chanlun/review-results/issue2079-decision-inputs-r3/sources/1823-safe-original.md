## B. 清理合同批准后才执行的验收

### SAFE-STALE：只清可证明归属且已停止的 M 外 socket

`socket_residue_cleans_owned_stale_after_sigkill`：重复 OBS-OUT。未来实现须以已批准的排他控制身份确认旧实例已结束、路径属于该会话/域、类型与 uid 正确、路径未被替换，才清理这一 socket；记录核验与 unlink 结果。随后同一合法持久域经规定恢复链启动并通过 ready/数据读回。E/B 残留也必须有具名处置或明确的整体重启失败收据，不能只修 S 就宣布整个 launcher 重启成功。

本测试的正控不得用“PID 不存在”单独放行。PID 可能复用、记录可能缺失，需绑定 boot/start-time/二进制/控制锁/会话以及 socket 归属；核验和 unlink 之间的排他与路径替换风险必须由合同具体解决。

### SAFE-LIVE：活实例与第二 launcher

L1 ready 后启动指向相同 M 外 socket 的 L2；保留同一路径/inode、L1 监听 FD 与已知 Ready 身份。L2 必须拒绝，不能 unlink、替换或截断路径；L1 仍对请求正常返回，数据未丢、未取得第二写者。暂停/高负载导致 connect 超时的活实例同样不能被当 stale。

### SAFE-UNKNOWN：所有权不明和路径类型不对

参数化负控：缺控制收据、PID 不明、PID 复用/boot 不符、错误 uid、socket 属另一会话；同路径普通文件、目录、symlink、父路径 symlink。每例均拒绝且原对象保留，不能删后重试。错误 uid 仅在现有 runner 可合法制造时做真实负控；否则标明缺 fixture 权限，不添加 sudo/隔离扩权。

### SAFE-RACE：核验后的替换

利用批准的测试同步点，在核验与实际删除之间让同一测试的竞争者替换 socket/父路径。删除必须拒绝或在排他协议下无法发生替换；竞争者的对象不得被删除。不得以反复随机 sleep 代替确定调度。若实现无法建立这个边界，安全正控不能通过。

### SAFE-ADMISSION：不以删 socket 放宽 M 或恢复边界

M 内路径一律按批准布局合同拒绝，保持 `SourceTypeUnsupported`、`UnknownDatabaseSidecar`、身份/成员集合、writer.lock、旧 epoch、坏锚等既有门。针对 layout 预检拒绝，断言无域 spawn、无新 DB 或锚、所有原件不变；针对合法恢复，仅允许合同列明的日志/epoch/恢复元数据变化，不允许删除用户数据。

数据断言比较已提交原始事件/订单/仓位等当前 fixture 的完整业务投影及原件存续，不把合法 SQLite WAL/锁文件变化当数据丢失。不得用 `immutable=1` 在有未 checkpoint WAL 时声称读到了最新全量状态；用已批准一致性快照/现成审计入口获取投影，并防止测试观测本身在 admission 窗口创建 shm。
