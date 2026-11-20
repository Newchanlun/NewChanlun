export const meta = {
  name: 'sweep-2114-trend-formed-corpus',
  description: 'Exhaustive sweep of the original Chan blog corpus for every passage about a trend being formed / confirmed / established while the second center is not yet complete, for decision #2114',
  phases: [
    { title: 'Sweep', detail: 'finders with different wording families and search modes' },
    { title: 'Critic', detail: 'completeness critic proposes missed wordings; loop until dry' },
    { title: 'Verify', detail: 'four-step citation check and dedup into one corpus table' },
  ],
}

const WORKER = 'Read /home/workspace/.claude/plugins/cache/pstack-claude/pstack/0.9.143/skills/poteto-mode/worker.md before anything else.\n\n'

const CONTEXT = `Goal: NewChanlun is a quant system built on Chan theory (缠论). Decision ticket #2114 must rule when a trend counts as formed: adjacent same-level centers (中枢) A and B, A settled, the later center B has appeared (three overlapping segments) but is still open / not yet completed, and their outer edges are strictly separated. The ruling draft has been blocked three times for the same reason: its archaeology searched the original blog text by a few keywords and each review found more passages with other wording. Round 2 missed passages using 形成 (lesson 102 line 238; lesson 35 line 122; lesson 25 lines 306-308). Round 3 missed passages using 确认 / 确立 (lesson 100 line 34 "第二个5分钟中枢的确认从而确认5分钟的下跌"; lesson 68 line 154 "已经出现第二个5分钟中枢，因此，该5分钟的上涨类型是可以确立了"; lesson 91 line 130 "等待第二个1分钟中枢的出现，看这1分钟的上涨是否确立"). You are building the COMPLETE list so that a fourth review cannot find another wording.

Corpus: /home/workspace/src/NewChanlun/docs/chanlun/text/blog/ - 109 files NNN-第N课.md (about 38,600 lines), the master's original blog lessons. Each file has the lesson body and, after a boundary line, a reply area with reader comments and the master's replies, and in later lessons (roughly 60-108) daily market commentary by the master. Only this directory counts as the original. Read docs/agents/doctrine-rules.md section 文档层名分 for the four-step citation check: (1) exact line number, (2) verbatim text, (3) author attribution - is the line the master's own body text, the master's reply (look for the reply header such as "缠中说禅：" and timestamp lines above it), a reader's comment, or an editor's note (注 / 娇注 etc.), (4) inline notes by another hand inside the line. A reader's or editor's sentence is NOT the master's text.

What counts as relevant (either direction): any passage where the master states, implies or denies that a trend / 上涨 / 下跌 / 走势类型 of some level is formed, established, confirmed, counts, exists, or can be called such, in a state where the second same-level center has only just appeared or is not yet complete (no third-class buy/sell point of the later center yet), or where he says what is additionally needed before it counts; also passages that say such a reading can still be overturned (the later center expanding into a larger center, 中枢扩展, a+B evolving), and passages about when a center itself is "completed / confirmed" (tied to the third-class point). Passages that only define a trend as "two same-level centers in the same direction" in the abstract are relevant but should be marked as abstract definitions.

READ-ONLY: no edits, commits, pushes, comments. Use rg / sed -n / Read on the corpus.
`

const HITS = {
  type: 'object',
  properties: {
    finder: { type: 'string' },
    queries: { type: 'array', items: { type: 'string' }, description: 'the exact rg commands run, with hit counts' },
    passages: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          file: { type: 'string', description: 'e.g. 100-第100课.md' },
          line: { type: 'number' },
          quote: { type: 'string', description: 'verbatim, <=220 chars' },
          author: { type: 'string', enum: ['master_body', 'master_reply', 'master_daily_commentary', 'reader', 'editor_note', 'unclear'] },
          attribution_basis: { type: 'string', description: '<=160 chars: boundary line number, reply header / timestamp lines, note markers' },
          state: { type: 'string', description: '<=200 chars: what market or structural state the sentence speaks about (which centers exist, is the later one complete), and how you know (cite the line)' },
          says: { type: 'string', enum: ['trend_formed_now', 'trend_not_yet_or_needs_more', 'can_still_be_overturned', 'center_completion_rule', 'abstract_definition', 'other_relevant'] },
          wording: { type: 'string', description: 'the key word(s) used: 形成 / 确认 / 确立 / 成立 / 才算 / ...' },
        },
        required: ['file', 'line', 'quote', 'author', 'attribution_basis', 'state', 'says', 'wording'],
      },
    },
  },
  required: ['finder', 'queries', 'passages'],
}

const CRITIC = {
  type: 'object',
  properties: {
    new_wordings: { type: 'array', items: { type: 'string' }, description: 'wordings or search modes not yet covered that produced at least one NEW relevant passage' },
    passages: HITS.properties.passages,
    dry: { type: 'boolean', description: 'true if your additional searches found no new relevant passage' },
    searched: { type: 'array', items: { type: 'string' }, description: 'every additional rg command run, with hit counts' },
  },
  required: ['new_wordings', 'passages', 'dry', 'searched'],
}

const TABLE = {
  type: 'object',
  properties: {
    corpus_markdown: { type: 'string', description: 'Chinese markdown, <=14000 chars: one table of all verified relevant passages sorted by lesson and line (file:line, verbatim quote, author class with basis, state, what it says, key wording), then a short section listing every query family run with hit counts, then a list of passages that were reported but rejected and why' },
    counts: { type: 'string', description: 'how many passages per says-category and per author class' },
    rejected: { type: 'array', items: { type: 'string' } },
  },
  required: ['corpus_markdown', 'counts', 'rejected'],
}

const FINDERS = [
  { key: 'formed-family', prompt: 'Search mode: wording family around 形成 / 形成了 / 才算 / 算是 / 算不算 / 就是 / 已经是 / 成为 near 上涨 / 下跌 / 趋势 / 升势 / 跌势 / 走势类型 / 盘整, and near 第二个(.{0,6})中枢 / 两个(.{0,6})中枢 / 第2个中枢 / 新的中枢 / 新中枢. Build several rg -n patterns with bounded gaps (.{0,20}), run them over the whole directory, read EVERY hit in context (sed -n with 6 lines before and after, more for reply areas to find the header), and keep the relevant ones.' },
  { key: 'confirm-family', prompt: 'Search mode: wording family around 确认 / 确立 / 确定 / 成立 / 确定了 / 得到确认 / 可以确立 / 能否成立 / 是否成立 / 100% / 百分百 / 不能给出 near 上涨 / 下跌 / 趋势 / 走势 / 类型 / 中枢. Also 完成 near 中枢 (a center being completed) and 第三类买卖点 / 三买 / 三卖 near 中枢(.{0,12})(完成|确认|结束). Build several rg -n patterns with bounded gaps, run them over the whole directory, read every hit in context and keep the relevant ones.' },
  { key: 'structure-family', prompt: 'Search mode: by structure rather than by verb. Find every line that mentions a SECOND center of some level: 第二个.{0,8}中枢 / 第2个.{0,8}中枢 / 两个.{0,10}中枢 / 第二个.{0,4}(1|5|15|30|60)分钟中枢 / 第二个日线中枢 / 下一个中枢 / 后一个中枢 / 再形成.{0,6}中枢 / 又一个中枢. For each hit read the surrounding paragraph and decide whether the master says anything about the trend status at that moment, whatever verb he uses (including verbs nobody has searched for yet - note them). Also search a+A+b+B, a`+B, a\'+B, A+b+B, 中枢扩展 / 扩展成 / 演化成 / 变成更大 near 趋势 / 上涨 / 下跌.' },
  { key: 'daily-commentary', prompt: 'Search mode: the daily market commentary in the later lessons (roughly lessons 60-108, usually after the boundary line, each entry with a title line and a time line). The master repeatedly comments live on "an N-minute rise/decline" as centers appear. Find every commentary entry where he speaks about whether the current N分钟上涨 / 下跌 has formed, is established, is confirmed, continues, ends, or evolves: rg for (1|5|15|30|60)分钟(的)?(上涨|下跌) within 30 chars of 形成|确立|确认|成立|延续|结束|完成|演化|扩展|是否|能否|关键|只要|一旦; also 线段的(上涨|下跌), 日线(上涨|下跌). Read each hit in context and record the state the market was in (use neighbouring entries to establish which centers existed).' },
]

phase('Sweep')
const first = (await parallel(FINDERS.map(f => () => agent(
  WORKER + CONTEXT + '\n' + f.prompt + '\n\nBe exhaustive within your mode: record every relevant passage, not a sample. For each, do the four-step check. Passages already known (lessons 100:34, 68:154, 91:130, 102:238, 35:122, 25:306-308, 20:32, 41:319, 37:18, 18:42, 18:44, 107:32, 36:26, 36:30) should still be listed if your searches hit them, so coverage can be cross-checked.',
  { label: `sweep:${f.key}`, phase: 'Sweep', schema: HITS, agentType: 'pstack:poteto-agent' }
)))).filter(Boolean)

const key = p => `${p.file}:${p.line}`
const seen = new Map()
for (const r of first) for (const p of r.passages) if (!seen.has(key(p))) seen.set(key(p), p)
log(`sweep: ${first.length}/4 finders, ${seen.size} distinct passages`)

phase('Critic')
let dry = 0
let round = 0
const criticLog = []
while (dry < 1 && round < 2) {
  round++
  const have = [...seen.values()].map(p => `${p.file}:${p.line} [${p.wording}] ${p.says}`).join('\n')
  const c = await agent(
    WORKER + CONTEXT + `\nYou are the completeness critic, round ${round}. Four finders searched by these modes: (1) 形成-family verbs, (2) 确认/确立/成立-family verbs, (3) by structure (any mention of a second center), (4) the daily commentary. Their query lists: ${JSON.stringify(first.map(r => ({ finder: r.finder, queries: r.queries })))}\n\nPassages found so far (file:line [wording] category):\n${have}\n\nYour job: find what they missed. Think of wordings and modes NOT in their query lists - other verbs and idioms the master uses for "it now counts / is established / is in place" (for example 走出来 / 出来了 / 成立了 / 才能说 / 可以说 / 才是 / 没走出来 / 还没有 / 就可以 / 意味着 / 就意味 / 宣告 / 标志 / 开始了 / 展开 / 进入), classical or colloquial phrasings, negations, questions from readers that he answers on exactly this point (search the reader question, then read his reply), and passages that discuss it without naming a number (后面的中枢 / 新的同级别中枢). Also pick five lessons at random among those with NO passage found so far from the range 17-45 and five from 60-108 and skim their relevant sections directly to estimate the miss rate. Run the searches, read hits in context, and report only NEW relevant passages (not already in the list), each with the four-step check. Set dry=true only if you found none.`,
    { label: `critic:${round}`, phase: 'Critic', schema: CRITIC, agentType: 'pstack:poteto-agent' }
  )
  if (!c) break
  criticLog.push({ round, new_wordings: c.new_wordings, searched: c.searched, found: c.passages.length })
  let fresh = 0
  for (const p of c.passages) if (!seen.has(key(p))) { seen.set(key(p), p); fresh++ }
  log(`critic round ${round}: ${fresh} new passages (${c.new_wordings.join(' / ') || 'none'})`)
  if (c.dry || fresh === 0) dry++
}

phase('Verify')
const all = [...seen.values()]
const table = await agent(
  WORKER + CONTEXT + `\nYou are the verifier. Below are ${all.length} candidate passages reported by the finders and the critic. For EACH one open the file at that line yourself (sed -n) and re-do the four-step check: is the line number right, is the quote verbatim, who is the author (find the boundary line and, in the reply area, the reply header and timestamp above the line; a reader's line or an editor's note is not the master's text), are there inline notes by another hand. Reject passages that are misattributed, misquoted, or not actually about the trend-status question; correct line numbers where off by a few lines. Then produce the final corpus table.\n\nCandidates (JSON): ${JSON.stringify(all)}\n\nQuery families run (JSON): ${JSON.stringify(first.map(r => ({ finder: r.finder, queries: r.queries })))}\n\nCritic rounds (JSON): ${JSON.stringify(criticLog)}`,
  { label: 'verify:table', phase: 'Verify', schema: TABLE, agentType: 'pstack:poteto-agent' }
)

return { table, candidates: all.length, critic_rounds: criticLog }
