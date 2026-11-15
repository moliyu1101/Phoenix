/** Offline source checks. Not a complete Next.js build or browser test. */
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';
import assert from 'node:assert/strict';
const require=createRequire(import.meta.url);
const ts=require(process.env.TYPESCRIPT_PATH || 'typescript');
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const walk=dir=>fs.readdirSync(dir,{withFileTypes:true}).flatMap(e=>{
 if(['node_modules','.next','.git','scripts'].includes(e.name))return [];
 const p=path.join(dir,e.name);return e.isDirectory()?walk(p):[p];
});
const files=walk(root).filter(p=>/\.(ts|tsx|mts|cts)$/.test(p)&&!p.endsWith('.d.ts'));
const failures=[];let imports=0;
for(const filename of files){
 const source=fs.readFileSync(filename,'utf8');
 const sf=ts.createSourceFile(filename,source,ts.ScriptTarget.Latest,true);
 for(const d of sf.parseDiagnostics)failures.push(ts.flattenDiagnosticMessageText(d.messageText,'\n')+' in '+filename);
 const output=ts.transpileModule(source,{fileName:filename,reportDiagnostics:true,compilerOptions:{target:ts.ScriptTarget.ES2020,module:ts.ModuleKind.ESNext,jsx:ts.JsxEmit.Preserve,isolatedModules:true}});
 for(const d of output.diagnostics||[])if(d.category===ts.DiagnosticCategory.Error)failures.push(ts.flattenDiagnosticMessageText(d.messageText,'\n')+' in '+filename);
 for(const entry of ts.preProcessFile(source,true,true).importedFiles){
  const n=entry.fileName;if(!n.startsWith('.')&&!n.startsWith('@/'))continue;imports++;
  const target=n.startsWith('@/')?path.join(root,n.slice(2)):path.resolve(path.dirname(filename),n);
  if(!['','.ts','.tsx','.js','.mjs','.json','.css','/index.ts','/index.tsx','/index.js'].some(s=>fs.existsSync(target+s)))failures.push('Unresolved import '+n+' in '+path.relative(root,filename));
 }
}
assert.equal(failures.length,0,failures.join('\n'));
const temp=fs.mkdtempSync(path.join(os.tmpdir(),'phoenix-ts-'));
try{
 const program=ts.createProgram([path.join(root,'lib/phoenixProjection.ts')],{target:ts.ScriptTarget.ES2020,module:ts.ModuleKind.CommonJS,strict:true,skipLibCheck:true,outDir:temp,noEmitOnError:true,types:[]});
 const diagnostics=ts.getPreEmitDiagnostics(program);
 assert.equal(diagnostics.length,0,ts.formatDiagnosticsWithColorAndContext(diagnostics,{getCurrentDirectory:()=>root,getCanonicalFileName:n=>n,getNewLine:()=> '\n'}));
 assert.equal(program.emit().emitSkipped,false);
 const {projectPhoenix}=require(path.join(temp,'phoenixProjection.js'));
 const run={id:'run-fixture',state:'running',created:100,updated:120,billed_usd:0};
 const tasks=[{id:'a',key:'decode',goal:'decode evidence',role:'solver',state:'done',dependencies:[],worker_id:'solver-a',started:101,ended:110,priority:1},{id:'b',key:'review',goal:'independent check',role:'reviewer',state:'running',dependencies:['decode'],worker_id:'reviewer',started:111,priority:0}];
 const worker=(id,roles,active)=>({id,name:id,roles,enabled:true,status:active.length?'working':'standby',active_task_ids:active,profiles:{solver:{model:'model-'+id}},usage:{input_tokens:30,output_tokens:20,priced_cost_usd:null,unpriced_calls:1}});
 const detail={run,tasks,model_calls:[{input_tokens:60,output_tokens:40}],facts:[{id:'fact',task_id:'a',statement:'original decoded',stance:'supported',citations:'[{"evidence_id":"ev-one"}]',created:109}],candidates:[{status:'unverified',value:'flag{decoy}'},{status:'accepted',value:'flag{fixture}'}],events:[{seq:2,task_id:'a',kind:'fact.added',payload:'{}',created:109},{seq:1,kind:'run.started',payload:'{}',created:100}]};
 const swarm={tasks,workers:[worker('solver-a',['solver'],[]),worker('reviewer',['reviewer'],['b'])]};
 const deck=projectPhoenix(detail,swarm,{title:'Native fixture',category:'misc',targets:[]});
 let checks=0;const eq=(a,b)=>{assert.deepEqual(a,b);checks++;};
 eq(deck.runId,'run-fixture');eq(deck.challengeName,'Native fixture');eq(Object.keys(deck.lanes).length,2);
 eq(deck.lanes.reviewer.intentId,'review');eq(deck.lanes.reviewer.model,'model-reviewer');eq(deck.lanes.reviewer.role,'review');
 eq(deck.blackboard.intents[1].dependsOn,['decode']);eq(deck.blackboard.intents[1].worker,'reviewer');
 eq(deck.blackboard.facts[0].verified,false);eq(deck.blackboard.facts[0].actor,'solver-a');eq(deck.blackboard.facts[0].provenance.artifactRefs[0].artifactId,'ev-one');
 eq(deck.flags,['flag{fixture}']);eq(deck.solved,false);eq(deck.finished,false);eq(deck.tokensIn,60);eq(deck.tokensOut,40);eq(deck.costBySolver['solver-a'].unpricedCalls,1);
 eq(deck.chat[0].role,'system');eq(deck.chat[1].role,'agent');eq(deck.chat[1].solverId,'solver-a');
 eq(deck.blackboard.observations.length,1);eq(deck.blackboard.observations[0].admitted,false);eq(deck.runtimeEvents.length,2);
 const handoff=projectPhoenix({...detail,evidence_handoffs:[{target_task_id:'b',source_task_id:'a',evidence_id:'ev-one'}]},swarm,{});eq(handoff.blackboard.intents[1].fromFacts,[1]);eq(deck.blackboard.intents[1].fromFacts,[]);
 const paused=projectPhoenix({...detail,run:{...run,state:'paused'}},swarm,{});eq(paused.finished,false);

 const done=projectPhoenix({...detail,run:{...run,state:'solved'}},swarm,{});eq(done.finished,true);eq(done.solved,true);
 const blank=projectPhoenix({run:{...run,state:'created'}},null,null);eq(Object.keys(blank.lanes).length,0);eq(blank.flags,[]);
 eq(JSON.parse(fs.readFileSync(path.join(root,'public/manifest.json'),'utf8')).start_url,'/ctf');
 console.log(JSON.stringify({mode:'SOURCE-ONLY; not full typecheck, build, browser or network E2E',syntax_files:files.length,local_imports:imports,projection_typecheck:'passed',projection_assertions:checks},null,2));
}finally{fs.rmSync(temp,{recursive:true,force:true});}
