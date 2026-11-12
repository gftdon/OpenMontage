import test from 'node:test';import assert from 'node:assert/strict';import fs from 'node:fs';import path from 'node:path';
test('only cutaways reset Loop to ceil beat start; avatar remains global',()=>{
 const root=path.resolve(new URL('../../../../..',import.meta.url).pathname),s=fs.readFileSync(root+'/remotion-composer/src/YtNewsStyle01V4.tsx','utf8');
 assert.match(s,/const layerStartFrame = Math\.ceil\(beat\.t \* fps\)/);
 assert.match(s,/<Sequence from=\{layerStartFrame\} layout="none"><Loop durationInFrames=\{L\} layout="none"><OffthreadVideo/);
 assert.match(s,/<\/Loop><\/Sequence>/);
 assert.match(s,/const L = Math\.max\(1, Math\.floor\(\(EPISODE\.brollDur\[src\] - from\) \* fps\) - 2\)/);
 assert.match(s,/trimBefore=\{Math\.round\(from \* fps\)\}/);
 assert.ok(!s.includes('startFrom='),'the deprecated startFrom prop must not be used');
 const avatar=s.slice(s.indexOf('<OffthreadVideo muted src={staticFile(`${EPISODE.assetDir}/${EPISODE.avatarFile}`)}'));assert.ok(avatar.length>0,'avatar OffthreadVideo not found');assert.ok(!avatar.slice(0,500).includes('Sequence'));
});
