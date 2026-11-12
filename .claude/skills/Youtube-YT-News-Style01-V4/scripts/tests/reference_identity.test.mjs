import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
const root=path.resolve(new URL('../../../../..',import.meta.url).pathname);
const skill=path.resolve(new URL('../..',import.meta.url).pathname);
const src=(f)=>path.join(root,'remotion-composer/src',f);
const asset=(f)=>path.join(skill,'assets',f);
const same=(a,b)=>Buffer.compare(fs.readFileSync(a),fs.readFileSync(b))===0;

test('engine in remotion-composer/src is byte-identical to the skill reference copy',()=>{
 assert.ok(same(src('YtNewsStyle01V4.tsx'),asset('YtNewsStyle01V4.reference.tsx')),'YtNewsStyle01V4.tsx differs from assets/YtNewsStyle01V4.reference.tsx');
});
test('V4 entry in remotion-composer/src is byte-identical to the skill reference copy',()=>{
 assert.ok(same(src('ytNewsStyle01V4.entry.tsx'),asset('ytNewsStyle01V4.entry.reference.tsx')),'ytNewsStyle01V4.entry.tsx differs from assets/ytNewsStyle01V4.entry.reference.tsx');
});
test('the real entry registers only YtNewsStyle01V4 and imports nothing outside the V4 files (no Root / index)',()=>{
 const text=fs.readFileSync(src('ytNewsStyle01V4.entry.tsx'),'utf8');
 const code=text.split('\n').filter(l=>!/^\s*(\/\/|\/\*|\*)/.test(l)).join('\n');
 assert.equal((code.match(/<Composition\b/g)||[]).length,1);
 assert.equal((code.match(/registerRoot\(/g)||[]).length,1);
 assert.match(code,/<Composition id="YtNewsStyle01V4" component=\{YtNewsStyle01V4\} width=\{1920\} height=\{1080\} fps=\{25\}/);
 const specifiers=[...code.matchAll(/from\s+["']([^"']+)["']/g)].map(m=>m[1]).sort();
 assert.deepEqual(specifiers,['./YtNewsStyle01V4','./ytNewsStyle01V4Sample.json','./ytNewsStyle01V4SampleCaptions.json','remotion']);
 assert.match(text,/npx remotion studio src\/ytNewsStyle01V4\.entry\.tsx/);
});
test('sample episode and sample captions are byte-identical to their reference twins',()=>{
 assert.ok(same(src('ytNewsStyle01V4Sample.json'),asset('ytNewsStyle01V4Episode.reference.json')),'sample episode differs from its reference twin');
 assert.ok(same(src('ytNewsStyle01V4SampleCaptions.json'),asset('ytNewsStyle01V4Captions.reference.json')),'sample captions differ from their reference twin');
});
test('the migrated sample (fixtures/episodes/valid/sample-v1.json) is byte-identical to the src sample and its reference twin',()=>{
 const fixture=path.join(skill,'scripts/tests/fixtures/episodes/valid/sample-v1.json');
 assert.ok(same(fixture,src('ytNewsStyle01V4Sample.json')),'fixture sample-v1.json differs from remotion-composer/src/ytNewsStyle01V4Sample.json');
 assert.ok(same(fixture,asset('ytNewsStyle01V4Episode.reference.json')),'fixture sample-v1.json differs from assets/ytNewsStyle01V4Episode.reference.json');
});
test('engine keeps the measurement guard verbatim and holds no episode data literal',()=>{
 const engine=fs.readFileSync(src('YtNewsStyle01V4.tsx'),'utf8');
 assert.ok(engine.includes('||box.width<=0||box.height<=0'),'probe condition ||box.width<=0||box.height<=0 is missing');
 assert.doesNotMatch(engine,/const\s+BEATS\s*:\s*Beat\[\]\s*=\s*\[/);
 assert.doesNotMatch(engine,/const\s+EPISODE\s*=\s*\{/);
 assert.doesNotMatch(engine,/const\s+BROLL_DUR\s*:\s*Record<[^>]*>\s*=\s*\{/);
});
test('the old captions TypeScript module is gone',()=>{
 assert.ok(!fs.existsSync(src('ytNewsStyle01V4Captions.ts')));
 assert.ok(!fs.existsSync(asset('ytNewsStyle01V4Captions.reference.ts')));
});
