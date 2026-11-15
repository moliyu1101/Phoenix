"use client";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { ThreadRail } from "./ThreadRail";
import type { RunSummary, Folder } from "@/lib/useRun";
import { api, post, patch, useResource, isActive } from "@/lib/phoenix";
import { matchesBinding, shortcutBinding, isMacPlatform } from "@/lib/shortcutBindings";
import { NewChallenge } from "./PhoenixNewChallenge";
import { RunView } from "./PhoenixSolve";
export { RunView } from "./PhoenixSolve";

export default function RunWorkbench() {
 const params = useParams<{ id?: string }>(), rid = params?.id || "", router = useRouter();
 const runs = useResource<RunSummary[]>("/api/workbench/runs", 7000), folders = useResource<Folder[]>("/api/workbench/folders", 10000);
 const [width, setWidth] = useState(264), [collapsed, setCollapsed] = useState(true), [error, setError] = useState("");
 const { refresh: refreshRuns } = runs;
 const refresh = useCallback(() => { void refreshRuns(); }, [refreshRuns]);
 useEffect(()=>{const onKey=(e:KeyboardEvent)=>{if(e.defaultPrevented)return;const match=(id:Parameters<typeof shortcutBinding>[0])=>matchesBinding(e,shortcutBinding(id),isMacPlatform());if(match("newChat")){e.preventDefault();router.push("/ctf");}else if(match("toggleSidebar")){e.preventDefault();setCollapsed(v=>!v);}else if(match("modelPicker")){e.preventDefault();router.push("/settings");}else if(!(e.target as HTMLElement)?.closest("input,textarea,select,[contenteditable=true]")&&match("help")){e.preventDefault();router.push("/settings/shortcuts");}};window.addEventListener("keydown",onKey);return()=>window.removeEventListener("keydown",onKey);},[router]);
 async function railAction(a: any): Promise<Folder | null | void> {
  try {
   if (a.kind === "newFolder") { const result = await post<Folder>("/api/workbench/folders", { name: "\u65b0\u6587\u4ef6\u5939" }); void folders.refresh(); return result; }
   if (a.kind === "renameFolder") await patch(`/api/workbench/folders/${a.folderId}`, { name: a.name });
   else if (a.kind === "deleteFolder") await api(`/api/workbench/folders/${a.folderId}`, { method: "DELETE" });
   else if (a.kind === "exportFolder") { const blob = new Blob([JSON.stringify(runs.data?.filter(r => r.folder_id === a.folderId), null, 2)], { type: "application/json" }); const href = URL.createObjectURL(blob); const el = document.createElement("a"); el.href = href; el.download = "phoenix-folder-index.json"; el.click(); setTimeout(() => URL.revokeObjectURL(href), 1000); }
   else if (a.kind === "delete") { const current=await api(`/api/runs/${a.runId}`); if(isActive(current.run.state)){setError("该运行仍在执行，请先在运行页暂停，再从侧栏移除。");refresh();return;} if (!window.confirm("\u4ece\u4fa7\u8fb9\u680f\u9690\u85cf\u6b64\u8bb0\u5f55\uff1f\u539f\u59cb\u8bc1\u636e\u4ecd\u4f1a\u4fdd\u7559\u3002")) return; await api(`/api/workbench/runs/${a.runId}`, { method: "DELETE" }); if (rid === a.runId) router.push("/ctf"); }
   else if (a.kind === "reorder") await post("/api/workbench/runs/reorder", { run_ids: a.runIds, pinned: a.pinned });
   else if (["pin", "archive", "rename", "move"].includes(a.kind)) await patch(`/api/workbench/runs/${a.runId}`, a.kind === "pin" ? { pinned: a.pinned } : a.kind === "archive" ? { archived: a.archived } : a.kind === "rename" ? { name: a.name } : { folder_id: a.folderId });
   refresh(); void folders.refresh(); setError("");
  } catch (e) { setError((e as Error).message); }
 }
 return <div className="shell px-shell"><ThreadRail collapsed={collapsed} width={width} runs={runs.data || []} folders={folders.data || []} activeRunId={rid} draftActive={!rid} connected={!runs.error && !!runs.data} onNew={() => router.push("/ctf")} onSelect={id => router.push(`/run/${id}`)} onAction={railAction} onResize={setWidth} onOpenSettings={() => router.push("/settings")} onClose={() => setCollapsed(true)} />
  <main className="px-main">
   {error && <div className="px-error" role="alert">{error}</div>}{rid ? <RunView key={rid} rid={rid} onRefresh={refresh} onToggleSidebar={() => setCollapsed(!collapsed)} /> : <NewChallenge refresh={refresh} onToggleSidebar={() => setCollapsed(!collapsed)} />}
  </main></div>;
}
// Retained source compatibility only; no pentest route or legacy engine is mounted.
export const PentestWorkbench = RunWorkbench;
