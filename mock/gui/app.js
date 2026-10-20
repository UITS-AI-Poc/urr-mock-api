/* CatCloud research mock GUI. Vanilla JS, no build. Talks only to /api/v1 (served by serve.py).
   Flow: pick persona -> GET /students/by-netid/{net_id} (NSIF record) -> POST /matches with that record. */
'use strict';

const $ = (s, r = document) => r.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const store = {
  get(k, d) { try { const v = localStorage.getItem('urr.' + k); return v == null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem('urr.' + k, JSON.stringify(v)); } catch { /* storage may be blocked */ } },
  clear() { try { Object.keys(localStorage).filter(k => k.startsWith('urr.') && k !== 'urr.persona').forEach(k => localStorage.removeItem(k)); } catch { /* ignore */ } },
};

const S = {
  personas: [], p: null, student: null, types: {}, matches: null, matchSig: '', programs: null,
  shown: 8, q: '', major: 'any', loc: 'any', prog: 'Research', progQ: '', trace: [], mode: '',
  faculty: {}, chat: { step: 0, a: {} }, flow: {}, browse: { page: 1, q: '', data: null }, showScores: store.get('showScores', false),
};

/* ------------------------------------------------------------------ api */
async function api(method, path, body) {
  const t0 = performance.now();
  const entry = { method, path, status: '…', ms: 0, body: null };
  S.trace.push(entry); updateTraceBtn();
  let res, text;
  try {
    res = await fetch('/api/v1' + path, { method, headers: body ? { 'content-type': 'application/json' } : {}, body: body ? JSON.stringify(body) : undefined });
    text = await res.text();
  } catch (e) { entry.status = 'network error'; throw new Error('Cannot reach the local server: ' + e.message); }
  entry.status = res.status; entry.ms = Math.round(performance.now() - t0); entry.body = text;
  updateTraceBtn();
  let json = null; try { json = JSON.parse(text); } catch { /* non-json */ }
  if (!res.ok) throw new Error(`${method} ${path} -> ${res.status}: ${json ? JSON.stringify(json.detail ?? json) : text.slice(0, 200)}`);
  return json;
}

/* ------------------------------------------------------------ helpers */
const today = () => { const d = new Date(); d.setHours(0, 0, 0, 0); return d; };
const parseD = s => new Date(s + 'T00:00:00');
const fmtD = s => parseD(s).toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
const daysUntil = s => Math.ceil((parseD(s) - today()) / 86400000);
const initials = n => (n || '?').split(/\s+/).filter(Boolean).slice(0, 2).map(w => w[0].toUpperCase()).join('');
const clip = (s, n) => (s && s.length > n ? s.slice(0, n - 1).trimEnd() + '…' : s || '');
const TYPE_LABEL = { paid: 'Paid', volunteer: 'Volunteer', for_credit: 'For credit' };
const TYPE_KEY = { Paid: 'paid', Volunteer: 'volunteer', 'For credit': 'for_credit' };

function topics(f) { // research_interests is free text split on commas; keep short, topic-like phrases
  const raw = f.research_interests_raw || (f.research_interests || []).join(', ');
  const out = [];
  for (let t of raw.split(/\s-\s*(?=[A-Za-z])|^-\s*|[;,\n•]/)) {
    t = t.replace(/^[\s\-•*\d.)]+/, '').replace(/^(and|or)\s+/i, '').replace(/[ .;:]+$/, '').trim();
    if (t.length > 2 && t.length <= 50 && t.split(/\s+/).length <= 6 && !out.some(x => x.toLowerCase() === t.toLowerCase())) out.push(t);
  }
  return out.slice(0, 5);
}
const isMentoring = f => !f.project || f.project.inferred_from !== 'interests';
function applyLine(p) {
  if (!p) return '↗ No posted opening — reach out';
  if (p.application_mode === 'conversational') return '💬 A couple of quick questions to apply';
  if (p.application_status === 'closed') return `Closed ${fmtD(p.application_closes)}`;
  if (p.application_status === 'not_yet_open') return `🔔 Opens ${fmtD(p.application_opens)} — set a reminder`;
  const d = daysUntil(p.application_closes);
  return d <= 14 ? `⏰ Closes in ${Math.max(d, 0)} days — ${fmtD(p.application_closes)}` : `📋 Formal application, closes ${fmtD(p.application_closes)}`;
}
const closesSoon = p => p && p.application_mode === 'structured' && p.application_status === 'open' && daysUntil(p.application_closes) <= 14;
const typesOn = () => Object.keys(S.types).filter(k => S.types[k]);

/* ------------------------------------------------------- persona/data */
async function boot() {
  try { S.mode = (await (await fetch('/__config')).json()).mode; } catch { S.mode = 'unknown'; }
  $('#mode').textContent = '· ' + S.mode;
  $('#showScores').checked = S.showScores;
  let list;
  try { list = (await api('GET', '/students/demo-sample?count=20')).students; }
  catch (e) { return showError(e); }
  S.personas = list.filter(s => s.persona_label);
  if (!S.personas.length) return showError(new Error('The API returned no personas.'));
  if (S.personas.some(s => !s.persona_id)) banner('The API looks older than this GUI (personas have no persona_id). Redeploy the stack to get the current personas.', true);
  const sel = $('#persona');
  sel.innerHTML = S.personas.map(s => `<option value="${esc(s.net_id)}">${esc(s.persona_label)}</option>`).join('');
  const saved = store.get('persona', null);
  sel.value = S.personas.some(s => s.net_id === saved) ? saved : S.personas[0].net_id;
  await selectPersona(sel.value);
}

async function selectPersona(netId) {
  store.set('persona', netId);
  S.p = S.personas.find(s => s.net_id === netId);
  S.types = { paid: false, volunteer: false, for_credit: false, ...(S.p.preferences || {}) };
  S.matches = null; S.matchSig = ''; S.shown = 8; S.q = ''; S.major = 'any'; S.loc = 'any'; S.chat = { step: 0, a: {} }; S.flow = {};
  $('#blurb').textContent = S.p.blurb || '';
  try { S.student = await api('GET', `/students/by-netid/${encodeURIComponent(netId)}`); }
  catch (e) { return showError(e); }
  render();
}

async function ensureMatches() {
  const prefs = { ...S.types };
  const sig = S.student.student_id + JSON.stringify(prefs);
  if (S.matches && S.matchSig === sig) return S.matches;
  const r = await api('POST', '/matches', { student: S.student, preferences: prefs, limit: 100 });
  S.matches = r.matches; S.matchSig = sig;
  return S.matches;
}
async function getFaculty(id) {
  if (!S.faculty[id]) S.faculty[id] = await api('GET', `/faculty/${encodeURIComponent(id)}`);
  return S.faculty[id];
}
async function ensurePrograms() {
  if (!S.programs) S.programs = (await api('GET', '/programs?page_size=100')).programs;
  return S.programs;
}

function visibleMatches() {
  const on = typesOn(), q = S.q.trim().toLowerCase();
  const planWords = (S.student.plan || '').toLowerCase().split(/[^a-z]+/).filter(w => w.length > 3);
  return (S.matches || []).filter(m => {
    const f = m.faculty;
    if (on.length && !on.some(t => (f.opportunity_types || []).includes(TYPE_LABEL[t]))) return false;
    if (S.loc !== 'any' && !(f.research_locations || []).includes(S.loc)) return false;
    if (S.major === 'mine') {
      const mj = (f.majors_considered || []).join(' ').toLowerCase();
      if (!(/\b(any|all)\b/.test(mj) || planWords.some(w => mj.includes(w)))) return false;
    }
    if (q) {
      const hay = [f.name, f.title, f.primary_department, f.college, f.project && f.project.title, (f.research_interests || []).join(' ')].join(' ').toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });
}

/* --------------------------------------------------------------- views */
function rtop(active) {
  const a = k => (active === k ? 'on' : '');
  return `<div class="rtop"><div class="rtop__brand"><b>CATCLOUD</b><span>Research Opportunities</span></div>
    <nav class="rtabs"><a class="${a('explore')}" href="#/explore">Explore</a><a class="${a('saved')}" href="#/saved">Saved</a>
    <a class="${a('messages')}" href="#/messages">Messages</a><span class="avatar" title="${esc(S.p.persona_label)}">${esc(initials(S.p.persona_label.split('—')[0]))}</span></nav></div>`;
}
function shell(active, inner) {
  const item = (k, label, href) => href ? `<a class="${active === k ? 'is-on' : ''}" href="${href}">${label}</a>` : `<a class="is-off" title="Not part of the mock">${label}</a>`;
  return `<div class="shell"><nav class="side"><div class="side__logo">CatCloud</div>
    ${item('home', '🏠 Home', '#/home')}${item('s', '🔗 Services')}${item('e', '⭐ Events')}${item('n', '📣 News')}${item('opps', '🎓 Opportunities', '#/opps')}${item('c', '📅 Calendar')}
    </nav><div class="shell__main">${inner}</div></div>`;
}
const footnote = '<p class="muted" style="margin-top:36px">Mock data: faculty are from the ur.arizona.edu snapshot (2026-10-16); projects, deadlines and match reasons are synthetic. Read-only — nothing you enter is saved on a server.</p>';

async function viewHome() {
  const ms = await ensureMatches();
  const top = ms.find(m => typesOn().length === 0 || typesOn().some(t => (m.faculty.opportunity_types || []).includes(TYPE_LABEL[t]))) || ms[0];
  const f = top && top.faculty;
  const heads = f ? `<div class="card" style="border-left:4px solid var(--red)"><div class="eyebrow">NEW RESEARCH MATCH</div>
    <h3 style="font-size:20px">${esc(f.project.title)} — ${esc(f.name)}'s lab is looking for ${esc((f.opportunity_types || []).join(' / ').toLowerCase() || 'students')}.</h3>
    <p class="muted">${esc(top.match.reasons[0] || '')} · ${esc(applyLine(f.project).replace(/^[^\w]+/, ''))}</p>
    <a class="btn btn--primary" href="#/${isMentoring(f) ? 'faculty' : 'project'}/${esc(f.faculty_id)}">Open</a></div>` : '';
  return `<div class="wrap"><h1 style="font-size:34px">What can we help you with, ${esc(S.p.persona_label.split(' ')[0])}!</h1>
    <div class="row" style="margin:22px 0"><input class="input" placeholder="Drop a question here." disabled></div>
    <p class="muted">I'm plugged into:</p>
    <div class="chips" style="margin:8px 0 26px"><span class="chip">☰ Agenda</span><a class="chip on" href="#/opps">🎓 Opportunities</a><span class="chip">💰 Financial Aid</span><span class="chip">🎫 Registrar</span><span class="chip">📄 Bursar</span></div>
    <div class="eyebrow" style="margin-bottom:8px">HEADS-UP</div>${heads || '<div class="empty">No matches yet.</div>'}${footnote}</div>`;
}

const progTest = {
  Research: p => p.program_type === 'Research',
  Internship: p => /intern/i.test([p.name, p.description, p.program_type].join(' ')),
  Leadership: p => /leadership/i.test(p.program_type || ''),
  Volunteer: p => /volunteer|service/i.test([p.program_type, p.name].join(' ')),
};
async function viewOpps() {
  const progs = await ensurePrograms();
  const rows = progs.filter(progTest[S.prog]).filter(p => !S.progQ || (p.name + ' ' + (p.description || '')).toLowerCase().includes(S.progQ.toLowerCase()));
  const feature = S.prog === 'Research' ? `<div class="card card--feature"><div><div class="eyebrow">RESEARCH · POWERED BY THE CATCLOUD RESEARCH EXPERIENCE</div>
    <h3>Undergraduate Research Opportunities</h3><p class="muted" style="font-size:14px;margin:0">Browse active faculty projects, chat with the matcher, and apply directly through faculty-reviewed queues — a deeper experience built specifically for research, one click from here.</p></div>
    <a class="btn btn--primary" href="#/explore" style="white-space:nowrap">Explore Research →</a></div>` : '';
  const card = p => {
    const open = p.application_open && p.application_closed ? `Open Application: ${fmtD(p.application_open)} – ${fmtD(p.application_closed)}` : 'Open Application: TBD';
    return `<div class="card prog"><div class="eyebrow">${esc(p.topic || p.program_type || '')}</div><h3>${esc(p.name)}</h3>
      <div>${[p.program_type, p.topic].filter(Boolean).map(x => `<span class="pill">${esc(x)}</span>`).join('')}</div>
      <p class="muted" style="margin:8px 0">${esc(open)}</p>${p.website ? `<a href="${esc(p.website)}" target="_blank" rel="noopener">Program website ↗</a>` : ''}</div>`;
  };
  return shell('opps', `<div class="hero"><h2>Recommended Opportunities</h2><p>Based on your interest in ${esc(S.p.major_display || S.student.plan)}.</p></div>
    <div class="pad"><div><h1 style="font-size:32px">Opportunities</h1><p class="muted" style="font-size:14.5px">University programs for students to gain stand-out experience — jobs, internships, leadership, volunteer work, and research, all in one place.</p></div>
    <div class="searchrow"><input id="progQ" placeholder="Keyword" value="${esc(S.progQ)}"><button class="btn btn--primary" data-act="progSearch">SEARCH</button></div>
    <div class="chips">${Object.keys(progTest).map(k => `<span class="chip ${S.prog === k ? 'on' : ''}" data-act="prog" data-v="${k}">${k}</span>`).join('')}</div>
    ${feature}${rows.map(card).join('') || '<div class="empty">No programs in this category in the mock data.</div>'}
    <p class="muted">Viewing 1–${rows.length} of ${rows.length} · programs come from GET /programs</p></div>`);
}

function matchCard(m) {
  const f = m.faculty, p = f.project, mentoring = isMentoring(f);
  const fits = m.match.reasons.slice(0, 2).join(' · ');
  const meta = [(f.research_locations || []).join(', '), f.start_date ? `${mentoring ? 'listed' : 'active'} since ${f.start_date}` : ''].filter(Boolean).join(' · ');
  return `<article class="mcard"><div class="mcard__top"><div class="eyebrow">${esc([f.primary_department, f.college && f.college.replace(/^College of /, '')].filter(Boolean).join(' · '))}</div>
    <div>${closesSoon(p) ? '<span class="tag tag--soon">Closes soon</span> ' : ''}<span class="tag ${mentoring ? 'tag--mentor' : ''}">${mentoring ? 'Open to mentoring' : 'Active project'}</span></div></div>
    <h3>${esc(p.title)}</h3><div class="by">${esc(f.name)}${f.title ? ' · ' + esc(f.title) : ''}</div>
    <p style="margin:2px 0">${esc(clip(p.description, 230))}</p>
    ${fits ? `<div class="fits">✓ Fits you: ${esc(fits)}</div>` : ''}
    <div class="tags">${(f.opportunity_types || []).map(t => `<span>${esc(t)}</span>`).join('')}</div>
    <div class="muted">${esc(meta)}</div>
    <div class="mcard__top"><span style="font-weight:600">${esc(applyLine(p))}</span><a href="#/${mentoring ? 'faculty' : 'project'}/${esc(f.faculty_id)}"><b>${mentoring ? 'View profile' : 'View project'} →</b></a></div>
    ${S.showScores ? `<div class="score">mock score ${m.match.percent} · ${esc(JSON.stringify(m.match.signals))}</div>` : ''}</article>`;
}
function resultsHtml() {
  const vis = visibleMatches(), shown = vis.slice(0, S.shown);
  const soon = vis.some(m => closesSoon(m.faculty.project));
  const interest = (S.p.major_display || S.student.plan || '').toLowerCase();
  return `<div class="sect"><h2>Your matches</h2><p>We found ${vis.length} good fit${vis.length === 1 ? '' : 's'} for your interest in ${esc(interest)}.${soon ? " Some close soon, so it's worth a look first." : ''}</p>
    <p class="muted">Matches get better as you browse, save, and respond — CatCloud uses that activity to refine what shows up here.</p></div>
    <div class="cards">${shown.map(matchCard).join('') || '<div class="empty">No matches with these filters. Try clearing a filter.</div>'}</div>
    ${vis.length > shown.length ? `<div class="pager"><button class="btn" data-act="more">Show more (${vis.length - shown.length} left)</button></div>` : ''}`;
}
async function viewExplore() {
  await ensureMatches();
  const locs = [...new Set((S.matches || []).flatMap(m => m.faculty.research_locations || []))].sort();
  return rtop('explore') + `<div class="wrap"><h1>Find a research opportunity that fits you</h1>
    <p class="lede">One list of good matches, drawn from faculty who've told CatCloud they're available — an active project, or open to mentoring generally. More faculty join every term as new listings are confirmed.</p>
    <div class="row"><a class="btn btn--primary" href="#/chat">Chat with the matcher</a><a class="btn" href="#/browse">Browse all opportunities</a></div>
    <div style="margin-top:28px"><input id="q" class="input" placeholder="Search by topic, department, or faculty name" value="${esc(S.q)}"></div>
    <div class="filters"><span class="lbl">Type</span>${Object.keys(TYPE_LABEL).map(k => `<span class="tchip ${S.types[k] ? 'on' : ''}" data-act="type" data-v="${k}">${TYPE_LABEL[k]}${S.types[k] ? ' ✓' : ''}</span>`).join('')}
      <select id="major"><option value="any">Major</option><option value="mine" ${S.major === 'mine' ? 'selected' : ''}>Welcomes my major</option></select>
      <select id="loc"><option value="any">Location</option>${locs.map(l => `<option ${S.loc === l ? 'selected' : ''}>${esc(l)}</option>`).join('')}</select></div>
    <div id="results">${resultsHtml()}</div>${footnote}</div>`;
}

async function viewProject(id) {
  const f = await getFaculty(id), p = f.project;
  if (!p) return viewFacultyProfile(id);
  const ms = await ensureMatches(), m = ms.find(x => x.faculty.faculty_id === id);
  const saved = (store.get('saved.' + S.student.student_id, [])).includes(id);
  const closed = p.application_status === 'closed', notYet = p.application_status === 'not_yet_open';
  const apply = p.application_mode === 'conversational'
    ? `<div class="cta"><div class="eyebrow">HOW YOU'LL APPLY</div><h2 style="font-size:22px;margin:6px 0">A couple of quick questions</h2>
        <p>${esc(f.name)} reviews responses directly — no form beyond this, and no email to write. Your major and class standing go along automatically.</p>
        <a class="btn btn--primary" href="#/respond/${esc(id)}">Answer 2 quick questions</a></div>`
    : `<div class="cta"><div class="eyebrow">HOW YOU'LL APPLY</div><h2 style="font-size:22px;margin:6px 0">A formal application</h2>
        <p>${esc(f.name)} set up questions, a resume requirement, and a deadline — candidates are compared side by side after it closes.</p>
        <dl class="kv"><div><dt>Applications ${notYet ? 'open' : 'close'}</dt><dd>${esc(fmtD(notYet ? p.application_opens : p.application_closes))}</dd></div>
        <div><dt>Students wanted</dt><dd>${esc(p.spots ?? '—')} spot${p.spots === 1 ? '' : 's'}</dd></div></dl><div style="margin-top:14px">
        ${closed ? '<button class="btn" disabled>Closed</button>' : notYet ? '<button class="btn" data-act="remind">Remind me when it opens</button>' : `<a class="btn btn--primary" href="#/apply/${esc(id)}">Start application</a>`}</div></div>`;
  return rtop('explore') + `<div class="wrap"><a class="back" href="#/explore">← Back to results</a>
    <span class="tag ${isMentoring(f) ? 'tag--mentor' : ''}">${isMentoring(f) ? 'Open to mentoring' : 'Active project'}</span>
    <h1 style="font-size:38px;margin:10px 0 14px">${esc(p.title)}</h1>
    <div class="row"><span class="avatar">${esc(initials(f.name))}</span><div><b>${esc(f.name)}</b><div class="muted">${esc([f.title, f.primary_department].filter(Boolean).join(' · '))}</div></div>
      <a href="#/faculty/${esc(id)}">View faculty profile</a></div>
    <div class="panel"><h2>About the project</h2><p>${esc(p.description)}</p><p class="muted">${esc(p.disclaimer)}</p></div>
    <div class="panel"><h2>What you'd likely be doing</h2><ul>${p.likely_tasks.map(t => `<li>${esc(t)}</li>`).join('')}</ul><p class="muted">${esc(p.tasks_note)}</p></div>
    <div class="panel"><h2>Why this matches you</h2>${m && m.match.reasons.length ? `<ul>${m.match.reasons.map(r => `<li>${esc(r)}</li>`).join('')}</ul>` : '<p class="muted">This listing is not in your current ranked matches.</p>'}
      ${S.showScores && m ? `<div class="score">mock score ${m.match.percent} · ${esc(JSON.stringify(m.match.signals))}</div>` : ''}
      <p class="muted">Saving this or applying already tells us it's a good match — no extra step needed.</p></div>
    ${apply}
    <div class="panel"><h2>At a glance</h2><dl class="kv">
      <div><dt>Incentive</dt><dd>${esc(p.incentive || 'Not given')}</dd></div><div><dt>Credit</dt><dd>${esc(p.credit || 'Not given')}</dd></div>
      <div><dt>Format</dt><dd>${esc(p.format || '—')}</dd></div><div><dt>Location</dt><dd>${esc((f.research_locations || []).join(', ') || '—')}</dd></div>
      <div><dt>Majors considered</dt><dd>${esc(clip((f.majors_considered || []).join(', '), 140) || '—')}</dd></div>
      <div><dt>Prerequisites</dt><dd>${esc(clip(f.prerequisite_courses, 160) || 'None listed')}</dd></div></dl></div>
    <div class="row"><button class="btn" data-act="save" data-id="${esc(id)}">${saved ? '★ Saved' : '☆ Save for later'}</button>
      <a href="#" data-act="fit" class="muted">Not a fit? Tell us why</a></div>
    <div id="fitbox" hidden class="panel"><b>What's off about it?</b><div class="tags" style="margin:10px 0">${['Wrong field or major', "Time commitment doesn't work for me", 'Looks like it may already be filled', "Topic doesn't interest me", 'Other'].map(r => `<span class="tchip" data-act="reason">${r}</span>`).join('')}</div>
      <button class="btn btn--primary" data-act="fitSend">Send feedback</button> <span id="fitmsg" class="muted"></span></div>${footnote}</div>`;
}

async function viewFacultyProfile(id) {
  const f = await getFaculty(id), p = f.project;
  const saved = (store.get('saved.' + S.student.student_id, [])).includes(id);
  const tp = topics(f);
  return rtop('explore') + `<div class="wrap"><a class="back" href="#/explore">← Back to results</a>
    <span class="tag tag--mentor">${p && !isMentoring(f) ? 'Active project' : 'Open to mentoring'}</span>
    <div class="row" style="margin:12px 0"><span class="avatar" style="width:56px;height:56px;font-size:16px">${esc(initials(f.name))}</span>
      <div><h1 style="font-size:36px">${esc(f.name)}</h1><div class="muted">${esc([f.title, f.primary_department].filter(Boolean).join(' · '))}${f.college ? ' · ' + esc(f.college) : ''}</div></div></div>
    ${tp.length ? `<div class="tags">${tp.map(t => `<span>${esc(t)}</span>`).join('')}</div>` : ''}
    <div class="panel"><h2>About the lab</h2><p>${esc(p ? p.description : 'This researcher is not currently offering a posted opportunity.')}</p>${p ? `<p class="muted">${esc(p.disclaimer)}</p>` : ''}</div>
    ${f.prerequisite_courses ? `<div class="panel"><h2>Who can apply, in their own words</h2><blockquote style="margin:0;border-left:3px solid var(--red);padding-left:14px">${esc(f.prerequisite_courses)}</blockquote>
      <p class="muted">Shown exactly as the researcher entered it — there is no structured prerequisites field.</p></div>` : ''}
    <div class="panel"><h2>At a glance</h2><dl class="kv"><div><dt>Department</dt><dd>${esc(f.primary_department || '—')}</dd></div><div><dt>College</dt><dd>${esc(f.college || '—')}</dd></div>
      <div><dt>Typically offers</dt><dd>${esc((f.opportunity_types || []).join(', ') || '—')}</dd></div><div><dt>Location</dt><dd>${esc((f.research_locations || []).join(', ') || '—')}</dd></div>
      <div><dt>Majors considered</dt><dd>${esc(clip((f.majors_considered || []).join(', '), 140) || '—')}</dd></div><div><dt>Active projects</dt><dd>${p ? '1 listed' : 'None listed'}</dd></div></dl></div>
    <div class="row">${p ? `<a class="btn btn--primary" href="#/${p.application_mode === 'structured' ? 'apply' : 'respond'}/${esc(id)}">${p.application_mode === 'structured' ? 'Start application' : 'Answer 2 quick questions'}</a>` : ''}
      ${p ? `<a class="btn" href="#/project/${esc(id)}">View project</a>` : ''}
      <button class="btn" data-act="save" data-id="${esc(id)}">${saved ? '★ Saved' : '☆ Save for later'}</button></div>${footnote}</div>`;
}

async function viewRespond(id) {
  const f = await getFaculty(id), n = store.get('resp.' + S.student.student_id, []).length;
  const fl = S.flow.respond && S.flow.respond.id === id ? S.flow.respond : (S.flow.respond = { id, step: 'form', a1: '', a2: '' });
  const auto = `<div class="auto"><div><b>Major</b>${esc(S.p.major_display)}</div><div><b>Class standing</b>${esc(S.p.class_standing)}</div></div>`;
  if (fl.step === 'done') return rtop('explore') + `<div class="wrap"><div class="cta"><h2>Sent to ${esc(f.name)}'s queue</h2><p>They review responses like this one directly — there's nothing more for you to do right now.</p>
    <p class="muted"><b>Mock:</b> this was stored only in this browser (see Messages); the API is read-only.</p></div><a class="btn btn--primary" href="#/explore">Back to your matches</a></div>`;
  if (fl.step === 'review') return rtop('explore') + `<div class="wrap"><a class="back" href="#/project/${esc(id)}">← Back to opportunity</a><h1 style="font-size:34px">This is what ${esc(f.name)} will see</h1>${auto}
    <div class="panel"><div class="eyebrow">WHAT DREW YOU HERE</div><p>${esc(fl.a1)}</p><div class="eyebrow">FOLLOW-THROUGH EXAMPLE</div><p>${esc(fl.a2)}</p></div>
    <div class="row"><button class="btn btn--primary" data-act="respSubmit" data-id="${esc(id)}">Submit response</button><button class="btn" data-act="respEdit">Edit answers</button></div></div>`;
  return rtop('explore') + `<div class="wrap"><a class="back" href="#/project/${esc(id)}">← Back to opportunity</a><h1 style="font-size:34px">Answer two quick questions</h1>
    <p class="lede">${esc(f.name)} reviews responses like this one directly — there's no form to fill out beyond this, and no email to write. Your major and class standing go along automatically.</p>
    <div class="banner" style="border-radius:8px">This will be your ${n + 1}${['st', 'nd', 'rd'][n] || 'th'} response from this browser. Faculty read every one individually — make each one count rather than sending many.</div>
    <div class="field"><label for="a1">What drew you to this project or lab specifically?</label><textarea id="a1" class="input">${esc(fl.a1)}</textarea></div>
    <div class="field"><label for="a2">A real example of follow-through</label><textarea id="a2" class="input">${esc(fl.a2)}</textarea><span class="muted">Doesn't need to be academic — a project, a job, a habit.</span></div>
    <button class="btn btn--primary" data-act="respReview">Review my response</button></div>`;
}

async function viewApply(id) {
  const f = await getFaculty(id), p = f.project;
  const fl = S.flow.apply && S.flow.apply.id === id ? S.flow.apply : (S.flow.apply = { id, done: false });
  if (fl.done) return rtop('explore') + `<div class="wrap"><div class="cta"><h2>Application submitted</h2><p>${esc(f.name)} reviews applications together after they close${p && p.application_closes ? ' on ' + esc(fmtD(p.application_closes)) : ''}.</p>
    <p class="muted"><b>Mock:</b> stored only in this browser (see Messages); the API is read-only.</p></div><a class="btn btn--primary" href="#/explore">Back to your matches</a></div>`;
  return rtop('explore') + `<div class="wrap"><a class="back" href="#/project/${esc(id)}">← Back to project</a><h1 style="font-size:34px">Apply to ${esc(f.name)}'s group</h1>
    <p class="lede">This is a formal application, reviewed alongside everyone else's after the deadline${p && p.application_closes ? ' (' + esc(fmtD(p.application_closes)) + ')' : ''} — not a rolling reply.</p>
    <div class="auto"><div><b>Major</b>${esc(S.p.major_display)}</div><div><b>Class standing</b>${esc(S.p.class_standing)}</div></div>
    ${['Why are you interested in this project?', 'What relevant coursework or experience do you have?', 'What days or times are you generally available?'].map((q, i) => `<div class="field"><label for="ap${i}">${q}</label><textarea id="ap${i}" class="input"></textarea></div>`).join('')}
    <div class="field"><label for="resume">Resume — required (PDF)</label><input id="resume" type="file" accept="application/pdf"><span class="muted">The file stays in your browser; nothing is uploaded.</span></div>
    <button class="btn btn--primary" data-act="applySubmit" data-id="${esc(id)}">Submit application</button> <span id="apmsg" class="muted"></span></div>`;
}

function viewChat() {
  const c = S.chat, bub = (t, u) => `<div class="bubble ${u ? 'u' : ''}">${esc(t)}</div>`;
  let h = bub('Hi! I can help you find a research opportunity that fits your interests and schedule. What subjects or problems have you found yourself curious about lately?');
  if (c.step >= 1) h += bub(c.a.interest || '(skipped)', true) + bub('Good start. Roughly how many hours a week could you commit?');
  if (c.step >= 2) h += bub(c.a.hours, true) + bub('And does it need to be paid, or would volunteer or for-credit work too? Pick any that work.');
  let input = '';
  if (c.step === 0) input = `<div class="field"><label for="ci">Type your answer</label><input id="ci" class="input" placeholder="e.g. how the brain makes decisions"></div><button class="btn btn--primary" data-act="chat0">Send</button>`;
  if (c.step === 1) input = `<div class="field"><label for="ch">Hours per week</label><select id="ch" class="input"><option>4–6 hours</option><option selected>8–10 hours</option><option>12+ hours</option></select></div><button class="btn btn--primary" data-act="chat1">Send</button>`;
  if (c.step === 2) input = `<div class="tags">${Object.keys(TYPE_LABEL).map(k => `<span class="tchip ${S.types[k] ? 'on' : ''}" data-act="ctype" data-v="${k}">${TYPE_LABEL[k]}</span>`).join('')}</div><p><button class="btn btn--primary" data-act="chat2">Show my matches</button></p>`;
  return rtop('explore') + `<div class="wrap"><a class="back" href="#/explore">← Back to results</a><h1 style="font-size:34px">Let's find your fit</h1>
    <p class="lede">Answer a few questions — this isn't graded, just a starting point. <span class="muted">(Scripted for the mock: your answers set the type preferences sent to POST /matches.)</span></p>
    <div class="chat">${h}</div>${input}</div>`;
}

async function viewBrowse() {
  const b = S.browse, qs = new URLSearchParams({ page: b.page, page_size: 20 }); if (b.q) qs.set('q', b.q);
  const d = await api('GET', '/faculty?' + qs);
  const pages = Math.max(1, Math.ceil(d.total / d.page_size));
  return rtop('explore') + `<div class="wrap"><a class="back" href="#/explore">← Back to matches</a><h1 style="font-size:34px">Browse all researchers</h1>
    <p class="lede">${d.total} researchers from GET /faculty — unranked.</p>
    <div class="row"><input id="bq" class="input" style="flex:1" placeholder="Search by name, department or topic" value="${esc(b.q)}"><button class="btn btn--primary" data-act="bsearch">Search</button></div>
    <div class="cards">${d.faculty.map(f => `<article class="mcard"><div class="mcard__top"><div class="eyebrow">${esc(f.primary_department || '')}</div><span class="tag">${esc(f.project ? f.project.application_status.replace(/_/g, ' ') : 'no listing')}</span></div>
      <h3 style="font-size:19px">${esc(f.name)}</h3><div class="by">${esc(f.title || '')}</div><div class="tags">${(f.opportunity_types || []).map(t => `<span>${esc(t)}</span>`).join('')}</div>
      <a href="#/${f.project && !isMentoring(f) ? 'project' : 'faculty'}/${esc(f.faculty_id)}"><b>View →</b></a></article>`).join('')}</div>
    <div class="pager"><button class="btn" data-act="bprev" ${b.page <= 1 ? 'disabled' : ''}>← Prev</button><span class="muted">Page ${d.page} of ${pages}</span><button class="btn" data-act="bnext" ${b.page >= pages ? 'disabled' : ''}>Next →</button></div></div>`;
}

async function viewSaved() {
  const ids = store.get('saved.' + S.student.student_id, []);
  const fs = await Promise.all(ids.map(getFaculty));
  return rtop('saved') + `<div class="wrap"><h1 style="font-size:34px">Saved</h1><p class="lede">Stored only in this browser for ${esc(S.p.persona_label.split('—')[0])}.</p>
    ${fs.length ? `<div class="cards">${fs.map(f => `<article class="mcard"><h3 style="font-size:19px">${esc(f.project ? f.project.title : f.name)}</h3><div class="by">${esc(f.name)}</div><a href="#/${f.project && !isMentoring(f) ? 'project' : 'faculty'}/${esc(f.faculty_id)}"><b>View →</b></a></article>`).join('')}</div>` : '<div class="empty">Nothing saved yet.</div>'}</div>`;
}
function viewMessages() {
  const rs = store.get('resp.' + S.student.student_id, []);
  return rtop('messages') + `<div class="wrap"><h1 style="font-size:34px">Messages</h1><p class="lede">Responses you submitted in this browser. The mock API is read-only, so nothing reaches a faculty queue.</p>
    ${rs.length ? `<div class="cards">${rs.map(r => `<article class="mcard"><b>${esc(r.name)}</b><span class="muted">${esc(r.kind)} · ${esc(r.at)} · "sent" (local only)</span></article>`).join('')}</div>` : '<div class="empty">No messages.</div>'}</div>`;
}

/* ------------------------------------------------------------- router */
const route = () => { const [, a = 'home', b] = location.hash.split('/'); return [a, b ? decodeURIComponent(b) : null]; };
const VIEWS = { home: viewHome, opps: viewOpps, explore: viewExplore, browse: viewBrowse, chat: viewChat, saved: viewSaved, messages: viewMessages,
  project: viewProject, faculty: viewFacultyProfile, respond: viewRespond, apply: viewApply };

async function render() {
  if (!S.student) return;
  const [name, id] = route(), view = VIEWS[name] || viewHome;
  $('#app').innerHTML = '<div class="loading">Loading…</div>';
  try { $('#app').innerHTML = await view(id); window.scrollTo(0, 0); }
  catch (e) { showError(e); }
}
function showError(e) {
  $('#app').innerHTML = `<div class="wrap"><div class="panel" style="border-color:#f2b5b5"><h2>Something went wrong</h2><p style="word-break:break-word">${esc(e.message)}</p>
    <p class="muted">If this mentions the AWS CLI or SSO, run <code>aws sso login --profile aipoc-admin</code> and restart serve.py, or start it with <code>--local</code>.</p></div></div>`;
}
function banner(msg, err) { const b = $('#banner'); b.textContent = msg; b.hidden = !msg; b.className = 'banner' + (err ? ' banner--err' : ''); }
function refreshResults() { const r = $('#results'); if (r) r.innerHTML = resultsHtml(); }

/* ------------------------------------------------------------- events */
document.addEventListener('click', async e => {
  const el = e.target.closest('[data-act]'); if (!el) return;
  const act = el.dataset.act, v = el.dataset.v, id = el.dataset.id;
  const val = s => ($(s) ? $(s).value.trim() : '');
  if (act === 'fit') { e.preventDefault(); $('#fitbox').hidden = !$('#fitbox').hidden; }
  else if (act === 'reason') el.classList.toggle('on');
  else if (act === 'fitSend') $('#fitmsg').textContent = 'Thanks — noted (mock: not saved).';
  else if (act === 'remind') { el.textContent = '✓ Reminder set (local only)'; el.disabled = true; }
  else if (act === 'save') {
    const k = 'saved.' + S.student.student_id, cur = store.get(k, []);
    store.set(k, cur.includes(id) ? cur.filter(x => x !== id) : [...cur, id]); render();
  }
  else if (act === 'type') { S.types[v] = !S.types[v]; S.shown = 8; render(); }
  else if (act === 'more') { S.shown += 8; refreshResults(); }
  else if (act === 'prog') { S.prog = v; render(); }
  else if (act === 'progSearch') { S.progQ = val('#progQ'); render(); }
  else if (act === 'respReview') { S.flow.respond.a1 = val('#a1'); S.flow.respond.a2 = val('#a2'); S.flow.respond.step = 'review'; render(); }
  else if (act === 'respEdit') { S.flow.respond.step = 'form'; render(); }
  else if (act === 'respSubmit') { await logResponse(id, 'Quick-question response'); S.flow.respond.step = 'done'; render(); }
  else if (act === 'applySubmit') {
    if (!$('#resume').files.length) { $('#apmsg').textContent = 'A PDF resume is required for this listing.'; return; }
    await logResponse(id, 'Formal application'); S.flow.apply.done = true; render();
  }
  else if (act === 'chat0') { S.chat.a.interest = val('#ci'); S.chat.step = 1; render(); }
  else if (act === 'chat1') { S.chat.a.hours = val('#ch') ? $('#ch').value : ''; S.chat.step = 2; render(); }
  else if (act === 'ctype') { S.types[v] = !S.types[v]; el.classList.toggle('on'); }
  else if (act === 'chat2') { S.shown = 8; location.hash = '#/explore'; }
  else if (act === 'bsearch') { S.browse.q = val('#bq'); S.browse.page = 1; render(); }
  else if (act === 'bprev') { S.browse.page--; render(); }
  else if (act === 'bnext') { S.browse.page++; render(); }
});
async function logResponse(id, kind) {
  const f = await getFaculty(id), k = 'resp.' + S.student.student_id;
  store.set(k, [...store.get(k, []), { name: f.name, kind, at: new Date().toLocaleString() }]);
}
document.addEventListener('input', e => {
  if (e.target.id === 'q') { S.q = e.target.value; S.shown = 8; refreshResults(); }
});
document.addEventListener('change', e => {
  if (e.target.id === 'major') { S.major = e.target.value; refreshResults(); }
  if (e.target.id === 'loc') { S.loc = e.target.value; refreshResults(); }
});
document.addEventListener('keydown', e => {
  if (e.key === 'Enter' && e.target.id === 'progQ') { S.progQ = e.target.value.trim(); render(); }
  if (e.key === 'Enter' && e.target.id === 'bq') { S.browse.q = e.target.value.trim(); S.browse.page = 1; render(); }
});
$('#persona').addEventListener('change', e => { location.hash = '#/home'; selectPersona(e.target.value); });
$('#restart').addEventListener('click', () => { store.clear(); S.faculty = {}; selectPersona(S.p.net_id); location.hash = '#/home'; });
$('#showScores').addEventListener('change', e => { S.showScores = e.target.checked; store.set('showScores', S.showScores); render(); });
window.addEventListener('hashchange', render);

/* -------------------------------------------------------------- trace */
function updateTraceBtn() {
  $('#traceBtn').textContent = `API calls (${S.trace.length})`;
  if (!$('#trace').hidden) drawTrace();
}
function drawTrace() {
  $('#traceList').innerHTML = [...S.trace].reverse().map((t, i) => {
    const cls = String(t.status).startsWith('2') ? 's2xx' : 's4xx';
    return `<li data-i="${S.trace.length - 1 - i}"><span class="${cls}">${esc(t.status)}</span> <b>${esc(t.method)}</b> ${esc(t.path)} <span class="muted">${t.ms}ms</span></li>`;
  }).join('');
}
$('#traceBtn').addEventListener('click', () => { $('#trace').hidden = !$('#trace').hidden; drawTrace(); });
$('#traceClose').addEventListener('click', () => { $('#trace').hidden = true; });
$('#traceList').addEventListener('click', e => {
  const li = e.target.closest('li'); if (!li) return;
  const ex = $('pre', li); if (ex) return ex.remove();
  const b = S.trace[+li.dataset.i].body || '';
  const pre = document.createElement('pre'); pre.textContent = b.length > 4000 ? b.slice(0, 4000) + '\n… (truncated)' : b; li.appendChild(pre);
});

boot();
