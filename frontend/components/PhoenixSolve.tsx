"use client";
import {uiLabel,roleLabels,workerDisplayName,localizedError} from "@/lib/phoenix-labels";

import dynamic from "next/dynamic";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode, type KeyboardEvent } from "react";
import { Icon, type IconName } from "./Icon";
import { RunSignalsStrip } from "./RunSignalsStrip";
import { PhoenixRunTools } from "./PhoenixRunTools";
import { PhoenixActivityTimeline } from "./PhoenixActivityTimeline";
import { api, post, patch, parse, useResource, useRunEvents, download, isActive, canResume, label, fmtDate } from "@/lib/phoenix";
import { projectPhoenix } from "@/lib/phoenixProjection";
import { eventPresentation, usePhoenixTimeline, type NativeEvent } from "@/lib/phoenixTimeline";
import { matchesBinding, shortcutBinding, isMacPlatform } from "@/lib/shortcutBindings";
import { applyConversationReadingPrefsToElement, subscribeConversationReadingPrefs } from "@/lib/conversationReadingPrefs";
import { setThemePreference } from "@/lib/themePreference";

// Keep Phoenix's actual canvas and interaction model, with a native Phoenix projection.
const Collaboration = dynamic(() => import("./AgentCollaborationCanvas").then(m => m.AgentCollaborationCanvas), { ssr: false, loading: () => <div className="px-empty">正在载入协作图…</div> });
const MessageMarkdown = dynamic(() => import("./ai-native/message-markdown").then(m => m.MessageMarkdown), { ssr: false, loading: () => <div className="px-empty">正在载入复盘…</div> });
type View = "conversation" | "runtime" | "graph";
type RuntimeView = "sandbox" | "terminal" | "browser" | "assets" | "traffic" | "approvals" | "engines" | "timeline" | "workers" | "usage" | "tasks" | "facts" | "evidence" | "files";
const views: [View, string, IconName][] = [["conversation", "对话", "rows"], ["runtime", "运行时", "panel"], ["graph", "协作图", "network"]];
const runtimeViews: [RuntimeView, string, IconName][] = [["sandbox","题目沙箱","cpu"],["terminal","终端","terminal"],["browser","浏览器","globe"],["assets","资产与覆盖","layers"],["traffic","HTTP 流量","radio"],["approvals","拦截审批","checkCircle"],["engines","执行引擎","bot"],["timeline", "活动时间线", "list"], ["workers", "智能体详情", "grid"], ["usage", "用量", "rows"], ["tasks", "协作任务", "listTodo"], ["facts", "共享黑板", "checkCircle"], ["evidence", "工具证据", "terminal"], ["files", "工作区文件", "folder"]];
const conversational = new Set(["operator.message", "plan.added", "worker.message", "worker.finished", "fact.created", "run.created", "run.started", "run.state", "worker.error", "planner.error", "flag.verified", "flag.operator_receipt", "run.continued"]);

function Section({ title, badge, children }: { title: string; badge?: ReactNode; children: ReactNode }) {
  return <details className="insp-sec px-info-section" open><summary><span>{title}</span>{badge}<Icon name="chevronUp" size={13} /></summary>{children}</details>;
}

// A stable component type keeps existing journal entries mounted during polling
// and composer edits, so Phoenix's entrance animation only runs for new entries.
function EventRow({ event, workerName, onWorkerSelect, onInspect }: {
  event: NativeEvent;
  workerName?: string;
  onWorkerSelect: (worker: string) => void;
  onInspect: (evidenceId: string) => Promise<void>;
}) {
  const p = eventPresentation(event), worker = event.worker_id || event.payload.worker_id;
  const evidenceId = event.kind === "evidence.created" ? event.payload.id : null;
  return <article className={`coord-bubble ${p.bubble ? "px-event-bubble" : "system status"} ${event.kind === "operator.message" ? "human" : ""} ${event.kind.includes("error") ? "px-event-error" : ""}`} data-event-seq={event.seq}>
    <span className="coord-node" aria-hidden="true"><Icon name={p.icon as IconName} size={12} /></span>
    <div className="who">{worker && <button className="px-worker-link" onClick={() => onWorkerSelect(worker)}>{workerName || worker}</button>}<span>{p.title}</span><time className="ts" dateTime={new Date(event.created*1000).toISOString()}>{new Date(event.created*1000).toLocaleTimeString("zh-CN",{hour12:false})}</time></div>
    <div className="body">{p.text}</div>
    {evidenceId && <button className="px-text-button" onClick={() => void onInspect(evidenceId)}><Icon name="fileSearch" size={12} />{evidenceId} →</button>}
  </article>;
}

export function RunView({ rid, onRefresh, onToggleSidebar }: { rid: string; onRefresh: () => void; onToggleSidebar?: () => void }) {
  const router = useRouter();
  const detail = useResource<any>(`/api/runs/${rid}`, 5000), swarm = useResource<any>(`/api/runs/${rid}/swarm`, 5000);
  const challenge = useResource<any>(detail.data ? `/api/challenges/${detail.data.run.challenge_id}` : null, 0);
  const files = useResource<any>(`/api/runs/${rid}/workspace`, 7000), catalog = useResource<any>("/api/swarm/catalog", 0);
  const timeline = usePhoenixTimeline(rid);
  const { refresh: refreshDetail } = detail, { refresh: refreshSwarm } = swarm, { refresh: refreshFiles } = files, { refresh: refreshTimeline } = timeline;
  const refresh = useCallback(() => { void refreshDetail(); void refreshSwarm(); void refreshFiles(); void refreshTimeline(); onRefresh(); }, [refreshDetail, refreshSwarm, refreshFiles, refreshTimeline, onRefresh]);
  useRunEvents(rid, refresh);
  const [view, setView] = useState<View>("conversation"), [runtimeView, setRuntimeView] = useState<RuntimeView>("timeline");
  const [runtimeInspector, setRuntimeInspector] = useState(false);
  const [inspectorOpen, setInspectorOpen] = useState(true), [focused, setFocused] = useState("");
  const [error, setError] = useState(""), [busy, setBusy] = useState(false), [modal, setModal] = useState<any>(null);
  const [draft, setDraft] = useState(""), [notice, setNotice] = useState("");
  const [add, setAdd] = useState(false), [workerName, setWorkerName] = useState("智能体"), [role, setRole] = useState("solver"), [profile, setProfile] = useState("");
  const [elapsed, setElapsed] = useState(0), [following, setFollowing] = useState(true);
  const scroll = useRef<HTMLDivElement>(null), textarea = useRef<HTMLTextAreaElement>(null);
  const deck = useMemo(() => detail.data ? projectPhoenix({ ...detail.data, events: [...timeline.items].reverse() }, swarm.data, challenge.data) : null, [detail.data, swarm.data, challenge.data, timeline.items]);
  useEffect(() => {
    function readView() {
      const url = new URL(window.location.href);
      const next = url.searchParams.get("view") || (url.pathname.endsWith("/collaboration") ? "graph" : null);
      setView(next === "collaboration" || next === "graph" ? "graph" : next === "runtime" ? "runtime" : "conversation");
    }
    readView(); window.addEventListener("popstate", readView);
    return () => window.removeEventListener("popstate", readView);
  }, []);
  useEffect(() => {
    if (!detail.data) return;
    const r = detail.data.run;
    const tick = () => setElapsed(Math.max(0, Math.floor((isActive(r.state) ? Date.now()/1000 : r.updated) - r.created)));
    tick(); const id = setInterval(tick, 1000); return () => clearInterval(id);
  }, [detail.data]);
  useEffect(() => { if (following && scroll.current) scroll.current.scrollTop = scroll.current.scrollHeight; }, [timeline.items, following, view]);

  useEffect(()=>{const onKey=(e:globalThis.KeyboardEvent)=>{if(e.defaultPrevented)return;const editable=(e.target as HTMLElement)?.closest("input,textarea,select,[contenteditable=true]");const match=(id:Parameters<typeof shortcutBinding>[0])=>matchesBinding(e,shortcutBinding(id),isMacPlatform());if(!editable&&match("focusComposer")){e.preventDefault();setView("conversation");requestAnimationFrame(()=>textarea.current?.focus());}else if(match("togglePanel")||match("toggleLog")){e.preventDefault();setView(v=>v==="runtime"?"conversation":"runtime");setRuntimeView("timeline");}else if(match("panelFiles")){e.preventDefault();setView("runtime");setRuntimeView("files");}else if(match("panelAgents")){e.preventDefault();setView("runtime");setRuntimeView("workers");}};window.addEventListener("keydown",onKey);return()=>window.removeEventListener("keydown",onKey);},[]);
  useEffect(()=>{const apply=()=>applyConversationReadingPrefsToElement(scroll.current?.closest(".px-solve") as HTMLElement|null);apply();return subscribeConversationReadingPrefs(apply);},[view]);
  function selectView(next: View) {
    setView(next);
    const url = new URL(window.location.href); url.searchParams.set("view", next === "graph" ? "collaboration" : next);
    window.history.replaceState(null, "", url);
  }
  function openRuntime(next: RuntimeView, worker = "") { setRuntimeView(next); setFocused(worker); selectView("runtime"); }
  async function action(fn: () => Promise<any>) {
    setBusy(true); setError("");
    try { await fn(); refresh(); } catch (e) { setError(localizedError(e)); } finally { setBusy(false); }
  }
  async function inspect(eid: string) { await action(async () => setModal({ title: "原始工具证据", value: await api(`/api/runs/${rid}/evidence/${eid}?length=32000`) })); }
  async function generateWriteup() {
    const paid = detail.data.run.mode === "live";
    if (paid && !window.confirm("生成复盘将调用模型并可能产生 API 费用，是否继续？")) return;
    await action(async () => setModal({ title: "复盘题解", writeup: await post(`/api/runs/${rid}/writeup`, { confirm_paid: paid }) }));
  }
  async function openWriteup() {
    await action(async () => {
      try { setModal({ title: "复盘题解", writeup: await api(`/api/runs/${rid}/writeup`) }); }
      catch (e) { if ((e as any).status === 404) setNotice("尚未生成复盘，请先点击“生成复盘”。"); else throw e; }
    });
  }
  async function receipt(cid: string, accepted: boolean) {
    const text = window.prompt("请粘贴真实平台回执或独立复现说明（至少 8 字符）");
    if (text) await action(() => post(`/api/candidates/${cid}/receipt`, { accepted, receipt: text }));
  }
  async function send() {
    if (!draft.trim() || busy) return;
    await action(async () => {
      if (isActive(detail.data.run.state) || canResume(detail.data.run.state)) {
        await post(`/api/runs/${rid}/messages`, { content: draft.trim() });
        setDraft(""); setNotice("已保存，将在 规划器 / 智能体 的下一轮上下文中读取。"); setFollowing(true);
      } else {
        const next = await post(`/api/runs/${rid}/continue`, { content: draft.trim() });
        router.push(`/run/${next.id}`);
      }
    });
  }
  function tabKeys(e: KeyboardEvent, index: number) {
    let next = index;
    if (e.key === "ArrowRight") next = (index+1)%3;
    else if (e.key === "ArrowLeft") next = (index+2)%3;
    else if (e.key === "Home") next = 0;
    else if (e.key === "End") next = 2;
    else return;
    e.preventDefault(); selectView(views[next][0]); document.getElementById(`tab-${views[next][0]}`)?.focus();
  }
  if (!detail.data) return <div className="px-empty" role="status">{detail.error || "正在读取运行记录…"}</div>;
  const d = detail.data, run = d.run, s = swarm.data, ch = challenge.data;
  const active = isActive(run.state), resumable = canResume(run.state), editable = ["created", "running"].includes(run.state) || resumable;
  const tasks = s?.tasks || d.tasks;
  const accepted = d.candidates.filter((c: any) => c.status === "accepted").length;
  const costUnknown = !d.model_calls.length || d.model_calls.some((m: any) => m.cost_usd == null);
  const duration = `${Math.floor(elapsed/60)}:${String(elapsed%60).padStart(2,"0")}`;
  const canSend = editable || (run.mode === "live" && run.state !== "distilling");
  const names = new Map<string, string>((s?.workers || []).map((w: any) => [w.id, workerDisplayName(w.name)]));
  const visibleEvents = timeline.items.filter(e => conversational.has(e.kind));
  const inspectorVisible = view === "runtime" ? runtimeInspector : inspectorOpen;
  const group = ["timeline","workers","usage","engines"].includes(runtimeView) ? "observe" : ["files","sandbox","terminal","assets"].includes(runtimeView) ? "assets" : "investigate";

  const evidenceList = <>{d.evidence.map((e: any) => <button className="px-evidence-row" key={e.id} onClick={() => void inspect(e.id)}><span><strong>{uiLabel(e.tool)}</strong><code>{e.id}</code></span><small>{e.ok ? "成功" : "失败"}<br />{fmtDate(e.created)}</small></button>)}{d.evidence.length === 100 && <p className="px-muted">此索引显示最近 100 条；完整证据可从活动时间线打开。</p>}{!d.evidence.length && <div className="px-empty">尚无工具证据</div>}</>;
  const fileList = <>{files.error && <div className="px-error">{files.error}</div>}{["inputs", "artifacts"].map(area => <section key={area}><h3 className="px-files-heading">{area === "inputs" ? "题目附件" : "智能体 产物"}</h3>{(files.data?.[area] || []).map((f: any) => <button className="px-evidence-row" key={f.path} onClick={() => void action(async () => setModal({title: f.path, value: await api(`/api/runs/${rid}/workspace/read?area=${area === "inputs" ? "input" : "work"}&path=${encodeURIComponent(f.path)}`)}))}><span><Icon name="file" size={14} /> {f.path}</span><small>{f.size} B</small></button>)}{!files.data?.[area]?.length && <p className="px-muted">暂无文件</p>}</section>)}</>;

  return <div className="convo px-solve">
    <header className="convo-top">
      <button className="icon-btn" aria-label="展开题目侧栏" onClick={onToggleSidebar}><Icon name="menu" size={17} /></button>
      <div className="convo-top-context"><h1 className="title" title={ch?.title}>{ch?.title || rid}</h1><span className="cat">{ch?.category?uiLabel(ch.category):"题目"}</span><code className="rid" title={rid}>{rid}</code></div>
      <div className="convo-top-view"><div className="px-view-tabs" role="tablist" aria-label="解题视图">{views.map(([key, title, icon], i) => <button id={`tab-${key}`} role="tab" key={key} aria-selected={view === key} aria-controls="solve-panel" tabIndex={view === key ? 0 : -1} onKeyDown={e => tabKeys(e,i)} onClick={() => selectView(key)}><Icon name={icon} size={13} />{title}</button>)}</div></div>
      <div className="convo-top-controls"><span className="runstate"><span className={`runstate-dot ${active ? "live" : "done"}`} />{label(run.state)}</span><span className={`dot ${detail.error || timeline.error ? "off" : "on"}`} title="Phoenix 接口连接" /><button className="icon-btn" aria-label="切换运行信息" aria-expanded={inspectorVisible} onClick={() => view === "runtime" ? setRuntimeInspector(!runtimeInspector) : setInspectorOpen(!inspectorOpen)}><Icon name="panelRightClose" size={16} /></button><button className="icon-btn" aria-label="切换明暗主题" onClick={()=>setThemePreference(document.documentElement.dataset.theme === "dark" ? "light" : "dark")}><Icon name="moon" size={15}/></button></div>
    </header>
    {(error || detail.error || swarm.error || challenge.error || timeline.error) && <div className="px-error" role="alert">{error || detail.error || swarm.error || challenge.error || timeline.error}<button className="px-text-button" onClick={refresh}>重新连接</button></div>}
    <div className="px-solve-body">
      <section className="px-solve-main" id="solve-panel" role="tabpanel" aria-labelledby={`tab-${view}`}>
        {view === "conversation" && <>
        <div className="px-solve-status"><span><Icon name={run.state === "solved" ? "check" : active ? "activity" : "clock"} size={14} /><b>{label(run.state)}</b><span className="px-status-divider" />内部记录 {d.candidates.length} · 已确认 {accepted}/1</span><span>{run.mode !== "live" && <b className="px-warning">脚本化 演示</b>}<Icon name="clock" size={13} />{duration}<button onClick={() => openRuntime("tasks")}><Icon name="list" size={13} />流程</button></span></div>
        {deck && <RunSignalsStrip className="px-native-signals" deck={deck} nativeItems={{facts:d.facts.map((f:any)=>`待独立验证 · ${f.statement}`),flags:d.candidates.map((c:any)=>`${c.value} · ${label(c.status)}`)}} onOpenArtifact={panel=>panel === "collaboration" ? selectView("graph") : openRuntime(panel === "workers" ? "workers" : "evidence")} />}
        </>}

        {view === "conversation" && <>
          <div ref={scroll} className="px-thread-scroll" onScroll={() => { const el=scroll.current; if(el) setFollowing(el.scrollHeight-el.scrollTop-el.clientHeight<80); }}>
            <div className="coord-thread px-native-thread"><div className="coord-wrap">
              <article className="coord-bubble human px-original-prompt"><span className="coord-node"><Icon name="send" size={12} /></span><div className="who">你 <span className="k">消息</span><time className="ts">{fmtDate(run.created)}</time></div><div className="body">{ch?.description || "正在读取题面…"}{!!ch?.targets?.length && <p>目标： {ch.targets.join(", ")}</p>}</div>{ch?.files?.length > 0 && <button className="px-text-button" onClick={() => openRuntime("files")}><Icon name="paperclip" size={13} />{ch.files.map((f: any) => f.path).join(" · ")}</button>}</article>
              {visibleEvents.map(e => <EventRow key={e.seq} event={e} workerName={names.get(e.worker_id || e.payload.worker_id)} onWorkerSelect={worker => openRuntime("timeline", worker)} onInspect={inspect} />)}
              {!active && !resumable && <article className="coord-bubble answer"><span className="coord-node"><Icon name={accepted ? "check" : "clock"} size={12} /></span><div className="coord-digest-title">本轮结论</div><div className="body">{accepted ? `已确认 ${accepted} 个 Flag。` : "本次尚未得到已确认的 答案。"} {d.facts.length} 条共享发现，{tasks.filter((t:any) => t.state === "done").length}/{tasks.length} 项任务完成。<p className="px-muted">{localizedError(run.reason)}</p></div><button className="px-text-button" onClick={() => openRuntime("evidence")}>查看原始证据 →</button></article>}
            </div></div>
          </div>
          {!following && <button className="px-jump-latest" onClick={() => setFollowing(true)}><Icon name="arrowDown" size={13} />回到最新消息</button>}
          <form className="composer2 px-solve-composer" onSubmit={e => {e.preventDefault();void send();}}><div className="wrap"><div className="px-compose-row"><textarea ref={textarea} rows={1} maxLength={8000} value={draft} onChange={e => setDraft(e.target.value)} aria-label="向蜂群补充消息" placeholder={editable ? "输入要向解题智能体 追问的问题或补充的方向" : "补充下一轮的方向，继续做题"} onKeyDown={e => {if(e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing){e.preventDefault();void send();}}} /><button className="send" aria-label="发送消息" type="submit" disabled={busy || !draft.trim() || !canSend}><Icon name="send" size={16} /></button></div><div className="quick"><button className="primary" type="button" disabled={busy || run.mode !== "live" || active} onClick={() => { if(resumable) {if(window.confirm("已检查中断执行；恢复使用原预算与剩余时限。")) void action(() => post(`/api/runs/${rid}/resume`,{acknowledge_uncertain:true}));} else {setDraft(draft || "基于上一轮的发现继续求解，优先复现原始证据并探索未完成方向。"); textarea.current?.focus();} }}><Icon name="refresh" size={13} />继续做题</button><button type="button" onClick={() => textarea.current?.focus()}><Icon name="help" size={13} />补充 / 追问</button><button type="button" disabled={busy || active} title={active ? "运行结束后可生成复盘" : "调用模型生成中文题解"} onClick={() => void generateWriteup()}><Icon name="pencil" size={13} />生成复盘</button><button type="button" disabled={busy} onClick={() => void openWriteup()}><Icon name="rows" size={13} />查看复盘</button><span className="px-compose-hint">{run.mode !== "live" ? "脚本化演示 · 不调用真实模型" : editable ? "消息在下一轮上下文生效" : "继续做题将新建一轮，使用新的模型预算"}</span></div></div>{notice && <div className="px-compose-notice" role="status">{notice}</div>}</form>
        </>}

        {view === "runtime" && <div className="px-native-runtime"><div className="px-phoenix-runtime-nav"><nav className="px-runtime-groups" aria-label="运行时分类">{[["observe","轨迹","radio"],["investigate","调查","crosshair"],["assets","资产","layers"]].map(([key,title,icon])=><button key={key} aria-pressed={group===key} onClick={()=>{setRuntimeView(key==="observe"?"timeline":key==="investigate"?"evidence":"files");setFocused("");}}><Icon name={icon as IconName} size={14}/>{title}</button>)}</nav><nav className="px-runtime-nav" aria-label="运行时面板">{runtimeViews.filter(([key])=>group==="observe"?["timeline","workers","usage","engines"].includes(key):group==="assets"?["files","sandbox","terminal","assets"].includes(key):["evidence","facts","tasks","browser","traffic","approvals"].includes(key)).map(([key,title,icon]) => <button key={key} aria-current={runtimeView === key ? "page" : undefined} onClick={() => {setRuntimeView(key);setFocused("");}}><Icon name={icon} size={14}/>{title}{["timeline","workers"].includes(key)&&<small>{key==="timeline"?timeline.items.length:s?.workers.length||0}</small>}</button>)}</nav>{runtimeView==="timeline"&&<select className="px-runtime-worker-filter" aria-label="筛选智能体" value={focused} onChange={e=>setFocused(e.target.value)}><option value="">全部执行单元</option>{(s?.workers||[]).map((w:any)=><option key={w.id} value={w.id}>{workerDisplayName(w.name)}</option>)}</select>}</div>
          {runtimeView === "timeline" && <PhoenixActivityTimeline detail={d} swarm={s} challenge={ch} events={timeline.items} worker={focused}/>}
          {runtimeView !== "timeline" && <div className="px-runtime-content">
            {["sandbox","terminal","browser","assets","traffic","approvals","engines"].includes(runtimeView)&&<PhoenixRunTools rid={rid} panel={runtimeView}/>}
            {runtimeView === "usage" && <><h2 className="px-files-heading">原生模型调用用量</h2><p className="px-muted">{run.calls} 次调用 · {run.billed_tokens.toLocaleString("zh-CN")} 已记账词元 · {costUnknown?"费用未完整计价":`$${run.billed_usd.toFixed(4)}`}</p><table className="px-usage-table"><thead><tr><th>角色 / 智能体</th><th>状态</th><th>输入词元</th><th>输出词元</th><th>费用</th></tr></thead><tbody>{d.model_calls.map((c:any)=><tr key={c.id}><td>{c.role} / {c.worker_id||"协调器"}</td><td>{c.status}</td><td>{c.input_tokens??"未上报"}</td><td>{c.output_tokens??"未上报"}</td><td>{c.cost_usd==null?"未定价":`$${c.cost_usd.toFixed(4)}`}</td></tr>)}</tbody></table>{!d.model_calls.length&&<div className="px-empty">暂无模型调用记录</div>}</>}
            {runtimeView === "workers" && <><div className="px-section-head"><h3>原生蜂群 · {s?.workers.length || 0} 智能体</h3>{editable && <button className="px-text-button" onClick={() => setAdd(!add)}><Icon name="plus" size={13} />添加智能体</button>}</div>{editable && <label className="px-inline-label">并行上限 <select aria-label="并行上限" value={s?.concurrency || run.config.concurrency} onChange={e => void action(() => patch(`/api/runs/${rid}/swarm`,{concurrency:Number(e.target.value)}))}>{Array.from({length:16},(_,i)=><option key={i+1}>{i+1}</option>)}</select></label>}
              {add && <form className="px-card px-native-form" onSubmit={e=>{e.preventDefault();void action(async()=>{await post(`/api/runs/${rid}/swarm/workers`,{id:`worker-${Date.now().toString(36)}`,name:workerName,roles:[role],profile:profile||null});setAdd(false);});}}><label>名称<input required value={workerName} onChange={e=>setWorkerName(e.target.value)}/></label><label>角色<select aria-label="角色" value={role} onChange={e=>setRole(e.target.value)}><option value="analyst">分析员</option><option value="solver">解题器</option><option value="reviewer">复核器</option></select></label><label>模型配置<select value={profile} onChange={e=>setProfile(e.target.value)}><option value="">继承角色模型</option>{Object.keys(catalog.data?.profiles || {}).map(p=><option key={p} value={p}>{uiLabel(p)}</option>)}</select></label><button disabled={busy}>加入编队</button></form>}
              {s?.workers.map((w:any)=><article className={`px-native-worker ${focused === w.id ? "px-selected" : ""}`} key={w.id}><div className="px-row"><strong><Icon name="bot" size={16}/> {workerDisplayName(w.name)}</strong><span className={w.status === "working" ? "px-live" : "px-muted"}>{label(w.status)}</span></div><p><code>{w.id}</code> · {roleLabels(w.roles)} · {Object.values(w.profiles).map((p:any)=>p.model || "未配置").join(" / ")}</p><p className="px-muted">{w.completed} 已完成 · {w.failed} 失败 · {w.usage.calls} 次调用 · {w.usage.input_tokens+w.usage.output_tokens} 词元</p>{w.active_task_ids.map((id:string)=><p key={id}>{tasks.find((t:any)=>t.id===id)?.goal}</p>)}<div className="px-actions"><button className="px-text-button" onClick={()=>openRuntime("timeline",w.id)}>查看时间线 →</button>{editable && <button className="px-text-button" disabled={busy} onClick={()=>void action(()=>patch(`/api/runs/${rid}/swarm/workers/${w.id}`,{enabled:!w.enabled}))}>{w.enabled ? "完成当前任务后停用" : "重新启用"}</button>}</div></article>)}
            </>}
            {runtimeView === "tasks" && <>{tasks.map((t:any)=><article className="px-task" key={t.id} data-state={t.state}><div className="px-row"><code>{t.key} · {uiLabel(t.role)}</code><span>{label(t.state)}</span></div><strong>{t.goal}</strong><p className="px-muted">{t.worker_id || "待领取"} {t.dependencies.length ? `← ${t.dependencies.join(", ")}` : "· 无前置依赖"}</p>{t.summary && <p>{t.summary}</p>}<small>{fmtDate(t.started)} → {fmtDate(t.ended)}</small></article>)}{!tasks.length && <div className="px-empty">规划器尚未生成任务</div>}</>}
            {runtimeView === "facts" && <>{d.facts.map((f:any)=><article className="px-native-worker" key={f.id}><div className="px-row"><code>{f.id}</code><span className="px-muted">{f.stance}</span></div><p>{f.statement}</p><small className="px-muted">带来源的声明，尚非独立验证结论</small><div className="px-actions">{parse<any[]>(f.citations,[]).map((q:any,i:number)=><button className="px-text-button" key={i} onClick={()=>void inspect(q.evidence_id)}>{q.evidence_id} →</button>)}</div></article>)}{!d.facts.length && <div className="px-empty">尚无共享发现</div>}</>}
            {runtimeView === "evidence" && evidenceList}
            {runtimeView === "files" && fileList}
          </div>}</div>}
        {view === "graph" && deck && <div className="px-native-graph"><Collaboration deck={deck} running={active} onOpenWorker={id=>openRuntime("workers",id)} onOpenTimeline={id=>openRuntime("timeline",id)} onOpenFact={()=>openRuntime("facts")} /></div>}
      </section>

      {inspectorVisible && <aside className="run-inspector px-solve-inspector" aria-label="运行信息"><div className="px-info-heading">运行信息<Icon name="panelRightClose" size={14}/></div>
        {run.mode !== "live" && <div className="px-scripted-note"><Icon name="info" size={14}/><span>脚本化 集成演示<br/><small>真实工具与证据流 · 脚本化模型决策</small></span></div>}
        {run.state === "failed" && <div className="px-error"><b>运行失败</b><p>{localizedError(run.reason)}</p></div>}
        <Section title="任务合同" badge={<span className="insp-flag-count">题目</span>}><div className="insp-task-grid"><div><span>目标</span><b>{ch?.description || "读取中…"}</b></div><div><span>执行目标</span><b>{ch?.targets?.join(", ") || "本地题目附件"}</b></div><div><span>答案 格式</span><b>{ch?.flag_prefix ? `${ch.flag_prefix}…` : "默认花括号格式"}</b></div></div></Section>
        <Section title="答案" badge={<span className="insp-flag-count">{d.candidates.length}</span>}><div className="px-flag-counts"><span>内部记录 <b>{d.candidates.length}</b></span><span>已确认 <b>{accepted}<small>/1</small></b></span></div>{!d.candidates.length && <div className="px-no-flag"><Icon name="flag" size={13}/>尚未收集到 答案</div>}{d.candidates.map((c:any)=><div className="px-native-flag" key={c.id}><div className="px-row"><span className={c.status === "accepted" ? "px-success" : "px-warning"}>{label(c.status)}</span><button className="px-text-button" onClick={()=>void inspect(c.evidence_id)}>来源 ↗</button></div><code>{c.value}</code><small>{uiLabel(c.verification) || "形状匹配不等于正确性验证"}</small><Link className="px-text-button" href={`/competition?run_id=${rid}&candidate_id=${c.id}`}>提交到平台 →</Link>{c.status === "unverified" && <div className="px-actions"><button className="px-text-button" disabled={busy} onClick={()=>void receipt(c.id,true)}>录入接受回执</button><button className="px-text-button" disabled={busy} onClick={()=>void receipt(c.id,false)}>录入拒绝回执</button></div>}</div>)}</Section>
        <Section title="工作面板"><div className="px-panel-links">{runtimeViews.map(([key,title,icon])=><button key={key} onClick={()=>openRuntime(key)}><Icon name={icon} size={14}/>{title}</button>)}<button onClick={()=>selectView("graph")}><Icon name="network" size={14}/>协作图</button></div></Section>
        <Section title="运行与预算"><dl className="px-run-metrics"><dt>智能体</dt><dd>{s?.live_workers || 0} 活跃 / {s?.workers.length || 0}</dd><dt>词元</dt><dd>{run.billed_tokens.toLocaleString("zh-CN")} / {run.config.budget.max_tokens.toLocaleString("zh-CN")}</dd><dt>调用</dt><dd>{run.calls} / {run.config.budget.max_calls}</dd><dt>用时</dt><dd>{duration} / {run.config.budget.wall_seconds}s</dd><dt>费用</dt><dd>{costUnknown ? "未完整计价" : `$${run.billed_usd.toFixed(4)}`}</dd></dl><div className="px-actions">{active && <button className="px-text-button" disabled={busy} onClick={()=>void action(()=>post(`/api/runs/${rid}/pause`))}><Icon name="pause" size={13}/>暂停蜂群</button>}{resumable && <button className="px-text-button" disabled={busy} onClick={()=>void action(()=>post(`/api/runs/${rid}/reconcile`))}>协调容器</button>}</div><code className="px-run-id">{rid}</code></Section>
        <div className="px-info-footer"><Link href="/swarm">蜂群编队</Link><Link href="/knowledge">知识库</Link><Link href="/memory">记忆蒸馏</Link></div>
      </aside>}
    </div>
    {modal && <div className="px-modal-backdrop" onClick={()=>setModal(null)} onKeyDown={e=>{if(e.key === "Escape")setModal(null);}}><section className={`px-modal px-card ${modal.writeup ? "px-writeup-modal" : ""}`} role="dialog" aria-modal="true" aria-label={modal.title} tabIndex={-1} ref={el=>el?.focus()} onClick={e=>e.stopPropagation()}><div className="px-row"><h2>{modal.title}</h2><button autoFocus onClick={()=>setModal(null)} aria-label="关闭"><Icon name="x" size={18}/></button></div>{modal.writeup ? <><div className="px-writeup-meta"><span>模型 <code>{modal.writeup.model}</code></span><span className={modal.writeup.verified_outcome ? "px-success" : "px-warning"}>{modal.writeup.verified_outcome ? "答案已独立确认" : "答案尚未独立确认"}</span><span>消耗 {((modal.writeup.input_tokens||0)+(modal.writeup.output_tokens||0)).toLocaleString("zh-CN")} 词元</span><span>{fmtDate(modal.writeup.updated)}</span></div><div className="px-writeup-body"><MessageMarkdown text={modal.writeup.body}/></div>{!!modal.writeup.citations?.length && <div className="px-writeup-citations"><span>引用证据</span>{modal.writeup.citations.map((q:any,i:number)=><button key={i} className="px-text-button" onClick={()=>void inspect(q.evidence_id)}><Icon name="fileSearch" size={12}/>{q.evidence_id} →</button>)}</div>}<div className="px-actions px-writeup-actions"><button className="px-text-button" onClick={()=>void action(()=>download(`/api/runs/${rid}/writeup/export`,`${rid}-writeup.md`))}><Icon name="download" size={13}/>下载 Markdown</button><button className="px-text-button" disabled={busy||active} onClick={()=>void generateWriteup()}><Icon name="refresh" size={13}/>重新生成</button><button className="px-text-button" onClick={()=>void action(()=>download(`/api/runs/${rid}/writeup/evidence`,`${rid}-evidence.md`))}><Icon name="file" size={13}/>导出原始证据</button></div></> : <><pre>{JSON.stringify(modal.value,null,2)}</pre>{modal.value?.next_offset != null && <button onClick={()=>void action(async()=>{const v=modal.value;const path=v.id ? `/api/runs/${rid}/evidence/${v.id}?length=32000&offset=${v.next_offset}` : `/api/runs/${rid}/workspace/read?area=${v.area}&path=${encodeURIComponent(v.path)}&offset=${v.next_offset}`;setModal({...modal,value:await api(path)});})}>下一页</button>}</>}</section></div>}
  </div>;
}
