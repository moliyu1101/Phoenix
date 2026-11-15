"use client";
import { useEffect, useState } from "react";
import { localizedError } from "@/lib/phoenix-labels";
import { PhoenixLogo } from "./PhoenixLogo";
import { TOKEN_KEY, token } from "@/lib/phoenix";
import { setConversationStorageScope } from "@/lib/conversationStorageScope";
import { startUiPreferencesSync } from "@/lib/uiPreferences";
export function LoginGate({ children, onAuthStateChange }: { children: React.ReactNode; onAuthStateChange?: (open: boolean) => void }) {
  const [ready, setReady] = useState(false), [loading, setLoading] = useState(true), [value, setValue] = useState(""), [error, setError] = useState("");
  async function check(key: string) {
    setLoading(true); setError("");
    try {
      const response = await fetch("/api/overview", { headers: { Authorization: "Bearer " + key }, cache: "no-store" });
      if (!response.ok) throw new Error(response.status === 401 ? "\u8bf7\u8f93\u5165\u542f\u52a8\u65f6\u663e\u793a\u7684\u5de5\u4f5c\u53f0\u4ee4\u724c" : `\u540e\u7aef\u8fde\u63a5\u5931\u8d25: HTTP ${response.status}`);
      sessionStorage.setItem(TOKEN_KEY, key); setConversationStorageScope(`${window.location.origin}:phoenix-operator`); setReady(true); onAuthStateChange?.(true);
    } catch (e) { setError(localizedError(e)); setReady(false); }
    finally { setLoading(false); }
  }
  useEffect(() => {
    if (token()) void check(token()); else setLoading(false);
    const stopSync = startUiPreferencesSync();
    const expire = () => { setConversationStorageScope(""); setReady(false); onAuthStateChange?.(false); };
    window.addEventListener("phoenix-auth-expired", expire);
    return () => { stopSync(); window.removeEventListener("phoenix-auth-expired", expire); };
  // The authentication check runs once per mount; no secret is in the URL.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  if (ready) return <>{children}</>;
  return <main className="px-login"><form className="px-card px-login-card" onSubmit={e => { e.preventDefault(); void check(value); }}>
    <div className="px-login-brand-stage"><PhoenixLogo size={220} artwork decorative/></div><h1>{"\u767b\u5f55 Phoenix \u5de5\u4f5c\u53f0"}</h1>
    <p>{"\u8702\u7fa4\u534f\u4f5c \u00b7 \u8bc1\u636e\u6eaf\u6e90 \u00b7 \u77e5\u8bc6\u4e0e\u8bb0\u5fc6"}</p>
    <label>{"\u5de5\u4f5c\u53f0\u4ee4\u724c\uff08\u4e0d\u662f\u6a21\u578b 接口密钥\uff09"}<input type="password" autoComplete="off" required value={value} onChange={e => setValue(e.target.value)} placeholder="PHOENIX_WEB_TOKEN" /></label>
    {error && <div className="px-error" role="alert">{error}</div>}
    <button type="submit" className="px-primary" disabled={loading}>{loading ? "\u8fde\u63a5\u4e2d\u2026" : "\u8fdb\u5165\u5de5\u4f5c\u53f0"}</button>
    <small>{"\u4ee4\u724c\u4ec5\u5b58\u5728\u5f53\u524d\u6d4f\u89c8\u5668\u4f1a\u8bdd\uff0c\u4e0d\u653e\u5165 URL\u3002"}</small>
  </form></main>;
}
