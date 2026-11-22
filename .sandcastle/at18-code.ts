import { execFileSync } from "node:child_process";
import { cargoContext, type CargoTarget, enabledRustItem } from "./at18-cargo.ts";
import { type At18Repository, utf8 } from "./at18-source.ts";

// Rust 只做语法与源码接入核验，仍由登记的真实 Cargo 作业提供运行结果。
function tokens(source: string, rust: boolean): string[] {
  const out: string[] = [];
  const quote = rust ? /b?'(?:\\[^]|[^'\\\r\n])'/ : /'(?:\\[^]|[^'\\\r\n])*'/;
  const token = new RegExp(/\s+|\/\/[^\r\n]*|\/\*|(?:b?r(#{0,255})"[^]*?"\1)|(?:b|c)?"(?:\\[^]|[^"\\])*"|`(?:\\[^]|[^`\\])*`|/.source +
    quote.source + /|[\w]+|::|->|=>|\.\.=|\.\.|==|!=|\|\||&&|[^]/.source, "gy");
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

function rustTestBody(code: string[], name: string, qualified?: string, enabled = (_prefix: string[]) => true) {
  function* candidates(module: string[], parents: string[]): Generator<{
    fn: NonNullable<ReturnType<typeof rustFunction>>; module: string[];
  }> {
    for (const item of rustItems(module)) {
      if (!enabled(item.prefix)) continue;
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

type RustAccess = "call" | "drive" | "value" | "export";
type RustReference = { path: string[]; access: RustAccess };
type RustBinding = { kind: "path" | "call-result"; path: string[] } | RustRoutine |
  { kind: "pending"; routine: RustRoutine; args: (RustBinding | undefined)[]; driver: "await" | "iterate" | "async-iterate" };
type RustRoutine = {
  kind: "routine"; body: string[]; params: RustParameter[]; scope: RustScope;
  block: boolean; asynchronous: boolean;
};
type RustScope = {
  parent?: RustScope;
  items: Map<string, RustBinding | undefined>;
  macros: Set<string>;
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

const patternKeywords = new Set(["_", "ref", "mut", "box", "true", "false", "const", "self", "Self",
  "super", "crate"]);
function patternBindings(pattern: string[]): RustParameter {
  const names = new Set<string>();
  for (let i = 0; i < pattern.length; i++) {
    const token = pattern[i];
    if (token === "#" && pattern[i + 1] === "[") {
      i = groupEnd(pattern, i + 1);
      continue;
    }
    if (token === "const" && pattern[i + 1] === "{") {
      i = groupEnd(pattern, i + 1);
      continue;
    }
    if (token === "::" && pattern[i + 1] === "<") {
      const end = closing(pattern, i + 1, "<", ">");
      if (end > i) i = end;
      continue;
    }
    if (identifier.test(token) && !patternKeywords.has(token) && pattern[i - 1] !== "::" &&
        ![":", "::", "{", "("].includes(pattern[i + 1])) names.add(token);
  }
  // 只有按值绑定的一个名字可以保留初始化式的函数值；引用和解构仅建立遮蔽。
  const direct = pattern[0] === "mut" ? pattern.slice(1) : pattern;
  return { shadows: [...names], simple: direct.length === 1 && names.has(direct[0]) ? direct[0] : undefined };
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
    params.push(patternBindings(code.slice(start, separator(code, start, end, ":"))));
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
    macros: scope.macros,
    values: includeValues ? new Map(scope.values) : new Map(),
  };
}

// 绑定回答“这个名字是什么”；执行遍历回答“此处是否调用它”。
// 生产接线另查未执行的具名引用，防止把空封装误降级成纯模块公开。
function rustReferences(imports: ReturnType<typeof rustImports>, body: string[], params: string[],
  observeValues: boolean, itemEnabled: (prefix: string[]) => boolean, latent = false, driveReturn = false): RustReference[] {
  const refs: RustReference[] = [];
  const module: RustScope = {
    items: new Map(imports.map(({ alias, path }) => [alias, { kind: "path", path }])),
    macros: new Set(),
    values: new Map(),
  };
  const running = new Set<string[]>();
  const childScope = (parent: RustScope): RustScope =>
    ({ parent, items: new Map(), macros: new Set(), values: new Map() });

  function localMacro(scope: RustScope | undefined, name: string): boolean {
    for (; scope; scope = scope.parent) if (scope.macros.has(name)) return true;
    return false;
  }
  function shadow(scope: RustScope, pattern: RustParameter, value?: RustBinding) {
    for (const name of pattern.shadows) scope.values.set(name, name === pattern.simple ? value : undefined);
  }

  function parameterScope(parent: RustScope, params: RustParameter[], args: (RustBinding | undefined)[]): RustScope {
    const scope = childScope(parent);
    params.forEach((pattern, i) => shadow(scope, pattern, args[i]));
    return scope;
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
      if (value.asynchronous) return { kind: "pending", routine: value, args, driver: "await" };
      return evaluateRoutine(value, args);
    }
    if (value?.kind === "path") {
      note(value, "call");
      return { kind: "call-result", path: value.path };
    }
  }

  function drive(value: RustBinding | undefined, driver: "await" | "iterate" | "async-iterate") {
    if (value?.kind === "pending" && value.driver === driver) return evaluateRoutine(value.routine, value.args);
    if (value?.kind === "call-result" && driver === "await") refs.push({ path: value.path, access: "drive" });
  }

  function afterAttributes(code: string[], start: number) {
    let i = start;
    while (code[i] === "#" && code[i + 1] === "[") {
      const close = groupEnd(code, i + 1);
      if (close <= i) break;
      i = close + 1;
    }
    return i;
  }

  function beforeItem(code: string[], start: number) {
    let i = afterAttributes(code, start);
    if (code[i] === "pub") {
      i++;
      if (code[i] === "(") i = groupEnd(code, i) + 1;
    }
    while (["async", "unsafe", "default"].includes(code[i]) ||
        (["const", "extern"].includes(code[i]) && ["async", "unsafe", "const", "extern", "fn"].includes(code[i + 1]))) i++;
    if (code[i] === "extern" && code[i + 1]?.startsWith('"')) i += 2;
    return i;
  }

  function itemAt(code: string[], start: number) {
    const i = beforeItem(code, start), kind = code[i];
    const named = ["mod", "use", "fn", "type", "struct", "enum", "trait", "const", "static", "union", "macro_rules", "extern"];
    if (kind === "impl" || (kind === "extern" && code[i + 1] === "{") ||
        (code[i - 2] === "extern" && kind === "{")) {
      const brace = separator(code, i, code.length, "{");
      if (brace === code.length) return;
      return { index: i, end: groupEnd(code, brace) + 1, opaqueBody: brace };
    }
    if (!named.includes(kind)) return;
    const name = code[i + (kind === "static" && code[i + 1] === "mut" || kind === "macro_rules" ? 2 : 1)];
    if (!identifier.test(name ?? "") || (kind === "const" && name === "_")) {
      if (!(kind === "use" && ["::", "{"].includes(name)) && !(kind === "const" && name === "_")) return;
    }
    if (kind === "fn") {
      const fn = rustFunction(code, i);
      if (fn) return { index: i, end: fn.end + 1, name, fn };
    }
    if (["mod", "struct", "enum", "trait", "union", "macro_rules"].includes(kind)) {
      const semi = separator(code, i + 1, code.length, ";");
      const brace = separator(code, i + 1, semi, "{");
      if (brace < semi) return { index: i, end: groupEnd(code, brace) + 1, name, opaqueBody: brace };
      if (kind === "macro_rules") {
        const group = i + 3, close = groupEnd(code, group);
        if (close > group) return { index: i, end: close + 1, name };
      }
    }
    return { index: i, end: separator(code, i + 1, code.length, ";") + 1, name };
  }

  function block(code: string[], parent: RustScope) {
    const scope = childScope(parent);
    const skip = new Map<number, number>(), definitions: RustRoutine[] = [], opaque: string[][] = [];
    // 块级 item 预先遮蔽。跳过每个 item 的完整范围，不把内部方法或宏体当作语句。
    for (let i = 0; i < code.length;) {
      const item = itemAt(code, i);
      if (item && item.end > i) {
        skip.set(i, item.end);
        const enabled = itemEnabled(code.slice(i, item.index));
        if (enabled && code[item.index] === "use") {
          for (const { alias, path } of rustImports(code.slice(item.index, item.end))) {
            scope.items.set(alias, { kind: "path", path });
          }
        } else if (item.fn && (enabled || latent)) {
          const routine: RustRoutine = { kind: "routine", body: item.fn.body, params: parametersOf(item.fn.args),
            scope: captured(scope, false), block: true, asynchronous: code.slice(i, item.index).includes("async") };
          if (enabled && item.name) scope.items.set(item.name, routine);
          definitions.push(routine);
        } else {
          if (enabled && item.name) {
            if (code[item.index] === "macro_rules") scope.macros.add(item.name);
            else scope.items.set(item.name, undefined);
          }
          if (latent && item.opaqueBody !== undefined) opaque.push(code.slice(item.opaqueBody + 1, item.end - 1));
        }
        i = item.end;
        continue;
      }
      const close = groupEnd(code, i);
      i = close > i ? close + 1 : i + 1;
    }
    if (latent) {
      for (const routine of definitions) evaluateRoutine(routine, []);
      for (const body of opaque) block(body, scope);
    }
    return scan(code, 0, code.length, scope, false, skip);
  }

  // 只在表达式可以起头的位置把竖线解释为闭包，不截获位或、逻辑或。
  const expressionPrefix = new Set(["(", "[", "{", ":", "=", "=>", ",", ";", "return", "break", "yield",
    "!", "&", "&&", "*", "..", "..=", "+", "-", "/", "%", "^", "<", ">", "|", "==", "!=", "in", "else", "if"]);
  function startsExpression(code: string[], i: number, start: number) {
    return i === start || expressionPrefix.has(code[i - 1]) ||
      (code[i - 1] === "]" && closingAttribute(code, start, i));
  }

  function closingAttribute(code: string[], start: number, end: number) {
    for (let i = end - 2; i >= start; i--) {
      if (code[i] === "#" && code[i + 1] === "[" && groupEnd(code, i + 1) === end - 1) return true;
    }
    return false;
  }

  function delayedBlock(code: string[], start: number, end: number, scope: RustScope) {
    let i = start;
    const asynchronous = code[i] === "async";
    if (asynchronous) i++;
    const generator = code[i] === "gen";
    if (generator) i++;
    if (!asynchronous && !generator) return;
    if (code[i] === "move") i++;
    if (code[i] !== "{") return;
    const close = groupEnd(code, i);
    if (close <= i || close >= end) return;
    const routine: RustRoutine = { kind: "routine", body: code.slice(i + 1, close), params: [],
      scope: captured(scope, true), block: true, asynchronous: true };
    const driver = generator ? (asynchronous ? "async-iterate" : "iterate") : "await";
    const value: RustBinding = { kind: "pending", routine, args: [], driver };
    if (latent) evaluateRoutine(routine, []);
    return { value, end: close + 1 };
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
    return { end: last + Number(blockBody), value };
  }

  function argumentsOf(code: string[], from: number, end: number, scope: RustScope, observed: boolean,
    limit = Infinity) {
    const args: (RustBinding | undefined)[] = [];
    while (from < end && args.length < limit) {
      // 先识别参数开头的闭包，否则 |a,b| 内部的逗号会截断它。
      const delayed = closure(code, from, end, scope);
      const to = separator(code, delayed?.end ?? from, end, ",");
      if (delayed?.end === to) {
        if (latent) evaluateRoutine(delayed.value, []);
        args.push(delayed.value);
      } else args.push(scan(code, from, to, scope, observed));
      from = to + 1;
    }
    return args;
  }

  // 条件/迭代源本身可以是块表达式，不能把其中的块当成控制体。
  function controlBody(code: string[], from: number, end: number) {
    for (let i = from; i < end; i++) {
      const close = groupEnd(code, i);
      if (close <= i) continue;
      if (code[i] === "{" && i !== from &&
          !["=", "&&", "||", "!", "async", "gen", "move", "const", "unsafe"].includes(code[i - 1]) &&
          ![".", "?", "&&", "||", "==", "!=", "::"].includes(code[close + 1])) return i;
      i = close;
    }
    return end;
  }

  function ifEnd(code: string[], start: number, end: number) {
    let last = groupEnd(code, controlBody(code, start + 1, end));
    while (last > start && code[last + 1] === "else") {
      const other = last + 2;
      const finish = groupEnd(code, code[other] === "if" ? controlBody(code, other + 1, end) : other);
      if (finish <= last) break;
      last = finish;
    }
    return last > start ? last + 1 : end;
  }

  function bracedExpressionEnd(code: string[], start: number, end: number) {
    const token = code[start];
    if (token === "if") return ifEnd(code, start, end);
    const brace = ["match", "for", "while"].includes(token) ? controlBody(code, start + 1, end) :
      token === "{" ? start : ["loop", "unsafe", "const"].includes(token) && code[start + 1] === "{" ? start + 1 : end;
    const close = groupEnd(code, brace);
    return close > brace ? close + 1 : end;
  }

  function conditions(code: string[], from: number, end: number, scope: RustScope, observed: boolean) {
    const inner = childScope(scope);
    while (code[from] === "(" && groupEnd(code, from) === end - 1) { from++; end--; }
    if (end === from + 1 && code[from] === "false") return { inner, truth: false };
    if (end === from + 1 && code[from] === "true") return { inner, truth: true };
    if (code[from] === "false" && code[from + 1] === "&&" && separator(code, from + 2, end, "||") === end) {
      if (latent) scan(code, from + 2, end, scope, observed);
      return { inner, truth: false };
    }
    if (code[from] === "true" && code[from + 1] === "||") {
      if (latent) scan(code, from + 2, end, scope, observed);
      return { inner, truth: true };
    }
    const firstLet = separator(code, from, end, "let");
    if (firstLet === end) {
      scan(code, from, end, scope, observed);
      return { inner, truth: undefined };
    }
    for (let start = from; start < end;) {
      const stop = separator(code, start, end, "&&");
      if (code[start] === "let") {
        const eq = separator(code, start + 1, stop, "=");
        const value = scan(code, eq + 1, stop, inner, observed);
        shadow(inner, patternBindings(code.slice(start + 1, eq)), value);
      } else if (stop === start + 1 && code[start] === "false") {
        return { inner, truth: false };
      } else scan(code, start, stop, inner, observed);
      start = stop + 1;
    }
    return { inner, truth: undefined };
  }

  function initializerElse(code: string[], start: number, end: number) {
    // else paired with a top-level if belongs to the initializer; let-else owns the remaining else.
    let nestedIf = 0;
    for (let i = start; i < end; i++) {
      if (code[i] === "if") nestedIf++;
      if (code[i] === "else") {
        if (!nestedIf) return i;
        nestedIf--;
      }
      const close = groupEnd(code, i);
      if (close > i) i = close;
    }
    return end;
  }

  function expressionEnd(code: string[], start: number, end: number) {
    return Math.min(...[",", ";"].map(t => separator(code, start, end, t)));
  }

  function matchArms(code: string[], from: number, end: number, scope: RustScope, observed: boolean) {
    for (let start = from; start < end;) {
      if (code[start] === ",") { start++; continue; }
      const arrow = separator(code, start, end, "=>");
      if (arrow === end) return;
      const attrsEnd = afterAttributes(code, start);
      const guard = separator(code, attrsEnd, arrow, "if");
      const arm = arrow + 1, braced = bracedExpressionEnd(code, arm, end);
      const delayed = closure(code, arm, end, scope);
      const stop = braced < end && ![".", "?", "(", "["].includes(code[braced]) ?
        braced : separator(code, delayed?.end ?? arm, end, ",");
      if (latent || itemEnabled(code.slice(start, attrsEnd))) {
        const inner = childScope(scope);
        shadow(inner, patternBindings(code.slice(attrsEnd, guard)));
        const condition = guard < arrow ? conditions(code, guard + 1, arrow, inner, observed) : undefined;
        if (latent || condition?.truth !== false) scan(code, arm, stop, condition?.inner ?? inner, observed);
      }
      start = stop;
    }
  }

  function scan(code: string[], start: number, end: number, scope: RustScope, observed = false,
    skip = new Map<number, number>()): RustBinding | undefined {
    let result: RustBinding | undefined, expressionStart = start;
    if (code[start] === "&") return scan(code, start + (code[start + 1] === "mut" ? 2 : 1), end, scope, observed, skip);
    for (let i = start; i < end;) {
      const token = code[i], itemEnd = skip.get(i);
      if (itemEnd !== undefined && itemEnd > i) { i = expressionStart = itemEnd; continue; }
      if (token === ";") { i++; expressionStart = i; continue; }
      if (token === "#" && code[i + 1] === "[") {
        const head = afterAttributes(code, i);
        if (latent || itemEnabled(code.slice(i, head))) {
          if (expressionStart === i) expressionStart = head;
          i = head;
        } else {
          const braced = bracedExpressionEnd(code, head, end);
          i = braced < end && ![".", "?", "(", "["].includes(code[braced]) ?
            braced : expressionEnd(code, head, end) + 1;
          expressionStart = i;
        }
        continue;
      }
      if (token === "let") {
        const last = separator(code, i + 1, end, ";");
        const eq = separator(code, i + 1, last, "=");
        const colon = separator(code, i + 1, eq, ":");
        const pattern = patternBindings(code.slice(i + 1, colon));
        const other = initializerElse(code, eq + 1, last);
        const value = scan(code, eq + 1, other, scope, observed);
        if (other < last) scan(code, other + 1, last, scope, observed);
        shadow(scope, pattern, value);
        i = expressionStart = last + 1;
        continue;
      }
      if (!latent && ((token === "false" && code[i + 1] === "&&") || (token === "true" && code[i + 1] === "||"))) {
        const last = separator(code, i + 2, end, ";");
        // false && A || B still evaluates B; true || A skips the entire remaining disjunction.
        const follow = token === "false" ? separator(code, i + 2, last, "||") : last;
        i = follow + 1;
        continue;
      }
      if (token === "return") return scan(code, i + 1, separator(code, i + 1, end, ";"), scope, observed);
      let value: RustBinding | undefined, next = i + 1;
      const delayed = startsExpression(code, i, start) ?
        delayedBlock(code, i, end, scope) ?? closure(code, i, end, scope) : undefined;
      const brace = ["for", "if", "while", "match"].includes(token) ? controlBody(code, i + 1, end) : end;
      const tail = brace < end ? groupEnd(code, brace) : -1;
      if (tail > brace && tail < end) {
        if (token === "for") {
          const inAt = separator(code, i + 1, brace, "in");
          if (inAt < brace) {
            const iter = scan(code, inAt + 1, brace, scope, observed);
            const asynchronous = code[i + 1] === "await";
            drive(iter, asynchronous ? "async-iterate" : "iterate");
            const inner = childScope(scope);
            shadow(inner, patternBindings(code.slice(i + 1 + Number(asynchronous), inAt)));
            block(code.slice(brace + 1, tail), inner);
          }
        } else if (token === "match") {
          scan(code, i + 1, brace, scope, observed);
          matchArms(code, brace + 1, tail, scope, observed);
        } else {
          const { inner, truth } = conditions(code, i + 1, brace, scope, observed);
          const yes = latent || truth !== false ? block(code.slice(brace + 1, tail), inner) : undefined;
          if (token === "if" && code[tail + 1] === "else") {
            const other = tail + 2;
            next = code[other] === "if" ? ifEnd(code, other, end) : groupEnd(code, other) + 1;
            const no = next > other && (latent || truth !== true) ? scan(code, other, next, scope, observed) : undefined;
            value = truth === true ? yes : truth === false ? no : undefined;
          } else if (token === "if" && truth === true) value = yes;
        }
        next = Math.max(next, tail + 1);
      } else if (delayed) {
        ({ value, end: next } = delayed);
        if (latent && value.kind === "routine") evaluateRoutine(value, []);
      } else if (token === "(" || token === "[" || token === "{") {
        const close = groupEnd(code, i);
        if (close < i || close >= end) break;
        if (token === "{") value = block(code.slice(i + 1, close), scope);
        else {
          const args = argumentsOf(code, i + 1, close, scope, observed);
          if (token === "(" && args.length === 1 && code[close - 1] !== ",") value = args[0];
        }
        next = close + 1;
      } else if ((identifier.test(token) || token === "::") && code[i - 1] !== ".") {
        const { parts, end: after } = pathAt(code, i);
        if (!parts.length) { i++; continue; }
        next = after;
        if (code[next] === "!" && groupEnd(code, next + 1) > next) {
          const close = groupEnd(code, next + 1);
          const name = parts.length === 1 && !localMacro(scope, parts[0]) ? parts[0] : "";
          // 任意宏可以丢弃实参。标准断言只无条件求值谓词/比较项。
          const limit = ["assert", "debug_assert"].includes(name) ? 1 :
            ["assert_eq", "assert_ne", "debug_assert_eq", "debug_assert_ne"].includes(name) ? 2 : 0;
          if (limit && !name.startsWith("debug_")) argumentsOf(code, next + 2, close, scope, observeValues, limit);
          const pin = ["std::pin::pin", "core::pin::pin"].includes(parts.join("::"));
          if (pin) value = argumentsOf(code, next + 2, close, scope, observed, 1)[0];
          next = close + 1;
        } else value = token === "::" ? { kind: "path", path: parts } : lookup(scope, parts);
        if (code[next] === "=" && code[next + 1] !== "=" && parts.length === 1) {
          let layer: RustScope | undefined = scope;
          while (layer && !layer.values.has(parts[0])) layer = layer.parent;
          if (layer) {
            const last = separator(code, next + 1, end, ";");
            layer.values.set(parts[0], scan(code, next + 1, last, scope, observed));
            i = expressionStart = last + 1;
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
          const args = argumentsOf(code, next + 1, close, scope, observed);
          const path = value?.kind === "path" ? value.path.join("::") : "";
          if (["std::pin::Pin::new", "core::pin::Pin::new", "std::boxed::Box::pin", "Box::pin"].includes(path)) value = args[0];
          else if (["std::future::Future::poll", "core::future::Future::poll"].includes(path)) value = drive(args[0], "await");
          else value = invoke(value, args);
          invoked = true;
          next = close + 1;
        } else if (code[next] === "." && identifier.test(code[next + 1] ?? "")) {
          const method = code[next + 1];
          if (method === "await") {
            value = drive(value, "await");
            next += 2;
          } else if ((value?.kind === "pending" || value?.kind === "call-result") &&
              method === "as_mut" && code[next + 2] === "(" && code[next + 3] === ")") {
            next += 4;
          } else if (code[next + 2] === "(" &&
              (method === "poll" && (value?.kind === "call-result" || value?.kind === "pending" && value.driver === "await") ||
               value?.kind === "pending" &&
                 ((value.driver === "iterate" && ["next", "nth", "collect", "count", "last", "fold", "for_each"].includes(method)) ||
                  (value.driver === "async-iterate" && method === "poll_next")))) {
            const close = groupEnd(code, next + 2);
            if (close <= next + 2 || close >= end) break;
            argumentsOf(code, next + 3, close, scope, observed);
            value = drive(value, value?.kind === "pending" ? value.driver : "await");
            next = close + 1;
          } else {
            value = undefined;
            next += 2;
          }
        } else break;
      }
      if (observed && !invoked) note(value, "value");
      if (next === end) result = i === expressionStart ? value : undefined;
      i = next;
    }
    return result;
  }

  const returned = block(body, parameterScope(module, parametersOf(params), []));
  if (driveReturn) drive(returned, "await");
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
    function active(code: string[], enabled = itemEnabled) {
      return [...rustItems(code)].filter(item => enabled(item.prefix));
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
              if (!fn || !substantiveRust(fn.body) ||
                  (!latent && access === "call" && item.prefix.includes("async"))) continue;
              if (inReplacement) found.add(path + ":" + name);
              else for (const ref of rustReferences(importsOf(code, items), fn.body, fn.args, false, itemEnabled, latent,
                access === "drive" && !item.prefix.includes("async"))) {
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
    const testItemEnabled = (prefix: string[]) => enabledRustItem(prefix, features, target, true);
    const registered = rustTestBody(code, name, selector, testItemEnabled);
    const root = checkPath.startsWith("rust/tests/") ? crate : "crate";
    if (!registered || !root) return false;

    // 根中具名封装和重导出明确接线时，只接受它们到达的导出。
    // 只有纯模块公开的接入方式，才从其可公开访问的路径判定。
    const libCode = read(lib), libItems = active(libCode);
    const roots = libItems.flatMap((item): RustReference[] => {
      if (!item.public) return [];
      if (item.kind === "fn") return [{ path: [libCode[item.index + 1]], access: item.prefix.includes("async") ? "drive" : "call" }];
      if (item.kind === "use") return importsOf(libCode, [item]).map(({ alias }) => ({ path: [alias], access: "export" }));
      return [];
    });
    const testReferences = rustReferences(importsOf(registered.module, active(registered.module, testItemEnabled)),
      registered.fn.body, registered.fn.args, true, testItemEnabled)
      .filter(ref => ref.path[0] === root).map(ref => ({ path: ref.path.slice(1), access: ref.access }));
    const drivenWrappers = testReferences.filter(ref => ref.access === "drive" && ref.path.length === 1 &&
      roots.some(candidate => candidate.path[0] === ref.path[0]));
    const production = targets([...roots, ...drivenWrappers], true);
    const moduleOnly = !production.size && !targets(roots, true, true).size;
    const tested = targets(testReferences, root !== "crate");
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
