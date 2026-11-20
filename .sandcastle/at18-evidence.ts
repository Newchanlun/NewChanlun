/** #1551 待定：这是可信采集器和判定层之间的内存接口，不是可由 observations
 * 或任意 JSON 自行声明的原件协议。未接入经批准的解读器时，不存在肯定支持。 */
export type EvidenceKind = "coverage" | "destination" | "tb" | "runtime" | "permission" |
  "migration" | "post_gate" | "deferral" | "legacy" | "review";
export type EvidenceClass = "simulation" | "experiment" | "production";
type Fact = null | boolean | number | string | readonly Fact[] | { readonly [key: string]: Fact };

export interface EvidenceClaim {
  kind: EvidenceKind;
  scope: string;
  predicate: string;
  evidence_class?: EvidenceClass;
  facts?: Fact;
}

export interface EvidenceFinding {
  claim: EvidenceClaim;
  verdict: "PASS" | "FAIL";
  execution: "EXECUTED" | "RECONCILED" | "NOT_RUN";
  /** 解读器从原件取得的稳定定位符，转存于现有 ArtifactRef.bounded_scope。 */
  pointer: string;
}

export const claim = (kind: EvidenceKind, scope: string, predicate: string,
  evidence_class?: EvidenceClass, facts?: Fact): EvidenceClaim =>
  ({ kind, scope, predicate, ...(evidence_class && { evidence_class }), ...(facts !== undefined && { facts }) });

export const legacyRules = {
  942: "逐问处分不变，旧关闭不证明两场所隔离，也不恢复强平实验",
  1096: "TB-10 勘察及 TB-11 对账，冻结或收编与 ADR 0048 删除分证",
  1282: "冻结七标的和双对照的旧研究，不替代新程序验收",
  1304: "TB-07 回放恢复 AsKnown 全状态、AT-14 报告器与回归锁，未齐保持 OPEN",
  1319: "TB-08 核实 feed/wire，TB-04 意图与回报，TB-09 隔离，不恢复旧简化链",
  1320: "TB-07 的正式回放与图外重型测量分列",
  1279: "仅保留自有义务，不提前解除本图前置或宣布放行",
} as const;
