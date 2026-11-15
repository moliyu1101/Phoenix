"use client";
import {uiLabel,localizedError} from "@/lib/phoenix-labels";
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./phoenix";

export type NativeEvent = { seq: number; kind: string; created: number; task_id?: string; worker_id?: string; payload: Record<string, any> };
type Page = { items: NativeEvent[]; has_more: boolean; next_after: number };

/** Drain the durable journal in sequence order; SSE is only a refresh signal. */
export function usePhoenixTimeline(rid: string) {
  const [items, setItems] = useState<NativeEvent[]>([]), [error, setError] = useState("");
  const generation = useRef(0), cursor = useRef(0), inflight = useRef(false), again = useRef(false);
  const refresh = useCallback(async (): Promise<void> => {
    if (inflight.current) { again.current = true; return; }
    const version = generation.current;
    inflight.current = true;
    try {
      do {
        again.current = false;
        let more = true;
        while (more && version === generation.current) {
          const page = await api<Page>(`/api/runs/${rid}/timeline?after=${cursor.current}&limit=200`);
          if (version !== generation.current) return;
          cursor.current = page.next_after;
          // An empty poll must not invalidate history or trigger follow scrolling.
          if (page.items.length) setItems(old => [...new Map([...old, ...page.items].map(e => [e.seq, e])).values()].sort((a,b) => a.seq-b.seq));
          more = page.has_more;
        }
      } while (again.current && version === generation.current);
      if (version === generation.current) setError("");
    } catch (e) { if (version === generation.current) setError((e as Error).message); }
    finally { inflight.current = false; if (again.current) { again.current = false; void refresh(); } }
  }, [rid]);
  useEffect(() => {
    const version = ++generation.current; cursor.current = 0; setItems([]); void refresh();
    const timer = setInterval(() => void refresh(), 5000);
    return () => { generation.current = version + 1; clearInterval(timer); };
  }, [refresh]);
  return { items, error, refresh };
}

export function eventPresentation(e: NativeEvent): { title: string; text: string; icon: string; bubble: boolean } {
  const p = e.payload;
  const known: Record<string, [string, string, string, boolean]> = {
    "operator.message": ["你", p.content, "send", true],
    "plan.added": ["协调器 · 任务规划", p.rationale, "radio", true],
    "worker.message": ["消息", p.content, "bot", true],
    "worker.finished": ["任务交接", p.summary, "checkCircle", true],
    "fact.created": ["共享发现", p.statement, "check", true],
    "run.created": ["系统 · 状态", "运行已创建，等待蜂群调度。", "clock", false],
    "run.started": ["系统 · 状态", "Phoenix 原生蜂群开始执行。", "clock", false],
    "run.state": ["系统 · 状态", /[\u3400-\u9fff]/.test(p.reason||"")?p.reason:uiLabel(p.state)||"运行状态已更新", "clock", false],
    "swarm.assigned": ["智能体领取任务", `${p.worker_id} · ${uiLabel(p.role)} · ${p.model || "继承角色模型"}`, "bot", false],
    "tool.started": ["工具调用", uiLabel(p.tool), "terminal", false],
    "evidence.created": ["工具证据", `${uiLabel(p.tool)} · ${p.ok ? "成功" : "失败"}`, "fileSearch", false],
    "flag.verified": ["答案验证", uiLabel(p.status), "flag", false],
    "flag.operator_receipt": ["答案人工回执", uiLabel(p.status), "flag", false],
    "worker.error": ["智能体执行失败", localizedError(p.reason), "xCircle", true],
    "planner.error": ["协调器执行失败", localizedError(p.reason), "xCircle", true],
    "run.continued": ["继续做题", `承接 ${p.source_run_id}，本轮使用新的预算。`, "refresh", false],
  };
  const v = known[e.kind] || [uiLabel(e.kind), p.reason || p.summary || JSON.stringify(p), "activity", false];
  return { title: v[0], text: v[1] || "", icon: v[2], bubble: v[3] };
}
