"use client";
import {useEffect,useState} from "react";
import {PageFrame} from "./PhoenixPageFrame";
import {AppearanceSettings} from "./settings/AppearanceSettings";
import {ShortcutsSettings} from "./settings/ShortcutsSettings";
export function PreferencesPage({shortcuts=false}:{shortcuts?:boolean}) {
 const [mounted,setMounted]=useState(false);useEffect(()=>setMounted(true),[]);
 return <PageFrame title={shortcuts?"快捷键":"外观"} subtitle={shortcuts?"沿用 Phoenix 的键位编辑器，快捷键偏好保存在此设备。":"使用 Phoenix 原有的主题、配色、字体和阅读设置。"}>{mounted?(shortcuts?<ShortcutsSettings nativeOnly/>:<AppearanceSettings nativeOnly/>):<div role="status">正在读取偏好…</div>}</PageFrame>;
}
