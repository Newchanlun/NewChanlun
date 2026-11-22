import { execFileSync } from "node:child_process";
import { lstatSync, readFileSync, realpathSync } from "node:fs";
import { relative, resolve, sep } from "node:path";
import { gitEnvironment } from "./git-environment.ts";
import { deliveryManifestSchema, type DeliveryManifest } from "./delivery-bundle.ts";
import { at18GitHub, type At18GitHub } from "./at18-github.ts";
import {
  At18BootstrapError, byteSha256, canonicalizeJcs, deriveJson, externalPath, parseJsonObject, repoPath, sha,
  type ArtifactRef, type FailedCheck,
} from "./at18-format.ts";

export const G0 = "bd54d4b28ec4f83d596837f84f1f861dd085124c";
export const P0 = "b5cd3fee352e5f7199233de628da05ff06c5798f";
export const at18 = ".chanlun/at18/";
export type TreeEntry = { mode: string; kind: string; oid: string };
export type Git = (...args: string[]) => Buffer;
export const utf8 = (b: Buffer) => new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(b);
export const compare = (a: string, b: string) => Buffer.compare(Buffer.from(a), Buffer.from(b));
export const sorted = (s: Iterable<string>) => [...new Set(s)].sort(compare);
export const nul = (b: Buffer) => utf8(b).split("\0").slice(0, -1);
export const inside = (directory: string, file: string) => {
  const r = relative(directory, file);
  return r === "" || (r !== ".." && !r.startsWith(".." + sep));
};
export class At18Repository {
  readonly github: At18GitHub;
  readonly git: Git;
  private readonly trees = new Map<string, Map<string, TreeEntry>>();
  private readonly blobs = new Map<string, Buffer>();
  constructor(readonly root: string) {
    this.git = (...args) => execFileSync("git", [
      "--no-replace-objects", "--literal-pathspecs", "-C", root, ...args,
    ], { stdio: ["ignore", "pipe", "pipe"], env: gitEnvironment(), maxBuffer: 64 * 1024 * 1024 });
    let origin = "";
    try { origin = this.string("config", "--get", "remote.origin.url"); } catch { /* 由 R01 报告来源失败 */ }
    this.github = at18GitHub(root, origin);
  }
  string(...args: string[]) { return utf8(this.git(...args)).trim(); }
  external(path: string) {
    if (!externalPath.safeParse(path).success || inside(this.root, path)) throw new Error("INVALID_REPORT_PATH");
    const st = lstatSync(path);
    if (!st.isFile() || realpathSync(path) !== path) throw new Error("REPORT_NOT_REGULAR_FILE");
    return readFileSync(path);
  }
  ancestor(ancestor: string, head: string) {
    if (!sha.safeParse(ancestor).success || !sha.safeParse(head).success) return false;
    const verified = this.string("rev-parse", "--verify", ancestor + "^{commit}") === ancestor;
    if (!verified) return false;
    try { this.git("merge-base", "--is-ancestor", ancestor, head); return true; }
    catch { return false; }
  }
  tree(commit: string) {
    const existing = this.trees.get(commit);
    if (existing) return existing;
    if (!sha.safeParse(commit).success) throw new Error("commit");
    const tree = new Map<string, TreeEntry>();
    for (const entry of nul(this.git("ls-tree", "-rz", commit))) {
      const tab = entry.indexOf("\t");
      const [mode, kind, oid] = entry.slice(0, tab).split(" ");
      tree.set(entry.slice(tab + 1), { mode, kind, oid });
    }
    this.trees.set(commit, tree);
    return tree;
  }
  blob(commit: string, path: string) {
    if (!repoPath.safeParse(path).success) throw new Error("INVALID_REPORT_PATH");
    const entry = this.tree(commit).get(path);
    if (!entry) throw new Error("REPORT_NOT_IN_HEAD");
    if (entry.kind !== "blob" || !/^100(644|755)$/.test(entry.mode)) throw new Error("REPORT_NOT_REGULAR_FILE");
    let bytes = this.blobs.get(entry.oid);
    if (!bytes) { bytes = this.git("cat-file", "blob", entry.oid); this.blobs.set(entry.oid, bytes); }
    return bytes;
  }
  chain(from: string, exclude?: string): string[] {
    if (!sha.safeParse(from).success || (exclude && !sha.safeParse(exclude).success)) throw new Error("commit");
    return this.string("rev-list", "--first-parent", from, ...(exclude ? ["^" + exclude] : [])).split("\n").filter(Boolean);
  }
  changed(parent: string, commit: string) {
    return nul(this.git("diff", "--no-renames", "--name-only", "-z", parent, commit, "--"));
  }
  anchor(path: string, chain: readonly string[]) {
    for (const [index, commit] of chain.entries()) {
      const current = this.tree(commit).get(path);
      const previous = this.tree(chain[index + 1] ?? P0).get(path);
      if (current?.mode !== previous?.mode || current?.oid !== previous?.oid) return commit;
    }
    return undefined;
  }
}

type ReportDeclaration = DeliveryManifest["reports"][number];
export function artifactBytes(source: At18Repository, m: DeliveryManifest, artifact: ReportDeclaration) {
  const fail = (code: string): never => { throw new At18BootstrapError(code, code, artifact.path); };
  let bytes: Buffer;
  if ("storage" in artifact) {
    if (artifact.ticket !== m.ticket || artifact.base !== m.base || artifact.head !== m.head) return fail("REPORT_VERSION_MISMATCH");
    const root = m.externalReportsRoot;
    if (!root || !externalPath.safeParse(root).success || !externalPath.safeParse(artifact.path).success ||
        !inside(root, artifact.path) || root === artifact.path || inside(source.root, root)) return fail("INVALID_REPORT_PATH");
    try {
      if (realpathSync(root) !== root) return fail("INVALID_REPORT_PATH");
      bytes = source.external(artifact.path);
    } catch (error) {
      if (error instanceof At18BootstrapError) throw error;
      const why = error instanceof Error ? error.message : "";
      return fail(why === "INVALID_REPORT_PATH" || why === "REPORT_NOT_REGULAR_FILE" ? why : "REPORT_MISSING");
    }
  } else {
    try { bytes = source.blob(m.head, artifact.path); }
    catch (error) {
      const why = error instanceof Error ? error.message : "";
      return fail(["INVALID_REPORT_PATH", "REPORT_NOT_IN_HEAD", "REPORT_NOT_REGULAR_FILE"].includes(why) ? why : "REPORT_NOT_IN_HEAD");
    }
    const absolute = resolve(source.root, artifact.path);
    try {
      if (!lstatSync(absolute).isFile() || realpathSync(absolute) !== absolute) return fail("REPORT_NOT_REGULAR_FILE");
      if (byteSha256(readFileSync(absolute)) !== artifact.sha256) return fail("REPORT_HASH_MISMATCH");
    } catch (error) {
      if (error instanceof At18BootstrapError) throw error;
      return fail("REPORT_MISSING");
    }
  }
  if (byteSha256(bytes) !== artifact.sha256) return fail("REPORT_HASH_MISMATCH");
  return bytes;
}
export function readOwnManifest(source: At18Repository, path: string) {
  let bytes: Buffer;
  try { bytes = source.external(path); }
  catch { throw new At18BootstrapError("MANIFEST_UNREADABLE", "本票仓外清单不可读。"); }
  let manifest: DeliveryManifest;
  try {
    const raw = parseJsonObject(bytes);
    const members: unknown[] = [raw];
    for (const member of members) {
      if (member !== null && typeof member === "object") {
        if (Object.hasOwn(member, "__proto__")) throw new Error("undeclared key");
        members.push(...Object.values(member));
      }
    }
    canonicalizeJcs(raw);
    manifest = deliveryManifestSchema.parse(raw);
  }
  catch { throw new At18BootstrapError("INVALID_MANIFEST", "本票仓外清单 JSON 或结构无效。"); }
  if (manifest.ticket !== 1391) throw new At18BootstrapError("INVALID_MANIFEST", "本票仓外清单 ticket 须为 1391。");

  const reports = new Map<string, ReportDeclaration>();
  for (const artifact of manifest.reports) {
    if (reports.has(artifact.path)) {
      throw new At18BootstrapError("REPORT_DECLARATION_MISMATCH", "实体只能登记一次。", artifact.path);
    }
    reports.set(artifact.path, artifact);
  }
  const related = [...manifest.reviews.map(r => r.report), ...manifest.checks.map(r => r.evidence),
    manifest.scan.evidence, manifest.scan.disclosure?.triage];
  for (const artifact of related) {
    if (!artifact) continue;
    const declared = reports.get(artifact.path);
    if (!declared) throw new At18BootstrapError("UNDECLARED_REPORT", "证据实体未登记。", artifact.path);
    if (canonicalizeJcs(declared) !== canonicalizeJcs(artifact)) {
      throw new At18BootstrapError("REPORT_DECLARATION_MISMATCH", "证据身份与登记不一致。", artifact.path);
    }
  }
  const registered = new Map(manifest.reports.map(a => [a.path, artifactBytes(source, manifest, a)]));
  return { manifest, registered };
}
export type Own = ReturnType<typeof readOwnManifest>;
export function repoRef(head: string, path: string, bytes: Buffer, role: string): ArtifactRef {
  return { storage: "in_repo", path, commit: head, ticket: null, base: null, head: null,
    sha256: byteSha256(bytes), bounded_scope: "AT18:" + role };
}
export function extRef(m: DeliveryManifest, path: string, bytes: Buffer, role: string): ArtifactRef {
  return { storage: "external", path, commit: null, ticket: m.ticket, base: m.base, head: m.head,
    sha256: byteSha256(bytes), bounded_scope: "AT18:" + role };
}

export class Diagnostics {
  private readonly errors = new Map<string, FailedCheck>();
  add(check_id: string, scope: string, evidence_ref: ArtifactRef | null = null) {
    if (/[\uD800-\uDFFF]/u.test(scope)) scope = "/";
    const key = check_id + "\0" + scope;
    const current = this.errors.get(key);
    if (!current || (evidence_ref && (!current.evidence_ref || compare(refKey(evidence_ref), refKey(current.evidence_ref)) < 0))) {
      this.errors.set(key, { check_id, scope, detail: check_id, evidence_ref });
    }
  }
  all() { return [...this.errors.values()].sort((a, b) => compare(a.check_id, b.check_id) || compare(a.scope, b.scope)); }
  get size() { return this.errors.size; }
  async get<T>(scope: string, read: () => Promise<T>) {
    try { return await read(); }
    catch { this.add("SOURCE_UNAVAILABLE", scope); return undefined; }
  }
}
export function refKey(r: ArtifactRef) {
  return [r.storage, r.path, r.commit ?? "", String(r.ticket ?? "").padStart(16, "0"),
    r.base ?? "", r.head ?? "", r.sha256, r.bounded_scope].join("\0");
}
export function refs(input: Iterable<ArtifactRef>) {
  return [...new Map([...input].map(r => [refKey(r), r])).values()].sort((a, b) => compare(refKey(a), refKey(b)));
}
export function jsonBlob(source: At18Repository, head: string, path: string) {
  const bytes = source.blob(head, path);
  if (!bytes.length) throw new Error("empty");
  const json = parseJsonObject(bytes);
  canonicalizeJcs(json);
  return { bytes, json };
}
export const escapeToken = (s: string) => s.replaceAll("~", "~0").replaceAll("/", "~1").replaceAll("%", "%25").replaceAll("@", "%40");
export function valueAt(value: unknown, pointer: string): unknown {
  if (!/^(?:\/(?:[^~]|~[01])*)?$/.test(pointer)) return undefined;
  if (!pointer) return value;
  for (const token of pointer.slice(1).split("/").map(t => t.replaceAll("~1", "/").replaceAll("~0", "~"))) {
    if (value === null || typeof value !== "object" || (Array.isArray(value) && !/^(0|[1-9][0-9]*)$/.test(token)) ||
        !Object.hasOwn(value, token)) return undefined;
    value = (value as Record<string, unknown>)[token];
  }
  return value;
}
