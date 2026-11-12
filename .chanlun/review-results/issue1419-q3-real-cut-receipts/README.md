# `#1419` Q3 S3 真实多代夹具公开入口收据（`t1..t5`）

对应测试：`s_session/tests/test_q3_s3_real_cut.cjs`（`test_sha256` `1e76f967487aa8bca7e9f20e6ac9b297753a9aa30076cc07ffe8aaa89487dee2`）
对应夹具加载器：`s_session/tests/q3_complete_fixture.cjs`（`harness_sha256` `8248fd718319e0068d81e64202ae820cfd6179b668f07f4175e363dceb9dfeba`）
对应夹具：`s_session/tests/fixtures/q3-real-s3-w-recover-revise.json`（Git LFS 入仓，`91,895,732 B`，`fixture_sha256` `2a83c1808b21fdc6647d37a602d782622b2d74c5bfb4342e16cb69f7d0490a2a`）
浏览器单文件产物：`s_session/browser/tb01c-client.js`（`bundle_sha256` `18d0c34a106818b4b4371f3e89c8518c19049206e860e165fc545131d04ab8b4`，含 `#1978` 与 `#1789`/`#1855` W1 冻结基串 vs V3/W2 现役基串、槽位及时间序闭环对齐）
运行环境：macOS arm64（96 GiB RAM），Node `v22.23.1`，严格单进程串行执行。

## 逐条命令与实测读数

命令模板：

```bash
/usr/bin/time -l env Q3_WIRE_PROBE=1 node --max-old-space-size=16000 --test --test-reporter=tap \
  --test-name-pattern="<pattern>" s_session/tests/test_q3_s3_real_cut.cjs > .chanlun/review-results/issue1419-q3-real-cut-receipts/<id>.log 2>&1
```

| 编号 | 匹配模式 | 结果 | 退出码 | 实测耗时（real） | 峰值 RSS（bytes） | Swaps | 日志文件 |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| `t1` | `导出出自 W 唯一写者规则串` | `ok 1` | `0` | `0.67 s` | `693,075,968` | `0` | `t1.log` |
| `t2` | `cut0 首根与等待期` | `ok 1` | `0` | `36.20 s` | `1,669,300,224` | `0` | `t2.log` |
| `t3` | `跨真实写者恢复` | `ok 1` | `0` | `1752.06 s` | `10,637,721,600` | `0` | `t3.log` |
| `t4` | `首中枢` | `ok 1` | `0` | `5137.82 s` | `15,869,870,080` | `0` | `t4.log` |
| `t5` | `尾段` | `ok 1` | `0` | `2531.60 s` | `13,973,422,080` | `0` | `t5.log` |
