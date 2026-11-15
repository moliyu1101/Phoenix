"use client";
import {type ReactNode} from "react";
import {X,FileText,ExternalLink} from "lucide-react";
import {uiLabel} from "@/lib/phoenix-labels";
import {ConfigModal} from "../fusion/ConfigModal";

export function WorkspaceStats({items}:{items:{label:string;value:ReactNode;hint?:string}[]}){
 return <div className="px-workspace-stats">{items.map(item=><div key={item.label}><span>{item.label}</span><strong>{item.value}</strong>{item.hint&&<small>{item.hint}</small>}</div>)}</div>;
}
export function WorkspaceTabs({items,value,onChange,label}:{items:{id:string;label:string;count?:number}[];value:string;onChange:(id:string)=>void;label:string}){
 return <nav className="px-workspace-tabs" aria-label={label}>{items.map(item=><button type="button" key={item.id} aria-current={value===item.id?"page":undefined} onClick={()=>onChange(item.id)}>{item.label}{item.count!==undefined&&<span>{item.count}</span>}</button>)}</nav>;
}
export function StateBadge({value}:{value:string}){return <span className={`px-state-badge px-state-${value}`} data-state={value}><i/>{uiLabel(value)}</span>;}
export function DetailPane({title,eyebrow,actions,children,onClose}:{title:string;eyebrow?:string;actions?:ReactNode;children:ReactNode;onClose:()=>void}){
 return <section className="px-workspace-detail" aria-label={title}><header><div>{eyebrow&&<span>{eyebrow}</span>}<h2>{title}</h2></div><button className="px-detail-close" aria-label="关闭详情" onClick={onClose}><X size={17}/></button></header>{actions&&<div className="px-detail-actions">{actions}</div>}<div className="px-detail-body">{children}</div></section>;
}
export function ContentSection({title,children}:{title:string;children:ReactNode}){return <section className="px-content-section"><h3>{title}</h3>{children}</section>;}
export function SourceMeta({fields}:{fields:{label:string;value:ReactNode}[]}){return <dl className="px-source-meta">{fields.map(f=><div key={f.label}><dt>{f.label}</dt><dd>{f.value||"—"}</dd></div>)}</dl>;}
export function EvidenceModal({evidence,onClose,onNext}:{evidence:any;onClose:()=>void;onNext?:()=>void}){
 return <ConfigModal open={!!evidence} onClose={onClose} title="原始工具证据">{evidence&&<div className="px-evidence-document"><div className="px-evidence-document-title"><FileText size={18}/><strong>{uiLabel(evidence.tool)}</strong><StateBadge value={evidence.ok?"ok":"failed"}/></div><SourceMeta fields={[{label:"证据编号",value:<code>{evidence.id}</code>},{label:"完整性校验",value:<code>{evidence.sha256}</code>},{label:"来源",value:uiLabel(evidence.origin)}]}/><pre className="px-code-document">{evidence.content}</pre><footer><span>已读取 {evidence.offset+evidence.content.length} / {evidence.total_chars} 字符</span>{evidence.next_offset!=null&&onNext&&<button onClick={onNext}><ExternalLink size={14}/>继续读取</button>}</footer></div>}</ConfigModal>;
}
