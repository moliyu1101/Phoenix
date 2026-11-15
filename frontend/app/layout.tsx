import type { Metadata, Viewport } from "next";
import "./globals.css";
import "./styles/phoenix-fusion.css";
import "@xterm/xterm/css/xterm.css";
import "@/styles/transitions/_root.css";
import "@/styles/transitions/index.css";
import "@/styles/transitions/surfaces.css";
import "@/styles/transitions/accessibility.css";
import "./styles/phoenix-refinement.css";
import SchemeBoot from "../components/SchemeBoot";
import { Providers } from "./providers";
import { WorkspaceAppShell } from "@/components/WorkspaceAppShell";

export const metadata: Metadata = {
  applicationName: "Phoenix",
  title: {
    default: "Phoenix · 智能体蜂群解题工作台",
    template: "%s · Phoenix",
  },
  description: "原生智能体蜂群解题、证据溯源、知识库、记忆蒸馏与策略进化工作台。",
  appleWebApp: {
    capable: true,
    statusBarStyle: "black-translucent",
    title: "Phoenix",
  },
};

// C35: cover mode + C37: themeColor for PWA standalone status bar
export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  themeColor: [
    { media: "(prefers-color-scheme: dark)", color: "#0f1011" },
    { media: "(prefers-color-scheme: light)", color: "#ffffff" },
  ],
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html data-phoenix-ui-build={process.env.NEXT_PUBLIC_PHOENIX_UI_BUILD || "development"} data-phoenix-appearance-contract="1" lang="zh-CN" data-theme="dark" className="dark" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: `try{if(/(?:^|\\s)PhoenixDesktop\\/[\\w.+-]+(?:\\s|$)/.test(navigator.userAgent)){var a=JSON.parse(localStorage.getItem("phoenix.desktop.appearanceOverride")||"null");if(a&&(a.resolvedTheme==="light"||a.resolvedTheme==="dark")){var r=document.documentElement;r.dataset.theme=a.resolvedTheme;r.classList.toggle("dark",a.resolvedTheme==="dark");r.classList.toggle("light",a.resolvedTheme==="light")}}}catch{}` }} />
        {/* Stable head links are recolored by the palette engine. */}
        <link id="phoenix-favicon" rel="icon" href="/favicon.svg" type="image/svg+xml" sizes="any" />
        <link id="phoenix-apple-icon" rel="apple-touch-icon" href="/brand/phoenix-logo.png" sizes="1536x1024" />
        <link id="phoenix-manifest" rel="manifest" href="/manifest.json" />
        <script dangerouslySetInnerHTML={{ __html: 'try{document.documentElement.dataset.motion=localStorage.getItem("phoenix.motion")==="reduce"?"reduce":"system"}catch{}' }} />
        {/* Sync <html lang> from persisted UI locale before hydration (FishCodeTech#22). */}
        <script dangerouslySetInnerHTML={{ __html: 'document.documentElement.lang="zh-CN";document.documentElement.setAttribute("xml:lang","zh-CN")' }} />
      </head>
      <body suppressHydrationWarning>
        <SchemeBoot />
        <Providers><WorkspaceAppShell>{children}</WorkspaceAppShell></Providers>
      </body>
    </html>
  );
}
