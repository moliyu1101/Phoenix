"use client";
import {PageFrame} from "./PhoenixPageFrame";
import {PlatformWorkspace} from "./fusion/PlatformWorkspace";
import {ScopeWorkspace} from "./fusion/ScopeWorkspace";
export function IntegrationsPage({competition=false}:{competition?:boolean}){
 return <PageFrame title={competition?"比赛平台":"外部集成"} subtitle={competition?"连接比赛、同步题库，在 Phoenix 中解题并回传平台结果。":"连接资产源，将外部线索导入蜂群工作区。"}>{competition?<PlatformWorkspace/>:<ScopeWorkspace/>}</PageFrame>;
}
