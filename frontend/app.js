const DATA_DIR = '../demo-data';
let DAYS = [];
let currentDayIdx = 0;
let keywords = [];
let zoomedIdx = -1;

async function boot() {
    // Load available days from manifest, fallback to hardcoded
    try {
        const r = await fetch(`${DATA_DIR}/days.json`);
        DAYS = await r.json();
    } catch {
        DAYS = ['20260331', '20260401'];
    }
    currentDayIdx = DAYS.length - 1;
    await loadDay(currentDayIdx);
    wire();
}

async function loadDay(idx) {
    const day = DAYS[idx];
    try {
        const r = await fetch(`${DATA_DIR}/zeitgeist_${day}.json`);
        if (!r.ok) throw new Error(r.status);
        keywords = await r.json();
    } catch (e) {
        keywords = [];
        console.error('Failed to load', day, e);
    }
    buildGrid();
    buildWords();
    updateFooter();
    document.getElementById('prev').style.opacity = idx > 0 ? 1 : 0.3;
    document.getElementById('next').style.opacity = idx < DAYS.length - 1 ? 1 : 0.3;
}

function formatDay(dayStr) {
    return `${dayStr.slice(0,4)}-${dayStr.slice(4,6)}-${dayStr.slice(6,8)}`;
}

/* ---- Grid ---- */
function buildGrid() {
    const g = document.getElementById('grid');
    g.innerHTML = '';
    const GRID_SIZE = 25;
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
    const WORD_COUNT = 25;
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

    z.classList.remove('hidden');
    light(i);
}

function openFullscreen() {
    if (zoomedIdx < 0) return;
    const kw = keywords[zoomedIdx];
    document.getElementById('fs-img').src = kw.frameImage || kw.imageUrl || '';
    document.getElementById('fs-word').textContent = kw.phrase;
    document.getElementById('fullscreen').classList.remove('hidden');
    document.getElementById('zoom').classList.add('hidden');
}

/* ---- Wiring ---- */
function wire() {
    document.getElementById('zoom-img').addEventListener('click', (e) => {
        e.stopPropagation();
        openFullscreen();
    });
    document.getElementById('zoom').addEventListener('click', () => {
        document.getElementById('zoom').classList.add('hidden');
        zoomedIdx = -1;
        dim();
    });
    document.getElementById('fullscreen').addEventListener('click', () => {
        document.getElementById('fullscreen').classList.add('hidden');
        zoomedIdx = -1;
    });

    // About panel
    document.querySelector('a[href="#about"]').addEventListener('click', (e) => {
        e.preventDefault();
        document.getElementById('about').classList.remove('hidden');
    });
    document.getElementById('about').addEventListener('click', () => {
        document.getElementById('about').classList.add('hidden');
    });

    document.getElementById('prev').addEventListener('click', (e) => {
        e.preventDefault();
        if (currentDayIdx > 0) { currentDayIdx--; loadDay(currentDayIdx); }
    });
    document.getElementById('next').addEventListener('click', (e) => {
        e.preventDefault();
        if (currentDayIdx < DAYS.length - 1) { currentDayIdx++; loadDay(currentDayIdx); }
    });

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            document.getElementById('fullscreen').classList.add('hidden');
            document.getElementById('zoom').classList.add('hidden');
            zoomedIdx = -1;
            dim();
        }
        if (e.key === 'ArrowLeft') { e.preventDefault(); if (currentDayIdx > 0) { currentDayIdx--; loadDay(currentDayIdx); } }
        if (e.key === 'ArrowRight') { e.preventDefault(); if (currentDayIdx < DAYS.length - 1) { currentDayIdx++; loadDay(currentDayIdx); } }
    });
}

function updateFooter() {
    const day = DAYS[currentDayIdx];
    const y = day.slice(0,4), m = day.slice(4,6), dd = day.slice(6,8);
    const d = new Date(+y, +m - 1, +dd);

    const weekday = d.toLocaleDateString('en-US', { weekday: 'long' });
    const month = d.toLocaleDateString('en-US', { month: 'short' });
    const ft = document.getElementById('footer-title');
    if (ft) ft.textContent = `${weekday}, ${month} ${+dd}, ${y}`;
}

boot();
