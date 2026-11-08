import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { syncBuiltinESMExports } from 'node:module';
import { join } from 'node:path';
import { execFileSync } from 'node:child_process';
import { tmpdir } from 'node:os';
import { retireLegacyShadow, takePidLock } from './decision-claimer.mts';

test('旧影子迁移交错：另一个处理者不得迁走新活动目录或其锁', () => {
  const root=fs.mkdtempSync(join(tmpdir(),'shadow-race-')), dir=join(root,'9');
  fs.mkdirSync(dir); fs.writeFileSync(join(dir,'summary.json'),JSON.stringify({phase:'shadow_p'}));
  const original=fs.readFileSync, exists=fs.existsSync;
  let nested=false, inner: string|null=null;
  // B 已读旧状态并检查旧锁（retireLegacyShadowLocked 用 pidLockHeld 读 dir/.lock）；
  // A 在 B 使用检查结果前完成退役并开始处理。
  fs.readFileSync=((path: fs.PathOrFileDescriptor, ...rest: unknown[]) => {
    if(String(path)===join(dir,'.lock') && !nested){
      nested=true;
      inner=retireLegacyShadow(root,9);
      if(inner){fs.mkdirSync(dir);fs.writeFileSync(join(dir,'.lock'),'active-A');}
    }
    return (original as (...a: unknown[]) => unknown)(path, ...rest);
  }) as typeof fs.readFileSync;
  syncBuiltinESMExports();
  try {
    const outer=retireLegacyShadow(root,9);
    assert.ok(nested,'交错钩子必须真正触发');
    assert.equal([inner,outer].filter(Boolean).length,1,'同票交错只能有一个迁移 owner');
    if(inner) assert.equal(original(join(dir,'.lock'),'utf8'),'active-A','活动锁不可被另一迁移者搬走');
    assert.equal(exists(`${dir}.shadow-p-retired-2`),false);
  } finally {fs.readFileSync=original;syncBuiltinESMExports();fs.rmSync(root,{recursive:true,force:true});}
});

test('残留锁并发回收：两个回收者都判定旧 pid 已不存在时，只能有一个拿到锁，且锁里是它的 pid', () => {
  const root=fs.mkdtempSync(join(tmpdir(),'stale-lock-race-')), lock=join(root,'.9.lock');
  // 已退出子进程的 pid，模拟 SIGKILL 后留下的残留锁。
  const dead=String(execFileSync(process.execPath,['-e','process.stdout.write(String(process.pid))']));
  fs.writeFileSync(lock,dead);
  const original=fs.readFileSync;
  let nested=false, inner: boolean|null=null;
  // A 读到残留 pid 后、动手回收前，B 完整做完一次回收并持锁。
  fs.readFileSync=((path: fs.PathOrFileDescriptor, ...rest: unknown[]) => {
    const result=(original as (...a: unknown[]) => unknown)(path, ...rest);
    if(String(path)===lock && !nested){ nested=true; inner=takePidLock(lock); }
    return result;
  }) as typeof fs.readFileSync;
  syncBuiltinESMExports();
  try {
    const outer=takePidLock(lock);
    assert.ok(nested,'交错钩子必须真正触发');
    assert.equal([inner,outer].filter(Boolean).length,1,'同一把锁只能有一个持有者');
    assert.equal(original(lock,'utf8'),String(process.pid));
    assert.equal(fs.existsSync(`${lock}.takeover`),false,'接管门用完即清');
  } finally {fs.readFileSync=original;syncBuiltinESMExports();fs.rmSync(root,{recursive:true,force:true});}
});

test('残留锁回收：持门后锁已被别人释放并由第三方新建，不得删掉第三方的锁', () => {
  const root=fs.mkdtempSync(join(tmpdir(),'stale-lock-gone-')), lock=join(root,'.9.lock');
  const dead=String(execFileSync(process.execPath,['-e','process.stdout.write(String(process.pid))']));
  fs.writeFileSync(lock,dead);
  const original=fs.readFileSync, other=String(process.ppid);
  let reads=0;
  fs.readFileSync=((path: fs.PathOrFileDescriptor, ...rest: unknown[]) => {
    if(String(path)!==lock) return (original as (...a: unknown[]) => unknown)(path, ...rest);
    reads++;
    try { return (original as (...a: unknown[]) => unknown)(path, ...rest); }
    finally {
      // 第一次读到残留 pid 后：另一个回收者接管、处理完并释放（锁文件消失）。
      if(reads===1) fs.rmSync(lock);
      // 持门后重读发现锁已不在的那一刻：第三方走快速路径以 wx 新建了自己的锁。
      if(reads===2) fs.writeFileSync(lock, other, {flag:'wx'});
    }
  }) as typeof fs.readFileSync;
  syncBuiltinESMExports();
  try {
    assert.equal(takePidLock(lock),false,'第三方已持锁，本进程不得再拿到');
    assert.ok(reads>=2,'交错钩子必须真正触发');
    assert.equal(original(lock,'utf8'),other,'第三方的锁原样保留');
    assert.equal(fs.existsSync(`${lock}.takeover`),false);
  } finally {fs.readFileSync=original;syncBuiltinESMExports();fs.rmSync(root,{recursive:true,force:true});}
});
