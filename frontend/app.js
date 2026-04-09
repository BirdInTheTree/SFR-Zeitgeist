const DATA_DIR = '../demo-data';
let DAYS = [];
let currentDayIdx = 0;
let keywords = [];
let zoomedIdx = -1;
let isLoading = false;

const GRID_SIZE = 49;
const dom = {
    grid: null,
    wordCol: null,
    footerTitle: null,
    subtitle: null,
    snapshotMeta: null,
    loadState: null,
    prev: null,
    next: null,
    zoom: null,
    fullscreen: null,
    about: null,
};

function cacheDom() {
    dom.grid = document.getElementById('grid');
    dom.wordCol = document.getElementById('word-col');
    dom.footerTitle = document.getElementById('footer-title');
    dom.subtitle = document.getElementById('subtitle');
    dom.snapshotMeta = document.getElementById('snapshot-meta');
    dom.loadState = document.getElementById('load-state');
    dom.prev = document.getElementById('prev');
    dom.next = document.getElementById('next');
    dom.zoom = document.getElementById('zoom');
    dom.fullscreen = document.getElementById('fullscreen');
    dom.about = document.getElementById('about');
}

async function boot() {
    cacheDom();
    // Load available days from manifest, fallback to hardcoded
    try {
        const r = await fetch(`${DATA_DIR}/days.json`);
        if (!r.ok) throw new Error(`days manifest failed: ${r.status}`);
        DAYS = await r.json();
    } catch {
        DAYS = ['20260331', '20260401'];
    }
    currentDayIdx = DAYS.length - 1;
    setSubtitle();
    await loadDay(currentDayIdx);
    wire();
}

async function loadDay(idx) {
    if (isLoading) return;
    const day = DAYS[idx];
    setLoadState('Loading snapshot...', 'loading');
    document.body.classList.add('loading');
    isLoading = true;

    try {
        const r = await fetch(`${DATA_DIR}/zeitgeist_${day}.json`);
        if (!r.ok) throw new Error(`snapshot failed: ${r.status}`);
        keywords = await r.json();
        currentDayIdx = idx;
        buildGrid();
        buildWords();
        updateFooter();
        updateSnapshotMeta();
        updateNav();
        setLoadState(`Showing ${formatLongDay(day)}`, 'ready');
    } catch (error) {
        keywords = [];
        buildGrid();
        buildWords();
        updateFooter();
        updateSnapshotMeta();
        updateNav();
        setLoadState(`Could not load ${formatDay(day)}.`, 'error');
        console.error(error);
    } finally {
        isLoading = false;
        document.body.classList.remove('loading');
    }
}

function formatDay(dayStr) {
    return `${dayStr.slice(0,4)}-${dayStr.slice(4,6)}-${dayStr.slice(6,8)}`;
}

function formatLongDay(dayStr) {
    const [year, month, day] = [dayStr.slice(0, 4), dayStr.slice(4, 6), dayStr.slice(6, 8)];
    return new Date(+year, +month - 1, +day).toLocaleDateString('en-US', {
        month: 'long',
        day: 'numeric',
        year: 'numeric',
    });
}

function setSubtitle() {
    if (!dom.subtitle) return;
    dom.subtitle.textContent = 'Topic-centric navigation for the SRF news archive, ranked from subtitle spikes.';
}

function setLoadState(message, state) {
    if (!dom.loadState) return;
    dom.loadState.textContent = message;
    dom.loadState.className = `load-state ${state}`;
}

function updateNav() {
    dom.prev.style.opacity = currentDayIdx > 0 ? 1 : 0.3;
    dom.next.style.opacity = currentDayIdx < DAYS.length - 1 ? 1 : 0.3;
}

function updateSnapshotMeta() {
    if (!dom.snapshotMeta) return;
    const items = keywords.slice(0, GRID_SIZE);
    const imageCount = items.filter(kw => kw.frameImage || kw.imageUrl).length;
    const quoteCount = items.reduce((sum, kw) => sum + (kw.quotes ? kw.quotes.length : 0), 0);
    const parts = [
        `${items.length} topics`,
        `${imageCount} with imagery`,
        `${quoteCount} source quotes`,
        `${DAYS.length} archived days`,
    ];
    dom.snapshotMeta.textContent = `${formatLongDay(DAYS[currentDayIdx])} • ${parts.join(' • ')}`;
}

function addTextOnlyBadge(cell) {
    if (cell.querySelector('.img-badge')) return;
    const badge = document.createElement('div');
    badge.className = 'img-badge';
    badge.textContent = 'text only';
    cell.appendChild(badge);
}

/* ---- Grid ---- */
function buildGrid() {
    const g = dom.grid;
    g.innerHTML = '';
    const items = keywords.slice(0, GRID_SIZE);
    items.forEach((kw, i) => {
        const c = document.createElement('div');
        c.className = 'cell';
        c.dataset.i = i;

        const imgSrc = kw.frameImage || kw.imageUrl || '';
        const img = document.createElement('img');
        if (imgSrc) {
            img.src = imgSrc;
            img.alt = kw.phrase;
            img.loading = 'lazy';
            img.onerror = () => {
                img.style.display = 'none';
                c.classList.add('no-img');
                addTextOnlyBadge(c);
            };
        } else {
            img.style.display = 'none';
            c.classList.add('no-img');
        }

        if (c.classList.contains('no-img')) {
            addTextOnlyBadge(c);
        }

        const lb = document.createElement('div');
        lb.className = 'label';
        lb.textContent = kw.phrase;

        // Air time badge
        if (kw.airTime) {
            const badge = document.createElement('div');
            badge.className = 'time-badge';
            badge.textContent = kw.airTime;
            c.appendChild(badge);
        }

        c.appendChild(img);
        c.appendChild(lb);
        c.addEventListener('mouseenter', () => light(i));
        c.addEventListener('mouseleave', dim);
        c.addEventListener('click', () => openZoom(i));
        g.appendChild(c);
    });
    for (let i = items.length; i < GRID_SIZE; i++) {
        const c = document.createElement('div');
        c.className = 'cell empty';
        g.appendChild(c);
    }
}

/* ---- Word column ---- */
function buildWords() {
    const col = dom.wordCol;
    col.innerHTML = '';
    const WORD_COUNT = 49;
    keywords.slice(0, WORD_COUNT).forEach((kw, i) => {
        const w = document.createElement('div');
        w.className = 'w';
        w.dataset.i = i;
        w.innerHTML = `<span class="num">${i+1}.</span><span class="txt">${kw.phrase}</span>`;
        w.addEventListener('mouseenter', () => light(i));
        w.addEventListener('mouseleave', dim);
        w.addEventListener('click', () => openZoom(i));
        col.appendChild(w);
    });
}

/* ---- Highlight ---- */
function light(i) {
    dom.grid.querySelectorAll('.cell').forEach(c => c.classList.toggle('lit', +c.dataset.i === i));
    dom.wordCol.querySelectorAll('.w').forEach(el => {
        const j = +el.dataset.i;
        const dist = Math.abs(j - i);
        el.classList.remove('on', 'near1', 'near2', 'far');
        if (dist === 0) el.classList.add('on');
        else if (dist === 1) el.classList.add('near1');
        else if (dist === 2) el.classList.add('near2');
    });
}

function dim() {
    dom.grid.querySelectorAll('.cell').forEach(c => c.classList.remove('lit'));
    dom.wordCol.querySelectorAll('.w').forEach(w => w.classList.remove('on', 'near1', 'near2', 'far'));
}

/* ---- Zoom ---- */
function openZoom(i) {
    zoomedIdx = i;
    const kw = keywords[i];
    const z = dom.zoom;
    document.getElementById('zoom-img').src = kw.frameImage || kw.imageUrl || '';
    document.getElementById('zoom-word').textContent = kw.phrase;

    const hl = document.getElementById('zoom-headlines');
    hl.innerHTML = '<strong>PROGRAMS:</strong> (click to watch)';

    if (kw.quotes && kw.quotes.length > 0) {
        kw.quotes.forEach(q => {
            const div = document.createElement('div');
            div.style.marginTop = '6px';

            const source = document.createElement('span');
            source.style.color = '#888';
            source.style.fontSize = '11px';
            source.textContent = `${q.channel} · ${q.title}`;

            const quote = document.createElement('p');
            quote.style.fontStyle = 'italic';
            quote.style.color = '#555';
            quote.style.fontSize = '12px';
            quote.style.margin = '2px 0';
            quote.textContent = q.quote;

            div.appendChild(source);
            div.appendChild(quote);

            if (q.urn) {
                const link = document.createElement('a');
                link.href = `https://www.srf.ch/play/tv/-/video/-?urn=${q.urn}`;
                link.target = '_blank';
                link.textContent = '→ Watch on Play SRF';
                div.appendChild(link);
            }

            hl.appendChild(div);
        });
    } else {
        const empty = document.createElement('div');
        empty.textContent = 'No source quotes available for this topic in the current snapshot.';
        hl.appendChild(empty);
    }

    z.classList.remove('hidden');
    light(i);
}

function openFullscreen() {
    if (zoomedIdx < 0) return;
    const kw = keywords[zoomedIdx];
    document.getElementById('fs-img').src = kw.frameImage || kw.imageUrl || '';
    document.getElementById('fs-word').textContent = kw.phrase;
    dom.fullscreen.classList.remove('hidden');
    dom.zoom.classList.add('hidden');
}

function openAbout() {
    dom.about.classList.remove('hidden');
    dom.about.setAttribute('aria-hidden', 'false');
}

function closeAbout() {
    dom.about.classList.add('hidden');
    dom.about.setAttribute('aria-hidden', 'true');
}

/* ---- Wiring ---- */
function wire() {
    document.getElementById('zoom-img').addEventListener('click', (e) => {
        e.stopPropagation();
        openFullscreen();
    });
    dom.zoom.addEventListener('click', () => {
        dom.zoom.classList.add('hidden');
        zoomedIdx = -1;
        dim();
    });
    dom.fullscreen.addEventListener('click', () => {
        dom.fullscreen.classList.add('hidden');
        zoomedIdx = -1;
    });

    document.getElementById('about-link').addEventListener('click', (e) => {
        e.preventDefault();
        openAbout();
    });
    document.getElementById('about-close').addEventListener('click', (e) => {
        e.stopPropagation();
        closeAbout();
    });
    dom.about.addEventListener('click', (e) => {
        if (e.target === dom.about) closeAbout();
    });

    dom.prev.addEventListener('click', (e) => {
        e.preventDefault();
        if (currentDayIdx > 0) loadDay(currentDayIdx - 1);
    });
    dom.next.addEventListener('click', (e) => {
        e.preventDefault();
        if (currentDayIdx < DAYS.length - 1) loadDay(currentDayIdx + 1);
    });

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            dom.fullscreen.classList.add('hidden');
            dom.zoom.classList.add('hidden');
            closeAbout();
            zoomedIdx = -1;
            dim();
        }
        if (e.key === 'ArrowLeft') { e.preventDefault(); if (currentDayIdx > 0) loadDay(currentDayIdx - 1); }
        if (e.key === 'ArrowRight') { e.preventDefault(); if (currentDayIdx < DAYS.length - 1) loadDay(currentDayIdx + 1); }
    });
}

function updateFooter() {
    const day = DAYS[currentDayIdx];
    const y = day.slice(0,4), m = day.slice(4,6), dd = day.slice(6,8);
    const end = new Date(+y, +m - 1, +dd);
    const start = new Date(end);
    start.setDate(start.getDate() - 6);

    const fmt = d => d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
    if (dom.footerTitle) dom.footerTitle.textContent = `Snapshot for ${fmt(end)}, ${end.getFullYear()}`;
}

boot();
