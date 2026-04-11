const DATA_DIR = '../demo-data';
let DAYS = [];
let currentDayIdx = 0;
let keywords = [];
let zoomedIdx = -1;
let _previousFocus = null;  // for restoring focus when overlay closes

/* ---- Focus trap for overlays ---- */
function trapFocus(overlay) {
    const focusable = overlay.querySelectorAll('a[href], button, [tabindex]:not([tabindex="-1"])');
    if (focusable.length === 0) return;
    overlay.addEventListener('keydown', (e) => {
        if (e.key !== 'Tab') return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (e.shiftKey && document.activeElement === first) {
            e.preventDefault();
            last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
            e.preventDefault();
            first.focus();
        }
    });
}

function openOverlay(el) {
    _previousFocus = document.activeElement;
    el.classList.remove('hidden');
    el.focus();
}

function closeOverlay(el) {
    el.classList.add('hidden');
    if (_previousFocus) { _previousFocus.focus(); _previousFocus = null; }
}

async function boot() {
    // Load available weeks from manifest
    try {
        const r = await fetch(`${DATA_DIR}/weeks.json`);
        DAYS = await r.json();
    } catch {
        DAYS = ['20260330'];
    }
    currentDayIdx = DAYS.length - 1;
    await loadWeek(currentDayIdx);
    wire();
}

async function loadWeek(idx) {
    const week = DAYS[idx];
    const grid = document.getElementById('grid');

    grid.innerHTML = '<div class="load-error">Loading...</div>';

    try {
        const r = await fetch(`${DATA_DIR}/zeitgeist_week_${week}.json`);
        if (!r.ok) throw new Error(r.status);
        keywords = await r.json();
    } catch (e) {
        keywords = [];
        console.error('Failed to load week', week, e);
        grid.innerHTML = `<div class="load-error">Could not load data for week ${week}</div>`;
    }
    buildGrid();
    buildWords();
    updateFooter();
    document.getElementById('prev').style.opacity = idx > 0 ? 1 : 0.3;
    document.getElementById('next').style.opacity = idx < DAYS.length - 1 ? 1 : 0.3;
}

/* ---- Grid ---- */
function buildGrid() {
    const g = document.getElementById('grid');
    g.innerHTML = '';
    const GRID_SIZE = 49;
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
            img.onerror = () => { img.style.display = 'none'; c.classList.add('no-img'); };
        } else {
            img.style.display = 'none';
            c.classList.add('no-img');
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
        c.className = 'cell';
        c.style.background = '#f5f5f5';
        g.appendChild(c);
    }
}

/* ---- Word column ---- */
function buildWords() {
    const col = document.getElementById('word-col');
    col.innerHTML = '';
    const WORD_COUNT = 49;
    keywords.slice(0, WORD_COUNT).forEach((kw, i) => {
        const w = document.createElement('div');
        w.className = 'w';
        w.dataset.i = i;
        const num = document.createElement('span');
        num.className = 'num';
        num.textContent = `${i+1}.`;
        const txt = document.createElement('span');
        txt.className = 'txt';
        txt.textContent = kw.phrase;
        w.appendChild(num);
        w.appendChild(txt);
        w.addEventListener('mouseenter', () => light(i));
        w.addEventListener('mouseleave', dim);
        w.addEventListener('click', () => openZoom(i));
        col.appendChild(w);
    });
}

/* ---- Highlight ---- */
function light(i) {
    document.querySelectorAll('.cell').forEach(c => c.classList.toggle('lit', +c.dataset.i === i));
    document.querySelectorAll('.w').forEach(el => {
        const j = +el.dataset.i;
        const dist = Math.abs(j - i);
        el.classList.remove('on', 'near1', 'near2', 'far');
        if (dist === 0) el.classList.add('on');
        else if (dist === 1) el.classList.add('near1');
        else if (dist === 2) el.classList.add('near2');
    });
}

function dim() {
    document.querySelectorAll('.cell').forEach(c => c.classList.remove('lit'));
    document.querySelectorAll('.w').forEach(w => w.classList.remove('on', 'near1', 'near2', 'far'));
}

/* ---- Zoom ---- */
function openZoom(i) {
    zoomedIdx = i;
    const kw = keywords[i];
    const z = document.getElementById('zoom');
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
    }

    openOverlay(z);
    light(i);
}

function openFullscreen() {
    if (zoomedIdx < 0) return;
    const kw = keywords[zoomedIdx];
    document.getElementById('fs-img').src = kw.frameImage || kw.imageUrl || '';
    document.getElementById('fs-word').textContent = kw.phrase;
    document.getElementById('zoom').classList.add('hidden');
    openOverlay(document.getElementById('fullscreen'));
}

/* ---- Wiring ---- */
function wire() {
    // Set up focus traps on all overlays
    trapFocus(document.getElementById('zoom'));
    trapFocus(document.getElementById('fullscreen'));
    trapFocus(document.getElementById('about'));
    document.getElementById('zoom-img').addEventListener('click', (e) => {
        e.stopPropagation();
        openFullscreen();
    });
    document.getElementById('zoom').addEventListener('click', (e) => {
        // Close only when clicking the overlay background, not the content
        if (e.target !== e.currentTarget) return;
        closeOverlay(document.getElementById('zoom'));
        zoomedIdx = -1;
        dim();
    });
    document.getElementById('fullscreen').addEventListener('click', () => {
        closeOverlay(document.getElementById('fullscreen'));
        zoomedIdx = -1;
    });

    // About panel
    document.querySelector('a[href="#about"]').addEventListener('click', (e) => {
        e.preventDefault();
        openOverlay(document.getElementById('about'));
    });
    document.getElementById('about').addEventListener('click', () => {
        closeOverlay(document.getElementById('about'));
    });

    document.getElementById('prev').addEventListener('click', (e) => {
        e.preventDefault();
        if (currentDayIdx > 0) { currentDayIdx--; loadWeek(currentDayIdx); }
    });
    document.getElementById('next').addEventListener('click', (e) => {
        e.preventDefault();
        if (currentDayIdx < DAYS.length - 1) { currentDayIdx++; loadWeek(currentDayIdx); }
    });

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            closeOverlay(document.getElementById('fullscreen'));
            closeOverlay(document.getElementById('zoom'));
            zoomedIdx = -1;
            dim();
        }
        // Block navigation while any overlay is open
        if (zoomedIdx >= 0) return;
        if (e.key === 'ArrowLeft') { e.preventDefault(); if (currentDayIdx > 0) { currentDayIdx--; loadWeek(currentDayIdx); } }
        if (e.key === 'ArrowRight') { e.preventDefault(); if (currentDayIdx < DAYS.length - 1) { currentDayIdx++; loadWeek(currentDayIdx); } }
    });
}

function updateFooter() {
    const week = DAYS[currentDayIdx];
    const y = week.slice(0,4), m = week.slice(4,6), dd = week.slice(6,8);
    const mon = new Date(+y, +m - 1, +dd);
    const sun = new Date(mon); sun.setDate(sun.getDate() + 6);

    const fmt = (d) => d.toLocaleDateString('de-CH', { day: 'numeric', month: 'long' });
    const ft = document.getElementById('footer-title');
    if (ft) ft.textContent = `${fmt(mon)} – ${fmt(sun)} ${sun.getFullYear()}`;
}

boot();
