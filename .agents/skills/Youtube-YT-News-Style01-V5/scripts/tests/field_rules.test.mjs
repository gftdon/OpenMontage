// qc_field_rules.json <-> engine consistency, both ways:
//   A. every text field the engine can render (every <TextField id=... lane=... role=...>) has a rule, with the same tier,
//      and its lane is one the rule allows;
//   B. no rule and no rule lane refers to something the engine cannot render (no dead id, no unknown lane).
// The engine is read as source text (it renders through React; the TextField call sites are the contract).
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { loadFieldRules, resolveFieldRule } from '../qc_layout_eval.mjs';
import { enginePath, loadEngine } from './_engine_bundle.mjs';

const rules = loadFieldRules();
const source = fs.readFileSync(enginePath, 'utf8');
const { LANES } = await loadEngine();

// ---- TextField call sites: brace-aware attribute scan -------------------------------------------------------------
function textFieldSites(src) {
  const sites = [];
  const open = /<TextField\b/g;
  let m;
  while ((m = open.exec(src))) {
    let i = m.index + m[0].length, depth = 0, attrs = '';
    for (; i < src.length; i++) {
      const c = src[i];
      if (c === '{') depth++;
      else if (c === '}') depth--;
      else if (c === '>' && depth === 0) break;
      attrs += c;
    }
    sites.push(attrs);
  }
  return sites;
}
const attrOf = (attrs, name) => {
  const at = attrs.search(new RegExp(`(^|\\s)${name}=`));
  if (at < 0) return null;
  let i = attrs.indexOf('=', at) + 1;
  if (attrs[i] === '"') return attrs.slice(i, attrs.indexOf('"', i + 1) + 1);   // keeps the quotes: literals() reads it
  let depth = 0, out = '';
  for (; i < attrs.length; i++) {
    const c = attrs[i];
    if (c === '{') { depth++; if (depth === 1) continue; }
    if (c === '}') { depth--; if (depth === 0) break; }
    out += c;
  }
  return out;
};
// All string / template literals of an expression: "x" -> x, `typo-line-${i}` -> typo-line-0 (a concrete sample).
// `${k}` is the vs side: it expands to both "left" and "right"; every other placeholder is a number (0).
const expand = text => (/\$\{k\}/.test(text) ? ['left', 'right'].flatMap(k => expand(text.replace('${k}', k))) : [text.replace(/\$\{[^}]*\}/g, '0')]);
const literals = expr => [...expr.matchAll(/"([^"]*)"|`([^`]*)`/g)].flatMap(x => expand(x[1] ?? x[2]));
// The two lane identifiers the engine computes from a "split" | "wide" prefix.
const LANE_VARS = { urlId: ['split.chrome.url', 'wide.chrome.url'], labelId: ['split.chrome.label', 'wide.chrome.label'] };

const sites = textFieldSites(source).map(attrs => {
  const idExpr = attrOf(attrs, 'id'), laneExpr = attrOf(attrs, 'lane'), roleExpr = attrOf(attrs, 'role');
  assert.ok(idExpr && laneExpr, `TextField without id/lane: ${attrs.slice(0, 80)}`);
  const lanes = /^[A-Za-z_]+$/.test(laneExpr.trim()) ? LANE_VARS[laneExpr.trim()] : literals(laneExpr);
  assert.ok(lanes?.length, `unresolved lane expression "${laneExpr}" (extend LANE_VARS)`);
  const ids = literals(idExpr);
  // the generic wrapper declaration `id: string` is not a call site; a call site always names its id
  return { ids, lanes, tier: roleExpr ? literals(roleExpr)[0] : 'read', size: Number(attrOf(attrs, 'size')) || null, attrs };
}).filter(s => s.ids.length);

test('the scan finds the engine text fields (sanity: not an empty pass)', () => {
  const ids = new Set(sites.flatMap(s => s.ids));
  for (const id of ['brand', 'kicker', 'caption', 'headline', 'description', 'cta', 'end-cta', 'source-url', 'typo-title', 'typo-num-0', 'vs-sep', 'stat-big-0-0', 'stat-label-0-0', 'vs-left-badge', 'vs-right-title', 'lower-sub']) assert.ok(ids.has(id), `${id} not found in the engine`);
  assert.ok(sites.length >= 25, `only ${sites.length} TextField call sites found`);
});

test('A. every engine text field has a rule with the same tier, and its lane is allowed', () => {
  for (const s of sites) {
    for (const id of s.ids) {
      const rule = resolveFieldRule(rules, id);
      assert.ok(rule, `engine field "${id}" has no rule in qc_field_rules.json`);
      assert.equal(rule.tier, s.tier, `"${id}": engine tier ${s.tier}, rule tier ${rule.tier}`);
      for (const lane of s.lanes) assert.ok(rule.lanes.includes(lane), `"${id}" renders in lane ${lane}, rule allows ${rule.lanes}`);
    }
  }
});

test('B. no rule is dead: every rule key matches an engine field, every rule lane is an engine text lane used by it', () => {
  const concrete = sites.flatMap(s => s.ids.map(id => ({ id, lanes: s.lanes })));
  for (const [key, rule] of Object.entries(rules)) {
    if (key.startsWith('_')) continue;
    const hit = concrete.filter(c => key.endsWith('*') ? c.id.startsWith(key.slice(0, -1)) : c.id === key);
    assert.ok(hit.length, `rule "${key}" matches no engine field`);
    // the rule key must be the one the resolver picks for at least one of those fields (an exact key can shadow a pattern)
    assert.ok(hit.some(c => resolveFieldRule(rules, c.id) === rule), `rule "${key}" is shadowed by another rule for every field it matches`);
    assert.ok(Number.isInteger(rule.maxLines) && rule.maxLines >= 1, key);
    for (const lane of rule.lanes) {
      assert.ok(LANES[lane], `rule "${key}" names lane ${lane}, which is not in LANES`);
      assert.equal(LANES[lane].role, 'text', `rule "${key}": lane ${lane} is not a text lane`);
      assert.ok(hit.some(c => c.lanes.includes(lane)), `rule "${key}" allows lane ${lane} but no matching engine field renders there`);
    }
  }
});

test('B. every engine text lane is used by some rule (no unused lane in LANES)', () => {
  const used = new Set(Object.entries(rules).filter(([k]) => !k.startsWith('_')).flatMap(([, r]) => r.lanes));
  for (const [id, l] of Object.entries(LANES)) if (l.role === 'text') assert.ok(used.has(id), `text lane ${id} is used by no rule`);
});

test('minimum sizes: no TextField asks for less than label 30 px / read 38 px, and the clamp in TextField is there', () => {
  assert.match(source, /const MIN_PX = \{ label: 30, read: 38 \} as const;/);
  assert.match(source, /Math\.max\(size \?\? MIN_PX\[role\], MIN_PX\[role\]\)/);
  for (const s of sites) if (s.size !== null) assert.ok(s.size >= (s.tier === 'label' ? 30 : 38), `${s.ids}: size ${s.size} below the tier minimum`);
});

test('the rules file is no longer provisional and its rules are well formed', () => {
  assert.doesNotMatch(rules._status, /^provisional/);
  for (const [key, rule] of Object.entries(rules)) {
    if (key.startsWith('_')) continue;
    assert.ok(['read', 'label'].includes(rule.tier), key);
    assert.ok(Array.isArray(rule.lanes) && rule.lanes.length > 0, key);
  }
});

test('the resolver self-test: a wrong tier or lane in a rule would be caught by A (mutation check)', () => {
  const mutated = { ...rules, 'typo-*': { ...rules['typo-*'], tier: 'label' } };
  const site = sites.find(s => s.ids.some(id => id.startsWith('typo-line')));
  assert.notEqual(resolveFieldRule(mutated, 'typo-line-0').tier, site.tier);
  assert.equal(resolveFieldRule(rules, 'typo-eyebrow').tier, 'label', 'the exact key beats the typo-* pattern');
  assert.equal(resolveFieldRule(rules, 'vs-left-badge').tier, 'label');
  assert.equal(resolveFieldRule(rules, 'vs-left-title').tier, 'read');
  assert.equal(resolveFieldRule(rules, 'stat-big-3-1').tier, 'read');
  assert.equal(resolveFieldRule(rules, 'stat-label-3-1').tier, 'label');
});
