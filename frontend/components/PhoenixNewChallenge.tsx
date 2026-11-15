"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useId, useRef, useState } from "react";
import { Welcome } from "./Conversation";
import { Icon } from "./Icon";
import { useT } from "@/lib/i18n";
import { matchesBinding, shortcutBinding, isMacPlatform } from "@/lib/shortcutBindings";
import { setThemePreference } from "@/lib/themePreference";
import { post, useResource, categoryLabels } from "@/lib/phoenix";

async function readBase64(file:File):Promise<string> {
  if(file.size>32*1024*1024)throw new Error("单个附件不得超过 32 MiB");
  return new Promise((resolve,reject)=>{const reader=new FileReader();reader.onerror=()=>reject(new Error("附件读取失败"));reader.onload=()=>resolve(String(reader.result).split(",")[1]);reader.readAsDataURL(file);});
}

export function NewChallenge({refresh,onToggleSidebar}:{refresh:()=>void;onToggleSidebar:()=>void}) {
  const t=useT(), router=useRouter(), catalog=useResource<any>("/api/swarm/catalog",0), draftId=useId().replace(/[^a-zA-Z0-9]/g,"");
  const [description,setDescription]=useState(""),[title,setTitle]=useState(""),[category,setCategory]=useState("misc"),[targets,setTargets]=useState("");
  const [files,setFiles]=useState<File[]>([]),[advanced,setAdvanced]=useState(false),[workers,setWorkers]=useState<string[]>([]);
  const [concurrency,setConcurrency]=useState(4),[maxTokens,setMaxTokens]=useState(120000),[wall,setWall]=useState(1200),[autoDistill,setAutoDistill]=useState(true);
  const [busy,setBusy]=useState(false),[error,setError]=useState("");
  const input=useRef<HTMLTextAreaElement>(null),upload=useRef<HTMLInputElement>(null);
  useEffect(()=>{const onKey=(e:KeyboardEvent)=>{if(!(e.target as HTMLElement)?.closest("input,textarea,select")&&matchesBinding(e,shortcutBinding("focusComposer"),isMacPlatform())){e.preventDefault();input.current?.focus();}};window.addEventListener("keydown",onKey);return()=>window.removeEventListener("keydown",onKey);},[]);
  async function dispatch() {
    if(busy || !description.trim())return;
    setError("");
    if(catalog.data && !Object.values(catalog.data.profiles).some((p:any)=>p.model)) {setError("模型尚未配置，请先在设置中查看配置方式；也可运行无费用蜂群演示。");return;}
    if(files.reduce((n,f)=>n+f.size,0)>128*1024*1024){setError("附件总大小不得超过 128 MiB");return;}
    setBusy(true);
    try{
      const challenge=await post("/api/challenges",{title:title.trim() || description.trim().split("\n")[0].slice(0,100),description,category,
        targets:targets.split(/\n+/).map(s=>s.trim()).filter(Boolean),authorized:true});
      for(const file of files)await post(`/api/challenges/${challenge.id}/files`,{name:file.name,data_base64:await readBase64(file)});
      const run=await post(`/api/challenges/${challenge.id}/runs`,{concurrency,worker_ids:workers,auto_distill:autoDistill,budget:{max_tokens:maxTokens,wall_seconds:wall}});
      refresh();router.push(`/run/${run.id}`);
    }catch(e){setError((e as Error).message);}finally{setBusy(false);}
  }
  async function demo(){setBusy(true);setError("");try{const run=await post("/api/swarm-demo");refresh();router.push(`/run/${run.id}`);}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
  function addFiles(selected:File[]){setFiles(old=>[...new Map([...old,...selected].map(f=>[f.name,f])).values()]);}
  const configured=Object.values(catalog.data?.profiles || {}).filter((p:any)=>p.model).length;
  return <div className="convo px-phoenix-draft">
    <header className="convo-top"><button className="icon-btn" aria-label="展开题目侧栏" onClick={onToggleSidebar}><Icon name="menu" size={17}/></button><div className="convo-top-context"><h1 className="title">新建解题</h1><code className="rid">sessions/draft-{draftId}</code></div><div className="convo-top-controls"><Link className="px-model-count" href="/settings" title="模型配置"><i/>{configured}</Link><button className="icon-btn" aria-label="切换明暗主题" onClick={()=>setThemePreference(document.documentElement.dataset.theme==="dark"?"light":"dark")}><Icon name="moon" size={15}/></button></div></header>
    <div className="px-draft-scroll"><div className="px-draft-center">
      <Welcome t={t} onChoose={prefill=>{setDescription(prefill.text);const i=["ex1","ex2","ex3"].findIndex(k=>t(`welcome.${k}.prompt`)===prefill.text);setCategory(["web","crypto","pwn"][i] || "misc");input.current?.focus();}}/>
      <form className="composer2 px-draft-composer" onSubmit={e=>{e.preventDefault();void dispatch();}} onDragOver={e=>e.preventDefault()} onDrop={e=>{e.preventDefault();addFiles(Array.from(e.dataTransfer.files));}}>
        <div className="wrap"><textarea ref={input} aria-label="描述一道题" placeholder="描述一道题 —— 粘贴题面、一个地址，或附件说明。题目原文进入蜂群，规划器根据完整题面规划分工。" rows={2} maxLength={24000} value={description} onChange={e=>setDescription(e.target.value)} onKeyDown={e=>{if((e.ctrlKey || e.metaKey)&&e.key==="Enter"){e.preventDefault();void dispatch();}}}/>
          {!!files.length && <div className="attach-row">{files.map(f=><span className="attach-chip" key={f.name}><Icon name="file" size={12}/><span>{f.name}</span><button type="button" aria-label={`移除 ${f.name}`} onClick={()=>setFiles(files.filter(x=>x!==f))}><Icon name="x" size={12}/></button></span>)}</div>}
          <div className="crow"><button className="px-text-button" type="button" aria-label="添加附件" onClick={()=>upload.current?.click()}><Icon name="paperclip" size={17}/></button><input ref={upload} type="file" multiple hidden onChange={e=>addFiles(Array.from(e.target.files||[]))}/><span className="px-draft-explainer">题目原文进入 Phoenix · 独立智能体共享证据</span><span className="spacer"/><span className="chip"><Icon name="flag" size={12}/>单个答案</span><button className="chip" type="button" onClick={()=>setAdvanced(!advanced)}><Icon name={targets.trim()?"globe":"folder"} size={12}/>{targets.trim()?"题目目标":"本地附件"}</button><button className="chip" type="button" aria-expanded={advanced} aria-controls="draft-advanced" onClick={()=>setAdvanced(!advanced)}><Icon name="gear" size={12}/>高级<Icon name="chevronDown" size={11}/></button><button className="send" type="submit" aria-label="开始解题" disabled={busy||!description.trim()}><Icon name="send" size={16}/></button></div>
        </div>
        <div className="px-draft-foot"><span>题面、附件与目标将进入同一解题工作区</span><span>Ctrl + Enter 派发</span><button type="button" onClick={()=>void demo()} disabled={busy}>无费用蜂群演示</button></div>
        {error && <div className="px-error" role="alert">{error} <Link href="/settings">模型配置 →</Link></div>}
        {advanced && <div id="draft-advanced" className="px-draft-advanced px-composer"><div className="px-form-row"><label>题目名称（留空则取题面首行）<input value={title} onChange={e=>setTitle(e.target.value)} maxLength={180}/></label><label>题型<select value={category} onChange={e=>{setCategory(e.target.value);setWorkers([]);}}>{Object.entries(categoryLabels).map(([key,name])=><option key={key} value={key}>{name}</option>)}</select></label></div><label>题目目标（每行一个精确源站地址）<textarea rows={2} value={targets} onChange={e=>setTargets(e.target.value)} placeholder="http://challenge.example:8080 或 tcp://challenge.example:31337"/></label><div className="px-form-row px-three"><label>并行 智能体 上限<input type="number" min={1} max={16} value={concurrency} onChange={e=>setConcurrency(Number(e.target.value))}/></label><label>词元 预算<input type="number" min={500} max={10000000} value={maxTokens} onChange={e=>setMaxTokens(Number(e.target.value))}/></label><label>总时限（秒）<input type="number" min={10} max={86400} value={wall} onChange={e=>setWall(Number(e.target.value))}/></label></div><div className="px-worker-select">{(catalog.data?.workers || []).filter((w:any)=>w.enabled&&(!w.categories.length||w.categories.includes(category))).map((w:any)=><label className="px-check" key={w.id}><input type="checkbox" checked={workers.includes(w.id)} onChange={e=>setWorkers(e.target.checked?[...workers,w.id]:workers.filter(id=>id!==w.id))}/>{w.name}</label>)}</div><label className="px-check"><input type="checkbox" checked={autoDistill} onChange={e=>setAutoDistill(e.target.checked)}/>结束后蒸馏经验草稿（使用本轮剩余预算）</label></div>}
      </form>
    </div></div>
  </div>;
}
