"use client";
import Link from "next/link";
import {usePathname,useRouter} from "next/navigation";
import {type ReactNode} from "react";
import {SettingsNav,SettingsPage,type SettingsNavGroup} from "./settings/primitives";
import {PhoenixLogo} from "./PhoenixLogo";
import {Icon} from "./Icon";
import {setThemePreference} from "@/lib/themePreference";

const groups:SettingsNavGroup[]=[
 {id:"connection",label:"连接",items:[{id:"settings",href:"/settings",label:"模型与用量",icon:"cpu",keywords:"模型 连接 预算"},{id:"integrations",href:"/settings/integrations",label:"外部集成",icon:"plug",keywords:"ScopeSentry 资产源"},{id:"extensions",href:"/settings/extensions",label:"扩展与 MCP",icon:"package",keywords:"MCP 插件 工具 扩展"}]},
 {id:"preferences",label:"偏好",items:[{id:"appearance",href:"/settings/appearance",label:"外观",icon:"sun",keywords:"主题 字体 字号 配色"},{id:"shortcuts",href:"/settings/shortcuts",label:"快捷键",icon:"keyboard",keywords:"键盘 操作"}]},
];
export function PageFrame({title,subtitle,children,actions}:{title:string;subtitle:string;children:ReactNode;actions?:ReactNode}) {
 const pathname=usePathname(),router=useRouter();
 const settings=pathname.startsWith("/settings");
 const active=groups.flatMap(g=>g.items).find(i=>i.href===pathname)?.id;
 return <div className={`cx-root px-library-shell px-page-workspace ${settings?"px-page-settings":"px-page-business"}`}>
 {settings&&<aside className="px-library-nav" aria-label="设置分类"><Link href="/ctf" className="settings-hub-brand"><PhoenixLogo size={25} wordmark/></Link><SettingsNav title="设置" groups={groups} activeId={active} link={Link} onNavigate={href=>router.push(href)} labels={{search:"搜索设置",clear:"清除搜索",empty:"没有匹配的设置",nav:"设置导航"}}/><div className="px-library-nav-foot"><button onClick={()=>setThemePreference(document.documentElement.dataset.theme==="dark"?"light":"dark")}><Icon name="moon" size={14}/>切换主题</button><span>PHOENIX · 0.1.0</span></div></aside>}
 <main className="px-library-main" id="settings-main"><div className="px-page-breadcrumb"><span>{settings?"设置":"工作台"}</span><Icon name="chevronRight" size={12}/><span>{title}</span>{!settings&&<Link href="/ctf" className="px-page-return"><Icon name="arrowLeft" size={13}/>返回解题</Link>}</div><SettingsPage wide title={title} description={subtitle} actions={actions}><div className="px-library-body">{children}</div></SettingsPage></main></div>;
}
