import {uiLabel} from "./phoenix-labels";
export function parse<T = any>(value: T | string, fallback: T = {} as T): T {
  if (typeof value !== "string") return value;
  try { return JSON.parse(value); } catch { return fallback; }
}

export const isActive = (state: string) => ["created", "running", "distilling"].includes(state);
export const canResume = (state: string) => ["paused", "interrupted"].includes(state);
export const categoryLabels: Record<string, string> = { web: "网站安全", crypto: "密码学", pwn: "二进制利用", reverse: "逆向工程", forensics: "取证分析", misc: "杂项" };
export const stateLabels: Record<string, string> = {
 created: "\u5f85\u8c03\u5ea6", running: "\u8fd0\u884c\u4e2d", distilling: "\u84b8\u998f\u4e2d", solved: "\u5df2\u786e\u8ba4",
 failed: "\u5931\u8d25", paused: "\u5df2\u6682\u505c", interrupted: "\u5f85\u6062\u590d", exhausted: "\u5df2\u7ed3\u675f",
 awaiting_verification: "\u5f85\u9a8c\u8bc1", budget_exhausted: "\u9884\u7b97\u8017\u5c3d", pending: "\u5f85\u9886\u53d6", done: "\u5df2\u5b8c\u6210",
 blocked: "\u5df2\u963b\u585e", working: "\u5de5\u4f5c\u4e2d", draining: "\u5b8c\u6210\u5f53\u524d\u4efb\u52a1\u540e\u505c\u7528", standby: "\u5f85\u547d",
 disabled: "\u5df2\u505c\u7528", finished: "\u5df2\u7ed3\u675f", accepted: "\u5df2\u63a5\u53d7", unverified: "\u672a\u9a8c\u8bc1", rejected: "\u5df2\u62d2\u7edd",
};
export function label(state: string) { return stateLabels[state] || uiLabel(state); }
export function fmtDate(ts?: number) { return ts ? new Date(ts * 1000).toLocaleString("zh-CN") : "\u2014"; }
