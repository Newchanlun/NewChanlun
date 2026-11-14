#!/usr/bin/env node
import { MaintenanceOwner, MaintenanceClosed, maintenanceCommand } from "../.sandcastle/maintenance.mts";
/**
 * wayfinder_engine.mts —— 图清自动汇入主干管线自动化（#1078 裁定落地，#1084 实装）。
 *
 * 形态（#1078 裁定）：
 *   - DAG 走查器 = 纯函数：输入 tracker 状态（map 子票 + blocking 边 + 标签 + comments）
 *     → 输出触发动作清单；本文件内所有带「纯函数」注释的导出均可离线单测。
 *   - loop 壳 = 4 分钟轮询（watcher.sh / dispatcher 先例），每轮重算 ready 集、天然幂等；
 *   - stateless：不建状态库，tracker 即账本。
 *
 * 自动动作边界（#1078 裁定 4）：
 *   1. 图清（子票全关、frontier 空）→ 派主控同型起草子代理（经 CLIProxyLocal，#1588 / #1617）起草 spec 草案 → 开图内 spec 票
 *      → 待非作者独审；
 *   2. spec 裁定（编排者账号发结构化「SPEC 独审裁定：PASS」，非作者、绑定当前正文摘要，#1909）→ 自动拆 tracer-bullet 实装票
 *      （blocking 边 + 票面逐条挂裁定票）→ 发布 ready-for-agent → 按依赖释放拾取标签；
 *   3. 实装票全关 + 图关判据满足 → 自动起草图关 comment + close map。
 *
 * 本引擎不裁决策票，也不处理纯决策图；决策票由 decision-claimer 起草并经非作者独审裁定。
 * 本引擎不碰 main：main 的合入不设人工批准，由分支保护的 deepagents/review 与 ci-ok 必需检查把关，满足后代理合入；
 * spec 与 P 类决策改为起草 + 非作者独审 PASS 由代理裁定（#1909）。
 *
 * #1084 追加（2026-08-19 打回复核）——常驻控制面成为活机制：
 *   - 每轮区分五桶：全仓 ready-for-agent / 已获 ${releaseLabel()} 拾取权 / blocked / claimed / running；
 *   - 只由本控制面给合资格实装票（已批准 spec/DAG + 未 assign + 无 blocker）挂 sandcastle，
 *     不把全部历史 ready-for-agent 无差别放行（planReleases / classifyTicket 纯函数）；
 *   - gh 查询有限重试 + 指数退避 + fail-loud（单次网络失败不永久停摆）；
 *   - 无 runnable 票 sleep 后重查、不退出（常驻 for(;;)）；
 *   - 每轮写状态页 .sandcastle/logs/wayfinder-status.md（五桶分明）。
 *
 * 部署（受管常驻，launchd KeepAlive）：
 *   bash .sandcastle/install-wayfinder-engine.sh install   # 安装并加载
 *   bash .sandcastle/install-wayfinder-engine.sh status    # 查状态
 *   launchd 跑 .sandcastle/run-wayfinder-engine.sh --live  # 真实执行（--live 显式，默认仍 dry-run）
 *
 * 跑法（仓库根，手工调试）：
 *   npx tsx scripts/wayfinder_engine.mts --once --dry-run   单轮演练（只打印动作，不执行）
 *   npx tsx scripts/wayfinder_engine.mts                    常驻轮询（默认 dry-run，4 分钟一轮）
 *   npx tsx scripts/wayfinder_engine.mts --live --once      真实执行一轮
 */

import { HOLD_LABELS, MIRROR_LABEL, ORCHESTRATOR_LOGIN, QUEUE_LABEL, releaseLabel, graphAdmissionFrozen, withGraphAdmission as withEngineAdmission, withTicketHold, type LocalClaim } from "../.sandcastle/deepagents-cutover.mts";
export { releaseLabel, HOLD_LABELS, ORCHESTRATOR_LOGIN, withEngineAdmission };
import { execFileSync, execSync } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { cliProxyEnv } from "../.sandcastle/cliproxy-env.mts";
import { MAIN_MODEL, SUPPORTED_MAIN_MODELS } from "../.sandcastle/main-model.mts";

// ── 顶部常量（编排者 / 周期 / 起草子代理模型） ──────────────────────────────
// 编排账号默认读 queue-policy.json 的 orchestrator_login（与 Python 消费者同源）。
// 环境变量覆盖：WAYFINDER_ORCHESTRATOR / WAYFINDER_POLL_SECONDS /
//               WAYFINDER_SPEC_MODEL / WAYFINDER_SPEC_PROVIDER。
// 默认 dry-run（安全默认）；真实执行须显式 --live。
const DEFAULT_POLL_SECONDS = 240; // 4 分钟（dispatcher 先例）
// 起草子代理与当前主控同型（用户 2026-10-24，#1617）：Claude Code CLI 经本机
// CLIProxyLocal 自动路由；实际模型只在 main-model.mts 配置，独立评审不靠异模型。
export const DEFAULT_SPEC_MODEL = MAIN_MODEL;
export const DEFAULT_SPEC_PROVIDER = "claude-cliproxy";
/** WAYFINDER_SPEC_MODEL 只接受主控同型；非法值 fail-loud，不回退旧模型。 */
export const SUPPORTED_SPEC_MODELS = SUPPORTED_MAIN_MODELS;
// gh 在 FORCE_COLOR 环境下会给 --json 输出染色，必须洗掉（main.mts 同款）。
const GH_ENV: NodeJS.ProcessEnv = {
  ...process.env,
  NO_COLOR: "1",
  CLICOLOR: "0",
  FORCE_COLOR: "0",
  CLICOLOR_FORCE: "0",
  GH_REPO: process.env.GH_REPO ?? "xy7365527-lang/NewChanlun",
};

// ── 类型（tracker 状态的归一化视图，纯函数只吃这些） ─────────────────────────

export interface IssueComment {
  author: string;
  body: string;
  createdAt: string;
}

export interface ChildIssue {
  number: number;
  title: string;
  body: string;
  state: "OPEN" | "CLOSED";
  labels: string[];
  assignees: string[];
  /** open 阻塞边的数量（issue_dependencies_summary.blocked_by，非阻塞票号清单）。 */
  blockedBy: number;
  comments: IssueComment[];
  /**
   * 本票的 sub_issues（递归）。analyzeMap 只看 map 直挂层，不读此字段；
   * buildSpecApprovalIndex 递归它，让 SPEC 子树（TB 汇总 → 叶 → 纵片）拿到批准态。
   */
  children?: ChildIssue[];
  /** sub_issues_summary 的 open 子票数（total − completed）；递归截断时仍可判汇总票。 */
  openSubIssues?: number;
}

export interface MapState {
  number: number;
  title: string;
  body: string;
  state: "OPEN" | "CLOSED";
  labels: string[];
  children: ChildIssue[];
}

export type Action =
  | { kind: "draft_spec"; map: number }
  | { kind: "split_impl_tickets"; map: number; spec: number }
  | { kind: "close_graph"; map: number };

export interface WalkOptions {
  /** 编排者 login；spec 裁定记录只认此账号的评论。 */
  orchestrator: string;
}

export interface Analysis {
  phase: string;
  actions: Action[];
}

// ── 角色分类（纯函数） ────────────────────────────────────────────────────────

const DECISION_LABELS = [
  "wayfinder:grilling",
  "wayfinder:research",
  "wayfinder:prototype",
  "wayfinder:task",
];

/** 决策票：带 wayfinder:<type> 标签的子票（grilling/research/prototype/task）。 */
export function isDecisionTicket(c: Pick<ChildIssue, "labels">): boolean {
  return c.labels.some((l) => DECISION_LABELS.includes(l));
}

/**
 * spec 票：标题以 📋 SPEC 或 [spec] 开头（#775/#1077 惯例），或以「SPEC：」「SPEC:」开头
 * （#1340 曾用标题「SPEC：完整生产程序…」失配，图审计 2026-10-20 第 15 条）。
 */
export function isSpecTicket(c: Pick<ChildIssue, "title">): boolean {
  return (
    /^\s*📋\s*SPEC/i.test(c.title) ||
    /^\s*\[spec\]/i.test(c.title) ||
    /^\s*SPEC\s*[：:]/.test(c.title)
  );
}

/** 实装票：标题以 [impl] 开头（#1077 拆出的 S1–S5 惯例）。 */
export function isImplTicket(c: Pick<ChildIssue, "title">): boolean {
  return /^\s*\[impl\]/i.test(c.title);
}

/** 实装票标签（/to-tickets 拆出的 tracer-bullet 叶子；#1340 TB 叶子多只带此标签、不带 [impl] 标题）。 */
export const IMPL_LABEL = "wayfinder:impl";

/**
 * 放行用的实装票判据：标题 [impl] 或带 wayfinder:impl 标签，且不是决策票。
 * 只用于队列交棒（classifyTicket）；analyzeMap 的拆票/关图仍按标题判，口径不动。
 */
export function isImplCandidate(c: Pick<ChildIssue, "title" | "labels">): boolean {
  if (isDecisionTicket(c)) return false;
  return isImplTicket(c) || c.labels.includes(IMPL_LABEL);
}

/**
 * 纯决策图（v1 不碰，spec 出图走人工）：Notes 显式声明「本图为纯决策图，不带实装——理由：…」。
 * 判据取 wayfinder-workflow.md 的声明样板，避免误伤正文里泛泛提及「纯决策图」的引用句。
 */
export function isPureDecisionMap(map: Pick<MapState, "body">): boolean {
  return /本图为纯决策图|纯决策图[，,]\s*不带实装/.test(map.body);
}

// ── spec 裁定检测（纯函数，#1909） ─────────────────────────────────────────────

export const SPEC_RULING_HEAD = "SPEC 独审裁定";

const REJECT_RE = /不批准|不通过|打回|驳回|重写|reject|deny|nack|暂不/i;

/** SPEC 正文摘要：GitHub 返回的 body，统一 CRLF 并去掉末尾空白后取 sha256。 */
export function specBodyDigest(body: string): string {
  return createHash("sha256").update(body.replace(/\r\n/g, "\n").trimEnd(), "utf8").digest("hex");
}

export interface SpecReview {
  specNumber: number;
  verdict: "PASS" | "BLOCK";
  /** 起草者身份（模型或会话）。 */
  author: string;
  /** 独审者身份；必须不同于起草者。 */
  reviewer: string;
  /** 独审时所审 SPEC 正文的 specBodyDigest。 */
  digest: string;
}

export interface SpecRuling extends SpecReview {
  /** 独审原件位置（路径或链接）。 */
  evidence: string;
}

/** 去掉行首 Markdown 前缀（引用、标题、列表、强调）与行尾强调；正文里的下划线保留（路径常含 _）。 */
const strip = (line: string) => line.replace(/^(?:\s*(?:>|#{1,6}|[-*]\s|\*{1,3}|_{1,3}))+\s*/, "").replace(/(?:\*{1,3}|_{1,3})\s*$/, "").trim();
const field = (lines: string[], name: string) => {
  for (const l of lines) {
    const m = new RegExp(`^${name}\\s*[：:]\\s*(.*)$`).exec(strip(l));
    if (m) return m[1]!.replace(/^`|`$/g, "").trim();
  }
  return "";
};

/**
 * 解析结构化 SPEC 裁定评论。首行（去掉行尾空白后）必须恰为「SPEC 独审裁定：PASS」或「…：BLOCK」，
 * 只容许 specRulingBody 写出的整行加粗 `**…**`；结论后多一个字（如「PASS不通过」「PASS (draft)」）、
 * 半角冒号、引用或列表前缀都不算裁定，返回 null，交由 isSpecApproved 按普通评论（含驳回词判定）处理。
 */
export function parseSpecRuling(body: string): SpecRuling | null {
  const lines = body.replace(/\r\n/g, "\n").split("\n");
  const m = new RegExp(`^(?:\\*\\*${SPEC_RULING_HEAD}：(PASS|BLOCK)\\*\\*|${SPEC_RULING_HEAD}：(PASS|BLOCK))$`)
    .exec((lines[0] ?? "").replace(/\s+$/, ""));
  if (!m) return null;
  const rest = lines.slice(1);
  return {
    specNumber: Number(field(rest, "SPEC")),
    verdict: (m[1] ?? m[2]) as SpecRuling["verdict"],
    author: field(rest, "作者"),
    reviewer: field(rest, "独审"),
    digest: field(rest, "正文 sha256").toLowerCase(),
    evidence: field(rest, "证据"),
  };
}

/** 审查绑定同时用于原件发布和评论消费；BLOCK 原件也须绑定所审正文。 */
function specReviewProblem(r: SpecReview, specNumber: number, specBody: string): string | null {
  if (!Number.isSafeInteger(r.specNumber) || r.specNumber <= 0 || r.specNumber !== specNumber) return "SPEC 票号不匹配";
  if (r.verdict !== "PASS" && r.verdict !== "BLOCK") return "结论只能是 PASS 或 BLOCK";
  if (![r.author, r.reviewer].every((v) => typeof v === "string" && v.trim() && !/[\r\n]/.test(v))) return "缺作者或独审单行身份";
  if (r.author.trim().toLowerCase() === r.reviewer.trim().toLowerCase()) return "独审与作者相同";
  if (typeof r.digest !== "string" || !/^[a-f0-9]{64}$/.test(r.digest)) return "缺正文 sha256";
  if (r.digest !== specBodyDigest(specBody)) return "正文已在独审后改动";
  return null;
}

/** 只有绑定当前 SPEC 的非作者 PASS 才能放行。 */
export function specRulingProblem(r: SpecRuling, specNumber: number, specBody: string): string | null {
  if (r.verdict !== "PASS") return "裁定为 BLOCK";
  if (!r.evidence.trim() || /[\r\n]/.test(r.evidence)) return "缺独审原件位置";
  return specReviewProblem(r, specNumber, specBody);
}

/** 结构化裁定评论正文（给主控发评论用）。 */
export function specRulingBody(r: SpecRuling): string {
  return [`**${SPEC_RULING_HEAD}：${r.verdict}**`, `SPEC：${r.specNumber}`, `作者：${r.author}`, `独审：${r.reviewer}`, `正文 sha256：${r.digest}`, `证据：${r.evidence}`].join("\n") + "\n";
}

/**
 * 评论是否为「裁定类」：全文任意位置（NFKC 归一后）出现「SPEC 独审裁定」即命中，用于撤销判定的宽松探测。
 * 不看首行位置与前缀——开头空行、HTML 注释、代码块、列表/表格前缀、半角冒号、结论后缀（「PASS不通过」）、
 * 不成形的 BLOCK 都算命中。放行判定不用这个函数，只用严格的 parseSpecRuling。
 */
function isSpecRulingHeadLine(body: string): boolean {
  // 撤销要松（opus / kimi 审 ee229448）：只看首行会被开头空行、HTML 注释、未覆盖的 Markdown 前缀绕过。
  // 改为全文任意位置出现「SPEC…独审裁定」（容许中间空白、全/半角）即视为裁定类评论；
  // 它若不是合规 PASS，就撤销。宁可多撤，不可漏撤。
  return /SPEC\s*独审裁定/i.test(body.normalize("NFKC"));
}

/**
 * spec 是否已裁定放行。只认 orchestrator 的评论，按时间序推进，规则不对称：
 *   - 放行要严：首行必须恰为 parseSpecRuling 认的合规 PASS，且有效（非作者、证据齐、摘要等于当前正文），
 *     正文其余处也不含驳回词，才放行；
 *   - 撤销要松：正文任意处出现「SPEC 独审裁定」（不论位置、前缀、是否合规 PASS/BLOCK）
 *     或命中驳回词，一律撤销——不合规的 BLOCK 也撤销，不能让格式稍有偏差的撤销退化成放行；
 *   - 其余自由文本（既不含「SPEC 独审裁定」也不含驳回词）不改变当前状态，不区分票或评论的创建日期。
 * 拿不准（既不是合规 PASS 也不确定是否该撤销）一律按未放行处理。
 */
export function isSpecApproved(spec: ChildIssue, orchestrator: string): boolean {
  const mine = spec.comments
    .filter((c) => c.author === orchestrator)
    .sort((a, b) => (a.createdAt < b.createdAt ? -1 : a.createdAt > b.createdAt ? 1 : 0));
  let approved = false;
  for (const c of mine) {
    const ruling = parseSpecRuling(c.body);
    const compliantPass = ruling !== null && ruling.verdict === "PASS" && specRulingProblem(ruling, spec.number, spec.body) === null && !REJECT_RE.test(c.body);
    if (compliantPass) approved = true;
    else if (isSpecRulingHeadLine(c.body) || REJECT_RE.test(c.body)) approved = false;
  }
  return approved;
}

// ── 图关判据：残雾必须有去向（纯函数） ─────────────────────────────────────────

/** 截取正文里某个 ## 标题到下一个 ## 标题之间的段落；不存在返回 null。 */
function extractSection(body: string, heading: string): string | null {
  const lines = body.split("\n");
  let start = -1;
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]!;
    if (/^#{1,6}\s+/.test(line) && line.includes(heading)) {
      start = i;
      break;
    }
  }
  if (start < 0) return null;
  const out: string[] = [];
  for (let i = start + 1; i < lines.length; i++) {
    if (/^#{1,6}\s+/.test(lines[i]!)) break;
    out.push(lines[i]!);
  }
  return out.join("\n");
}

/** 一条残雾是否有去向：毕业成票（#号）/ 明写搁置 / 移 Out of scope。 */
function fogItemResolved(item: string): boolean {
  if (/#\d+/.test(item)) return true;
  if (/issues\/\d+/.test(item)) return true;
  if (/搁置/.test(item)) return true;
  if (/out of scope/i.test(item)) return true;
  return false;
}

/**
 * 返回「## Not yet specified」段中尚无去向的残雾条目（列表项）。
 * 空数组 = 残雾全部有去向（或没有残雾段）。关图前必须为空。
 */
export function unresolvedFog(body: string): string[] {
  const section = extractSection(body, "Not yet specified");
  if (section === null) return [];
  const items: string[] = [];
  for (const line of section.split("\n")) {
    const t = line.trim();
    if (/^[-*•]\s+/.test(t) || /^\d+[.、]\s+/.test(t)) items.push(t);
  }
  return items.filter((i) => !fogItemResolved(i));
}

// ── spec 拆票计划解析（纯函数） ────────────────────────────────────────────────

export interface ImplTicketPlan {
  id: string;
  title: string;
  summary?: string;
  dependsOn: string[];
  rulings: number[];
}

function extractJsonFences(text: string): string[] {
  const out: string[] = [];
  const re = /```(?:json)?\s*\n([\s\S]*?)```/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text)) !== null) {
    if (m[1]) out.push(m[1]!);
  }
  return out;
}

function tryParsePlan(text: string): ImplTicketPlan[] | null {
  let obj: unknown;
  try {
    obj = JSON.parse(text);
  } catch {
    return null;
  }
  if (!obj || typeof obj !== "object") return null;
  const tickets = (obj as { tickets?: unknown }).tickets;
  if (!Array.isArray(tickets) || tickets.length === 0) return null;
  const out: ImplTicketPlan[] = [];
  for (const t of tickets) {
    if (!t || typeof t !== "object") return null;
    const o = t as Record<string, unknown>;
    if (typeof o.id !== "string" || typeof o.title !== "string") return null;
    // 依赖与裁定票号有一项畸形就整份计划无效：丢掉一项会少一条 blocking 边或一条裁定挂接。
    const dependsOn = o.depends_on ?? [];
    const rulings = o.rulings ?? [];
    if (!Array.isArray(dependsOn) || !dependsOn.every((x) => typeof x === "string")) return null;
    if (!Array.isArray(rulings) || !rulings.every((x) => Number.isSafeInteger(x) && x > 0)) return null;
    out.push({
      id: o.id,
      title: o.title,
      summary: typeof o.summary === "string" ? o.summary : undefined,
      dependsOn: dependsOn as string[],
      rulings: rulings as number[],
    });
  }
  return out;
}

/**
 * 从 spec 正文解析机器可读拆票计划（由 spec 起草子代理在
 * 「## 实施票拆分（机器可读）」节内用 wayfinder-split 标记 + json 围栏产出）。
 * 有标记只取标记后的第一个围栏，标记后没有完整围栏也返回 null；无标记才兜底扫全文 json 围栏。解析不出或含畸形项返回 null（不建票）。
 */
export function parseSplitPlan(specBody: string): ImplTicketPlan[] | null {
  // 有标记就只认标记后的第一个围栏：它畸形时不退回别的围栏（可能是示例），整份计划按无效处理。
  // 有标记但其后没有完整围栏：同样按无效处理，不退回扫全文（标记前的围栏可能是示例）。
  const marker = specBody.indexOf("wayfinder-split");
  if (marker >= 0) {
    const marked = extractJsonFences(specBody.slice(marker))[0];
    return marked === undefined ? null : tryParsePlan(marked);
  }
  const candidates = extractJsonFences(specBody);
  for (const text of candidates) {
    const plan = tryParsePlan(text);
    if (plan) return plan;
  }
  return null;
}

// ── DAG 走查器（纯函数）：tracker 状态 → 触发动作 ─────────────────────────────

/**
 * 单张图的走查。状态机（带实装图的完整生命周期）：
 *   走图中 → 图清(draft_spec) → spec 待独审 → spec 独审裁定 PASS(split) → 实装中 → 实装全关(close)。
 * 每个动作的触发条件在该动作执行后必然失效（stateless 幂等的根基）：
 *   draft_spec 后 spec 子票出现；split 后实装票出现；close 后图变 CLOSED。
 */
export function analyzeMap(map: MapState, opts: WalkOptions): Analysis {
  if (map.state !== "OPEN") return { phase: "已关（跳过）", actions: [] };
  if (isPureDecisionMap(map)) return { phase: "纯决策图（v1 不碰，spec 出图人工）", actions: [] };

  const spec = map.children.filter(isSpecTicket);
  const impl = map.children.filter(isImplTicket);
  const decision = map.children.filter(isDecisionTicket);

  // 决策票未全关：还在走图，机器不替人裁，也不越过未决决策去开 spec。
  if (decision.some((c) => c.state === "OPEN")) {
    return { phase: "走图中（决策票未全关）", actions: [] };
  }

  // 图清：无 spec、无实装票，且全部子票（决策票）已关。
  if (spec.length === 0 && impl.length === 0) {
    if (decision.length > 0 && map.children.every((c) => c.state === "CLOSED")) {
      return {
        phase: "图清 → 起草 spec 草案并开图内 spec 票（待非作者独审）",
        actions: [{ kind: "draft_spec", map: map.number }],
      };
    }
    return { phase: "无决策子票（新图/空图，无动作）", actions: [] };
  }

  // spec 已存在：先判是否该拆票（幂等——拆到一半的图按计划补拆）。
  if (spec.length > 0) {
    const s = spec[0]!;
    if (s.state === "OPEN" && isSpecApproved(s, opts.orchestrator)) {
      const plan = parseSplitPlan(s.body);
      if (plan === null) {
        // 无机器可读拆票计划：actor 拿不到计划就不建票（只报「留人工」），impl 恒空 ⟹
        // 每轮重触发（stateless 无「已触发过」记忆），直到人工把计划补进 spec 正文。
        // 手动拆出的 map 直挂票能让本分支不再命中，但 releaseTicket 不放行计划外的直挂票，须补计划后经拆票迁移。
        if (impl.length === 0) {
          return {
            phase: "spec 已裁定 PASS → 拆 tracer-bullet 实装票",
            actions: [{ kind: "split_impl_tickets", map: map.number, spec: s.number }],
          };
        }
      } else {
        // 与 actSplitImpl 同口径：按身份标记（旧票按标题）对上计划项；hold 标签停放的已发布票也算拆齐。
        const complete = plan.every((t) =>
          impl.some((i) => (i.body.includes(splitIdentity(s.number, t.id)) || i.title.startsWith(`[impl] ${t.id} `)) &&
            i.body.includes(splitReceipt(s.number, s.body, t.id)) &&
            (i.state === "CLOSED" || i.labels.includes("ready-for-agent") || i.labels.some((l) => HOLD_LABELS.includes(l)))),
        );
        if (!complete) {
          return {
            phase: "spec 已裁定 PASS → 拆 tracer-bullet 实装票（补拆缺失票）",
            actions: [{ kind: "split_impl_tickets", map: map.number, spec: s.number }],
          };
        }
      }
    } else if (s.state === "OPEN") {
      return { phase: "spec 待非作者独审裁定（无有效 PASS 记录）", actions: [] };
    }
    // spec 已关（或已批准且拆齐）→ 落到实装票判定。
  }

  // 实装票判定。
  if (impl.length > 0) {
    const allImplClosed = impl.every((c) => c.state === "CLOSED");
    if (allImplClosed) {
      const fog = unresolvedFog(map.body);
      if (fog.length === 0) {
        return {
          phase: "实装票全关 + 图关判据满足 → 起草图关 comment 并 close map",
          actions: [{ kind: "close_graph", map: map.number }],
        };
      }
      return {
        phase: `实装票全关但残雾无去向（${fog.length} 条）→ 不关图，留人工`,
        actions: [],
      };
    }
    return { phase: "实装中（工蜂拾取 / 评审 / 双审与 CI 通过后合入）", actions: [] };
  }

  // 有 spec、无实装票、且 spec 已关（异常）。
  return { phase: "spec 已关但无实装票（异常，人工处置）", actions: [] };
}

/** 纯函数走查器：单图 → 动作清单。 */
export function walkGraph(map: MapState, opts: WalkOptions): Action[] {
  return analyzeMap(map, opts).actions;
}

/** 纯函数走查器：多图 → 动作清单（每轮重算 ready 集）。 */
export function walkGraphs(maps: MapState[], opts: WalkOptions): Action[] {
  return maps.flatMap((m) => analyzeMap(m, opts).actions);
}

// ── 队列分类与 sandcastle 释放规划（#1084 追加：控制面交棒链，纯函数） ─────────

/** 全仓 ready-for-agent 票的归一化视图（含父图 spec 批准态）。 */
export interface ReadyTicket {
  number: number;
  title: string;
  labels: string[];
  assignees: string[];
  /** open 阻塞边数量（只计 state=OPEN 的 blocker）。 */
  blockedBy: number;
  /** 所属 open map 的 spec 是否已批准；null = 不在任何 open map 下（含图外 spec/无主票）。 */
  specApproved: boolean | null;
  /** 本票 open 的 sub_issues 数（来自 map 子树；不在子树里为 undefined）。>0 = 汇总票，不放行。 */
  openChildren?: number;
  /** 祖先链上确有 SPEC 节点（区别于只继承 map 的 SPEC 批准态的 map 直挂票）。 */
  underSpec?: boolean;
}

/** 每轮五桶 + 待释放清单，一次算清（分类判据见 classifyTicket）。 */
export type TicketBucket =
  | "blocked"   // 有 open blocker，工蜂不可拾取
  | "claimed"   // 已 assign（人工认领或工蜂运行中，无 sandcastle）
  | "running"   // 已 assign 且仍带 sandcastle（claim 与摘 label 之间的瞬态）
  | "released"  // 未 assign + 无 blocker + 带 sandcastle（工蜂可拾取）
  | "eligible"  // 未 assign + 无 blocker + 无 sandcastle + 合资格实装票（待释放）
  | "held";     // 未 assign + 无 blocker + 无 sandcastle + 不合资格（决策/spec/未批准 spec 等）

/** gh issue list 的 blockedBy 结构：totalCount 含已关 blocker，须按 nodes.state 数 open。 */
export interface BlockedBySummary {
  nodes?: Array<{ state?: string }>;
  totalCount?: number;
}

/** open blocker 数量（纯函数）。 */
export function openBlockerCount(b: BlockedBySummary | undefined): number {
  if (!b) return 0;
  if (Array.isArray(b.nodes)) return b.nodes.filter((n) => n.state === "OPEN").length;
  return b.totalCount ?? 0;
}

/** 单票分类（纯函数）：五桶判据，只吃归一化视图。 */
export function classifyTicket(t: ReadyTicket, label = releaseLabel()): TicketBucket {
  const hasReleaseLabel = t.labels.includes(label);
  if (label === QUEUE_LABEL && t.labels.includes("sandcastle")) return "held";
  if (t.blockedBy > 0) return "blocked";
  // 已有负责人（任何 assignee）一律不放行：负责人是否仍活跃由人/审计判断，引擎不替人释放认领。
  if (t.assignees.length > 0) return hasReleaseLabel ? "running" : "claimed";
  if (hasReleaseLabel) return "released";
  if (t.labels.some((l) => HOLD_LABELS.includes(l))) return "held";
  // 汇总票（TB 汇验等）的工作由子票承担，子票未全关前不放行。
  if ((t.openChildren ?? 0) > 0) return "held";
  if (isImplCandidate(t) && t.specApproved === true && enteredByRule(t)) return "eligible";
  return "held";
}

/**
 * 进放行队列的两条路：
 *   - 带 ready-for-agent（#1084 原口径，含 map 直挂实装票）；
 *   - 只带 wayfinder:impl 的票，须祖先链上确有一张 SPEC（/to-tickets 从 SPEC 拆出的叶子）。
 * map 直挂、未挂 ready-for-agent 的 wayfinder:impl 票不因加扫标签而被放行。
 */
function enteredByRule(t: ReadyTicket): boolean {
  return t.labels.includes("ready-for-agent") || t.underSpec === true;
}

/** 单票不放行/放行原因（纯函数，供 --explain 与 dry-run 报告）。 */
export function explainTicket(t: ReadyTicket): string {
  const b = classifyTicket(t);
  if (b === "blocked") return `blocked（open blocker ${t.blockedBy}）`;
  if (b === "claimed") return `claimed（assignee ${t.assignees.join(",")}）`;
  if (b === "running") return `running（已 assign 且带 ${releaseLabel()}）`;
  if (b === "released") return `released（已带 ${releaseLabel()}）`;
  if (b === "eligible") return "eligible（实装票 + 祖先链 SPEC 已批准 + 未 assign + 无 blocker）";
  const hold = t.labels.filter((l) => HOLD_LABELS.includes(l));
  if (hold.length) return `held（人闸标签 ${hold.join(",")}）`;
  if (!isImplCandidate(t)) return "held（非实装票：无 [impl] 标题 / wayfinder:impl 标签，或为决策票）";
  if ((t.openChildren ?? 0) > 0) return `held（汇总票，open 子票 ${t.openChildren}）`;
  if (t.specApproved === null) return "held（不在任何 open map 子树内）";
  if (t.specApproved === false) return "held（所属 SPEC 未批准）";
  return "held（map 直挂票未挂 ready-for-agent，且祖先链上无 SPEC）";
}

/** 子树遍历结果：批准态 + 祖先链上是否确有 SPEC（纯函数产物）。 */
export interface SpecTreeFacts {
  approved: Map<number, boolean>;
  underSpec: Set<number>;
  /** 本票批准态依赖的 SPEC 身份；执行时重新读取，不复用批准布尔值。 */
  requiredSpecs: Map<number, number[]>;
  /** 授权来自 map 直挂 SPEC（祖先链上无 SPEC 节点）的票：放行时须是该 SPEC 拆票计划里的票。 */
  planBound: Set<number>;
}

/**
 * 图内子票 → 批准态（纯函数）。
 *
 * 判据（wayfinder-workflow.md「队列交棒」：只放行「已批准 spec/DAG」下的实装票）：
 *   - 祖先链上有 SPEC 节点的票：链上每一张 SPEC 都已批准才算批准（嵌套 SPEC 不能绕过上层驳回）；
 *     #1323 → SPEC #1340 → TB 汇总 → 叶 → 纵片 全链由此拿到 #1340 的批准态（图审计 2026-10-20 第 14 条）；
 *   - 祖先链上没有 SPEC 的票（map 直挂票及其子票）：继承 map 直挂 SPEC 的批准态（#1084 原口径）。
 * 不在任何 open map 子树里的票不进索引（specApproved=null）。
 */
export function buildSpecTreeFacts(maps: MapState[], orchestrator: string): SpecTreeFacts {
  const approved = new Map<number, boolean>();
  const underSpec = new Set<number>();
  const requiredSpecs = new Map<number, number[]>();
  const planBound = new Set<number>();
  const specOk = (s: ChildIssue) => currentSpecApproved(s, s.number, orchestrator);
  for (const m of maps) {
    if (m.state !== "OPEN") continue;
    const spec = m.children.find(isSpecTicket);
    const mapApproved = spec !== undefined && specOk(spec);
    const visited = new Set<number>();
    // chain：祖先链上的 SPEC 情况；null = 链上尚无 SPEC。
    const visit = (node: ChildIssue, chain: boolean | null, ancestors: number[]) => {
      if (visited.has(node.number)) return;
      visited.add(node.number);
      const value = chain === null ? mapApproved : chain;
      // 同一票若被多处挂（理论上 sub_issue 单父），任一路径未批准即按未批准，宁严勿宽。
      const prev = approved.get(node.number);
      approved.set(node.number, prev === undefined ? value : prev && value);
      const required = chain === null ? (spec ? [spec.number] : []) : ancestors;
      requiredSpecs.set(node.number, [...new Set([...(requiredSpecs.get(node.number) ?? []), ...required])]);
      if (chain !== null) underSpec.add(node.number);
      else planBound.add(node.number);
      const next = isSpecTicket(node) ? (chain === null ? specOk(node) : chain && specOk(node)) : chain;
      for (const c of node.children ?? []) visit(c, next, isSpecTicket(node) ? [...ancestors, node.number] : ancestors);
    };
    for (const c of m.children) visit(c, null, []);
  }
  // 同一票若另有一条 SPEC 子树路径，仍按须在计划内处理（宁严勿宽）。
  return { approved, underSpec, requiredSpecs, planBound };
}

/** 兼容旧签名：只要批准态。 */
export function buildSpecApprovalIndex(maps: MapState[], orchestrator: string): Map<number, boolean> {
  return buildSpecTreeFacts(maps, orchestrator).approved;
}

/** 子树内每张有 sub_issues 的票 → open 子票数（纯函数）。 */
export function buildOpenChildIndex(maps: MapState[]): Map<number, number> {
  const idx = new Map<number, number>();
  const visited = new Set<number>();
  const visit = (node: ChildIssue) => {
    if (visited.has(node.number)) return;
    visited.add(node.number);
    const kids = node.children ?? [];
    const fromKids = kids.filter((k) => k.state === "OPEN").length;
    const open = Math.max(fromKids, node.openSubIssues ?? 0);
    if (kids.length || node.openSubIssues !== undefined) idx.set(node.number, open);
    for (const k of kids) visit(k);
  };
  for (const m of maps) if (m.state === "OPEN") for (const c of m.children) visit(c);
  return idx;
}

/** 把 spec 批准态（及可选的 open 子票数）并入 ready 视图（纯函数）。 */
export function withSpecApproval(
  ready: ReadyTicket[],
  specIdx: Map<number, boolean>,
  openChildIdx?: Map<number, number>,
  underSpec?: Set<number>,
): ReadyTicket[] {
  return ready.map((t) => ({
    ...t,
    specApproved: specIdx.get(t.number) ?? null,
    ...(openChildIdx?.has(t.number) ? { openChildren: openChildIdx.get(t.number)! } : {}),
    ...(underSpec ? { underSpec: underSpec.has(t.number) } : {}),
  }));
}

/** 队列汇总（纯函数）：五桶计数 + 待释放（合资格实装票）号码清单。 */
export function summarizeQueue(tickets: ReadyTicket[]): {
  buckets: Record<TicketBucket, number>;
  eligible: number[];
} {
  const buckets: Record<TicketBucket, number> = {
    blocked: 0,
    claimed: 0,
    running: 0,
    released: 0,
    eligible: 0,
    held: 0,
  };
  const eligible: number[] = [];
  for (const t of tickets) {
    const b = classifyTicket(t);
    buckets[b]++;
    if (b === "eligible") eligible.push(t.number);
  }
  return { buckets, eligible };
}

/** 控制面释放计划：合资格实装票 → 挂 sandcastle（不无差别放行历史 ready-for-agent）。 */
export function planReleases(tickets: ReadyTicket[]): number[] {
  return summarizeQueue(tickets).eligible;
}

// ── gh 封装（IO 层，非纯） ─────────────────────────────────────────────────────

// #1084 追加：GitHub 查询有限重试 + 指数退避 + fail-loud。单次网络超时/瞬时失败
// 不得杀死整轮——读路径重试，耗尽后才 fail-loud（抛错），由轮询壳 catch 后继续下一轮。
// 写路径（ghOnce）不重试：issue create 非幂等，重试会造重复票；幂等性交给
// stateless 每轮重算（本轮失败下一轮自然补做）。
const GH_MAX_ATTEMPTS = Number(process.env.WAYFINDER_GH_MAX_ATTEMPTS ?? 4);
const GH_BASE_BACKOFF_MS = Number(process.env.WAYFINDER_GH_BASE_BACKOFF_MS ?? 1000);

function sleepSync(ms: number): void {
  // execSync 是同步调用；退避用 Atomics.wait 做可中断的同步睡眠（无 TTY 也可用）。
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);
}

/** 单次 gh 调用（写路径用；读路径走 gh() 重试）。 */
function ghOnce(args: string): string {
  return execSync(`gh ${args}`, {
    encoding: "utf8",
    env: GH_ENV,
    maxBuffer: 32 * 1024 * 1024,
  }).trim();
}

/** 读路径 gh 调用：有限重试 + 指数退避，耗尽后 fail-loud。 */
function gh(args: string): string {
  let lastErr: unknown;
  for (let attempt = 1; attempt <= GH_MAX_ATTEMPTS; attempt++) {
    try {
      return ghOnce(args);
    } catch (e) {
      lastErr = e;
      if (attempt < GH_MAX_ATTEMPTS) {
        const backoff = GH_BASE_BACKOFF_MS * 2 ** (attempt - 1);
        console.error(
          `[wayfinder_engine] gh 查询失败（第 ${attempt}/${GH_MAX_ATTEMPTS} 次，${backoff}ms 后重试）：${String(e).slice(0, 200)}`,
        );
        sleepSync(backoff);
      }
    }
  }
  throw new Error(
    `gh 查询重试 ${GH_MAX_ATTEMPTS} 次后仍失败（fail-loud）：${String(lastErr).slice(0, 500)}`,
  );
}

function shellQuote(s: string): string {
  return `'${s.replace(/'/g, `'\\''`)}'`;
}

function issueUrl(number: number): string {
  const repo = GH_ENV.GH_REPO ?? "xy7365527-lang/NewChanlun";
  return `https://github.com/${repo}/issues/${number}`;
}

function normalizeState(s: string): "OPEN" | "CLOSED" {
  return s.toLowerCase() === "closed" ? "CLOSED" : "OPEN";
}

interface RawChild {
  number: number;
  title: string;
  body?: string | null;
  /** REST 列举时才有：作者与是否为 PR，拆票恢复据此只认编排账号自己建的 issue。 */
  user?: { login?: string } | null;
  pull_request?: unknown;
  state: string;
  labels?: Array<{ name: string }>;
  assignees?: Array<{ login: string }>;
  issue_dependencies_summary?: { blocked_by?: number };
  sub_issues_summary?: { total?: number; completed?: number };
}

interface RawComment {
  user: { login: string };
  body?: string | null;
  created_at: string;
}

/** 子树递归深度上限（map → SPEC → TB → 叶 → 纵片 = 4 层，留余量）。 */
const MAX_TREE_DEPTH = 8;

function fetchChildren(
  mapNumber: number,
  depth = 0,
  visited: Set<number> = new Set([mapNumber]),
): ChildIssue[] {
  const raw = JSON.parse(
    gh(`api --paginate repos/${GH_ENV.GH_REPO}/issues/${mapNumber}/sub_issues`),
  ) as RawChild[];
  return raw.map((c) => {
    const child: ChildIssue = {
      number: c.number,
      title: c.title,
      body: c.body ?? "",
      state: normalizeState(c.state),
      labels: (c.labels ?? []).map((l) => l.name),
      assignees: (c.assignees ?? []).map((a) => a.login),
      blockedBy: c.issue_dependencies_summary?.blocked_by ?? 0,
      comments: [],
    };
    if (c.sub_issues_summary?.total !== undefined) {
      child.openSubIssues = Math.max(0, c.sub_issues_summary.total - (c.sub_issues_summary.completed ?? 0));
    }
    // 只对 spec 子票拉评论（批准检测需要）；决策票的评论在起草 spec 时才按需拉。
    if (isSpecTicket(child)) child.comments = fetchComments(child.number);
    // 递归子树（只对确有 sub_issues 的票发请求）；防环 + 深度上限。
    if ((c.sub_issues_summary?.total ?? 0) > 0 && depth + 1 < MAX_TREE_DEPTH && !visited.has(c.number)) {
      visited.add(c.number);
      child.children = fetchChildren(c.number, depth + 1, visited);
    }
    return child;
  });
}

function fetchComments(issueNumber: number, read: (args: string) => string = gh): IssueComment[] {
  const raw = JSON.parse(
    read(`api --paginate repos/${GH_ENV.GH_REPO}/issues/${issueNumber}/comments`),
  ) as RawComment[];
  return raw.map((c) => ({
    author: c.user.login,
    body: c.body ?? "",
    createdAt: c.created_at,
  }));
}

/** 写前从 tracker 取当前正文及全部评论，复用扫描阶段的唯一裁定合同。 */
function readCurrentSpec(number: number, read: (args: string) => string = gh): ChildIssue {
  const v = JSON.parse(read(`issue view ${number} --json number,title,body,state`));
  return { number: v.number, title: v.title, body: v.body ?? "", state: normalizeState(v.state),
    labels: [], assignees: [], blockedBy: 0, comments: fetchComments(number, read) };
}

function currentSpecApproved(spec: ChildIssue, number: number, orchestrator: string): boolean {
  return spec.number === number && isSpecTicket(spec) && spec.state === "OPEN" && isSpecApproved(spec, orchestrator);
}

export function fetchOpenMaps(): MapState[] {
  const out = gh(
    `issue list --label wayfinder:map --state open --limit 100 --json number,title,body,state,labels`,
  );
  const raw = JSON.parse(out) as Array<{
    number: number;
    title: string;
    body?: string | null;
    state: string;
    labels: Array<{ name: string }>;
  }>;
  return raw.map((m) => ({
    number: m.number,
    title: m.title,
    body: m.body ?? "",
    state: normalizeState(m.state),
    labels: m.labels.map((l) => l.name),
    children: fetchChildren(m.number),
  }));
}

/**
 * 扫描集 = open 的 ready-for-agent ∪ wayfinder:impl（spec 批准态由 withSpecApproval 并入）。
 * #1340 正文约定「ready-for-agent 表示已批准可拆票，不是可直接拾取」，TB 叶子多只带 wayfinder:impl，
 * 只扫 ready-for-agent 会让它们永远不进扫描集（图审计 2026-10-20 结论 2）。
 */
export function fetchReadyTickets(): ReadyTicket[] {
  const seen = new Map<number, ReadyTicket>();
  for (const label of SCAN_LABELS) {
    const got = fetchLabelled(label);
    if (got.length >= SCAN_LIMIT) console.error(`[wayfinder_engine] ⚠ ${label} 扫描到 ${got.length} 张，已达上限 ${SCAN_LIMIT}，可能截断`);
    for (const t of got) if (!seen.has(t.number)) seen.set(t.number, t);
  }
  return [...seen.values()].sort((a, b) => a.number - b.number);
}

const SCAN_LABELS = ["ready-for-agent", IMPL_LABEL];
const SCAN_LIMIT = 500;

function fetchLabelled(label: string): ReadyTicket[] {
  const out = gh(
    `issue list --label ${shellQuote(label)} --state open --limit ${SCAN_LIMIT} --json number,title,labels,assignees,blockedBy`,
  );
  const raw = JSON.parse(out) as Array<{
    number: number;
    title: string;
    labels?: Array<{ name: string }>;
    assignees?: Array<{ login: string }>;
    blockedBy?: BlockedBySummary;
  }>;
  return raw.map((r) => ({
    number: r.number,
    title: r.title,
    labels: (r.labels ?? []).map((l) => l.name),
    assignees: (r.assignees ?? []).map((a) => a.login),
    blockedBy: openBlockerCount(r.blockedBy),
    specApproved: null,
  }));
}

/** 写前复核（纯函数）：读到的单票现状仍可放行才返回 null，否则返回原因。 */
export function recheckBeforeRelease(v: {
  state?: string;
  labels?: Array<{ name: string }>;
  assignees?: Array<{ login: string }>;
  blockedBy?: BlockedBySummary;
}, label = releaseLabel()): string | null {
  if ((v.state ?? "OPEN").toUpperCase() !== "OPEN") return "票已关闭";
  if ((v.assignees ?? []).length > 0) return `已有负责人 ${(v.assignees ?? []).map((a) => a.login).join(",")}`;
  if (openBlockerCount(v.blockedBy) > 0) return "有 open blocker";
  const names = (v.labels ?? []).map((l) => l.name);
  if (names.includes(label)) return `已带 ${label}`;
  const other = label === QUEUE_LABEL ? "sandcastle" : QUEUE_LABEL;
  if (names.includes(other)) return `已带另一放行标签 ${other}`;
  if (label === QUEUE_LABEL && names.some(name => name.startsWith("agent:"))) return "旧 agent 标签";
  const hold = names.filter((l) => HOLD_LABELS.includes(l));
  if (hold.length) return `人闸标签 ${hold.join(",")}`;
  return null;
}

/**
 * 释放一张合资格实装票：挂 sandcastle（add-label 幂等，写路径 ghOnce）。
 * 挂前重读单票与批准态依赖的全部 SPEC；身份来自同一遍子树遍历，批准布尔值不跨写入复用。返回 null = 已挂。
 * via = "plan"：授权来自 map 直挂 SPEC，票必须是该 SPEC 当前拆票计划里的票并带当前发布凭据；
 * via = "tree"：票在 SPEC 节点的子树里，授权来自祖先链上每张 SPEC 的当前 PASS。两种都核拆票身份标记。
 */
export function releaseTicket(
  number: number,
  authorization: { specs: number[]; orchestrator: string; via: "plan" | "tree" },
  io: { read: (args: string) => string; write: (args: string) => string } = { read: gh, write: ghOnce },
  label = releaseLabel(),
): string | null {
  const v = JSON.parse(io.read(`issue view ${number} --json title,body,state,labels,assignees,blockedBy`));
  const why = recheckBeforeRelease(v, label);
  if (why) return why;
  if (!authorization.specs.length) return "缺父 SPEC 身份，不能沿用扫描批准态";
  for (const spec of authorization.specs) {
    const current = readCurrentSpec(spec, io.read);
    if (!currentSpecApproved(current, spec, authorization.orchestrator)) {
      return `SPEC #${spec} 当前无有效 PASS`;
    }
    // map 直挂 SPEC 授权的票只认它当前获审拆票计划里的票：有标记的按身份、旧票按标题对上计划项，
    // 且都须带当前正文的发布凭据。计划外的旧票、手工票或 SPEC 没有机器可读拆票节时不放行
    // （旧票先经拆票迁移补身份与凭据）。SPEC 子树里的票由祖先链 PASS 授权，带拆票标记的同样核计划。
    const tagged = (v.body ?? "").includes(`<!-- wayfinder-ticket:${spec}:`);
    const plan = parseSplitPlan(current.body);
    const item = plan?.find(t => tagged
      ? (v.body ?? "").includes(splitIdentity(spec, t.id))
      : v.title?.startsWith(`[impl] ${t.id} `));
    if (!item) {
      if (authorization.via === "tree" && !tagged) continue;
      if (tagged) return `SPEC #${spec} 不再包含该拆票身份`;
      return plan ? `不在 SPEC #${spec} 当前拆票计划内` : `SPEC #${spec} 没有机器可读拆票计划，不放行计划外的票`;
    }
    if (!(v.body ?? "").includes(splitReceipt(spec, current.body, item.id))) {
      return `SPEC #${spec} 拆票尚未完整发布`;
    }
  }
  io.write(`issue edit ${number} --add-label ${label}`);
  return null;
}

// ── 状态页（#1084 追加：五桶分明，不把 sandcastle 空误写成 ready-for-agent 空） ──

const STATUS_PATH = ".sandcastle/logs/wayfinder-status.md";

/** 状态页正文（纯函数渲染，便于测试）。 */
export function renderStatus(
  opts: { dryRun: boolean; stamp: string },
  maps: MapState[],
  ready: ReadyTicket[],
  summary: ReturnType<typeof summarizeQueue>,
): string {
  const b = summary.buckets;
  const eligibleList = summary.eligible.length
    ? ` → ${summary.eligible.map((n) => `#${n}`).join(" ")}`
    : "";
  return [
    `# wayfinder_engine 控制面状态（${opts.stamp}，${opts.dryRun ? "dry-run" : "live"}）`,
    "",
    `- open wayfinder:map：${maps.length} 张`,
    `- 扫描集 open（ready-for-agent ∪ wayfinder:impl）：${ready.length} 张`,
    `  - 已获 ${releaseLabel()} 拾取权（可拾取）：${b.released}`,
    `  - blocked（有 open blocker）：${b.blocked}`,
    `  - claimed（已 assign）：${b.claimed}`,
    `  - running（已 assign 且带 ${releaseLabel()}）：${b.running}`,
    `  - 待释放（合资格实装票，本轮挂 ${releaseLabel()}）：${b.eligible}${eligibleList}`,
    `  - 不合资格（决策/spec/未批准 spec/人闸标签等，不放行）：${b.held}`,
    "",
  ].join("\n");
}

function writeStatus(
  cfg: EngineConfig,
  stamp: string,
  maps: MapState[],
  ready: ReadyTicket[],
  summary: ReturnType<typeof summarizeQueue>,
): void {
  mkdirSync(".sandcastle/logs", { recursive: true });
  writeFileSync(STATUS_PATH, renderStatus({ dryRun: cfg.dryRun, stamp }, maps, ready, summary) + "\n", "utf8");
}

// ── 动作执行器（IO 层；dry-run 下不调用） ──────────────────────────────────────

export interface EngineConfig {
  maintenanceRoot?: string;
  maintenanceEsConfig?: string;
  orchestrator: string;
  dryRun: boolean;
  pollSeconds: number;
  specModel: string;
  specProvider: string;
  once: boolean;
  /** 逐票打印分桶与原因（dry-run 报告用）。 */
  explain: boolean;
}

function createIssue(
  title: string,
  body: string,
  labels: string[],
): { number: number; id: number } {
  const tmp = join(
    tmpdir(),
    `wayfinder_issue_${Date.now()}_${Math.random().toString(36).slice(2)}.md`,
  );
  writeFileSync(tmp, body, "utf8");
  try {
    const labelArgs = labels.map((l) => `--label ${shellQuote(l)}`).join(" ");
    // ghOnce：issue create 非幂等，不重试（重试会造重复票）。
    const out = ghOnce(
      `issue create --title ${shellQuote(title)} --body-file ${shellQuote(tmp)} ${labelArgs}`,
    );
    const m = out.match(/issues\/(\d+)\s*$/);
    if (!m) throw new Error(`无法从 gh issue create 输出解析票号：${out}`);
    const number = Number(m[1]);
    const id = Number(gh(`api repos/${GH_ENV.GH_REPO}/issues/${number} --jq .id`));
    return { number, id };
  } finally {
    rmSync(tmp, { force: true });
  }
}

function addSubIssue(mapNumber: number, childId: number): void {
  // sub_issue_id 须为整型（数据库 id），用 -F（typed）而非 -f（string），否则 422。
  // ghOnce：写路径不重试（幂等性交给下一轮 stateless 重算）。
  ghOnce(
    `api --method POST repos/${GH_ENV.GH_REPO}/issues/${mapNumber}/sub_issues -F sub_issue_id=${childId}`,
  );
}

function addBlockingEdge(childNumber: number, blockerDbId: number): void {
  ghOnce(
    `api --method POST repos/${GH_ENV.GH_REPO}/issues/${childNumber}/dependencies/blocked_by -F issue_id=${blockerDbId}`,
  );
}

function issueDbId(number: number): number {
  return Number(gh(`api repos/${GH_ENV.GH_REPO}/issues/${number} --jq .id`));
}

/**
 * 纯函数：解析并校验 spec 起草子代理配置（#1588）。
 * provider 只认 claude-cliproxy；model 只认主控同型。非法值 throw，不静默回退默认。
 */
export function resolveSpecDrafter(env: Record<string, string | undefined>): {
  specProvider: string;
  specModel: string;
} {
  const specProvider = env.WAYFINDER_SPEC_PROVIDER ?? DEFAULT_SPEC_PROVIDER;
  const specModel = env.WAYFINDER_SPEC_MODEL ?? DEFAULT_SPEC_MODEL;
  if (specProvider !== DEFAULT_SPEC_PROVIDER) {
    throw new Error(
      `[FAIL-loud #1588] WAYFINDER_SPEC_PROVIDER=${specProvider} 不受支持：起草子代理只走 ${DEFAULT_SPEC_PROVIDER}（Claude Code CLI 经 CLIProxyLocal）`,
    );
  }
  if (!SUPPORTED_SPEC_MODELS.includes(specModel)) {
    throw new Error(
      `[FAIL-loud #1588] WAYFINDER_SPEC_MODEL=${specModel} 不等于当前主控模型（${SUPPORTED_SPEC_MODELS.join(" / ")}）`,
    );
  }
  return { specProvider, specModel };
}

/** 纯函数：起草子代理的 Claude Code CLI 调用（无头 -p、禁用全部工具、不落会话）。prompt 走 stdin。 */
export function specDrafterCommand(specModel: string): { file: string; args: string[] } {
  return {
    file: "claude",
    args: ["-p", "--bare", "--model", specModel, "--output-format", "text", "--tools", "", "--no-session-persistence"],
  };
}

/**
 * 纯函数：起草子代理的子进程 env = 宿主 env + CLIProxyLocal 路由变量，并剔除 ANTHROPIC_API_KEY
 * （Claude Code 优先认它，继承下来会绕开 CLIProxyLocal；decision-claimer.mts claudeOnce 同款）。
 */
export function specDrafterEnv(
  base: NodeJS.ProcessEnv,
  proxyEnv: Record<string, string>,
): NodeJS.ProcessEnv {
  const env: NodeJS.ProcessEnv = { ...base, ...proxyEnv };
  delete env.ANTHROPIC_API_KEY;
  return env;
}

/**
 * 起草 spec 的子代理：Claude Code CLI 经 CLIProxyLocal，只读、无工具，输出即 spec 正文。
 * cwd 取临时目录，不让仓内 CLAUDE.md / 项目 hooks 混进起草上下文；路由密钥只进子进程 env。
 */
function runSpecDrafter(prompt: string, cfg: EngineConfig): string {
  const { specModel } = resolveSpecDrafter({
    WAYFINDER_SPEC_PROVIDER: cfg.specProvider,
    WAYFINDER_SPEC_MODEL: cfg.specModel,
  });
  const { file, args } = specDrafterCommand(specModel);
  const command = maintenanceCommand(file, args);
  return execFileSync(command.file, command.args, {
    encoding: "utf8",
    input: prompt,
    cwd: tmpdir(),
    env: specDrafterEnv(process.env, cliProxyEnv()),
    maxBuffer: 32 * 1024 * 1024,
    timeout: 15 * 60 * 1000,
  }).trim();
}

/** 拉一张图的全量上下文（供起草 spec / 组装图关 comment）。 */
function fetchMapContext(mapNumber: number): {
  number: number;
  title: string;
  body: string;
  children: Array<{ number: number; title: string; state: string; body: string; lastComment: string }>;
} {
  const map = JSON.parse(
    gh(`issue view ${mapNumber} --json number,title,body,state`),
  ) as { number: number; title: string; body: string; state: string };
  const children = fetchChildren(mapNumber);
  const ctx = children.map((c) => {
    const comments = fetchComments(c.number);
    return {
      number: c.number,
      title: c.title,
      state: c.state,
      body: c.body,
      lastComment: comments.length > 0 ? comments[comments.length - 1]!.body : "",
    };
  });
  return { number: map.number, title: map.title, body: map.body, children: ctx };
}

function truncate(s: string, n: number): string {
  return s.length <= n ? s : `${s.slice(0, n)}\n…（截断）`;
}

function buildSpecDraftPrompt(mapNumber: number): string {
  const ctx = fetchMapContext(mapNumber);
  const decisionList = ctx.children
    .filter((c) => c.state === "CLOSED")
    .map((c) => {
      return (
        `- #${c.number} ${c.title}\n` +
        `  正文：${truncate(c.body, 3000)}\n` +
        `  决议（末条评论）：${truncate(c.lastComment, 3000)}`
      );
    })
    .join("\n");

  return `你是一名 spec 起草子代理（只读文书，#1000 例外类）。为下面这张 wayfinder 图起草「图内实施总单 spec」（不出图，实施票在图内）。

## 硬性规则

1. 只读：不得创建/评论/关闭任何 issue，不得写任何仓库文件；只输出 spec 正文。
2. 输出格式（严格）：
   - 第一行必须是 H1 标题：\`# 📋 SPEC：<一句话主题>（map #${mapNumber} 实施总单）\`
   - 第二行声明：\`本 spec 是 map #${mapNumber} 的实施总单，实施票在图内。Part of #${mapNumber}。\`
   - 后续按需分节：\`## Problem Statement\` / \`## Solution\` / \`## Implementation Decisions\` / \`## Testing Decisions\` / \`## Out of Scope\`。
   - 末尾必须带「## 实施票拆分（机器可读）」节：先一行 \`<!-- wayfinder-split -->\`，然后一个 json 代码围栏，内容为：
     \`{"tickets":[{"id":"S1","title":"…","summary":"…","depends_on":[],"rulings":[<裁定票号>]},…]}\`
     id 用 S1/S2/…；depends_on 填依赖的其他 id（无则 []）；rulings 填该票逐条挂的裁定票号（数字数组）。
   - 除以上内容外，不输出任何前言/后语。
3. 口径：spec 是实施总单不是判决书——每条 Implementation Decision 挂裁定票号（正文用 #<号> 链接），决策正本在各自票内；本图已全关的决策票在下方给出。
4. 语言：简体中文。

## 图的现状（map #${mapNumber}）

${truncate(ctx.body, 20000)}

## 已关决策子票（决议在各自末条评论）

${decisionList || "（无）"}`;
}

/** 动作 1：图清 → 起草 spec → 开图内 spec 票 → 待非作者独审裁定。 */
function actDraftSpec(a: Extract<Action, { kind: "draft_spec" }>, cfg: EngineConfig): void {
  const mapNumber = a.map;
  const draft = runSpecDrafter(buildSpecDraftPrompt(mapNumber), cfg);

  // 拆 H1 标题与正文；声明行（本 spec 是 map #N 的实施总单）由本函数统一前置，
  // 起草稿里的同款声明行若存在则剥掉，避免重复。
  const lines = draft.split("\n");
  const h1Idx = lines.findIndex((l) => l.startsWith("# "));
  const title =
    h1Idx >= 0
      ? lines[h1Idx]!.replace(/^#\s+/, "").trim()
      : `📋 SPEC：实施总单（map #${mapNumber}）`;
  const rest = h1Idx >= 0 ? lines.slice(h1Idx + 1) : lines;
  while (rest.length > 0 && rest[0]!.trim() === "") rest.shift();
  if (rest.length > 0 && /实施总单/.test(rest[0]!) && /Part of #\d+/.test(rest[0]!)) rest.shift();
  while (rest.length > 0 && rest[0]!.trim() === "") rest.shift();
  const draftBody = rest.join("\n");

  const finalBody =
    `本 spec 是 map [#${mapNumber}](${issueUrl(mapNumber)}) 的实施总单，实施票在图内。Part of #${mapNumber}。\n\n` +
    `${draftBody}\n\n---\n待非作者独审（#1909）：起草者 ${cfg.specProvider}/${cfg.specModel}。独审 PASS 后由编排账号发「${SPEC_RULING_HEAD}」记录（格式与摘要见 .sandcastle/docs/graph-engineering.md「SPEC 裁定」），引擎读到有效 PASS 才拆实装票。\n`;

  const created = createIssue(title, finalBody, []);
  addSubIssue(mapNumber, created.id);
  console.log(`  ✓ 已开图内 spec 票 #${created.number} → 待非作者独审裁定`);
}

/** 身份在 create 内一起提交，关联失败或响应丢失后仍能从 REST 账本找回。 */
function splitIdentity(spec: number, id: string): string {
  return `<!-- wayfinder-ticket:${spec}:${encodeURIComponent(id)} -->`;
}

function splitReceipt(spec: number, body: string, id: string): string {
  return `<!-- wayfinder-published:${spec}:${specBodyDigest(body)}:${encodeURIComponent(id)} -->`;
}

const SPLIT_BODY_END = "<!-- wayfinder-ticket-end -->";
const SPLIT_LEGACY_HEAD = "## 迁移前原票正文";
const SPLIT_LEGACY_GOAL = "### 迁移前的目标（旧版计划，以上方当前目标为准）";

/**
 * 未发布实施票的正文（纯函数）。引擎写的部分（身份、SPEC 链接、决策链、目标，到 `wayfinder-ticket-end`
 * 标记为止）每次都按当前 SPEC 重写；标记以下是票上不属于引擎的文字，逐行保留在「迁移前原票正文」节下，
 * 其中的 SPEC 链接改成纯文字，保证全文只有当前这一个 `Part of [SPEC #n]`（DeepAgents 准入要求唯一）。
 * 早期引擎的票没有结束标记：只去掉身份行与那一行 SPEC 链接（它们由上方当前版本取代），旧的「目标」标题
 * 改成「迁移前的目标」，其后所有文字（旧目标与后来追加的验收条件、范围、人工说明）原样保留。
 * 已发布（带当前版回执）的票不经过本函数。
 */
export function splitTicketBody(identity: string, plannedBody: string, current: string | null | undefined): string {
  const head = `${plannedBody.replace(/\n+$/, "")}\n${SPLIT_BODY_END}\n`;
  const text = (current ?? "").replace(/\r\n/g, "\n");
  let kept: string;
  const end = text.indexOf(SPLIT_BODY_END);
  if (end >= 0) {
    kept = text.slice(end + SPLIT_BODY_END.length);
  } else {
    const lines = text.split("\n");
    if (lines[0] === identity) lines.shift();
    if (/^Part of \[SPEC #\d+\]/.test(lines[0] ?? "")) {
      lines.shift();
      const goal = lines.findIndex(l => /^## 目标（spec [^）]*）$/.test(l));
      if (goal >= 0) lines[goal] = SPLIT_LEGACY_GOAL;
    }
    kept = lines.join("\n");
  }
  kept = kept.replace(/^\s+|\s+$/g, "");
  if (kept.startsWith(SPLIT_LEGACY_HEAD)) kept = kept.slice(SPLIT_LEGACY_HEAD.length).replace(/^\s+/, "");
  kept = kept.replace(/Part of \[SPEC #(\d+)\]\([^)]*\)/g, "（迁移前记载：SPEC #$1）")
    .replace(/Part of \[SPEC #(\d+)\]/g, "（迁移前记载：SPEC #$1）");
  return kept ? `${head}\n${SPLIT_LEGACY_HEAD}\n\n${kept}\n` : head;
}

/**
 * 旧票迁移前的持有判定（纯函数），输入是票级动作锁内的新鲜读数。已关票执行器不会再动，不算持有。
 * 本机持有记录覆盖写 intent 后、挂镜像前的空窗；票面镜像在释放排空后才摘，是 GitHub 上可见的持有。
 */
export function migrationHold(v: {
  state?: string;
  labels?: Array<{ name: string }>;
  assignees?: Array<{ login: string }>;
}, claim: Pick<LocalClaim, "state" | "run_id"> | null): string | null {
  if (normalizeState(v.state ?? "OPEN") === "CLOSED") return null;
  const assignees = (v.assignees ?? []).map(a => a.login);
  if (assignees.length) return `已被 ${assignees.join(",")} 认领，等其取消认领后再迁移`;
  if (claim && claim.state !== "released") {
    return `正由 ${claim.run_id} 持有（${claim.state}），等 executor release 后再迁移`;
  }
  if ((v.labels ?? []).some(l => l.name === MIRROR_LABEL)) {
    return `票面仍有 ${MIRROR_LABEL} 镜像：持有未释放或释放未完成，排空后重跑 executor release 再迁移`;
  }
  return null;
}

/** 动作 2：先准备完整依赖图，再将实施票发布到现有释放流程。 */
async function actSplitImpl(a: Extract<Action, { kind: "split_impl_tickets" }>, cfg: EngineConfig): Promise<void> {
  const spec = readCurrentSpec(a.spec);
  if (!currentSpecApproved(spec, a.spec, cfg.orchestrator)) return;
  const plan = parseSplitPlan(spec.body);
  if (!plan) {
    console.error(`  ✗ spec #${a.spec} 无机器可读拆票节（wayfinder-split），无法自动拆票 → 留人工。`);
    return;
  }
  const ids = new Set(plan.map(t => t.id));
  if (ids.size !== plan.length || plan.some(t => !t.id || t.dependsOn.some(d => !ids.has(d) || d === t.id))) {
    throw new Error("拆票计划含重复身份或无效依赖，不创建票");
  }
  const visiting = new Set<string>(), visited = new Set<string>();
  const visit = (id: string) => {
    if (visiting.has(id)) throw new Error("拆票计划存在依赖环，不创建票");
    if (visited.has(id)) return;
    visiting.add(id);
    for (const dep of plan.find(t => t.id === id)!.dependsOn) visit(dep);
    visiting.delete(id); visited.add(id);
  };
  for (const id of ids) visit(id);
  const stillApproved = () => {
    const current = readCurrentSpec(a.spec);
    return current.body === spec.body && currentSpecApproved(current, a.spec, cfg.orchestrator);
  };
  const linked = fetchChildren(a.map).filter(isImplTicket);
  // REST 分页列举不用搜索索引；create 成功但未关联的票也在同一恢复集合里。
  const repositoryIssues = JSON.parse(gh(`api --paginate ${shellQuote(`repos/${GH_ENV.GH_REPO}/issues?state=all&per_page=100`)} --slurp`)) as RawChild[][];
  const allIssues = repositoryIssues.flat();
  const tickets = new Map<string, { number: number; id: number; body: string; state: string; labels: string[] }>();
  for (const t of plan) {
    const identity = splitIdentity(a.spec, t.id);
    // 身份标记只认编排账号自己建的 issue：外部账号预建的同标记票或 PR 不能冒充引擎的实施票，也不能让恢复因「多张票」卡死。
    const marked = allIssues.filter(i => !i.pull_request && i.user?.login === cfg.orchestrator && (i.body ?? "").includes(identity));
    const legacy = linked.filter(i => i.title.startsWith(`[impl] ${t.id} `) && !i.body.includes("<!-- wayfinder-ticket:"));
    const candidates = [...new Map([...marked, ...legacy].map(i => [i.number, i])).values()];
    if (candidates.length > 1) throw new Error(`拆票身份 ${t.id} 对应多张票，不能自动选择`);
    let existing = candidates[0];
    const receipt = splitReceipt(a.spec, spec.body, t.id);
    if (existing && /<!-- wayfinder-published:/.test(existing.body ?? "") && !(existing.body ?? "").includes(receipt)) {
      throw new Error(`已发布 #${existing.number} 属于另一版 SPEC，须显式修订实施合同`);
    }
    const rulings = t.rulings.map(n => `[#${n}](${issueUrl(n)})`).join(" + ");
    const plannedBody = `${identity}\nPart of [SPEC #${a.spec}](${issueUrl(a.spec)})（map [#${a.map}](${issueUrl(a.map)}) 图内实施票）。` +
      (rulings ? `决策链：${rulings}。` : "") + `\n\n## 目标（spec ${t.id}）\n\n${t.summary ?? "（见 spec 对应条目）"}\n`;
    const bodyFor = (current: string | null | undefined) => splitTicketBody(identity, plannedBody, current);
    let body = bodyFor(existing?.body);
    const found = existing !== undefined;
    if (!existing) {
      if (!stillApproved()) return;
      const created = createIssue(`[impl] ${t.id} ${t.title}`, body, []);
      existing = { ...created, title: `[impl] ${t.id} ${t.title}`, body, state: "OPEN", labels: [] };
    }
    const number = existing.number;
    let names = (existing.labels ?? []).map(l => typeof l === "string" ? l : l.name);
    const published = (existing.body ?? "").includes(receipt);
    let state = existing.state;
    if (found && !published) {
      // 与执行器领取、释放共用票级动作锁；判定与写入都用锁内重读的票面，不用分页快照。
      await withTicketHold(number, (claim) => {
        const fresh = JSON.parse(gh(`issue view ${number} --json state,labels,assignees,body`)) as RawChild;
        const why = migrationHold(fresh, claim);
        if (why) throw new Error(`未完整发布的 #${number} ${why}`);
        names = (fresh.labels ?? []).map(l => l.name);
        state = fresh.state;
        body = bodyFor(fresh.body);
        // 回收旧版本留下的提前发布标签；票型标签 wayfinder:impl 保留（未发布票缺发布凭据，releaseTicket 不放行）。
        const exposed = names.filter(l => ["ready-for-agent", "sandcastle", QUEUE_LABEL].includes(l));
        // 票级动作锁只挡 DeepAgents 执行器；旧 Sandcastle 消费者（main.mts、main-swarm、claim-loop、health-monitor）
        // 不认这把锁，只在旧入口冻结（drain 处于 draining）时被挡住。本动作运行在引擎准入内：旧入口未冻结时走的是
        // 旧准入（共享锁、drain open），冻结后走新队列准入（共享锁、drain draining 且切流记录有效），持锁期间状态不会翻转。
        // 所以只有新队列准入（releaseLabel() === QUEUE_LABEL）下旧消费者确定领不到票；旧入口未冻结时，
        // 需要改票面的迁移一律不做，免得旧消费者凭先前读到的票面在复核之后领走正在改写的票。不改任何东西的恢复照常。
        const writes = exposed.length > 0 || (fresh.body ?? "") !== body;
        if (writes && releaseLabel() !== QUEUE_LABEL) {
          throw new Error(`#${number} 迁移要改票面，但旧 Sandcastle 入口未冻结（未切到 ${QUEUE_LABEL}）；冻结旧入口并完成切流后重跑`);
        }
        if (exposed.length) ghOnce(`issue edit ${number} --remove-label ${shellQuote(exposed.join(","))}`);
        names = names.filter(l => !exposed.includes(l));
        if ((fresh.body ?? "") !== body) ghOnce(`issue edit ${number} --body ${shellQuote(body)}`);
      });
    }
    const id = issueDbId(number);
    if (!linked.some(i => i.number === number)) addSubIssue(a.map, id);
    tickets.set(t.id, { number, id, body: published ? existing.body! : body, state, labels: names });
  }
  // 补边是准备态收敛，不授予执行权；即使 PASS 撤销也完成已创建票的安全依赖。
  for (const t of plan) {
    const child = tickets.get(t.id)!;
    const pages = JSON.parse(gh(`api --paginate repos/${GH_ENV.GH_REPO}/issues/${child.number}/dependencies/blocked_by --slurp`)) as Array<Array<{ id: number }>>;
    const edges = pages.flat();
    for (const dep of new Set(t.dependsOn)) {
      const blocker = tickets.get(dep)!;
      if (!edges.some(e => e.id === blocker.id)) addBlockingEdge(child.number, blocker.id);
    }
  }
  // 每票发布前重验当前裁定；失败后保持已准备图，下一轮补余下的发布。
  for (const t of plan) {
    const child = tickets.get(t.id)!;
    if (!stillApproved()) return;
    const receipt = splitReceipt(a.spec, spec.body, t.id);
    if (!child.body.includes(receipt)) ghOnce(`issue edit ${child.number} --body ${shellQuote(`${child.body}\n${receipt}\n`)}`);
    if (normalizeState(child.state) === "CLOSED") continue;
    if (!stillApproved()) return;
    // 维护者用 hold 标签停放的已发布票不再补 ready-for-agent；只摘掉 ready-for-agent 而不挂 hold 的，按发布中断补回。
    if (child.labels.some(l => HOLD_LABELS.includes(l))) continue;
    if (!child.labels.includes("ready-for-agent")) ghOnce(`issue edit ${child.number} --add-label ready-for-agent`);
  }
}

/** 动作 3：实装票全关 + 判据满足 → 起草图关 comment + close map（不碰 main）。 */
function actCloseGraph(a: Extract<Action, { kind: "close_graph" }>, _cfg: EngineConfig): void {
  const mapNumber = a.map;
  const ctx = fetchMapContext(mapNumber);
  const spec = ctx.children.find((c) => isSpecTicket({ title: c.title } as ChildIssue));
  const impl = ctx.children.filter((c) => isImplTicket({ title: c.title } as ChildIssue));
  // 决策票全关只列决策票（spec/实装票各有独立行，混入会让「决策票全关」名不副实）。
  const decisionClosed = ctx.children.filter(
    (c) =>
      c.state === "CLOSED" &&
      !isSpecTicket({ title: c.title }) &&
      !isImplTicket({ title: c.title }),
  );
  const fog = unresolvedFog(ctx.body);

  const lines: string[] = [];
  lines.push(`## 图关闭（${new Date().toISOString().slice(0, 10)}）——到达 destination`);
  lines.push("");
  lines.push(`- **决策票全关**：${decisionClosed.map((c) => `[#${c.number}](${issueUrl(c.number)})`).join(" / ") || "（无）"}`);
  if (spec) lines.push(`- **spec**：[#${spec.number}](${issueUrl(spec.number)})（图内实施总单）`);
  lines.push(`- **实装票全关**：${impl.map((c) => `[#${c.number}](${issueUrl(c.number)})`).join(" / ") || "（无）"}`);
  lines.push(`- **残雾去向核实**：${fog.length === 0 ? "无残留（Not yet specified 已清空或全部有去向）" : `⚠ 仍有 ${fog.length} 条（不应发生）`}`);
  lines.push("");
  lines.push("（本评论由 wayfinder_engine 自动起草；本引擎不碰 main，合入由分支保护的 deepagents/review 与 ci-ok 把关。）");

  const comment = lines.join("\n");
  // spec 非持久：实装落地即关。
  if (spec && spec.state === "OPEN") {
    ghOnce(`issue close ${spec.number} --comment "实施票已全关，spec 落地即关（非持久件）。"`);
    console.log(`  ✓ 关闭 spec #${spec.number}`);
  }
  ghOnce(`issue close ${mapNumber} --comment ${shellQuote(comment)}`);
  console.log(`  ✓ 关闭 map #${mapNumber}（comment 已附）`);
}

async function executeAction(action: Action, cfg: EngineConfig): Promise<void> {
  switch (action.kind) {
    case "draft_spec":
      return actDraftSpec(action, cfg);
    case "split_impl_tickets":
      return actSplitImpl(action, cfg);
    case "close_graph":
      return actCloseGraph(action, cfg);
  }
}

function describeAction(a: Action): string {
  switch (a.kind) {
    case "draft_spec":
      return `起草 spec 草案（Claude 起草子代理）→ 开图内 spec 票 → 待非作者独审裁定  (map #${a.map})`;
    case "split_impl_tickets":
      return `拆 tracer-bullet 实装票（blocking 边 + 逐条挂裁定票）+ sandcastle 标签  (map #${a.map}, spec #${a.spec})`;
    case "close_graph":
      return `起草图关 comment + close map  (map #${a.map})`;
  }
}

// ── 壳：轮询 + 每轮重算 ready 集 ───────────────────────────────────────────────

const roundIO = { frozen: graphAdmissionFrozen, maps: fetchOpenMaps, ready: fetchReadyTickets,
  admit: withEngineAdmission, execute: executeAction, release: releaseTicket, status: writeStatus };

export async function runOnce(cfg: EngineConfig, maintenance?: Pick<MaintenanceOwner, "work">,
  io = roundIO): Promise<void> {
  if (io.frozen()) return;
  const stamp = new Date().toISOString().slice(0, 19).replace("T", " ");
  console.log(`\n[wayfinder_engine] ${stamp} 一轮开始（${cfg.dryRun ? "dry-run" : "live"}）`);
  let maps: MapState[];
  let ready: ReadyTicket[];
  let facts: SpecTreeFacts;
  try {
    maps = io.maps();
    // 队列交棒视图：全仓 ready-for-agent × 父图 spec 批准态。
    facts = buildSpecTreeFacts(maps, cfg.orchestrator);
    ready = withSpecApproval(io.ready(), facts.approved, buildOpenChildIndex(maps), facts.underSpec);
  } catch (e) {
    console.error(`[wayfinder_engine] 拉取 tracker 状态失败（网络/鉴权？已重试，本轮跳过）：${e}`);
    return;
  }

  // 1) DAG 走查动作（draft_spec / split_impl_tickets / close_graph）。
  console.log(`  open 的 wayfinder:map 共 ${maps.length} 张`);
  for (const m of maps) {
    const analysis = analyzeMap(m, { orchestrator: cfg.orchestrator });
    console.log(`  · #${m.number} ${m.title} — ${analysis.phase}`);
    for (const action of analysis.actions) {
      if (cfg.dryRun) {
        console.log(`    [dry-run] 将执行：${describeAction(action)}`);
      } else {
        try {
          const execute = () => io.admit(() => io.execute(action, cfg));
          if (maintenance) await maintenance.work(`map:${m.number}:${action.kind}`, execute);
          else await execute();
        } catch (e) {
          if (e instanceof MaintenanceClosed) {
            console.log("    维护关闭，停止本轮新领取");
            return;
          }
          console.error(`    ✗ 执行失败（${action.kind}）：${e}`);
        }
      }
    }
  }

  // 2) 队列交棒：只给合资格实装票（已批准 spec/DAG + 未 assign + 无 blocker）挂 sandcastle，
  //    不把全部历史 ready-for-agent 无差别放行。
  const summary = summarizeQueue(ready);
  console.log(
    `  扫描集（ready-for-agent ∪ wayfinder:impl）${ready.length} 张：可拾取 ${summary.buckets.released} / blocked ${summary.buckets.blocked} / ` +
      `claimed ${summary.buckets.claimed} / running ${summary.buckets.running} / 待释放 ${summary.buckets.eligible} / 不放行 ${summary.buckets.held}`,
  );
  if (cfg.explain) {
    for (const t of ready) console.log(
        `    · #${t.number} ${explainTicket(t)} [spec=${t.specApproved === null ? "图外" : t.specApproved ? "已批准" : "未批准"}] — ${t.title.slice(0, 60)}`,
      );
  }
  for (const n of summary.eligible) {
    if (cfg.dryRun) {
      console.log(`    [dry-run] 将释放（挂 ${releaseLabel()}）：#${n}`);
    } else {
      try {
        const release = () => io.admit(() => io.release(n, { specs: facts.requiredSpecs.get(n) ?? [], orchestrator: cfg.orchestrator,
          via: facts.planBound.has(n) ? "plan" : "tree" }));
        const why = maintenance ? await maintenance.work(`release:${n}`, release) : await release();
        if (why) console.log(`    · 写前复核不放行 #${n}：${why}`);
        else console.log(`    ✓ 已释放（挂 ${releaseLabel()}）：#${n}`);
      } catch (e) {
        if (e instanceof MaintenanceClosed) {
          console.log("    维护关闭，停止本轮新领取");
          return;
        }
        console.error(`    ✗ 释放失败（#${n}）：${e}`);
      }
    }
  }

  // 3) 状态页：五桶分明落盘，供宿主/roster 读（不把 sandcastle 空误写成全空）。
  io.status(cfg, stamp, maps, ready, summary);
  console.log(`[wayfinder_engine] 一轮结束`);
}

function parseArgs(argv: string[]): EngineConfig {
  let maintenanceRoot: string | undefined;
  let maintenanceEsConfig: string | undefined;
  let dryRun = true;
  let once = false;
  let explain = false;
  let pollSeconds = Number(process.env.WAYFINDER_POLL_SECONDS ?? DEFAULT_POLL_SECONDS);
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]!;
    if (a === "--live") dryRun = false;
    else if (a === "--dry-run") dryRun = true;
    else if (a === "--once") once = true;
    else if (a === "--explain") explain = true;
    else if (a === "--maintenance-es-config") {
      if (!argv[i + 1]) throw new Error("--maintenance-es-config 缺参数");
      maintenanceEsConfig = resolve(argv[++i]!);
    }
    else if (a === "--maintenance-root") {
      if (!argv[i + 1]) throw new Error("--maintenance-root 缺参数");
      maintenanceRoot = resolve(argv[++i]!);
    }
    else if (a === "--poll-seconds") {
      const n = Number(argv[i + 1]);
      if (Number.isFinite(n) && n > 0) {
        pollSeconds = n;
        i++;
      }
    }
  }
  return {
    maintenanceRoot,
    maintenanceEsConfig,
    orchestrator: process.env.WAYFINDER_ORCHESTRATOR ?? ORCHESTRATOR_LOGIN,
    dryRun,
    pollSeconds,
    // 启动即校验（非主控同型直接 fail-loud，不等到图清起草时才炸）。
    ...resolveSpecDrafter(process.env),
    once,
    explain,
  };
}

const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

/**
 * 读取独审 JSON 原件，核对票号和当前正文后打印评论，不写 GitHub。
 *   npx tsx scripts/wayfinder_engine.mts --spec-ruling <号> --review-file <原件.json>
 * digest 来自独审原件；发布时只比较，不能用当前正文摘要替换。
 */
export function specRulingCli(
  argv: string[],
  readBody: (n: number) => string = (n) => JSON.parse(gh(`issue view ${n} --json body`)).body as string,
  readReview: (path: string) => string = (path) => readFileSync(path, "utf8"),
): string {
  const arg = (name: string) => {
    const i = argv.indexOf(name);
    const v = i >= 0 ? argv[i + 1] : undefined;
    if (!v) throw new Error(`--spec-ruling 缺 ${name}`);
    return v;
  };
  const n = Number(arg("--spec-ruling").replace(/^#/, ""));
  if (!Number.isSafeInteger(n) || n <= 0) throw new Error("--spec-ruling 票号非法");
  const evidence = arg("--review-file");
  if (!evidence.trim() || /[\r\n]/.test(evidence)) throw new Error("独审原件路径须为非空单行");
  const review: unknown = JSON.parse(readReview(evidence));
  if (!review || typeof review !== "object" || Array.isArray(review)) throw new Error("独审原件须为 JSON 对象");
  // 外部 JSON 在下面统一校验，附加的逐项审查意见留在原件中。
  const r = { ...review, evidence } as SpecRuling;
  const why = specReviewProblem(r, n, readBody(n));
  if (why) throw new Error(`SPEC #${n} 裁定记录无效：${why}`);
  return specRulingBody(r);
}

async function main(): Promise<void> {
  if (process.argv.includes("--spec-ruling")) {
    process.stdout.write(specRulingCli(process.argv.slice(2)));
    return;
  }
  const cfg = parseArgs(process.argv.slice(2));
  console.log(
    `[wayfinder_engine] 启动：dry-run=${cfg.dryRun} poll=${cfg.pollSeconds}s orchestrator=${cfg.orchestrator} spec 起草子代理=${cfg.specProvider}/${cfg.specModel}`,
  );
  const maintenance = cfg.dryRun ? undefined : new MaintenanceOwner("wayfinder", cfg.maintenanceRoot, cfg.maintenanceEsConfig);
  try {
    if (cfg.once) {
      if (!maintenance?.poll()) await runOnce(cfg, maintenance);
      return;
    }
    for (;;) {
      try {
        if (!maintenance?.poll()) {
          if (graphAdmissionFrozen()) { console.log("旧入口冻结，本轮不再领新工作"); return; }
          await runOnce(cfg, maintenance);
        }
      } catch (e) {
        console.error(`[wayfinder_engine] 一轮异常：${e}`);
      }
      await sleep(cfg.pollSeconds * 1000);
    }
  } finally {
    try { maintenance?.stop(); } catch { console.error("maintenance stop unavailable，保留未确认状态"); }
  }
}

if ((import.meta as { main?: boolean }).main) {
  main();
}
