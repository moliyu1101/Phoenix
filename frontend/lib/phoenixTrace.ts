import {uiLabel,roleLabels,workerDisplayName} from "./phoenix-labels";
import { finalizeScenario, type TraceSpanSpec, type TraceEventSpec } from "../components/activity-timeline/traceModel";
import { parse, isActive } from "./phoenix-state";

/** Phoenix records -> Phoenix's original waterfall. Missing boundaries stay unknown. */
export function phoenixTrace(detail: any, swarm: any, challenge: any, recorded: any[]) {
  const run = detail.run, origin = run.created * 1000, live = isActive(run.state);
  const at = (ts: number) => Math.max(0, ts * 1000 - origin);
  const end = live ? undefined : at(run.updated);
  const events = [...recorded].sort((a,b) => a.seq-b.seq);
  const tasks = swarm?.tasks || detail.tasks || [];
  const spans: TraceSpanSpec[] = [{id:"coordinator",parentId:null,name:"协调器",kind:"agent",start:0,end,
    failed:run.state === "failed",error:run.state === "failed" ? run.reason : undefined,detail:uiLabel(run.state)}];
  const ledger: TraceEventSpec[] = [];
  spans.push({id:"input",parentId:"coordinator",name:"用户输入",kind:"group",start:0,end:0,point:true});
  spans.push({id:"system",parentId:"coordinator",name:"运行事件",kind:"group",start:0,end});
  ledger.push({id:"challenge",spanId:"input",ts:0,kind:"input",text:challenge?.description || run.id});
  const owners = new Map<string,string>(tasks.map((t:any) => [t.id,t.worker_id]));
  const workerIds = new Set<string>();
  for (const worker of swarm?.workers || []) {
    const mine = tasks.filter((t:any) => t.worker_id === worker.id && t.started != null);
    if (!mine.length) continue; // A registered, never-started worker is not an executed span.
    workerIds.add(worker.id);
    const started = Math.min(...mine.map((t:any)=>t.started));
    const complete = mine.every((t:any)=>t.ended != null);
    spans.push({id:`worker:${worker.id}`,parentId:"coordinator",name:workerDisplayName(worker.name),kind:"worker",start:at(started),
      end:complete ? at(Math.max(...mine.map((t:any)=>t.ended))) : end,
      detail:`${worker.id} · ${roleLabels(worker.roles)}`,engine:"phoenix",
      failed:mine.some((t:any)=>t.state === "failed"),cancelled:mine.some((t:any)=>t.state === "interrupted")});
    for(const task of mine) spans.push({id:`task:${task.id}`,parentId:`worker:${worker.id}`,name:task.key,kind:"group",
      detail:task.goal,start:at(task.started),end:task.ended != null ? at(task.ended) : end,
      unknown:!live && task.ended == null,failed:task.state === "failed",output:task.summary});
  }
  const parent = (taskId?: string, worker?: string) => {
    if(taskId && spans.some(s=>s.id === `task:${taskId}`))return `task:${taskId}`;
    const owner=worker || (taskId ? owners.get(taskId) : undefined);
    return owner && workerIds.has(owner) ? `worker:${owner}` : "system";
  };
  for(const call of detail.model_calls || []) {
    if(call.created == null)continue;
    spans.push({id:`model:${call.id}`,parentId:parent(call.task_id,call.worker_id),name:`${uiLabel(call.role)} · 模型调用`,kind:"llm",
      start:at(call.created),end:call.ended != null ? at(call.ended) : end,unknown:call.status === "uncertain",
      tokensIn:call.input_tokens ?? undefined,tokensOut:call.output_tokens ?? undefined,cost:call.cost_usd ?? undefined,
      detail:uiLabel(call.status)});
  }
  for(const event of events) {
    const p=parse(event.payload), spanId=parent(event.task_id,event.worker_id || p.worker_id);
    if(event.kind === "tool.started") {
      const finished=events.find(e=>e.seq>event.seq && e.task_id===event.task_id && e.kind==="tool.completed" && parse(e.payload).call_id===p.call_id);
      const result=finished ? parse(finished.payload) : null;
      spans.push({id:`tool:${event.seq}`,parentId:spanId,name:uiLabel(p.tool),kind:"tool",
        tool:/read/.test(p.tool)?"read":/write/.test(p.tool)?"edit":/search/.test(p.tool)?"search":/http|tcp/.test(p.tool)?"web":"shell",
        start:at(event.created),end:finished ? at(finished.created) : live ? undefined : at(event.created),
        point:!finished && !live,unknown:!finished && !live,failed:result?.ok===false,
        detail:finished ? result.evidence_id || "已执行" : "未记录工具结束边界",output:result ? JSON.stringify(result,null,2) : undefined});
    }
    const title = ["run.state","flag.verified","flag.operator_receipt"].includes(event.kind) ? uiLabel(p.state||p.status) : p.content || p.rationale || p.summary || p.statement || p.reason ||
      (p.tool ? `${uiLabel(event.kind)} · ${uiLabel(p.tool)}` : uiLabel(event.kind));
    ledger.push({id:`event:${event.seq}`,spanId:event.kind === "operator.message"?"input":spanId,ts:at(event.created),
      kind:event.kind === "operator.message"?"input":event.kind === "fact.created"?"finding":event.kind.startsWith("tool.")?"call":event.kind.startsWith("flag.")?"result":"system",
      text:String(title),body:JSON.stringify({seq:event.seq,kind:event.kind,...p},null,2)});
  }
  return {origin,scenario:finalizeScenario({id:run.id,title:challenge?.title || run.id,task:"",spans,events:ledger})};
}
