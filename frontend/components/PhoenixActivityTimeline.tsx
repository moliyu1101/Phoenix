"use client";
import { useMemo } from "react";
import { ActivityConsole, type ConsoleClock } from "./activity-timeline/ActivityConsole";
import { phoenixTrace } from "@/lib/phoenixTrace";
import { isActive } from "@/lib/phoenix-state";

export function PhoenixActivityTimeline({detail,swarm,challenge,events,worker}: {detail:any;swarm:any;challenge:any;events:any[];worker:string}) {
  const {scenario,origin}=useMemo(()=>phoenixTrace(detail,swarm,challenge,events),[detail,swarm,challenge,events]);
  const clock=useMemo<ConsoleClock>(()=>isActive(detail.run.state)?{mode:"live",origin}:{mode:"replay",startAt:"end"},[detail.run.state,origin]);
  const focus=useMemo(()=>worker?{spanId:`worker:${worker}`,nonce:Date.now()}:null,[worker]);
  const calls=detail.model_calls || [], tokens=calls.filter((c:any)=>c.input_tokens!=null && c.output_tokens!=null);
  const unpriced=calls.filter((c:any)=>c.cost_usd==null).length;
  return <ActivityConsole className="rt-embedded px-phoenix-trace" scenario={scenario} clock={clock} resetKey={detail.run.id}
    autoFold={false} lang="zh" timeOrigin={origin} focus={focus} summary={{
      cost:!calls.length?"费用暂无数据":unpriced?"未完整计价":`$${detail.run.billed_usd.toFixed(4)}`,
      tokens:tokens.length?tokens.reduce((n:number,c:any)=>n+c.input_tokens+c.output_tokens,0):null,
    }}/>;
}
