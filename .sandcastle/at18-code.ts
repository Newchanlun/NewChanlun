import { execFileSync } from "node:child_process";
import { resolve } from "node:path";
import { type At18Repository, utf8 } from "./at18-source.ts";

// 只判读源文本，不执行受验提交。保留 token，注释和字符串中的伪声明不作证。
function tokens(source: string, rust: boolean): string[] {
  const out: string[] = [];
  const quote = rust ? /'(?:\\[^]|[^'\\\r\n])'/ : /'(?:\\[^]|[^'\\\r\n])*'/;
  const token = new RegExp(/\s+|\/\/[^\r\n]*|\/\*|(?:b?r(#{0,255})"[^]*?"\1)|"(?:\\[^]|[^"\\])*"|`(?:\\[^]|[^`\\])*`|/.source +
    quote.source + /|[\w]+|::|->|=>|[^]/.source, "gy");
  for (let i = 0; i < source.length;) {
    token.lastIndex = i;
    const next = token.exec(source);
    if (!next) return [];
    const value = next[0];
    i = token.lastIndex;
    if (value === "/*") {
      let depth = 1;
      while (depth && i < source.length) {
        if (rust && source.startsWith("/*", i)) { depth++; i += 2; }
        else if (source.startsWith("*/", i)) { depth--; i += 2; }
        else i++;
      }
      if (depth) return [];
    } else if (!/^\s|^\/\//.test(value)) out.push(value);
  }
  return out;
}

function closing(code: string[], start: number, left: string, right: string) {
  let depth = 0;
  for (let i = start; i < code.length; i++) {
    if (code[i] === left) depth++;
    else if (code[i] === right && --depth === 0) return i;
  }
  return -1;
}

function rustFunction(code: string[], index: number) {
  if (code[index] !== "fn" || !/^[A-Za-z_]\w*$/.test(code[index + 1] ?? "")) return;
  const signature = code.slice(index + 2).findIndex(t => ["(", ";", "{", "}"].includes(t)) + index + 2;
  if (code[signature] !== "(") return;
  const argsEnd = closing(code, signature, "(", ")");
  if (argsEnd < 0) return;
  const offset = code.slice(argsEnd + 1).findIndex(t => ["{", ";", "}"].includes(t));
  const start = argsEnd + 1 + offset;
  if (offset < 0 || code[start] !== "{") return;
  const end = closing(code, start, "{", "}");
  if (end > start) return code.slice(start + 1, end);
}

function substantiveRust(body: string[]) {
  return body.some(t => /[a-zA-Z0-9]/.test(t)) &&
    !body.some((t, i) => ["todo", "unimplemented"].includes(t) && body[i + 1] === "!");
}

function rustTestBody(code: string[], name: string, qualified?: string) {
  const matching = code.map((t, i) => t === "fn" && code[i + 1] === name ? i : -1).filter(i => i >= 0);
  const modulesAt = (end: number) => {
    const stack: string[] = [];
    for (let i = 0; i < end; i++) {
      if (code[i] === "{") stack.push(code[i - 2] === "mod" ? code[i - 1] : "");
      else if (code[i] === "}") stack.pop();
    }
    return [...stack.filter(Boolean), name].join("::");
  };
  const found = qualified === undefined ? matching : matching.filter(i => modulesAt(i) === qualified);
  if (found.length !== 1) return;
  const index = found[0];
  const body = rustFunction(code, index);
  if (!body || !substantiveRust(body)) return false;
  const attributes: string[][] = [];
  let i = index - 1;
  while (["pub", "async", "unsafe"].includes(code[i])) i--;
  while (code[i] === "]") {
    const start = closing(code.slice(0, i + 1).reverse(), 0, "]", "[");
    if (start < 0 || code[i - start - 1] !== "#") break;
    attributes.push(code.slice(i - start + 1, i));
    i -= start + 2;
  }
  return attributes.some(a => a.join("") === "test") && !attributes.some(a => a.includes("ignore")) ? body : undefined;
}

export function rustTest(source: string, name: string, selector?: string) {
  return !!rustTestBody(tokens(source, true), name, selector);
}

function pythonAst(input: unknown) {
  try {
    execFileSync("python3", ["-I", resolve(__dirname, "at18-python-source.py")],
      { input: JSON.stringify(input), stdio: ["pipe", "ignore", "ignore"], timeout: 5_000 });
    return true;
  } catch { return false; }
}

function rustModules(code: string[], features: string[]) {
  const modules: string[] = [];
  let depth = 0, start = 0;
  for (let i = 0; i < code.length; i++) {
    if (depth === 0 && code[i] === "mod" && /^[A-Za-z_]\w*$/.test(code[i + 1] ?? "") && code[i + 2] === ";") {
      const attributes = code.slice(start, i);
      // 非测试模块可能受平台或 Cargo feature 约束；未知路径重定向不能靠文件名猜。
      if (!attributes.some((t, j) => {
        if (t !== "#" || attributes[j + 1] !== "[") return false;
        if (["path", "cfg_attr"].includes(attributes[j + 2])) return true;
        if (attributes[j + 2] !== "cfg") return false;
        const end = closing(attributes, j + 1, "[", "]");
        const cfg = attributes.slice(j + 3, end).join("");
        return !["(unix)", "(windows)"].includes(cfg) && !features.some(feature => cfg === `(feature=${JSON.stringify(feature)})`);
      })) modules.push(code[i + 1]);
    }
    if (code[i] === "{") depth++;
    if (code[i] === "}") depth--;
    if (depth === 0 && (code[i] === ";" || code[i] === "}")) start = i + 1;
  }
  return modules;
}

function rustImports(code: string[]) {
  const imports: { path: string[]; alias: string; exported: boolean }[] = [];
  for (let i = 0; i < code.length; i++) {
    if (code[i] !== "use") continue;
    const end = code.indexOf(";", i);
    if (end < 0) break;
    const tree = code.slice(i + 1, end);
    const exported = code[i - 1] === "pub";
    let next = 0;
    function useTree(path: string[]) {
      const part = tree[next++];
      if (part === "{") {
        while (next < tree.length && tree[next] !== "}") {
          useTree(path);
          if (tree[next] === ",") next++;
        }
        if (tree[next] === "}") next++;
        return;
      }
      if (!part || !/^[A-Za-z_]\w*$/.test(part)) return;
      const resolved = part === "self" && path.length ? path : [...path, part];
      if (tree[next] === "::") { next++; useTree(resolved); return; }
      const alias = tree[next] === "as" ? (next++, tree[next++]) : resolved.at(-1);
      if (alias) imports.push({ path: resolved, alias, exported });
    }
    useTree([]);
    i = end;
  }
  return imports;
}

function rustReferences(code: string[], body: string[]) {
  const imports = rustImports(code);
  return body.flatMap((token, i) => {
    if (!/^[A-Za-z_]\w*$/.test(token) || body[i - 1] === "::") return [];
    const names = [token];
    for (let j = i + 1; body[j] === "::" && /^[A-Za-z_]\w*$/.test(body[j + 1] ?? ""); j += 2) names.push(body[j + 1]);
    const from = imports.filter(item => item.alias === token);
    return from.length ? from.map(item => [...item.path, ...names.slice(1)]) : [names];
  });
}

function rustDefinition(code: string[], name: string) {
  return code.some((t, i) => {
    if (code[i + 1] !== name) return false;
    if (t === "fn") {
      const body = rustFunction(code, i);
      return !!body && body.some(token => !["{", "}", "(", ")", ";", ",", "return"].includes(token)) &&
        !body.some((token, j) => ["todo", "unimplemented"].includes(token) && body[j + 1] === "!");
    }
    return ["type", "struct", "enum", "trait", "const", "static", "union"].includes(t);
  });
}

export function rustReplacement(s: At18Repository, F: string, entry: string, checkPath: string, selector: string, features: string[]) {
  const base = "rust/src/";
  if (!entry.startsWith(base)) return false;
  const modulePath = entry.slice(base.length).replace(/(?:\/mod)?\.rs$/, "").split("/");
  if (modulePath.some(p => !/^[A-Za-z_]\w*$/.test(p)) || ["lib", "main"].includes(modulePath[0])) return false;
  const tree = s.tree(F);
  const read = (path: string) => utf8(s.blob(F, path));
  function child(parent: string, name: string) {
    const dir = parent === base + "lib.rs" ? base : parent.replace(/(?:\/mod)?\.rs$/, "") + "/";
    const found = [dir + name + ".rs", dir + name + "/mod.rs"].filter(p => tree.has(p));
    return found.length === 1 ? found[0] : undefined;
  }
  const lib = base + "lib.rs";
  function walk(modules: string[]) {
    let path = lib;
    for (const name of modules) {
      if (!rustModules(tokens(read(path), true), features).includes(name)) return undefined;
      const next = child(path, name);
      if (!next) return undefined;
      path = next;
    }
    return path;
  }
  if (walk(modulePath) !== entry) return false;
  function resolves(modules: string[], names: string[], seen = new Set<string>()): boolean {
    if (!names.length) return false;
    const key = modules.join("::") + "/" + names.join("::");
    if (seen.has(key)) return false;
    seen.add(key);
    const current = walk(modules);
    if (!current) return false;
    const code = tokens(read(current), true);
    const [name, ...tail] = names;
    if (tail.length ? resolves([...modules, name], tail, seen) : rustDefinition(code, name)) return true;
    return rustImports(code).filter(item => item.alias === name && item.exported).some(({ path }) => {
      const [start, ...rest] = path;
      const qualified = start === "crate" ? rest : start === "super" ? [...modules.slice(0, -1), ...rest] :
        [...modules, ...(start === "self" ? rest : path)];
      return resolves(qualified.slice(0, -1), [...qualified.slice(-1), ...tail], seen);
    });
  }
  const cargo = read("rust/Cargo.toml");
  const crate = /(?:^|\n)\[lib\]([^]*?)(?:\n\[|$)/.exec(cargo)?.[1].match(/^name\s*=\s*"([\w-]+)"/m)?.[1] ??
    /(?:^|\n)\[package\]([^]*?)(?:\n\[|$)/.exec(cargo)?.[1].match(/^name\s*=\s*"([\w-]+)"/m)?.[1];
  const code = tokens(read(checkPath), true);
  const name = selector.split("::").at(-1) ?? "";
  const body = rustTestBody(code, name, selector);
  const root = checkPath.startsWith("rust/tests/") ? crate?.replaceAll("-", "_") : "crate";
  return !!body && !!root && rustReferences(code, body).some(([from, ...path]) =>
    from === root && modulePath.every((name, i) => path[i] === name) && resolves(modulePath, path.slice(modulePath.length)));
}

export function pythonReplacement(s: At18Repository, F: string, entry: string, integration: string, checkPath: string, selector: string) {
  if (!entry.startsWith("trading_system/") || !integration.startsWith("trading_system/") ||
      !integration.endsWith(".py") || !checkPath.endsWith(".py") ||
      integration.split("/").includes("tests") || integration === checkPath || entry === integration) return false;
  const read = (path: string) => utf8(s.blob(F, path));
  return pythonAst({ source: read(entry), entry, integration, caller: read(integration), checkPath, test: read(checkPath), selector });
}

export function nodeTest(source: string, name: string) {
  const code = tokens(source, false);
  return code.some((t, i) => {
    if (t !== "test" || code[i + 1] !== "(" ||
        ![JSON.stringify(name), "'" + name + "'"].includes(code[i + 2]) || code[i + 3] !== ",") return false;
    const end = closing(code, i + 1, "(", ")");
    const start = code.indexOf("=>", i + 4) + 1;
    if (!start || start >= end || code[start] !== "{") return false;
    const tail = closing(code, start, "{", "}");
    return tail > start && tail < end && code.slice(start + 1, tail).some(token => /^[A-Za-z_]\w*$/.test(token));
  });
}
