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
// #1906 批次没有逐票 fence；以下是该合入 Git blob 首部标明的逐票验证器。
const batchedProducts = new Map([
  ["s_session/tests/tb02b_verify.py", [1392, 1405]],
  ["s_session/tests/tb02c_verify.py", [1404]],
  ["s_session/tests/tb02d_verify.py", [1414]],
]);
const batch1906 = "3d61fb72944f577ea3b758b54001c2a7544b04dc";
const history1942 = "3cd162ea4c3c8c73a0d6b8c6866894a0204e78bc";
const legacyProduct = { commit: history1942, path: "rust/src/history_simulation/mod.rs" };

function commitPathOwners(s: At18Repository, base: string, head: string, path: string) {
  const subjects = s.string("log", "--no-merges", "--format=%s", base + ".." + head, "--", path);
  return new Set([...subjects.matchAll(/^[\w-]+\(#([1-9]\d*)\)!?:/gm)].map(m => Number(m[1])));
}

function oldReviewedProduct(s: At18Repository, merge: string, parent: string, H: string, pr: Row, path: string, ticket: number) {
  if (!s.ancestor(merge, preFenceMain) || s.string("rev-parse", merge + "^2") !== H) return false;
  const body = s.string("show", "-s", "--format=%B", merge);
  const origin = /^Merge pull request #(\d+) from [\w.-]+\/([^\s]+)$/m.exec(body);
  if (!origin || Number(origin[1]) !== pr.number || object(pr.head).ref !== origin[2]) return false;
  const base = s.string("merge-base", parent, H);
  if (!s.changed(base, H).includes(path)) return false;
  const owners = commitPathOwners(s, base, H, path);
  if (owners.size > 0) return owners.size === 1 && owners.has(ticket);

  // #1942 的最后一个 head 是同步 main；首个实际产品 commit 未带 #1381
  // 标记。只让 Git 中冻结的 #1381 专用路径和已获审的真实 PR diff 补足归属。
  return merge === history1942 && pr.number === 1942 &&
    origin[2] === "codex/1381-history-simulation-r6" && ticket === 1381 &&
    (/^rust\/src\/history_simulation\//.test(path) || /^rust\/tests\/history_simulation_entry\.(?:rs|py)$/.test(path));
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
    // #1942 已合入时还没有逐票协议；缺新格式声明时只解析已固定的主产品。
    const data = declarations.length === 1 ? productDelivery.parse(declarations[0]) :
      ticket.number === 1381 && reviewed.has(history1942) ? { ticket: 1381, products: [legacyProduct] } : undefined;
    if (!data) return [];
    if (data.ticket !== ticket.number) return [];
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
      } else if (commit === batch1906) {
        if (!batchedProducts.get(path)?.includes(ticket.number)) return [];
      } else if (owners && owners.size > 1) {
        const pathOwners = commitPathOwners(s, parent, commit, path);
        if (pathOwners.size !== 1 || !pathOwners.has(ticket.number)) return [];
      }
      seen.add(key);
    }
    return sorted(data.products.map(row => row.commit));
  } catch { return []; }
}
