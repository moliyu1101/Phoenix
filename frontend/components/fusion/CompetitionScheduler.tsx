"use client";
import {useEffect,useState} from "react";
import Link from "next/link";
import {Flag,Plus,RefreshCw,Play,Pause,RotateCcw,Trash2,Send,Settings2,Check,ArrowRight,ListOrdered,Zap} from "lucide-react";
import {api,post,patch,useResource} from "@/lib/phoenix";
import {uiLabel} from "@/lib/phoenix-labels";
import {Badge,Empty,ToolHeader,useOperation} from "./Workbench";
import {ConfigModal} from "./ConfigModal";

const CATEGORIES=["web","crypto","pwn","reverse","forensics","misc"];
const ENTRY_STATE:Record<string,{label:string;tone:string}>={
 pending:{label:"排队中",tone:"blue"},running:{label:"解题中",tone:"amber"},solved:{label:"已解出",tone:"green"},
 exhausted:{label:"已耗尽",tone:"muted"},failed:{label:"失败",tone:"muted"},skipped:{label:"已跳过",tone:"muted"},
};
const ACTION:Record<string,string>={admit:"准入",hold:"挂起",settled:"已结算",skip:"跳过",error:"错误",requeue:"重新排队"};
const HOLD_REASON:Record<string,string>={category_filtered:"类别不在策略范围",auto_import_disabled:"未开启自动导入"};
const SUBMIT_STATE:Record<string,{label:string;tone:string}>={
 correct:{label:"判对",tone:"green"},incorrect:{label:"判错",tone:"muted"},pending:{label:"待回执",tone:"amber"},
 unknown:{label:"结果未知",tone:"amber"},submitted:{label:"已提交",tone:"blue"},
};

function decisionText(entry:any):string{
 const d=entry.admission_decision||{};
 if(!d.action)return "等待调度准入";
 const action=ACTION[d.action]||d.action;
 if(d.action==="hold")return `${action}：${HOLD_REASON[d.reason]||d.reason||""}`;
 if(d.action==="error")return `${action}：${entry.last_error||d.reason||""}`;
 if(d.action==="settled")return `${action}：${uiLabel(d.run_state||"")}`;
 return action;
}

export function CompetitionScheduler(){
 const op=useOperation();
 const competitions=useResource<any[]>("/api/competitions",4000);
 const platforms=useResource<any[]>("/api/integrations/platforms",0);
 const [selected,setSelected]=useState("");
 const [modal,setModal]=useState(false),[notice,setNotice]=useState("");
 const [connection,setConnection]=useState(""),[title,setTitle]=useState(""),[external,setExternal]=useState("");
 const detail=useResource<any>(selected?`/api/competitions/${selected}`:null,4000);
 const [policy,setPolicy]=useState<any>(null);
 useEffect(()=>{if(competitions.data?.length&&!selected)setSelected(competitions.data[0].id);},[competitions.data,selected]);
 useEffect(()=>{if(detail.data?.policy)setPolicy({...detail.data.policy,budget:{...detail.data.policy.budget},categories:[...(detail.data.policy.categories||[])]});},[detail.data?.id,detail.data?.updated]);
 const list=competitions.data||[],current=list.find(c=>c.id===selected),queue:any[]=detail.data?.queue||[];
 const platformLabel=(cid:string)=>platforms.data?.find(p=>p.connection_id===cid)?.label||cid;
 const counts=current?.counts||{};
 const running=current?.scheduler_state==="running";
 function refreshAll(){void competitions.refresh();void detail.refresh();}
 function toggleCategory(cat:string){setPolicy((p:any)=>({...p,categories:p.categories.includes(cat)?p.categories.filter((x:string)=>x!==cat):[...p.categories,cat]}));}
 async function savePolicy(){await op.act(async()=>{await patch(`/api/competitions/${selected}/policy`,{max_concurrency:Number(policy.max_concurrency),categories:policy.categories,auto_submit:!!policy.auto_submit,auto_import:!!policy.auto_import,auto_distill:!!policy.auto_distill,flag_prefix:policy.flag_prefix,targets:String(policy.targetsText??(policy.targets||[]).join("\n")).split(/\s+/).filter(Boolean),budget:{max_calls:Number(policy.budget.max_calls),max_tokens:Number(policy.budget.max_tokens),wall_seconds:Number(policy.budget.wall_seconds)}});await detail.refresh();setNotice("调度策略已保存。");});}
 return <div className="px-fusion-panel px-integration-workspace px-comp-scheduler">
  <ToolHeader icon={<ListOrdered size={20}/>} title="比赛调度" description="注册比赛、编排队列，Phoenix 自动准入、原生解题并按策略回传平台。"><Link className="px-tool-link" href="/competition"><Flag size={14}/>比赛平台<ArrowRight size={12}/></Link><button className="px-tool-primary" onClick={()=>{setConnection(platforms.data?.[0]?.connection_id||"");setTitle("");setExternal("");setModal(true);}}><Plus size={14}/>新建比赛</button></ToolHeader>
  {(op.error||competitions.error||detail.error)&&<div role="alert" className="px-error">{op.error||competitions.error||detail.error}</div>}
  {notice&&<p className="px-tool-notice" role="status"><Check size={14}/>{notice}</p>}
  <section>
   <div className="px-tool-table-scroll"><table className="px-admin-table px-comp-list"><thead><tr><th>比赛</th><th>平台连接</th><th>调度状态</th><th>排队 / 解题 / 已解</th><th>操作</th></tr></thead><tbody>{list.map(c=>{const n=c.counts||{};return <tr key={c.id} data-selected={c.id===selected} onClick={()=>setSelected(c.id)}><td><strong>{c.title}</strong><small>{c.external_competition_id||"默认比赛"}</small></td><td>{platformLabel(c.connection_id)}</td><td><Badge tone={c.scheduler_state==="running"?"green":"muted"}>{c.scheduler_state==="running"?"调度中":"已暂停"}</Badge></td><td>{n.pending||0} / {n.running||0} / {n.solved||0}</td><td><button aria-label={`删除 ${c.title}`} disabled={op.busy} onClick={e=>{e.stopPropagation();void op.act(async()=>{await api(`/api/competitions/${c.id}`,{method:"DELETE"});if(selected===c.id)setSelected("");await competitions.refresh();setNotice("比赛已删除。");});}}><Trash2 size={13}/>删除</button></td></tr>;})}</tbody></table></div>
   {!list.length&&<Empty title={competitions.loading?"读取比赛…":"还没有注册比赛"}>连接比赛平台后新建比赛，同步题库即可开始批量调度。<button onClick={()=>{setConnection(platforms.data?.[0]?.connection_id||"");setModal(true);}}><Plus size={14}/>新建比赛</button></Empty>}
  </section>
  {current&&<>
   <div className="px-fusion-toolbar">
    <button disabled={op.busy} onClick={()=>void op.act(async()=>{const r=await post(`/api/competitions/${selected}/sync`);refreshAll();setNotice(`题库同步完成：新增 ${r.added}，更新 ${r.updated}。`);})}><RefreshCw size={14}/>同步题库</button>
    {running?<button disabled={op.busy} onClick={()=>void op.act(async()=>{await post(`/api/competitions/${selected}/scheduler`,{action:"pause"});refreshAll();setNotice("调度已暂停，不再准入新题。");})}><Pause size={14}/>暂停调度</button>
     :<button className="px-tool-primary" disabled={op.busy} onClick={()=>void op.act(async()=>{await post(`/api/competitions/${selected}/scheduler`,{action:"start"});refreshAll();setNotice("调度已启动。");})}><Play size={14}/>启动调度</button>}
    <button disabled={op.busy} onClick={()=>void op.act(async()=>{const r=await post(`/api/competitions/${selected}/tick`);refreshAll();setNotice(`手动调度：准入 ${r.admitted.length}，结算 ${r.settled.length}，回传 ${r.submitted.length}。`);})}><Zap size={14}/>手动调度</button>
    <span className="px-tool-count">{current.title}</span>
   </div>
   <div className="px-tool-summary"><span>队列<b>{queue.length}</b></span><span>排队中<b>{counts.pending||0}</b></span><span>解题中<b>{counts.running||0}</b></span><span>已解出<b>{counts.solved||0}</b></span><span>已耗尽<b>{counts.exhausted||0}</b></span><span>失败<b>{counts.failed||0}</b></span><span>已跳过<b>{counts.skipped||0}</b></span></div>
   <div className="px-comp-grid">
    <div className="px-tool-main">
     <div className="px-tool-table-scroll"><table className="px-admin-table px-competition-board"><thead><tr><th>题目</th><th>类别</th><th>分值</th><th>优先级</th><th>队列状态</th><th>运行绑定</th><th>回传</th><th>操作</th></tr></thead><tbody>{queue.map(entry=>{const meta=ENTRY_STATE[entry.state]||{label:entry.state,tone:"muted"};const sub=entry.submission_state?SUBMIT_STATE[entry.submission_state]||{label:entry.submission_state,tone:"muted"}:null;return <tr key={entry.id}>
      <td><strong>{entry.title}</strong><small>#{entry.challenge_key}</small><div className="px-comp-decision">{decisionText(entry)}</div></td>
      <td><Badge>{uiLabel(entry.category)}</Badge></td>
      <td>{entry.score}</td>
      <td><input className="px-comp-priority" type="number" min={0} max={100} aria-label={`优先级 ${entry.title}`} defaultValue={entry.priority} key={`${entry.id}-${entry.priority}`} disabled={op.busy} onBlur={e=>{const v=Number(e.target.value);if(v!==entry.priority)void op.act(async()=>{await patch(`/api/competitions/${selected}/queue/${entry.id}`,{priority:v});await detail.refresh();});}}/></td>
      <td><Badge tone={meta.tone}>{meta.label}</Badge>{entry.run_state&&<small>{uiLabel(entry.run_state)}</small>}</td>
      <td>{entry.run_id?<Link className="px-comp-run" href={`/run/${entry.run_id}`}><Play size={12}/>打开运行</Link>:<span className="px-comp-decision">未绑定</span>}</td>
      <td>{sub?<Badge tone={sub.tone}>{sub.label}</Badge>:<span className="px-comp-decision">—</span>}</td>
      <td><div className="px-comp-row-actions">
       {entry.state!=="running"&&<button disabled={op.busy} onClick={()=>void op.act(async()=>{await post(`/api/competitions/${selected}/queue/${entry.id}/admit`);refreshAll();setNotice("已手动准入并启动解题。");})}><Play size={12}/>准入</button>}
       {entry.state!=="running"&&entry.state!=="skipped"&&<button disabled={op.busy} onClick={()=>void op.act(async()=>{await post(`/api/competitions/${selected}/queue/${entry.id}/skip`);refreshAll();})}>跳过</button>}
       {["failed","exhausted","skipped","solved"].includes(entry.state)&&<button disabled={op.busy} onClick={()=>void op.act(async()=>{await post(`/api/competitions/${selected}/queue/${entry.id}/requeue`);refreshAll();})}><RotateCcw size={12}/>重排</button>}
      </div></td>
     </tr>;})}</tbody></table></div>
     {!queue.length&&<Empty title="队列为空">点击“同步题库”从平台拉取题目并加入调度队列。</Empty>}
     <footer className="px-tool-table-footer">显示 {queue.length} 道题目{detail.data?.updated&&<span>更新于 {new Date(detail.data.updated*1000).toLocaleString("zh-CN")}</span>}</footer>
    </div>
    {policy&&<aside className="px-comp-policy">
     <h3><Settings2 size={16}/>调度策略</h3>
     <section>
      <label className="px-comp-toggle">最大并行解题<input type="number" min={1} max={16} aria-label="最大并行解题" value={policy.max_concurrency} onChange={e=>setPolicy({...policy,max_concurrency:e.target.value})}/></label>
      <label className="px-comp-toggle">自动导入题面与附件<input type="checkbox" aria-label="自动导入" checked={!!policy.auto_import} onChange={e=>setPolicy({...policy,auto_import:e.target.checked})}/></label>
      <label className="px-comp-toggle">解出后自动回传平台<input type="checkbox" aria-label="自动回传" checked={!!policy.auto_submit} onChange={e=>setPolicy({...policy,auto_submit:e.target.checked})}/></label>
      <label className="px-comp-toggle">结束后自动蒸馏经验<input type="checkbox" aria-label="自动蒸馏" checked={!!policy.auto_distill} onChange={e=>setPolicy({...policy,auto_distill:e.target.checked})}/></label>
     </section>
     <section>
      <h4>准入类别（不选表示全部）</h4>
      <div className="px-comp-categories">{CATEGORIES.map(cat=><button key={cat} type="button" aria-pressed={policy.categories.includes(cat)} onClick={()=>toggleCategory(cat)}>{uiLabel(cat)}</button>)}</div>
     </section>
     <section>
      <h4>单题运行预算</h4>
      <div className="px-comp-budget">
       <label>调用<input type="number" min={1} aria-label="最大调用" value={policy.budget.max_calls} onChange={e=>setPolicy({...policy,budget:{...policy.budget,max_calls:e.target.value}})}/></label>
       <label>词元<input type="number" min={500} aria-label="最大词元" value={policy.budget.max_tokens} onChange={e=>setPolicy({...policy,budget:{...policy.budget,max_tokens:e.target.value}})}/></label>
       <label>秒<input type="number" min={10} aria-label="最长秒数" value={policy.budget.wall_seconds} onChange={e=>setPolicy({...policy,budget:{...policy.budget,wall_seconds:e.target.value}})}/></label>
      </div>
     </section>
     <section>
      <label>答案前缀<input aria-label="答案前缀" pattern="[A-Za-z0-9_]{1,32}" value={policy.flag_prefix} onChange={e=>setPolicy({...policy,flag_prefix:e.target.value})}/></label>
      <label>题目目标<textarea rows={3} aria-label="题目目标" placeholder="每行一个 http(s)://主机:端口 或 tcp://主机:端口；附件题可留空" value={policy.targetsText??(policy.targets||[]).join("\n")} onChange={e=>setPolicy({...policy,targetsText:e.target.value})}/></label>
      <button className="px-tool-primary" disabled={op.busy} onClick={()=>void savePolicy()}><Send size={14}/>保存策略</button>
     </section>
    </aside>}
   </div>
  </>}
  <ConfigModal open={modal} onClose={()=>setModal(false)} title="新建比赛"><form className="px-tool-form" onSubmit={e=>{e.preventDefault();void op.act(async()=>{const value=await post<any>("/api/competitions",{connection_id:connection,title,external_competition_id:external});await competitions.refresh();setSelected(value.id);setModal(false);setNotice("比赛已注册，点击同步题库开始调度。");});}}>
   <label>平台连接<select required aria-label="平台连接" value={connection} onChange={e=>setConnection(e.target.value)}><option value="">选择已连接的平台</option>{platforms.data?.map(p=><option key={p.connection_id} value={p.connection_id}>{p.label||p.platform_kind} · {p.canonical_base_url}</option>)}</select></label>
   {!platforms.data?.length&&<p className="px-comp-decision">尚未配置平台连接，请先到“比赛平台”新建连接。</p>}
   <label>比赛名称<input required aria-label="比赛名称" value={title} onChange={e=>setTitle(e.target.value)} placeholder="例如：春季邀请赛"/></label>
   <label>平台比赛编号<input aria-label="平台比赛编号" value={external} onChange={e=>setExternal(e.target.value)} placeholder="GZCTF 比赛编号；CTFd 可留空"/></label>
   {op.error&&<div role="alert" className="px-error">{op.error}</div>}
   <div className="px-modal-footer"><button type="button" onClick={()=>setModal(false)}>取消</button><button className="px-tool-primary" disabled={op.busy||!connection||!title}>注册比赛</button></div>
  </form></ConfigModal>
 </div>;
}