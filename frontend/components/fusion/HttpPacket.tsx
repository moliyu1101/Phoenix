"use client";
// Migrated from PHOENIX traffic/page.tsx: HTTP start/header lines and JSON/markup token rendering.
import * as React from "react";
import {Copy, Check, WrapText} from "lucide-react";
function statusTone(status: number) {
  if (status >= 500) return "text-red-500";
  if (status >= 400) return "text-amber-500";
  if (status >= 300) return "text-blue-500";
  if (status >= 200) return "text-emerald-500";
  return "text-muted-foreground";
}

function StartLine({ line }: { line: string }) {
  const response = /^(HTTP\/\S+)(\s+)(\d{3})(.*)$/.exec(line);
  if (response) {
    return (
      <>
        <span className="text-muted-foreground">{response[1]}</span>
        {response[2]}
        <span className={statusTone(Number(response[3]))}>{response[3]}</span>
        {response[4]}
      </>
    );
  }

  const request = /^([A-Z]+)(\s+)(\S+)(\s+)(HTTP\/\S+)$/.exec(line);
  if (request) {
    return (
      <>
        <span className="font-semibold text-primary">{request[1]}</span>
        {request[2]}
        <span className="text-chart-2">{request[3]}</span>
        {request[4]}
        <span className="text-muted-foreground">{request[5]}</span>
      </>
    );
  }

  return line;
}

function HeaderLine({ line }: { line: string }) {
  const separator = line.indexOf(":");
  if (separator <= 0) return line;
  return (
    <>
      <span className="text-primary">{line.slice(0, separator)}</span>
      <span className="text-muted-foreground">:</span>
      <span className="text-chart-2">{line.slice(separator + 1)}</span>
    </>
  );
}

function JsonBody({ body }: { body: string }) {
  const parts: React.ReactNode[] = [];
  const tokens = /("(?:\\.|[^"\\])*")(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?/g;
  let cursor = 0;
  for (const match of body.matchAll(tokens)) {
    const index = match.index ?? 0;
    if (index > cursor) parts.push(body.slice(cursor, index));
    let className = "text-chart-4";
    if (match[1]) className = match[2] ? "text-primary" : "text-chart-2";
    else if (match[3]) className = "text-chart-3";
    parts.push(
      <span key={`${index}-${match[0].length}`} className={className}>
        {match[0]}
      </span>,
    );
    cursor = index + match[0].length;
  }
  if (cursor < body.length) parts.push(body.slice(cursor));
  return parts;
}

function MarkupBody({ body }: { body: string }) {
  const parts: React.ReactNode[] = [];
  const tags = /<\/?[A-Za-z][^>]*>|<!--[\s\S]*?-->/g;
  let cursor = 0;
  for (const match of body.matchAll(tags)) {
    const index = match.index ?? 0;
    if (index > cursor) parts.push(body.slice(cursor, index));
    parts.push(
      <span key={`${index}-${match[0].length}`} className="text-primary">
        {match[0]}
      </span>,
    );
    cursor = index + match[0].length;
  }
  if (cursor < body.length) parts.push(body.slice(cursor));
  return parts;
}

type BodyFormat = "json" | "markup" | "plain";

function detectBodyFormat(body: string): BodyFormat {
  const trimmed = body.trimStart();
  if (trimmed.startsWith("{") || trimmed.startsWith("[")) return "json";
  if (trimmed.startsWith("<")) return "markup";
  return "plain";
}

function HighlightedBody({ body, format }: { body: string; format: BodyFormat }) {
  if (format === "json") return <JsonBody body={body} />;
  if (format === "markup") return <MarkupBody body={body} />;
  return body;
}


export function HttpPacket({raw}:{raw:string}) {
 const [wrap,setWrap]=React.useState(true),[copied,setCopied]=React.useState(false);
 React.useEffect(()=>{if(!copied)return;const id=setTimeout(()=>setCopied(false),1500);return()=>clearTimeout(id);},[copied]);
 const lines=raw.replaceAll("\r\n","\n").split("\n"),separator=lines.indexOf("");
 const format=detectBodyFormat(lines.slice(separator+1).join("\n"));
 return <div className="px-http-packet"><div className="px-packet-tools"><button aria-label="自动换行" aria-pressed={wrap} onClick={()=>setWrap(!wrap)}><WrapText size={14}/></button><button aria-label="复制报文" onClick={()=>void navigator.clipboard.writeText(raw).then(()=>setCopied(true))}>{copied?<Check size={14}/>:<Copy size={14}/>}</button></div><pre style={{whiteSpace:wrap?"pre-wrap":"pre"}}>{lines.map((line,i)=><div key={i}><span className="px-line-number">{i+1}</span><code>{i===0?<StartLine line={line}/>:separator<0||i<separator?<HeaderLine line={line}/>:i===separator?" ":<HighlightedBody body={line} format={format}/>}</code></div>)}</pre></div>;
}
