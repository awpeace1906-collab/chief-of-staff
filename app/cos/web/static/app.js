// Chief of Staff web app: talks only to this server's /api. No third-party scripts.
(() => {
  const DIV = { me: "Andrew", stephanie: "Stephanie", kids: "Home & kids" };
  const KIND = { calendar: "Calendar", email: "Email", board: "To-do list", list: "To-do list", other: "Proposal" };
  const SOURCE = { gmail: "Gmail", outlook: "Outlook", calendar: "calendar", manual: "you", readywhen: "readywhen", "microsoft-todo": "Microsoft To Do", digest: "a digest" };
  const state = { items: [], proposals: [], brief: null, messages: [], local: [], canWrite: true, agent: "Assistant",
                  tz: "America/Denver", open: new Set(), filter: "all", briefOpen: false, loaded: false };
  const $ = (id) => document.getElementById(id);
  const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };

  // server calls; a 401 means the sign-in cookie expired
  async function api(path, opts = {}) {
    const r = await fetch(path, { credentials: "same-origin", ...opts,
      headers: { ...(opts.body ? { "Content-Type": "application/json" } : {}), ...(opts.headers || {}) } });
    if (r.status === 401) { location.href = "/login"; throw new Error("signed out"); }
    if (!r.ok) {
      let detail = ""; try { detail = (await r.json()).detail || ""; } catch (e) {}
      const err = new Error(detail || `HTTP ${r.status}`); err.status = r.status; throw err;
    }
    return r.status === 204 ? null : r.json();
  }
  const send = (path, method, body) => api(path, { method, body: JSON.stringify(body) });

  // dates in the owner's timezone
  const ymd = (d) => new Intl.DateTimeFormat("en-CA", { timeZone: state.tz, year: "numeric", month: "2-digit", day: "2-digit" }).format(d);
  const today = () => ymd(new Date());
  const addDays = (s, n) => { const d = new Date(s + "T12:00:00Z"); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10); };
  const dow = (s) => new Date(s + "T12:00:00Z").toLocaleDateString("en-US", { weekday: "short", timeZone: "UTC" });
  const md = (s) => new Date(s + "T12:00:00Z").toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
  function tickClock() {
    $("clock").textContent = new Intl.DateTimeFormat("en-US", { timeZone: state.tz, weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit", timeZoneName: "short" }).format(new Date());
  }
  tickClock(); setInterval(tickClock, 30000);

  function setAgent(name) {
    state.agent = String(name || "Assistant").slice(0, 40);
    document.querySelectorAll(".agentName").forEach((n) => (n.textContent = state.agent));
  }

  // tabs (remember the last one per device)
  const tabs = ["today", "todo", "talk", "more"];
  function show(name) {
    for (const t of tabs) { $("tab-" + t).setAttribute("aria-selected", String(t === name)); $(t).hidden = t !== name; }
    try { localStorage.setItem("cos.tab", name); } catch (e) {}
    window.scrollTo(0, 0);
    if (name === "talk") renderThread();
    if (name === "more") loadStatus();
  }
  for (const t of tabs) $("tab-" + t).addEventListener("click", () => show(t));
  document.querySelectorAll(".stat").forEach((b) => b.addEventListener("click", () => {
    if (b.dataset.go === "today") $("propGroup").scrollIntoView({ behavior: "smooth", block: "start" }); else show(b.dataset.go);
  }));
  let startTab = "today";
  try { const h = location.hash.slice(1); startTab = tabs.includes(h) ? h : (localStorage.getItem("cos.tab") || "today"); state.filter = localStorage.getItem("cos.filter") || "all"; } catch (e) {}
  show(tabs.includes(startTab) ? startTab : "today");

  // division filter
  function paintChips() { document.querySelectorAll(".chip").forEach((c) => c.setAttribute("aria-pressed", String(c.dataset.f === state.filter))); }
  document.querySelectorAll(".chip").forEach((c) => c.addEventListener("click", () => {
    state.filter = c.dataset.f; paintChips(); renderItems();
    try { localStorage.setItem("cos.filter", state.filter); } catch (e) {}
  }));
  paintChips();

  // tiny, safe markdown: paragraphs, bullets, **bold**
  function renderMd(text, box) {
    box.textContent = "";
    let list = null;
    for (const raw of String(text || "").split("\n")) {
      const line = raw.trimEnd();
      if (!line.trim()) { list = null; continue; }
      const bullet = /^\s*[-*•]\s+(.*)$/.exec(line);
      const target = bullet ? (list ||= box.appendChild(el("ul"))).appendChild(el("li")) : (list = null, box.appendChild(el("p")));
      const content = bullet ? bullet[1] : line.replace(/^#+\s*/, "");
      content.split(/(\*\*[^*]+\*\*)/).forEach((part) => {
        if (/^\*\*[^*]+\*\*$/.test(part)) target.appendChild(el("strong", null, part.slice(2, -2)));
        else if (part) target.appendChild(document.createTextNode(part));
      });
    }
  }

  function flash(msg) { $("talkStatus").textContent = msg; $("addStatus").textContent = msg; setTimeout(() => { $("addStatus").textContent = ""; }, 4000); }

  // writes
  async function patchItem(item, fields) {
    Object.assign(item, fields); renderItems();  // optimistic
    try { await send("/api/board/" + encodeURIComponent(item.id), "PATCH", fields); }
    catch (e) { flash("That didn't save: " + e.message); }
    refresh();
  }

  // to-do strips
  const isDone = (i) => i.status === "done" || i.status === "dropped";
  function whenLabel(item) {
    const t = today(), w = el("div", "when");
    if (!item.due) { w.append(el("span", "day", "—"), el("span", "date", "no date")); return w; }
    if (!isDone(item) && item.due < t) w.classList.add("overdue");
    w.append(el("span", "day", item.due === t ? "Today" : item.due === addDays(t, 1) ? "Tmrw" : dow(item.due)), el("span", "date", md(item.due)));
    return w;
  }
  const sourceLabel = (item) => item.source?.label || SOURCE[item.source?.kind] || "";

  function strip(item, opts = {}) {
    const s = el("div", "strip" + (isDone(item) ? " done" : ""));
    s.dataset.div = DIV[item.division] ? item.division : "me";
    const main = el("div", "main");
    const body = el("button", "body"); body.type = "button";
    body.setAttribute("aria-expanded", String(state.open.has(item.id)));
    body.append(el("span", "title", item.title || "(untitled)"));
    const meta = el("span", "meta"); meta.append(el("span", "tag", DIV[item.division] || "Andrew"));
    if (sourceLabel(item)) meta.append(el("span", "src", "from " + sourceLabel(item)));
    body.append(meta);
    body.addEventListener("click", () => { state.open.has(item.id) ? state.open.delete(item.id) : state.open.add(item.id); renderItems(); });
    const act = el("div", "act");
    const btn = el("button", "check", "✓"); btn.type = "button";
    btn.setAttribute("aria-label", (isDone(item) ? "Mark not done: " : "Mark done: ") + (item.title || ""));
    btn.disabled = !state.canWrite;
    btn.addEventListener("click", () => patchItem(item, { status: isDone(item) ? "open" : "done" }));
    act.append(btn);
    main.append(el("div", "band"), whenLabel(item), body, act);
    s.append(main);
    if (state.open.has(item.id) && !opts.compact) s.append(details(item));
    if (!isDone(item)) swipe(s, item);
    return s;
  }

  function details(item) {
    const box = el("div", "more");
    if (item.notes) box.append(el("p", "notes", item.notes));
    if (item.source?.url) { const a = el("a", "status", "Open the original"); a.href = item.source.url; a.target = "_blank"; a.rel = "noopener"; box.append(a); }
    const t = today();
    const snooze = el("div", "row");
    for (const [label, due] of [["Tomorrow", addDays(t, 1)], ["Next week", addDays(t, 7)], ["No date", null]]) {
      const b = el("button", "btn small", label); b.type = "button"; b.disabled = !state.canWrite;
      b.addEventListener("click", () => patchItem(item, { due }));
      snooze.append(b);
    }
    const fields = el("div", "fields");
    const dl = el("label", null, "Due"); const di = el("input"); di.type = "date"; di.value = item.due || ""; di.disabled = !state.canWrite;
    di.addEventListener("change", () => patchItem(item, { due: di.value || null })); dl.append(di);
    const fl = el("label", null, "For"); const fs = el("select");
    for (const [v, n] of Object.entries(DIV)) { const o = el("option", null, n); o.value = v; if (v === item.division) o.selected = true; fs.append(o); }
    fs.disabled = !state.canWrite; fs.addEventListener("change", () => patchItem(item, { division: fs.value })); fl.append(fs);
    fields.append(dl, fl);
    box.append(el("span", "status", "Snooze"), snooze, fields);
    return box;
  }

  // swipe right to finish
  function swipe(s, item) {
    let x0 = null, y0 = 0, dx = 0, on = false;
    s.addEventListener("pointerdown", (e) => { if (e.pointerType === "mouse" || !state.canWrite) return; x0 = e.clientX; y0 = e.clientY; dx = 0; on = false; });
    s.addEventListener("pointermove", (e) => {
      if (x0 == null) return;
      dx = e.clientX - x0;
      if (!on && Math.abs(e.clientY - y0) > 12) { x0 = null; return; }
      if (!on && dx > 12) { on = true; s.classList.add("swiping"); }
      if (on) { s.style.transform = `translateX(${Math.max(0, Math.min(dx, 120))}px)`; s.classList.toggle("swipe-ok", dx > 90); }
    });
    const end = () => {
      if (x0 == null) return;
      x0 = null; s.classList.remove("swiping", "swipe-ok"); s.style.transform = "";
      if (on && dx > 90) patchItem(item, { status: "done" });
    };
    s.addEventListener("pointerup", end); s.addEventListener("pointercancel", end);
  }

  function renderItems() {
    if (!state.loaded) return;
    const t = today(), week = addDays(t, 7);
    const all = state.items;
    const openAll = all.filter((i) => !isDone(i));
    const pick = (list) => state.filter === "all" ? list : list.filter((i) => (i.division || "me") === state.filter);
    const open = pick(openAll);
    const byDue = (a, b) => (a.due || "9999").localeCompare(b.due || "9999") || String(a.title).localeCompare(String(b.title));
    const overdue = openAll.filter((i) => i.due && i.due < t), dueToday = openAll.filter((i) => i.due === t);
    $("todoBadge").textContent = openAll.length ? String(openAll.length) : "";
    $("nDue").textContent = dueToday.length; $("nOver").textContent = overdue.length;
    $("statOver").classList.toggle("alert", overdue.length > 0);

    const groups = [
      ["Overdue", open.filter((i) => i.due && i.due < t)],
      ["Today", open.filter((i) => i.due === t)],
      ["Tomorrow", open.filter((i) => i.due === addDays(t, 1))],
      ["This week", open.filter((i) => i.due && i.due > addDays(t, 1) && i.due <= week)],
      ["Later", open.filter((i) => i.due && i.due > week)],
      ["No date", open.filter((i) => !i.due)],
    ];
    const box = $("todoGroups"); box.textContent = "";
    for (const [name, list] of groups) {
      if (!list.length) continue;
      const g = el("div", "group"); const h = el("h2", null, name); h.append(el("small", null, String(list.length)));
      g.append(h); list.sort(byDue).forEach((i) => g.append(strip(i))); box.append(g);
    }
    if (!open.length) box.append(el("p", "empty", state.filter === "all" ? "Nothing open. Add a to-do below, or send one from the Talk tab." : "Nothing open for this person."));

    const done = pick(all.filter(isDone)).sort((a, b) => String(b.updatedAt || "").localeCompare(String(a.updatedAt || ""))).slice(0, 15);
    const dl = $("doneList"); dl.textContent = "";
    done.forEach((i) => dl.append(strip(i)));
    if (!done.length) dl.append(el("p", "note", "Finished items show up here."));

    const dt = $("dueToday"); dt.textContent = "";
    [...overdue, ...dueToday].sort(byDue).forEach((i) => dt.append(strip(i, { compact: true })));
    if (!overdue.length && !dueToday.length) dt.append(el("p", "note", "Nothing due today."));
  }

  // brief
  function renderBrief() {
    if (!state.loaded) return;
    const box = $("brief"); box.textContent = "";
    const b = state.brief;
    if (!b) { box.append(el("p", "empty", "The morning brief lands here each morning.")); return; }
    const card = el("div", "card brief" + (state.briefOpen ? "" : " collapsed"));
    card.append(el("h3", null, b.subject || "Morning brief"));
    card.append(el("p", "note", b.day ? (b.day === today() ? "Today · " : "") + dow(b.day) + " " + md(b.day) : ""));
    const body = el("div", "md"); renderMd(b.markdown, body); card.append(body);
    const tog = el("button", "btn quiet small", state.briefOpen ? "Show less" : "Read all"); tog.type = "button";
    tog.addEventListener("click", () => { state.briefOpen = !state.briefOpen; renderBrief(); });
    card.append(tog); box.append(card);
  }

  // proposals
  const PILL = { approved: "Approved · being done", done: "Done", declined: "Declined", failed: "Couldn't do it" };
  function proposalCard(p) {
    const c = el("div", "card proposal"); c.dataset.div = p.division || "";
    const inner = el("div", "inner");
    const k = el("div", "kicker"); k.append(el("span", "num", "#" + (p.n ?? "•")), el("span", null, KIND[p.kind] || p.kind || "Proposal"));
    if (p.calendar) k.append(el("span", null, "· " + p.calendar));
    inner.append(k);
    inner.append(el("p", "ptitle", p.title || p.summary || ""));
    const facts = el("dl", "facts");
    const add = (dt, dd) => { if (!dd) return; facts.append(el("dt", null, dt), el("dd", null, dd)); };
    add("When", p.when); add("Where", p.where); add("Change", p.change);
    if (facts.childNodes.length) inner.append(facts);
    if (p.title && p.summary) inner.append(el("p", "why", p.summary));
    if (p.changes) inner.append(el("p", "result", "Your changes: " + p.changes));
    if (p.result) inner.append(el("p", "result", p.result));
    const row = el("div", "row");
    if (p.status === "pending") {
      const yes = el("button", "btn primary", "Approve"); yes.type = "button";
      const edit = el("button", "btn", "Change…"); edit.type = "button";
      const no = el("button", "btn quiet", "Decline"); no.type = "button";
      const bs = [yes, edit, no]; bs.forEach((b) => (b.disabled = !state.canWrite));
      yes.addEventListener("click", () => decide(p, { status: "approved" }, bs));
      no.addEventListener("click", () => decide(p, { status: "declined" }, bs));
      edit.addEventListener("click", () => {
        if (inner.querySelector(".changebox")) return;
        const cb = el("div", "changebox");
        const lab = el("label", null, "What should be different?"); const ta = el("textarea"); ta.placeholder = "Make it 7pm, and put it on the Family calendar"; lab.append(ta);
        const r2 = el("div", "row");
        const go = el("button", "btn primary", "Approve with changes"); go.type = "button";
        const cancel = el("button", "btn quiet", "Cancel"); cancel.type = "button";
        go.addEventListener("click", () => { const v = ta.value.trim(); if (v) decide(p, { status: "approved", changes: v }, [go, cancel, ...bs]); else ta.focus(); });
        cancel.addEventListener("click", () => cb.remove());
        r2.append(go, cancel); cb.append(lab, r2); inner.insertBefore(cb, row); ta.focus();
      });
      row.append(yes, edit, no);
    } else {
      row.append(el("span", "pill " + p.status, PILL[p.status] || p.status));
    }
    inner.append(row); c.append(el("div", "band"), inner);
    return c;
  }

  function renderProposals() {
    if (!state.loaded) return;
    const box = $("proposals"); box.textContent = "";
    const order = (a, b) => String(b.day).localeCompare(String(a.day)) || (a.n || 0) - (b.n || 0);
    const pending = state.proposals.filter((p) => p.status === "pending").sort(order);
    const active = state.proposals.filter((p) => p.status === "approved" || p.status === "failed").sort(order);
    const recent = state.proposals.filter((p) => p.status === "done" || p.status === "declined").sort(order);
    $("nProps").textContent = pending.length;
    $("todayBadge").textContent = pending.length ? String(pending.length) : "";
    $("propHint").textContent = pending.length ? "Nothing happens until you approve." : "";
    [...pending, ...active].forEach((p) => box.append(proposalCard(p)));
    if (!pending.length && !active.length) box.append(el("p", "empty", "Nothing waiting. New proposals arrive with the brief or after " + state.agent + " answers a message."));
    if (recent.length) {
      const d = el("details", "older group"); d.append(el("summary", null, `Recently handled (${recent.length})`));
      recent.forEach((p) => d.append(proposalCard(p))); box.append(d);
    }
  }

  async function decide(p, fields, buttons) {
    buttons.forEach((b) => (b.disabled = true));
    try { await send("/api/proposals/" + encodeURIComponent(p.id), "PATCH", fields); }
    catch (e) { flash("That didn't save: " + e.message); buttons.forEach((b) => (b.disabled = false)); }
    refresh();
  }

  // conversation
  function renderThread() {
    const box = $("thread"); box.textContent = "";
    const all = [...state.messages.map((m) => ({ ...m, kind: "db" })), ...state.local]
      .sort((a, b) => String(a.at).localeCompare(String(b.at))).slice(-40);
    if (!all.length) { box.append(el("p", "empty", "No messages yet.")); return; }
    for (const m of all) {
      const mine = m.from === "owner";
      const b = el("div", "msg " + (mine ? "me" : "agent") + (mine && m.kind === "db" && m.status === "new" ? " queued" : ""));
      b.append(el("span", "who", mine ? (m.kind === "db" ? (m.status === "new" ? "You · waiting for " + state.agent : "You · sent") : "You · asked") : (m.kind === "db" ? state.agent : state.agent + " · quick answer")));
      b.append(document.createTextNode(m.text || ""));
      box.append(b);
    }
    if (!$("talk").hidden) box.lastElementChild?.scrollIntoView({ block: "nearest" });
  }

  async function ask() {
    const text = $("say").value.trim();
    if (!text) return;
    const history = state.local.slice(-8).filter((m) => m.text && m.text !== "Thinking…").map((m) => ({ from: m.from, text: m.text }));
    const turn = { from: "owner", text, at: new Date().toISOString() };
    const reply = { from: "assistant", text: "Thinking…", at: new Date(Date.now() + 1).toISOString() };
    state.local.push(turn, reply); renderThread();
    $("say").value = ""; busy(true);
    try {
      reply.text = (await send("/api/ask", "POST", { question: text, history })).answer;
    } catch (e) {
      reply.text = e.status === 409 || e.status === 502 ? "Quick answers aren't available right now (" + e.message + "). Use Send instead." : "That didn't go through. Try again.";
    } finally { busy(false); renderThread(); }
  }

  async function sendMessage() {
    const text = $("say").value.trim();
    if (!text) return;
    $("sendBtn").disabled = true;
    try {
      await send("/api/messages", "POST", { text });
      $("say").value = "";
      $("talkStatus").textContent = "Sent. " + state.agent + " answers here shortly.";
      refresh();
    } catch (e) { flash("That didn't send: " + e.message); }
    finally { $("sendBtn").disabled = !state.canWrite; }
  }

  function busy(on) { $("askBtn").disabled = on; $("stopBtn").hidden = true; $("talkStatus").textContent = on ? "Asking…" : ""; }
  $("askBtn").addEventListener("click", ask);
  $("sendBtn").addEventListener("click", sendMessage);

  // add a to-do
  $("addForm").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const f = ev.target;
    const title = f.title.value.trim();
    if (!title) return;
    $("addBtn").disabled = true;
    try {
      await send("/api/board", "POST", { title, direction: "i-owe", due: f.due.value || null, division: f.division.value,
                                         notes: f.notes.value.trim(), source: { kind: "manual" } });
      f.reset(); $("addStatus").textContent = "Added.";
      setTimeout(() => ($("addStatus").textContent = ""), 2500);
      refresh();
    } catch (e) { flash("That didn't save: " + e.message); }
    finally { $("addBtn").disabled = !state.canWrite; }
  });

  // load and keep fresh: poll while visible, and reload on return to the app
  let inflight = null;
  async function refresh() {
    if (inflight) return inflight;
    inflight = (async () => {
      try {
        const [settings, items, proposals, messages, latest] = await Promise.all([
          api("/api/settings"),
          api("/api/board?status=open,proposed,waiting,snoozed,done"),
          api("/api/proposals"),
          api("/api/messages?limit=60"),
          api("/api/brief/latest").catch((e) => { if (e.status === 404) return null; throw e; }),
        ]);
        state.tz = settings.timezone || state.tz;
        setAgent(settings.assistant?.name);
        Object.assign(state, { items, proposals, messages, brief: latest, loaded: true });
        $("offline").hidden = true;
        renderItems(); renderProposals(); renderBrief(); renderThread();
      } catch (e) {
        if (e.message !== "signed out") { $("offline").hidden = false; }
      } finally { inflight = null; }
    })();
    return inflight;
  }
  refresh();
  setInterval(() => { if (!document.hidden) refresh(); }, 30000);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) refresh(); });

  // Settings: connections, name, schedule, run now
  function conn(title, state, ok, action) {
    const row = el("div", "card conn");
    row.append(el("b", null, title), el("span", "state" + (ok === true ? " ok" : ok === false ? " bad" : ""), state));
    if (action) {
      const a = el(action.href ? "a" : "button", "btn small", action.label);
      if (action.href) a.href = action.href; else { a.type = "button"; a.addEventListener("click", action.onClick); }
      row.append(a);
    }
    return row;
  }
  const hourLabel = (h) => `${h % 12 || 12}:45 ${h < 12 ? "AM" : "PM"}`;
  for (const id of ["checkFirst", "checkLast"]) for (let h = 0; h < 24; h++) { const o = el("option", null, hourLabel(h)); o.value = h; $(id).append(o); }

  async function loadStatus() {
    let st;
    try { st = await api("/api/status"); } catch (e) { $("conns").textContent = "Couldn't load settings: " + e.message; return; }
    const box = $("conns"); box.textContent = "";
    const g = st.google;
    box.append(conn("Google (Gmail and Calendar)",
      !g.connected ? "Not connected" : !g.canWriteCalendar ? "Connected, read-only. Reconnect so approved calendar changes can be made." : "Connected",
      g.connected && g.canWriteCalendar ? true : false, { label: g.connected ? "Reconnect" : "Connect", href: "/oauth/google/start" }));
    const m = st.microsoft;
    box.append(conn("Microsoft 365", m.connected ? "Connected" + (m.account ? " as " + m.account : "") : "Not connected",
      m.connected ? true : null, { label: m.connected ? "Reconnect" : "Connect", href: "/oauth/microsoft/start" }));
    box.append(conn("Claude (AI)", st.anthropicKey ? `Ready · about $${(st.usage30d || 0).toFixed(2)} in the last 30 days` : "No API key set on the server", st.anthropicKey));
    box.append(conn("Brain", st.brain.configured ? (st.brain.lastSync ? "Synced " + new Date(st.brain.lastSync).toLocaleString() : "Set up; syncs with the first check") : "Not set up (optional)",
      st.brain.configured ? true : null, st.brain.configured ? { label: "Sync now", onClick: async (ev) => {
        ev.target.disabled = true;
        try { const r = await send("/api/brain/sync", "POST", {}); ev.target.textContent = `+${r.pulled} / ↑${r.pushed}`; } catch (e) { ev.target.textContent = "Failed"; }
      } } : null));
    box.append(conn("Texting", st.sms.configured ? `On (${st.sms.provider})` + (st.sms.briefByText ? " · brief by text" : "") : "Not set up (needs a phone number)", st.sms.configured ? true : null));
    const sch = st.scheduler;
    box.append(conn("Schedule", !sch.running ? "Not running on this server (set COS_SCHEDULER=1)" : sch.lastError ? "Last problem: " + sch.lastError : "Running", sch.running && !sch.lastError));
    $("moreBadge").textContent = (!g.connected || !g.canWriteCalendar || !st.anthropicKey || sch.lastError) ? "!" : "";
    $("agentInput").value = st.assistant.name || state.agent;
    $("briefTime").value = st.brief.time || "08:25";
    $("checkOn").value = st.check.enabled ? "1" : "0";
    $("checkFirst").value = st.check.firstHour; $("checkLast").value = st.check.lastHour;
    $("aboutLine").textContent = `Chief of Staff v${st.version}`;
    state.status = st;
  }

  $("nameForm").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const name = $("agentInput").value.trim();
    if (!name) return;
    try {
      await send("/api/settings/assistant", "PUT", { ...(state.status?.assistant || {}), name });
      setAgent(name); $("nameStatus").textContent = "Saved.";
    } catch (e) { $("nameStatus").textContent = "Didn't save: " + e.message; }
  });

  $("schedForm").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const first = +$("checkFirst").value, last = +$("checkLast").value;
    if (last < first) { $("schedStatus").textContent = "The window has to end after it starts."; return; }
    try {
      await send("/api/settings/brief", "PUT", { ...(state.status?.brief || {}), time: $("briefTime").value });
      await send("/api/settings/check", "PUT", { ...(state.status?.check || {}), enabled: $("checkOn").value === "1", firstHour: first, lastHour: last });
      $("schedStatus").textContent = "Saved."; loadStatus();
    } catch (e) { $("schedStatus").textContent = "Didn't save: " + e.message; }
  });

  $("checkNow").addEventListener("click", async () => {
    $("checkNow").disabled = true; $("checkStatus").textContent = "Running…";
    try {
      const r = await send("/api/check/run", "POST", {});
      const n = (k) => (Array.isArray(r[k]) ? r[k].length : r[k]) || 0;
      $("checkStatus").textContent = r.errors?.length ? "Problem: " + r.errors[0]
        : `Done: ${n("approvals")} approval(s), ${n("messages")} message(s), ${(r.capture?.added || []).length} new to-do(s).`;
      refresh();
    } catch (e) { $("checkStatus").textContent = "Couldn't run: " + e.message; }
    finally { $("checkNow").disabled = false; }
  });

  if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
})();
