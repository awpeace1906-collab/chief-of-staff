// Chief of Staff web app: talks only to this server's /api. No third-party scripts.
(() => {
  const DIV = { me: "Andrew", stephanie: "Stephanie", kids: "Home & kids" };
  const KIND = { calendar: "Calendar", email: "Email", board: "To-do list", list: "To-do list", other: "Proposal" };
  const SOURCE = { gmail: "Gmail", outlook: "Outlook", calendar: "calendar", manual: "you", readywhen: "readywhen", "microsoft-todo": "Microsoft To Do", digest: "a digest" };
  const state = { items: [], proposals: [], brief: null, messages: [], local: [], canWrite: true, agent: "Assistant",
                  records: { decision: [], trip: [], binder: [], expense: [], card: [] }, protect: [],
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
  const tabs = ["today", "sched", "todo", "talk", "more"];
  function show(name) {
    for (const t of tabs) { $("tab-" + t).setAttribute("aria-selected", String(t === name)); $(t).hidden = t !== name; }
    try { localStorage.setItem("cos.tab", name); } catch (e) {}
    window.scrollTo(0, 0);
    if (name === "talk") renderThread();
    if (name === "more") loadStatus();
    if (name === "sched") setTimeout(loadDay, 0);  // after the script has set up the day view
  }
  for (const t of tabs) $("tab-" + t).addEventListener("click", () => show(t));
  document.querySelectorAll(".stat").forEach((b) => b.addEventListener("click", () => {
    if (b.dataset.go === "today") $("propGroup").scrollIntoView({ behavior: "smooth", block: "start" }); else show(b.dataset.go);
  }));
  let startTab = "today";
  try { const h = location.hash.slice(1); startTab = tabs.includes(h) ? h : (localStorage.getItem("cos.tab") || "today"); state.filter = localStorage.getItem("cos.filter") || "all"; } catch (e) {}
  show(tabs.includes(startTab) ? startTab : "today");

  // division filter
  function paintChips() { document.querySelectorAll("#todo .chip").forEach((c) => c.setAttribute("aria-pressed", String(c.dataset.f === state.filter))); }
  document.querySelectorAll("#todo .chip").forEach((c) => c.addEventListener("click", () => {
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
    if (item.top === monday()) meta.append(el("span", "tag", "★ Top 3"));
    const src = [item.direction === "owed-to-me" && item.counterparty ? "waiting on " + item.counterparty : "", sourceLabel(item) ? "from " + sourceLabel(item) : ""].filter(Boolean).join(" · ");
    if (src) meta.append(el("span", "src", src));
    if (item.kind === "renewal" && item.expires) meta.append(el("span", "exp", "expires " + md(item.expires)));
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
    if (!isDone(item)) {
      const more = el("div", "row");
      const isTop = item.top === monday(), tops = state.items.filter((i) => i.top === monday() && !isDone(i)).length;
      const star = el("button", "btn small", isTop ? "★ Take out of top 3" : "☆ Top 3 this week"); star.type = "button";
      star.disabled = !state.canWrite || (!isTop && tops >= 3);
      star.addEventListener("click", () => patchItem(item, { top: isTop ? null : monday() }));
      const drop = el("button", "btn small quiet", "Drop it"); drop.type = "button"; drop.disabled = !state.canWrite;
      drop.addEventListener("click", () => patchItem(item, { status: "dropped" }));
      more.append(star, drop); box.append(more);
    }
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

    const waiting = open.filter((i) => i.direction === "owed-to-me" || i.status === "waiting");
    const mine = open.filter((i) => !waiting.includes(i));
    const groups = [
      ["Top 3 this week", mine.filter((i) => i.top === monday())],
      ["Overdue", mine.filter((i) => i.due && i.due < t)],
      ["Today", mine.filter((i) => i.due === t)],
      ["Tomorrow", mine.filter((i) => i.due === addDays(t, 1))],
      ["This week", mine.filter((i) => i.due && i.due > addDays(t, 1) && i.due <= week)],
      ["Later", mine.filter((i) => i.due && i.due > week)],
      ["No date", mine.filter((i) => !i.due)],
      ["Waiting on others", waiting],
    ].map(([name, list]) => [name, name === "Top 3 this week" ? list : list.filter((i) => i.top !== monday())]);
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
    renderExpenses();
  }

  const monday = () => { const t = today(); return addDays(t, -((new Date(t + "T12:00:00Z").getUTCDay() + 6) % 7)); };
  const money = (n) => "$" + (Math.round(+n * 100) / 100).toFixed(2);

  function renderExpenses() {
    const list = state.records.expense, box = $("expenses"); box.textContent = "";
    $("expenseBox").hidden = !list.length;
    const groups = {};
    list.forEach((x) => (groups[x.group || "Other"] = groups[x.group || "Other"] || []).push(x));
    for (const [name, xs] of Object.entries(groups)) {
      const g = el("div", "money"); g.append(el("b", null, name), el("span"));
      xs.sort((a, b) => String(a.date).localeCompare(String(b.date))).forEach((x) => g.append(el("span", null, (x.date ? md(x.date) + " · " : "") + (x.vendor || "")), el("span", null, money(x.amount || 0))));
      g.append(el("span", "tot", "Total"), el("span", "tot", money(xs.reduce((s, x) => s + (+x.amount || 0), 0))));
      box.append(g);
    }
  }

  // decisions: the owner's tap is the choice; the assistant sets up the next steps
  function renderDecisions() {
    const box = $("decisions"); box.textContent = "";
    const t = today();
    const open = state.records.decision.filter((d) => d.status === "open").sort((a, b) => String(a.deadline || "9999").localeCompare(String(b.deadline || "9999")));
    const recent = state.records.decision.filter((d) => d.status === "decided" && String(d.decidedAt || "").slice(0, 10) >= addDays(t, -2));
    $("decideGroup").hidden = !open.length && !recent.length;
    for (const d of open) {
      const c = el("div", "card pad decision group");
      const k = el("div", "kicker"); k.append(el("span", null, "Decide"));
      if (d.deadline) k.append(el("span", d.deadline <= addDays(t, 1) ? "num" : null, "· by " + dow(d.deadline) + " " + md(d.deadline)));
      c.append(k, el("p", "ptitle", d.title));
      if (d.context) c.append(el("p", "why", d.context));
      const opts = el("div", "opts");
      for (const o of d.options || []) {
        const b = el("button", "opt" + (d.recommendation === o.id ? " rec" : "")); b.type = "button"; b.disabled = !state.canWrite;
        b.append(el("b", null, o.label || o.id)); if (o.detail) b.append(el("small", null, o.detail));
        b.addEventListener("click", async () => {
          opts.querySelectorAll("button").forEach((x) => (x.disabled = true));
          try { await send("/api/decisions/" + encodeURIComponent(d.id) + "/choose", "POST", { choice: o.id }); }
          catch (e) { flash("That didn't save: " + e.message); }
          refresh();
        });
        opts.append(b);
      }
      c.append(opts); box.append(c);
    }
    for (const d of recent) {
      const c = el("div", "card pad decision group");
      c.append(el("p", "ptitle", d.title), el("p", "result", "You chose: " + (d.choiceLabel || d.choice) + ". " + (d.actions || state.agent + " is setting up the next steps.")));
      box.append(c);
    }
  }

  // tomorrow, this week, next trip
  function renderCards() {
    const box = $("cards"); box.textContent = "";
    const t = today(), hour = +new Intl.DateTimeFormat("en-US", { timeZone: state.tz, hour: "numeric", hourCycle: "h23" }).format(new Date());
    const card = (id) => state.records.card.find((c) => c.id === id);
    const mdCard = (title, sub, text) => {
      const c = el("div", "card brief"); c.append(el("h3", null, title)); if (sub) c.append(el("p", "note", sub));
      const body = el("div", "md"); renderMd(text, body); c.append(body); box.append(c);
    };
    const tm = card("tomorrow");
    if (tm && tm.markdown && (tm.day > t || (tm.day === t && hour < 12))) mdCard(tm.day === t ? "Today, first things" : "Tomorrow", dow(tm.day) + " " + md(tm.day), tm.markdown);
    const wk = card("week");
    if (wk && wk.markdown && wk.weekOf && wk.weekOf <= t && t < addDays(wk.weekOf, 7)) mdCard("This week", "Week of " + md(wk.weekOf), wk.markdown);
    const trip = state.records.trip.filter((x) => (x.end || x.start || "") >= t).sort((a, b) => String(a.start).localeCompare(String(b.start)))[0];
    if (trip) {
      const c = el("div", "card pad tripcard");
      const k = el("div", "kicker"); k.append(el("span", null, "Next trip"), el("span", null, "· " + md(trip.start) + (trip.end && trip.end !== trip.start ? "–" + md(trip.end) : "")));
      c.append(k, el("h3", null, trip.title || "Trip"));
      if (trip.note) c.append(el("p", "why", trip.note));
      const ul = el("ul", "legs");
      (trip.legs || []).forEach((l) => { const li = el("li"); li.append(el("b", null, l.when || ""), document.createTextNode(l.what + (l.detail ? " · " + l.detail : ""))); ul.append(li); });
      if (ul.childNodes.length) c.append(ul);
      box.append(c);
    }
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
    if (p.draft) { add("To", p.draft.to); add("Subject", p.draft.subject); }
    if (facts.childNodes.length) inner.append(facts);
    if (p.title && p.summary) inner.append(el("p", "why", p.summary));
    if (p.draft) inner.append(el("div", "draft", p.draftBody || p.draft.body));
    if (p.changes) inner.append(el("p", "result", "Your changes: " + p.changes));
    if (p.result) inner.append(el("p", "result", p.result));
    const row = el("div", "row");
    if (p.status === "pending") {
      const yes = el("button", "btn primary", p.draft ? "Send" : "Approve"); yes.type = "button";
      const edit = el("button", "btn", "Change…"); edit.type = "button";
      const no = el("button", "btn quiet", "Decline"); no.type = "button";
      const bs = [yes, edit, no]; bs.forEach((b) => (b.disabled = !state.canWrite));
      yes.addEventListener("click", () => decide(p, { status: "approved" }, bs));
      no.addEventListener("click", () => decide(p, { status: "declined" }, bs));
      edit.addEventListener("click", () => {
        if (inner.querySelector(".changebox")) return;
        const cb = el("div", "changebox");
        const lab = el("label", null, p.draft ? "Edit the email" : "What should be different?"); const ta = el("textarea");
        if (p.draft) { ta.value = p.draftBody || p.draft.body; ta.rows = 8; } else ta.placeholder = "Make it 7pm, and put it on the Family calendar";
        lab.append(ta);
        const r2 = el("div", "row");
        const go = el("button", "btn primary", p.draft ? "Send this version" : "Approve with changes"); go.type = "button";
        const cancel = el("button", "btn quiet", "Cancel"); cancel.type = "button";
        go.addEventListener("click", () => {
          const v = ta.value.trim(); if (!v) { ta.focus(); return; }
          decide(p, p.draft ? { status: "approved", draftBody: v, changes: "Edited the email before sending" } : { status: "approved", changes: v }, [go, cancel, ...bs]);
        });
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


  // Day view: hours down the side, in the device's time zone (it follows the owner when they
  // travel). The server gives the day's events, free windows and blocks on their way; the
  // suggestions come from the to-do list here, so ticking one off updates them at once.
  const DEV_TZ = (() => { try { return Intl.DateTimeFormat().resolvedOptions().timeZone; } catch (e) { return null; } })() || "UTC";
  const HOUR_PX = 56;
  const sched = { day: null, data: null, error: "", show: new Set(["me", "kids"]), open: null };
  try { const v = JSON.parse(localStorage.getItem("cos.schedShow") || "null"); if (Array.isArray(v)) sched.show = new Set(v); } catch (e) {}
  function tzOffset(date, tz) {
    const p = Object.fromEntries(new Intl.DateTimeFormat("en-US", { timeZone: tz, hourCycle: "h23", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" }).formatToParts(date).map((x) => [x.type, x.value]));
    return Date.UTC(+p.year, p.month - 1, +p.day, +p.hour, +p.minute, +p.second) - date.getTime();
  }
  function local(date) { const d = new Date(date.getTime() + tzOffset(date, DEV_TZ)); return { day: d.toISOString().slice(0, 10), mins: d.getUTCHours() * 60 + d.getUTCMinutes() }; }
  function at(day, mins) { const [y, mo, d] = day.split("-").map(Number); const guess = Date.UTC(y, mo - 1, d, 0, mins); return new Date(guess - tzOffset(new Date(guess), DEV_TZ)); }
  const devToday = () => local(new Date()).day;
  const hm = (mins) => { const h = Math.floor(mins / 60) % 24, m = mins % 60; return (h % 12 || 12) + (m ? ":" + String(m).padStart(2, "0") : "") + (h < 12 ? "am" : "pm"); };
  const dur = (mins) => (mins >= 60 ? Math.floor(mins / 60) + "h" + (mins % 60 ? " " + (mins % 60) + "m" : "") : mins + "m");
  const tzShort = (tz, d) => new Intl.DateTimeFormat("en-US", { timeZone: tz, timeZoneName: "short" }).formatToParts(d).find((p) => p.type === "timeZoneName")?.value || tz;
  function span(startIso, endIso) {
    const s = local(new Date(startIso)), f = local(new Date(endIso || startIso));
    const sm = s.day < sched.day ? 0 : s.day > sched.day ? 1440 : s.mins;
    const fm = f.day > sched.day ? 1440 : f.day < sched.day ? 0 : f.mins;
    return { s: sm, e: fm };
  }

  async function loadDay() {
    if (!sched.day) sched.day = devToday();
    const want = sched.day;
    renderDay();
    $("schedStatus").textContent = "Loading the day…";
    try {
      const d = await api("/api/day?date=" + want + "&tz=" + encodeURIComponent(DEV_TZ));
      if (want !== sched.day) return;
      sched.data = d; sched.error = "";
    } catch (e) {
      if (want !== sched.day) return;
      sched.data = null;
      sched.error = e.status === 409 ? "Connect Google in Settings to see your calendars. Free time below assumes an empty day." : "Couldn't load the calendars (" + e.message + "). Free time below assumes an empty day.";
    }
    renderDay();
  }

  function urgency(i, t) {
    if (i.due && i.due < t) return [0, i.due];
    if ((i.nudges || 0) >= 3) return [1, i.due || "9999"];
    if (i.due === t) return [2, i.due];
    if (i.due && i.due <= addDays(t, 2)) return [3, i.due];
    if (i.promise) return [4, i.due || "9999"];
    if (i.due && i.due <= addDays(t, 7)) return [5, i.due];
    return [i.due ? 6 : 7, i.due || "9999"];
  }
  function ranked(planned) {
    const t = today();
    return state.items.filter((i) => !isDone(i) && i.status !== "snoozed" && i.division !== "stephanie" && i.direction !== "owed-to-me" && !planned.has(i.id))
      .map((i) => ({ i, u: urgency(i, t) })).sort((a, b) => a.u[0] - b.u[0] || a.u[1].localeCompare(b.u[1]) || String(a.i.title).localeCompare(String(b.i.title))).map((x) => x.i);
  }
  function why(i) {
    const t = today();
    if (i.due && i.due < t) return ["Overdue " + Math.round((new Date(t) - new Date(i.due)) / 864e5) + "d", true];
    if ((i.nudges || 0) >= 3) return ["Stuck · " + i.nudges + " briefs", true];
    if (i.due === t) return ["Due today", true];
    if (i.promise) return ["You promised" + (i.counterparty ? " " + i.counterparty : "") + (i.due ? " · " + dow(i.due) : ""), false];
    return [i.due ? "Due " + dow(i.due) + " " + md(i.due) : "No date", false];
  }
  function fallbackFree() {  // no calendar data: the whole working day, from now on
    if (sched.day < devToday()) return [];
    let lo = 420; if (sched.day === devToday()) lo = Math.max(lo, Math.ceil(local(new Date()).mins / 15) * 15);
    return lo < 1260 - 30 ? [{ s: lo, e: 1260 }] : [];
  }
  function without(free, busy) {  // cut blocks out of free windows, keeping pieces of 30+ minutes
    let out = free;
    for (const b of busy) out = out.flatMap((g) => b.e <= g.s || b.s >= g.e ? [g] : [{ s: g.s, e: b.s }, { s: b.e, e: g.e }]);
    return out.filter((g) => g.e - g.s >= 30);
  }
  function lanes(list) {
    list.sort((a, b) => a.s - b.s || b.e - a.e);
    let cluster = [], end = -1;
    const flush = () => { const cols = []; for (const ev of cluster) { let c = cols.findIndex((x) => x <= ev.s); if (c < 0) { c = cols.length; cols.push(0); } cols[c] = ev.e; ev.col = c; } cluster.forEach((ev) => (ev.cols = cols.length)); cluster = []; };
    for (const ev of list) { if (ev.s >= end && cluster.length) flush(); cluster.push(ev); end = Math.max(end, ev.e); }
    if (cluster.length) flush();
    return list;
  }

  function renderDay() {
    if (!sched.day) sched.day = devToday();
    const isToday = sched.day === devToday(), noon = at(sched.day, 720);
    $("dayName").textContent = "";
    $("dayName").append(document.createTextNode((isToday ? "Today · " : "") + dow(sched.day) + " " + md(sched.day)), el("small", null, "Times in " + tzShort(DEV_TZ, noon) + (DEV_TZ !== state.tz ? " (home is " + tzShort(state.tz, noon) + ")" : "")));
    document.querySelectorAll("#schedChips .chip").forEach((c) => c.setAttribute("aria-pressed", String(c.dataset.f === "me" || sched.show.has(c.dataset.f))));
    const d = sched.data && sched.data.date === sched.day ? sched.data : null;
    const shown = (d?.events || []).filter((e) => e.division === "me" || sched.show.has(e.division));
    const ad = $("allDay"); ad.textContent = "";
    shown.filter((e) => e.allDay).forEach((e) => { const s = el("span", null, e.title); s.dataset.div = e.division; ad.append(s); });
    const timed = shown.filter((e) => !e.allDay).map((e) => ({ ...span(e.start, e.end), title: e.title, where: e.location || "", div: e.division })).filter((e) => e.e > e.s);
    const planned = (d?.planned || state.proposals.filter((p) => p.start && (p.status === "approved" || p.status === "pending") && local(new Date(p.start)).day === sched.day)).map((p) => ({ ...span(p.start, p.end), title: String(p.title || "").replace(/^Add:\s*/, ""), div: p.division || "me", tent: true, itemId: p.itemId }));
    const wd = new Date(sched.day + "T12:00:00Z").getUTCDay();
    const toM = (s) => { const [h, m] = String(s).split(":").map(Number); return h * 60 + (m || 0); };
    const prot = d ? (d.protected || []).map((w) => ({ ...span(w.start, w.end), title: w.label, div: "me", prot: true }))
      : state.protect.filter((w) => !w.days || w.days.includes(wd)).map((w) => ({ s: toM(w.start), e: toM(w.end), title: w.label || "Protected", div: "me", prot: true }));
    const free = d ? d.free.map((g) => ({ ...span(g.start, g.end) })) : without(fallbackFree(), [...planned, ...prot]);
    renderBinder();
    const queue = ranked(new Set(planned.map((p) => p.itemId).filter(Boolean)));
    const n = queue.filter((i) => urgency(i, today())[0] <= 3).length;
    $("schedBadge").textContent = n ? String(n) : "";

    const all = [...timed, ...planned, ...prot.filter((e) => e.e > e.s)];
    let startH = 6, endH = 22;
    for (const e of all) { startH = Math.min(startH, Math.floor(e.s / 60)); endH = Math.max(endH, Math.ceil(e.e / 60)); }
    const y = (mins) => ((mins - startH * 60) / 60) * HOUR_PX;
    const tl = $("timeline"); tl.textContent = ""; tl.style.height = (endH - startH) * HOUR_PX + "px";
    for (let h = startH + 1; h <= endH; h++) { const l = el("span", "hr", h === 24 ? "" : hm(h * 60)); l.style.top = y(h * 60) + "px"; tl.append(l); }
    const body = el("div", "body"); tl.append(body);
    const split = timed.some((e) => e.div !== "me"), mainW = split ? 70 : 100;
    lanes(all.filter((e) => e.div === "me" || e.tent || e.prot)).forEach((e) => body.append(evtBox(e, y, 0, mainW)));
    lanes(timed.filter((e) => e.div !== "me")).forEach((e) => body.append(evtBox(e, y, mainW, 100 - mainW)));

    let qi = 0;
    for (const g of free) {
      const id = sched.day + ":" + g.s, px = y(g.e) - y(g.s);
      const box = el("div", "gap" + (sched.open === id ? " open" : ""));
      box.style.top = y(g.s) + 2 + "px"; box.style.height = Math.max(22, px - 4) + "px";
      box.style.left = "4px"; box.style.width = `calc(${mainW}% - 8px)`;
      const picks = queue.slice(qi, qi + Math.min(3, Math.max(1, Math.floor((g.e - g.s) / 30)))); qi += picks.length;
      const fits = Math.max(0, Math.floor((px - 26) / 50));
      const head = el("div", "gh"); head.append(el("span", null, "Free " + hm(g.s) + "–" + hm(g.e) + " · " + dur(g.e - g.s)));
      if (picks.length > fits || sched.open === id) {
        const more = el("button", null, sched.open === id ? "Close" : picks.length + (picks.length === 1 ? " idea" : " ideas"));
        more.type = "button"; more.addEventListener("click", () => { sched.open = sched.open === id ? null : id; renderDay(); });
        head.append(more);
      }
      box.append(head);
      picks.slice(0, sched.open === id ? picks.length : Math.min(picks.length, fits)).forEach((i) => box.append(sugRow(i, g)));
      if (!picks.length && px >= 40) box.append(el("span", "m", "Nothing waiting"));
      body.append(box);
    }
    if (isToday) { const nowM = local(new Date()).mins; if (nowM >= startH * 60 && nowM <= endH * 60) { const ln = el("div", "nowline"); ln.style.top = y(nowM) + "px"; body.append(ln); } }
    $("schedStatus").textContent = sched.error || (free.length ? "" : sched.day < devToday() ? "This day has passed." : "No free time left.");
  }

  function evtBox(e, y, leftPct, widthPct) {
    const b = el("div", "evt" + (e.tent ? " tent" : "") + (e.prot ? " prot" : "")); b.dataset.div = e.div;
    const w = widthPct / (e.cols || 1);
    b.style.top = y(e.s) + 1 + "px"; b.style.height = Math.max(20, y(e.e) - y(e.s) - 2) + "px";
    b.style.left = `calc(${leftPct + (e.col || 0) * w}% + 2px)`; b.style.width = `calc(${w}% - 4px)`;
    b.append(el("b", null, e.title));
    if (y(e.e) - y(e.s) >= 34) b.append(el("small", null, hm(e.s) + "–" + hm(e.e) + (e.where ? " · " + e.where : "") + (e.tent ? " · being added" : "")));
    return b;
  }

  function renderBinder() {
    const box = $("binder"); box.textContent = "";
    const b = state.records.binder.find((x) => x.start && x.start <= sched.day && sched.day <= (x.end || x.start));
    if (!b) return;
    const c = el("div", "card pad binder");
    const k = el("div", "kicker"); k.append(el("span", null, "Binder"), el("span", null, "· " + md(b.start) + (b.end ? "–" + md(b.end) : "")));
    c.append(k, el("h3", null, b.title || "Binder"));
    for (const sec of b.sections || []) {
      const det = el("details"); det.append(el("summary", null, sec.h || ""));
      const ul = el("ul"); (sec.lines || []).forEach((l) => ul.append(el("li", null, l))); det.append(ul); c.append(det);
    }
    box.append(c);
  }

  // plans changed: the assistant re-plans the day and proposes the moves
  document.querySelectorAll("#replanChips .btn").forEach((b) => b.addEventListener("click", () => { $("replanText").value = b.dataset.t; $("replanText").focus(); }));
  $("replanBtn").addEventListener("click", async () => {
    const what = $("replanText").value.trim();
    if (!what) { $("replanText").focus(); return; }
    $("replanBtn").disabled = true;
    const day = sched.day || devToday(), now = local(new Date());
    const at = day === now.day ? String(Math.floor(now.mins / 60)).padStart(2, "0") + ":" + String(now.mins % 60).padStart(2, "0") : "";
    try {
      await send("/api/replan", "POST", { day, at, timeZone: DEV_TZ, what });
      $("replanText").value = "";
      await refresh();  // re-renders the day, so the confirmation goes after it
      $("schedStatus").textContent = "Sent. " + state.agent + " is re-planning; any moves show under Needs your OK.";
    } catch (e) { $("schedStatus").textContent = "That didn't send: " + e.message; }
    finally { $("replanBtn").disabled = !state.canWrite; }
  });

  function sugRow(i, g) {
    const r = el("div", "sug"); r.dataset.div = i.division || "me";
    const c = el("button", "check", "✓"); c.type = "button"; c.setAttribute("aria-label", "Mark done: " + i.title); c.disabled = !state.canWrite;
    c.addEventListener("click", () => { c.disabled = true; patchItem(i, { status: "done" }).then(renderDay); });
    const mid = el("div"); const [txt, late] = why(i);
    mid.append(el("span", "t", i.title), el("span", "m" + (late ? " late" : ""), txt));
    const blk = el("button", "btn", "Block"); blk.type = "button"; blk.disabled = !state.canWrite;
    blk.addEventListener("click", async () => {
      blk.disabled = true;
      const start = at(sched.day, g.s), end = new Date(start.getTime() + Math.min(+(i.minutes || 30), g.e - g.s) * 60000);
      try {
        const p = await send("/api/schedule/block", "POST", { itemId: i.id, start: start.toISOString(), end: end.toISOString(), timeZone: DEV_TZ });
        await Promise.all([loadDay(), refresh()]);
        $("schedStatus").textContent = p.status === "done" ? p.result : "Saved. It goes on your calendar at the next check.";
      } catch (e) { blk.disabled = false; $("schedStatus").textContent = "That didn't save: " + e.message; }
    });
    r.append(c, mid, blk);
    return r;
  }

  $("dayPrev").addEventListener("click", () => { sched.day = addDays(sched.day || devToday(), -1); sched.open = null; loadDay(); });
  $("dayNext").addEventListener("click", () => { sched.day = addDays(sched.day || devToday(), 1); sched.open = null; loadDay(); });
  $("dayToday").addEventListener("click", () => { sched.day = devToday(); sched.open = null; loadDay(); });
  document.querySelectorAll("#schedChips .chip").forEach((c) => c.addEventListener("click", () => {
    if (c.dataset.f === "me") return;  // your own calendar always shows: it defines your free time
    sched.show.has(c.dataset.f) ? sched.show.delete(c.dataset.f) : sched.show.add(c.dataset.f);
    try { localStorage.setItem("cos.schedShow", JSON.stringify([...sched.show])); } catch (e) {}
    renderDay();
  }));
  setInterval(() => { if (!$("sched").hidden) renderDay(); }, 60000);  // the now-line moves

  // load and keep fresh: poll while visible, and reload on return to the app
  let inflight = null;
  async function refresh() {
    if (inflight) return inflight;
    inflight = (async () => {
      try {
        const [settings, items, proposals, messages, latest, records] = await Promise.all([
          api("/api/settings"),
          api("/api/board?status=open,proposed,waiting,snoozed,done"),
          api("/api/proposals"),
          api("/api/messages?limit=60"),
          api("/api/brief/latest").catch((e) => { if (e.status === 404) return null; throw e; }),
          api("/api/records").catch(() => null),
        ]);
        if (records) state.records = { ...state.records, ...records };
        state.protect = settings.schedule?.protect || [];
        state.tz = settings.timezone || state.tz;
        setAgent(settings.assistant?.name);
        Object.assign(state, { items, proposals, messages, brief: latest, loaded: true });
        $("offline").hidden = true;
        renderItems(); renderProposals(); renderBrief(); renderThread(); renderDecisions(); renderCards();
        if (!$("sched").hidden) renderDay();
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
    if (last < first) { $("schedFormStatus").textContent = "The window has to end after it starts."; return; }
    try {
      await send("/api/settings/brief", "PUT", { ...(state.status?.brief || {}), time: $("briefTime").value });
      await send("/api/settings/check", "PUT", { ...(state.status?.check || {}), enabled: $("checkOn").value === "1", firstHour: first, lastHour: last });
      $("schedFormStatus").textContent = "Saved."; loadStatus();
    } catch (e) { $("schedFormStatus").textContent = "Didn't save: " + e.message; }
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
