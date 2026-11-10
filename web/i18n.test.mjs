import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { parseHTML } from 'linkedom';
import { messages } from './messages.js';
import { detectLocale, setLocale, getLocale, normalizeLocale, STORAGE_KEY, mountLocaleControl } from './i18n.js';
import { mountLaunch } from './screens/launch.js';
import { mountDebugger } from './screens/debugger.js';
import { FIXTURES } from './screens/debugger.dev.fixtures.js';

function environment(url = 'https://example.test/debug/?other=1#memory', saved = null, languages = ['fr', 'zh-CN']) {
  const values = new Map(saved ? [[STORAGE_KEY, saved]] : []);
  const env = { location: { href: url }, navigator: { languages },
    localStorage: { getItem: key => values.get(key), setItem: (key, value) => values.set(key, value) },
    history: { state: { preserved: true }, replaceState(state, _, href) { assert.deepEqual(state, {preserved:true}); env.location.href = href; } } };
  return { env, values };
}
function dom() {
  const {document, window} = parseHTML('<!doctype html><html><head></head><body><main id="app"></main></body></html>');
  globalThis.document = document;
  return { document, window, root: document.getElementById('app') };
}

test('catalog parity and complete English messages', () => {
  for (const [key, value] of Object.entries(messages)) {
    assert.deepEqual(Object.keys(value).sort(), ['en', 'zh'], key);
    assert.equal(typeof value.en, 'string'); assert.equal(typeof value.zh, 'string');
    assert.doesNotMatch(value.en, /[\u3400-\u9fff]/u, key);
  }
  for (const file of ['screens/launch.js', 'screens/debugger.js']) {
    for (const [, key] of readFileSync(new URL(file, import.meta.url), 'utf8').matchAll(/tr\("([^"]+)"\)/g)) assert.ok(messages[key], key);
  }
});
test('query, saved preference, browser languages, unsupported and blocked storage', () => {
  assert.equal(detectLocale(environment('https://e.test/?lang=en', 'zh').env), 'en');
  assert.equal(detectLocale(environment('https://e.test/?lang=bogus', 'en').env), 'en');
  assert.equal(detectLocale(environment().env), 'zh');
  assert.equal(detectLocale(environment('https://e.test/', null, ['fr']).env), 'en');
  assert.equal(normalizeLocale('ZH-cn'), 'zh');
  const {env} = environment();
  Object.defineProperty(env, 'localStorage', {get() {throw Error('blocked');}});
  assert.equal(detectLocale(env), 'zh');
  assert.doesNotThrow(() => setLocale('en', env));
  assert.equal(detectLocale(env), 'en');
  assert.equal(setLocale('bad', env), false);
});
test('manual preference updates share URL without losing query/hash, stores language only', () => {
  const {env,values} = environment('https://example.test/debug/?lang=en&other=1#memory');
  setLocale('zh', env);
  assert.equal(detectLocale(env), 'zh');
  assert.equal(new URL(env.location.href).searchParams.get('other'), '1');
  assert.equal(new URL(env.location.href).hash, '#memory');
  assert.deepEqual([...values], [[STORAGE_KEY, 'zh']]);
});
test('launch switching preserves exact textarea node, draft, boot and open errors; destroy unsubscribes', async () => {
  const {root,window,document} = dom(); setLocale('zh');
  const loads=[];
  const view=await mountLaunch(root,{fetchManifest: async()=>({programs:[{file:'hello.mal',cells:12,steps:39}]}),onLoad:(...args)=>loads.push(args)});
  const textarea=root.querySelector('textarea');
  root.querySelector('.mb-load-btn').click();
  assert.match(root.querySelector('.mb-drop-error').textContent,/还没有代码/);
  setLocale('en');
  assert.match(root.querySelector('.mb-drop-error').textContent,/No code/);
  textarea.value='用户代码 <script> never translate';
  view.setBootPhase('wheel');
  for(const locale of ['zh','en','zh','en'])setLocale(locale);
  assert.equal(root.querySelector('textarea'),textarea);
  assert.equal(textarea.value,'用户代码 <script> never translate');
  assert.match(root.querySelector('.mb-boot').textContent,/Unpacking/);
  assert.match(root.textContent,/Load and debug/);
  assert.doesNotMatch(root.textContent.replace(textarea.textContent,''),/[\u3400-\u9fff]/);
  root.querySelector('.mb-load-btn').dispatchEvent(new window.Event('click'));
  assert.deepEqual(loads,[[textarea.value,'']]);
  const html=root.innerHTML;view.destroy();setLocale('zh');assert.equal(root.innerHTML,html);
});
test('debugger switches paused, running, stopped, selected memory and raw output without commands or state changes', () => {
  const {root} = dom();setLocale('zh');
  const commands=[]; const subs=new Map();
  const session={lastSnapshot:structuredClone(FIXTURES.paused),on:(name,fn)=>{subs.set(name,fn);return ()=>subs.delete(name);}};
  for(const name of ['step','back','run','stop','reset','snapshot','seek','breakpoint','watchpoint'])session[name]=(...args)=>commands.push([name,...args]);
  const view=mountDebugger(root,session,{theme:'light',fileName:'用户程序.mal'});
  view.setOutput('原样输出 <b>hello</b>');
  view.state.selected=53;
  view.applyProgress({step:444});
  const before=JSON.stringify(view.state); const calls=commands.length;
  setLocale('en');assert.equal(JSON.stringify(view.state),before);assert.equal(commands.length,calls);
  assert.match(root.querySelector('.mb-step').textContent,/444/);
  assert.match(root.textContent,/Running/);
  assert.match(root.textContent,/Registers/);
  assert.equal(root.querySelector('.mb-out-box').textContent,'原样输出 <b>hello</b>');
  assert.equal(root.querySelector('.mb-file').textContent,'用户程序.mal');
  view.applyStopped({reason:'breakpoint',data:session.lastSnapshot});
  view.applyError({kind:'python',message:'后端原文 <script>bad</script>'});
  const after=JSON.stringify(view.state);
  for(const locale of ['zh','en','zh','en'])setLocale(locale);
  assert.equal(JSON.stringify(view.state),after);assert.equal(commands.length,calls);
  assert.match(root.querySelector('.mb-err').textContent,/后端原文 <script>bad<\/script>/);
  assert.equal(root.querySelector('.mb-err script'),null);
  assert.equal(view.state.theme,'light');assert.equal(view.state.selected,53);
  view.destroy();assert.equal(subs.size,0);setLocale('zh');assert.equal(root.innerHTML,'');
});

test('an example fetch failing after a switch reports the error in the current locale', async () => {
  const {root}=dom();setLocale('zh');
  const previousFetch=globalThis.fetch;let fail;
  globalThis.fetch=()=>new Promise((_,reject)=>{fail=reject;});
  let view;
  try {
    view=await mountLaunch(root,{fetchManifest:async()=>({programs:[{file:'hello.mal',cells:12,steps:39}]})});
    root.querySelector('[data-example]').click();
    setLocale('en');fail(Error('raw 中文 <b>detail</b>'));
    await new Promise(resolve=>setImmediate(resolve));
    const error=root.querySelector('.mb-drop-error');
    assert.equal(error.style.display,'block');
    assert.match(error.textContent,/Could not load hello.mal/);
    assert.match(error.textContent,/raw 中文 <b>detail<\/b>/);
    assert.equal(error.querySelector('b'),null);
    setLocale('zh');assert.match(root.querySelector('.mb-drop-error').textContent,/未能加载示例/);
  } finally {view?.destroy();globalThis.fetch=previousFetch;}
});

test('real snapshot fixtures translate dynamic text, tooltips and accessible labels', () => {
  const {root,window}=dom();
  for(const snapshot of Object.values(FIXTURES)) {
    setLocale('zh');
    const view=mountDebugger(root,{lastSnapshot:snapshot});
    setLocale('en');
    assert.doesNotMatch(root.textContent,/[\u3400-\u9fff]/);
    for(const node of root.querySelectorAll('[title],[aria-label],[aria-valuetext]')) {
      for(const attr of ['title','aria-label','aria-valuetext'])assert.doesNotMatch(node.getAttribute(attr)||'',/[\u3400-\u9fff]/);
    }
    const cell=root.querySelector('.mb-cell');
    cell.dispatchEvent(new window.Event('mouseover',{bubbles:true}));
    assert.equal(root.querySelector('.mb-tip').hidden,false);
    assert.match(root.querySelector('.mb-tip').textContent,/Value/);
    setLocale('zh');assert.match(root.querySelector('.mb-tip').textContent,/写入/);
    setLocale('en');assert.match(root.querySelector('.mb-tip').textContent,/Writes/);
    view.applyError({kind:'python',message:'后端原文'});
    assert.equal(root.querySelector('.mb-err button').getAttribute('aria-label'),'Dismiss message');
    setLocale('zh');assert.equal(root.querySelector('.mb-err button').getAttribute('aria-label'),'关闭消息');
    assert.match(root.querySelector('.mb-err').textContent,/后端原文/);
    view.destroy();
  }
});

test('locale control is labelled, updates document metadata and cleans up', () => {
  const {document,window,root}=dom(); const {env,values}=environment();env.document=document;
  setLocale('en',env);const destroy=mountLocaleControl(root,env);
  const select=root.querySelector('select');
  assert.equal(select.getAttribute('aria-label'),'Interface language');
  assert.equal(document.documentElement.lang,'en');assert.equal(document.title,'pyMalbolge Debugger');
  for(const option of select.options)option.selected=option.value==='zh';
  select.dispatchEvent(new window.Event('change'));
  assert.equal(getLocale(),'zh');assert.equal(document.documentElement.lang,'zh-CN');
  assert.equal(select.getAttribute('aria-label'),'界面语言');assert.equal(values.get(STORAGE_KEY),'zh');
  destroy();assert.equal(root.innerHTML,'');setLocale('en',env);assert.equal(root.innerHTML,'');
});
