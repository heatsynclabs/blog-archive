/* HeatSync Labs blog archive — vanilla JS, no dependencies, no build step.
   Routes (hash):
     #/                     timeline
     #/calendar             calendar, all years
     #/calendar/2011        calendar, one year
     #/p/<slug>             one post
     #/q/<query>            search results
   Post bodies are pre-rendered HTML in data/html/<slug>.html, so there is no
   Markdown parser in the browser. data/posts.json is the whole index. */

const MONTHS = ['January','February','March','April','May','June',
                'July','August','September','October','November','December'];
const DOW = ['S','M','T','W','T','F','S'];

const main = document.getElementById('main');
const search = document.getElementById('q');
let DATA = null;

const esc = s => String(s ?? '').replace(/[&<>"']/g,
  c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

/* ---------------------------------------------------------------- boot */
fetch('data/posts.json')
  .then(r => { if (!r.ok) throw new Error(r.status); return r.json(); })
  .then(d => {
    DATA = d;
    DATA.items.forEach(i => { i._hay = (i.title + ' ' + i.excerpt + ' ' + i.author).toLowerCase(); });
    const m = d.meta;
    const stats = document.getElementById('colophon-stats');
    if (stats) stats.innerHTML =
      `<strong>${m.posts}</strong> posts and <strong>${m.pages}</strong> pages, ` +
      `<strong>${m.images}</strong> images, covering ${m.first} to ${m.last}. ` +
      `Generated ${m.generated}.`;
    route();
  })
  .catch(e => {
    main.innerHTML = `<div class="wrap"><div class="empty">Could not load
      <code>data/posts.json</code> (${esc(e.message)}).<br><br>
      If you opened this file directly, serve the folder instead:<br>
      <code>python3 -m http.server</code></div></div>`;
  });

window.addEventListener('hashchange', route);

document.getElementById('views').addEventListener('click', e => {
  const b = e.target.closest('button[data-view]');
  if (b) location.hash = b.dataset.view === 'calendar' ? '#/calendar' : '#/';
});

/* ---------------------------------------------------------------- theme */
const THEME_KEY = 'hslblog.theme';
const themeBtn = document.getElementById('theme');

function applyTheme(t) {
  document.documentElement.setAttribute('data-theme', t);
  if (!themeBtn) return;
  const dark = t === 'dark';
  // The button advertises what it will switch TO.
  document.getElementById('theme-ico').textContent = dark ? '◑' : '◐';
  document.getElementById('theme-txt').textContent = dark ? 'Light' : 'Dark';
  themeBtn.setAttribute('aria-pressed', String(dark));
  themeBtn.setAttribute('aria-label', dark ? 'Switch to light theme' : 'Switch to dark theme');
  themeBtn.title = dark ? 'Switch to light theme' : 'Switch to dark theme';
}

function currentTheme() {
  return document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'light';
}

applyTheme(currentTheme());   // sync the button with what the <head> script set

if (themeBtn) themeBtn.addEventListener('click', () => {
  const next = currentTheme() === 'dark' ? 'light' : 'dark';
  applyTheme(next);
  try { localStorage.setItem(THEME_KEY, next); } catch (e) { /* private mode */ }
});

let searchTimer;
search.addEventListener('input', () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => {
    const v = search.value.trim();
    location.hash = v ? '#/q/' + encodeURIComponent(v) : '#/';
  }, 220);
});

/* ---------------------------------------------------------------- router */
function route() {
  if (!DATA) return;
  const h = decodeURIComponent(location.hash.replace(/^#/, '')) || '/';
  const parts = h.split('/').filter(Boolean);
  setView(parts[0] === 'calendar' ? 'calendar' : 'timeline');

  if (parts[0] === 'p')        viewPost(parts.slice(1).join('/'));
  else if (parts[0] === 'calendar') viewCalendar(parts[1]);
  else if (parts[0] === 'q')   viewSearch(parts.slice(1).join('/'));
  else                         viewTimeline();

  if (parts[0] !== 'q' && search.value && !location.hash.startsWith('#/q/')) search.value = '';
  window.scrollTo(0, 0);
}

function setView(v) {
  document.querySelectorAll('#views button').forEach(b =>
    b.setAttribute('aria-pressed', String(b.dataset.view === v)));
}

const posts = () => DATA.items;
const byDate = () => posts().slice().sort((a, b) => a.date.localeCompare(b.date));

/* ---------------------------------------------------------------- cards */
function card(i) {
  const shot = i.thumb
    ? `<div class="shot"><img loading="lazy" src="${esc(i.thumb)}" alt=""></div>`
    : `<div class="noshot">text only</div>`;
  const badge = i.type === 'page' ? '<span class="badge pg">page</span>' : '';
  return `<a class="card" href="#/p/${esc(i.slug)}">
    ${shot}
    <div class="body">
      <div class="meta">${esc(i.date)} · ${esc(i.author)}${i.images ? ' · ' + i.images + ' img' : ''}</div>
      <h3>${esc(i.title)}</h3>
      <p class="ex">${esc(i.excerpt)}</p>
      <div>${badge}</div>
    </div></a>`;
}

/* ---------------------------------------------------------------- timeline */
function viewTimeline() {
  const m = DATA.meta;
  const items = byDate().filter(i => i.type === 'post');
  const years = {};
  items.forEach(i => (years[i.date.slice(0, 4)] ||= []).push(i));

  let h = `<section class="hero"><div class="wrap">
      <h1>The blog, 2009&ndash;2013</h1>
      <p>Everything the lab published on <code>heatsynclabs.org</code> before the
         site went quiet &mdash; the founding meetings in a police lodge, the RepRap,
         the balloon that reached 60,000 feet, the laser cutter Kickstarter, and the
         move into 140 W Main. Photographs included.</p>
      <ul class="stats">
        <li><b>${m.posts}</b><span>posts</span></li>
        <li><b>${m.pages}</b><span>pages</span></li>
        <li><b>${m.images}</b><span>images</span></li>
        <li><b>${m.first.slice(0, 4)}&ndash;${m.last.slice(0, 4)}</b><span>years</span></li>
      </ul></div></section><div class="wrap">`;

  Object.keys(years).sort().forEach(y => {
    h += `<div class="yearhead"><h2>${y}</h2>
            <span class="count">${years[y].length} post${years[y].length === 1 ? '' : 's'}</span></div>
          <div class="cards">${years[y].map(card).join('')}</div>`;
  });

  const pages = posts().filter(i => i.type === 'page');
  if (pages.length) {
    h += `<div class="yearhead"><h2>Pages</h2>
            <span class="count">${pages.length} standing pages &mdash; mission, pricing, board</span></div>
          <div class="cards">${pages.map(card).join('')}</div>`;
  }
  main.innerHTML = h + '</div>';
}

/* ---------------------------------------------------------------- calendar */
function viewCalendar(year) {
  const items = byDate();
  const yearsAvail = [...new Set(items.map(i => i.date.slice(0, 4)))].sort();
  const active = yearsAvail.includes(year) ? year : null;

  const byDay = {};
  items.forEach(i => (byDay[i.date] ||= []).push(i));

  let h = `<section class="hero"><div class="wrap">
      <h1>Calendar</h1>
      <p>Amber squares are days the blog published. Click one to read it.
         ${active ? '' : 'Pick a year, or scroll &mdash; every year is below.'}</p>
      <div class="cal-years">
        <button ${active ? '' : 'aria-pressed="true"'} onclick="location.hash='#/calendar'">All</button>
        ${yearsAvail.map(y => `<button ${y === active ? 'aria-pressed="true"' : ''}
           onclick="location.hash='#/calendar/${y}'">${y}</button>`).join('')}
      </div></div></section><div class="wrap">`;

  (active ? [active] : yearsAvail).forEach(y => {
    const n = items.filter(i => i.date.startsWith(y)).length;
    h += `<div class="yearhead"><h2>${y}</h2><span class="count">${n} entries</span></div>
          <div class="months">`;
    for (let mo = 0; mo < 12; mo++) {
      const first = new Date(Date.UTC(+y, mo, 1));
      const days = new Date(Date.UTC(+y, mo + 1, 0)).getUTCDate();
      const pad = first.getUTCDay();
      let cells = DOW.map(d => `<div class="dow">${d}</div>`).join('');
      cells += '<div class="day empty"></div>'.repeat(pad);
      let monthCount = 0;
      for (let d = 1; d <= days; d++) {
        const key = `${y}-${String(mo + 1).padStart(2, '0')}-${String(d).padStart(2, '0')}`;
        const hit = byDay[key];
        if (hit) {
          monthCount += hit.length;
          const label = hit.map(x => x.title).join(' · ').replace(/"/g, '');
          const href = hit.length === 1 ? `#/p/${hit[0].slug}` : `#/q/${key}`;
          cells += `<a class="day has${hit.length > 1 ? ' multi' : ''}" href="${href}"
                      title="${esc(label)}">${d}</a>`;
        } else {
          cells += `<div class="day">${d}</div>`;
        }
      }
      h += `<div class="month"><h3>${MONTHS[mo]}${monthCount ? ` <em>${monthCount}</em>` : ''}</h3>
              <div class="grid7">${cells}</div></div>`;
    }
    h += '</div>';
  });
  main.innerHTML = h + '</div>';
}

/* ---------------------------------------------------------------- search */
function viewSearch(q) {
  search.value = q;
  const terms = q.toLowerCase().split(/\s+/).filter(Boolean);
  const hits = byDate().filter(i =>
    terms.every(t => i._hay.includes(t) || i.date.includes(t)));
  main.innerHTML = `<section class="hero"><div class="wrap">
      <h1>${hits.length} result${hits.length === 1 ? '' : 's'}</h1>
      <p>Matching <code>${esc(q)}</code> in titles, text and authors.
         <a href="#/">Back to the timeline</a>.</p></div></section>
    <div class="wrap">${hits.length
      ? `<div class="cards" style="margin-top:var(--space-8)">${hits.map(card).join('')}</div>`
      : '<div class="empty">Nothing matched.</div>'}</div>`;
}

/* ---------------------------------------------------------------- post */
function viewPost(slug) {
  const all = byDate();
  const idx = all.findIndex(i => i.slug === slug);
  if (idx < 0) {
    main.innerHTML = `<div class="wrap"><div class="empty">No such entry.
      <a href="#/">Back to the timeline</a>.</div></div>`;
    return;
  }
  const i = all[idx];
  const prev = all[idx - 1], next = all[idx + 1];

  main.innerHTML = `<article class="post"><div class="wrap">
      <div class="post-head">
        <div class="kicker">${i.type === 'page' ? 'Page' : 'Post'} · ${esc(i.date)}</div>
        <h1>${esc(i.title)}</h1>
        <div class="byline">by ${esc(i.author)}${i.images ? ' · ' + i.images + ' image' + (i.images === 1 ? '' : 's') : ''}${i.comments ? ' · ' + i.comments + ' comments' : ''} · ${i.words} words</div>
      </div>
      ${i.attribution ? `<p class="attrib"><strong>Authorship corrected.</strong>
        Stored in the WordPress database under the <code>${esc(i.stored_author)}</code> account,
        but not ${esc(i.stored_author)}'s — ${esc(i.author)}'s account was deleted and her posts
        reassigned, which rewrote the author on every one of them.
        ${i.attribution === 'confirmed' ? 'She signs this post in the body.'
          : 'This post predates the ' + esc(i.stored_author) + ' account.'}</p>` : ''}
      <div class="content" id="body"><p class="note">loading…</p></div>
      <p class="srcline">Source: <code>wp_posts.ID=${esc(i.wp_id)}</code> ·
        Markdown: <code>posts/${esc(i.slug)}.md</code></p>
      <nav class="pager">
        ${prev ? `<a href="#/p/${esc(prev.slug)}">← ${esc(prev.title)}</a>` : '<span></span>'}
        ${next ? `<a href="#/p/${esc(next.slug)}" style="text-align:right">${esc(next.title)} →</a>` : '<span></span>'}
      </nav></div></article>`;

  fetch(`data/html/${slug}.html`)
    .then(r => { if (!r.ok) throw new Error(r.status); return r.text(); })
    .then(t => { document.getElementById('body').innerHTML = t; })
    .catch(() => {
      document.getElementById('body').innerHTML =
        `<p class="note">Could not load the body for this entry.</p>`;
    });
}
