"use client";
import {uiLabel} from "@/lib/phoenix-labels";
import {readChatPreferences,useChatPreferences} from "@/lib/chatPreferences";
import {useEffect,useRef,useState} from "react";
import Image from "next/image";
import {Box, Play, Pause, Square, Terminal as SquareTerminal, Globe, ArrowRight, MousePointer2, Camera, FileText, Link as LinkIcon, Cpu, Settings2, ExternalLink} from "lucide-react";
import Link from "next/link";
import {api,post,useResource} from "@/lib/phoenix";
import {AssetsPanel} from "./fusion/AssetsPanel";
import {TrafficPanel} from "./fusion/TrafficPanel";
import {Badge,Empty,ToolHeader,useOperation,Refresh} from "./fusion/Workbench";
export function PhoenixRunTools({rid,panel}:{rid:string;panel:string}){
 if(panel==="sandbox")return <SandboxPanel key={rid} rid={rid}/>;
 if(panel==="terminal")return <TerminalPanel key={rid} rid={rid}/>;
 if(panel==="browser")return <BrowserPanel key={rid} rid={rid}/>;
 if(panel==="assets")return <AssetsPanel key={rid} rid={rid}/>;
 if(panel==="traffic"||panel==="approvals")return <TrafficPanel key={rid+panel} rid={rid} approvals={panel==="approvals"}/>;
 if(panel==="engines")return <EnginesPanel key={rid} rid={rid}/>;
 return null;
}

function SandboxPanel({rid}:{rid:string}){
 const r=useResource<any>(`/api/runs/${rid}/sandbox`,5000),op=useOperation();
 const [command,setCommand]=useState(""),[history,setHistory]=useState<any[]>([]),[tab,setTab]=useState("console");
 const state=r.data?.state,states:Record<string,string>={absent:"未创建",unavailable:"不可用",running:"运行中",paused:"已暂停",exited:"已停止",not_created:"未创建",missing:"未创建"};
 return <section className="px-fusion-panel" aria-label="运行沙箱"><ToolHeader icon={<Box size={19}/>} title="题目沙箱" description="工具、交互终端和 智能体 共用本轮文件环境。"><Badge tone={state==="running"?"green":"muted"}>{states[state]||state||"读取中"}</Badge><Refresh busy={r.loading} onClick={()=>void r.refresh()}/></ToolHeader>
  <div className="px-sandbox-overview"><div className="px-sandbox-machine"><Box size={30}/><div><strong>{r.data?.category?uiLabel(r.data.category):"Phoenix"} 工具环境</strong><code>{r.data?.image||"按题型准备工具镜像"}</code></div></div><div className="px-fusion-toolbar">{[["start","创建 / 启动",Play],["pause","暂停容器",Pause],["resume","恢复容器",Play],["stop","停止容器",Square]].map(([action,title,Icon]:any)=><button key={action} disabled={op.busy||(action==="pause"&&state!=="running")||(action==="resume"&&state!=="paused")||(action==="stop"&&!['running','paused'].includes(state))} onClick={()=>void op.act(async()=>{await post(`/api/runs/${rid}/sandbox`,{action});await r.refresh();})}><Icon size={14}/>{title}</button>)}</div></div>
  <div className="px-tool-properties-row"><span>附件挂载 <code>/input</code></span><span>持久工作区 <code>/work</code></span><span>网络请求经本轮工具通道</span></div>
  <nav className="px-tool-tabs"><button aria-pressed={tab==="console"} onClick={()=>setTab("console")}><SquareTerminal size={14}/>命令执行</button><button aria-pressed={tab==="environment"} onClick={()=>setTab("environment")}><Settings2 size={14}/>环境详情</button></nav>
  {(op.error||r.error||r.data?.error)&&<div className="px-error" role="alert">{op.error||r.error||r.data.error}</div>}
  {tab==="console"?<><form className="px-command-editor" onSubmit={e=>{e.preventDefault();void op.act(async()=>{const result=await post(`/api/runs/${rid}/sandbox/exec`,{command,timeout:60});setHistory(old=>[{...result,command,time:new Date().toLocaleTimeString("zh-CN",{hour12:false})},...old]);});}}><header><span><SquareTerminal size={14}/>bash</span><small>人工执行前先暂停蜂群</small></header><textarea aria-label="沙箱命令" required rows={4} value={command} onChange={e=>setCommand(e.target.value)} spellCheck={false} placeholder="file /input/*"/><footer><span>超时 60s · 输出写入本轮证据</span><button className="px-tool-primary" disabled={op.busy||!command.trim()}><Play size={14}/>在沙箱中执行</button></footer></form><section className="px-command-history"><h3>执行记录 <Badge>{history.length}</Badge></h3>{!history.length?<Empty title="等待执行命令">输出、退出码和证据引用将在这里保留。</Empty>:history.map((result,i)=><article key={i}><header><code>$ {result.command}</code><span>{result.time}</span><Badge tone={result.exit_code===0?"green":"amber"}>退出码 {result.exit_code}{result.timed_out?" · 超时":""}</Badge></header><pre className="px-fusion-output">{result.stdout||"（无输出）"}</pre><p className="px-evidence-ref">证据 {result.evidence_id}</p></article>)}</section></>:<dl className="px-tool-properties"><dt>镜像</dt><dd>{r.data?.image||"—"}</dd><dt>容器</dt><dd>{r.data?.container_name||"—"}</dd><dt>状态</dt><dd>{states[state]||state||"—"}</dd><dt>附件目录</dt><dd>/input · 只读</dd><dt>工作目录</dt><dd>/work · 本轮持久化</dd></dl>}
 </section>;
}

function BrowserPanel({rid}:{rid:string}){
 const [url,setUrl]=useState(""),[selector,setSelector]=useState(""),[value,setValue]=useState(""),[result,setResult]=useState<any>(null),[view,setView]=useState("text"),[history,setHistory]=useState<string[]>([]),op=useOperation();
 const run=useResource<any>(`/api/runs/${rid}`,0),challenge=useResource<any>(run.data?`/api/challenges/${run.data.run.challenge_id}`:null,0);
 async function act(action:string,href?:string){await op.act(async()=>{const next=await post<any>(`/api/runs/${rid}/browser`,{action,url:href||url,selector,value});setResult(next);if(next.url){setUrl(next.url);setHistory(old=>Array.from(new Set([next.url,...old])).slice(0,12));}if(action==="screenshot")setView("screenshot");});}
 return <section className="px-fusion-panel" aria-label="题目浏览器"><ToolHeader icon={<Globe size={19}/>} title="题目浏览器" description="与 智能体 共用页面会话，记录请求和操作证据。"><Badge tone={result?"green":"muted"}>{result?"会话已连接":"尚未打开页面"}</Badge><button disabled={op.busy||!result} onClick={()=>void act("screenshot")}><Camera size={14}/>截图</button></ToolHeader>
  <form className="px-browser-address" onSubmit={e=>{e.preventDefault();void act("navigate");}}><Globe size={16}/><input required type="url" aria-label="浏览器地址" placeholder="输入题目地址" value={url} onChange={e=>setUrl(e.target.value)}/><button className="px-tool-primary" disabled={op.busy}><ArrowRight size={14}/>访问</button></form>
  {!!challenge.data?.targets?.length&&<div className="px-browser-targets"><span>题目目标</span>{challenge.data.targets.map((target:string)=><button key={target} onClick={()=>{setUrl(target);void act("navigate",target);}} disabled={op.busy}>{target}</button>)}</div>}
  {op.error&&<div role="alert" className="px-error">{op.error}</div>}{op.busy&&<p role="status" className="px-tool-progress">正在处理页面；开启拦截时，可前往“拦截审批”处理请求。</p>}
  <div className="px-browser-workspace"><div className="px-browser-document"><nav className="px-tool-tabs">{[["text","页面内容",FileText],["screenshot","截图预览",Camera],["links","链接",LinkIcon]].map(([id,title,Icon]:any)=><button key={id} aria-pressed={view===id} onClick={()=>setView(id)}><Icon size={14}/>{title}</button>)}<span>{result?.title||"新标签页"}</span></nav>{!result?<Empty title="打开题目页面">输入地址或选择上方目标，开始浏览。</Empty>:view==="screenshot"?(result.image_base64?<Image unoptimized width={1280} height={720} style={{height:"auto"}} className="px-fusion-browser-shot" src={`data:image/png;base64,${result.image_base64}`} alt="题目浏览器当前页面"/>:<Empty title="尚未截图"><button disabled={op.busy} onClick={()=>void act("screenshot")}>获取当前截图</button></Empty>):view==="links"?<div className="px-browser-links">{result.links?.map((link:any,i:number)=><button key={i} onClick={()=>{setUrl(link.url);void act("navigate",link.url);}} disabled={op.busy}><LinkIcon size={14}/><span><strong>{link.text||link.url}</strong><small>{link.url}</small></span><ArrowRight size={14}/></button>)}{!result.links?.length&&<Empty title="页面没有链接"/>}</div>:<pre className="px-browser-text">{result.text||"页面没有可读文本"}</pre>}{result?.evidence_id&&<footer className="px-evidence-ref">证据 <code>{result.evidence_id}</code></footer>}</div>
   <aside className="px-browser-controls"><h3><MousePointer2 size={15}/>元素操作</h3><label>选择器<input aria-label="页面元素" placeholder="#username 或 button[type=submit]" value={selector} onChange={e=>setSelector(e.target.value)}/></label><label>值 / 按键<input aria-label="填写内容" placeholder="输入内容或 Enter" value={value} onChange={e=>setValue(e.target.value)}/></label><div className="px-fusion-toolbar">{[["click","点击"],["fill","填写"],["press","按键"],["read","读取页面"]].map(([action,title])=><button key={action} disabled={op.busy||!result||(action!=="read"&&!selector)} onClick={()=>void act(action)}>{title}</button>)}</div><h3>访问记录</h3><div className="px-browser-history">{history.map(href=><button key={href} title={href} onClick={()=>{setUrl(href);void act("navigate",href);}} disabled={op.busy}>{href}</button>)}{!history.length&&<p className="px-muted">本次页面访问后显示</p>}</div></aside>
  </div>
 </section>;
}

function EnginesPanel({rid}:{rid:string}){
 const catalog=useResource<any[]>("/api/integrations/engines",0),sessions=useResource<any[]>(`/api/runs/${rid}/engine-sessions`,4000),[installed,setInstalled]=useState<any[]>([]),[checked,setChecked]=useState(false),op=useOperation();
 const items=(catalog.data||[]).map(e=>({...e,...installed.find(x=>x.id===e.id)}));
 return <section className="px-fusion-panel"><ToolHeader icon={<Cpu size={19}/>} title="执行引擎" description="查看原生接口、Pi 与外部命令行工具 的接入方式和本轮会话。"><Link className="px-tool-link" href="/swarm"><Settings2 size={14}/>蜂群编队<ExternalLink size={12}/></Link><button disabled={op.busy} onClick={()=>void op.act(async()=>{setInstalled(await api(`/api/runs/${rid}/engines`));setChecked(true);})}>检查已安装引擎</button></ToolHeader>{op.error&&<div role="alert" className="px-error">{op.error}</div>}<table className="px-admin-table"><thead><tr><th>引擎</th><th>接入方式</th><th>安装状态</th></tr></thead><tbody>{items.map(e=><tr key={e.id}><td><strong>{e.id==="api"?"Phoenix 原生工具循环":e.label}</strong><small>{e.id}</small></td><td>{e.gateway?"本轮模型与预算":"独立 命令行 账号"}</td><td><Badge tone={e.installed?"green":"muted"}>{checked?(e.installed?"已安装":"未安装 / 未启动沙箱"):"未检查"}</Badge></td></tr>)}</tbody></table><h3>本轮会话 <Badge>{sessions.data?.length||0}</Badge></h3>{!sessions.data?.length?<Empty title="尚无引擎会话">在蜂群编队中为 智能体 选择引擎，启动后在此查看。</Empty>:<table className="px-admin-table"><thead><tr><th>引擎</th><th>状态</th><th>会话</th></tr></thead><tbody>{sessions.data.map(s=><tr key={s.id}><td>{s.engine}</td><td><Badge>{uiLabel(s.state)}</Badge></td><td><code>{s.remote_session||s.id}</code></td></tr>)}</tbody></table>}</section>;
}
function TerminalPanel({rid}:{rid:string}){
 const [sid,setSid]=useState(""),op=useOperation(),host=useRef<HTMLDivElement>(null),terminalDisplay=useRef<any>(null),prefs=useChatPreferences();
 useEffect(()=>{const view=terminalDisplay.current;if(!view||!host.current)return;view.term.options.fontSize=Math.round(prefs.uiFontSize*13/14);view.term.options.fontFamily=getComputedStyle(host.current).getPropertyValue("--cx-font-mono").trim();view.resize();},[prefs.uiFontSize,prefs.codeFont]);
 useEffect(()=>{setSid(sessionStorage.getItem(`phoenix.terminal.${rid}`)||"");},[rid]);
 useEffect(()=>{
  if(!sid||!host.current)return;
  let disposed=false,timer:ReturnType<typeof setTimeout>|undefined,cleanup=()=>{};
  void(async()=>{
   const [{Terminal},{FitAddon}]=await Promise.all([import("@xterm/xterm"),import("@xterm/addon-fit")]);
   if(disposed||!host.current)return;
   const term=new Terminal({convertEol:false,fontSize:Math.round(readChatPreferences().uiFontSize*13/14),fontFamily:getComputedStyle(host.current).getPropertyValue("--cx-font-mono").trim(),scrollback:3000,theme:{background:"#111318",foreground:"#e4e7ef"}}),fit=new FitAddon();
   term.loadAddon(fit);term.open(host.current);fit.fit();
   const resize=()=>{fit.fit();void post(`/api/runs/${rid}/terminals/${sid}/resize`,{rows:term.rows,cols:term.cols}).catch(()=>{});};
   const observer=new ResizeObserver(resize);observer.observe(host.current);resize();terminalDisplay.current={term,fit,resize};
   let after=0,pending="",sending=false;
   const send=async()=>{if(sending||!pending)return;sending=true;const data=pending;pending="";try{await post(`/api/runs/${rid}/terminals/${sid}/input`,{data_base64:btoa(String.fromCharCode(...new TextEncoder().encode(data)))});}catch(e){term.writeln("\r\n"+(e as Error).message);}finally{sending=false;if(pending)void send();}};
   const input=term.onData(data=>{pending+=data;void send();});
   const poll=async()=>{try{const next=await api<any>(`/api/runs/${rid}/terminals/${sid}?after=${after}`);if(disposed)return;for(const chunk of next.items)term.write(Uint8Array.from(atob(chunk.content),c=>c.charCodeAt(0)));after=next.next_after;if(next.state!=="open"){term.writeln("\r\n终端已关闭，可重新连接沙箱。");return;}}catch(e){if(!disposed)term.writeln("\r\n"+(e as Error).message);return;}if(!disposed)timer=setTimeout(poll,300);};
   void poll();cleanup=()=>{observer.disconnect();input.dispose();if(terminalDisplay.current?.term===term)terminalDisplay.current=null;term.dispose();};
  })();
  return()=>{disposed=true;if(timer)clearTimeout(timer);cleanup();};
 },[rid,sid]);
 return <section className="px-fusion-panel" aria-label="沙箱终端"><ToolHeader icon={<SquareTerminal size={19}/>} title="交互终端" description="连接本轮沙箱；切换视图后保留会话。"><div className="px-fusion-toolbar"><button disabled={op.busy} onClick={()=>void op.act(async()=>{const next=await post<any>(`/api/runs/${rid}/terminals`);sessionStorage.setItem(`phoenix.terminal.${rid}`,next.id);setSid(next.id);})}>打开新终端</button>{sid&&<button disabled={op.busy} onClick={()=>void op.act(async()=>{await api(`/api/runs/${rid}/terminals/${sid}`,{method:"DELETE"});sessionStorage.removeItem(`phoenix.terminal.${rid}`);setSid("");})}>关闭终端</button>}</div></ToolHeader>
  <div className="px-terminal-tab"><SquareTerminal size={14}/><span>{sid ? "bash · /work" : "未连接"}</span><Badge tone={sid?"green":"muted"}>{sid?"PTY 已连接":"等待连接"}</Badge><code>{sid}</code></div>{op.error&&<div role="alert" className="px-error">{op.error}</div>}
  <div className="px-fusion-terminal" ref={host}>{!sid&&<div className="px-empty">打开终端以连接本轮工作区</div>}</div>
 </section>;
}

