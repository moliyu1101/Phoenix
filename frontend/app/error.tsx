"use client";
import Link from "next/link";
export default function ErrorPage({reset}:{reset:()=>void}){return <main className="px-empty"><h1>页面暂时无法显示</h1><p>请重新加载页面，或返回解题工作台继续操作。</p><button className="px-admin-button" onClick={reset}>重新加载</button><Link className="px-text-button" href="/ctf">返回解题工作台</Link></main>;}
