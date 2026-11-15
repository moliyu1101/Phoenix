import Link from "next/link";
export default function NotFound(){return <main className="px-empty"><h1>找不到此页面</h1><p>页面地址可能已更改，或对应记录已被移除。</p><Link className="px-text-button" href="/ctf">返回解题工作台</Link></main>;}
