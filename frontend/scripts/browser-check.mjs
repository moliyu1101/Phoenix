/** Real browser checks against the native API and retained Phoenix UI. */
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
const meta=process.argv[2]||'../.preview-data/preview.json';
const output=process.argv[3]||'../../delivery/previews';
const base=process.argv[4]||process.env.PHOENIX_UI_URL||'http://127.0.0.1:3012';
for(const [script,args] of [['browser-phoenix-check.mjs',[meta,output,base]],['browser-library-check.mjs',[output,base]],['browser-modes-check.mjs',[output,base]]]){
 const result=spawnSync(process.execPath,[fileURLToPath(new URL(script,import.meta.url)),...args],{stdio:'inherit'});
 if(result.status!==0)process.exit(result.status||1);
}
