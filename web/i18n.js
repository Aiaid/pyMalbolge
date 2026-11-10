import { messages, semanticMessages } from './messages.js';

export const STORAGE_KEY = 'pymalbolge.language';
export function normalizeLocale(value) {
  if (typeof value !== 'string') return null;
  const primary = value.toLowerCase().split('-')[0];
  return primary === 'en' || primary === 'zh' ? primary : null;
}
// Storage, history and navigator can all be unavailable in private/sandboxed contexts.
export function detectLocale(env = globalThis) {
  let query, saved;
  try { query = normalizeLocale(new URL(env.location.href).searchParams.get('lang')); } catch {}
  try { saved = normalizeLocale(env.localStorage.getItem(STORAGE_KEY)); } catch {}
  let languages = [];
  try { languages = env.navigator.languages || [env.navigator.language]; } catch {}
  return query || saved || languages.map(normalizeLocale).find(Boolean) || 'en';
}
let locale = detectLocale();
const listeners = new Set();
export const getLocale = () => locale;
export function tr(key) {
  const message = messages[key];
  if (!message) throw new Error(`Unknown UI message: ${key}`);
  return message[locale];
}
export function semanticText(source) {
  return semanticMessages[source] ? tr(semanticMessages[source]) : source;
}
export function onLocaleChange(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}
function updateDocument(env) {
  if (!env.document) return;
  env.document.documentElement.lang = locale === 'zh' ? 'zh-CN' : 'en';
  env.document.title = locale === 'zh' ? 'pyMalbolge 调试器' : 'pyMalbolge Debugger';
  const meta = env.document.querySelector('meta[name="description"]');
  if (meta) meta.content = locale === 'zh'
    ? 'Malbolge 单步调试器：纯静态，Python 跑在 Web Worker 里，代码不离开浏览器。'
    : 'Malbolge step debugger: static, Python in a Web Worker, code stays in your browser.';
}
export function setLocale(value, env = globalThis) {
  const next = normalizeLocale(value);
  if (!next) return false;
  try { env.localStorage.setItem(STORAGE_KEY, next); } catch {}
  try {
    const url = new URL(env.location.href);
    url.searchParams.set('lang', next);
    env.history.replaceState(env.history.state, '', url.href);
  } catch {}
  const changed = locale !== next;
  locale = next;
  updateDocument(env);
  if (changed) for (const fn of listeners) fn(locale);
  return true;
}
// This control is outside the screen roots, so switching cannot replace it or
// destroy its focus, the session, or partially entered program text.
export function mountLocaleControl(container, env = globalThis) {
  const doc = container.ownerDocument;
  const label = doc.createElement('label');
  const caption = doc.createElement('span');
  const select = doc.createElement('select');
  label.className = 'mb-language';
  for (const [value, text] of [['en', 'English'], ['zh', '简体中文']]) {
    const option = doc.createElement('option');
    option.value = value; option.textContent = text; option.lang = value === 'zh' ? 'zh-CN' : 'en';
    select.append(option);
  }
  const refresh = () => {
    caption.textContent = locale === 'zh' ? '语言' : 'Language';
    select.setAttribute('aria-label', locale === 'zh' ? '界面语言' : 'Interface language');
    for (const option of select.options) option.selected = option.value === locale;
    updateDocument(env);
  };
  const change = () => setLocale(select.value, env);
  select.addEventListener('change', change);
  label.append(caption, select); container.append(label);
  const off = onLocaleChange(refresh); refresh();
  return () => { off(); select.removeEventListener('change', change); label.remove(); };
}
