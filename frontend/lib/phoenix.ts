"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import {localizedError} from "./phoenix-labels";
export const TOKEN_KEY = "phoenix.workbench.token";
export function token() { try { return sessionStorage.getItem(TOKEN_KEY) || ""; } catch { return ""; } }
export async function request(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  if (token()) headers.set("Authorization", "Bearer " + token());
  if (init.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");
  const response = await fetch(path, { ...init, headers, cache: "no-store" });
  if (response.status === 401) window.dispatchEvent(new Event("phoenix-auth-expired"));
  return response;
}
export async function api<T = any>(path: string, init?: RequestInit): Promise<T> {
  let response:Response;
  try {response=await request(path,init);}
  catch(cause){throw Object.assign(new Error(localizedError(cause)),{cause});}
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const diagnostic=body.detail || body.error || body;
    throw Object.assign(new Error(localizedError(diagnostic,response.status)),{status:response.status,diagnostic});
  }
  return response.json();
}
export const post = <T = any>(path: string, body: unknown = {}) => api<T>(path, { method: "POST", body: JSON.stringify(body) });
export const patch = <T = any>(path: string, body: unknown) => api<T>(path, { method: "PATCH", body: JSON.stringify(body) });
export function useResource<T = any>(path: string | null, interval = 4000) {
  const [data, setData] = useState<T | null>(null), [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const version = useRef(0);
  const refresh = useCallback(async () => {
    if (!path) return;
    const current = ++version.current;
    try { const next = await api<T>(path); if (current === version.current) { setData(next); setError(""); } }
    catch (e) { if (current === version.current) setError(String((e as Error).message)); }
    finally { if (current === version.current) setLoading(false); }
  }, [path]);
  useEffect(() => {
    setData(null); setError(""); setLoading(true); void refresh();
    const id = interval ? setInterval(refresh, interval) : undefined;
    return () => { version.current++; if (id) clearInterval(id); };
  }, [refresh, interval]);
  return { data, error, loading, refresh };
}
// Read SSE with an Authorization header, retaining the durable event cursor.
export function useRunEvents(rid: string, onEvent: () => void) {
  const callback = useRef(onEvent); callback.current = onEvent;
  useEffect(() => {
    if (!rid) return;
    const controller = new AbortController(); let cursor = 0, refreshTimer: ReturnType<typeof setTimeout> | undefined;
    const sleep = () => new Promise(resolve => setTimeout(resolve, 1200));
    async function loop() {
      while (!controller.signal.aborted) {
        try {
          const response = await request(`/api/runs/${encodeURIComponent(rid)}/stream?after=${cursor}`, { signal: controller.signal });
          if (!response.ok || !response.body) { if (response.status === 401) return; throw new Error("Stream disconnected"); }
          const reader = response.body.getReader(), decoder = new TextDecoder(); let buffer = "";
          while (!controller.signal.aborted) {
            const { value, done } = await reader.read(); if (done) break;
            buffer += decoder.decode(value, { stream: true });
            let end: number;
            while ((end = buffer.indexOf("\n\n")) >= 0) {
              const frame = buffer.slice(0, end); buffer = buffer.slice(end + 2);
              const id = /^id: (\d+)$/m.exec(frame); if (id) cursor = Math.max(cursor, Number(id[1]));
              if (/^data:/m.test(frame) && !refreshTimer) refreshTimer = setTimeout(() => { refreshTimer = undefined; callback.current(); }, 200);
            }
          }
        } catch { if (controller.signal.aborted) return; }
        await sleep();
      }
    }
    void loop();
    return () => { controller.abort(); if (refreshTimer) clearTimeout(refreshTimer); };
  }, [rid]);
}
export async function download(path: string, filename: string) {
  const response = await request(path); if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const href = URL.createObjectURL(await response.blob()); const a = document.createElement("a");
  a.href = href; a.download = filename; a.click(); setTimeout(() => URL.revokeObjectURL(href), 1000);
}

export { parse, isActive, canResume, categoryLabels, stateLabels, label, fmtDate } from "./phoenix-state";
