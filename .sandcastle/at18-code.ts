import { execFileSync } from "node:child_process";
import { cargoContext, type CargoTarget, enabledRustItem } from "./at18-cargo.ts";
import { type At18Repository, utf8 } from "./at18-source.ts";

// Rust 只做语法与源码接入核验，仍由登记的真实 Cargo 作业提供运行结果。
function tokens(source: string, rust: boolean): string[] {
  const out: string[] = [];
  const quote = rust ? /'(?:\\[^]|[^'\\\r\n])'/ : /'(?:\\[^]|[^'\\\r\n])*'/;
  const token = new RegExp(/\s+|\/\/[^\r\n]*|\/\*|(?:b?r(#{0,255})"[^]*?"\1)|"(?:\\[^]|[^"\\])*"|`(?:\\[^]|[^`\\])*`|/.source +
    quote.source + /|[\w]+|::|->|=>|\|\||&&|[^]/.source, "gy");
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
  if (end > start) return { body: code.slice(start + 1, end), args: code.slice(signature + 1, argsEnd), end };
}

function substantiveRust(body: string[]) {
  return body.some(t => /[a-zA-Z0-9]/.test(t)) &&
    !body.some((t, i) => ["todo", "unimplemented"].includes(t) && body[i + 1] === "!");
}

function rustTestBody(code: string[], name: string, qualified?: string) {
  function* candidates(module: string[], parents: string[]): Generator<{
    fn: NonNullable<ReturnType<typeof rustFunction>>; module: string[];
  }> {
    for (const item of rustItems(module)) {
      const symbol = module[item.index + 1];
      if (item.kind === "mod" && module[item.index + 2] === "{") {
        const start = item.index + 2, end = closing(module, start, "{", "}");
        if (end > start) yield* candidates(module.slice(start + 1, end), [...parents, symbol]);
      }
      if (item.kind !== "fn" || symbol !== name ||
          (qualified !== undefined && [...parents, name].join("::") !== qualified)) continue;
      const fn = rustFunction(module, item.index);
      if (!fn || !substantiveRust(fn.body)) continue;
      const attrs = item.prefix.join("");
      if (attrs.includes("#[test]") && !/#\[ignore(?:=|\])/.test(attrs)) yield { fn, module };
    }
  }
  const found = [...candidates(code, [])];
  return found.length === 1 ? found[0] : undefined;
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
type RustReference = { path: string[]; access: RustAccess };
type RustBinding = { kind: "path"; path: string[] } | RustRoutine |
  { kind: "pending"; routine: RustRoutine; args: (RustBinding | undefined)[] };
type RustRoutine = {
  kind: "routine"; body: string[]; params: RustParameter[]; scope: RustScope;
  block: boolean; asynchronous: boolean;
};
type RustScope = {
  parent?: RustScope;
  items: Map<string, RustBinding | undefined>;
  values: Map<string, RustBinding | undefined>;
};
type RustParameter = { simple?: string; shadows: string[] };
const identifier = /^[A-Za-z_]\w*$/;
const delimiters: Record<string, string> = { "(": ")", "[": "]", "{": "}" };

function groupEnd(code: string[], i: number) {
  const close = delimiters[code[i]];
  return close ? closing(code, i, code[i], close) : -1;
}

function separator(code: string[], start: number, end: number, wanted: string) {
  for (let i = start; i < end; i++) {
    if (code[i] === wanted) return i;
    const close = groupEnd(code, i);
    if (close > i) i = close;
  }
  return end;
}

function bindingsOf(pattern: string[]): RustParameter {
  const binding = pattern.filter(t => t !== "ref" && t !== "mut" && t !== "&");
  const shadows = binding.filter((t, i) => identifier.test(t) && t !== "_" &&
    binding[i - 1] !== "::" && ![":", "::", "{", "("].includes(binding[i + 1]));
  return { simple: binding.length === 1 ? shadows[0] : undefined, shadows };
}

function parametersOf(code: string[]) {
  const params: RustParameter[] = [];
  for (let start = 0; start < code.length;) {
    // 泛型的逗号不是形参分隔符。
    let end = start, generic = 0;
    for (; end < code.length; end++) {
      if (code[end] === "<") generic++;
      else if (code[end] === ">" && generic) generic--;
      else if (code[end] === "," && !generic) break;
      const close = groupEnd(code, end);
      if (close > end) end = close;
    }
    params.push(bindingsOf(code.slice(start, separator(code, start, end, ":"))));
    start = end + 1;
  }
  return params;
}

function pathAt(code: string[], i: number) {
  const parts: string[] = [];
  if (code[i] === "::") i++;
  while (identifier.test(code[i] ?? "")) {
    parts.push(code[i++]);
    if (code[i] !== "::") break;
    if (code[i + 1] === "<") {
      const end = closing(code, i + 1, "<", ">");
      if (end >= 0) { i = end + 1; if (code[i] === "::") { i++; continue; } }
    } else if (identifier.test(code[i + 1] ?? "")) {
      i++;
      continue;
    }
    break;
  }
  return { parts, end: i };
}

function lookup(scope: RustScope, [first, ...rest]: string[]): RustBinding | undefined {
  if (!first) return;
  for (let layer: RustScope | undefined = scope; layer; layer = layer.parent) {
    const bindings = layer.values.has(first) ? layer.values : layer.items;
    if (!bindings.has(first)) continue;
    const value = bindings.get(first);
    if (!rest.length) return value;
    if (value?.kind === "path") return { kind: "path", path: [...value.path, ...rest] };
    return;
  }
  return { kind: "path", path: [first, ...rest] };
}

function captured(scope: RustScope, includeValues: boolean): RustScope {
  return {
    parent: scope.parent && captured(scope.parent, includeValues),
    items: scope.items,
    values: includeValues ? new Map(scope.values) : new Map(),
  };
}

// 绑定回答“这个名字是什么”；执行遍历回答“此处是否调用它”。
// 生产接线另查未执行的具名引用，防止把空封装误降级成纯模块公开。
function rustReferences(imports: ReturnType<typeof rustImports>, body: string[], params: string[],
  observeValues: boolean, itemEnabled: (prefix: string[]) => boolean, latent = false): RustReference[] {
  const refs: RustReference[] = [];
  const module: RustScope = {
    items: new Map(imports.map(({ alias, path }) => [alias, { kind: "path", path }])),
    values: new Map(),
  };
  const running = new Set<string[]>();
  function parameterScope(parent: RustScope, params: RustParameter[], args: (RustBinding | undefined)[]): RustScope {
    const values = new Map<string, RustBinding | undefined>();
    params.forEach(({ shadows, simple }, i) => {
      for (const name of shadows) values.set(name, name === simple ? args[i] : undefined);
    });
    return { parent, items: new Map(), values };
  }
  const note = (value: RustBinding | undefined, access: RustAccess) => {
    if (value?.kind === "path") refs.push({ path: value.path, access });
  };

  function evaluateRoutine(routine: RustRoutine, args: (RustBinding | undefined)[]) {
    if (running.has(routine.body)) return;
    running.add(routine.body);
    try {
      const scope = parameterScope(routine.scope, routine.params, args);
      if (routine.block) return block(routine.body, scope);
      return scan(routine.body, 0, routine.body.length, scope);
    } finally {
      running.delete(routine.body);
    }
  }

  function invoke(value: RustBinding | undefined, args: (RustBinding | undefined)[]): RustBinding | undefined {
    if (value?.kind === "routine") {
      if (value.asynchronous) return { kind: "pending", routine: value, args };
      return evaluateRoutine(value, args);
    }
    note(value, "call");
  }

  function block(code: string[], parent: RustScope) {
    const scope: RustScope = { parent, items: new Map(), values: new Map() };
    const skip = new Map<number, number>(), definitions: RustRoutine[] = [];
    // Rust 块内 item 从块起点起可见；let 则直到初始化式结束才遮蔽。
    for (const item of rustItems(code)) {
      const name = code[item.index + 1], enabled = itemEnabled(item.prefix);
      if (item.kind === "use") {
        const end = separator(code, item.index + 1, code.length, ";");
        if (enabled) for (const { alias, path } of rustImports(code.slice(item.index, end + 1))) {
          scope.items.set(alias, { kind: "path", path });
        }
        skip.set(item.index, end + 1);
      } else if (identifier.test(name ?? "") && !["fn", "unsafe", "extern", "async"].includes(name)) {
        if (item.kind === "fn") {
          const fn = rustFunction(code, item.index);
          if (!fn) continue;
          skip.set(item.index, fn.end + 1);
          if (!enabled) continue;
          const routine: RustRoutine = { kind: "routine", body: fn.body, params: parametersOf(fn.args),
            scope: captured(scope, false), block: true, asynchronous: item.prefix.includes("async") };
          scope.items.set(name, routine);
          definitions.push(routine);
        } else {
          const end = separator(code, item.index + 1, code.length, ";");
          const brace = separator(code, item.index + 2, end, "{");
          const braced = ["mod", "struct", "enum", "trait", "union"].includes(item.kind) && brace < end;
          skip.set(item.index, braced ? groupEnd(code, brace) + 1 : end + 1);
          if (enabled) scope.items.set(name, undefined);
        }
      }
    }
    if (latent) for (const routine of definitions) evaluateRoutine(routine, []);
    return scan(code, 0, code.length, scope, false, skip);
  }

  function closure(code: string[], start: number, end: number, scope: RustScope) {
    let i = start;
    const asynchronous = code[i] === "async";
    if (asynchronous) i++;
    if (code[i] === "move") i++;
    if (code[i] !== "|" && code[i] !== "||") return;
    const argsEnd = code[i] === "||" ? i : separator(code, i + 1, end, "|");
    if (argsEnd >= end) return;
    const params = argsEnd === i ? [] : parametersOf(code.slice(i + 1, argsEnd));
    i = argsEnd + 1;
    if (code[i] === "->") i = separator(code, i + 1, end, "{");
    const blockBody = code[i] === "{";
    const last = blockBody ? groupEnd(code, i) : Math.min(
      separator(code, i, end, ","), separator(code, i, end, ";"));
    if (last < i || last > end) return;
    const value: RustRoutine = { kind: "routine", body: code.slice(i + Number(blockBody), last), params,
      scope: captured(scope, true), block: blockBody, asynchronous };
    if (latent) evaluateRoutine(value, []);
    return { end: last + Number(blockBody), value };
  }

  function argumentsOf(code: string[], from: number, end: number, scope: RustScope, observed: boolean,
    limit = Infinity) {
    const args: (RustBinding | undefined)[] = [];
    while (from < end && args.length < limit) {
      // 先识别参数开头的闭包，否则 |a,b| 内部的逗号会截断它。
      const delayed = closure(code, from, end, scope);
      const to = separator(code, delayed?.end ?? from, end, ",");
      args.push(delayed?.end === to ? delayed.value : scan(code, from, to, scope, observed));
      from = to + 1;
    }
    return args;
  }

  function scan(code: string[], start: number, end: number, scope: RustScope, observed = false,
    skip = new Map<number, number>()): RustBinding | undefined {
    let result: RustBinding | undefined;
    for (let i = start; i < end;) {
      const token = code[i], itemEnd = skip.get(i);
      if (itemEnd !== undefined && itemEnd > i) { i = itemEnd; continue; }
      if (token === "#" && code[i + 1] === "[") { i = groupEnd(code, i + 1) + 1; continue; }
      if (token === "let") {
        const last = separator(code, i + 1, end, ";");
        const eq = separator(code, i + 1, last, "=");
        const colon = separator(code, i + 1, eq, ":");
        const { shadows, simple } = bindingsOf(code.slice(i + 1, colon));
        const value = scan(code, eq + 1, last, scope, observed);
        // 只给简单标识符保留函数值；解构的标识符仍须遮蔽外层名字。
        for (const name of shadows) scope.values.set(name, name === simple ? value : undefined);
        i = last + 1;
        continue;
      }
      if ((token === "false" && code[i + 1] === "&&") || (token === "true" && code[i + 1] === "||")) {
        const last = separator(code, i + 2, end, ";");
        // false && A || B still evaluates B; true || A skips the entire remaining disjunction.
        const follow = token === "false" ? separator(code, i + 2, last, "||") : last;
        i = follow + 1;
        continue;
      }
      if (token === "return") return scan(code, i + 1, separator(code, i + 1, end, ";"), scope, observed);
      if (token === "if" && ["true", "false"].includes(code[i + 1]) && code[i + 2] === "{") {
        const yes = groupEnd(code, i + 2), other = code[yes + 1] === "else" && code[yes + 2] === "{";
        const last = other ? groupEnd(code, yes + 2) : yes;
        if (code[i + 1] === "true") block(code.slice(i + 3, yes), scope);
        else if (other) block(code.slice(yes + 3, last), scope);
        i = last + 1;
        continue;
      }
      let value: RustBinding | undefined, next = i + 1;
      const delayed = (i === start || [";", "=", "=>", ","].includes(code[i - 1])) ?
        closure(code, i, end, scope) : undefined;
      if (delayed) {
        ({ value, end: next } = delayed);
      } else if (token === "(" || token === "[" || token === "{") {
        const close = groupEnd(code, i);
        if (close < i || close >= end) break;
        if (token === "{") value = block(code.slice(i + 1, close), scope);
        else if (token === "(" && code[i - 1] !== ".") value = argumentsOf(code, i + 1, close, scope, observed)[0];
        else argumentsOf(code, i + 1, close, scope, observed);
        next = close + 1;
      } else if ((identifier.test(token) || token === "::") && code[i - 1] !== ".") {
        const { parts, end: after } = pathAt(code, i);
        if (!parts.length) { i++; continue; }
        next = after;
        if (code[next] === "!" && groupEnd(code, next + 1) > next) {
          const close = groupEnd(code, next + 1), name = parts.length === 1 ? parts[0] : "";
          // 任意宏可以丢弃实参。标准断言只无条件求值谓词/比较项。
          const limit = ["assert", "debug_assert"].includes(name) ? 1 :
            ["assert_eq", "assert_ne", "debug_assert_eq", "debug_assert_ne"].includes(name) ? 2 : 0;
          if (limit && !name.startsWith("debug_")) argumentsOf(code, next + 2, close, scope, observeValues, limit);
          i = close + 1;
          continue;
        }
        value = token === "::" ? { kind: "path", path: parts } : lookup(scope, parts);
        if (code[next] === "=" && code[next + 1] !== "=" && parts.length === 1) {
          let layer: RustScope | undefined = scope;
          while (layer && !layer.values.has(parts[0])) layer = layer.parent;
          if (layer) {
            const last = separator(code, next + 1, end, ";");
            layer.values.set(parts[0], scan(code, next + 1, last, scope, observed));
            i = last + 1;
            continue;
          }
        }
        if (latent && code[next] === "(") note(lookup(module, parts), "call");
        if (["if", "while", "for", "match", "loop", "else", "as", "in"].includes(token)) value = undefined;
      }
      let invoked = false;
      for (; next < end;) {
        if (code[next] === "(") {
          const close = groupEnd(code, next);
          if (close < next || close >= end) break;
          value = invoke(value, argumentsOf(code, next + 1, close, scope, observed));
          invoked = true;
          next = close + 1;
        } else if (code[next] === "." && identifier.test(code[next + 1] ?? "")) {
          value = code[next + 1] === "await" && value?.kind === "pending" ?
            evaluateRoutine(value.routine, value.args) : undefined;
          next += 2;
        } else break;
      }
      if (observed && !invoked) note(value, "value");
      if (next === end) result = i === start ? value : undefined;
      i = next;
    }
    return result;
  }

  block(body, parameterScope(module, parametersOf(params), []));
  return refs;
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
    const itemEnabled = (prefix: string[]) => enabledRustItem(prefix, features, target);
    function targets(paths: RustReference[], external: boolean, latent = false) {
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
              const fn = rustFunction(code, item.index);
              if (!fn || !substantiveRust(fn.body)) continue;
              if (inReplacement) found.add(path + ":" + name);
              else for (const ref of rustReferences(importsOf(code, items), fn.body, fn.args, false, itemEnabled, latent)) {
                follow(ref.path, [], ref.access);
              }
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
    const registered = rustTestBody(code, name, selector);
    const root = checkPath.startsWith("rust/tests/") ? crate : "crate";
    if (!registered || !root) return false;

    // 根中具名封装和重导出明确接线时，只接受它们到达的导出。
    // 只有纯模块公开的接入方式，才从其可公开访问的路径判定。
    const libCode = read(lib), libItems = active(libCode);
    const roots = libItems.flatMap((item): RustReference[] => {
      if (!item.public) return [];
      if (item.kind === "fn") return [{ path: [libCode[item.index + 1]], access: "call" }];
      if (item.kind === "use") return importsOf(libCode, [item]).map(({ alias }) => ({ path: [alias], access: "export" }));
      return [];
    });
    const production = targets(roots, true);
    const moduleOnly = !production.size && !targets(roots, true, true).size;
    const tested = targets(rustReferences(importsOf(registered.module, active(registered.module)), registered.fn.body, registered.fn.args, true, itemEnabled)
      .filter(ref => ref.path[0] === root).map(ref => ({ path: ref.path.slice(1), access: ref.access })), root !== "crate");
    return [...tested].some(symbol => moduleOnly || production.has(symbol));
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
