import test from 'node:test';import assert from 'node:assert/strict';import fs from 'node:fs';import path from 'node:path';
test('only cutaways reset Loop to ceil beat start; avatar remains global',()=>{
 const root=path.resolve(new URL('../../../../..',import.meta.url).pathname),s=fs.readFileSync(root+'/remotion-composer/src/YtNewsStyle01V4.tsx','utf8');
 assert.match(s,/const beatStartFrame=Math\.ceil\(beat\.t\*fps\)/);assert.match(s,/<Sequence from=\{beatStartFrame\} layout="none"><Loop/);assert.match(s,/<\/Loop><\/Sequence>/);
 const avatar=s.slice(s.indexOf('<OffthreadVideo muted src={staticFile(`${EPISODE.assetDir}/avatar_source.mp4`)}'));assert.ok(!avatar.slice(0,500).includes('Sequence'));
});
