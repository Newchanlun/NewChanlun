import { execFileSync } from "node:child_process";

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

export function rustTest(source: string, name: string) {
  const code = tokens(source, true);
  const matching = code.map((t, i) => t === "fn" && code[i + 1] === name ? i : -1).filter(i => i >= 0);
  if (matching.length !== 1) return false;
  const index = matching[0];
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
  return attributes.some(a => a.join("") === "test") && !attributes.some(a => a.includes("ignore"));
}

export function substantiveReplacement(path: string, source: string) {
  if (path.endsWith(".py")) {
    // AST（不 import / 不执行原件），拒绝纯 docstring、pass 和省略号。
    try {
      execFileSync("python3", ["-I", "-c", [
        "import ast, sys",
        "def substantive(node):",
        "    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):",
        "        return any(substantive(child) for child in node.body)",
        "    return (isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign, ast.Return, ast.For, ast.While, ast.If, ast.With, ast.Try))",
        "            or isinstance(node, ast.Expr) and isinstance(node.value, ast.Call))",
        "sys.exit(not any(substantive(node) for node in ast.parse(sys.stdin.read()).body))",
      ].join("\n")], { input: source, stdio: ["pipe", "ignore", "ignore"], timeout: 5_000 });
      return true;
    } catch { return false; }
  }
  const implementation = (code: string[]): boolean => code.some((t, i) => {
    if (t === "fn") {
      const body = rustFunction(code, i);
      return !!body && substantiveRust(body);
    }
    if (!/^[A-Za-z_]\w*$/.test(code[i + 1] ?? "")) return false;
    if (t === "type" && code[i + 2] === "=") return /^[\w&([]/.test(code[i + 3] ?? "") && code.slice(i + 3).includes(";");
    if (!["struct", "enum", "mod", "trait"].includes(t) || !["{", "("].includes(code[i + 2])) return false;
    const left = code[i + 2];
    const end = closing(code, i + 2, left, left === "{" ? "}" : ")");
    if (end <= i + 3) return false;
    const body = code.slice(i + 3, end);
    return t === "mod" ? implementation(body) : substantiveRust(body);
  });
  return implementation(tokens(source, true));
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
