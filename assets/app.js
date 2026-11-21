'use strict';

// 용어 데이터는 data/terms.json 에서 불러옵니다 (scripts/build_data.py 로 생성).
const DATA_URL = 'data/terms.json';
const PAGE = 100;            // 한 번에 보여 줄 결과 수 ('더 보기'로 이어서 표시)
const MAX_QUERY = 200;
const EXAMPLES = ['fever', '복부', 'FUO', 'schwannoma', '심부전'];

// 뜻풀이 안의 표시: 뒤따르는 글을 가진 항목(필드)과, 분야만 알려 주는 배지
const FIELDS = { '동': '동의어', '약': '약어', '원': '원어', '복': '복수형', '단': '단수형', '각주': '각주' };

const $ = (s) => document.querySelector(s);
const input = $('#searchInput');
const resultsEl = $('#results');
const countEl = $('#resultCount');
const clearBtn = $('#clearBtn');

let termsData = [];
let dataReady = false;
let current = [];      // 현재 검색 결과
let shown = 0;         // 화면에 그린 수
let lastQuery = '';

// ── 뜻풀이 구조화: "아킬레스힘줄 [동] 아킬레스건 [각주] …" → { main, fields, badges } ──
function parseKorean(raw) {
  const out = { main: '', fields: [], badges: [] };
  const re = /\s*\[([가-힣]{1,4})\]\s*/g;
  let last = 0, cur = null, m;
  const push = (text) => {
    text = text.trim();
    if (!text) return;
    if (cur) cur.text = cur.text ? `${cur.text} ${text}` : text;
    else out.main = out.main ? `${out.main} ${text}` : text;
  };
  while ((m = re.exec(raw))) {
    const tag = m[1];
    if (cur && cur.key === '각주' && !FIELDS[tag]) continue; // 각주 안의 [ ]는 글자 그대로
    push(raw.slice(last, m.index));
    last = re.lastIndex;
    if (FIELDS[tag]) { cur = { key: tag, label: FIELDS[tag], text: '' }; out.fields.push(cur); }
    else if (!out.badges.includes(tag)) out.badges.push(tag);
  }
  push(raw.slice(last));
  out.fields = out.fields.filter((f) => f.text);
  return out;
}

function abbrOf(item) {
  const f = item.p.fields.find((x) => x.key === '약');
  if (!f) return '';
  const m = f.text.match(/^([^()]+?)(?:\s*\(|$)/);
  return (m ? m[1] : f.text).trim();
}

// 복사 형식: 한글(원어, 용어) · 한글(용어, 약어) · 한글(용어)
function copyPayload(item) {
  const main = item.p.main;
  const orig = item.p.fields.find((x) => x.key === '원');
  if (orig) return `${main}(${orig.text}, ${item.term})`;
  const abbr = abbrOf(item);
  if (abbr) return `${main}(${item.term}, ${abbr})`;
  return `${main}(${item.term})`;
}

function formatDate(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || '');
  return m ? `${m[1]}년 ${Number(m[2])}월 ${Number(m[3])}일` : (iso || '');
}

async function loadTerms() {
  try {
    const res = await fetch(DATA_URL, { cache: 'no-cache' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    const meta = data.meta || {};
    termsData = (data.terms || []).map(([term, korean]) => {
      const p = parseKorean(korean);
      return { term, korean, p, _t: term.toLowerCase(), _k: korean.toLowerCase(), _m: p.main.toLowerCase() };
    });
    for (const it of termsData) it._a = abbrOf(it).toLowerCase();
    dataReady = true;
    const parts = [];
    if (meta.edition) parts.push(`의학용어집 ${meta.edition}`);
    parts.push(`${termsData.length.toLocaleString()}개 용어`);
    if (meta.updated) parts.push(`${formatDate(meta.updated)} 업데이트`);
    $('#versionInfo').textContent = parts.join(' · ');
    performSearch(input.value);
  } catch (e) {
    $('#versionInfo').textContent = '';
    renderMessage('용어 데이터를 불러오지 못했습니다', ['네트워크 연결을 확인한 뒤 새로고침해 주세요.'], false);
  }
}

// ── 검색: 일치 정도(정확히 같음 > 앞부분 일치 > 포함)로 먼저 정렬하고, 같으면 짧은 용어 먼저 ──
const noSpaceLen = (s) => (s || '').replace(/\s+/g, '').length;
function rank(it, q) {
  if (it._t === q || it._a === q || it._m === q) return 0;
  if (it._t.startsWith(q) || it._m.startsWith(q)) return 1;
  if (it._t.includes(q)) return 2;
  return 3; // 뜻풀이(동의어·각주 포함)에만 있음
}

function performSearch(query) {
  query = String(query ?? '');
  if (query.length > MAX_QUERY) query = query.slice(0, MAX_QUERY);
  syncHash(query.trim());
  if (!dataReady) return;
  const q = query.trim().toLowerCase();
  lastQuery = query.trim();
  if (!q) { current = []; countEl.textContent = ''; renderStart(); return; }

  const hits = [];
  for (const it of termsData) {
    if (it._t.includes(q) || it._k.includes(q)) hits.push({ it, r: rank(it, q) });
  }
  hits.sort((a, b) => a.r - b.r
    || noSpaceLen(a.it.term) - noSpaceLen(b.it.term)
    || a.it.term.localeCompare(b.it.term, undefined, { sensitivity: 'base' }));
  current = hits.map((h) => h.it);

  countEl.textContent = '';
  const qs = document.createElement('span'); qs.className = 'q'; qs.textContent = `‘${lastQuery}’ 검색 결과 `;
  const em = document.createElement('em'); em.textContent = current.length.toLocaleString();
  countEl.append(qs, em, '개');

  if (!current.length) {
    renderMessage('검색 결과가 없습니다', [
      '철자가 맞는지 확인해 주세요.',
      '영어 대신 한글로, 또는 한글 대신 영어로 검색해 보세요.',
      '단어 일부만 입력해 보세요. (예: schwannoma → schwann)',
    ], true);
    return;
  }
  resultsEl.textContent = '';
  const ul = document.createElement('ul');
  ul.className = 'list';
  resultsEl.appendChild(ul);
  shown = 0;
  renderMore(ul);
}

function renderMore(ul) {
  const end = Math.min(shown + PAGE, current.length);
  const frag = document.createDocumentFragment();
  for (let i = shown; i < end; i++) frag.appendChild(renderItem(current[i]));
  ul.appendChild(frag);
  const first = ul.children[shown];
  shown = end;
  resultsEl.querySelector('.more')?.remove();
  if (shown < current.length) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'more';
    btn.textContent = `더 보기 (${(current.length - shown).toLocaleString()}개 남음)`;
    btn.addEventListener('click', () => {
      const firstNew = shown;
      renderMore(ul);
      ul.children[firstNew]?.querySelector('.copy-btn')?.focus({ preventScroll: true });
    });
    resultsEl.appendChild(btn);
  }
  return first;
}

// 검색어 강조: <mark> + 글자 노드만 사용 (innerHTML 쓰지 않음)
function highlight(parent, text, query) {
  const t = String(text ?? '');
  const q = query.toLowerCase();
  if (!q) { parent.append(t); return; }
  const lt = t.toLowerCase();
  let i = 0;
  while (i < t.length) {
    const idx = lt.indexOf(q, i);
    if (idx === -1) { parent.append(t.slice(i)); break; }
    if (idx > i) parent.append(t.slice(i, idx));
    const mk = document.createElement('mark');
    mk.textContent = t.slice(idx, idx + q.length);
    parent.appendChild(mk);
    i = idx + q.length;
  }
}

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
}

function renderItem(item) {
  const li = el('li', 'item');
  const h = el('h2', 'term');
  const en = el('span', 'en');
  highlight(en, item.term, lastQuery);
  h.appendChild(en);
  for (const b of item.p.badges) h.appendChild(el('span', 'badge', b));
  li.appendChild(h);

  const ko = el('p', 'ko');
  highlight(ko, item.p.main, lastQuery);
  li.appendChild(ko);

  if (item.p.fields.length) {
    const dl = el('dl', 'extra');
    for (const f of item.p.fields) {
      dl.appendChild(el('dt', null, f.label));
      const dd = el('dd');
      highlight(dd, f.text, lastQuery);
      dl.appendChild(dd);
    }
    li.appendChild(dl);
  }

  const btn = el('button', 'copy-btn');
  btn.type = 'button';
  btn.title = copyPayload(item);
  const ico = el('i', 'ico ico-copy'); ico.setAttribute('aria-hidden', 'true');
  const lbl = el('span', 'lbl', '복사');
  const sr = el('span', 'sr-only', ` ${item.term}`);
  btn.append(ico, lbl, sr);
  btn.addEventListener('click', async () => {
    const ok = await copyToClipboard(copyPayload(item));
    showToast(ok ? `복사했습니다: ${copyPayload(item)}` : '복사하지 못했습니다');
    if (ok) { btn.classList.add('done'); setTimeout(() => btn.classList.remove('done'), 1200); }
  });
  li.appendChild(btn);
  return li;
}

function renderMessage(title, lines, withExamples) {
  resultsEl.textContent = '';
  const box = el('div', 'empty');
  box.appendChild(el('h2', null, title));
  if (lines.length === 1) box.appendChild(el('p', null, lines[0]));
  else { const ul = el('ul'); for (const l of lines) ul.appendChild(el('li', null, l)); box.appendChild(ul); }
  if (withExamples) box.appendChild(exampleLinks());
  resultsEl.appendChild(box);
}

function renderStart() {
  resultsEl.textContent = '';
  const box = el('div', 'empty');
  box.appendChild(el('h2', null, '찾을 의학용어를 입력해 주세요'));
  box.appendChild(el('p', null, '영어 용어, 한글 뜻풀이, 약어 모두 검색할 수 있습니다.'));
  box.appendChild(exampleLinks());
  resultsEl.appendChild(box);
}

function exampleLinks() {
  const acts = el('div', 'acts');
  acts.setAttribute('role', 'group');
  acts.setAttribute('aria-label', '예시 검색어');
  for (const w of EXAMPLES) {
    const b = el('button', 'tag-link', w);
    b.type = 'button';
    b.addEventListener('click', () => { input.value = w; updateClearBtn(); performSearch(w); input.focus(); });
    acts.appendChild(b);
  }
  return acts;
}

// ── 주소에 검색어 남기기 (#q=…): 새로고침·공유·뒤로 가기 후에도 같은 결과 ──
function readHash() {
  try { return new URLSearchParams(location.hash.slice(1)).get('q') || ''; } catch (e) { return ''; }
}
function syncHash(q) {
  const h = q ? `#q=${encodeURIComponent(q)}` : '';
  if (location.hash === h) return;
  history.replaceState(null, '', h || location.pathname + location.search);
}

// ── 복사 · 알림 ──
async function copyToClipboard(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch (e) {
    try {
      const ta = document.createElement('textarea');
      ta.value = text;
      ta.setAttribute('readonly', '');
      ta.className = 'copy-ta-hidden';
      document.body.appendChild(ta);
      ta.select();
      const ok = document.execCommand('copy');
      ta.remove();
      return ok;
    } catch (e2) {
      return false;
    }
  }
}

function showToast(message) {
  const t = $('#toast');
  t.textContent = message;
  t.classList.add('show');
  clearTimeout(showToast._timer);
  showToast._timer = setTimeout(() => { t.classList.remove('show'); t.textContent = ''; }, 1800);
}

// ── 입력 ──
let searchTimeout = null;
function updateClearBtn() { clearBtn.hidden = !input.value; }
function clearSearch() {
  clearTimeout(searchTimeout);
  input.value = '';
  updateClearBtn();
  performSearch('');
  input.focus();
}
clearBtn.addEventListener('click', clearSearch);
input.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && input.value) { e.preventDefault(); clearSearch(); }
});
input.addEventListener('input', () => {
  updateClearBtn();
  clearTimeout(searchTimeout);
  searchTimeout = setTimeout(() => performSearch(input.value), 250);
});
$('#searchForm').addEventListener('submit', (e) => {
  e.preventDefault();
  clearTimeout(searchTimeout);
  performSearch(input.value);
  input.blur(); // 모바일: 키보드 내려 결과가 보이게
});
window.addEventListener('hashchange', () => {
  const q = readHash();
  if (q !== input.value.trim()) { input.value = q; updateClearBtn(); performSearch(q); }
});

// 좁은 화면에서는 검색창 안내 문구가 잘리지 않게 짧은 문구로 (KRDS: 검색어 입력 필드는 말줄임 없이)
(() => {
  const long = input.placeholder, short = input.dataset.short;
  const mq = window.matchMedia('(max-width: 767px)');
  const set = () => { input.placeholder = mq.matches && short ? short : long; };
  set();
  mq.addEventListener?.('change', set);
})();

// ── 화면 설정: 글자 크기 · 화면 모드 (KRDS 화면 크기 조절 · 선명한 화면 모드) ──
(() => {
  const root = document.documentElement;
  const load = () => {
    try {
      const s = JSON.parse(localStorage.getItem('view-settings') || 'null');
      if (s) return s;
      const old = localStorage.getItem('theme');
      return { mode: old === 'dark' ? 'high-contrast' : old === 'light' ? 'light' : 'theme' };
    } catch (e) { return {}; }
  };
  const save = (v) => { try { localStorage.setItem('view-settings', JSON.stringify(v)); localStorage.removeItem('theme'); } catch (e) { /* 저장이 막힌 브라우저는 이번 방문에만 적용 */ } };
  let cur = Object.assign({ scale: 1, mode: 'theme' }, load());
  const apply = () => {
    root.dataset.mode = cur.mode;
    root.style.fontSize = Number(cur.scale) === 1 ? '' : `${62.5 * cur.scale}%`;
    for (const r of document.querySelectorAll('#settings-menu input[name="scale"]')) r.checked = Number(r.value) === Number(cur.scale);
    for (const r of document.querySelectorAll('#settings-menu input[name="mode"]')) r.checked = r.value === cur.mode;
  };
  apply();
  $('#settings-menu').addEventListener('change', (e) => {
    if (e.target.name === 'scale') cur.scale = Number(e.target.value);
    if (e.target.name === 'mode') cur.mode = e.target.value;
    apply(); save(cur);
  });
  $('#settings-reset').addEventListener('click', () => { cur = { scale: 1, mode: 'theme' }; apply(); save(cur); });

  // 펼침 메뉴: Esc·바깥 클릭·Tab으로 밖에 나가면 닫고, Esc일 때 초점은 버튼으로
  const wrap = $('#settings'), btn = wrap.querySelector('.util-btn'), menu = $('#settings-menu');
  const close = (refocus) => { if (menu.hidden) return; menu.hidden = true; btn.setAttribute('aria-expanded', 'false'); if (refocus) btn.focus(); };
  btn.addEventListener('click', () => {
    if (!menu.hidden) { close(false); return; }
    menu.hidden = false; btn.setAttribute('aria-expanded', 'true');
    menu.querySelector('input:checked')?.focus();
  });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && wrap.contains(document.activeElement)) close(true); });
  document.addEventListener('click', (e) => { if (!wrap.contains(e.target)) close(false); });
  document.addEventListener('focusin', (e) => { if (!wrap.contains(e.target)) close(false); });
})();

// ── 맨 위로: 한 화면 이상 내려가면 표시, 누르면 검색창으로 ──
(() => {
  const btn = $('#goTop');
  const onScroll = () => { btn.hidden = window.scrollY < window.innerHeight; };
  window.addEventListener('scroll', onScroll, { passive: true });
  onScroll();
  btn.addEventListener('click', () => { window.scrollTo({ top: 0 }); input.focus({ preventScroll: true }); });
})();

// ---- 초기화 ----
input.value = readHash() || input.value;
updateClearBtn();
loadTerms();
