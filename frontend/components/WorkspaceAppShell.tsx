"use client";
import Link from "next/link";
import {usePathname} from "next/navigation";
import {useEffect,useState,type ReactNode} from "react";
import {LoginGate} from "./LoginGate";
import {Icon,type IconName} from "./Icon";
import {Tooltip} from "./chat/ui/Tooltip";
import {I18nProvider} from "@/lib/i18n";
import {setThemePreference} from "@/lib/themePreference";
import {TOKEN_KEY} from "@/lib/phoenix";

const modes:[string,IconName,string][]=[
 ["/ctf","crosshair","解题"],
 ["/competition","flag","比赛平台"],
 ["/swarm","grid","蜂群编队"],
 ["/knowledge","book","知识库"],
 ["/memory","brain","记忆蒸馏"],
 ["/evolution","gitBranch","策略进化"],
];

export function WorkspaceAppShell({children}:{children:ReactNode}) {
 const pathname=usePathname(),[theme,setTheme]=useState("dark");
 useEffect(()=>{
  const sync=()=>setTheme(document.documentElement.dataset.theme==="light"?"light":"dark");
  sync();const observer=new MutationObserver(sync);
  observer.observe(document.documentElement,{attributes:true,attributeFilter:["data-theme"]});
  return()=>observer.disconnect();
 },[]);
 const themeLabel=theme==="dark"?"切换到亮色模式":"切换到暗色模式";
 return <I18nProvider><LoginGate><div className="workspace-frame px-frame">
  <a className="skip-link" href="#phoenix-content">跳到主要内容</a>
  <aside className="workspace-activity-rail" aria-label="工作台导航">
   <div className="workspace-rail-main"><nav id="workspace-navigation" className="workspace-rail-links" aria-label="模式选择">
    {modes.map(([href,icon,text])=>{
     const active=pathname===href||(href==="/ctf"&&(pathname==="/"||pathname.startsWith("/run/")));
     return <Tooltip key={href} content={text} placement="right"><Link href={href} className="workspace-rail-control" aria-label={text} aria-current={active?"page":undefined}><Icon name={icon} size={19}/><span className="sr-only">{text}</span></Link></Tooltip>;
    })}
   </nav></div>
   <div className="workspace-rail-bottom">
    <Tooltip content={themeLabel} placement="right"><button type="button" className="workspace-rail-control" aria-label={themeLabel} onClick={()=>setThemePreference(theme==="dark"?"light":"dark")}><Icon name={theme==="dark"?"sun":"moon"} size={19}/></button></Tooltip>
    <Tooltip content="设置" placement="right"><Link href="/settings" className="workspace-rail-control" aria-label="设置" aria-current={pathname.startsWith("/settings")?"page":undefined}><Icon name="gear" size={19}/></Link></Tooltip>
    <Tooltip content="退出" placement="right"><button type="button" className="workspace-rail-control" aria-label="退出" onClick={()=>{sessionStorage.removeItem(TOKEN_KEY);window.dispatchEvent(new Event("phoenix-auth-expired"));}}><Icon name="x" size={18}/></button></Tooltip>
   </div>
  </aside>
  <div id="phoenix-content" className="workspace-frame-content" tabIndex={-1}>{children}</div>
 </div></LoginGate></I18nProvider>;
}
