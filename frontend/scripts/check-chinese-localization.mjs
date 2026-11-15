import fs from 'node:fs';import path from 'node:path';import vm from 'node:vm';
import assert from 'node:assert/strict';import {fileURLToPath} from 'node:url';import ts from 'typescript';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const source=fs.readFileSync(path.join(root,'lib/i18n.tsx'),'utf8'),sf=ts.createSourceFile('i18n.tsx',source,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX),signatures={},values={};
function walk(node){if(ts.isPropertyAssignment(node)&&node.name.getText(sf)==='zh'&&ts.isStringLiteral(node.initializer)){const key=node.parent.parent.name.text,text=node.initializer.text;signatures[key]=[...text.matchAll(/\{([A-Za-z][A-Za-z0-9_]*)\}/g)].map(x=>x[1]).sort();values[key]=text;}ts.forEachChild(node,walk);}walk(sf);
assert.deepEqual(signatures,JSON.parse(fs.readFileSync(path.join(root,'scripts/fixtures/chinese-placeholders.json'),'utf8')),'Translation must preserve every original interpolation parameter and message key');
for(const [key,value] of Object.entries(values)){const text=value.replace(/\{[^}]*\}|`[^`]*`/g,'');assert(!/\b(?:Worker|Agent|Planner|Distiller|Fact|Step|Goal|Token|Profile)\b/.test(text),`Untranslated interface term: ${key}`);}
const code=ts.transpileModule(fs.readFileSync(path.join(root,'lib/phoenix-labels.ts'),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2020}}).outputText;
const module={exports:{}};vm.runInNewContext(code,{module,exports:module.exports});const {uiLabel,roleLabels,workerDisplayName,localizedError}=module.exports;
assert.equal(uiLabel('reviewer'),'复核器');assert.equal(uiLabel('settled'),'已结算');assert.equal(uiLabel('fact_record'),'记录事实');assert.equal(uiLabel('web'),'网站安全');assert.equal(uiLabel('draft'),'草稿');
assert.equal(uiLabel('deepseek-v4.1-flash-1017'),'deepseek-v4.1-flash-1017');assert.equal(workerDisplayName('自定义 Worker 名称'),'自定义 Worker 名称');
const roles=['analyst','reviewer'];assert.equal(roleLabels(roles),'分析员 / 复核器');assert.deepEqual(roles,['analyst','reviewer']);
assert.equal(localizedError('Target is outside the explicit challenge scope',403),'此地址不在本题的目标范围内，请检查题目目标。');assert.equal(localizedError('Failed to fetch'),'网络连接失败，请检查服务是否正常运行。');
assert.match(localizedError([{loc:['body','title'],type:'missing',msg:'Field required'}],422),/题目名称.*不能为空/);
console.log(JSON.stringify({message_keys:Object.keys(signatures).length,interpolation_signatures_preserved:true,display_only_labels_and_original_values:'passed',error_localization:'passed'},null,2));
