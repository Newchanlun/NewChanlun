import { execFileSync } from "node:child_process";
import { cargoContext, enabledRustItem } from "./at18-cargo.ts";
import { type At18Repository, utf8 } from "./at18-source.ts";

// Rust 只做语法与源码接入核验，仍由登记的真实 Cargo 作业提供运行结果。
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

function* rustItems(code: string[]) {
  let depth = 0, start = 0;
  for (let i = 0; i < code.length; i++) {
    const t = code[i];
    if (!depth && ["mod", "use", "fn", "type", "struct", "enum", "trait", "const", "static", "union"].includes(t)) {
      yield { index: i, kind: t, prefix: code.slice(start, i), public: code[i - 1] === "pub" ||
        (t === "fn" && /(?:^| )pub(?: (?:async|unsafe|const))*$/.test(code.slice(start, i).join(" "))) };
    }
    if (["{", "(", "["].includes(t)) depth++;
    if (["}", ")", "]"].includes(t)) depth--;
    if (!depth && [";", "}"].includes(t)) start = i + 1;
  }
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

function rustReferences(code: string[], body: string[], callsOnly = false) {
  const imports = rustImports(code);
  return body.flatMap((token, i) => {
    if (!/^[A-Za-z_]\w*$/.test(token) || body[i - 1] === "::") return [];
    const names = [token];
    for (let j = i + 1; body[j] === "::" && /^[A-Za-z_]\w*$/.test(body[j + 1] ?? ""); j += 2) names.push(body[j + 1]);
    if (callsOnly && body[i + 2 * names.length - 1] !== "(") return [];
    const from = imports.filter(item => item.alias === token);
    return from.length ? from.map(item => [...item.path, ...names.slice(1)]) : [names];
  });
}

export function rustReplacement(s: At18Repository, F: string, entry: string, checkPath: string, selector: string, explicit: string[]) {
  const base = "rust/src/";
  if (!entry.startsWith(base)) return false;
  const modulePath = entry.slice(base.length).replace(/(?:\/mod)?\.rs$/, "").split("/");
  if (modulePath.some(p => !/^[A-Za-z_]\w*$/.test(p)) || ["lib", "main"].includes(modulePath[0])) return false;
  try {
    const tree = s.tree(F), lib = base + "lib.rs", cargo = "rust/Cargo.toml";
    const { crate, edition, features } = cargoContext(tree.has(cargo) ? utf8(s.blob(F, cargo)) : undefined, explicit);
    const parsed = new Map<string, string[]>();
    function read(path: string) {
      const cached = parsed.get(path);
      if (cached) return cached;
      const source = utf8(s.blob(F, path));
      // stdin + skip_children：仅让 Rust 语法解析器读取 F 的这一份字节，不取检出的子模块。
      execFileSync("rustfmt", ["--emit", "stdout", "--config", "skip_children=true", "--edition", edition],
        { input: source, stdio: ["pipe", "ignore", "ignore"], timeout: 5_000 });
      const code = tokens(source, true);
      parsed.set(path, code);
      return code;
    }
    function walk(modules: string[]) {
      let path = lib;
      for (const name of modules) {
        const code = read(path);
        if (![...rustItems(code)].some(item => item.kind === "mod" && code[item.index + 1] === name &&
            code[item.index + 2] === ";" && enabledRustItem(item.prefix, features))) return;
        const dir = path === lib ? base : path.replace(/(?:\/mod)?\.rs$/, "") + "/";
        const found = [dir + name + ".rs", dir + name + "/mod.rs"].filter(p => tree.has(p));
        if (found.length !== 1) return;
        path = found[0];
      }
      return path;
    }
    if (walk(modulePath) !== entry || !read(entry).length) return false;
    function qualify(modules: string[], [start, ...rest]: string[]) {
      if (start === "crate") return rest;
      if (start === "super") return qualify(modules.slice(0, -1), rest);
      if (start === "self") return [...modules, ...rest];
      return start === undefined ? modules : [...modules, start, ...rest];
    }
    function reaches(modules: string[], [name, ...tail]: string[], external: boolean, viaEntry: boolean, seen: Set<string>): boolean {
      if (!name) return false;
      const key = JSON.stringify([modules, name, tail, external, viaEntry]);
      if (seen.has(key)) return false;
      seen.add(key);
      const path = walk(modules);
      if (!path) return false;
      const code = read(path);
      // 生产封装可以把内部调用直接解析到替代模块的子模块，不必逐段从入口再走一遍。
      const entered = viaEntry || modulePath.every((part, i) => modules[i] === part);
      const items = [...rustItems(code)].filter(item => enabledRustItem(item.prefix, features));
      if (tail.length && items.some(item => item.kind === "mod" && code[item.index + 1] === name && (!external || item.public)) &&
          reaches([...modules, name], tail, external, entered, seen)) return true;
      for (const item of items) {
        if (external && !item.public) continue;
        if (item.kind === "use") {
          const end = code.indexOf(";", item.index);
          for (const imported of rustImports(code.slice(item.index, end + 1))) {
            if (imported.alias !== name) continue;
            const qualified = qualify(modules, imported.path);
            if (reaches(qualified.slice(0, -1), [...qualified.slice(-1), ...tail], false, entered, seen)) return true;
          }
        } else if (!tail.length && code[item.index + 1] === name && item.kind !== "mod") {
          if (item.kind !== "fn") {
            if (entered) return true;
            continue;
          }
          const body = rustFunction(code, item.index);
          if (!body || !substantiveRust(body)) continue;
          if (entered) return true;
          const imports = items.filter(it => it.kind === "use").flatMap(it =>
            code.slice(it.index, code.indexOf(";", it.index) + 1));
          for (const ref of rustReferences(imports, body, true)) {
            const qualified = qualify(modules, ref);
            if (reaches(qualified.slice(0, -1), qualified.slice(-1), false, false, seen)) return true;
          }
        }
      }
      return false;
    }
    const code = read(checkPath);
    const name = selector.split("::").at(-1) ?? "";
    const body = rustTestBody(code, name, selector);
    const root = checkPath.startsWith("rust/tests/") ? crate : "crate";
    return !!body && !!root && rustReferences(code, body).some(([from, ...path]) =>
      from === root && reaches([], path, root !== "crate", false, new Set<string>()));
  } catch { return false; }
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
