/* #1374：经济域只读消费者；规范字节/严格解析复用现有 TB01C。 */
(function (root, factory) {
  const shared = typeof module === "object" && module.exports ? require("./tb01c-client.js") : root.TB01C;
  const api = factory(shared);
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.TB03A = api;
})(globalThis, function (shared) {
  "use strict";
  const {canonical, parse, sha256} = shared;
  const object = value => value !== null && typeof value === "object" && !Array.isArray(value);
  const need = (ok, reason) => { if (!ok) throw new Error(reason); };
  const same = (a, b) => canonical(a) === canonical(b);
  function keys(value, fields, what) {
    need(object(value) && Object.keys(value).length === fields.length && fields.every(k => Object.hasOwn(value, k)), what + " 字段不完整或多余");
  }
  function integer(value, positive = false, signed = false) {
    need(typeof value === "string" && /^(?:0|-?[1-9][0-9]*)$/.test(value), "整数不是规范文本");
    const number = BigInt(value);
    need(number <= 9223372036854775807n && number >= (signed ? -9223372036854775808n : positive ? 1n : 0n), "整数越出精确域");
    return number;
  }
  function cut(value, domain) {
    keys(value, ["domain_id", "commit_seq", "root_hash"], "域切面");
    need(value.domain_id === domain && /^[0-9a-f]{64}$/.test(value.root_hash), "切面域或根摘要不符");
    integer(value.commit_seq);
  }
  function text(value, what) {
    need(typeof value === "string" && value.length > 0, what + " 缺失");
  }
  function digest(value, what) {
    need(typeof value === "string" && /^[0-9a-f]{64}$/.test(value), what + " 摘要无效");
  }
  function reference(value) {
    keys(value, ["authority_id", "object_id", "revision", "content_hash"], "开局对象引用");
    text(value.authority_id, "权威身份"); text(value.object_id, "对象身份");
    integer(value.revision); digest(value.content_hash, "对象内容");
  }
  async function verifyVoices(book, view, discovery, domain) {
    const voices = book.voice;
    if (voices.status === "MissingDependency") {
      keys(voices, ["status", "reason", "identity"], "未绑定 Voice");
      need(voices.identity === null, "缺依赖不能携带已成立身份");
      text(voices.reason, "开局依据缺项");
      return;
    }
    keys(voices, ["status", "records"], "Voice 集合");
    need(voices.status === "Bound" && Array.isArray(voices.records) && voices.records.length > 0,
      "已绑定 Voice 集合为空或状态未知");
    const identities = new Map(), bindings = new Set();
    for (const record of voices.records) {
      keys(record, ["voice_id", "binding_id", "identity", "instrument", "operation_level", "structure_view",
        "parent_voice_id", "opening_basis", "evidence", "first_known_ns", "commit_ns", "commit_seq",
        "business_lifecycle", "responsibility_tail"], "Voice 记录");
      digest(record.voice_id, "Voice 身份"); text(record.binding_id, "绑定身份");
      need(!identities.has(record.voice_id) && !bindings.has(record.binding_id), "Voice 或绑定身份重复");
      identities.set(record.voice_id, record); bindings.add(record.binding_id);
      keys(record.identity, ["carrier_ref", "gamma_ref", "sigma", "n"], "Voice 四元身份");
      reference(record.identity.carrier_ref); reference(record.identity.gamma_ref);
      need(["Long", "Short"].includes(record.identity.sigma), "Voice 方向未知");
      integer(record.identity.n);
      need(record.instrument === book.symbol && record.operation_level === book.operation_level,
        "Voice 与所属重的标的或操作级别不同");
      const structure = record.structure_view;
      keys(structure, ["profile_id", "execution_level", "confirmation_level", "nest_depth"], "结构参照");
      text(structure.profile_id, "结构 profile");
      const execution = integer(structure.execution_level), confirmation = integer(structure.confirmation_level);
      need(confirmation === execution + integer(structure.nest_depth), "结构参照与区间套梯级数不符");
      const basis = record.opening_basis;
      keys(basis, ["fact_key", "fact_hash", "allocation_id", "e_cut", "raw_sha256", "json_pointer", "quantity", "units"], "开局量依据");
      text(basis.fact_key, "原事实身份"); digest(basis.fact_hash, "原事实");
      text(basis.allocation_id, "分配身份"); cut(basis.e_cut, "E"); digest(basis.raw_sha256, "原始字节");
      need(typeof basis.json_pointer === "string" && same(basis.units, book.units), "开局量纲或来源指针不符");
      integer(basis.quantity, true);
      keys(record.evidence, ["authority_id", "bundle_sha256", "verification_sha256"], "定义证据引用");
      text(record.evidence.authority_id, "定义权威");
      need(record.identity.carrier_ref.authority_id === record.evidence.authority_id &&
        record.identity.gamma_ref.authority_id === record.evidence.authority_id, "开局引用与定义证据权威不同");
      digest(record.evidence.bundle_sha256, "定义证据包"); digest(record.evidence.verification_sha256, "独立核验");
      need(integer(record.first_known_ns) <= integer(record.commit_ns) &&
        BigInt(record.commit_ns) <= BigInt(view.commit_ns) &&
        integer(record.commit_seq, true) <= BigInt(view.cut.commit_seq), "Voice 晚于当前可知切面");
      keys(record.business_lifecycle, ["status"], "业务生命周期");
      need(record.business_lifecycle.status === "NotRecorded", "未支持的业务生命周期记录");
      keys(record.responsibility_tail, ["status", "reason"], "责任尾账");
      need(record.responsibility_tail.status === "Unknown", "未支持的责任尾账记录");
      text(record.responsibility_tail.reason, "责任尾账缺项");
      const identity = {schema: "voice-identity/1", domain_id: domain, session_id: discovery.session_id,
        session_generation: discovery.session_generation, chong_id: book.chong_id, identity: record.identity};
      need(record.voice_id === await sha256(identity), "Voice 不可变身份摘要不符");
    }
    for (const record of voices.records) {
      if (record.parent_voice_id === null) need(record.identity.n === "0", "根 Voice 的代际须为零");
      else {
        const parent = identities.get(record.parent_voice_id);
        need(parent !== undefined && BigInt(record.identity.n) === BigInt(parent.identity.n) + 1n &&
          record.identity.sigma !== parent.identity.sigma, "Voice 父关系、代际或方向不符");
        need(BigInt(parent.commit_seq) < BigInt(record.commit_seq) &&
          BigInt(parent.commit_ns) <= BigInt(record.first_known_ns) &&
          BigInt(parent.first_known_ns) <= BigInt(record.first_known_ns), "父 Voice 未先于子 Voice 持久成立");
      }
    }
  }
  // #1394 §5.7：版本由 discovery 明示，未知值和混搭拒绝，不从失败降档。
  // #1716：/3 = economic-session/1 窄测试臂，/4 = economic-session/2 内容域；两者都接受签署 cap 激活。
  const contentDomain = version => version === "tb03b-finance/2" || version === "tb03b-finance/4";
  const capActivation = version => version === "tb03b-finance/3" || version === "tb03b-finance/4";
  // #1407 C2/C3：/5 与 /6 = economic-session/1 上的 E 精确命令生产者；/6 在命令体固化 model_ref。
  const exactRelease = version => version === "tb03b-finance/5" || version === "tb03b-finance/6";
  const modelBinding = version => version === "tb03b-finance/6";
  function revision(discovery) {
    need(discovery.finance_revision === undefined || ["tb03b-finance/1", "tb03b-finance/2", "tb03b-finance/3", "tb03b-finance/4", "tb03b-finance/5", "tb03b-finance/6"].includes(discovery.finance_revision), "未知财务查询版本");
    return contentDomain(discovery.finance_revision) ? "economic-session/2" : "economic-session/1";
  }
  function evidence(value, discovery, horizon) {
    const version=discovery.finance_revision;
    if (contentDomain(version)) {
      keys(value, ["schema_revision", "content_format", "kind", "session_id", "session_generation", "writer_epoch", "pending_revision", "commit_ns", "basis_ref"], "财务内容证据");
      need(value.schema_revision === "s-financial-evidence/1" && value.content_format === "s-content/1" && value.kind === "FinancialBasisEvidence", "财务内容证据版本不符");
      keys(value.basis_ref, ["format", "kind", "root", "extent"], "内容引用");
      need(value.basis_ref.format === "s-content/1" && value.basis_ref.kind === "object" && /^sc1-[0-9a-f]{64}$/.test(value.basis_ref.root) && value.basis_ref.extent === "7", "财务 basis 引用无效");
    } else {
      keys(value, ["kind", "session_id", "session_generation", "writer_epoch", "pending_revision", "commit_ns", "snapshot"], "原财务结构依据");
      need(value.kind === "FinancialBasis" && object(value.snapshot), "原财务结构依据无效");
    }
    text(value.session_id, "结构会话"); integer(value.session_generation, true); integer(value.writer_epoch, true);
    need(value.session_id===discovery.session_id && value.session_generation===discovery.session_generation, "结构依据与可信会话不同");
    need(value.pending_revision === false && integer(value.commit_ns) <= horizon, "结构依据未成立或晚于首次获知");
    // 此 HTTP 合同未提供内容节点；只核持久头/引用，不能声称验证节点闭包或七字段正文绑定。
  }
  const financeKinds = {ImportResponsibility:"ResponsibilityImportedReceipt", PrepareDecision:"PreparedReceipt", Reserve:"ReserveReceipt", CommitDecision:"LocalCommitReceipt", AbortDecision:"AbortReceipt", CloseApplicants:"ApplicantsClosedReceipt", ActivateCapPolicy:"CapPolicyActivatedReceipt"};
  const commandKinds = {...financeKinds, MakeDispatchable:"DispatchableReceipt", ReleaseExact:"ReleasedExactReceipt"};
  const kindsOf = version => exactRelease(version) ? commandKinds : financeKinds;
  async function bytesHash(bytes) {
    return Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256",bytes)),n=>n.toString(16).padStart(2,"0")).join("");
  }
  async function textSha256(source) {
    return bytesHash(new TextEncoder().encode(source));
  }
  // #1716：未显式激活时，由冻结原件派生 v1。
  function activeCap(image,seq,data) {
    const last=image.history.filter(e=>e.kind==="ActivateCapPolicy" && BigInt(e.commit_seq)<BigInt(seq)).at(-1);
    return last?last.record.to:{schema_revision:"funding-cap-policy/1",...(capActivation(data.schema_revision)?{profile_id:data.policy.profile_id}:{}),policy_id:data.policy.policy_id,policy_version:"1",cap:data.policy.cap,valid_through_ns:data.policy.valid_through_ns};
  }
  function liabilityBefore(image,seq) {
    const before=image.history.filter(e=>BigInt(e.commit_seq)<BigInt(seq));
    return before.filter(e=>e.kind==="ImportResponsibility").reduce((sum,e)=>sum+BigInt(e.record.original.amount),0n)+before.filter(e=>e.kind==="Reserve").flatMap(e=>e.record.grants).reduce((sum,g)=>sum+BigInt(g.amount),0n);
  }
  async function receiptMatches(r, image, view, discovery) {
    keys(r, ["kind", "domain_id", "record", "first_known_ns", "commit_ns", "cut", "receipt_key"], "财务原回执");
    cut(r.cut, view.cut.domain_id);
    need(r.domain_id === view.cut.domain_id && integer(r.cut.commit_seq, true) <= integer(view.cut.commit_seq) && integer(r.commit_ns) <= integer(view.commit_ns), "原回执越过固定切面");
    if (r.cut.commit_seq === view.cut.commit_seq) need(same(r.cut, view.cut), "原回执固定根不同");
    need(integer(r.first_known_ns)<=integer(r.commit_ns), "回执知识时态不同");
    const e = image.history.find(h => h.commit_seq === r.cut.commit_seq);
    need(e && (e.kind==="ReleaseExact" && e.record.state==="Unsupported" ? "ReleaseUnsupportedReceipt" : kindsOf(discovery.finance_revision)[e.kind]) === r.kind && same(e.record, r.record) && e.first_known_ns === r.first_known_ns && e.commit_ns === r.commit_ns, "原回执与历史原件不同");
    need(r.receipt_key === discovery.finance_revision + ":" + e.kind + ":" + await sha256(e.request.payload[e.kind === "ImportResponsibility" ? "responsibility_id" : ["Reserve","CloseApplicants"].includes(e.kind) ? "slot_id" : e.kind === "ActivateCapPolicy" ? "activation_id" : e.kind === "ReleaseExact" ? "command_id" : "decision_id"]), "原回执键与请求不同");
  }
  async function proof(p, horizon, discovery) {
    keys(p, ["domain_id", "receipt", "previous_root", "commit_ns", "image", "current_image", "current_epoch", "current_epoch_at_ns", "current_cut", "current_previous_root", "current_commit_ns"], "对端财务证明");
    need(discovery.domains.includes(p.domain_id), "对端证明域未知");
    integer(p.current_epoch, true);
    need(integer(p.current_epoch_at_ns) <= horizon && integer(p.commit_ns) <= horizon && integer(p.current_commit_ns) <= horizon, "对端证明晚于首次获知");
    cut(p.current_cut, p.domain_id); cut(p.receipt.cut, p.domain_id);
    need(integer(p.current_cut.commit_seq) >= integer(p.receipt.cut.commit_seq) && p.commit_ns === p.receipt.commit_ns, "对端当前切面早于原提交");
    for (const [image, c, prev, ns] of [[p.image,p.receipt.cut,p.previous_root,p.commit_ns], [p.current_image,p.current_cut,p.current_previous_root,p.current_commit_ns]]) {
      digest(prev, "对端前根");
      const root = await sha256({domain_id:p.domain_id,session_id:discovery.session_id,session_generation:discovery.session_generation,commit_seq:c.commit_seq,previous_root:prev,commit_ns:ns,image_hash:await sha256(image)});
      need(root === c.root_hash, "对端证明实际持久图像根不同");
      await financeImage(image, {cut:c,commit_ns:ns}, discovery);
    }
    await receiptMatches(p.receipt,p.image,{cut:p.receipt.cut,commit_ns:p.commit_ns},discovery);
  }
  async function grant(g, slotId, discovery) {
    keys(g, ["amount", "applicant_epoch", "applicant_generation", "attempt_id", "decision_id", "e_epoch", "execution_eligibility", "grant_id", "owner", "plan_hash", "plan_id", "policy", "prepared_cut", "quantity", "reserved_ns", "reserved_seq", "units"], "原 grant");
    need(discovery.domains.includes(g.owner) && g.owner.startsWith("B:") && g.execution_eligibility === "None", "grant owner 或资格不同");
    cut(g.prepared_cut, g.owner); digest(g.plan_hash,"grant 计划");
    integer(g.amount); integer(g.quantity,true); integer(g.applicant_epoch,true); integer(g.applicant_generation,true); integer(g.e_epoch,true); integer(g.reserved_seq,true); integer(g.reserved_ns);
    need(g.grant_id === await sha256(["tb03b-finance/1",discovery.session_id,discovery.session_generation,slotId,g.decision_id,g.plan_hash]), "grant 派生摘要不同");
  }
  function planShape(plan,version) {
    keys(plan,[...(exactRelease(version)?["exact"]:[]),"applicant_epoch","applicant_generation","attempt_id","decision_id","expected_book_version","expected_rights_version","fee_source","fee_tail","limit_price","o_ref","owner","plan_id","price_source","quantity","quantity_source","right_id","s_ref","slot_id","voice_binding_id"],"计划");
    for(const field of ["owner","decision_id","attempt_id","plan_id","slot_id","right_id","voice_binding_id","price_source","quantity_source","fee_source"])text(plan[field],field);
    for(const field of ["applicant_epoch","applicant_generation","expected_book_version","expected_rights_version","quantity","limit_price"])integer(plan[field],true);
    integer(plan.fee_tail);
    need(BigInt(plan.quantity)*BigInt(plan.limit_price)+BigInt(plan.fee_tail)<=9223372036854775807n,"原输入完整责任算式溢出");
    keys(plan.s_ref,["object_id","object_hash","profile_id",...(contentDomain(version)?["schema_revision"]:[])],"S 对象引用");
    if(contentDomain(version))need(plan.s_ref.schema_revision==="s-object-ref/2","S 引用版本不同");
    text(plan.s_ref.object_id,"S 对象");text(plan.s_ref.profile_id,"S profile");digest(plan.s_ref.object_hash,"S 对象");
    keys(plan.o_ref,["operation_id","kind","source_ref","s_object_id","quantity"],"O 引用");
    text(plan.o_ref.operation_id,"O 身份");text(plan.o_ref.source_ref,"O 来源");
    need(plan.o_ref.kind==="TestOnlyCashBuy" && plan.o_ref.s_object_id===plan.s_ref.object_id && plan.o_ref.quantity===plan.quantity,"S/O 计划绑定不同");
    if(!exactRelease(version))return;
    const x=plan.exact,names=["command_id","logical_order_family","chong_id","allocation_id","side","symbol","projection_manifest","eligibility_ref","concurrency"];
    keys(x,[...names,"revision","first_quantity"],"精确命令计划");for(const k of names)text(x[k],k);
    need(!x.command_id.includes(":") && x.revision==="1" && x.first_quantity===plan.quantity && x.side==="buy" && plan.owner==="B:"+x.chong_id,"精确命令计划超出 C1 首次提交范围");
  }
  function inputWitness(event) {
    text(event.witness.input_raw,"财务原输入");
    need(new TextEncoder().encode(event.witness.input_raw).byteLength<=16*1024*1024,"财务原输入超出原 Rust 字节上限");
    const data=parse(event.witness.input_raw);
    keys(data,["schema_revision","kind","source_id","source_epoch","policy","baseline","rights","plans","slots",...(exactRelease(data.schema_revision)?["exact_release"]:[])],"财务原输入");
    need((event.request.schema_revision==="economic-session/2"?["tb03b-finance/2","tb03b-finance/4"]:["tb03b-finance/1","tb03b-finance/3","tb03b-finance/5","tb03b-finance/6"]).includes(data.schema_revision) && data.kind==="TestOnly","财务原输入版本/范围不同");
    text(data.source_id,"输入来源");text(data.source_epoch,"输入来源代际");
    for(const k of ["rights","plans","slots"])need(Array.isArray(data[k]),"财务原输入族缺失");
    const p=data.policy,b=data.baseline;
    keys(p,["policy_id","allocation_policy_id","cap","currency","money_unit","quantity_unit","quantum","capability_id","model","valid_through_ns",...(capActivation(data.schema_revision)?["profile_id"]:[])],"原资金政策");
    for(const k of ["policy_id","currency","money_unit","quantity_unit","capability_id",...(capActivation(data.schema_revision)?["profile_id"]:[])])text(p[k],"政策 "+k);
    need(p.allocation_policy_id==="#1349/atomic-slot-wait/v1" && p.model==="TestOnlyUnleveragedCashBuy" && p.quantum==="1","原 TestOnly 政策能力范围不同");
    integer(p.cap);integer(p.valid_through_ns);
    keys(b,["responsibility_id","amount","source_ref","covered_facts"],"原责任界");text(b.responsibility_id,"责任身份");text(b.source_ref,"责任来源");integer(b.amount);
    need(Array.isArray(b.covered_facts),"原责任覆盖须数组");const facts=new Set();
    for(const f of b.covered_facts){keys(f,["fact_key","fact_hash","token"],"原责任覆盖");digest(f.fact_key,"覆盖事实身份");digest(f.fact_hash,"覆盖事实");text(f.token,"覆盖 token");need(!facts.has(f.fact_key),"原责任覆盖事实重复");facts.add(f.fact_key);}
    const rightIds=new Set(),owners=new Set();
    for(const r of data.rights){
      keys(r,["right_id","owner","version","amount","currency","source_ref"],"原输入权利");text(r.right_id,"权利身份");text(r.source_ref,"权利来源");integer(r.version,true);integer(r.amount);
      need(/^B:.+/.test(r.owner) && r.currency===p.currency && !rightIds.has(r.right_id) && !owners.has(r.owner),"原输入权利身份/币种重复或不同");rightIds.add(r.right_id);owners.add(r.owner);
    }
    const ids=new Set(),attempts=new Set(),plans=new Set();
    for(const q of data.plans){
      planShape(q,data.schema_revision);need(!exactRelease(data.schema_revision) || data.plans.filter(p=>p.exact.command_id===q.exact.command_id).length===1,"原输入 command_id 重复");const attempt=canonical([q.owner,q.attempt_id]),r=data.rights.find(r=>r.right_id===q.right_id);
      need(!ids.has(q.decision_id) && !attempts.has(attempt) && !plans.has(q.plan_id),"原输入决定/attempt/plan 身份重复");ids.add(q.decision_id);attempts.add(attempt);plans.add(q.plan_id);
      need(r && r.owner===q.owner && BigInt(r.version)<=BigInt(q.expected_rights_version),"原输入计划不属于原权利/版本");
    }
    // discovery 没有 input_sha256/授权来源目录；这些只核持久原输入的可见型域及内部一致性。
    return data;
  }
  async function inputSlots(data,discovery) {
    need(data.rights.every(r=>discovery.domains.includes(r.owner)),"原输入权利 owner 不在已配置域");
    const slots=new Set(),assigned=new Set();
    for(const s of data.slots){
      keys(s,["slot_id","applicants","input_end"],"原输入 slot");text(s.slot_id,"slot 身份");need(!slots.has(s.slot_id),"原输入 slot 重复");slots.add(s.slot_id);
      keys(s.input_end,["kind","source_id","source_epoch","watermark","complete_request_hash"],"原 slot 结束依据");integer(s.input_end.watermark,true);
      need(Array.isArray(s.applicants) && s.applicants.length>0 && s.input_end.kind==="ControlledInputEnd" && s.input_end.source_id===data.source_id && s.input_end.source_epoch===data.source_epoch && s.input_end.complete_request_hash===await sha256(s.applicants),"原 slot 结束依据不覆盖完整请求集");
      const owners=new Set();
      for(const id of s.applicants){
        text(id,"申请身份");const q=data.plans.find(q=>q.decision_id===id);
        need(q && q.slot_id===s.slot_id && !assigned.has(id) && !owners.has(q.owner),"原 slot 请求重复或归属错误");assigned.add(id);owners.add(q.owner);
      }
    }
    need(assigned.size===data.plans.length && assigned.size>0,"原输入计划未完整纳入非空关闭集合");
  }
  async function eventBinding(event,view,discovery,image) {
    need(["ImportResponsibility","Reserve","CloseApplicants","ActivateCapPolicy","MakeDispatchable","ReleaseExact"].includes(event.kind)?view.cut.domain_id==="E":view.cut.domain_id.startsWith("B:"),"财务原事件 owner 域不同");
    const request=event.request.payload,record=event.record,data=inputWitness(event);
    need(data.schema_revision===discovery.finance_revision,"财务原输入与查询版本不同");
    if(event.kind==="ActivateCapPolicy")need(capActivation(discovery.finance_revision),"cap 激活只属于 tb03b-finance/3 与 /4");
    await inputSlots(data,discovery);
    const active=activeCap(image,event.commit_seq,data);
    if(!["AbortDecision","CloseApplicants","ActivateCapPolicy"].includes(event.kind))need(BigInt(event.kind==="Reserve"?active.valid_through_ns:data.policy.valid_through_ns)>=integer(event.commit_ns),"原共同界/能力证据在提交时已过期");
    const fields={ActivateCapPolicy:["op","activation_id","policy_id","from_version","to_version","cap","valid_through_ns","policy_record","writer_epoch"],ImportResponsibility:["op","responsibility_id","writer_epoch"],PrepareDecision:["op","decision_id","plan_hash","writer_epoch"],Reserve:["op","slot_id","request_set_hash","writer_epoch"],CommitDecision:["op","decision_id","plan_hash","grant_id","writer_epoch"],AbortDecision:["op","decision_id","plan_hash","writer_epoch","reason"],CloseApplicants:["op","slot_id","writer_epoch","closed","reason"],MakeDispatchable:["op","decision_id","plan_hash","writer_epoch"],ReleaseExact:["op","decision_id","command_id","plan_hash","certificate","x_id","x_epoch","writer_epoch"]};
    keys(request,fields[event.kind],"财务原请求业务字段");integer(request.writer_epoch,true);
    if(["PrepareDecision","CommitDecision","AbortDecision"].includes(event.kind)) {
      need(request.decision_id===record.decision_id && request.plan_hash===record.prepared.plan_hash,"原计划摘要/请求业务身份不同");
      if(event.kind==="PrepareDecision")need(request.writer_epoch===record.prepared.plan.applicant_epoch,"Prepare 请求申请代际不同");
      if(event.kind==="CommitDecision")need(request.grant_id===record.grant.original.grant_id,"Commit 请求 grant 身份不同");
      if(event.kind==="AbortDecision")need(request.reason===record.abort_reason,"Abort 请求原因不同");
    } else if(event.kind==="Reserve") {
      need(request.slot_id===record.slot_id && request.request_set_hash===await sha256(record.slot.applicants) && same(record.slot,data.slots.find(s=>s.slot_id===record.slot_id)) && record.policy_id===data.policy.policy_id,"Reserve 请求业务身份或原 slot 不同");
    } else if(event.kind==="ActivateCapPolicy") {
      keys(event.witness,["input_raw","cap_policy_raw"],"cap 激活依据");
      keys(request.policy_record,["path","sha256"],"签署原件引用");digest(request.policy_record.sha256,"签署原件");
      text(event.witness.cap_policy_raw,"签署原件");
      need(await textSha256(event.witness.cap_policy_raw)===request.policy_record.sha256,"签署原件内容与引用摘要不同");
      const signed=parse(event.witness.cap_policy_raw);
      keys(signed,["schema_revision","kind","profile_id","policy_id","version","supersedes","cap","currency","money_unit","valid_through_ns","authorizer","authorized_at_ns","signature_ref"],"签署原件");
      text(signed.authorizer,"签署人");text(signed.signature_ref,"签署引用");integer(request.cap);integer(request.valid_through_ns);
      need(signed.schema_revision==="funding-cap-policy-record/1" && signed.kind==="TestOnly" && signed.profile_id===data.policy.profile_id && signed.policy_id===data.policy.policy_id && signed.currency===data.policy.currency && signed.money_unit===data.policy.money_unit && signed.version===request.to_version && signed.supersedes===request.from_version && signed.cap===request.cap && signed.valid_through_ns===request.valid_through_ns && integer(signed.authorized_at_ns)<=integer(event.commit_ns),"签署原件与激活请求或冻结政策不符");
      need(image.history.some(e=>e.kind==="ImportResponsibility" && BigInt(e.commit_seq)<BigInt(event.commit_seq)),"责任基线未规范导入不能激活");
      const liability=liabilityBefore(image,event.commit_seq);
      need(request.policy_id===data.policy.policy_id && request.from_version===active.policy_version && BigInt(request.to_version)===BigInt(active.policy_version)+1n && BigInt(request.valid_through_ns)>=integer(event.commit_ns) && liability<=BigInt(request.cap),"cap 激活越过原子点责任/版本/有效期");
      const to={schema_revision:"funding-cap-policy/1",profile_id:signed.profile_id,policy_id:request.policy_id,policy_version:request.to_version,cap:request.cap,valid_through_ns:request.valid_through_ns,activation_id:request.activation_id,replaces_version:request.from_version,policy_record_sha256:request.policy_record.sha256,authorizer:signed.authorizer,authorized_at_ns:signed.authorized_at_ns,signature_ref:signed.signature_ref,liability_at_activation:liability.toString(),activated_seq:event.commit_seq,activated_ns:event.commit_ns};
      need(same(record,{activation_id:request.activation_id,state:"CapPolicyActivated",from:active,to,liability_at_activation:liability.toString()}),"cap 激活记录与原子点重算不同");
    } else if(event.kind==="MakeDispatchable") {
      // IC E.MakeDispatchable：B 原 Commit 收据、E 自己的 grant/责任与冻结计划三者一致。
      keys(event.witness,["input_raw","commit_proof"],"Dispatchable 依据");
      const q=data.plans.find(q=>q.decision_id===request.decision_id),cp=event.witness.commit_proof,committed=cp.receipt.record;
      need(q && request.plan_hash===await sha256(q),"MakeDispatchable 原计划不符");
      need(cp.domain_id===q.owner && cp.receipt.kind==="LocalCommitReceipt" && committed.state==="Committed" && same(committed.prepared.plan,q) && same(cp.current_image.finance.decisions.find(d=>d.decision_id===q.decision_id),committed),"B 本地 Commit 原收据或当前状态不符");
      const g=committed.grant.original,reserve=image.history.find(e=>e.kind==="Reserve" && e.record.slot_id===q.slot_id);
      need(reserve && reserve.commit_seq===committed.grant.e_cut.commit_seq && image.finance.slots.some(s=>s.slot_id===q.slot_id && s.state==="Reserved" && s.grants.some(x=>same(x,g))) && image.finance.responsibilities.some(r=>r.responsibility_id===g.grant_id && r.amount===g.amount && same(r.grant,g)),"B Commit 的 grant 不是 E 原授信或责任未保留");
      need(same(record,{decision_id:q.decision_id,command_id:q.exact.command_id,state:"Dispatchable",owner:q.owner,plan_hash:request.plan_hash,grant_id:g.grant_id,local_commit_receipt:committed.local_commit_receipt,commit_cut:cp.receipt.cut,dispatchable_seq:event.commit_seq,dispatchable_ns:event.commit_ns,execution_eligibility:"None"}),"Dispatchable 记录与原 Commit/计划重算不同");
    } else if(event.kind==="ReleaseExact") {
      keys(event.witness,["input_raw"],"放行依据");
      await verifyRelease(event,image,data,discovery);
    } else if(event.kind==="ImportResponsibility") {
      const original={responsibility_id:data.baseline.responsibility_id,owner:"E:baseline",amount:data.baseline.amount,source:data.baseline,policy:data.policy};
      need(request.responsibility_id===data.baseline.responsibility_id && same(record,{responsibility_id:data.baseline.responsibility_id,state:"ResponsibilityImported",original}),"原责任导入全公式/身份不同");
    } else {
      text(request.reason,"关闭申请原因");
      need(request.slot_id===record.slot_id && same(request.closed,record.closed) && request.reason===record.reason && record.commit_ns===event.commit_ns && record.state==="ApplicantsClosed" && record.responsibility_release==="None", "关闭申请原请求不同");
      need(Array.isArray(record.closed) && record.closed.length>0,"关闭申请集合为空");
      const owners=new Set();
      for(const c of record.closed){
        need(!owners.has(c.owner),"本次关闭申请 owner 重复");owners.add(c.owner);
        keys(c,["owner","applicant_epoch","applicant_generation"],"关闭申请");integer(c.applicant_epoch,true);integer(c.applicant_generation,true);
        need(data.plans.some(p=>p.slot_id===record.slot_id && p.owner===c.owner && p.applicant_epoch===c.applicant_epoch && p.applicant_generation===c.applicant_generation),"关闭对象不在原完整申请集合");
      }
    }
  }
  // 用 Dispatchable 原记录、冻结投影与证书重算放行对象；不能从 X 的接纳状态反推 E。
  async function verifyRelease(event,image,data,discovery) {
    const req=event.request.payload,q=data.plans.find(p=>p.decision_id===req.decision_id);
    const made=image.history.find(e=>e.kind==="MakeDispatchable" && e.record.command_id===req.command_id);
    need(q && made && BigInt(made.commit_seq)<BigInt(event.commit_seq),"放行缺原 Dispatchable");
    const base=made.record,x=q.exact,s=data.exact_release, target=s.x_target;
    const change={kind:"submit",order:{command_id:x.command_id,family_id:x.logical_order_family,chong_id:x.chong_id,
      revision:x.revision,side:x.side,quantity:q.quantity,kind:{kind:"limit",price:q.limit_price},
      eligibility_ref:x.eligibility_ref,projection_manifest:x.projection_manifest}};
    const certificate={rd11_policy:s.rd11_policy,responsibility_refs:[base.grant_id],
      structure_dependencies:[q.s_ref.object_id+"@"+q.s_ref.object_hash],market_dependencies:s.market_dependencies,
      rule_revision:s.rule_revision,conditions:s.conditions};
    const coverage=s.model_coverage,model_ref=coverage.model_ref;
    if(modelBinding(data.schema_revision)) digest(model_ref.content_hash,"模型内容摘要");
    const command={command_id:x.command_id,logical_order_family:x.logical_order_family,first_quantity:x.first_quantity,
      allocation_id:x.allocation_id,session_id:discovery.session_id,session_generation:discovery.session_generation,
      x_id:target.x_id,x_epoch:target.x_epoch,symbol:x.symbol,projection_kind:s.projection_kind,
      ...(modelBinding(data.schema_revision)?{model_ref}:{}),change,
      plan_hash:await sha256(change),certificate,certificate_hash:await sha256(certificate)};
    need(req.command_id===x.command_id && base.decision_id===q.decision_id && base.plan_hash===await sha256(q)
      && req.x_id===target.x_id && req.x_epoch===target.x_epoch && req.plan_hash===command.plan_hash
      && same(req.certificate,certificate),"放行请求不属于冻结计划、条件或 X");
    const scope={order_kind:"limit",concurrency:x.concurrency,allocation_model:data.policy.allocation_policy_id};
    const covered=coverage.input_domain.some(d=>same(d,scope)) && !coverage.unsupported_domains.some(d=>same(d,scope));
    const result=covered ? {state:"ReleasedExact",first_quantity:x.first_quantity,allocation_id:x.allocation_id,
      responsibility_ref:base.grant_id,release_seq:event.commit_seq,release_commit_ns:event.commit_ns,model_ref,
      execution_eligibility:"ReleasedExact"} : {state:"Unsupported",unsupported_seq:event.commit_seq,
      unsupported_ns:event.commit_ns,unsupported:{reason:"ModelOrderUnspecified",model_ref,domain_id:coverage.domain_id,command_id:x.command_id}};
    need(same(event.record,{...base,command,command_hash:await sha256(command),...result}),"命令或放行记录与冻结原件不同");
  }
  function commandEvents(history,id) {
    return history.filter(e=>["MakeDispatchable","ReleaseExact"].includes(e.kind) && e.record.command_id===id);
  }
  function bookBefore(image,seq) {
    let opening=null,quantity=null;
    for(const e of image.history.filter(e=>e.kind==="ApplyAllocation" && BigInt(e.commit_seq)<BigInt(seq) && e.application.status==="Applied")) {
      const source=image.recorded.find(r=>r.fact_key===e.application.fact_key);
      need(source && same(source.event,e.event) && same(parse(source.raw_utf8).units,image.book.units),"Prepare 原 cut 的开局/量纲来源不同");
      if(Object.hasOwn(e.event,"observed_existing_book")) {
        need(opening===null,"历史开局重复");opening=e.event;quantity=integer(e.event.observed_existing_book.units,false,true);
      } else {
        need(opening && e.event.family_id===opening.family_id,"历史变动缺同族开局");quantity+=integer(e.event.deltas.units,false,true);
        need(quantity>=0n && quantity<=9223372036854775807n,"历史实际量越出精确域");
      }
    }
    need(opening && image.book && image.book.fixed_q===opening.book_identity.fixed_q && image.book.symbol===opening.book_identity.symbol && image.book.operation_level===opening.book_identity.op_level,"Prepare 固定 Q/标的/级别缺实际原账");
    return quantity;
  }
  function preparedBinding(p,event,image) {
    const data=inputWitness(event),plan=p.plan,book=image.book;
    need(same(plan,data.plans.find(q=>q.decision_id===plan.decision_id)),"Prepare 原计划绑定不同");
    keys(p.right_source,["amount","currency","owner","right_id","source_ref","version"],"Prepared 原权利");
    need(same(p.right_source,data.rights.find(r=>r.right_id===plan.right_id)) && p.right_source.currency===p.units.money.currency,"Prepare 原权利来源不同");
    need(book.units.money.currency===data.policy.currency && book.units.money.unit===data.policy.money_unit && book.units.quantity.unit===data.policy.quantity_unit,"Prepare 原账/权利/政策量纲不同");
    need(p.prepared_ns===event.commit_ns && p.book_version_after===event.commit_seq && BigInt(p.book_version_before)+1n===BigInt(event.commit_seq),"Prepare 原事件时刻/序号不同");
    const quantity=bookBefore(image,event.commit_seq),earlier=image.history.filter(e=>e.kind==="PrepareDecision" && BigInt(e.commit_seq)<BigInt(event.commit_seq));
    const worst=quantity+BigInt(plan.quantity)+earlier.reduce((sum,e)=>sum+integer(e.record.prepared.plan.quantity,true),0n);
    need(p.actual_quantity===quantity.toString() && p.fixed_q===book.fixed_q && same(p.units,book.units) && p.worst_quantity===worst.toString() && worst<=BigInt(book.fixed_q),"Prepare 原 cut 实际量/固定 Q/最坏量不同");
    const rightBefore=integer(p.right_source.version,true)+BigInt(earlier.filter(e=>e.record.prepared.plan.right_id===plan.right_id).length);
    need(BigInt(p.rights_version_before)===rightBefore,"Prepare 原权利 CAS 版本不同");
    const voice=image.history.find(e=>e.kind==="BindVoice" && e.record.binding_id===plan.voice_binding_id && BigInt(e.commit_seq)<BigInt(event.commit_seq));
    need(voice && same(voice.record,p.voice) && book.voice.status==="Bound" && book.voice.records.some(v=>same(v,p.voice)) && p.voice.identity.sigma==="Long" && p.voice.instrument===book.symbol && p.voice.operation_level===book.operation_level && BigInt(p.voice.commit_ns)<=BigInt(event.first_known_ns),"Prepare 原 Voice 绑定/标的/时序不同");
    const right=image.finance.rights.find(r=>r.right_id===plan.right_id);
    need(right && ["amount","currency","owner","right_id","source_ref","version"].every(k=>same(right[k],p.right_source[k])),"Prepare 原权利与实际权利绑定不同");
  }
  function financeCoverage(image,view) {
    const f=image.finance,history=image.history,events=history.filter(e=>Object.hasOwn(kindsOf(f.schema_revision),e.kind));
    if(events.length) {
      need(history.at(-1).commit_seq===view.cut.commit_seq && history.at(-1).commit_ns===view.commit_ns,"实际历史末尾与固定切面不同");
      need(history.every((e,i)=>e.commit_seq===(BigInt(i)+1n).toString() && (i===0 || integer(e.commit_ns)>=integer(history[i-1].commit_ns))),"完整历史序号/提交时序不同");
    }
    const preparations=events.filter(e=>e.kind==="PrepareDecision"),ids=new Set();
    for(const e of preparations) {
      const id=e.record.decision_id;need(!ids.has(id),"Prepare 历史身份重复");ids.add(id);
      const d=f.decisions.find(d=>d.decision_id===id),chain=events.filter(h=>["PrepareDecision","CommitDecision","AbortDecision"].includes(h.kind) && h.record.decision_id===id);
      need(d && chain.length<=2 && same(chain.at(-1).record,d),"决定与历史须双向完整覆盖");
      if(chain.length===2)need(chain[0]===e && ["CommitDecision","AbortDecision"].includes(chain[1].kind) && BigInt(chain[1].commit_seq)>BigInt(e.commit_seq) && BigInt(chain[1].commit_ns)>=BigInt(e.commit_ns),"决定终态先于原 Prepare");
    }
    need(f.decisions.length===ids.size,"当前决定缺原 Prepare 历史");
    if(preparations.length)need(bookBefore(image,(integer(view.cut.commit_seq)+1n).toString()).toString()===image.book.actual_quantity,"当前实际量与已应用原事实历史不同");
    const rights=new Set(preparations.map(e=>e.record.prepared.plan.right_id));
    need(f.rights.length===rights.size && new Set(f.rights.map(r=>r.right_id)).size===rights.size && f.rights.every(r=>rights.has(r.right_id)),"权利与 Prepare 须双向完整覆盖");
    for(const r of f.rights) {
      const chain=preparations.filter(e=>e.record.prepared.plan.right_id===r.right_id);
      need(r.current_version===chain.at(-1).record.prepared.rights_version_after,"当前权利版本与 Prepare 末尾不同");
    }
    const reserves=events.filter(e=>e.kind==="Reserve");
    need(reserves.length===f.slots.length && reserves.every(e=>f.slots.some(s=>same(s,e.record))),"slot 与 Reserve 须双向完整覆盖");
    const originals=[...events.filter(e=>e.kind==="ImportResponsibility").map(e=>e.record.original),...f.slots.flatMap(s=>s.grants.map(g=>({amount:g.amount,grant:g,owner:g.owner,responsibility_id:g.grant_id})))];
    need(originals.length===f.responsibilities.length && originals.every(r=>f.responsibilities.some(x=>same(x,r))),"责任与原导入/grant 须双向完整覆盖");
    const closed=events.filter(e=>e.kind==="CloseApplicants").flatMap(e=>e.record.closed.map(c=>({...c,slot_id:e.record.slot_id})));
    need(same(f.closed_applicants||[],closed),"关闭申请与原历史须双向覆盖");
    const activations=events.filter(e=>e.kind==="ActivateCapPolicy");
    need(activations.length?same(f.cap_policy,activations.at(-1).record.to):!Object.hasOwn(f,"cap_policy"),"当前 cap 版本与激活历史末尾不同");
    if(exactRelease(f.schema_revision)) {
      const current=new Map();
      for(const event of events.filter(e=>["MakeDispatchable","ReleaseExact"].includes(e.kind))) {
        const id=event.record.command_id, prior=current.get(id);
        need(event.kind==="MakeDispatchable" ? !prior : prior?.state==="Dispatchable","命令历史缺原准备或出现重复迁移");
        current.set(id,event.record);
      }
      need(current.size===f.commands.length && [...current.values()].every(r=>f.commands.some(c=>same(c,r))),"命令当前记录与所选切面历史末项不同");
    }
  }
  function reservePrepared(reserve) {
    const proofs=reserve.witness.prepared_proofs,ids=new Set(),data=inputWitness(reserve),slot=reserve.record;
    need(Array.isArray(proofs),"Reserve Prepared 证明族缺失");
    const active=slot.slot.applicants.filter(id=>{
      const plan=data.plans.find(p=>p.decision_id===id);
      need(plan && plan.slot_id===slot.slot_id,"Reserve 原申请集合不同");
      return !slot.closed_applicants.some(c=>c.slot_id===slot.slot_id && c.owner===plan.owner && c.applicant_epoch===plan.applicant_epoch && c.applicant_generation===plan.applicant_generation);
    });
    need(active.length>0 && proofs.length===active.length,"Reserve 完整同 slot 申请覆盖不同");
    for(const pf of proofs) {
      const original=pf.receipt.record,p=original.prepared,plan=p.plan,current=pf.current_image.finance.decisions.find(d=>d.decision_id===original.decision_id);
      need(!ids.has(original.decision_id) && active.includes(original.decision_id),"Reserve Prepared 身份重复/越范围");ids.add(original.decision_id);
      need(pf.receipt.kind==="PreparedReceipt" && original.state==="Prepared" && same(plan,data.plans.find(q=>q.decision_id===original.decision_id)) && current && current.state==="Prepared" && same(current,original),"Reserve 原 Prepared/当前状态已失效");
      need(pf.current_epoch===plan.applicant_epoch && pf.current_cut.commit_seq===p.book_version_after && pf.current_image.history.at(-1).commit_seq===p.book_version_after,"Reserve 申请代际或原 Prepared 切面不同");
    }
  }
  async function grantBinding(g,p,reserve,preparedCut,discovery) {
    const plan=p.plan,s=reserve.record;
    await grant(g,plan.slot_id,discovery);
    for(const k of ["owner","decision_id","plan_id","attempt_id","applicant_epoch","applicant_generation","quantity"])need(g[k]===plan[k],"grant 与 Prepared 绑定不同");
    need(g.plan_hash===p.plan_hash && g.amount===p.locked_amount && same(g.units,p.units) && same(g.prepared_cut,preparedCut) && g.e_epoch===reserve.request.payload.writer_epoch && g.reserved_ns===reserve.commit_ns && g.reserved_seq===reserve.commit_seq && same(g.policy,inputWitness(reserve).policy) && s.slot_id===plan.slot_id,"grant 与 Prepared 金额/切面/原 Reserve 绑定不同");
  }
  function commitScope(event,plan,g) {
    const gp=event.witness.grant_proof,slot=gp.receipt.record,current=gp.current_image.finance;
    need(gp.receipt.kind==="ReserveReceipt" && slot.state==="Reserved" && slot.slot_id===plan.slot_id && current.slots.some(s=>same(s,slot)) && slot.grants.some(x=>same(x,g)),"Commit 捕获 E 当前 slot 范围已失效");
    need(!(current.closed_applicants||[]).some(c=>c.slot_id===plan.slot_id && c.owner===plan.owner && c.applicant_epoch===plan.applicant_epoch && c.applicant_generation===plan.applicant_generation),"Commit 捕获 E 当前申请代际已关闭");
    const coverage=inputWitness(event).baseline.covered_facts;
    for(const pending of gp.current_image.pending) {
      const c=coverage.find(c=>c.fact_key===pending.fact_key && c.token===pending.token),fact=gp.current_image.recorded.find(r=>c && r.fact_key===c.fact_key);
      need(c && fact && fact.fact_hash===c.fact_hash,"Commit 捕获 E 当前 Pending 未被原责任覆盖");
    }
  }
  async function decision(d, view, discovery, image) {
    keys(d, ["decision_id", "execution_eligibility", "grant", "local_commit_receipt", "prepared", "state", "structure_evidence", ...(d.state === "AbortedBeforeCommit" ? ["abort_reason","abort_ns"] : [])], "决定原件");
    need(["Prepared","Committed","AbortedBeforeCommit"].includes(d.state) && d.execution_eligibility === "None", "普通财务状态不能有执行资格");
    const p=d.prepared, plan=p.plan, domain=view.cut.domain_id;
    keys(p, ["actual_quantity","book_version_after","book_version_before","fixed_q","locked_amount","plan","plan_hash","prepared_ns","right_source","rights_version_after","rights_version_before","units","voice","worst_quantity"], "Prepared");
    planShape(plan,discovery.finance_revision);
    need(domain.startsWith("B:") && plan.owner===domain && plan.decision_id===d.decision_id,"决定与计划归属不符");
    need(p.plan_hash === await sha256(plan), "原计划摘要不同");
    const locked=integer(plan.quantity,true)*integer(plan.limit_price,true)+integer(plan.fee_tail);
    need(integer(p.locked_amount) === locked && locked <= 9223372036854775807n, "私有锁未覆盖全额责任");
    need(integer(p.worst_quantity) >= integer(p.actual_quantity,false,true)+BigInt(plan.quantity) && BigInt(p.worst_quantity) <= integer(p.fixed_q,true), "最坏量越过固定 Q");
    need(p.book_version_before === plan.expected_book_version && integer(p.book_version_after,true) === BigInt(p.book_version_before)+1n && p.rights_version_before === plan.expected_rights_version && integer(p.rights_version_after,true) === BigInt(p.rights_version_before)+1n, "准备版本未逐步增加");
    need(BigInt(p.book_version_after) <= integer(view.cut.commit_seq) && integer(p.prepared_ns) <= integer(view.commit_ns), "Prepared 晚于观察切面");
    need(p.right_source.owner === domain && p.right_source.right_id === plan.right_id && integer(p.right_source.amount) >= locked && p.voice.binding_id === plan.voice_binding_id, "权利或 Voice 绑定不同");
    evidence(d.structure_evidence,discovery,BigInt(p.prepared_ns));
    const prepared=image.history.find(e=>e.kind === "PrepareDecision" && e.record.decision_id === d.decision_id);
    need(prepared && same(prepared.record.prepared,p) && same(prepared.record.structure_evidence,d.structure_evidence), "决定改变首次 Prepare 原件");
    preparedBinding(p,prepared,image);
    if (d.state !== "Committed") {
      need(d.grant === null && d.local_commit_receipt === null, "未提交状态不能回填收据");
      if (d.state === "AbortedBeforeCommit") {
        text(d.abort_reason,"中止原因");const abort=image.history.find(e=>e.kind==="AbortDecision" && e.record.decision_id===d.decision_id);
        need(abort && same(abort.record,d) && d.abort_ns===abort.commit_ns && integer(d.abort_ns)>=BigInt(p.prepared_ns) && BigInt(d.abort_ns)<=BigInt(view.commit_ns),"Abort 缺合法原历史/Prepare 后时序");
      }
      return;
    }
    keys(d.grant,["e_cut","original"],"决定原 grant");
    const g=d.grant.original,r=d.local_commit_receipt;
    await grant(g,plan.slot_id,discovery); cut(d.grant.e_cut,"E");
    for (const k of ["owner","decision_id","plan_id","attempt_id","applicant_epoch","applicant_generation","quantity"]) need(g[k] === plan[k], "grant 与 Prepared 绑定不同");
    need(g.plan_hash === p.plan_hash && g.amount === p.locked_amount && same(g.units,p.units) && g.prepared_cut.commit_seq === prepared.commit_seq, "grant 与 Prepared 金额/切面不同");
    keys(r,["book_version_after","book_version_before","commit_hash","commit_ns","decision_id","e_cut","execution_eligibility","grant_id","plan_hash"],"本地提交收据");
    cut(r.e_cut,"E");
    need(r.execution_eligibility === "None" && r.decision_id === d.decision_id && r.grant_id === g.grant_id && r.plan_hash === p.plan_hash && same(r.e_cut,d.grant.e_cut), "本地收据身份不同");
    need(integer(r.book_version_after,true) === integer(r.book_version_before,true)+1n && BigInt(r.book_version_after)<=BigInt(view.cut.commit_seq) && integer(r.commit_ns)<=BigInt(view.commit_ns) && integer(g.reserved_ns)<=BigInt(r.commit_ns), "提交版本或先增责时序不同");
    need(r.commit_hash === await sha256([prepared.record,g,r.e_cut,r.book_version_after,r.commit_ns]), "本地提交摘要不同");
    const event=image.history.find(e=>e.kind === "CommitDecision" && e.record.decision_id === d.decision_id);
    need(event && same(event.record,d) && event.commit_ns === r.commit_ns && event.commit_seq === r.book_version_after, "提交与历史原件不同");
    const gp=event.witness.grant_proof;
    const reserve=gp.image.history.find(e=>e.kind==="Reserve" && e.commit_seq===g.reserved_seq);
    need(reserve && r.book_version_before===p.book_version_after,"Commit 原 Prepare CAS 或 Reserve 不同");
    await grantBinding(g,p,reserve,g.prepared_cut,discovery);
    commitScope(event,plan,g);
    need(same(gp.receipt.cut,r.e_cut) && gp.receipt.record.grants.some(x=>same(x,g)) && gp.current_image.finance.responsibilities.some(x=>x.responsibility_id === g.grant_id && x.amount === g.amount && same(x.grant,g)), "提交缺 E 原 grant/保留责任");
  }
  async function verifyFinance(f, view, discovery, image) {
    const domain=view.cut.domain_id;
    const v3=capActivation(discovery.finance_revision);
    keys(f,["schema_revision","rights","decisions","slots","responsibilities",...(exactRelease(discovery.finance_revision)?["commands"]:[]),...(Object.hasOwn(f,"closed_applicants")?["closed_applicants"]:[]),...(v3 && Object.hasOwn(f,"cap_policy")?["cap_policy"]:[])],"财务图像");
    need(f.schema_revision === discovery.finance_revision,"未知或混搭财务版本");
    for(const k of Object.keys(f).filter(k=>k!=="schema_revision" && k!=="cap_policy"))need(Array.isArray(f[k]),"财务记录族须数组");
    financeCoverage(image,view);
    const ids=new Set();
    for(const d of f.decisions){need(!ids.has(d.decision_id),"决定身份重复");ids.add(d.decision_id);await decision(d,view,discovery,image);}
    for(const r of f.rights){
      keys(r,["amount","currency","current_version","locked_amount","owner","right_id","source_ref","version"],"私有权利");
      need(domain.startsWith("B:") && r.owner===domain,"私有权利 owner 不同");
      need(integer(r.current_version,true)>=integer(r.version,true) && integer(r.locked_amount)<=integer(r.amount),"私有权利版本或全额锁不同");
      const total=f.decisions.filter(d=>d.prepared.plan.right_id===r.right_id).reduce((sum,d)=>sum+BigInt(d.prepared.locked_amount),0n);
      need(total===BigInt(r.locked_amount),"私有权利锁与决定总额不同");
    }
    const responsibilities=new Map();
    for(const r of f.responsibilities){
      keys(r,Object.hasOwn(r,"grant")?["amount","grant","owner","responsibility_id"]:["amount","owner","policy","responsibility_id","source"],"公共责任");
      need(domain==="E" && !responsibilities.has(r.responsibility_id),"公共责任 owner/身份不同");integer(r.amount);responsibilities.set(r.responsibility_id,r);
    }
    const slotIds=new Set();
    for(const s of f.slots){
      keys(s,["closed_applicants","grants","policy_id","required_total","reserve_ns","reserve_seq","retained_total","slot","slot_id","state","waiting_for",...(v3 && Object.hasOwn(s,"cap_policy")?["cap_policy"]:[])],"财务 slot");
      need(domain==="E" && !slotIds.has(s.slot_id) && ["Reserved","AwaitingAllocationPolicy"].includes(s.state),"slot 身份或状态不同");slotIds.add(s.slot_id);
      need(Array.isArray(s.grants) && Array.isArray(s.closed_applicants) && s.slot.slot_id===s.slot_id,"slot 原件不同");
      if(s.state==="AwaitingAllocationPolicy")need(s.waiting_for==="#1349/atomic-slot-wait/v1" && s.grants.length===0,"未决政策不能选择赢家");
      need(integer(s.reserve_seq,true)<=integer(view.cut.commit_seq) && integer(s.reserve_ns)<=integer(view.commit_ns),"Reserve 晚于固定切面");
      const reserve=image.history.find(e=>e.kind==="Reserve" && e.commit_seq===s.reserve_seq);
      need(reserve && same(reserve.record,s),"slot 与历史 Reserve 不同");
      reservePrepared(reserve);
      const earlierClosed=image.history.filter(e=>e.kind==="CloseApplicants" && BigInt(e.commit_seq)<BigInt(s.reserve_seq)).flatMap(e=>e.record.closed.map(c=>({...c,slot_id:e.record.slot_id})));
      need(same(s.closed_applicants,earlierClosed),"Reserve 关闭范围与捕获前历史不同");
      const grantIds=new Set();
      for(const g of s.grants){
        await grant(g,s.slot_id,discovery);need(!grantIds.has(g.grant_id),"grant 身份重复");grantIds.add(g.grant_id);
        const r=responsibilities.get(g.grant_id),pf=reserve.witness.prepared_proofs.find(p=>p.domain_id===g.owner && p.receipt.record.decision_id===g.decision_id);
        need(r && r.owner===g.owner && r.amount===g.amount && same(r.grant,g),"grant 缺先增全额责任");
        need(pf && same(pf.receipt.cut,g.prepared_cut),"grant Prepared 切面不同");
        const p=pf.receipt.record.prepared;
        await grantBinding(g,p,reserve,pf.receipt.cut,discovery);
        need(g.amount===p.locked_amount && g.plan_hash===p.plan_hash && g.quantity===p.plan.quantity && g.reserved_ns===s.reserve_ns && g.reserved_seq===s.reserve_seq,"grant 与原准备/保留不同");
      }
      const before=f.responsibilities.filter(r=>!r.grant || BigInt(r.grant.reserved_seq)<BigInt(s.reserve_seq)).reduce((sum,r)=>sum+BigInt(r.amount),0n);
      const required=before+reserve.witness.prepared_proofs.reduce((sum,p)=>sum+BigInt(p.receipt.record.prepared.locked_amount),0n);
      const retained=before+s.grants.reduce((sum,g)=>sum+BigInt(g.amount),0n);
      const cap=activeCap(image,s.reserve_seq,inputWitness(reserve));
      need(image.history.some(e=>e.kind==="ActivateCapPolicy" && BigInt(e.commit_seq)<BigInt(s.reserve_seq))?same(s.cap_policy,cap):!Object.hasOwn(s,"cap_policy"),"Reserve 所用 cap 版本不同");
      need((s.state==="Reserved") === (required<=integer(cap.cap)) && (s.state!=="Reserved" || (s.grants.length===reserve.witness.prepared_proofs.length && s.waiting_for===null)),"Reserve 原共同界/完整授信状态不同");
      need(integer(s.retained_total)===retained && integer(s.required_total)===required && required<=9223372036854775807n && retained<=9223372036854775807n,"公共责任总额不同");
    }
  }
  async function financeImage(image, view, discovery) {
    keys(image,["book","recorded","pending","applied","unmatched","history",...(discovery.finance_revision === undefined?[]:["finance"])],"完整经济图像");
    for(const k of ["recorded","pending","applied","unmatched","history"])need(Array.isArray(image[k]),"经济记录族不是数组");
    if(discovery.finance_revision===undefined)return;
    const kinds=kindsOf(discovery.finance_revision);
    for(const e of image.history){
      if(!Object.hasOwn(kinds,e.kind))continue;
      keys(e,["kind","record","request","witness","received_ns","first_known_ns","commit_ns","commit_seq"],"财务事件");
      const first=integer(e.first_known_ns);
      need(integer(e.received_ns)<=first && first<=integer(e.commit_ns) && BigInt(e.commit_ns)<=integer(view.commit_ns) && integer(e.commit_seq,true)<=integer(view.cut.commit_seq),"财务事件知识时态不同");
      need(e.request.schema_revision===revision(discovery) && e.request.session_id===discovery.session_id && e.request.session_generation===discovery.session_generation && e.request.payload.op===e.kind && e.request.payload_hash===await sha256(e.request.payload),"财务历史请求版本或摘要不同");
      await eventBinding(e,view,discovery,image);
      if(["PrepareDecision","Reserve","CommitDecision"].includes(e.kind))evidence(e.witness.structure,discovery,first);
      if(Object.hasOwn(e.record,"structure_evidence"))evidence(e.record.structure_evidence,discovery,first);
      if(e.kind==="PrepareDecision")need(same(e.record.structure_evidence,e.witness.structure) && e.record.state==="Prepared", "Prepare 依据被替换");
      if(e.kind==="Reserve")for(const p of e.witness.prepared_proofs)await proof(p,first,discovery);
      if(e.kind==="CommitDecision")await proof(e.witness.grant_proof,first,discovery);
      if(e.kind==="MakeDispatchable")await proof(e.witness.commit_proof,first,discovery);
    }
    // §5.7 仅递归列明 schema 路径；不猜测同名字段，不展开内容图改写 Hash。
    for(const r of image.recorded)if(Object.hasOwn(r,"e_commit_proof")){
      keys(r.e_commit_proof,["commit_ns","image","previous_root"],"原 E 提交证明");
      need(integer(r.e_commit_proof.commit_ns)<=integer(r.b_observation.first_known_ns),"原 E 图像晚于获知");
      cut(r.cut,"E");digest(r.e_commit_proof.previous_root,"原 E 前根");
      need(r.e_session_id===discovery.session_id && r.e_session_generation===discovery.session_generation && r.cut.root_hash===await sha256({domain_id:"E",session_id:r.e_session_id,session_generation:r.e_session_generation,commit_seq:r.cut.commit_seq,previous_root:r.e_commit_proof.previous_root,commit_ns:r.e_commit_proof.commit_ns,image_hash:await sha256(r.e_commit_proof.image)}),"原 E 提交实际根不同");
      await financeImage(r.e_commit_proof.image,{cut:r.cut,commit_ns:r.e_commit_proof.commit_ns},discovery);
    }
    await verifyFinance(image.finance,view,discovery,image);
  }
  async function verifyOriginal(reply, state, discovery, domain, kind, id) {
    need(state.completeness==="CompleteVector" && (["decision","grant"].includes(kind) || (kind==="command" && domain==="E" && exactRelease(discovery.finance_revision))),"原件请求缺固定完整向量");
    keys(reply,["kind","session_id","session_generation","manifest_hash","cuts","domain_id","original"],"经济原件");
    const cuts=Object.fromEntries(Object.entries(state.domains).map(([d,v])=>[d,v.cut]));
    need(reply.kind==="EconomicOriginal" && reply.session_id===state.session_id && reply.session_generation===state.session_generation && reply.manifest_hash===state.manifest_hash && reply.domain_id===domain && same(reply.cuts,cuts),"原件身份或固定向量不同");
    const view=state.domains[domain],o=reply.original;
    need(view && view.status==="Available","原件域不可用");
    if(kind==="command"){
      const record=view.image.finance.commands.find(c=>c.command_id===id);
      const head={kind:"EconomicCommand",domain_id:domain,command_id:id,cut:view.cut};
      if(!record)need(same(o,{...head,state:"NoRecord"}),"无命令切面返回了其他原件");
      else {
        keys(o,[...Object.keys(head),"state","record","receipts"],"命令原件");
        need(Object.keys(head).every(k=>same(head[k],o[k])) && o.state===record.state && same(o.record,record),"命令身份、记录或切面不同");
        const chain=commandEvents(view.image.history,id);
        need(chain.length>0 && Array.isArray(o.receipts) && o.receipts.length===chain.length,"命令回执链不完整");
        for(const [i,r] of o.receipts.entries()){
          need(r.cut.commit_seq===chain[i].commit_seq,"命令原回执不属于所选历史");
          await receiptMatches(r,view.image,view,discovery);
        }
      }
      return reply;
    }
    keys(o,kind==="decision"?["kind","domain_id","decision","receipts"]:["kind","domain_id","grant","receipt"],"原件记录");
    need(o.domain_id===domain && o.kind===(kind==="decision"?"EconomicDecision":"EconomicGrant"),"原件类型或 owner 不同");
    if(kind==="decision"){
      const d=view.image.finance.decisions.find(x=>x.decision_id===id);
      need(d && same(o.decision,d) && Array.isArray(o.receipts),"决定原件与快照不同");
      if(d.grant) {
        const preparedReceipt=o.receipts.find(r=>r.kind==="PreparedReceipt");
        need(preparedReceipt && same(preparedReceipt.cut,d.grant.original.prepared_cut),"原 Prepared 回执根与 grant 不同");
      }
      const events=view.image.history.filter(e=>Object.hasOwn(financeKinds,e.kind) && e.record.decision_id===id);
      need(o.receipts.length===events.length && new Set(o.receipts.map(r=>r.cut.commit_seq)).size===events.length,"决定原回执不完整");
      for(const r of o.receipts)await receiptMatches(r,view.image,view,discovery);
    }else{
      const g=view.image.finance.slots.flatMap(s=>s.grants).find(x=>x.grant_id===id);
      need(g && same(o.grant,g) && o.receipt.record.grants.some(x=>same(x,g)),"grant 原件与快照不同");
      await receiptMatches(o.receipt,view.image,view,discovery);
    }
    return reply;
  }
  async function verifySnapshot(value, discovery) {
    revision(discovery);
    keys(value, ["kind", "session_id", "session_generation", "manifest_hash", "mode", "as_known_ns", "domains", "completeness", "snapshot_token"], "经济快照");
    need(value.kind === "EconomicSnapshot" && value.session_id === discovery.session_id &&
      value.session_generation === discovery.session_generation && value.manifest_hash === discovery.manifest_hash, "经济快照会话或配置不符");
    need(value.mode === "Current" || value.mode === "AsKnown", "未知经济历史模式");
    if (value.as_known_ns !== null) integer(value.as_known_ns);
    keys(value.domains, discovery.domains, "全部经济域");
    let complete = true;
    for (const domain of discovery.domains) {
      const view = value.domains[domain];
      if (view.status === "Unavailable") {
        keys(view, ["status", "error"], "不可用域");
        need(typeof view.error === "string" && view.error.length > 0, "域不可用原因缺失");
        complete = false;
        continue;
      }
      keys(view, ["status", "cut", "commit_ns", "image", "image_hash"], "可用域");
      need(view.status === "Available", "未知域状态");
      cut(view.cut, domain);
      integer(view.commit_ns);
      if (value.as_known_ns !== null) need(BigInt(view.commit_ns) <= BigInt(value.as_known_ns), "图像晚于所声明的获知截止时刻");
      await financeImage(view.image, view, discovery);
      for (const key of ["recorded", "pending", "applied", "unmatched", "history"]) need(Array.isArray(view.image[key]), "经济记录族不是数组");
      need(await sha256(view.image) === view.image_hash, "完整经济图像摘要不同");
      const book = view.image.book;
      if (domain === "E") need(book === null, "E 不能伪装重账");
      else if (book !== null) {
        need(object(book) && domain === "B:" + book.chong_id, "重归属与权威域不同");
        integer(book.fixed_q, true); integer(book.operation_level); integer(book.actual_quantity, false, true);
        integer(book.opening_quantity, false, true);
        keys(book.income_book, ["Pi", "A", "W", "R"], "利润账");
        for (const amount of Object.values(book.income_book)) integer(amount, false, true);
        for (const amount of Object.values(book.known_cost_totals)) integer(amount, false, true);
        need(object(book.unknown) && object(book.voice) && Array.isArray(book.known_cost_components), "缺失账簿知识状态/原始成本史");
        await verifyVoices(book, view, discovery, domain);
      }
    }
    need(value.completeness === (complete ? "CompleteVector" : "PartialVector"), "域完整性声明与实际结果不同");
    const vectorCuts = Object.fromEntries(
      discovery.domains.map(d => [d, value.domains[d].status === "Available" ? value.domains[d].cut : null])
    );
    verifyEmbeddedCutsAgainstVector(value, vectorCuts, discovery.domains, false);
    const body = {...value}; delete body.snapshot_token;
    need(value.snapshot_token === "economic-snapshot-" + await sha256(body), "固定向量 token 与完整图像不同");
    return value;
  }
  const PROJECTION_REV = "economic-read-projection/1";
  const PROJECTION_ORIG_KINDS = ["fact", "allocation", "decision", "grant", "command", "model"];
  function isCutShape(v) {
    if (!object(v)) return false;
    const ks = Object.keys(v);
    return ks.length === 3 && Object.prototype.hasOwnProperty.call(v, "domain_id")
      && Object.prototype.hasOwnProperty.call(v, "commit_seq")
      && Object.prototype.hasOwnProperty.call(v, "root_hash");
  }
  function verifyEmbeddedCutsAgainstVector(root, cuts, knownDomains, requireKnownDomain = true) {
    const stack = [[root, null]];
    while (stack.length > 0) {
      const [node, parentKey] = stack.pop();
      if (Array.isArray(node)) {
        const elemKey = parentKey === "receipts" ? "receipts[]" : null;
        for (let i = node.length - 1; i >= 0; i--) stack.push([node[i], elemKey]);
        continue;
      }
      if (!object(node)) continue;
      const cutShape = isCutShape(node);
      const cutKey = parentKey !== null && (parentKey === "cut" || parentKey.endsWith("_cut"));
      if (cutShape || cutKey) {
        need(cutShape, "内嵌 cut 字段不完整或多余");
        const rdomain = node.domain_id;
        need(typeof rdomain === "string" && (!requireKnownDomain || knownDomains.includes(rdomain)), "回执所属域不在固定切面向量中");
        cut(node, rdomain);
        if (Object.prototype.hasOwnProperty.call(cuts, rdomain) && cuts[rdomain] !== null) {
          const rseq = BigInt(node.commit_seq), cseq = BigInt(cuts[rdomain].commit_seq);
          need(rseq <= cseq, "MissingDependency：回执(" + rdomain + ":" + node.commit_seq + ")晚于固定切面(" + rdomain + ":" + cuts[rdomain].commit_seq + ")，向量未就绪");
          if (rseq === cseq) need(same(node, cuts[rdomain]), "同序号回执根与固定切面根不符");
        }
      }
      if (["receipt", "e_receipt", "resolve_receipt", "receipts[]"].includes(parentKey)) {
        need(isCutShape(node.cut), "回执缺失合法 cut");
      }
      if (typeof node.domain_id === "string" && isCutShape(node.cut)) {
        need(node.domain_id === node.cut.domain_id, "回执域与 cut 域不符");
      }
      const ks = Object.keys(node).sort();
      for (let i = ks.length - 1; i >= 0; i--) stack.push([node[ks[i]], ks[i]]);
    }
  }
  async function utf8Sha256(text) {
    return bytesHash(new TextEncoder().encode(text));
  }
  function checkReadError(reply, rev) {
    if (object(reply) && reply.kind === "EconomicReadError") {
      keys(reply, ["schema_revision", "kind", "code", "detail", "transfer_id"], "分页错误");
      need(reply.schema_revision === rev && typeof reply.code === "string" && reply.code.length > 0
        && typeof reply.detail === "string" && reply.detail.length > 0, "分页错误格式非法");
      throw new Error(reply.detail.startsWith(reply.code) ? reply.detail : reply.code + "：" + reply.detail);
    }
  }
  async function verifyProjectedBook(book, domain, discovery) {
    if (domain === "E") { need(book === null, "E 不能伪装重账"); return; }
    if (book === null) return;
    need(object(book) && domain === "B:" + book.chong_id, "重归属与权威域不同");
    need(book.book_revision === discovery.book_revision, "投影书账版本与冻结域不同");
    integer(book.fixed_q, true); integer(book.operation_level);
    integer(book.actual_quantity, false, true); integer(book.opening_quantity, false, true);
    keys(book.income_book, ["Pi", "A", "W", "R"], "利润账");
    for (const amount of Object.values(book.income_book)) integer(amount, false, true);
    if (book.book_revision === "tb03c-book/1") {
      need(object(book.cost_totals), "tb03c 成本汇总缺失");
      integer(book.cost_totals.acquisition_cash, false, true);
      integer(book.cost_totals.commission, false, true);
      integer(book.cost_totals.fee_only, false, true);
      need(object(book.cost_basis), "tb03c 成本基数缺失");
      integer(book.cost_basis.K, false, true);
      need(object(book.cost_remaining) && object(book.principal) && object(book.phase), "tb03c 余量/本金/阶段缺失");
      if (book.cost_remaining.status === "Known") integer(book.cost_remaining.value, false, true);
    }
  }
  async function verifyProjection(value, discovery) {
    need(object(discovery.read_projection), "会话未声明只读投影能力");
    keys(value, ["kind", "projection_revision", "session_id", "session_generation", "manifest_hash",
      "mode", "as_known_ns", "domains", "projection_completeness", "projection_token"], "经济投影");
    need(value.kind === "EconomicProjection" && value.projection_revision === PROJECTION_REV
      && value.session_id === discovery.session_id && value.session_generation === discovery.session_generation
      && value.manifest_hash === discovery.manifest_hash, "经济投影身份或版本不符");
    need(value.mode === "Current" || value.mode === "AsKnown", "未知投影历史模式");
    if (value.as_known_ns !== null) integer(value.as_known_ns);
    keys(value.domains, discovery.domains, "投影域集合");
    let complete = true;
    for (const domain of discovery.domains) {
      const view = value.domains[domain];
      if (view.status === "Unavailable") {
        keys(view, ["status", "error"], "不可用投影域");
        need(typeof view.error === "string" && view.error.length > 0, "投影域不可用原因缺失");
        complete = false;
        continue;
      }
      keys(view, ["status", "projection_revision", "cut", "commit_ns", "writer_epoch", "audit_verified",
        "authoritative_image_hash", "authoritative_image_bytes", "projection_hash", "projection_bytes",
        "omitted_peer_images", "projection"], "可用投影域");
      need(view.status === "Available" && view.projection_revision === PROJECTION_REV
        && view.audit_verified === true
        && view.writer_epoch === discovery.read_projection.owner_epochs[domain], "投影域状态、审计确认或 epoch 不符");
      cut(view.cut, domain);
      integer(view.commit_ns);
      if (value.as_known_ns !== null) need(BigInt(view.commit_ns) <= BigInt(value.as_known_ns), "投影晚于获知截止时刻");
      digest(view.authoritative_image_hash, "权威原像摘要");
      integer(view.authoritative_image_bytes, true);
      digest(view.projection_hash, "投影摘要");
      const projBytes = new TextEncoder().encode(canonical(view.projection));
      need(await bytesHash(projBytes) === view.projection_hash
        && String(projBytes.byteLength) === view.projection_bytes, "投影正文摘要或字节长度不符");
      need(Array.isArray(view.omitted_peer_images), "省略证明锚点列表缺失");
      for (const om of view.omitted_peer_images) {
        keys(om, ["path", "omitted_kind", "sha256", "byte_len"], "省略证明锚点");
        need(typeof om.path === "string" && om.path.length > 0 && om.omitted_kind === "EmbeddedPeerImage", "省略锚点类型非法");
        digest(om.sha256, "省略锚点摘要"); integer(om.byte_len, true);
      }
      const proj = view.projection;
      need(object(proj), "投影正文非对象");
      for (const k of ["recorded", "pending", "applied", "unmatched", "history"]) need(Array.isArray(proj[k]), "投影记录族非数组");
      for (const rec of proj.recorded) {
        need(object(rec) && typeof rec.raw_utf8 === "string", "投影事实缺少原件字节");
        digest(rec.raw_sha256, "raw_sha256");
        need(await utf8Sha256(rec.raw_utf8) === rec.raw_sha256, "投影事实 raw_utf8 与 raw_sha256 不符");
      }
      if (proj.finance !== undefined) {
        need(object(proj.finance) && proj.finance.schema_revision === discovery.finance_revision, "投影财务版本不符");
      }
      await verifyProjectedBook(proj.book, domain, discovery);
    }
    need(value.projection_completeness === (complete ? "CompleteProjectionVector" : "PartialProjectionVector"), "投影完整性声明与域状态不符");
    const vectorCuts = Object.fromEntries(
      discovery.domains.map(d => [d, value.domains[d].status === "Available" ? value.domains[d].cut : null])
    );
    verifyEmbeddedCutsAgainstVector(value, vectorCuts, discovery.domains);
    const body = {...value}; delete body.projection_token;
    need(value.projection_token === "economic-projection-" + await sha256(body), "投影固定向量 token 与正文不符");
    return value;
  }
  async function verifyProjectionOriginal(reply, state, discovery, domain, kind, id) {
    need(state && state.kind === "EconomicProjection" && state.projection_completeness === "CompleteProjectionVector", "同切面取证需要完整投影向量");
    keys(reply, ["kind", "projection_revision", "session_id", "session_generation", "manifest_hash",
      "cuts", "domain_id", "original_kind", "object_id", "authoritative_image_hash",
      "authoritative_image_bytes", "commit_ns", "writer_epoch", "original"], "同切面投影原件");
    const cuts = Object.fromEntries(Object.entries(state.domains).map(([d, v]) => [d, v.cut]));
    const view = state.domains[domain];
    need(reply.kind === "EconomicProjectionOriginal" && reply.projection_revision === PROJECTION_REV
      && reply.session_id === state.session_id && reply.session_generation === state.session_generation
      && reply.manifest_hash === state.manifest_hash && reply.domain_id === domain
      && reply.original_kind === kind && reply.object_id === id && same(reply.cuts, cuts)
      && reply.authoritative_image_hash === view.authoritative_image_hash
      && reply.authoritative_image_bytes === view.authoritative_image_bytes
      && reply.commit_ns === view.commit_ns && reply.writer_epoch === view.writer_epoch, "同切面原件与固定投影切面不符");
    const o = reply.original;
    need(object(o), "同切面原件载荷非对象");
    verifyEmbeddedCutsAgainstVector(reply, cuts, discovery.domains);
    const checkFact = async (f) => {
      need(object(f) && typeof f.raw_utf8 === "string", "事实原件缺 raw_utf8");
      digest(f.raw_sha256, "raw_sha256");
      need(await utf8Sha256(f.raw_utf8) === f.raw_sha256, "事实原件精确字节与 raw_sha256 不符");
      need(object(f.raw_exact_text) && f.raw_exact_text.representation === "ExactDecimalIntegerTextProjection"
        && f.raw_exact_text.raw_sha256 === f.raw_sha256, "事实精确文本视图绑定不符");
      need(Array.isArray(f.receipts), "事实回执缺失");
    };
    if (kind === "fact") await checkFact(o);
    else if (kind === "allocation") {
      const rec = domain === "E" ? o.resolve_receipt : o.receipt;
      need(object(rec), "分配回执缺失");
      if (o.fact !== null && o.fact !== undefined) {
        await checkFact(o.fact);
      } else {
        need(object(o.fact_ref), "未连带事实时缺具名 fact_ref");
        digest(o.fact_ref.fact_key, "fact_ref.fact_key");
        digest(o.fact_ref.fact_hash, "fact_ref.fact_hash");
      }
    } else if (kind === "model") {
      need(object(o.model_ref), "模型原件缺 model_ref");
      digest(o.model_ref.content_hash, "model_ref.content_hash");
      if (o.model_raw_utf8 !== null) {
        need(typeof o.model_raw_utf8 === "string"
          && await utf8Sha256(o.model_raw_utf8) === o.model_ref.content_hash, "模型原件字节与 model_ref.content_hash 不符");
        need(object(o.model_exact_text) && o.model_exact_text.representation === "ExactDecimalIntegerTextProjection"
          && o.model_exact_text.content_hash === o.model_ref.content_hash, "模型精确文本视图绑定不符");
      }
    } else if (["decision", "grant", "command"].includes(kind)) {
      const recs = kind === "grant" ? [o.receipt] : (o.receipts || []);
      for (const r of recs) {
        need(object(r), "财务回执非对象");
      }
    }
    return reply;
  }
  class Client {
    constructor({fetcher = globalThis.fetch.bind(globalThis), onCommit = () => {}} = {}) {
      this.fetcher = fetcher; this.onCommit = onCommit; this.discovery = null; this.state = null; this.epoch = 0; this.readLog = [];
    }
    async fetchBounded(path, options, timeout, limit) {
      const control = new AbortController(), timer = setTimeout(() => control.abort(), timeout); // DevSkim: ignore DS172411 回调为函数字面量而非字符串
      try {
        const response = await this.fetcher(path, {...options, signal: control.signal});
        need(response.ok, "公开查询失败：HTTP " + response.status);
        const reader = response.body.getReader(), decoder = new TextDecoder("utf-8", {fatal: true});
        let size = 0, raw = "";
        try {
          while (true) {
            const {done, value} = await reader.read(); if (done) break;
            size += value.byteLength; need(size <= limit, "完整回复超过事前上限"); raw += decoder.decode(value, {stream: true});
          }
          raw += decoder.decode(); return parse(raw);
        } catch (error) { await reader.cancel(); throw error; }
      } finally { clearTimeout(timer); }
    }
    async discover() {
      if (this.discovery) return this.discovery;
      const d = await this.fetchBounded("/api/economic/ready", {}, 10000, 65536);
      need(d.schema_revision === "economic-discovery/1" && d.configured === true && d.scope === "TestOnlyRecordedEconomics", "经济查询配置未确认");
      need(typeof d.session_id === "string" && d.session_id.length > 0 && /^[0-9a-f]{64}$/.test(d.manifest_hash), "会话与配置摘要缺失");
      integer(d.session_generation, true); integer(d.producer_epoch, true);
      need(Array.isArray(d.domains) && d.domains.length > 0 && new Set(d.domains).size === d.domains.length &&
        d.domains.every(v => typeof v === "string" && (v === "E" || /^B:.+/.test(v))), "域目录无效");
      revision(d);
      integer(d.max_reply_bytes, true); integer(d.operation_timeout_ms, true);
      need(BigInt(d.max_reply_bytes) <= 67108864n && BigInt(d.operation_timeout_ms) <= 60000n, "公开配置超过浏览器资源界限");
      if(d.read_pages!==undefined){
        keys(d.read_pages,["schema_revision","owner_epochs"],"分页能力");
        need(exactRelease(d.finance_revision) && d.read_pages.schema_revision==="economic-read-pages/1","未知分页合同");
        keys(d.read_pages.owner_epochs,d.domains,"分页 owner 代际");
        Object.values(d.read_pages.owner_epochs).forEach(n=>integer(n,true));
      }
      if(d.read_projection!==undefined){
        keys(d.read_projection,["schema_revision","transport_revision","owner_epochs","original_kinds","watch_supported","available_actions"],"经济投影能力");
        need(d.finance_revision==="tb03b-finance/6" && d.read_projection.schema_revision===PROJECTION_REV
          && d.read_projection.transport_revision==="economic-read-pages/1"
          && d.read_projection.watch_supported===false
          && same(d.read_projection.available_actions,["projection","projection_original"]),"未知经济投影合同");
        keys(d.read_projection.owner_epochs,d.domains,"投影 owner 代际");
        Object.values(d.read_projection.owner_epochs).forEach(n=>integer(n,true));
        need(Array.isArray(d.read_projection.original_kinds)
          && d.read_projection.original_kinds.every(k=>PROJECTION_ORIG_KINDS.includes(k)),"投影原件类型非法");
      }
      this.discovery = d; return d;
    }
    async query(payload, deadline = null) {
      const d = await this.discover();
      if(d.read_pages && ["snapshot","watch","projection","projection_original"].includes(payload.op)){
        const end = performance.now()+Math.min(30000,Number(d.operation_timeout_ms));
        return this.pagedQuery(payload,Math.min(deadline??end,end));
      }
      return this.rpc(payload,payload.op,deadline);
    }
    async pagedQuery(query, deadline) {
      const d=this.discovery, rev=d.read_pages.schema_revision;
      const expectedKindMap={snapshot:"EconomicSnapshot",watch:"EconomicWatch",projection:"EconomicProjection",projection_original:"EconomicProjectionOriginal"};
      const expectedKind=expectedKindMap[query.op];
      need(typeof expectedKind==="string","未知分页查询类型");
      const remaining=()=>{const ms=Math.floor(deadline-performance.now());need(ms>0,"完整分页查询超时");return String(ms);};
      const call=(op,body)=>this.rpc({op,schema_revision:rev,...body},"read",deadline);
      const opened=await call("EconomicReadOpen",{query,requested_remaining_ms:remaining()});
      checkReadError(opened, rev);
      keys(opened,["schema_revision","kind","descriptor","descriptor_sha256"],"分页 Open");
      const h=opened.descriptor, binding={transfer_id:h.transfer_id,descriptor_sha256:opened.descriptor_sha256};
      need(opened.schema_revision===rev && opened.kind==="EconomicReadOpened" && /^[0-9a-f]{32}$/.test(h.transfer_id)
        && opened.descriptor_sha256===await sha256(h),"分页描述符摘要或传输身份不同");
      const close=async()=>{
        const closed=await call("EconomicReadClose",binding);
        checkReadError(closed, rev);
        need(same(closed,{schema_revision:rev,kind:"EconomicReadClosed",...binding}),"分页关闭未确认");
      };
      let doc;
      try {
        keys(h,["schema_revision","transfer_id","session_id","session_generation","manifest_hash","producer_id","producer_epoch",
          "query_sha256","document_kind","fixed_cuts","owner_epochs","document_bytes","document_sha256","chunk_bytes","page_count"],"分页描述符");
        need(h.schema_revision===rev && h.session_id===d.session_id && h.session_generation===d.session_generation
          && h.manifest_hash===d.manifest_hash && h.producer_id==="Q:"+d.session_id && h.producer_epoch===d.producer_epoch
          && same(h.owner_epochs,d.read_pages.owner_epochs) && h.query_sha256===await sha256(query)
          && h.document_kind===expectedKind,"分页描述符不属于本次查询");
        const size=Number(integer(h.document_bytes,true)),chunk=262144;
        need(size<=4194304 && h.chunk_bytes===String(chunk) && h.page_count===String(Math.ceil(size/chunk)),"分页容量或页数错误");
        const bytes=new Uint8Array(size);
        for(let i=0;i<size;i+=chunk){
          const page=await call("EconomicReadPage",{...binding,offset:String(i),requested_remaining_ms:remaining()});
          checkReadError(page, rev);
          const n=Math.min(chunk,size-i),done=i+n===size;
          keys(page,["schema_revision","kind","transfer_id","descriptor_sha256","offset","raw_byte_count","chunk_sha256","data_base64","next_offset","done"],"分页数据");
          need(page.schema_revision===rev && page.kind==="EconomicReadPage" && page.transfer_id===binding.transfer_id
            && page.descriptor_sha256===binding.descriptor_sha256 && page.offset===String(i) && page.raw_byte_count===String(n)
            && page.done===done && page.next_offset===(done?null:String(i+n)) && page.data_base64.length===4*Math.ceil(n/3),"分页边界或身份不同");
          const raw=atob(page.data_base64);
          need(raw.length===n && btoa(raw)===page.data_base64,"分页不是规范 base64");
          for(let j=0;j<n;j++)bytes[i+j]=raw.charCodeAt(j);
          need(await bytesHash(bytes.subarray(i,i+n))===page.chunk_sha256,"分页摘要不同");
        }
        need(await bytesHash(bytes)===h.document_sha256,"分页正文摘要不同");
        const raw=new TextDecoder("utf-8",{fatal:true}).decode(bytes); doc=parse(raw);
        need(canonical(doc)===raw && doc.kind===h.document_kind && doc.manifest_hash===h.manifest_hash
          && doc.session_id===h.session_id && doc.session_generation===h.session_generation,"分页正文身份或编码不同");
        if(query.op==="projection_original"){
          keys(doc.cuts,d.domains,"同切面原件固定切面");
          need(same(doc.cuts,h.fixed_cuts),"同切面原件切面与描述符不同");
        } else {
          keys(doc.domains,d.domains,"分页文档域");
          const fixed=Object.fromEntries(Object.entries(doc.domains).map(([id,v])=>[id,v.status==="Available"?
            (["snapshot","projection"].includes(query.op)?v.cut:v.next_cut):null]));
          need(same(fixed,h.fixed_cuts),"分页文档切面与描述符不同");
        }
        this.readLog.push({op:query.op,document_kind:h.document_kind,document_bytes:size,page_count:Number(h.page_count),document_sha256:h.document_sha256,fixed_cuts:h.fixed_cuts});
      } catch (error) {
        try { await close(); } catch { /* 保留首个错误；Q 会按原期限回收传输。 */ }
        throw error;
      }
      await close();
      return doc;
    }
    async rpc(payload, route, deadline) {
      const d=this.discovery;
      const request = {schema_revision: revision(d), session_id: d.session_id, session_generation: d.session_generation,
        source_namespace: "economic-browser", source_epoch: "1", message_id: "browser-" + globalThis.crypto.randomUUID(),
        producer_id: "economic-browser", producer_epoch: "1", payload_hash: await sha256(payload), causal_refs: [], payload};
      const timeout = deadline === null ? Number(d.operation_timeout_ms) + 1000 : Math.min(Number(d.operation_timeout_ms) + 1000, deadline - performance.now());
      need(timeout > 0, "整次追读超过事前时限，保留原切面");
      const response = await this.fetchBounded("/api/economic/" + route,
        {method: "POST", headers: {"Content-Type": "application/json"}, body: canonical(request)},
        timeout, route==="read"?Math.min(1048576,Number(d.max_reply_bytes)):Number(d.max_reply_bytes));
      keys(response, Object.keys(request), "公共回复");
      need(response.schema_revision === request.schema_revision && response.session_id === d.session_id &&
        response.session_generation === d.session_generation && response.producer_id === "Q:" + d.session_id &&
        response.producer_epoch === d.producer_epoch && response.source_epoch === d.producer_epoch &&
        response.source_namespace === "economic-observe/replies", "公开回复身份不符");
      const ph = await sha256(response.payload);
      const cause = Object.fromEntries(["source_namespace", "source_epoch", "message_id", "payload_hash"].map(k => [k, request[k]]));
      need(response.payload_hash === ph && same(response.causal_refs, [cause]) && response.message_id === "reply-" +
        await sha256([request.source_namespace, request.source_epoch, request.message_id, ph]), "回复内容或原因果摘要不符");
      need(!response.payload.error && response.payload.ok !== false, response.payload.detail || response.payload.error || "查询失败");
      if (deadline !== null) need(performance.now() < deadline, "整次追读超过事前时限，保留原切面");
      return response.payload;
    }
    async load({cuts = null, asKnown = null, token = null} = {}) {
      const epoch = ++this.epoch;
      const result = await this.query({op: "snapshot", cuts, as_known_ns: asKnown, snapshot_token: token});
      need(result.kind !== "Gap", "固定切面已过期，请重新读取当前向量");
      await verifySnapshot(result, this.discovery);
      if (token !== null) need(result.snapshot_token === token, "返回了另一个固定 token");
      else {
        need(result.mode === (cuts !== null || asKnown !== null ? "AsKnown" : "Current") &&
          result.as_known_ns === asKnown, "历史模式或获知时刻与原请求不同");
      }
      if (cuts !== null) for (const [domain, expected] of Object.entries(cuts)) {
        const view = result.domains[domain];
        if (view.status === "Available") need(same(view.cut, expected), "回看返回其他切面");
      }
      if (epoch === this.epoch) { this.state = result; this.onCommit(result); }
      return result;
    }
    async loadProjection({cuts = null, asKnown = null, token = null} = {}) {
      const d = await this.discover();
      need(object(d.read_projection), "会话未声明 economic-read-projection/1");
      const epoch = ++this.epoch;
      const result = await this.query({
        op: "projection",
        projection_revision: PROJECTION_REV,
        cuts,
        as_known_ns: asKnown,
        projection_token: token,
      });
      need(result.kind !== "Gap", "固定投影切面已过期，请重新读取当前投影向量");
      await verifyProjection(result, this.discovery);
      if (token !== null) need(result.projection_token === token, "返回了另一个投影固定 token");
      else {
        need(result.mode === (cuts !== null || asKnown !== null ? "AsKnown" : "Current") &&
          result.as_known_ns === asKnown, "投影历史模式或获知时刻与原请求不同");
      }
      if (cuts !== null) for (const [domain, expected] of Object.entries(cuts)) {
        const view = result.domains[domain];
        if (view.status === "Available") need(same(view.cut, expected), "投影回看返回其他切面");
      }
      if (epoch === this.epoch) { this.state = result; this.onCommit(result); }
      return result;
    }
    async projectionOriginal(state, domain, kind, id) {
      const cuts = Object.fromEntries(Object.entries(state.domains).map(([d, v]) => [d, v.cut]));
      const result = await this.query({
        op: "projection_original",
        projection_revision: PROJECTION_REV,
        domain_id: domain,
        kind,
        object_id: id,
        cuts,
      });
      return verifyProjectionOriginal(result, state, this.discovery, domain, kind, id);
    }
    async original(state, domain, kind, id) {
      if (state && state.kind === "EconomicProjection") {
        return this.projectionOriginal(state, domain, kind, id);
      }
      const cuts=Object.fromEntries(Object.entries(state.domains).map(([d,v])=>[d,v.cut]));
      const result=await this.query({op:"original",kind,domain_id:domain,object_id:id,cuts});
      return verifyOriginal(result,state,this.discovery,domain,kind,id);
    }
    async watch() {
      need(this.state !== null && this.state.kind === "EconomicSnapshot" && this.state.completeness === "CompleteVector",
        this.state && this.state.kind === "EconomicProjection"
          ? "只读投影视图不支持旧 Watch，请先切换到完整快照并取得 CompleteVector"
          : "需先取得完整向量才可续接");
      const epoch = ++this.epoch, before = this.state;
      const deadline = performance.now() + Number(this.discovery.operation_timeout_ms);
      const cuts = Object.fromEntries(Object.entries(before.domains).map(([d, v]) => [d, v.cut]));
      const changes = await this.query({op: "watch", cuts}, deadline);
      need(changes.kind === "EconomicWatch" && changes.session_id === before.session_id &&
        changes.session_generation === before.session_generation && changes.manifest_hash === before.manifest_hash, "变化身份不符");
      keys(changes.domains, this.discovery.domains, "变化域集合");
      const next = {};
      for (const [domain, result] of Object.entries(changes.domains)) {
        need(result.status === "Available", result.error || "变化域不可用，保留原切面");
        need(same(result.base_cut, cuts[domain]) && Array.isArray(result.changes), "变化起点不符");
        let previous = cuts[domain], previousNs = BigInt(before.domains[domain].commit_ns);
        for (const batch of result.changes) {
          keys(batch, ["cut", "image", "image_hash", "commit_ns"], "完整经济变化");
          cut(batch.cut, domain);
          integer(batch.commit_ns);
          need(BigInt(batch.commit_ns) >= previousNs && await sha256(batch.image) === batch.image_hash,
            "变化时间倒退或图像摘要不同");
          need(BigInt(batch.cut.commit_seq) === BigInt(previous.commit_seq) + 1n, "变化序号不连续");
          const one = {...cuts, [domain]: batch.cut};
          const fixed = await this.query({op: "snapshot", cuts: one, as_known_ns: null, snapshot_token: null}, deadline);
          await verifySnapshot(fixed, this.discovery);
          need(fixed.mode === "AsKnown" && fixed.as_known_ns === null, "逐批复核未返回指定历史模式");
          const view = fixed.domains[domain];
          need(view.status === "Available" && same(view.cut, batch.cut) && same(view.image, batch.image) &&
            view.image_hash === batch.image_hash && view.commit_ns === batch.commit_ns, "中间变化与同切面图像/时间不同");
          previous = batch.cut; previousNs = BigInt(batch.commit_ns);
        }
        need(same(previous, result.next_cut), "变化末尾与前沿不同"); next[domain] = result.next_cut;
      }
      const snapshot = await this.query({op: "snapshot", cuts: next, as_known_ns: null, snapshot_token: null}, deadline);
      await verifySnapshot(snapshot, this.discovery);
      need(snapshot.mode === "AsKnown" && snapshot.as_known_ns === null, "续接末尾历史模式不同");
      need(snapshot.completeness === "CompleteVector", "续接复核时存在不可用域");
      for (const domain of this.discovery.domains) {
        const batches = changes.domains[domain].changes;
        const expected = batches.length ? batches[batches.length - 1].image : before.domains[domain].image;
        const expectedNs = batches.length ? batches[batches.length - 1].commit_ns : before.domains[domain].commit_ns;
        need(same(snapshot.domains[domain].cut, next[domain]) && same(snapshot.domains[domain].image, expected) &&
          snapshot.domains[domain].commit_ns === expectedNs, "完整变化与同切面快照或提交时间不同");
      }
      need(performance.now() < deadline, "整次追读超过事前时限，保留原切面");
      if (epoch === this.epoch) { this.state = snapshot; this.onCommit(snapshot); }
      return snapshot;
    }
  }
  return Object.freeze({Client, verifySnapshot, verifyOriginal, verifyProjection, verifyProjectionOriginal, canonical, parse, sha256});
});
