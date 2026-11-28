// 只取 Node Runner 的结构化结果。用户 stdout/stderr 从不进入协议。
import { createWriteStream } from 'node:fs';
import { finished } from 'node:stream/promises';

export default async function* reporter(events) {
  const rows = [];
  const summaries = [];
  for await (const { type, data } of events) {
    if (type === 'test:summary' && !data.file) {
      summaries.push(data.counts);
    }
    if (type === 'test:pass' || type === 'test:fail') {
      rows.push({
        name: data.name, source: data.file ?? '', line: data.line ?? 0,
        status: data.skip ? 'skipped' : data.todo ? 'ignored' :
          type === 'test:pass' ? 'passed' : 'failed',
      });
    }
  }
  const stream = createWriteStream(process.env.AT18_FRAMEWORK_FILE, { flags: 'wx' });
  stream.end(JSON.stringify({ rows, summaries }));
  await finished(stream);
}
