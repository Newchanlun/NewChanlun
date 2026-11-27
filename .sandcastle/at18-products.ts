import { z } from "zod";
import { parseJsonObject, repoPath, sha } from "./at18-format.ts";
import { type Row, object } from "./at18-github.ts";
import { type Ticket } from "./at18-integrations.ts";
import { type At18Repository, sorted } from "./at18-source.ts";

export function ownedPr(pr: Row, ticket: number) {
  const branch = String(object(pr.head).ref ?? "");
  const match = /(?:^|\/)(?:issue[-/]?)?(\d+)(?:[-_/]|$)/.exec(branch);
  if (Number(match?.[1]) === ticket) return true;
  return new RegExp(`^(?:[\\w.-]+:\\s*)?\\[?#${ticket}(?![0-9])`, "i").test(String(pr.title ?? "")) ||
    new RegExp(`^\\s*(?:fix(?:e[sd])?|close[sd]?|resolve[sd]?)\\s+#${ticket}(?![0-9])`, "im").test(String(pr.body ?? ""));
}

const productDelivery = z.strictObject({ ticket: z.int().positive(),
  products: z.array(z.strictObject({ commit: sha, path: repoPath })).min(1) });
const prDelivery = z.strictObject({ ticket: z.int().positive(), paths: z.array(repoPath).min(1) });
const deliveryFences = (body: string) => [...body.matchAll(/^```at18-product-delivery\/1\r?\n([\s\S]*?)\r?\n^```[ \t]*$/gm)]
  .map(match => parseJsonObject(Buffer.from(match[1])));

// R5 开工时已合入的主线快照是旧格式的上界。只有这条祖先链可用旧证据，
// 新 head 即使自填早日期也必须提供当前 PR 和获审 head 两份一致的逐票归属。
const preFenceMain = "b9d898dccf46c2a716115eaa1215bc39c458a959";
// 仅取该路径上不可变的主张：提交标题、显式交付 trailer，或文件开头的归属声明。
const ticketMentions = (line: string) => [...line.matchAll(/(?:^|[^\w#])#([1-9]\d*)(?![\w])/g)].map(m => Number(m[1]));
function commitPathOwners(s: At18Repository, base: string, head: string, path: string) {
  const owners = new Set<number>();
  const history = s.string("log", "--full-history", "--no-merges", "--format=%s%x00%b%x00", base + ".." + head, "--", path);
  const fields = history.split("\0");
  for (let i = 0; i + 1 < fields.length; i += 2) {
    for (const number of ticketMentions(fields[i])) owners.add(number);
    for (const line of fields[i + 1].split("\n")) {
      if (/^\s*(?:Fix(?:e[sd])?|Clos(?:e[sd]?|ing)|Resolv(?:e[sd]?|ing)|Ticket|Refs)[: ]/i.test(line)) {
        for (const number of ticketMentions(line)) owners.add(number);
      }
    }
  }
  return owners;
}
function headerOwners(bytes: Buffer) {
  const head = bytes.toString("utf8").split(/\r?\n/).find(line => line.trim() && !line.startsWith("#!"));
  const primary = /^\s*(?:[ru]?(?:"""|''')|\/\/+!?|\/\*+|#)\s*(#[1-9]\d*(?:\s*[/、,]\s*#[1-9]\d*)*)(?:[：:\s]|$)/.exec(head ?? "");
  return new Set(ticketMentions(primary?.[1] ?? ""));
}
function branchScope(branch: string, ticket: number, path: string) {
  const scoped = new RegExp(`(?:^|/)(?:issue[-/]?)?${ticket}-([a-z0-9-]+?)(?:-r[0-9]+)?$`, "i").exec(branch)?.[1];
  if (!scoped || !scoped.includes("-")) return false;
  const namespace = scoped.replaceAll("-", "_");
  return path.startsWith("rust/src/" + namespace + "/") ||
    new RegExp(`^rust/tests/${namespace}(?:_[a-z0-9]+)*\\.(?:rs|py)$`).test(path);
}
function oldRange(s: At18Repository, merge: string, parent: string, H: string, pr: Row) {
  if (!s.ancestor(merge, preFenceMain) || s.string("rev-parse", merge + "^2") !== H) return undefined;
  const body = s.string("show", "-s", "--format=%B", merge);
  const origin = /^Merge pull request #(\d+) from [\w.-]+\/([^\s]+)$/m.exec(body);
  if (!origin || Number(origin[1]) !== pr.number || object(pr.head).ref !== origin[2]) return undefined;
  return { base: s.string("merge-base", parent, H), branch: origin[2] };
}
function oldReviewedProduct(s: At18Repository, merge: string, parent: string, H: string, pr: Row, path: string, ticket: number) {
  const origin = oldRange(s, merge, parent, H, pr);
  if (!origin || !s.changed(origin.base, H).includes(path)) return false;
  const header = headerOwners(s.blob(merge, path));
  if (header.size) return header.has(ticket);
  const owners = commitPathOwners(s, origin.base, H, path);
  if (owners.size) return owners.size === 1 && owners.has(ticket);
  // 分支票号单独不足以归属文件；还须命中实际变更中的同名代码命名空间。
  return branchScope(origin.branch, ticket, path);
}

function implicitOldProducts(s: At18Repository, number: number, reviewed: ReadonlyMap<string, Row>) {
  return [...reviewed].flatMap(([commit, pr]) => {
    if (!ownedPr(pr, number) || !s.ancestor(commit, preFenceMain)) return [];
    const parent = s.string("rev-parse", commit + "^1");
    const head = sha.parse(object(pr.head).sha);
    // 无路径声明时，仅推导唯一的、可逐路径归属的模块根。
    const roots = s.changed(parent, commit).filter(path => /^rust\/src\/[^/]+\/mod\.rs$/.test(path) &&
      oldReviewedProduct(s, commit, parent, head, pr, path, number));
    return roots.length === 1 ? [{ commit, path: roots[0] }] : [];
  });
}

function fencedProduct(body: string, path: string, ticket: number) {
  const claims = deliveryFences(body).map(v => prDelivery.parse(v));
  if (new Set(claims.map(v => v.ticket)).size !== claims.length) return false;
  const owners = claims.filter(v => v.paths.includes(path));
  return owners.length === 1 && owners[0].ticket === ticket;
}

export function deliveredProducts(s: At18Repository, ticket: Ticket, historical: ReadonlyMap<string, ReadonlySet<number>>,
  reviewed: ReadonlyMap<string, Row>) {
  if (ticket.state !== "CLOSED" || ticket.reason !== "COMPLETED" || typeof ticket.data?.body !== "string") return [];
  try {
    const declarations = deliveryFences(ticket.data.body);
    if (declarations.length > 1) return [];
    const data = declarations.length === 1 ? productDelivery.parse(declarations[0]) :
      { ticket: ticket.number, products: implicitOldProducts(s, ticket.number, reviewed) };
    if (data.ticket !== ticket.number || !data.products.length) return [];
    const seen = new Set<string>();
    for (const { commit, path } of data.products) {
      const key = commit + "\0" + path;
      if (seen.has(key)) return [];
      const current = reviewed.get(commit);
      const owners = historical.get(commit);
      if (!current && !owners?.has(ticket.number)) return [];
      const parent = s.string("rev-parse", commit + "^1");
      if (!s.changed(parent, commit).includes(path) || !s.blob(commit, path).length) return [];
      if (current) {
        const H = sha.parse(object(current.head).sha);
        const head = s.string("show", "-s", "--format=%B", H);
        const pr = String(current.body ?? "");
        if (head.includes("```at18-product-delivery/1")) {
          if (!fencedProduct(head, path, ticket.number) || !fencedProduct(pr, path, ticket.number)) return [];
        } else if (!oldReviewedProduct(s, commit, parent, H, current, path, ticket.number)) return [];
      } else {
        const header = headerOwners(s.blob(commit, path));
        if (header.size) {
          if (!header.has(ticket.number)) return [];
        } else {
          const scope = /^\.chanlun\/review-results\/issue([1-9]\d*)(?:-|\/)/.exec(path);
          if (scope) {
            if (Number(scope[1]) !== ticket.number) return [];
          } else {
            const pathOwners = commitPathOwners(s, parent, commit, path);
            if (pathOwners.size !== 1 || !pathOwners.has(ticket.number)) return [];
          }
        }
      }
      seen.add(key);
    }
    return sorted(data.products.map(row => row.commit));
  } catch { return []; }
}
