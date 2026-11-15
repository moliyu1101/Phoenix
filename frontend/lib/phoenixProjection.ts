import {roleLabels,workerDisplayName} from "./phoenix-labels";
import { emptyDeck } from "./run-events/state";
import type { DeckState } from "./run-events/types";
import { parse, isActive, canResume, label } from "./phoenix-state";
/** View projection only: Phoenix owns all runtime state, not the old Phoenix daemon. */
export function projectPhoenix(detail: any, swarm: any, challenge: any): DeckState {
 const run = detail.run, deck = emptyDeck(run.id);
 deck.challengeName = challenge?.title || run.id; deck.category = challenge?.category || "misc";
 deck.target = (challenge?.targets || []).join(", "); deck.mode = "ctf"; deck.started = true;
 deck.taskContract = {rawInstruction:challenge?.description || "",mode:"ctf",title:deck.challengeName,
  category:deck.category,attachments:(challenge?.files || []).map((f:any)=>({path:f.path,name:f.path,size:f.size,summary:""})),
  executionTarget:deck.target,authorizationScope:deck.target || "本地题目附件",completion:{kind:"ctf_flag",
   goal:`解决 ${deck.challengeName} 并验证答案`,taskType:deck.category,flagFormat:"brace",flagFormatHint:"默认花括号格式",
   expectedFlags:1,multiFlag:false,findingClass:"",outcomePredicate:"",collectUntilCoverage:false}};
 deck.startedAt = run.created; deck.finished = !isActive(run.state) && !canResume(run.state); deck.solved = run.state === "solved";
 deck.finishedAt = deck.finished ? run.updated : undefined; deck.usd = run.billed_usd;
 const assignments = new Map<string, string>((swarm?.tasks || []).map((t: any) => [t.id, t.worker_id]));
 const tasks = swarm?.tasks || detail.tasks || [];
 for (const w of swarm?.workers || []) {
  const activeTask = tasks.find((t: any) => w.active_task_ids.includes(t.id));
  const profile = Object.values(w.profiles)[0] as any;
  deck.lanes[w.id] = { solverId: w.id, engine: "phoenix", reasoning: "", toolLines: [],
   status: w.status === "working" ? "thinking" : w.status === "finished" ? "finished" : "idle", solved: false,
   online: w.enabled && !deck.finished, role: w.roles.includes("reviewer") ? "review" : "worker",
   phase: roleLabels(w.roles), statusReason: label(w.status), model: profile?.model,
   profileId: w.profile || w.id, profileLabel: workerDisplayName(w.name), intentId: activeTask?.key,
   tokensSpent: w.usage.input_tokens + w.usage.output_tokens, firstSeenAt: run.created };
  deck.costBySolver[w.id] = { usd: w.usage.priced_cost_usd || 0, tokensIn: w.usage.input_tokens,
   tokensOut: w.usage.output_tokens, unpricedCalls: w.usage.unpriced_calls, engine: "phoenix" };
 }
 const calls = detail.model_calls || [];
 deck.tokensIn = calls.reduce((n: number,c: any) => n + (c.input_tokens || 0), 0);
 deck.tokensOut = calls.reduce((n: number,c: any) => n + (c.output_tokens || 0), 0);
 deck.blackboard.intents = tasks.map((t: any) => ({ id: t.key, goal: t.goal, summary: t.summary,
  workerClass: t.role, fromFacts: [], dependsOn: t.dependencies, priority: t.priority,
  status: t.state === "running" ? "claimed" : t.state === "pending" ? "open" : "done",
  closeReason: t.state === "done" ? undefined : t.state, worker: t.worker_id || assignments.get(t.id),
  proposedBy: "coordinator", proposedTs: run.created, claimedTs: t.started || undefined, concludedTs: t.ended || undefined,
 }));
 deck.blackboard.facts = (detail.facts || []).map((f: any, index: number) => ({ factSeq: index + 1,
  fact: f.statement, verified: false, confidence: 0, actor: assignments.get(f.task_id) || "coordinator", verifier: "",
  intentId: tasks.find((t: any) => t.id === f.task_id)?.key, ts: f.created,
  provenance: { artifactRefs: parse<any[]>(f.citations, []).map((q: any) => ({artifactId:q.evidence_id})), workerId: assignments.get(f.task_id) },
 }));
 deck.blackboard.deadEnds = (detail.facts || []).filter((f: any) => f.stance === "disproven").map((f: any) => ({ reason:f.statement, actor:assignments.get(f.task_id) || "coordinator", ts:f.created }));
 // Phoenix cited claims are unverified observations in Phoenix's CTF canvas.
 // Do not promote them to verified Facts merely to make them visible.
 deck.blackboard.observations = deck.blackboard.facts.map((f, index) => ({
  observationSeq: index + 1, text: f.fact, actor: f.actor, intentId: f.intentId,
  confidence: 0, admitted: false, claimedVerified: false, ts: f.ts,
  artifactId: f.provenance?.artifactRefs?.[0]?.artifactId, provenance: f.provenance,
 }));
 // A dependency is not proof of an evidence read. Handoff edges require a
 // successful native evidence_read record joining producer and consumer.
 for (const intent of deck.blackboard.intents) {
  const task = tasks.find((t:any) => t.key === intent.id);
  const reads = (detail.evidence_handoffs || []).filter((r:any) => r.target_task_id === task?.id);
  intent.fromFacts = deck.blackboard.facts.filter(f => reads.some((r:any) =>
   f.provenance?.artifactRefs?.some(q => q.artifactId === r.evidence_id))).map(f => f.factSeq!);
 }
 deck.flags = (detail.candidates || []).filter((c: any) => c.status === "accepted").map((c: any) => c.value);
 deck.flag = deck.flags[0]; deck.blackboard.flags = deck.flags;
 const events = [...(detail.events || [])].sort((a,b) => a.seq-b.seq);
 const actor = (e: any) => e.worker_id || parse(e.payload).worker_id || (e.task_id ? assignments.get(e.task_id) : undefined);
 deck.chat = events.map((e: any) => { const p = parse(e.payload); return {
  id: String(e.seq), solverId: actor(e), role: e.kind === "operator.message" ? "human" : actor(e) ? "agent" : "system",
  kind: e.kind.startsWith("tool.") || e.kind === "evidence.created" ? "tool" : "text",
  content: p.content || p.rationale || p.summary || p.statement || p.reason || e.kind + "\n" + JSON.stringify(p), ts: e.created,
 }; });
 deck.runtimeEvents = events.map((e:any) => ({id:String(e.seq),solverId:actor(e)||"coordinator",eventType:e.kind,
  nativeType:e.kind,adapter:"phoenix",payload:parse(e.payload),ts:e.created}));
 deck.blackboard.events = events.map((e:any) => ({id:String(e.seq),kind:e.kind,actor:actor(e)||"coordinator",
  ts:e.created,label:parse(e.payload).summary || parse(e.payload).statement || parse(e.payload).reason || e.kind}));
 return deck;
}
