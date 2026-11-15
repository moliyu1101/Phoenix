"use client";
import {useState} from "react";
import {Plus,RefreshCw,Trash2,Play,Power,Package,Plug,Zap,Check,Settings2,Wrench} from "lucide-react";
import {api,post,patch,useResource} from "@/lib/phoenix";
import {Badge,Empty,ToolHeader,useOperation} from "./fusion/Workbench";
import {ConfigModal} from "./fusion/ConfigModal";

const TRANSPORTS:[string,string][]=[["stdio","Stdio 本地进程"],["streamable-http","Streamable HTTP"],["sse","SSE 远程"]];
const STATE:Record<string,{label:string;tone:string}>={healthy:{label:"健康",tone:"green"},error:{label:"异常",tone:"amber"},unknown:{label:"未探测",tone:"muted"}};
const EMPTY_SERVER={editingId:"",name:"",transport:"stdio",command:"",args:"",cwd:"",url:"",timeout:"15",envText:"",headerText:""};

function parseMap(text:string,label:string):Record<string,string>{
 if(!text.trim())return {};
 let value:any;
 try{value=JSON.parse(text);}catch{throw new Error(`${label} 必须是合法的 JSON 对象`);}
 if(!value||typeof value!=="object"||Array.isArray(value))throw new Error(`${label} 必须是 JSON 对象`);
 const out:Record<string,string>={};
 for(const [k,v] of Object.entries(value)){if(typeof v!=="string")throw new Error(`${label} 的值必须都是字符串`);out[k]=v;}
 return out;
}

export function PhoenixExtensions(){
 const op=useOperation();
 const overview=useResource<any>("/api/extensions/overview",5000);
 const servers=useResource<any>("/api/extensions/mcp-servers",5000);
 const plugins=useResource<any>("/api/extensions/plugins",5000);
 const tools=useResource<any>("/api/extensions/tools",5000);
 const [notice,setNotice]=useState("");
 const [serverModal,setServerModal]=useState(false),[serverForm,setServerForm]=useState({...EMPTY_SERVER});
 const [pluginModal,setPluginModal]=useState(false),[pluginName,setPluginName]=useState(""),[manifestText,setManifestText]=useState(""),[pluginPath,setPluginPath]=useState("");
 const [callModal,setCallModal]=useState(false),[callSid,setCallSid]=useState(""),[callTool,setCallTool]=useState(""),[argsText,setArgsText]=useState("{}"),[callRun,setCallRun]=useState(""),[callTask,setCallTask]=useState(""),[callResult,setCallResult]=useState<any>(null);
 const serverList:any[]=servers.data?.servers||[],pluginList:any[]=plugins.data?.plugins||[],toolList:any[]=tools.data?.tools||[];
 const ov=overview.data;
 const callServer=serverList.find(s=>s.id===callSid);
 function refreshAll(){void overview.refresh();void servers.refresh();void plugins.refresh();void tools.refresh();}
 function openServer(row?:any){
  if(row){const c=row.config||{};setServerForm({editingId:row.id,name:row.name,transport:row.transport,command:c.command||"",args:(c.args||[]).join("\n"),cwd:c.cwd||"",url:c.url||"",timeout:String(c.timeout??15),envText:"",headerText:""});}
  else setServerForm({...EMPTY_SERVER});
  setServerModal(true);
 }
 async function saveServer(){
  await op.act(async()=>{
   const f=serverForm;
   const config:any={timeout:Number(f.timeout)||15};
   if(f.transport==="stdio"){config.command=f.command.trim();config.args=f.args.split("\n").map(s=>s.trim()).filter(Boolean);config.cwd=f.cwd.trim();const env=parseMap(f.envText,"环境变量");if(Object.keys(env).length||!f.editingId)config.env=env;}
   else{config.url=f.url.trim();const headers=parseMap(f.headerText,"请求头");if(Object.keys(headers).length||!f.editingId)config.headers=headers;}
   if(f.editingId){await patch(`/api/extensions/mcp-servers/${f.editingId}`,{name:f.name.trim(),transport:f.transport,config});setNotice("MCP 服务器已更新。");}
   else{await post("/api/extensions/mcp-servers",{name:f.name.trim(),transport:f.transport,config,enabled:false});setNotice("MCP 服务器已创建，探测后即可启用。");}
   setServerModal(false);refreshAll();
  });
 }
 async function savePlugin(){
  await op.act(async()=>{
   const body:any={enabled:false};
   if(pluginName.trim())body.name=pluginName.trim();
   if(pluginPath.trim())body.path=pluginPath.trim();
   else{let manifest:any;try{manifest=JSON.parse(manifestText);}catch{throw new Error("插件清单必须是合法的 JSON 对象");}body.manifest=manifest;}
   await post("/api/extensions/plugins",body);setPluginModal(false);setPluginName("");setManifestText("");setPluginPath("");setNotice("插件已注册。");refreshAll();
  });
 }
 async function invokeTool(){
  await op.act(async()=>{
   let args:any;try{args=JSON.parse(argsText||"{}");}catch{throw new Error("调用参数必须是合法的 JSON 对象");}
   const body:any={name:callTool,arguments:args};
   if(callRun.trim())body.run_id=callRun.trim();
   if(callTask.trim())body.task_id=callTask.trim();
   setCallResult(await post(`/api/extensions/mcp-servers/${callSid}/call`,body));setNotice("工具调用完成。");
  });
 }
 const secretHint=(keys:string[],label:string)=>keys?.length?`当前${label}键：${keys.join("、")}（留空保持原值，输入 JSON 覆盖）`:`${label}为 JSON 对象，例如 {"TOKEN":"…"}`;
 return <div className="px-fusion-panel px-integration-workspace px-ext-workspace">
  <ToolHeader icon={<Package size={20}/>} title="扩展与 MCP" description="管理 MCP 服务器与智能体插件；启用并探测后，其工具会进入蜂群工具总线并记录证据。">
   <button className="px-tool-primary" onClick={()=>openServer()}><Plus size={14}/>新建 MCP 服务器</button>
   <button onClick={()=>{setPluginName("");setManifestText("");setPluginPath("");setPluginModal(true);}}><Plus size={14}/>注册插件</button>
  </ToolHeader>
  {(op.error||servers.error||plugins.error||overview.error)&&<div role="alert" className="px-error">{op.error||servers.error||plugins.error||overview.error}</div>}
  {notice&&<p className="px-tool-notice" role="status"><Check size={14}/>{notice}</p>}
  {ov&&<div className="px-tool-summary">
   <span>MCP SDK<b>{ov.sdk==="mcp"?"已就绪":"未安装"}</b></span>
   <span>服务器<b>{ov.mcp_servers.total}</b></span>
   <span>已启用<b>{ov.mcp_servers.enabled}</b></span>
   <span>健康<b>{ov.mcp_servers.healthy}</b></span>
   <span>插件<b>{ov.plugins.total}</b></span>
   <span>暴露工具<b>{ov.tools}</b></span>
  </div>}
  <section>
   <h3 className="px-ext-section"><Plug size={16}/>MCP 服务器</h3>
   <div className="px-tool-table-scroll"><table className="px-admin-table"><thead><tr><th>名称</th><th>传输</th><th>状态</th><th>工具</th><th>启用</th><th>操作</th></tr></thead><tbody>{serverList.map(s=>{const st=STATE[s.state]||STATE.unknown;return <tr key={s.id}>
    <td><strong>{s.name}</strong><small>{s.id}</small>{s.error&&<div className="px-ext-error">{s.error}</div>}</td>
    <td><Badge tone="blue">{(TRANSPORTS.find(t=>t[0]===s.transport)||[s.transport,s.transport])[1]}</Badge></td>
    <td><Badge tone={st.tone}>{st.label}</Badge>{s.last_probe&&<small>{new Date(s.last_probe*1000).toLocaleString("zh-CN")}</small>}</td>
    <td>{s.tool_count}</td>
    <td><button disabled={op.busy} aria-label={`启用 ${s.name}`} onClick={()=>void op.act(async()=>{await post(`/api/extensions/mcp-servers/${s.id}/enabled`,{enabled:!s.enabled});refreshAll();})}><Power size={13}/>{s.enabled?"已启用":"已停用"}</button></td>
    <td><div className="px-ext-actions">
     <button disabled={op.busy} onClick={()=>void op.act(async()=>{const r=await post<any>(`/api/extensions/mcp-servers/${s.id}/probe`);refreshAll();setNotice(r.state==="healthy"?`探测成功，发现 ${r.tool_count} 个工具。`:`探测失败：${r.error}`);})}><RefreshCw size={13}/>探测</button>
     <button disabled={op.busy||!s.enabled||s.state!=="healthy"||!s.tool_count} onClick={()=>{setCallSid(s.id);setCallTool(s.tools?.[0]?.name||"");setArgsText("{}");setCallRun("");setCallTask("");setCallResult(null);setCallModal(true);}}><Play size={13}/>调用</button>
     <button disabled={op.busy} onClick={()=>openServer(s)}><Settings2 size={13}/>编辑</button>
     <button disabled={op.busy} aria-label={`删除 ${s.name}`} onClick={()=>void op.act(async()=>{await api(`/api/extensions/mcp-servers/${s.id}`,{method:"DELETE"});refreshAll();setNotice("MCP 服务器已删除。");})}><Trash2 size={13}/></button>
    </div></td>
   </tr>;})}</tbody></table></div>
   {!serverList.length&&<Empty title={servers.loading?"读取 MCP 服务器…":"还没有 MCP 服务器"}>新建 stdio 或远程 MCP 服务器，探测发现工具后启用，即可在解题中调用。<button onClick={()=>openServer()}><Plus size={14}/>新建 MCP 服务器</button></Empty>}
  </section>
  <section>
   <h3 className="px-ext-section"><Package size={16}/>智能体插件</h3>
   <div className="px-tool-table-scroll"><table className="px-admin-table"><thead><tr><th>名称</th><th>来源</th><th>诊断</th><th>启用</th><th>操作</th></tr></thead><tbody>{pluginList.map(p=><tr key={p.id}>
    <td><strong>{p.name}</strong><small>{p.manifest?.version||""}</small></td>
    <td>{p.source?<span className="px-ext-source">{p.source}</span>:<Badge>清单注册</Badge>}</td>
    <td>{p.diagnostics?.length?<Badge tone="amber">{p.diagnostics.length} 条</Badge>:<Badge tone="green">正常</Badge>}</td>
    <td><button disabled={op.busy} aria-label={`启用 ${p.name}`} onClick={()=>void op.act(async()=>{await post(`/api/extensions/plugins/${p.id}/enabled`,{enabled:!p.enabled});refreshAll();})}><Power size={13}/>{p.enabled?"已启用":"已停用"}</button></td>
    <td><button disabled={op.busy} aria-label={`删除 ${p.name}`} onClick={()=>void op.act(async()=>{await api(`/api/extensions/plugins/${p.id}`,{method:"DELETE"});refreshAll();setNotice("插件已删除。");})}><Trash2 size={13}/>删除</button></td>
   </tr>)}</tbody></table></div>
   {!pluginList.length&&<Empty title={plugins.loading?"读取插件…":"还没有注册插件"}>通过 plugin.json 包路径或清单对象注册智能体插件。</Empty>}
  </section>
  <section>
   <h3 className="px-ext-section"><Wrench size={16}/>暴露给蜂群的工具 · {toolList.length}</h3>
   {toolList.length?<ul className="px-ext-tools">{toolList.map(t=><li key={t.function.name}><code>{t.function.name}</code><span>{t.function.description}</span></li>)}</ul>:<p className="px-ext-empty">启用并探测健康的 MCP 服务器后，其工具会出现在这里。</p>}
  </section>
  <ConfigModal open={serverModal} onClose={()=>setServerModal(false)} title={serverForm.editingId?"编辑 MCP 服务器":"新建 MCP 服务器"}>
   <form className="px-tool-form" onSubmit={e=>{e.preventDefault();void saveServer();}}>
    <label>名称<input required aria-label="服务器名称" value={serverForm.name} onChange={e=>setServerForm({...serverForm,name:e.target.value})} placeholder="例如：filesystem"/></label>
    <label>传输方式<select aria-label="传输方式" value={serverForm.transport} onChange={e=>setServerForm({...serverForm,transport:e.target.value})}>{TRANSPORTS.map(([v,l])=><option key={v} value={v}>{l}</option>)}</select></label>
    {serverForm.transport==="stdio"?<>
     <label>启动命令<input required aria-label="启动命令" value={serverForm.command} onChange={e=>setServerForm({...serverForm,command:e.target.value})} placeholder="npx 或可执行文件路径"/></label>
     <label>参数（每行一个）<textarea rows={3} aria-label="启动参数" value={serverForm.args} onChange={e=>setServerForm({...serverForm,args:e.target.value})} placeholder={"-y\n@modelcontextprotocol/server-filesystem"}/></label>
     <label>工作目录<input aria-label="工作目录" value={serverForm.cwd} onChange={e=>setServerForm({...serverForm,cwd:e.target.value})} placeholder="可留空"/></label>
     <label>环境变量（JSON，密钥不回显）<textarea rows={3} aria-label="环境变量" value={serverForm.envText} onChange={e=>setServerForm({...serverForm,envText:e.target.value})} placeholder={secretHint(serverList.find(s=>s.id===serverForm.editingId)?.config?.env_keys||[],"环境变量")}/></label>
    </>:<>
     <label>服务地址<input required type="url" aria-label="服务地址" value={serverForm.url} onChange={e=>setServerForm({...serverForm,url:e.target.value})} placeholder="https://example.com/mcp"/></label>
     <label>请求头（JSON，密钥不回显）<textarea rows={3} aria-label="请求头" value={serverForm.headerText} onChange={e=>setServerForm({...serverForm,headerText:e.target.value})} placeholder={secretHint(serverList.find(s=>s.id===serverForm.editingId)?.config?.header_keys||[],"请求头")}/></label>
    </>}
    <label>超时（秒）<input type="number" min={1} max={120} aria-label="超时秒数" value={serverForm.timeout} onChange={e=>setServerForm({...serverForm,timeout:e.target.value})}/></label>
    {op.error&&<div role="alert" className="px-error">{op.error}</div>}
    <div className="px-modal-footer"><button type="button" onClick={()=>setServerModal(false)}>取消</button><button className="px-tool-primary" disabled={op.busy||!serverForm.name.trim()}>{serverForm.editingId?"保存修改":"创建服务器"}</button></div>
   </form>
  </ConfigModal>
  <ConfigModal open={pluginModal} onClose={()=>setPluginModal(false)} title="注册智能体插件">
   <form className="px-tool-form" onSubmit={e=>{e.preventDefault();void savePlugin();}}>
    <label>插件名称（可留空，取清单 name）<input aria-label="插件名称" value={pluginName} onChange={e=>setPluginName(e.target.value)} placeholder="例如：demo-plugin"/></label>
    <label>plugin.json 包路径<input aria-label="包路径" value={pluginPath} onChange={e=>setPluginPath(e.target.value)} placeholder="留空则使用下方清单对象"/></label>
    <label>清单对象（JSON）<textarea rows={6} aria-label="插件清单" value={manifestText} onChange={e=>setManifestText(e.target.value)} placeholder={'{"name":"demo","version":"1.0.0","description":"演示插件"}'}/></label>
    {op.error&&<div role="alert" className="px-error">{op.error}</div>}
    <div className="px-modal-footer"><button type="button" onClick={()=>setPluginModal(false)}>取消</button><button className="px-tool-primary" disabled={op.busy||(!pluginPath.trim()&&!manifestText.trim())}>注册插件</button></div>
   </form>
  </ConfigModal>
  <ConfigModal open={callModal} onClose={()=>setCallModal(false)} title="调用 MCP 工具">
   <form className="px-tool-form" onSubmit={e=>{e.preventDefault();void invokeTool();}}>
    <label>工具<select required aria-label="选择工具" value={callTool} onChange={e=>setCallTool(e.target.value)}>{(callServer?.tools||[]).map((t:any)=><option key={t.name} value={t.name}>{t.name}</option>)}</select></label>
    <label>参数（JSON）<textarea rows={5} aria-label="调用参数" value={argsText} onChange={e=>setArgsText(e.target.value)}/></label>
    <div className="px-form-row"><label>绑定运行（可选，记录证据）<input aria-label="运行 ID" value={callRun} onChange={e=>setCallRun(e.target.value)} placeholder="run_…"/></label><label>绑定任务（可选）<input aria-label="任务 ID" value={callTask} onChange={e=>setCallTask(e.target.value)} placeholder="task_…"/></label></div>
    {callResult&&<pre className="px-fusion-output">{JSON.stringify(callResult,null,2)}</pre>}
    {op.error&&<div role="alert" className="px-error">{op.error}</div>}
    <div className="px-modal-footer"><button type="button" onClick={()=>setCallModal(false)}>关闭</button><button className="px-tool-primary" disabled={op.busy||!callTool}><Zap size={14}/>调用工具</button></div>
   </form>
  </ConfigModal>
 </div>;
}