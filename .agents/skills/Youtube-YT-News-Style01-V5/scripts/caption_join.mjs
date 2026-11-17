import {createHash} from 'node:crypto';
import fs from 'node:fs';
import {pathToFileURL} from 'node:url';
export const CAPTION_ALGORITHM_VERSION='a44-exact-icu-start-6';
const whitespace=c=>/\s/u.test(c);
export const activeChunk=(chunk,t)=>t>=chunk.displayStart&&t<chunk.displayEnd;
/** Exact script is authoritative for whitespace; ASR whitespace is not semantic.
 * ICU is lexical, not a Thai semantic parser. Phrase coalescing is pause/width based.
 * lexicalOverrides only joins exact brand spans, never replaces characters.
 */
export function buildCaptionPages(timedTokens,exactScript,options={}){
  const {maxUnits=30,maxDuration=3.5,pause=.45,lexicalOverrides=['GPT-Image-2.6','บอกว่า']}=options;
  const positions=[],aligned=[];let offset=0,previousStart=-Infinity;
  const fail=(message,extra={})=>{const diagnostics={scriptOffset:offset,unmatchedCharacters:1,...extra};const e=new Error(message);e.code='CAPTION_ALIGNMENT_MISMATCH';e.diagnostics=diagnostics;throw e;};
  for(const [index,token] of timedTokens.entries()){
    if(!Number.isFinite(token.s)||!Number.isFinite(token.e)||token.s<0||token.e<token.s||token.s<previousStart)throw new Error(`invalid timestamp at token ${index}`);
    previousStart=token.s;
    const start=positions.length;
    for(const character of token.w){
      if(whitespace(character))continue;
      while(offset<exactScript.length&&whitespace(exactScript[offset]))offset++;
      if(!exactScript.startsWith(character,offset))fail('caption/script character mismatch',{tokenIndex:index,expected:exactScript.slice(offset,offset+8),actual:character});
      positions.push({offset,index});offset+=character.length;
    }
    if(positions.length>start)aligned.push({index,token});
  }
  const trailingStart=offset;
  while(offset<exactScript.length&&whitespace(exactScript[offset]))offset++;
  if(offset!==exactScript.length)fail('unmatched script characters');
  let segments=[...new Intl.Segmenter('th',{granularity:'word'}).segment(exactScript)].map(s=>({start:s.index,end:s.index+s.segment.length}));
  // Lead-approved bounded quantity + classifier list, not a semantic parser.
  const quantity=/(?:[0-9]+(?:\.[0-9]+)?|(?:หนึ่ง|สอง|สาม|สี่|ห้า|หก|เจ็ด|แปด|เก้า|สิบ|ร้อย|พัน|หมื่น|แสน|ล้าน)+)[\t  ]*(?:วินาที|นาที|ชั่วโมง|วัน|เท่า|เปอร์เซ็นต์|บาท|ครั้ง|ภาพ|ตัว)/gu;
  const pairs=[...exactScript.matchAll(quantity)].map(m=>m[0]);
  // Union overlapping spans; never discard the uncovered prefix/suffix of an ICU word.
  for(const brand of [...lexicalOverrides,...pairs]){let at=exactScript.indexOf(brand);while(at!==-1){const end=at+brand.length;const touched=segments.filter(s=>s.start<end&&s.end>at);if(touched.length){const start=Math.min(at,...touched.map(s=>s.start)),stop=Math.max(end,...touched.map(s=>s.end));segments=segments.filter(s=>s.end<=start||s.start>=stop).concat({start,end:stop}).sort((a,b)=>a.start-b.start);}at=exactScript.indexOf(brand,end);}}
  // ASR may split inside an ICU word, or span multiple ICU words. Merge connected
  // spans so no sub-word timing is fabricated and no input token is duplicated.
  const tokenRanges=aligned.map(({index,token})=>{const p=positions.filter(p=>p.index===index);return {index,token,start:p[0].offset,end:p.at(-1).offset+String.fromCodePoint(exactScript.codePointAt(p.at(-1).offset)).length};});
  const units=[];let pending='';
  for(let i=0;i<segments.length;i++){
    let {start,end}=segments[i];
    if(/^\s+$/u.test(exactScript.slice(start,end))){pending+=exactScript.slice(start,end);continue;}
    let refs=tokenRanges.filter(r=>r.start<end&&r.end>start);
    let expanded=true;while(expanded){expanded=false;const target=Math.max(end,...refs.map(r=>r.end));while(i+1<segments.length&&segments[i+1].start<target){end=segments[++i].end;expanded=true;}refs=tokenRanges.filter(r=>r.start<end&&r.end>start);}
    if(!refs.length)fail('untimed script segment',{scriptOffset:start});
    const text=exactScript.slice(start,end),s=Math.min(...refs.map(r=>r.token.s)),e=Math.max(...refs.map(r=>r.token.e));
    units.push({text,spaceBefore:pending,tokens:[{w:text,s,e}],sourceTokens:refs.map(r=>({...r.token})),merged_from:refs.map(r=>r.index),scriptStart:start,scriptEnd:end});pending='';
  }
  // Attach dependent closing marks, and merge simultaneous starts into one visible
  // display group. Original timing tokens remain untouched in `sourceTokens`.
  // absorb(prev,u,i): u (= units[i]) becomes part of prev's display group; prev keeps its own start.
  const absorb=(prev,u,i)=>{
    const text=prev.text+u.spaceBefore+u.text;
    prev.sourceTokens??=prev.tokens;prev.sourceTokens=prev.sourceTokens.concat(u.sourceTokens??u.tokens);
    prev.tokens=[{w:text,s:prev.tokens[0].s,e:Math.max(...prev.sourceTokens.map(t=>t.e))}];prev.text=text;prev.scriptEnd=u.scriptEnd;prev.merged_from.push(...u.merged_from);units.splice(i,1);
  };
  for(let i=1;i<units.length;){
    const u=units[i],prev=units[i-1];
    if(/\n/u.test(u.spaceBefore)){
      if(u.tokens[0].s===prev.tokens[0].s){
        // start-6: the aligner collapsed the last word of a line onto the start of the next line, so that word's own
        // display window is empty. It joins the display group of the word before it ON THE SAME LINE: no timestamp is
        // invented, no word is dropped and the line break stays. A word that is alone on its line still fails closed.
        const before=units[i-2];
        if(!before||/\n/u.test(prev.spaceBefore))throw new Error('unsupported simultaneous starts across newline; explicit display group required, no words dropped');
        absorb(before,prev,i-1);i--;continue;
      }
      i++;continue;
    }
    if(/^[ๆฯ)\]}.!?。！？,;:]+$/u.test(u.text)||u.tokens[0].s===prev.tokens[0].s)absorb(prev,u,i);
    else i++;
  }
  for(const [i,unit] of units.entries()){
    const explicit=options.phraseBounds?.find(b=>b.scriptEnd===unit.scriptEnd);
    const next=units[i+1];
    const bound=explicit?.end??next?.tokens[0].s??options.endTime;
    if(!Number.isFinite(bound)||bound<unit.tokens[0].s||(next&&bound>next.tokens[0].s))throw new Error('explicit phrase/endTime bound required; cannot use word tail');
    unit.displayStart=unit.tokens[0].s;unit.displayEnd=bound;
    unit.displayBoundReason=explicit?.reason??(next?'next lexical word start':'explicit narration media endTime');
  }
  const graphemes=new Intl.Segmenter('th',{granularity:'grapheme'});
  const size=s=>[...graphemes.segment(s)].length;
  const width=group=>size(group.map((c,i)=>(i?c.spaceBefore:'')+c.text).join(''));
  const fits=group=>width(group)<=maxUnits&&group.at(-1).displayStart-group[0].displayStart<=maxDuration;
  const groups=[];let chunks=[];
  const flush=()=>{if(chunks.length)groups.push(chunks);chunks=[];};
  for(const unit of units){
    const last=chunks.at(-1);
    const startGap=last?unit.displayStart-last.displayStart:0;
    // Observed start-gap is a heuristic, NOT a measurement of silence. Keep all
    // preceding words together until the observed next start / explicit bound.
    const pauseBreak=last&&chunks.length>=2&&startGap>pause;
    if(last&&(/\n/u.test(unit.spaceBefore)||pauseBreak||/[.!?。！？]$/u.test(last.text)))flush();
    if(chunks.length&&!fits([...chunks,unit])){
      let split=-1;
      for(let i=1;i<chunks.length;i++)if(chunks[i].spaceBefore&&fits([...chunks.slice(i),unit]))split=i;
      if(split>0){const tail=chunks.slice(split);chunks=chunks.slice(0,split);flush();chunks=tail;}else flush();
    }
    chunks.push(unit);
  }flush();
  // Rebalance a one-word tail only if neither hard line/pause boundaries nor
  // width/start-duration limits are weakened.
  for(let i=1;i<groups.length;i++){
    const prev=groups[i-1],current=groups[i];
    if(current.length===1&&prev.length>2&&!/\n/u.test(current[0].spaceBefore)&&current[0].displayStart-prev.at(-1).displayStart<=pause&&fits([prev.at(-1),...current]))current.unshift(prev.pop());
  }
  const pages=groups.map(group=>{
    const leadingWhitespace=group[0].spaceBefore;
    const displayChunks=group.map((c,i)=>({...c,displaySpaceBefore:i===0?'':c.spaceBefore}));
    return {start:group[0].displayStart,end:group.at(-1).displayEnd,boundReason:group.at(-1).displayBoundReason,text:group.map(c=>c.spaceBefore+c.text).join(''),leadingWhitespace,displayText:displayChunks.map(c=>c.displaySpaceBefore+c.text).join(''),chunks:displayChunks,words:group.flatMap(c=>c.tokens)};
  });
  if(pages.length)pages.at(-1).text+=pending;
  const reconstructed=pages.map(p=>p.text).join('');
  if(reconstructed!==exactScript)fail('lossless caption invariant failed');
  return {schema:1,algorithm:CAPTION_ALGORITHM_VERSION,inputSha256:createHash('sha256').update(JSON.stringify({timedTokens,exactScript,options})).digest('hex'),pages,trailingSpace:pending,diagnostics:{unmatchedCharacters:0,inputTokens:timedTokens.length,chunks:units.length,mergedChunks:units.filter(u=>u.merged_from.length>1).length,scriptCharacters:exactScript.length,timingEnd:timedTokens.at(-1)?.e??0,semanticPhraseGuarantee:false}};
}

export function generateCaptionModule(result){
 return `export interface CaptionWord {w:string;s:number;e:number}
export interface CaptionChunk {text:string;spaceBefore:string;displaySpaceBefore:string;tokens:CaptionWord[];sourceTokens?:CaptionWord[];merged_from:number[];scriptStart:number;scriptEnd:number;displayStart:number;displayEnd:number;displayBoundReason:string}
export interface CaptionPage {start:number;end:number;text:string;leadingWhitespace:string;displayText:string;boundReason:string;chunks:CaptionChunk[];words:CaptionWord[]}
export const CAPTION_PROVENANCE=${JSON.stringify({algorithm:result.algorithm,inputSha256:result.inputSha256,diagnostics:result.diagnostics})};
export const CAPTION_PAGES:CaptionPage[]=${JSON.stringify(result.pages)};
`;
}
if(process.argv[1]&&import.meta.url===pathToFileURL(process.argv[1]).href){
 const args=process.argv.slice(2),get=key=>args[args.indexOf(key)+1];
 // V4: the engine reads the --out JSON directly (episode data, no per-episode TSX), so there is no --module any more.
 if(args.includes('--module')){console.error('caption_join: --module is not supported in V4 (no per-episode TSX); the engine reads the --out JSON');process.exit(2);}
 for(const flag of ['--tokens','--script','--options','--out'])if(!args.includes(flag)){console.error('caption_join: missing '+flag);process.exit(2);}
 const data=JSON.parse(fs.readFileSync(get('--tokens'),'utf8'));
 const tokens=data.flatMap(p=>p.words??[p]);
 const result=buildCaptionPages(tokens,fs.readFileSync(get('--script'),'utf8'),JSON.parse(fs.readFileSync(get('--options'),'utf8')));
 fs.writeFileSync(get('--out'),JSON.stringify(result,null,2)+'\n');
}
