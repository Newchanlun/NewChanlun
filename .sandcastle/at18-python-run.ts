import { execFileSync, type ExecFileSyncOptionsWithStringEncoding } from "node:child_process";
import { copyFileSync, existsSync, mkdirSync, mkdtempSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, isAbsolute, join, resolve } from "node:path";
import { z } from "zod";
import { type At18Repository } from "./at18-source.ts";

const absolute = z.string().refine(isAbsolute);
const runtime = z.object({ executable: absolute, base: absolute, prefix: absolute, paths: z.array(absolute) });
const receipt = "AT18_PYTHON_COVERED\n";
const driver = ".at18-python-source.py";

function isolatedPython(work: string, scratch: string, input: unknown) {
  const python = runtime.parse(JSON.parse(execFileSync("python3", ["-I", "-B", "-c",
    "import json, site, sys; print(json.dumps(dict(executable=sys.executable, base=sys.base_prefix, prefix=sys.prefix, paths=[*sys.path, *site.getsitepackages()])))"],
  { encoding: "utf8", timeout: 5_000, env: { PATH: process.env.PATH }, stdio: ["ignore", "pipe", "ignore"] })));
  const framework = join(python.base, "Resources/Python.app/Contents/MacOS/Python");
  const argv = [python.executable, "-I", "-B", join(work, driver), scratch];
  const options: ExecFileSyncOptionsWithStringEncoding = {
    cwd: work, env: { HOME: scratch, TMPDIR: scratch, PYTEST_DISABLE_PLUGIN_AUTOLOAD: "1" },
    input: JSON.stringify(input), encoding: "utf8", timeout: 45_000, killSignal: "SIGKILL",
    stdio: ["pipe", "pipe", "ignore"],
  };
  if (process.platform === "darwin") {
    const subtrees = [work, scratch, "/System/Library", "/System/Volumes/Preboot/Cryptexes/OS/usr/lib", "/usr/lib", python.base, ...python.paths].map(path => {
      try { return realpathSync(path); } catch { return path; }
    });
    // Homebrew 的 Framework launcher 会 exec 实际 Python.app；保留原解释器入口以选中其 venv。
    const executables = [python.executable, realpathSync(python.executable)];
    if (existsSync(framework)) executables.push(realpathSync(framework));
    const literal = (path: string) => "(literal " + JSON.stringify(path) + ")";
    const launch = executables.map(literal).join(" ");
    const venv = literal(join(python.prefix, "pyvenv.cfg"));
    const sandbox = `(version 1)(deny default)
      (allow process-exec ${launch})
      (allow file-read-metadata)
      (allow file-read* file-map-executable (literal "/") ${subtrees.map(path => "(subpath " + JSON.stringify(path) + ")").join(" ")}
        ${launch} ${venv} (literal "/dev/null") (literal "/dev/urandom"))
      (allow file-write* (subpath ${JSON.stringify(scratch)}) (literal "/dev/null"))
      (allow sysctl-read)`;
    return execFileSync("/usr/bin/sandbox-exec", ["-p", sandbox, ...argv], options) === receipt;
  }
  if (process.platform === "linux") {
    return execFileSync("bwrap", ["--unshare-all", "--die-with-parent", "--new-session",
      "--ro-bind", "/usr", "/usr", "--ro-bind-try", "/lib", "/lib", "--ro-bind-try", "/lib64", "/lib64",
      "--ro-bind-try", "/etc/ld.so.cache", "/etc/ld.so.cache", "--dev", "/dev",
      "--ro-bind", work, work, "--bind", scratch, scratch, "--chdir", work, "--", ...argv], options) === receipt;
  }
  return false;
}

export function pythonReplacement(s: At18Repository, F: string, entry: string, integration: string,
  checkPath: string, selector: string, count: number) {
  if (!entry.startsWith("trading_system/") || !entry.endsWith(".py") ||
      !integration.startsWith("trading_system/") || !integration.endsWith(".py") || !checkPath.endsWith(".py") ||
      integration.split("/").includes("tests") || integration === checkPath || entry === integration) return false;
  const root = realpathSync(mkdtempSync(join(tmpdir(), "at18-python-")));
  const work = join(root, "source"), scratch = join(root, "scratch");
  try {
    mkdirSync(work);
    mkdirSync(scratch);
    const tree = s.tree(F);
    const support = new Set([entry, integration, checkPath]);
    // 保留登记测试的包和从测试目录到根的 pytest 配置，拒绝从可变检出补文件。
    for (const target of [checkPath, entry, integration]) {
      for (let directory = dirname(target);;) {
        for (const file of ["__init__.py", "conftest.py", "pytest.ini", "pyproject.toml", "setup.cfg", "tox.ini"]) {
          const path = join(directory, file);
          if (tree.has(path)) support.add(path);
        }
        if (directory === ".") break;
        directory = dirname(directory);
      }
    }
    for (const path of tree.keys()) {
      if (path.endsWith(".py") && (path.startsWith("trading_system/") ||
          (dirname(checkPath) !== "." && path.startsWith(dirname(checkPath) + "/")))) support.add(path);
    }
    for (const path of support) {
      const bytes = s.blob(F, path); // 仅受验树中的普通文件，不跟随符号链接。
      const file = join(work, path);
      mkdirSync(dirname(file), { recursive: true });
      writeFileSync(file, bytes, { flag: "wx" });
    }
    copyFileSync(resolve(__dirname, "at18-python-source.py"), join(work, driver));
    return isolatedPython(work, scratch, { entry, integration, checkPath, selector, count });
  } catch { return false; }
  finally { rmSync(root, { recursive: true, force: true }); }
}
