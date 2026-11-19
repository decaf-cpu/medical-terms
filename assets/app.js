'use strict';

        // 용어 데이터는 data/terms.json 에서 불러옵니다 (scripts/build_data.py 로 생성).
        const DATA_URL = 'data/terms.json';
        let termsData = [];
        let dataReady = false;

        function showStatus(message) {
            const resultsDiv = document.getElementById('results');
            resultsDiv.textContent = '';
            const wrap = document.createElement('div');
            wrap.className = 'no-results';
            const icon = document.createElement('div');
            icon.className = 'no-results-icon';
            const msg = document.createElement('div');
            msg.textContent = message;
            wrap.appendChild(icon);
            wrap.appendChild(msg);
            resultsDiv.appendChild(wrap);
        }

        function formatDate(iso) {
            const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || '');
            return m ? `${m[1]}년 ${m[2]}월 ${m[3]}일` : (iso || '');
        }

        async function loadTerms() {
            try {
                const res = await fetch(DATA_URL, { cache: 'no-cache' });
                if (!res.ok) throw new Error(`HTTP ${res.status}`);
                const data = await res.json();
                const meta = data.meta || {};
                termsData = (data.terms || []).map(([term, korean]) => ({
                    term,
                    korean,
                    _t: term.toLowerCase(),
                    _k: korean.toLowerCase(),
                }));
                dataReady = true;

                document.getElementById('totalCount').textContent =
                    `총 ${termsData.length.toLocaleString()}개 용어`;
                const parts = [];
                if (meta.edition) parts.push(`의학용어집 ${meta.edition}`);
                if (meta.updated) parts.push(`업데이트: ${formatDate(meta.updated)}`);
                document.getElementById('versionInfo').textContent = parts.join(' · ');

                const input = document.getElementById('searchInput');
                performSearch(input.value);
            } catch (e) {
                showStatus('용어 데이터를 불러오지 못했습니다. 새로고침해 주세요.');
                document.getElementById('versionInfo').textContent = '';
            }
        }

        let searchTimeout = null;

function appendHighlightedText(parent, text, query) {
    // Safe highlighter: no innerHTML, only text nodes + <span class="highlight">
    parent.textContent = '';
    const t = String(text ?? '');
    const q = String(query ?? '').trim();
    if (!q) {
        parent.textContent = t;
        return;
    }

    const lowerT = t.toLowerCase();
    const lowerQ = q.toLowerCase();

    let i = 0;
    while (i < t.length) {
        const idx = lowerT.indexOf(lowerQ, i);
        if (idx === -1) {
            parent.appendChild(document.createTextNode(t.slice(i)));
            break;
        }
        if (idx > i) parent.appendChild(document.createTextNode(t.slice(i, idx)));

        const span = document.createElement('span');
        span.className = 'highlight';
        span.textContent = t.slice(idx, idx + q.length);
        parent.appendChild(span);

        i = idx + q.length;
    }
}

let currentDisplayItems = [];

        function ensureToast() {
            if (document.getElementById('toast')) return;
            const t = document.createElement('div');
            t.id = 'toast';
            t.textContent = '';
            document.body.appendChild(t);
        }

        function showToast(message) {
            ensureToast();
            const t = document.getElementById('toast');
            t.textContent = message;
            t.classList.add('show');
            clearTimeout(showToast._timer);
            showToast._timer = setTimeout(() => t.classList.remove('show'), 1100);
        }

        async function copyToClipboard(text) {
            try {
                await navigator.clipboard.writeText(text);
                return true;
            } catch (e) {
                // Fallback for older browsers / non-secure contexts
                try {
                    const ta = document.createElement('textarea');
                    ta.value = text;
                    ta.setAttribute('readonly', '');
                    ta.className = 'copy-ta-hidden';
                    document.body.appendChild(ta);
                    ta.select();
                    const ok = document.execCommand('copy');
                    document.body.removeChild(ta);
                    return ok;
                } catch (e2) {
                    return false;
                }
            }
        }

        function bindCopyButtons() {
            document.querySelectorAll('.copy-btn').forEach(btn => {
                btn.onclick = async () => {
                    const idx = Number(btn.getAttribute('data-idx'));
                    if (Number.isNaN(idx)) return;
                    const item = currentDisplayItems[idx];
                    if (!item) return;
                    let payload;
                    if (item.korean && item.korean.includes('[원]')) {
                        const wIdx = item.korean.indexOf('[원]');
                        const korPart = item.korean.slice(0, wIdx).trim();
                        const engPart = item.korean.slice(wIdx + 3).trim();
                        payload = `${korPart}(${engPart}, ${item.term})`;
                    } else if (item.korean && item.korean.includes('[약]')) {
                        const yakIdx = item.korean.indexOf('[약]');
                        const korPart = item.korean.slice(0, yakIdx).trim();
                        const afterYak = item.korean.slice(yakIdx + 3).trim();
                        const abbrMatch = afterYak.match(/^([^()]+?)(?:\s*\(|$)/);
                        const abbreviation = abbrMatch ? abbrMatch[1].trim() : afterYak;
                        payload = `${korPart}(${item.term}, ${abbreviation})`;
                    } else {
                        payload = `${item.korean}(${item.term})`;
                    }
                    const ok = await copyToClipboard(payload);
                    showToast(ok ? '복사됨' : '복사 실패');
                };
            });
        }

        function initTheme() {
    let stored = null;
    try {
        stored = localStorage.getItem('theme');
    } catch (e) {
        // localStorage may be blocked (privacy mode, policy). Fall back gracefully.
        stored = null;
    }
    const prefersDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
    const theme = stored ? stored : (prefersDark ? 'dark' : 'light');
    if (theme === 'dark') document.documentElement.setAttribute('data-theme', 'dark');
    else document.documentElement.removeAttribute('data-theme');
}

        function toggleTheme() {
            const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
            if (isDark) {
                document.documentElement.removeAttribute('data-theme');
                try {
                    localStorage.setItem('theme', 'light');
                } catch (e) {
                    // ignore storage errors
                }
                showToast('라이트 모드');
            } else {
                document.documentElement.setAttribute('data-theme', 'dark');
                try {
                    localStorage.setItem('theme', 'dark');
                } catch (e) {
                    // ignore storage errors
                }
                showToast('다크 모드');
            }
        }

        function termLengthNoSpaces(s) {
            return (s || '').replace(/\s+/g, '').length;
        }

        function performSearch(query) {
            
            // DoS guard: ignore extremely long inputs
            if ((query ?? '').length > 1000) {
                showToast('검색어가 너무 깁니다(최대 1000자).');
                return;
            }
if (!dataReady) return;
            if (!query.trim()) {
                displayResults(termsData.slice(0, 50));
                document.getElementById('resultCount').textContent = '';
                return;
            }

            const lowerQuery = query.toLowerCase();
            
            const filtered = termsData.filter(item =>
                item._t.includes(lowerQuery) ||
                item._k.includes(lowerQuery)
            );

            // Sort by English term length (excluding spaces)
            filtered.sort((a, b) => {
                const la = termLengthNoSpaces(a.term);
                const lb = termLengthNoSpaces(b.term);
                if (la !== lb) return la - lb; // shorter first
                return a.term.localeCompare(b.term, undefined, { sensitivity: 'base' });
            });

            displayResults(filtered);
            document.getElementById('resultCount').textContent = 
                `${filtered.length.toLocaleString()}개 검색 결과`;
        }

        function displayResults(results) {
    const resultsDiv = document.getElementById('results');
    const query = document.getElementById('searchInput').value;

    resultsDiv.textContent = '';

    if (!results || results.length === 0) {
        const wrap = document.createElement('div');
        wrap.className = 'no-results';

        const icon = document.createElement('div');
        icon.className = 'no-results-icon';

        const msg = document.createElement('div');
        msg.textContent = '검색 결과가 없습니다. 철자나 맞춤법 오류가 있는지 확인해 주세요.';

        wrap.appendChild(icon);
        wrap.appendChild(msg);
        resultsDiv.appendChild(wrap);
        return;
    }

    const displayItems = results.slice(0, 200);
    currentDisplayItems = displayItems;

    const frag = document.createDocumentFragment();

    for (let idx = 0; idx < displayItems.length; idx++) {
        const item = displayItems[idx];

        const itemDiv = document.createElement('div');
        itemDiv.className = 'result-item';

        const topDiv = document.createElement('div');
        topDiv.className = 'result-top';

        const termDiv = document.createElement('div');
        termDiv.className = 'result-term';
        appendHighlightedText(termDiv, item.term, query);

        const btn = document.createElement('button');
        btn.className = 'copy-btn';
        btn.type = 'button';
        btn.dataset.idx = String(idx);
        btn.setAttribute('aria-label', '뜻풀이 복사');
        btn.setAttribute('title', '뜻풀이 복사');

        // SVG icon (constant, created as DOM to avoid innerHTML)
        const svgNS = 'http://www.w3.org/2000/svg';
        const svg = document.createElementNS(svgNS, 'svg');
        svg.setAttribute('viewBox', '0 0 24 24');
        svg.setAttribute('width', '16');
        svg.setAttribute('height', '16');
        svg.setAttribute('aria-hidden', 'true');

        const p1 = document.createElementNS(svgNS, 'path');
        p1.setAttribute('d', 'M8 7a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2h-9a2 2 0 0 1-2-2V7Z');
        p1.setAttribute('fill', 'none');
        p1.setAttribute('stroke', 'currentColor');
        p1.setAttribute('stroke-width', '2');
        p1.setAttribute('stroke-linejoin', 'round');

        const p2 = document.createElementNS(svgNS, 'path');
        p2.setAttribute('d', 'M6 17H5a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1');
        p2.setAttribute('fill', 'none');
        p2.setAttribute('stroke', 'currentColor');
        p2.setAttribute('stroke-width', '2');
        p2.setAttribute('stroke-linecap', 'round');

        svg.appendChild(p1);
        svg.appendChild(p2);
        btn.appendChild(svg);

        topDiv.appendChild(termDiv);
        topDiv.appendChild(btn);

        const korDiv = document.createElement('div');
        korDiv.className = 'result-korean';
        appendHighlightedText(korDiv, item.korean, query);

        itemDiv.appendChild(topDiv);
        itemDiv.appendChild(korDiv);

        frag.appendChild(itemDiv);
    }

    resultsDiv.appendChild(frag);

    bindCopyButtons();

    if (results.length > 200) {
        const note = document.createElement('div');
        note.className = 'results-note';
        note.textContent = '결과가 너무 많아 상위 200개만 표시됩니다. 더 구체적인 검색어를 입력해주세요.';
        resultsDiv.appendChild(note);
    }
}

        document.getElementById('searchInput').addEventListener('input', (e) => {
            clearTimeout(searchTimeout);
            searchTimeout = setTimeout(() => {
                performSearch(e.target.value);
            }, 300);
        });

        const searchBtn = document.getElementById('searchBtn');
        if (searchBtn) {
            searchBtn.addEventListener('click', () => {
                const input = document.getElementById('searchInput');
                performSearch(input.value);
                input.focus();
            });
        }

        // ---- 초기화 ----
        initTheme();
        const themeBtn = document.getElementById('themeToggle');
        if (themeBtn) themeBtn.addEventListener('click', toggleTheme);
        loadTerms();
