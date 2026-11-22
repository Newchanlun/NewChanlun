import { execFileSync } from "node:child_process";
import { cargoContext, type CargoTarget, enabledRustItem } from "./at18-cargo.ts";
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

type RustAccess = "call" | "value" | "export";

// 函数引用可绑定给局部变量，但只有后续调用才构成行为证据。
function* rustReferences(imports: ReturnType<typeof rustImports>, body: string[], observeValues: boolean) {
  const scopes: Map<string, string[] | null>[] = [new Map()];
  const pending = new Map<number, [string, string[] | null]>();
  const identifier = /^[A-Za-z_]\w*$/;
  let assertedTo = -1;
  function pathAt(i: number) {
    const parts: string[] = [];
    while (identifier.test(body[i] ?? "")) {
      parts.push(body[i++]);
      if (body[i] !== "::" || !identifier.test(body[i + 1] ?? "")) break;
      i++;
    }
    return { parts, end: i };
  }
  function resolve([first, ...rest]: string[]) {
    if (!first) return [];
    for (let i = scopes.length - 1; i >= 0; i--) {
      const scope = scopes[i];
      if (scope.has(first)) {
        const path = scope.get(first);
        return path ? [...path, ...rest] : [];
      }
    }
    const imported = imports.find(item => item.alias === first);
    return [...(imported?.path ?? [first]), ...rest];
  }
  for (let i = 0; i < body.length; i++) {
    const token = body[i];
    const scope = scopes.at(-1)!;
    if (token === "{") scopes.push(new Map());
    if (token === "}") scopes.pop();
    if (token === "let") {
      const nameAt = i + (body[i + 1] === "mut" ? 2 : 1);
      const semi = body.indexOf(";", nameAt);
      const eq = body.indexOf("=", nameAt);
      if (semi > nameAt && identifier.test(body[nameAt]) && ["=", ":", ";"].includes(body[nameAt + 1])) {
        const rhs = eq > nameAt && eq < semi ? pathAt(eq + 1) : undefined;
        const path = rhs?.end === semi ? resolve(rhs.parts) : [];
        pending.set(semi, [body[nameAt], path.length ? path : null]);
      }
    }
    const binding = pending.get(i);
    if (binding) scope.set(...binding);
    if (observeValues && ["assert", "assert_eq", "assert_ne"].includes(token) && body[i + 1] === "!") {
      const open = body[i + 2], close = open === "(" ? ")" : open === "[" ? "]" : open === "{" ? "}" : "";
      if (close) assertedTo = Math.max(assertedTo, closing(body, i + 2, open, close));
    }
    if (!identifier.test(token) || ["::", ".", "fn"].includes(body[i - 1])) continue;
    const { parts, end } = pathAt(i);
    const call = body[end] === "(";
    if (call || i < assertedTo) {
      const access: RustAccess = call ? "call" : "value";
      yield { path: resolve(parts), access };
    }
  }
}

export function rustReplacement(s: At18Repository, F: string, entry: string, checkPath: string, selector: string,
  explicit: string[], target?: CargoTarget) {
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
            code[item.index + 2] === ";" && enabledRustItem(item.prefix, features, target))) return;
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
    function active(code: string[]) {
      return [...rustItems(code)].filter(item => enabledRustItem(item.prefix, features, target));
    }
    function importsOf(code: string[], items: ReturnType<typeof active>) {
      return items.filter(item => item.kind === "use").flatMap(item =>
        rustImports(code.slice(item.index, code.indexOf(";", item.index) + 1)));
    }
    function targets(paths: { path: string[]; access: RustAccess }[], external: boolean) {
      const found = new Set<string>(), seen = new Set<string>();
      function visit(modules: string[], [name, ...tail]: string[], external: boolean, access: RustAccess) {
        if (!name) return;
        const key = JSON.stringify([modules, name, tail, external, access]);
        if (seen.has(key)) return;
        seen.add(key);
        const path = walk(modules);
        if (!path) return;
        const code = read(path);
        const items = active(code);
        const inReplacement = modulePath.every((part, i) => modules[i] === part);
        function follow(path: string[], tail: string[], access: RustAccess) {
          const qualified = qualify(modules, path);
          visit(qualified.slice(0, -1), [...qualified.slice(-1), ...tail], false, access);
        }
        for (const item of items) {
          if (external && !item.public) continue;
          if (item.kind === "use") {
            const end = code.indexOf(";", item.index);
            for (const imported of rustImports(code.slice(item.index, end + 1))) {
              if (imported.alias === name) follow(imported.path, tail, access);
            }
          } else if (code[item.index + 1] === name) {
            if (item.kind === "mod" && tail.length) visit([...modules, name], tail, external, access);
            if (tail.length || item.kind === "mod") continue;
            if (item.kind === "fn" && access !== "value") {
              const body = rustFunction(code, item.index);
              if (!body || !substantiveRust(body)) continue;
              if (inReplacement) found.add(path + ":" + name);
              else for (const ref of rustReferences(importsOf(code, items), body, false)) follow(ref.path, [], ref.access);
            } else if (inReplacement && access !== "call" && ["const", "static"].includes(item.kind)) {
              found.add(path + ":" + name);
            }
          }
        }
      }
      for (const { path, access } of paths) visit([], path, external, access);
      return found;
    }
    const code = read(checkPath);
    const name = selector.split("::").at(-1) ?? "";
    const body = rustTestBody(code, name, selector);
    const root = checkPath.startsWith("rust/tests/") ? crate : "crate";
    if (!body || !root) return false;

    // 根中具名封装和重导出明确接线时，只接受它们到达的导出。
    // 只有纯模块公开的接入方式，才从其可公开访问的路径判定。
    const libCode = read(lib), libItems = active(libCode);
    const production = targets(libItems.flatMap((item): { path: string[]; access: RustAccess }[] => {
      if (!item.public) return [];
      if (item.kind === "fn") return [{ path: [libCode[item.index + 1]], access: "call" }];
      if (item.kind === "use") return importsOf(libCode, [item]).map(({ alias }) => ({ path: [alias], access: "export" }));
      return [];
    }), true);
    const tested = targets([...rustReferences(rustImports(code), body, true)]
      .filter(ref => ref.path[0] === root).map(ref => ({ path: ref.path.slice(1), access: ref.access })), root !== "crate");
    return [...tested].some(symbol => !production.size || production.has(symbol));
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
