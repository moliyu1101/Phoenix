"use client";
import {uiLabel} from "@/lib/phoenix-labels";
import {useMemo,useState} from "react";
import {Radio, ShieldCheck, Clock3, ArrowDownUp} from "lucide-react";
import {post,useResource} from "@/lib/phoenix";
import {RequestEditor} from "../src/RequestEditor";
import type {HttpExchange} from "../src/RequestWorkspaceTypes";
import {HttpPacket} from "./HttpPacket";
import {Badge,Empty,Refresh,SearchBox,ToolHeader,useOperation} from "./Workbench";

function packet(row:any,response=false){
 const r=response?row.response:row.request;if(!r)return "";
 return [(response?`HTTP/1.1 ${r.status}`:`${r.method} ${r.url} HTTP/1.1`),...Object.entries(r.headers||{}).map(([k,v])=>`${k}: ${v}`),"",r.body||""].join("\r\n");
}
export function parseRequest(raw:string,baseUrl:string){
 const separator=raw.includes("\r\n\r\n")?"\r\n\r\n":"\n\n",index=raw.indexOf(separator),head=index>=0?raw.slice(0,index):raw;
 const lines=head.split(/\r?\n/),start=/^([A-Z]+)\s+(\S+)\s+HTTP\/\S+$/.exec(lines.shift()||"");
 if(!start)throw new Error("请求首行应为 METHOD URL HTTP/1.1");
 const headers:Record<string,string>={};
 for(const line of lines){if(!line.trim())continue;const i=line.indexOf(":");if(i<1)throw new Error("请求头 应为名称: 值");const value=line.slice(i+1).trim();if(value!=="<redacted>")headers[line.slice(0,i).trim()]=value;}
 return {method:start[1],url:new URL(start[2],baseUrl).href,headers,body:index>=0?raw.slice(index+separator.length):""};
}
const stateLabel:Record<string,string>={pending:"待处理",approved:"已发送",rejected:"已拒绝",cancelled:"已取消"};
export function TrafficPanel({rid,approvals}:{rid:string;approvals:boolean}){
 const r=useResource<any>(`/api/runs/${rid}/${approvals?"approvals":"traffic"}`,2000),op=useOperation();
 const [selected,setSelected]=useState<any>(null),[raw,setRaw]=useState(""),[query,setQuery]=useState(""),[filter,setFilter]=useState("");
 const intercept=!!r.data?.intercept;
 const items:any[]=approvals?(r.data||[]):(r.data?.items||[]),filtered=items.filter(row=>`${row.request.method} ${row.request.url}`.toLowerCase().includes(query.toLowerCase())&&(!filter||(approvals?row.state:row.request.method)===filter));
 function select(item:any){setSelected(item);setRaw(packet(item));}
 const live=items.find(row=>row.id===selected?.id)||selected;
 const exchange=useMemo<HttpExchange|null>(()=>selected?{exchange_id:selected.id,task_id:rid,source_kind:selected.request.source||"http_tool",actor_ref:"",context_id:"",identity_revision:0,browser_generation:0,method:selected.request.method,observed_url:selected.request.url,started_at:selected.created,status_code:selected.response?.status,protocol:"HTTP",request_raw_ref:{artifact_id:"",sha256:"",size:0,task_id:rid,version:1,media_type:"text/plain"},capture_state:selected.response?.truncated?"partial":"recorded",execution_state:approvals?(stateLabel[selected.state]||selected.state):"completed"}:null,[selected,rid,approvals]);
 async function execute(approved=true){await op.act(async()=>{if(approvals){await post(`/api/runs/${rid}/approvals/${selected.id}`,{approved,...(approved?{request:parseRequest(raw,selected.request.url)}:{})});}else await post(`/api/runs/${rid}/traffic/${selected.id}/replay`,parseRequest(raw,selected.request.url));await r.refresh();});}
 return <section className="px-fusion-panel" aria-label={approvals?"拦截审批":"HTTP 流量"}>
  <ToolHeader icon={approvals?<ShieldCheck size={19}/>:<Radio size={19}/>} title={approvals?"拦截审批":"HTTP 流量"} description={approvals?"处理拦截队列，检查或编辑请求后再发送。":"检索录制请求，查看报文与响应，编辑后重放。"}><Badge>{items.length} 条</Badge><Refresh busy={r.loading} onClick={()=>void r.refresh()}/>{!approvals&&<button role="switch" aria-label="发送前拦截审批" aria-checked={intercept} disabled={op.busy||r.loading||!r.data?.items} className={intercept?"px-tool-primary":""} onClick={()=>{const enabled=!intercept;void op.act(async()=>{await post(`/api/runs/${rid}/traffic/intercept`,{enabled});await r.refresh();});}}><ShieldCheck size={14}/>{intercept?"拦截已开启":"开启拦截"}</button>}</ToolHeader>
  {approvals&&<div className="px-tool-summary"><span><Clock3 size={15}/><b>{items.filter(a=>a.state==="pending").length}</b> 待处理</span><span><ShieldCheck size={15}/><b>{items.filter(a=>a.state==="approved").length}</b> 已发送</span><span>每条请求保留独立处理结果</span></div>}
  <div className="px-tool-filter"><SearchBox value={query} onChange={setQuery} placeholder="搜索方法或 URL"/><select aria-label={approvals?"审批状态":"请求方法"} value={filter} onChange={e=>setFilter(e.target.value)}><option value="">{approvals?"全部状态":"全部方法"}</option>{(approvals?Object.keys(stateLabel):Array.from(new Set(items.map(i=>i.request.method)))).map(v=><option key={v} value={v}>{stateLabel[v]||v}</option>)}</select><span className="px-tool-count">{filtered.length} 条匹配</span></div>
  {(op.error||r.error)&&<div className="px-error" role="alert">{op.error||r.error}</div>}
  <div className="px-traffic-workspace"><div className="px-traffic-list"><table className="px-admin-table"><thead><tr><th>请求 / 来源</th><th>状态</th></tr></thead><tbody>{filtered.map(row=><tr key={row.id} data-selected={selected?.id===row.id}><td><button className="px-traffic-select" onClick={()=>select(row)}><Badge tone="blue">{row.request.method}</Badge><span title={row.request.url}>{row.request.url}</span></button><small>{row.request.source?uiLabel(row.request.source):"网络请求"} · {new Date(row.created*1000).toLocaleTimeString("zh-CN",{hour12:false})}</small></td><td><Badge tone={approvals?(row.state==="pending"?"amber":row.state==="approved"?"green":"muted"):(row.response.status>=400?"amber":"green")}>{approvals?stateLabel[row.state]||row.state:row.response.status}</Badge></td></tr>)}</tbody></table>{!filtered.length&&<Empty title={r.loading?"读取请求…":approvals?"当前没有拦截请求":"尚无录制流量"}>{approvals?"开启流量拦截后，请求将在这里等待处理。":"浏览器和 HTTP 工具产生的真实流量会显示在这里。"}</Empty>}</div>
   <div className="px-traffic-inspector">{selected&&exchange?<RequestEditor key={selected.id} exchange={exchange} rawRequest={raw} rawResponse={packet(selected,true)} onRawChange={setRaw} onSave={()=>{}} onExecute={()=>void execute()} onReload={()=>select(live)} onDecide={()=>{}} busy={op.busy} dirty={raw!==packet(selected)} conflict={false} native={{state:approvals?(stateLabel[live.state]||live.state):"已完成",source:`${selected.request.source?uiLabel(selected.request.source):"网络请求"} · ${new Date(selected.created*1000).toLocaleString("zh-CN")}`,evidence:selected.evidence_id,decided:approvals&&live.state!=="pending",onReject:approvals?()=>void execute(false):undefined,response:selected.response?<><div className="px-tool-filter"><Badge tone="green">HTTP {selected.response.status}</Badge><span>{selected.response.duration_ms} ms</span>{selected.response.truncated&&<Badge tone="amber">响应已截断</Badge>}</div><HttpPacket raw={packet(selected,true)}/></>:<Empty title={approvals?stateLabel[live.state]||"等待处理":"没有响应"}>发送后的响应记录可在 HTTP 流量中查看。</Empty>}}/>:<Empty title="选择一条请求"><ArrowDownUp size={18}/> 查看请求、响应与原始证据，或进入结构化编辑。</Empty>}</div>
  </div>
 </section>;
}
