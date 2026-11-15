"use client";
import {localizedError} from "@/lib/phoenix-labels";
import {useState, type ReactNode} from "react";
import {Search, X, Inbox, RefreshCw} from "lucide-react";

export function useOperation(){
 const [busy,setBusy]=useState(false),[error,setError]=useState("");
 async function act(fn:()=>Promise<unknown>){setBusy(true);setError("");try{await fn();}catch(e){setError(localizedError(e));}finally{setBusy(false);}}
 return {busy,error,act};
}
export function Empty({title,children}:{title:string;children?:ReactNode}){return <div className="px-tool-empty"><Inbox size={28}/><strong>{title}</strong><p>{children}</p></div>;}
export function Badge({children,tone="muted"}:{children:ReactNode;tone?:string}){return <span className={`px-tool-badge px-tool-badge--${tone}`}>{children}</span>;}
export function ToolHeader({icon,title,description,children}:{icon:ReactNode;title:string;description:string;children?:ReactNode}){return <header className="px-tool-header"><span className="px-tool-icon">{icon}</span><div><h2>{title}</h2><p>{description}</p></div><div className="px-tool-actions">{children}</div></header>;}
export function SearchBox({value,onChange,placeholder="搜索"}:{value:string;onChange:(value:string)=>void;placeholder?:string}){return <label className="px-tool-search"><Search size={14}/><input aria-label={placeholder} placeholder={placeholder} value={value} onChange={e=>onChange(e.target.value)}/>{value&&<button type="button" aria-label="清除搜索" onClick={()=>onChange("")}><X size={13}/></button>}</label>;}
export function Refresh({busy,onClick}:{busy?:boolean;onClick:()=>void}){return <button type="button" title="刷新" aria-label="刷新" disabled={busy} onClick={onClick}><RefreshCw size={14} className={busy?"px-tool-spin":""}/></button>;}
export function Drawer({title,children,onClose}:{title:string;children:ReactNode;onClose:()=>void}){return <section className="px-tool-inspector" aria-label={title}><header><h3>{title}</h3><button aria-label="关闭详情" onClick={onClose}><X size={16}/></button></header>{children}</section>;}
