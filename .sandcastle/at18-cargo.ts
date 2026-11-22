import { execFileSync } from "node:child_process";
import { z } from "zod";

const manifest = z.object({
  package: z.object({ name: z.string(), edition: z.enum(["2015", "2018", "2021", "2024"]).catch("2024") }).optional(),
  lib: z.object({ name: z.string().optional() }).optional(),
  features: z.record(z.string(), z.array(z.string())).optional(),
});

export function cargoContext(toml: string | undefined, explicit: string[]) {
  // tomllib 处理注释、多行及引号；只展开本 crate 的特性名，不把依赖名混进来。
  const config = toml === undefined ? {} : manifest.parse(JSON.parse(execFileSync("python3", ["-I", "-B", "-c",
    "import json, sys, tomllib; c = tomllib.load(sys.stdin.buffer); print(json.dumps({k: c[k] for k in ('package', 'lib', 'features') if k in c}, default=str))"],
  { input: toml, encoding: "utf8", timeout: 5_000, stdio: ["pipe", "pipe", "ignore"] })));
  const features = new Set(explicit);
  for (const enabled of features) {
    for (const name of config.features && Object.hasOwn(config.features, enabled) ? config.features[enabled] : []) {
      if (!name.startsWith("dep:") && !name.includes("/")) features.add(name);
    }
  }
  return { crate: (config.lib?.name ?? config.package?.name)?.replaceAll("-", "_"),
    edition: config.package?.edition ?? "2024", features };
}

export type CargoTarget = "linux" | "macos" | "windows";

export function cargoTarget(labels: readonly string[] = []): CargoTarget | undefined {
  const targets = new Set<CargoTarget>();
  for (const label of labels) {
    if (/^(?:linux|ubuntu-(?:latest|\d{2}\.\d{2}))$/i.test(label)) targets.add("linux");
    else if (/^macos(?:-(?:latest|\d+))?$/i.test(label)) targets.add("macos");
    else if (/^windows(?:-(?:latest|\d{4}))?$/i.test(label)) targets.add("windows");
  }
  return targets.size === 1 ? [...targets][0] : undefined;
}

export function enabledRustItem(attributes: string[], features: ReadonlySet<string>, target?: CargoTarget, testBuild?: boolean) {
  const family = target === undefined ? undefined : target === "windows" ? "windows" : "unix";
  function cfg(tokens: string[]) {
    let i = 0;
    function predicate(): boolean | undefined {
      const name = tokens[i++];
      if (tokens[i] === "=") {
        i++;
        const value = tokens[i++];
        if (!value?.startsWith('"')) return undefined;
        const literal: unknown = JSON.parse(value);
        if (typeof literal !== "string") return undefined;
        if (name === "feature") return features.has(literal);
        if (name === "target_os" && target !== undefined) return target === literal;
        if (name === "target_family" && family !== undefined) return family === literal;
        return undefined;
      }
      if (tokens[i] !== "(") {
        if (name === "test") return testBuild;
        if (name === "true" || name === "false") return name === "true";
        return family !== undefined && (name === "unix" || name === "windows") ? family === name : undefined;
      }
      i++;
      const children: (boolean | undefined)[] = [];
      while (tokens[i] !== ")" && i < tokens.length) {
        children.push(predicate());
        if (tokens[i] !== ",") break;
        i++;
      }
      if (tokens[i++] !== ")") return undefined;
      if (name === "all") return children.includes(false) ? false : children.includes(undefined) ? undefined : true;
      if (name === "any") return children.includes(true) ? true : children.includes(undefined) ? undefined : false;
      if (name === "not" && children.length === 1 && children[0] !== undefined) return !children[0];
      return undefined;
    }
    if (tokens[0] !== "(" || tokens.at(-1) !== ")") return false;
    i++;
    return predicate() === true && i === tokens.length - 1;
  }
  for (let i = 0; i < attributes.length; i++) {
    if (attributes[i] !== "#" || attributes[i + 1] !== "[") continue;
    let end = i + 2, depth = 1;
    while (end < attributes.length && depth) {
      if (attributes[end] === "[") depth++;
      if (attributes[end] === "]") depth--;
      end++;
    }
    const attr = attributes[i + 2];
    if (["path", "cfg_attr"].includes(attr) ||
        (attr === "cfg" && !cfg(attributes.slice(i + 3, end - 1)))) return false;
    i = end - 1;
  }
  return true;
}
