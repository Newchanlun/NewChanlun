import { z } from "zod";
import { tbTickets, type At18Source } from "./at18-report.ts";

const repository = "Newchanlun/NewChanlun";
const oid = z.string().regex(/^[a-f0-9]{40}$/);
const prList = z.array(z.array(z.object({ number: z.int().positive(), head: z.object({ sha: oid }),
  base: z.object({ ref: z.string() }) })));
const pull = z.object({
  merged: z.boolean(), head: z.object({ sha: oid }), base: z.object({ ref: z.string() }),
  merge_commit_sha: oid.nullable(),
});
const trackerIssue = z.object({
  number: z.int().positive(), state: z.enum(["OPEN", "CLOSED"]),
  subIssues: z.object({ totalCount: z.int().nonnegative(), nodes: z.array(
    z.object({ number: z.int().positive(), state: z.enum(["OPEN", "CLOSED"]) }),
  ) }),
});
const tracker = z.object({ data: z.object({ repository: z.record(z.string(), trackerIssue.nullable()) }) });

export function at18GitHub(origin: string, gh: (...args: string[]) => unknown):
  Pick<At18Source, "mergedMainCommit" | "tbRoster"> {
  if (!/^(https:\/\/github\.com\/|git@github\.com:|ssh:\/\/git@github\.com\/)Newchanlun\/NewChanlun(?:\.git)?$/i.test(origin)) return {};
  const mappings = new Map<string, string | undefined>();
  let native: z.infer<typeof tracker>["data"]["repository"] | undefined;
  let queried = false;

  return {
    // ADR 0064 §五:62(b) 仅用于仓外 ArtifactRef 归属；调用方另验 squash 落点祖先。
    mergedMainCommit(head) {
      if (mappings.has(head)) return mappings.get(head);
      if (!oid.safeParse(head).success) return undefined;
      mappings.set(head, undefined);
      try {
        const listed = prList.parse(gh("api", "--paginate", "--slurp", `repos/${repository}/commits/${head}/pulls`));
        const merged = new Set<string>();
        for (const candidate of listed.flat()) {
          if (candidate.head.sha !== head || candidate.base.ref !== "main") continue;
          const pr = pull.parse(gh("api", `repos/${repository}/pulls/${candidate.number}`));
          if (pr.merged && pr.head.sha === head && pr.base.ref === "main" && pr.merge_commit_sha) merged.add(pr.merge_commit_sha);
        }
        if (merged.size === 1) mappings.set(head, [...merged][0]);
      } catch { /* 查询失败不是合入证据。 */ }
      return mappings.get(head);
    },
    tbRoster(ticket) {
      if (!queried) {
        queried = true;
        const aliases = Object.values(tbTickets).map(id =>
          `i${id}:issue(number:${id}){number state subIssues(first:100){totalCount nodes{number state}}}`).join(" ");
        try {
          native = tracker.parse(gh("api", "graphql", "-f", `query=query {
            repository(owner:"Newchanlun",name:"NewChanlun") { ${aliases} } }`)).data.repository;
        } catch { /* 查询失败不能采用观察提交者的分母。 */ }
      }
      const record = native?.[`i${ticket}`];
      if (!record || record.number !== ticket || record.subIssues.nodes.length !== record.subIssues.totalCount) return undefined;
      return { state: record.state, slices: record.subIssues.nodes.map(({ number, state }) => ({ ticket: number, state })) };
    },
  };
}
