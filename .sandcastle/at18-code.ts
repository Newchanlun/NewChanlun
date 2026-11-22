import { execFileSync } from "node:child_process";
import { cargoContext, type CargoTarget, enabledRustItem } from "./at18-cargo.ts";
import { type At18Repository, utf8 } from "./at18-source.ts";

// Rust 只做语法与源码接入核验，仍由登记的真实 Cargo 作业提供运行结果。
function tokens(source: string, rust: boolean): string[] {
  const out: string[] = [];
  const quote = rust ? /b?'(?:\\(?:u\{[0-9a-fA-F_]+\}|x[0-9a-fA-F]{2}|[^])|[^'\\\r\n])'/u : /'(?:\\[^]|[^'\\\r\n])*'/;
  const token = new RegExp(/\s+|\/\/[^\r\n]*|\/\*|(?:b?r(#{0,255})"[^]*?"\1)|(?:b|c)?"(?:\\[^]|[^"\\])*"|`(?:\\[^]|[^`\\])*`|/.source +
    quote.source + /|[\w]+|::|->|=>|\.\.=|\.\.|==|!=|\|\||&&|[^]/.source, "gyu");
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
  let signature = index + 2;
  if (code[signature] === "<") {
    const generic = genericEnd(code, signature);
    if (generic < 0) return;
    signature = generic + 1;
  }
  if (code[signature] !== "(") return;
  const argsEnd = closing(code, signature, "(", ")");
  if (argsEnd < 0) return;
  let start = argsEnd + 1;
  for (; start < code.length && !["{", ";", "}"].includes(code[start]); start++) {
    const close = code[start] === "<" ? genericEnd(code, start) : groupEnd(code, start);
    if (close > start) start = close;
  }
  if (code[start] !== "{") return;
  const end = closing(code, start, "{", "}");
  if (end > start) return { body: code.slice(start + 1, end), args: code.slice(signature + 1, argsEnd), end };
}

function substantiveRust(body: string[]) {
  return body.some(t => /[a-zA-Z0-9]/.test(t)) &&
    !body.some((t, i) => ["todo", "unimplemented"].includes(t) && body[i + 1] === "!");
}

function rustTestBody(code: string[], name: string, qualified?: string, enabled = (_prefix: string[]) => true) {
  function* candidates(module: string[], parents: string[]): Generator<{
    fn: NonNullable<ReturnType<typeof rustFunction>>; module: string[]; parents: string[];
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
      if (attrs.includes("#[test]") && !/#\[ignore(?:=|\])/.test(attrs)) yield { fn, module, parents };
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
        (t === "fn" && /(?:^| )pub(?: (?:async|unsafe|const|extern(?: "[^"]*")?))*$/.test(code.slice(start, i).join(" "))) };
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
  { kind: "pending"; routine: RustRoutine; args: (RustBinding | undefined)[]; driver: "await" | "iterate" | "async-iterate" } |
  { kind: "ready"; value?: RustBinding } | { kind: "pending-future" } |
  { kind: "literal"; value: boolean | bigint | string } | RustElements | RustEnum | RustTypeAlias |
  { kind: "constructor"; tag: string; shape: VariantShape; family: RustEnum } |
  { kind: "variant"; tag: string; tuple?: RustElements; fields?: Map<string, RustBinding | undefined> };
type RustElements = { kind: "tuple" | "array"; elements: (RustBinding | undefined)[] };
type VariantShape = { form: "unit" | "record" } | { form: "tuple"; arity: number };
type RustEnum = { kind: "enum"; owner: string; variants: Map<string, VariantShape> };
type AliasParameter = { name: string; fallback?: string[] };
type AliasDefinition = { params: AliasParameter[]; target: string[] };
type RustTypeAlias = { kind: "type-alias"; scope: RustScope } & AliasDefinition;
type EnumArgument = (depth: number) => RustEnum | undefined;
type EnumResolver = (path: string[], args?: EnumArgument[], depth?: number) => RustEnum | undefined;
type RustConstructor = Extract<RustBinding, { kind: "constructor" }>;
type RustTruth = boolean | undefined;
type Driven = { kind: "pending" } | { kind: "ready"; value?: RustBinding };
class RustExit {
  constructor(readonly reason: "return" | "suspended" | "break" | "continue",
    readonly value?: RustBinding, readonly label?: string) {}
}
type RustRoutine = {
  kind: "routine"; body: string[]; params: RustParameter[]; scope: RustScope;
  block: boolean; asynchronous: boolean;
};
type RustScope = {
  parent?: RustScope;
  items: Map<string, RustBinding | undefined>;
  macros: Set<string>;
  values: Map<string, RustBinding | undefined>;
  immutable: Set<string>;
};
type RustParameter = string[];
const rustPathLimit = 32;
class RustPathLimit extends Error {}

type RustTerminal = {
  value: RustBinding | undefined;
  references: Map<string, RustReference>;
};
type RustFlow<T> = {
  fallthrough: T[];
  exits: T[];
  suspended: T[];
};
const identifier = /^[A-Za-z_]\w*$/;
const delimiters: Record<string, string> = { "(": ")", "[": "]", "{": "}" };

function groupEnd(code: string[], i: number) {
  const close = delimiters[code[i]];
  return close ? closing(code, i, code[i], close) : -1;
}

function genericEnd(code: string[], start: number) {
  let depth = 0;
  for (let i = start; i < code.length; i++) {
    if (code[i] === "<") depth++;
    else if (code[i] === ">" && --depth === 0) return i;
    const close = groupEnd(code, i);
    if (close > i) i = close;
  }
  return -1;
}

function nextGroup(code: string[], i: number) {
  return code[i] === "<" && code[i - 1] === "::" ? genericEnd(code, i) : groupEnd(code, i);
}

function separator(code: string[], start: number, end: number, wanted: string) {
  for (let i = start; i < end; i++) {
    if (code[i] === wanted) return i;
    const castEnd = code[i] === "as" ? fnPointerEnd(code, i + 1, end) : i;
    const close = castEnd > i + 1 ? castEnd - 1 : nextGroup(code, i);
    if (close > i) i = close;
  }
  return end;
}

const patternKeywords = new Set(["_", "ref", "mut", "box", "true", "false", "const", "self", "Self",
  "super", "crate"]);
function patternNames(pattern: string[]) {
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
      const end = genericEnd(pattern, i + 1);
      if (end > i) i = end;
      continue;
    }
    if (identifier.test(token) && !patternKeywords.has(token) && pattern[i - 1] !== "::" &&
        ![":", "::", "{", "("].includes(pattern[i + 1])) names.add(token);
  }
  return names;
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
    params.push(code.slice(start, separator(code, start, end, ":")));
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
      const end = genericEnd(code, i + 1);
      if (end >= 0) { i = end + 1; if (code[i] === "::") { i++; continue; } }
    } else if (identifier.test(code[i + 1] ?? "")) {
      i++;
      continue;
    }
    break;
  }
  return { parts, end: i };
}

function typeArguments(code: string[], start: number, end: number): string[][] {
  const args: string[][] = [];
  let from = start;
  for (let i = start; i < end; i++) {
    if (code[i] === ",") { args.push(code.slice(from, i)); from = i + 1; }
    else {
      const close = code[i] === "<" ? genericEnd(code, i) : groupEnd(code, i);
      if (close > i) i = close;
    }
  }
  if (from < end) args.push(code.slice(from, end));
  return args;
}

function aliasDefinition(code: string[], start: number): AliasDefinition | undefined {
  let index = start + 2;
  let params: AliasParameter[] = [];
  if (code[index] === "<") {
    const close = genericEnd(code, index);
    if (close < 0) return;
    params = typeArguments(code, index + 1, close).map(param => {
      const [first, second] = param;
      const name = first === "const" ? second : first === "'" ? "'" + second : first;
      let eq = 0;
      for (; eq < param.length && param[eq] !== "="; eq++) {
        const end = param[eq] === "<" ? genericEnd(param, eq) : groupEnd(param, eq);
        if (end > eq) eq = end;
      }
      return { name, fallback: eq < param.length ? param.slice(eq + 1) : undefined };
    });
    index = close + 1;
  }
  const end = separator(code, index, code.length, ";");
  for (; index < end && code[index] !== "="; index++) {
    const close = code[index] === "<" ? genericEnd(code, index) : groupEnd(code, index);
    if (close > index) index = close;
  }
  if (index + 1 < end) return { params, target: code.slice(index + 1, end) };
}

// 实参保留调用方作用域；别名目标按声明处词法环境解析。
function resolveType(code: string[], resolve: EnumResolver, depth: number,
  parameters = new Map<string, EnumArgument | undefined>()): RustEnum | undefined {
  if (depth > 32) return;
  let index = Number(code[0] === "::");
  const path: string[] = [];
  let args: EnumArgument[] = [];
  while (identifier.test(code[index] ?? "")) {
    path.push(code[index++]);
    if (code[index] === "::" && code[index + 1] === "<") index++;
    if (code[index] === "<") {
      const close = genericEnd(code, index);
      if (close < 0) return;
      args = typeArguments(code, index + 1, close).map(arg => at => resolveType(arg, resolve, at, parameters));
      index = close + 1;
    }
    if (index === code.length || code[index] === "where") {
      if (path.length === 1 && parameters.has(path[0])) return parameters.get(path[0])?.(depth + 1);
      return resolve(path, args, depth + 1);
    }
    if (code[index++] !== "::") return;
    args = [];
  }
}

function resolveAlias({ params, target }: AliasDefinition, resolve: EnumResolver, args: EnumArgument[], depth: number) {
  const parameters = new Map<string, EnumArgument | undefined>();
  for (const [i, { name, fallback }] of params.entries()) {
    // 默认值按声明次序取得前序实参，未声明的名字仍走别名自身的词法作用域。
    const earlier = new Map(parameters);
    parameters.set(name, args[i] ?? (fallback && (at => resolveType(fallback, resolve, at, earlier))));
  }
  return resolveType(target, resolve, depth, parameters);
}

function lookup(scope: RustScope, [first, ...rest]: string[]): RustBinding | undefined {
  if (!first) return;
  for (let layer: RustScope | undefined = scope; layer; layer = layer.parent) {
    const bindings = layer.values.has(first) ? layer.values : layer.items;
    if (!bindings.has(first)) continue;
    const value = bindings.get(first);
    if (!rest.length) return value;
    if (value?.kind === "path") return { kind: "path", path: [...value.path, ...rest] };
    if (value?.kind === "type-alias") return { kind: "path", path: [first, ...rest] };
    if (value?.kind === "enum" && rest.length === 1) return enumConstructor(value, rest[0]);
    return;
  }
  return { kind: "path", path: [first, ...rest] };
}

function literal(code: string[]): Extract<RustBinding, { kind: "literal" }> | undefined {
  if (code.length !== 1 && !(code.length === 2 && code[0] === "-")) return;
  const text = code.join("");
  if (text === "true" || text === "false") return { kind: "literal", value: text === "true" };
  const int = text.match(/^(-?)(0x[0-9a-fA-F_]+|0o[0-7_]+|0b[01_]+|[0-9][0-9_]*)(?:[iu](?:8|16|32|64|128|size))?$/);
  if (int) {
    const digits = int[2].replaceAll("_", "");
    if (/^0[xob]$/.test(digits)) return;
    return { kind: "literal", value: BigInt(digits) * (int[1] ? -1n : 1n) };
  }
  const raw = text.match(/^r(#{0,255})"([^]*)"\1$/);
  if (raw) return { kind: "literal", value: raw[2] };
  if (!text.startsWith('"') && !text.startsWith("'")) return;
  if (text.length < 2 || text[0] !== text.at(-1)) return;
  const escapes = new Map([["n", "\n"], ["r", "\r"], ["t", "\t"], ["0", "\0"], ["\\", "\\"], ['"', '"'], ["'", "'"]]);
  let valid = true;
  const value = text.slice(1, -1).replace(/\\(?:u\{[\da-fA-F_]+\}|x[\da-fA-F]{2}|[^])/g, escape => {
    const ordinary = escapes.get(escape[1]);
    if (ordinary !== undefined) return ordinary;
    if (escape.length > 2) {
      const point = Number.parseInt((escape[1] === "u" ? escape.slice(3, -1) : escape.slice(2)).replaceAll("_", ""), 16);
      if (point <= 0x10ffff && !(point >= 0xd800 && point <= 0xdfff)) return String.fromCodePoint(point);
    }
    valid = false;
    return "";
  });
  if (valid) return { kind: "literal", value };
}

function enumConstructor(definition: RustEnum, name: string): RustConstructor | undefined {
  const shape = definition.variants.get(name);
  if (shape) return { kind: "constructor", tag: definition.owner + "::" + name, shape, family: definition };
}

const optionVariants: RustEnum = { kind: "enum", owner: "prelude::Option",
  variants: new Map<string, VariantShape>([["Some", { form: "tuple", arity: 1 }], ["None", { form: "unit" }]]) };
const resultVariants: RustEnum = { kind: "enum", owner: "prelude::Result",
  variants: new Map<string, VariantShape>([["Ok", { form: "tuple", arity: 1 }], ["Err", { form: "tuple", arity: 1 }]]) };
const pollVariants: RustEnum = { kind: "enum", owner: "core::task::Poll",
  variants: new Map<string, VariantShape>([["Ready", { form: "tuple", arity: 1 }], ["Pending", { form: "unit" }]]) };

function builtinEnum(path: string[]): RustEnum | undefined {
  const owner = path.at(-1);
  const qualifiers = path.slice(0, -1).join("::");
  if (owner === "Poll" && (!qualifiers || qualifiers === "std::task" || qualifiers === "core::task")) return pollVariants;
  if (owner !== "Option" && owner !== "Result") return;
  if (!qualifiers || ["std", "core"].some(root => qualifiers === `${root}::${owner.toLowerCase()}`)) {
    return owner === "Option" ? optionVariants : resultVariants;
  }
}

function builtinConstructor(path: string[]): RustConstructor | undefined {
  const name = path.at(-1);
  if (!name) return;
  const family = path.length === 1 ?
    optionVariants.variants.has(name) ? optionVariants : resultVariants : builtinEnum(path.slice(0, -1));
  return family && enumConstructor(family, name);
}

function enumDefinition(code: string[], start: number, end: number, owner: string,
  enabled: (prefix: string[]) => boolean): RustEnum {
  const variants = new Map<string, VariantShape>();
  for (const field of splitAt(code.slice(start + 1, end), ",")) {
    let i = 0;
    while (field[i] === "#" && field[i + 1] === "[") {
      const close = groupEnd(field, i + 1);
      if (close < 0) break;
      i = close + 1;
    }
    if (enabled(field.slice(0, i)) && identifier.test(field[i] ?? "")) {
      const args = field[i + 1];
      if (args === "(") {
        // 字段类型内部的泛型逗号不分隔字段。
        const arity = parametersOf(field.slice(i + 2, groupEnd(field, i + 1))).length;
        variants.set(field[i], { form: "tuple", arity });
      } else variants.set(field[i], { form: args === "{" ? "record" : "unit" });
    }
  }
  return { kind: "enum", owner, variants };
}

function splitAt(code: string[], delimiter: string) {
  const parts: string[][] = [];
  for (let i = 0; i < code.length;) {
    const end = separator(code, i, code.length, delimiter);
    parts.push(code.slice(i, end));
    i = end + 1;
  }
  return parts;
}

type RustMatch = {
  truth: true | undefined;
  bindings: Map<string, RustBinding | undefined>;
};

function rustPattern(pattern: string[], value: RustBinding | undefined, scope: RustScope,
  constructorOf: (value: RustBinding | undefined, scope: RustScope) => RustConstructor | undefined): RustMatch[] {
  const one = (truth: RustTruth, bindings = new Map<string, RustBinding | undefined>()): RustMatch[] =>
    truth === false ? [] : [{ truth, bindings }];
  function cartesian(parts: RustMatch[][]) {
    let matches = one(true);
    for (const part of parts) {
      if (matches.length * part.length > rustPathLimit) throw new RustPathLimit();
      matches = matches.flatMap(left => part.map(right => ({
        truth: left.truth && right.truth,
        bindings: new Map([...left.bindings, ...right.bindings]),
      })));
    }
    return matches;
  }
  const maybe = (matches: RustMatch[], exact: boolean) =>
    exact ? matches : matches.map(result => ({ ...result, truth: undefined }));

  function match(pat: string[], member: RustBinding | undefined): RustMatch[] {
    const ors = splitAt(pat, "|");
    if (ors.length > 1 || pat[0] === "|") {
      const results = ors.filter(part => part.length).flatMap(part => match(part, member));
      if (results.length > rustPathLimit) throw new RustPathLimit();
      return results;
    }
    const at = separator(pat, 0, pat.length, "@");
    if (at < pat.length) return cartesian([match(pat.slice(0, at), member), match(pat.slice(at + 1), member)]);
    if (pat.length === 1 && pat[0] === "_") return one(true);
    const expected = literal(pat);
    if (expected) return one(member?.kind === "literal" ? expected.value === member.value : undefined);
    const { parts, end } = pathAt(pat, 0);
    const ctor = constructorOf(lookup(scope, parts), scope);
    if (ctor) {
      const variant = member?.kind === "variant" ? member : undefined;
      if (variant && variant.tag !== ctor.tag) return [];
      if (ctor.shape.form === "unit" && end === pat.length) return one(variant ? true : undefined);
      if (ctor.shape.form === "tuple" && pat[end] === "(" && groupEnd(pat, end) === pat.length - 1) {
        return maybe(matchElements(splitAt(pat.slice(end + 1, -1), ","), variant?.tuple?.elements), !!variant);
      }
      if (ctor.shape.form === "record" && pat[end] === "{" && groupEnd(pat, end) === pat.length - 1) {
        const fields = splitAt(pat.slice(end + 1, -1), ",").filter(field => field[0] !== "..");
        return maybe(cartesian(fields.map(field => {
          const colon = separator(field, 0, field.length, ":");
          return match(colon < field.length ? field.slice(colon + 1) : field, variant?.fields?.get(field[colon - 1]));
        })), !!variant);
      }
    }
    if (["(", "["].includes(pat[0]) && groupEnd(pat, 0) === pat.length - 1) {
      const inner = pat.slice(1, -1), fields = splitAt(inner, ",");
      if (pat[0] === "(" && fields.length === 1 && fields[0].length === inner.length) return match(inner, member);
      const kind = pat[0] === "(" ? "tuple" : "array";
      return matchElements(fields, member?.kind === kind ? member.elements : undefined);
    }
    const binding = pat.findIndex(token => token !== "ref" && token !== "mut");
    const name = binding === pat.length - 1 ? pat[binding] : "";
    if (identifier.test(name) && !patternKeywords.has(name) && !/^[A-Z]/.test(name)) {
      return one(true, new Map([[name, member]]));
    }
    return one(undefined);
  }
  function matchElements(fields: string[][], elements: RustElements["elements"] | undefined): RustMatch[] {
    const rest = fields.findIndex(field => field.length === 1 && field[0] === "..");
    if (elements && (rest < 0 ? elements.length !== fields.length : elements.length < fields.length - 1)) return [];
    const matched = cartesian(fields.flatMap((field, index) => index === rest ? [] : [match(field,
      elements?.[rest >= 0 && index > rest ? elements.length - fields.length + index : index])]));
    return maybe(matched, !!elements);
  }
  return match(pattern, value);
}

function fnPointerEnd(code: string[], start: number, end: number) {
  let i = start;
  if (code[i] === "for" && code[i + 1] === "<") {
    const binder = genericEnd(code, i + 1);
    if (binder < 0 || binder >= end) return start;
    i = binder + 1;
  }
  if (code[i] === "unsafe") i++;
  if (code[i] === "extern") {
    i++;
    if (code[i]?.startsWith('"')) i++;
  }
  if (code[i] !== "fn" || code[i + 1] !== "(") return start;
  const close = groupEnd(code, i + 1);
  if (close < 0 || close >= end) return start;
  i = close + 1;
  if (code[i] !== "->") return i;
  i++;
  while (code[i] === "&" || code[i] === "*" || code[i] === "'" ||
      code[i] === "mut" || code[i] === "const") {
    i += code[i] === "'" ? 2 : 1;
  }
  if (code[i] === "!" || code[i] === "_") return i + 1;
  const group = groupEnd(code, i);
  if (group > i) return group + 1;
  i = pathAt(code, i).end;
  if (code[i] === "<") {
    const generic = genericEnd(code, i);
    if (generic > i) i = generic + 1;
  }
  return i;
}

function captured(scope: RustScope, includeValues: boolean): RustScope {
  return {
    parent: scope.parent && captured(scope.parent, includeValues),
    items: scope.items,
    macros: scope.macros,
    values: includeValues ? new Map(scope.values) : new Map(),
    immutable: includeValues ? new Set(scope.immutable) : new Set(),
  };
}

// 绑定回答“这个名字是什么”；执行遍历回答“此处是否调用它”。
// 生产接线另查未执行的具名引用，防止把空封装误降级成纯模块公开。
function rustReferences(imports: ReturnType<typeof rustImports>, body: string[], params: string[],
  observeValues: boolean, itemEnabled: (prefix: string[]) => boolean, latent = false, driveReturn = false,
  moduleEnum: EnumResolver = () => undefined): RustReference[][] {
  const module: RustScope = {
    items: new Map(imports.map(({ alias, path }) => [alias, { kind: "path", path }])),
    macros: new Set(),
    values: new Map(),
    immutable: new Set(),
  };
  const running = new Set<string[]>();
  let localEnum = 0;
  let refs = new Map<string, RustReference>();
  const pendingPaths: number[][] = [[]];
  let path: number[] = [], cursor = 0, pathCount = 1;

  // 按决策前缀重放同一求值器，不复制捕获的作用域或把不同路径的值混成一个。
  // 一条路径上，只有正常结果会继续扫描；return 与挂起沿当前调用栈传播到所属边界。
  function selectPath<T>(choices: readonly T[]): T {
    if (choices.length === 1) return choices[0];
    if (!choices.length) throw new RustPathLimit();
    const index = cursor++;
    if (index < path.length) return choices[path[index]];
    pathCount += choices.length - 1;
    // 未枚举的分支不能被当成已经验证的执行路径。
    if (pathCount > rustPathLimit) throw new RustPathLimit();
    for (let i = choices.length - 1; i > 0; i--) pendingPaths.push([...path, i]);
    path.push(0);
    return choices[0];
  }

  function decide(truth: RustTruth) {
    return truth ?? selectPath([false, true]);
  }

  function recordReference(path: string[], access: RustAccess) {
    const key = access + ":" + path.join("::");
    if (!refs.has(key)) refs.set(key, { path, access });
  }
  function resolveEnum(scope: RustScope, path: string[], args: EnumArgument[] = [], depth = 0): RustEnum | undefined {
    if (depth > 32) return;
    if (path.length === 1) {
      for (let layer: RustScope | undefined = scope; layer; layer = layer.parent) {
        if (!layer.items.has(path[0])) continue;
        const value = layer.items.get(path[0]);
        if (value?.kind === "enum") return value;
        if (value?.kind === "path") return moduleEnum(value.path, args, depth + 1) ?? builtinEnum(value.path);
        if (value?.kind !== "type-alias") return;
        return resolveAlias(value, (named, actual, at) => resolveEnum(value.scope, named, actual, at), args, depth + 1);
      }
    }
    return moduleEnum(path, args, depth + 1) ?? builtinEnum(path);
  }

  function constructorOf(value: RustBinding | undefined, scope: RustScope): RustConstructor | undefined {
    if (value?.kind === "constructor") return value;
    if (value?.kind !== "path") return;
    const path = value.path, name = path.at(-1);
    if (!name) return;
    if (path.length > 1) {
      const definition = resolveEnum(scope, path.slice(0, -1));
      if (definition) return enumConstructor(definition, name);
      return;
    }
    return builtinConstructor(path);
  }
  const childScope = (parent: RustScope): RustScope =>
    ({ parent, items: new Map(), macros: new Set(), values: new Map(), immutable: new Set() });

  function localMacro(scope: RustScope | undefined, name: string): boolean {
    for (; scope; scope = scope.parent) if (scope.macros.has(name)) return true;
    return false;
  }
  function bindMatch(scope: RustScope, pattern: RustParameter, matched?: RustMatch) {
    for (const name of patternNames(pattern)) {
      // 单元变体（如 None 或经 use 导入的别名）不是新的局部名。
      if (!constructorOf(lookup(scope, [name]), scope)) {
        scope.values.set(name, matched?.bindings.get(name));
        scope.immutable.delete(name);
      }
    }
  }

  function bind(scope: RustScope, pattern: RustParameter, value?: RustBinding) {
    const matches = rustPattern(pattern, value, scope, constructorOf);
    const selected = latent ? matches[0] : matches.find(match => decide(match.truth));
    bindMatch(scope, pattern, selected);
    return selected ? latent ? selected.truth : true : false;
  }

  function ifBranch(truth: RustTruth, condition: string[], scope: RustScope) {
    if (truth !== undefined) return truth;
    let start = 0, end = condition.length, inverted = false;
    while (start < end) {
      if (condition[start] === "!") { inverted = !inverted; start++; }
      else if (condition[start] === "(" && groupEnd(condition, start) === end - 1) { start++; end--; }
      else break;
    }
    const name = condition[start];
    const chosen = decide(undefined);
    if (end === start + 1 && identifier.test(name ?? "")) {
      for (let layer: RustScope | undefined = scope; layer; layer = layer.parent) {
        if (!layer.values.has(name)) continue;
        if (layer.immutable.has(name)) layer.values.set(name, boolean(chosen !== inverted));
        break;
      }
    }
    return chosen;
  }

  function outcome(run: () => RustBinding | undefined) {
    try { return { value: run(), exit: undefined }; }
    catch (error) {
      if (error instanceof RustExit) return { value: error.value, exit: error.reason };
      throw error;
    }
  }

  function possible(run: () => RustBinding | undefined) {
    return outcome(run).value;
  }

  function sameValue(a: RustBinding | undefined, b: RustBinding | undefined): boolean {
    if (a === b) return true;
    if (!a || !b) return false;
    if (a.kind === "literal") return b.kind === a.kind && a.value === b.value;
    if (a.kind === "path" || a.kind === "call-result") return b.kind === a.kind && a.path.join("::") === b.path.join("::");
    if (a.kind === "tuple" || a.kind === "array") return b.kind === a.kind && a.elements.length === b.elements.length &&
      a.elements.every((element, i) => sameValue(element, b.elements[i]));
    if (a.kind === "ready") return b.kind === "ready" && sameValue(a.value, b.value);
    if (a.kind === "variant") return b.kind === "variant" && a.tag === b.tag && sameValue(a.tuple, b.tuple) &&
      a.fields?.size === b.fields?.size && [...(a.fields ?? [])].every(([key, value]) =>
        b.fields?.has(key) && sameValue(value, b.fields.get(key)));
    return a.kind === "constructor" && b.kind === a.kind && a.tag === b.tag;
  }

  function branch(...runs: (() => RustBinding | undefined)[]): RustBinding | undefined {
    if (latent) {
      for (const run of runs) possible(run);
      return;
    }
    return selectPath(runs)();
  }

  function sameBindings(a: Map<string, RustBinding | undefined>, b: Map<string, RustBinding | undefined>) {
    return a.size === b.size && [...a].every(([name, value]) => b.has(name) && sameValue(value, b.get(name)));
  }

  function scopeSnapshot(scope: RustScope): Map<string, RustBinding | undefined>[] {
    const layers: Map<string, RustBinding | undefined>[] = [];
    for (let layer: RustScope | undefined = scope; layer; layer = layer.parent) layers.push(new Map(layer.values));
    return layers;
  }

  function unchanged(scope: RustScope, snapshot: Map<string, RustBinding | undefined>[]) {
    return scopeSnapshot(scope).every((values, i) => sameBindings(values, snapshot[i]));
  }

  function parameterScope(parent: RustScope, params: RustParameter[], args: (RustBinding | undefined)[]): RustScope {
    const scope = childScope(parent);
    params.forEach((pattern, i) => bind(scope, pattern, args[i]));
    return scope;
  }
  const note = (value: RustBinding | undefined, access: RustAccess) => {
    if (value?.kind === "path") recordReference(value.path, access);
  };

  function evaluateRoutine(routine: RustRoutine, args: (RustBinding | undefined)[]) {
    if (running.has(routine.body)) return { value: undefined, exit: undefined };
    running.add(routine.body);
    try {
      const scope = parameterScope(routine.scope, routine.params, args);
      return outcome(() => routine.block ? block(routine.body, scope) :
        scan(routine.body, 0, routine.body.length, scope));
    } finally {
      running.delete(routine.body);
    }
  }

  function invoke(value: RustBinding | undefined, args: (RustBinding | undefined)[]): RustBinding | undefined {
    if (value?.kind === "routine") {
      if (value.asynchronous) return { kind: "pending", routine: value, args, driver: "await" };
      return evaluateRoutine(value, args).value;
    }
    if (value?.kind === "path") {
      note(value, "call");
      if (["std::future::pending", "core::future::pending", "future::pending"].includes(value.path.join("::"))) {
        return { kind: "pending-future" };
      }
      if (["std::future::ready", "core::future::ready", "future::ready"].includes(value.path.join("::"))) {
        return { kind: "ready", value: args[0] };
      }
      return { kind: "call-result", path: value.path };
    }
    if (value?.kind === "constructor" && value.shape.form === "tuple") {
      return { kind: "variant", tag: value.tag, tuple: { kind: "tuple", elements: args } };
    }
  }

  function drive(value: RustBinding | undefined, driver: "await" | "iterate" | "async-iterate"): Driven | undefined {
    if (value?.kind === "ready" && driver === "await") return { kind: "ready", value: value.value };
    if (value?.kind === "pending-future" && driver === "await") return { kind: "pending" };
    if (value?.kind === "pending" && value.driver === driver) {
      const result = evaluateRoutine(value.routine, value.args);
      return result.exit === "suspended" ? { kind: "pending" } : { kind: "ready", value: result.value };
    }
    if (value?.kind === "call-result" && driver === "await") recordReference(value.path, "drive");
  }

  function poll(value: RustBinding | undefined): RustBinding | undefined {
    const result = drive(value, "await");
    if (result?.kind === "pending") return { kind: "variant", tag: pollVariants.owner + "::Pending" };
    if (result?.kind === "ready") {
      return { kind: "variant", tag: pollVariants.owner + "::Ready",
        tuple: { kind: "tuple", elements: [result.value] } };
    }
  }

  function awaitValue(value: RustBinding | undefined) {
    const result = drive(value, "await");
    if (!latent && (result?.kind === "pending" ||
        (value === undefined || value.kind === "call-result" || value.kind === "path") && decide(undefined))) {
      throw new RustExit("suspended");
    }
    if (result?.kind === "ready") return result.value;
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
            else if (code[item.index] === "enum" && item.opaqueBody !== undefined) {
              scope.items.set(item.name, enumDefinition(code, item.opaqueBody, item.end - 1,
                `block:${localEnum++}:${item.name}`, itemEnabled));
            } else if (code[item.index] === "type") {
              const alias = aliasDefinition(code, item.index);
              scope.items.set(item.name, alias ? { kind: "type-alias", ...alias, scope: captured(scope, false) } : undefined);
            } else scope.items.set(item.name, undefined);
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
      for (const body of opaque) possible(() => block(body, scope));
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

  function delayedBlockStart(code: string[], start: number) {
    return code[start] === "async" || code[start] === "gen";
  }

  function closureStart(code: string[], start: number) {
    const token = code[code[start] === "move" ? start + 1 : start];
    return token === "|" || token === "||";
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
          ![".", "?", "&&", "||", "==", "!=", "::", "="].includes(code[close + 1])) return i;
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

  function labelAt(code: string[], start: number) {
    if (code[start] === "'" && identifier.test(code[start + 1] ?? "")) return code[start + 1];
  }

  function bracedExpressionEnd(code: string[], start: number, end: number) {
    if (labelAt(code, start) && code[start + 2] === ":") start += 3;
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
    const firstLet = separator(code, from, end, "let");
    if (firstLet === end) {
      const value = scan(code, from, end, scope, observed);
      return { inner, truth: value?.kind === "literal" && typeof value.value === "boolean" ? value.value : undefined };
    }
    let truth: RustTruth = true;
    for (let start = from; start < end;) {
      const stop = separator(code, start, end, "&&");
      const evaluate = (): RustBinding | undefined => {
        if (code[start] === "let") {
          const eq = separator(code, start + 1, stop, "=");
          const value = scan(code, eq + 1, stop, inner, observed);
          return boolean(bind(inner, code.slice(start + 1, eq), value));
        }
        return scan(code, start, stop, inner, observed);
      };
      const part = flag(evaluate());
      if (latent ? part === false : !decide(part)) return { inner, truth: false };
      if (part === undefined && latent) truth = undefined;
      start = stop + 1;
    }
    return { inner, truth };
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

  function flag(value: RustBinding | undefined): RustTruth {
    return value?.kind === "literal" && typeof value.value === "boolean" ? value.value : undefined;
  }

  function boolean(value: RustTruth): RustBinding | undefined {
    return value === undefined ? undefined : { kind: "literal", value };
  }

  function operator(code: string[], start: number, end: number, operators: string[]) {
    let found: { i: number; op: string; width: number } | undefined;
    for (let i = start; i < end; i++) {
      const cast = code[i] === "as" ? fnPointerEnd(code, i + 1, end) : i;
      const close = cast > i + 1 ? cast - 1 : nextGroup(code, i);
      if (close > i) { i = close; continue; }
      const pair = (code[i] === "<" || code[i] === ">") && code[i + 1] === "=";
      const op = pair ? code[i] + "=" : code[i];
      if (i > start && i + (pair ? 2 : 1) < end && operators.includes(op)) found = { i, op, width: pair ? 2 : 1 };
      if (pair) i++;
    }
    return found;
  }

  function computed(code: string[], start: number, end: number, scope: RustScope, observed: boolean) {
    const binary = operator(code, start, end, ["||"]) ?? operator(code, start, end, ["&&"]) ??
      operator(code, start, end, ["==", "!=", "<", "<=", ">", ">="]);
    if (!binary) {
      if (code[start] !== "!") return;
      const rhs = flag(scan(code, start + 1, end, scope, observed));
      return { value: boolean(rhs === undefined ? undefined : !rhs) };
    }
    const left = scan(code, start, binary.i, scope, observed);
    const right = () => scan(code, binary.i + binary.width, end, scope, observed);
    if (binary.op === "||" || binary.op === "&&") {
      const lhs = flag(left), stop = binary.op === "||";
      if (lhs === stop) {
        if (latent) possible(right);
        return { value: boolean(stop) };
      }
      if (latent || (lhs ?? decide(undefined)) !== stop) return { value: boolean(flag(right())) };
      return { value: boolean(stop) };
    }
    const target = right();
    if (left?.kind !== "literal" || target?.kind !== "literal" || typeof left.value !== typeof target.value) {
      return { value: undefined };
    }
    const a = left.value, b = target.value;
    const ordering = typeof a === "string" && typeof b === "string" ? Buffer.compare(Buffer.from(a), Buffer.from(b)) :
      a === b ? 0 : a < b ? -1 : 1;
    const relation = binary.op === "==" ? ordering === 0 : binary.op === "!=" ? ordering !== 0 :
      binary.op === "<" ? ordering < 0 : binary.op === "<=" ? ordering <= 0 :
      binary.op === ">" ? ordering > 0 : ordering >= 0;
    return { value: boolean(relation) };
  }

  function matchArms(code: string[], from: number, end: number, scope: RustScope, observed: boolean,
    scrutinee: RustBinding | undefined): RustBinding | undefined {
    const arms: { pattern: string[]; guard: number; arrow: number; arm: number; stop: number }[] = [];
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
      if (latent || itemEnabled(code.slice(start, attrsEnd))) arms.push({ pattern: code.slice(attrsEnd, guard), guard, arrow, arm, stop });
      start = stop;
    }

    function select(value: RustBinding | undefined): RustBinding | undefined {
      for (const { pattern, guard, arrow, arm, stop } of arms) {
        const matches = rustPattern(pattern, value, scope, constructorOf);
        // guard.next：结构匹配不结束搜索；守卫不成立时在同一臂试下一个绑定。
        for (const matched of latent && !matches.length ? [undefined] : matches) {
          if (!latent && !decide(matched?.truth)) continue;
          const inner = childScope(scope);
          bindMatch(inner, pattern, matched);
          const condition = guard < arrow ? conditions(code, guard + 1, arrow, inner, observed) : undefined;
          const run = () => scan(code, arm, stop, condition?.inner ?? inner, observed);
          if (latent) possible(run);
          else if (!condition || decide(condition.truth)) return run();
        }
      }
    }
    if (!latent && (scrutinee === undefined || scrutinee.kind === "path" || scrutinee.kind === "call-result")) {
      const values = partition();
      if (values.length) return select(selectPath(values));
    }
    return select(scrutinee);

    function partition(): RustBinding[] {
      const unguarded = arms.flatMap(({ pattern, guard, arrow }) => guard === arrow ? [pattern] : []);
      const choices = unguarded.flatMap(pattern => splitAt(pattern, "|").filter(part => part.length));
      if (["true", "false"].every(token => choices.some(part => part.length === 1 && part[0] === token))) {
        return [{ kind: "literal", value: true }, { kind: "literal", value: false }];
      }
      // 只用不带守卫且不依赖载荷值的模式证明枚举穷尽，例如 Some(_) / None。
      const family = choices.map(pattern => constructorOf(lookup(scope, pathAt(pattern, 0).parts), scope)?.family)
        .find(definition => definition !== undefined);
      if (!family) return [];
      const values: RustBinding[] = [];
      for (const [name, shape] of family.variants) {
        const tag = family.owner + "::" + name;
        const value: RustBinding = shape.form === "tuple" ?
          { kind: "variant", tag, tuple: { kind: "tuple", elements: Array<RustBinding | undefined>(shape.arity).fill(undefined) } } :
          { kind: "variant", tag };
        if (!unguarded.some(pattern => rustPattern(pattern, value, scope, constructorOf).some(match => match.truth))) return [];
        values.push(value);
      }
      return values;
    }
  }

  function loopBody(run: () => RustBinding | undefined, label?: string) {
    try { run(); }
    catch (error) {
      if (error instanceof RustExit && (error.label === undefined || error.label === label)) {
        if (error.reason === "break") return error;
        if (error.reason === "continue") return;
      }
      throw error;
    }
  }

  function scan(code: string[], start: number, end: number, scope: RustScope, observed = false,
    skip = new Map<number, number>()): RustBinding | undefined {
    let result: RustBinding | undefined, expressionStart = start;
    if (code[start] === "&") return scan(code, start + (code[start + 1] === "mut" ? 2 : 1), end, scope, observed, skip);
    for (let i = start; i < end;) {
      const label = code[i + 2] === ":" ? labelAt(code, i) : undefined;
      if (label) {
        if (i === expressionStart) expressionStart += 3;
        i += 3;
      }
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
        const pattern = code.slice(i + 1, colon);
        const other = initializerElse(code, eq + 1, last);
        const value = scan(code, eq + 1, other, scope, observed);
        if (other < last) {
          const matches = rustPattern(pattern, value, scope, constructorOf);
          const matched = latent ? matches[0] : matches.find(match => decide(match.truth));
          const otherwise = () => scan(code, other + 1, last, scope, observed);
          if (latent) possible(otherwise);
          else if (!matched) {
            otherwise();
            throw new RustExit("return");
          }
          bindMatch(scope, pattern, matched);
        } else {
          bind(scope, pattern, value);
        }
        if (pattern.length === 1 && scope.values.has(pattern[0])) scope.immutable.add(pattern[0]);
        i = expressionStart = last + 1;
        continue;
      }
      if (token === "return" || token === "break" || token === "continue") {
        const destination = token === "return" ? undefined : labelAt(code, i + 1);
        const from = i + (destination ? 3 : 1);
        throw new RustExit(token, scan(code, from, separator(code, from, end, ";"), scope, observed), destination);
      }
      if (i === expressionStart && !["if", "match", "while", "for", "loop", "yield"].includes(token) &&
          !delayedBlockStart(code, i) && !closureStart(code, i)) {
        const last = expressionEnd(code, i, end);
        const assignment = separator(code, i, last, "=");
        if (assignment === last || ["<", ">"].includes(code[assignment - 1])) {
          const calculation = computed(code, i, last, scope, observed);
          if (calculation) {
            if (last === end) return calculation.value;
            i = last;
            continue;
          }
        }
      }
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
            const pattern = code.slice(i + 1 + Number(asynchronous), inAt);
            const iterate = (member?: RustBinding) => {
              const inner = childScope(scope);
              bind(inner, pattern, member);
              return loopBody(() => block(code.slice(brace + 1, tail), inner), label);
            };
            if (latent) possible(() => { iterate(); });
            else if (iter?.kind === "array") {
              for (const member of iter.elements) if (iterate(member)) break;
            } else {
              // 未知长度必须包括空迭代；状态回到同一个循环头后，后续各分支
              // 已在更短的路径覆盖（重复已有调用不会增加必达集合）。
              for (let iterations = 0; decide(undefined); iterations++) {
                if (iterations >= 64) throw new RustPathLimit();
                const before = scopeSnapshot(scope);
                if (iterate() || unchanged(scope, before)) break;
              }
            }
          }
        } else if (token === "match") {
          const scrutinee = scan(code, i + 1, brace, scope, observed);
          value = matchArms(code, brace + 1, tail, scope, observed, scrutinee);
        } else {
          const condition = () => conditions(code, i + 1, brace, scope, observed);
          const then = (inner: RustScope) => block(code.slice(brace + 1, tail), inner);
          if (token === "while") {
            if (latent) possible(() => { loopBody(() => then(condition().inner), label); });
            else {
              for (let iterations = 0;; iterations++) {
                const before = scopeSnapshot(scope);
                const { inner, truth } = condition();
                if (!decide(truth) || loopBody(() => then(inner), label)) break;
                // 同一循环头的退出/返回已在更短路径被枚举。保留不退出的路径，
                // 不把无限循环后的语句记为已执行。
                if (unchanged(scope, before) || iterations >= 63) throw new RustExit("suspended");
              }
            }
          } else {
            const { inner, truth } = condition();
            const other = tail + 2;
            if (code[tail + 1] === "else") {
              next = code[other] === "if" ? ifEnd(code, other, end) : groupEnd(code, other) + 1;
            }
            const no = () => next > other ? scan(code, other, next, scope, observed) : undefined;
            value = latent ? branch(() => then(inner), no) :
              ifBranch(truth, code.slice(i + 1, brace), scope) ? then(inner) : no();
          }
        }
        next = Math.max(next, tail + 1);
      } else if (token === "loop" && code[i + 1] === "{" && groupEnd(code, i + 1) < end) {
        const close = groupEnd(code, i + 1);
        const iteration = () => loopBody(() => block(code.slice(i + 2, close), scope), label);
        next = close + 1;
        if (latent) possible(() => iteration()?.value);
        else {
          for (let iterations = 0;; iterations++) {
            const before = scopeSnapshot(scope), stopped = iteration();
            if (stopped) { value = stopped.value; break; }
            if (unchanged(scope, before) || iterations >= 63) throw new RustExit("suspended");
          }
        }
      } else if (delayed) {
        ({ value, end: next } = delayed);
        if (latent && value.kind === "routine") evaluateRoutine(value, []);
      } else if (token === "(" || token === "[" || token === "{") {
        const close = groupEnd(code, i);
        if (close < i || close >= end) break;
        if (token === "{") {
          try { value = block(code.slice(i + 1, close), scope); }
          catch (error) {
            if (!label || !(error instanceof RustExit) || error.reason !== "break" || error.label !== label) throw error;
            value = error.value;
          }
        } else if (token === "[" && separator(code, i + 1, close, ";") < close) {
          // 重复数组不是逐项列表；扫描元素求值，但不从语法推定长度。
          scan(code, i + 1, close, scope, observed);
        } else {
          const args = argumentsOf(code, i + 1, close, scope, observed);
          value = token === "(" && args.length === 1 && code[close - 1] !== "," ? args[0] :
            { kind: token === "(" ? "tuple" : "array", elements: args };
        }
        next = close + 1;
      } else if ((value = literal(code.slice(i, token === "-" ? i + 2 : i + 1)))) {
        if (token === "-") next++;
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
        } else {
          value = token === "::" ? { kind: "path", path: parts } : lookup(scope, parts);
          const ctor = constructorOf(value, scope);
          if (ctor) value = ctor.shape.form === "unit" ? { kind: "variant", tag: ctor.tag } : ctor;
        }
        if (code[next] === "=" && code[next + 1] !== "=" && parts.length === 1) {
          let layer: RustScope | undefined = scope;
          while (layer && !layer.values.has(parts[0])) layer = layer.parent;
          if (layer) {
            const last = separator(code, next + 1, end, ";");
            layer.values.set(parts[0], scan(code, next + 1, last, scope, observed));
            layer.immutable.delete(parts[0]);
            i = expressionStart = last + 1;
            continue;
          }
        }
        if (latent && code[next] === "(") note(lookup(module, parts), "call");
        if (["if", "while", "for", "match", "loop", "else", "as", "in"].includes(token)) value = undefined;
      }
      let invoked = false;
      for (; next < end;) {
        if (code[next] === "as") {
          const afterType = fnPointerEnd(code, next + 1, end);
          if (afterType <= next + 1) break;
          next = afterType;
        } else if (code[next] === "{" && value?.kind === "constructor" && value.shape.form === "record") {
          const close = groupEnd(code, next);
          if (close < next || close >= end) break;
          const fields = new Map<string, RustBinding | undefined>();
          for (const field of splitAt(code.slice(next + 1, close), ",")) {
            const colon = separator(field, 0, field.length, ":");
            if (field[0] === "..") {
              const base = scan(field, 1, field.length, scope, observed);
              if (base?.kind === "variant" && base.tag === value.tag) {
                for (const [name, member] of base.fields ?? []) if (!fields.has(name)) fields.set(name, member);
              }
            } else if (identifier.test(field[0] ?? "")) {
              fields.set(field[0], scan(field, colon < field.length ? colon + 1 : 0, field.length, scope, observed));
            }
          }
          value = { kind: "variant", tag: value.tag, fields };
          next = close + 1;
        } else if (code[next] === "(") {
          const close = groupEnd(code, next);
          if (close < next || close >= end) break;
          const args = argumentsOf(code, next + 1, close, scope, observed);
          const path = value?.kind === "path" ? value.path.join("::") : "";
          if (["std::pin::Pin::new", "core::pin::Pin::new", "std::boxed::Box::pin", "Box::pin"].includes(path)) value = args[0];
          else if (["std::future::Future::poll", "core::future::Future::poll"].includes(path)) value = poll(args[0]);
          else value = invoke(value, args);
          invoked = true;
          next = close + 1;
        } else if (code[next] === "." && identifier.test(code[next + 1] ?? "")) {
          const method = code[next + 1];
          if (method === "await") {
            value = awaitValue(value);
            next += 2;
          } else if (value?.kind === "variant" && value.tag.startsWith(pollVariants.owner + "::") &&
              ["is_ready", "is_pending"].includes(method) && code[next + 2] === "(" && code[next + 3] === ")") {
            value = boolean(value.tag.endsWith("::Ready") === (method === "is_ready"));
            next += 4;
          } else if ((value?.kind === "pending" || value?.kind === "call-result" || value?.kind === "ready" || value?.kind === "pending-future") &&
              method === "as_mut" && code[next + 2] === "(" && code[next + 3] === ")") {
            next += 4;
          } else if (code[next + 2] === "(" &&
              (method === "poll" && (value?.kind === "call-result" || value?.kind === "ready" || value?.kind === "pending-future" || value?.kind === "pending" && value.driver === "await") ||
               value?.kind === "pending" &&
                 ((value.driver === "iterate" && ["next", "nth", "collect", "count", "last", "fold", "for_each"].includes(method)) ||
                  (value.driver === "async-iterate" && method === "poll_next")))) {
            const close = groupEnd(code, next + 2);
            if (close <= next + 2 || close >= end) break;
            argumentsOf(code, next + 3, close, scope, observed);
            if (method === "poll") value = poll(value);
            else {
              const result = drive(value, value?.kind === "pending" ? value.driver : "await");
              value = result?.kind === "ready" ? result.value : undefined;
            }
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

  const paramsOfBody = parametersOf(params);
  if (latent) {
    const returned = possible(() => block(body, parameterScope(module, paramsOfBody, [])));
    if (driveReturn) drive(returned, "await");
    return [[...refs.values()]];
  }

  const flow: RustFlow<RustTerminal> = { fallthrough: [], exits: [], suspended: [] };
  for (let trace = pendingPaths.pop(); trace; trace = pendingPaths.pop()) {
    path = trace;
    cursor = localEnum = 0;
    refs = new Map();
    const scope = parameterScope(module, paramsOfBody, []);
    const result = outcome(() => block(body, scope));
    // 返回 Future 的同步封装：先离开函数，再 poll 返回值；不是在 return 前 poll。
    const driven = driveReturn && result.exit !== "suspended" ? outcome(() => awaitValue(result.value)) : result;
    const states = driven.exit === "suspended" ? flow.suspended :
      result.exit === undefined ? flow.fallthrough : flow.exits;
    const terminal = { value: driven.value, references: refs };
    if (!states.some(other => sameValue(other.value, terminal.value) &&
        other.references.size === refs.size && [...refs.keys()].every(key => other.references.has(key)))) {
      states.push(terminal);
    }
  }
  return [...flow.fallthrough, ...flow.exits, ...flow.suspended].map(terminal => [...terminal.references.values()]);
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
    function enumResolver(current: string[], modules: string[], enabled: typeof itemEnabled, testRoot?: string[]): EnumResolver {
      const enumCache = new Map<string, RustEnum>();
      function resolve(path: string[], context: string[], namespace: "test" | "lib", args: EnumArgument[],
        depth: number): RustEnum | undefined {
        if (depth > 32) return;
        if (namespace === "test" && root !== "crate" && path[0] === root) {
          return qualifiedEnum("lib", path.slice(1), args, depth);
        }
        return qualifiedEnum(namespace, qualify(context, path), args, depth) ?? builtinEnum(path);
      }

      function qualifiedEnum(namespace: "test" | "lib", qualified: string[], args: EnumArgument[], depth: number): RustEnum | undefined {
        const name = qualified.at(-1), owner = qualified.slice(0, -1);
        const key = namespace + "::" + qualified.join("::");
        if (!name || enumCache.has(key)) return enumCache.get(key);
        const sameModule = namespace === (testRoot ? "test" : "lib") && owner.join("::") === modules.join("::");
        let source = sameModule ? current : namespace === "test" ? testRoot : read(lib);
        if (!sameModule) {
          let local: string[] = [];
          for (const part of owner) {
            const mod: ReturnType<typeof active>[number] | undefined = source && active(source, enabled)
              .find(item => item.kind === "mod" && source?.[item.index + 1] === part);
            if (!source || !mod) return;
            local = [...local, part];
            const brace = mod.index + 2;
            if (source[brace] === "{") source = source.slice(brace + 1, groupEnd(source, brace));
            else {
              const file = namespace === "lib" ? walk(local) : undefined;
              source = file ? read(file) : undefined;
            }
          }
        }
        if (!source) return;
        const items = active(source, enabled);
        const declaration = items.find(item => (item.kind === "enum" || item.kind === "type") && source?.[item.index + 1] === name);
        if (declaration?.kind === "enum") {
          const brace = separator(source, declaration.index + 2, source.length, "{");
          const close = groupEnd(source, brace);
          if (close > brace) {
            const definition = enumDefinition(source, brace, close, key, enabled);
            enumCache.set(key, definition);
            return definition;
          }
        } else if (declaration?.kind === "type") {
          const alias = aliasDefinition(source, declaration.index);
          if (alias) return resolveAlias(alias,
            (path, actual = [], at = depth + 1) => resolve(path, owner, namespace, actual, at), args, depth + 1);
        } else {
          const imported = importsOf(source, items).find(item => item.alias === name);
          if (imported) return resolve(imported.path, owner, namespace, args, depth + 1);
        }
      }

      return (path, args = [], depth = 0) => resolve(path, modules, testRoot ? "test" : "lib", args, depth);
    }
    function terminalTargets(paths: RustReference[][], external: boolean, latent = false) {
      const resolving = new Set<string>();
      function intersect(paths: RustReference[][], resolve: (ref: RustReference) => string[]): string[] {
        const sets = paths.map(terminal => new Set(terminal.flatMap(resolve)));
        return [...(sets[0] ?? [])].filter(symbol => sets.every(terminal => terminal.has(symbol)));
      }

      function visit(modules: string[], [name, ...tail]: string[], external: boolean, access: RustAccess): string[] {
        if (!name) return [];
        const key = JSON.stringify([modules, name, tail, external, access]);
        if (resolving.has(key)) return [];
        const path = walk(modules);
        if (!path) return [];
        const found: string[] = [];
        const code = read(path);
        const items = active(code);
        const inReplacement = modulePath.every((part, i) => modules[i] === part);
        function follow(path: string[], tail: string[], access: RustAccess) {
          const qualified = qualify(modules, path);
          return visit(qualified.slice(0, -1), [...qualified.slice(-1), ...tail], false, access);
        }
        resolving.add(key);
        try {
          for (const item of items) {
            if (external && !item.public) continue;
            if (item.kind === "use") {
              const end = code.indexOf(";", item.index);
              for (const imported of rustImports(code.slice(item.index, end + 1))) {
                if (imported.alias === name) found.push(...follow(imported.path, tail, access));
              }
            } else if (code[item.index + 1] === name) {
              if (item.kind === "mod" && tail.length) found.push(...visit([...modules, name], tail, external, access));
              if (tail.length || item.kind === "mod") continue;
              if (item.kind === "fn" && access !== "value") {
                const fn = rustFunction(code, item.index);
                if (!fn || !substantiveRust(fn.body) ||
                    (!latent && access === "call" && item.prefix.includes("async"))) continue;
                if (inReplacement) found.push(path + ":" + name);
                else {
                  const branches = rustReferences(importsOf(code, items), fn.body, fn.args, false, itemEnabled, latent,
                    access === "drive" && !item.prefix.includes("async"), enumResolver(code, modules, itemEnabled));
                  found.push(...intersect(branches, ref => follow(ref.path, [], ref.access)));
                }
              } else if (inReplacement && access !== "call" && ["const", "static"].includes(item.kind)) {
                found.push(path + ":" + name);
              }
            }
          }
        } finally {
          resolving.delete(key);
        }
        return found;
      }
      return new Set(intersect(paths, ref => visit([], ref.path, external, ref.access)));
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
      registered.fn.body, registered.fn.args, true, testItemEnabled, false, false,
      enumResolver(registered.module, registered.parents, testItemEnabled, code))
      .map(terminal => terminal.filter(ref => ref.path[0] === root).map(ref => ({ path: ref.path.slice(1), access: ref.access })));
    const drivenWrappers = testReferences.flat().filter(ref => ref.access === "drive" && ref.path.length === 1 &&
      roots.some(candidate => candidate.path[0] === ref.path[0]));
    // 先把每条终态的调用解析到承接导出；封装与直接调用才可在交集里相遇。
    const production = terminalTargets([[...roots, ...drivenWrappers]], true);
    const moduleOnly = !production.size && !terminalTargets([roots], true, true).size;
    const tested = terminalTargets(testReferences, root !== "crate");
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
