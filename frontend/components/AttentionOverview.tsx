"use client";

import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "@/lib/useRun";
import { Icon } from "@/components/Icon";

type Severity = "action" | "review" | "info";

interface AttentionItem {
  id: string;
  kind: string;
  severity: Severity;
  title: string;
  detail: string;
  hint: string;
  refs: Record<string, string>;
  created: number;
}

interface EffectHealth {
  kind: string;
  accepted: number;
  waiting: number;
  running: number;
  completed: number;
  failed: number;
  dead_letter: number;
  cancelled: number;
  needs_attention: number;
}

interface AttentionView {
  generated: number;
  total: number;
  counts: Record<Severity, number>;
  items: AttentionItem[];
  effect_health: EffectHealth[];
}

const SEVERITY_LABEL: Record<Severity, string> = { action: "需操作", review: "待复核", info: "提示" };
const EMPTY_VIEW: AttentionView = { generated: 0, total: 0, counts: { action: 0, review: 0, info: 0 }, items: [], effect_health: [] };

export function AttentionOverview() {
  const [view, setView] = useState<AttentionView>(EMPTY_VIEW);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const res = await apiFetch("/api/attention", { signal: AbortSignal.timeout(15000) });
      if (!res.ok) throw new Error(`加载待人工总览失败（HTTP ${res.status}）`);
      setView((await res.json()) as AttentionView);
      setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载待人工总览失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 8000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  const act = useCallback(async (effectId: string, action: "retry" | "drop") => {
    setBusy(effectId + action);
    try {
      const res = await apiFetch(`/api/effects/${encodeURIComponent(effectId)}/${action}`, { method: "POST" });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.error || `操作失败（HTTP ${res.status}）`);
      }
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "操作失败");
    } finally {
      setBusy(null);
    }
  }, [refresh]);

  return (
    <div className="px-attention">
      <div className="px-attention-summary">
        <div className="px-attention-stat" data-tone="action"><strong>{view.counts.action}</strong><span>需操作</span></div>
        <div className="px-attention-stat" data-tone="review"><strong>{view.counts.review}</strong><span>待复核</span></div>
        <div className="px-attention-stat"><strong>{view.total}</strong><span>合计</span></div>
        <div className="px-attention-actions">
          <button type="button" onClick={() => void refresh()} aria-label="刷新">
            <Icon name="radio" size={14} /> 刷新
          </button>
        </div>
      </div>

      {error ? <div className="px-attention-error">{error}</div> : null}

      {view.effect_health.length ? (
        <div>
          <div className="px-attention-section-label">副作用队列健康</div>
          <div className="px-attention-health" style={{ marginTop: 8 }}>
            {view.effect_health.map((h) => (
              <span key={h.kind}>{h.kind} · 待处理 {h.accepted + h.waiting} · 需人工 {h.needs_attention}</span>
            ))}
          </div>
        </div>
      ) : null}

      {loading ? (
        <div className="px-attention-empty">正在加载…</div>
      ) : view.items.length === 0 ? (
        <div className="px-attention-empty">
          <strong>当前没有需要人工处理的事项</strong>
          自主循环正在正常运行；只有需要操作者决策的项才会出现在这里。
        </div>
      ) : (
        <div className="px-attention-list">
          {view.items.map((item) => (
            <div className="px-attention-item" key={item.id}>
              <span className="px-attention-badge" data-severity={item.severity}>{SEVERITY_LABEL[item.severity]}</span>
              <div className="px-attention-body">
                <strong>{item.title}</strong>
                <p>{item.detail}</p>
                <span className="px-attention-hint">{item.hint}</span>
              </div>
              {item.kind === "effect" && item.refs.effect_id ? (
                <div className="px-attention-actions">
                  <button type="button" disabled={busy !== null} onClick={() => void act(item.refs.effect_id, "retry")}>重试</button>
                  <button type="button" disabled={busy !== null} onClick={() => void act(item.refs.effect_id, "drop")}>丢弃</button>
                </div>
              ) : null}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}