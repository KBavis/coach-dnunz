"use strict";
const $ = (s, root = document) => root.querySelector(s);
const el = (tag, attrs = {}, ...kids) => {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k === "class") n.className = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else n.setAttribute(k, v === true ? "" : v);
  }
  n.append(...kids.filter((k) => k != null));
  return n;
};
const fmt = (t) => {
  t = Math.max(0, Math.floor(t));
  const h = Math.floor(t / 3600), m = Math.floor((t % 3600) / 60), s = t % 60;
  const ss = String(s).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${ss}` : `${m}:${ss}`;
};
const ago = (ts) => {
  const d = new Date(ts * 1000), days = Math.floor((Date.now() - d) / 864e5);
  if (days < 1) return "today";
  if (days < 2) return "yesterday";
  if (days < 7) return `${days} days ago`;
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: d.getFullYear() === new Date().getFullYear() ? undefined : "numeric" });
};
const plural = (n, w) => `${n} ${w}${n === 1 ? "" : "s"}`;
const api = async (path, opts) => {
  const r = await fetch(path, opts);
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail || msg; } catch (_) {}
    throw new Error(msg);
  }
  return r.json();
};
const json = (method, body) => ({ method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
const YOUTUBE = /^https?:\/\/((www|m|music)\.)?(youtube\.com|youtu\.be)\//i;
const VIDEO_EXT = /\.(mp4|mkv|mov|webm)$/i;

let toastTimer;
function toast(msg, bad = false, action = null) {
  const t = $("#toast");
  t.replaceChildren(el("span", {}, msg), ...(action ? [el("button", { class: "primary", onclick: () => { t.hidden = true; action.fn(); } }, action.label)] : []));
  t.className = bad ? "bad" : ""; t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.hidden = true; }, action ? 9000 : 4500);
}

/* ---------- menus ---------- */
let menuAnchor = null;
function openMenu(anchor, items) {
  const m = $("#menu");
  if (!m.hidden && menuAnchor === anchor) return closeMenu();   // the same ⋯ again closes it
  menuAnchor = anchor;
  m.replaceChildren(...items.map((it) => el("button", {
    class: it.danger ? "danger" : "", onclick: (e) => { e.stopPropagation(); closeMenu(); it.fn(); },
  }, it.label)));
  m.hidden = false;
  const r = anchor.getBoundingClientRect();
  m.style.top = `${r.bottom + 4}px`;
  m.style.left = `${Math.max(8, Math.min(r.right - m.offsetWidth, innerWidth - m.offsetWidth - 8))}px`;
}
function closeMenu() { $("#menu").hidden = true; menuAnchor = null; }
// close on any press outside the menu (capture: other handlers may stop the click), and whenever
// the menu could end up detached from its button
document.addEventListener("pointerdown", (e) => {
  if (!$("#menu").hidden && !$("#menu").contains(e.target) && !menuAnchor?.contains(e.target)) closeMenu();
}, true);
document.addEventListener("scroll", () => closeMenu(), true);
window.addEventListener("resize", () => closeMenu());
window.addEventListener("hashchange", () => closeMenu());

/* ---------- state ---------- */
let vods = [];
const uploads = new Map();   // key -> {name, pct, error}
const finished = new Set();  // ids that became ready while this page was open
let config = { parallel: 2, downloads: 3 };
let view = "library";

const PHASE = {
  PRE_ROUND: { cls: "pre", name: "Buy phase" },
  ROUND: { cls: "live", name: "Live" },
  POST_PLANT: { cls: "post", name: "Post-plant" },
  ROUND_END: { cls: "end", name: "Round end" },
  NON_GAME: { cls: "dead", name: "Dead time" },
};

/* ---------- routing ---------- */
function route() {
  const legacy = location.hash.match(/^#vod=(\w+)/);
  if (legacy) { location.replace(`#/vod/${legacy[1]}`); return; }
  const m = location.hash.match(/^#\/vod\/(\w+)/);
  if (m) openVod(m[1]);
  else showLibrary();
}
window.addEventListener("hashchange", route);

function showLibrary() {
  view = "library";
  $("#viewer-view").hidden = true;
  $("#library-view").hidden = false;
  const v = $("#video");
  if (!v.paused) v.pause();
  document.title = "Coach dnunz";
  renderLibrary();
}

/* ---------- library ---------- */
let lastStatus = null;   // id -> status at the previous refresh
async function refresh() {
  let list;
  try { list = await api("/api/vods"); } catch (_) { return; }
  if (lastStatus) {
    for (const v of list) {
      const was = lastStatus.get(v.id);
      if (v.status === "ready" && (was === "processing" || was === "queued")) {
        finished.add(v.id);
        toast(`"${v.name}" is ready to view`, false, { label: "Open", fn: () => { location.hash = `#/vod/${v.id}`; } });
      }
    }
  }
  lastStatus = new Map(list.map((v) => [v.id, v.status]));
  vods = list;
  renderLibrary();
  // the breakdown being viewed changed on the server (round results added, re-run finished)
  const mine = current && list.find((v) => v.id === current.id);
  if (view === "viewer" && mine?.status === "ready" && mine.updated && mine.updated !== current.updated) reloadCurrent();
}

function renderLibrary() {
  renderActivity();
  if (view !== "library") return;
  renderJobs();
  renderGrid();
  const nothing = !vods.length && !uploads.size;
  $("#welcome").hidden = !nothing;
  $("#lib-wrap").hidden = nothing;
}

function renderActivity() {
  const busy = vods.filter((v) => v.status === "processing" || v.status === "queued").length + uploads.size;
  const a = $("#activity");
  a.hidden = !busy;
  a.textContent = `${busy} in progress`;
}
$("#activity").onclick = () => { location.hash = "#/"; };

const DOWNLOADING = /download|youtube|joining/i;   // processing stages that are still fetching the video
const toDownload = (v) => v.status === "queued" && /^waiting to download/i.test(v.stage || "");

let jobsKey = "";
function renderJobs() {
  const byAdded = (a, b) => a.created_at - b.created_at;
  const server = vods.filter((v) => ["processing", "queued"].includes(v.status)).sort(byAdded);
  const ups = [...uploads.entries()].map(([key, u]) => ({ key, upload: true, ...u }));
  const failed = vods.filter((v) => v.status === "failed");
  const done = vods.filter((v) => v.status === "ready" && finished.has(v.id)).sort(byAdded);
  // where each waiting VOD stands in the analysis line (oldest first, like the server)
  const waiting = server.filter((v) => v.status === "queued" && !toDownload(v));
  const active = [...server, ...ups];

  const key = JSON.stringify([active, failed, done].map((l) => l.map((j) => [j.key || j.id, j.name, j.status, j.stage, Math.round(j.pct), j.error])));
  if (key === jobsKey) return;
  jobsKey = key;
  const any = active.length + failed.length + done.length;
  $("#jobs-wrap").hidden = !any;
  $("#clear-done").hidden = !done.length;
  const running = server.filter((v) => v.status === "processing" && !DOWNLOADING.test(v.stage)).length;
  const dl = server.filter((v) => v.status === "processing" && DOWNLOADING.test(v.stage)).length;
  $("#jobs-title").textContent = active.length ? "Processing queue" : failed.length ? "Needs attention" : "Just finished";
  $("#jobs-note").textContent = active.length
    ? [running && `${running} processing`, dl && `${dl} downloading`, waiting.length && `${waiting.length} waiting`, ups.length && `${ups.length} uploading`]
      .filter(Boolean).join(" · ") + ` — processed in the order added, ${config.parallel} at a time; YouTube links join once downloaded`
    : "";

  let n = 0;
  const row = (j, num, cls, stage, right, pct, bar) => el("div", { class: `qrow ${cls}` },
    el("span", { class: "q-num" }, num),
    el("div", { class: "q-main" },
      el("div", { class: "q-name", title: j.name }, j.name),
      el("div", { class: "q-stage", title: stage }, stage),
      bar ? el("div", { class: "bar" + (pct == null ? " wait" : "") }, el("div", { style: `width:${pct || 0}%` })) : null),
    el("div", { class: "q-right" }, right),
    j.upload || !["processing", "queued"].includes(j.status) ? el("span") : el("button", {
      class: "icon q-cancel", title: "Cancel and remove", onclick: () => removeVod(j) }, "✕"));

  $("#jobs").replaceChildren(
    ...active.map((j) => {
      n++;
      if (j.upload) {
        return j.error ? row(j, "!", "failed", j.error, "", null, false)
          : row(j, `#${n}`, "running", "Uploading to the app", `${Math.round(j.pct)}%`, j.pct, true);
      }
      if (j.status === "processing") {
        const what = DOWNLOADING.test(j.stage) ? "downloading" : "running";
        return row(j, `#${n}`, what, j.stage || "Starting", `${Math.round(j.pct)}%`, j.pct, true);
      }
      if (toDownload(j)) return row(j, `#${n}`, "waiting", "Waiting for a download slot", el("span", { class: "tag" }, "Queued"), null, false);
      const ahead = waiting.indexOf(j);
      const got = /^downloaded/i.test(j.stage || "") ? "Downloaded · " : "";
      const where = ahead <= 0 ? `${got}Up next — starts when a slot frees up` : `${got}Waiting — ${plural(ahead, "VOD")} ahead`;
      return row(j, `#${n}`, "waiting", where, el("span", { class: "tag" }, ahead <= 0 ? "Up next" : "Queued"), null, false);
    }),
    ...failed.map((j) => row(j, "!", "failed", j.error || "Processing failed", el("span", { class: "q-actions" },
      el("button", { onclick: () => reprocess(j) }, "Retry"),
      el("button", { class: "danger", onclick: () => removeVod(j) }, "Remove")), null, false)),
    ...done.map((j) => row(j, "✓", "done", j.summary && !j.summary.games ? "Ready — but no Valorant games were found"
      : `Ready — ${j.summary ? `${plural(j.summary.games, "game")}, ${plural(j.summary.rounds, "round")}` : "breakdown finished"}`,
      el("button", { class: "primary", onclick: () => { location.hash = `#/vod/${j.id}`; } }, "Open"), null, false)));
}
$("#clear-done").onclick = () => { finished.clear(); jobsKey = ""; renderLibrary(); };

function sortVods(list) {
  const by = $("#sort").value;
  const cmp = {
    new: (a, b) => b.created_at - a.created_at,
    old: (a, b) => a.created_at - b.created_at,
    name: (a, b) => a.name.localeCompare(b.name, undefined, { numeric: true }),
    long: (a, b) => b.duration - a.duration,
  }[by];
  return [...list].sort(cmp);
}

function highlight(text, q) {
  if (!q) return text;
  const i = text.toLowerCase().indexOf(q);
  if (i < 0) return text;
  const span = el("span");
  span.append(text.slice(0, i), el("mark", {}, text.slice(i, i + q.length)), text.slice(i + q.length));
  return span;
}

let gridKey = "";
function renderGrid() {
  const q = $("#search").value.trim().toLowerCase();
  const ready = vods.filter((v) => v.status === "ready");
  const shown = sortVods(ready.filter((v) => !q || v.name.toLowerCase().includes(q)));
  $("#lib-count").textContent = ready.length ? (q ? `${shown.length} of ${ready.length}` : `${ready.length}`) : "";
  $("#no-match").hidden = !(q && ready.length && !shown.length);
  const key = JSON.stringify([q, $("#sort").value, shown.map((v) => [v.id, v.name, v.duration, v.summary])]);
  if (key === gridKey) return;
  gridKey = key;
  $("#grid").replaceChildren(...shown.map((v) => card(v, q)));
  if (menuAnchor && !document.contains(menuAnchor)) closeMenu();
}

function card(v, q) {
  const s = v.summary;
  const meta = s && !s.games ? el("span", { class: "warn" }, `No Valorant games found · ${ago(v.created_at)}`)
    : s ? [plural(s.games, "game"), plural(s.rounds, "round"), ago(v.created_at)].join(" · ") : ago(v.created_at);
  const img = el("img", { src: `/api/vods/${v.id}/thumb.jpg`, alt: "", loading: "lazy" });
  img.onerror = () => img.remove();
  const title = el("div", { class: "title", title: v.name }, highlight(v.name, q));
  const c = el("div", { class: "card", tabindex: "0", onclick: () => { location.hash = `#/vod/${v.id}`; },
    onkeydown: (e) => { if (e.key === "Enter" && e.target === e.currentTarget) location.hash = `#/vod/${v.id}`; } },
    el("div", { class: "thumb" }, "◆", img, el("span", { class: "dur" }, fmt(v.duration))),
    el("div", { class: "body" }, title, el("div", { class: "meta" }, meta)),
    el("button", { class: "icon more", title: "More", onclick: (e) => {
      e.stopPropagation();
      openMenu(e.currentTarget, [
        { label: "Rename", fn: () => startRename(v, title) },
        { label: "Re-run detection", fn: () => reprocess(v, true) },
        { label: "Delete", danger: true, fn: () => removeVod(v) },
      ]);
    } }, "⋯"));
  return c;
}

$("#search").addEventListener("input", () => {
  if (view !== "library") location.hash = "#/";
  renderGrid();
});
$("#sort").addEventListener("change", renderGrid);

function startRename(v, target) {
  const input = el("input", { class: "rename", value: v.name });
  target.replaceWith(input);
  input.focus(); input.select();
  let done = false;
  const finish = async (save) => {
    if (done) return; done = true;
    const name = input.value.trim();
    if (save && name && name !== v.name) {
      try { await api(`/api/vods/${v.id}`, json("PATCH", { name })); v.name = name; }
      catch (e) { toast(e.message, true); }
    }
    input.replaceWith(target);
    target.textContent = v.name;
    if (current?.id === v.id) { current.name = v.name; document.title = `${v.name} · Coach dnunz`; }
    gridKey = ""; refresh();
  };
  input.addEventListener("keydown", (e) => {
    e.stopPropagation();                       // Enter must not also reach the card and open the VOD
    if (e.key === "Enter") { e.preventDefault(); finish(true); }
    if (e.key === "Escape") finish(false);
  });
  input.addEventListener("blur", () => finish(true));
  for (const ev of ["click", "pointerdown", "dblclick"]) input.addEventListener(ev, (e) => e.stopPropagation());
}

async function reprocess(v, confirmFirst = false) {
  if (confirmFirst && !confirm(`Re-run detection on "${v.name}"? The current breakdown is replaced when it finishes.`)) return;
  try { await api(`/api/vods/${v.id}/reprocess`, { method: "POST" }); } catch (e) { return toast(e.message, true); }
  if (view === "viewer") location.hash = "#/";
  refresh();
}

async function removeVod(v) {
  const busy = v.status === "processing" || v.status === "queued";
  const msg = busy ? `Cancel "${v.name}" and remove it?\n\n${v.status === "processing" ? "Its download or processing is stopped." : "It has not started yet."}`
    : `Delete "${v.name}" from the library?\n\nIts breakdown and its copy of the video are removed. A file you imported by path is not deleted.`;
  if (!confirm(msg)) return;
  try { await api(`/api/vods/${v.id}`, { method: "DELETE" }); } catch (e) { return toast(e.message, true); }
  if (current?.id === v.id) { current = null; location.hash = "#/"; }
  finished.delete(v.id);
  toast(busy ? `Cancelled "${v.name}"` : `Deleted "${v.name}"`);
  refresh();
}

/* ---------- adding VODs ---------- */
let picked = [];
let links = [""];
const dlg = $("#add-dialog");
function openAdd(files = []) {
  picked = [...files];
  links = [""];
  renderAdd();
  if (!dlg.open) dlg.showModal();
  if (!files.length) $("#link-rows input")?.focus();
}
$("#add-btn").onclick = () => openAdd();
$("#welcome-add").onclick = () => openAdd();

function linkState(i) {
  const v = links[i].trim();
  if (!v) return { kind: "empty" };
  if (!YOUTUBE.test(v)) return { kind: "bad", msg: "Not a YouTube link" };
  if (links.slice(0, i).some((x) => x.trim() === v)) return { kind: "bad", msg: "Already in the list" };
  return { kind: "ok" };
}
const goodLinks = () => links.filter((_, i) => linkState(i).kind === "ok").map((l) => l.trim());
const badLinks = () => links.filter((_, i) => linkState(i).kind === "bad").length;

function renderAdd(focus = -1) {
  $("#picked").replaceChildren(...picked.map((f, i) => el("li", {},
    el("span", { class: "n", title: f.name }, f.name),
    el("span", { class: "muted small" }, `${(f.size / 1e9).toFixed(f.size > 1e9 ? 1 : 2)} GB`),
    el("button", { type: "button", class: "icon", title: "Remove", onclick: () => { picked.splice(i, 1); renderAdd(); } }, "✕"))));
  $("#link-rows").replaceChildren(...links.map((_, i) => linkRow(i)));
  if (focus >= 0) { const inp = $("#link-rows").children[focus]?.querySelector("input"); inp?.focus(); }
  updateAddSummary();
}

function linkRow(i) {
  const st = linkState(i);
  const input = el("input", { type: "url", value: links[i], placeholder: "https://www.youtube.com/watch?v=…", autocomplete: "off", "aria-label": `YouTube link ${i + 1}` });
  const mark = el("span", { class: `l-mark ${st.kind}`, title: st.msg || "" }, st.kind === "ok" ? "✓" : st.kind === "bad" ? "!" : "");
  const msg = el("small", { class: "l-msg" }, st.msg || "");
  const wrap = el("div", { class: `lrow ${st.kind}` }, el("div", { class: "l-in" }, input, mark,
    el("button", { type: "button", class: "icon", title: "Remove this link", onclick: () => {
      links.splice(i, 1);
      if (!links.length) links = [""];
      renderAdd(Math.min(i, links.length - 1));
    } }, "✕")), msg);
  input.addEventListener("input", () => {
    links[i] = input.value;
    const s2 = linkState(i);
    wrap.className = `lrow ${s2.kind}`;
    mark.className = `l-mark ${s2.kind}`; mark.textContent = s2.kind === "ok" ? "✓" : s2.kind === "bad" ? "!" : "";
    msg.textContent = s2.msg || "";
    updateAddSummary();
  });
  input.addEventListener("paste", (e) => {
    // pasting several links at once fills one row each
    const parts = (e.clipboardData?.getData("text") || "").split(/\s+/).filter(Boolean);
    if (parts.length < 2) return;
    e.preventDefault();
    const keep = links[i].trim() ? [links[i]] : [];
    links.splice(i, 1, ...keep, ...parts);
    renderAdd(i + keep.length + parts.length - 1);
  });
  input.addEventListener("keydown", (e) => {
    if (e.key !== "Enter") return;
    e.preventDefault();
    if (i === links.length - 1) links.push("");
    renderAdd(i + 1);
  });
  return wrap;
}
$("#add-link").onclick = () => {
  const empty = links.findIndex((l) => !l.trim());
  if (empty >= 0) return renderAdd(empty);
  links.push("");
  renderAdd(links.length - 1);
};

function updateAddSummary() {
  const nf = picked.length, nl = goodLinks().length, n = nf + nl, bad = badLinks();
  const parts = [nf && plural(nf, "file"), nl && plural(nl, "link")].filter(Boolean);
  $("#add-summary").textContent = bad ? "Fix or remove the links marked in red"
    : n ? `${parts.join(" and ")} — processed in this order, ${config.parallel} at a time` : "Nothing added yet";
  const go = $("#add-go");
  go.disabled = !n || bad > 0;
  go.textContent = n ? `Add ${n} to the queue` : "Add to the queue";
}

$("#file").addEventListener("change", (e) => { addPicked(e.target.files); e.target.value = ""; });
function addPicked(files) {
  const ok = [...files].filter((f) => VIDEO_EXT.test(f.name));
  if (ok.length < files.length) toast("Only .mp4, .mkv, .mov and .webm files can be added", true);
  picked.push(...ok);
  renderAdd();
}
const drop = $("#drop");
["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); e.stopPropagation(); drop.classList.add("over"); }));
["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
drop.addEventListener("drop", (e) => { e.stopPropagation(); addPicked(e.dataTransfer.files); });

$("#add-form").addEventListener("submit", (e) => {
  if (e.submitter?.value !== "default") return;
  const files = picked, urls = goodLinks();
  picked = []; links = [""];
  location.hash = "#/";
  const n = files.length + urls.length;
  toast(`Added ${plural(n, "VOD")} to the queue. ${n > 1 ? "They process in the order added and each" : "It"} opens from your library when ready.`);
  ingest(files, urls);
});

async function ingest(files, urls) {
  for (const url of urls) {
    try { await api("/api/vods/from-url", json("POST", { url })); }
    catch (err) { toast(`${url}: ${err.message}`, true); }
  }
  if (urls.length) refresh();
  // uploads to the local server run two at a time; each starts processing as soon as it lands
  const queue = [...files];
  const next = async () => { while (queue.length) await upload(queue.shift()); };
  await Promise.all([next(), next()]);
  refresh();
}

function upload(file) {
  const key = `${file.name}:${file.size}:${Math.random()}`;
  uploads.set(key, { name: file.name, pct: 0 });
  renderLibrary();
  return new Promise((resolve) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/vods");
    xhr.upload.onprogress = (e) => {
      if (!e.lengthComputable) return;
      uploads.get(key).pct = (e.loaded / e.total) * 100;
      renderLibrary();
    };
    const fail = (msg) => {
      uploads.get(key).error = `Upload failed: ${msg}`;
      renderLibrary();
      setTimeout(() => { uploads.delete(key); renderLibrary(); }, 8000);
      resolve();
    };
    xhr.onload = async () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        await refresh();                 // show the server's queued entry before dropping ours
        uploads.delete(key); renderLibrary(); resolve();
      } else {
        let m = xhr.statusText; try { m = JSON.parse(xhr.responseText).detail; } catch (_) {}
        fail(m);
      }
    };
    xhr.onerror = () => fail("the app stopped responding");
    const fd = new FormData(); fd.append("file", file);
    xhr.send(fd);
  });
}

// dropping files anywhere adds them straight away (or into the dialog when it is open)
let dragDepth = 0;
const hasFiles = (e) => [...(e.dataTransfer?.types || [])].includes("Files");
window.addEventListener("dragenter", (e) => { if (!hasFiles(e)) return; e.preventDefault(); dragDepth++; if (!dlg.open) $("#drop-overlay").hidden = false; });
window.addEventListener("dragleave", (e) => { if (!hasFiles(e)) return; if (--dragDepth <= 0) { dragDepth = 0; $("#drop-overlay").hidden = true; } });
window.addEventListener("dragover", (e) => e.preventDefault());
window.addEventListener("drop", (e) => {
  e.preventDefault();
  dragDepth = 0; $("#drop-overlay").hidden = true;
  if (!e.dataTransfer.files.length) return;
  if (dlg.open) return addPicked(e.dataTransfer.files);
  const ok = [...e.dataTransfer.files].filter((f) => VIDEO_EXT.test(f.name));
  if (!ok.length) return toast("Only .mp4, .mkv, .mov and .webm files can be added", true);
  location.hash = "#/";
  ingest(ok, []);
});

/* ---------- viewer ---------- */
// The viewer is built around rounds: pick a game and a round on the right, then jump between its
// phases under the video. One accent colour marks where you are; everything else stays neutral.
let current = null;      // detail of the VOD being viewed
let segs = [], pauses = [], rounds = [], games = [], duration = 0;
let shownGame = null;

const PHASES = [            // [slot, label, label when the round has none]
  ["pre", "Buy phase", "No buy phase"],
  ["live", "Live", "No live phase"],
  ["post", "Planted", "No plant"],
  ["end", "Round end", "Round end"],
];
const ROUND_CLOCK = 100, SPIKE_CLOCK = 45;    // Valorant's round timer and spike timer, in seconds
const dur = (sec) => {                         // a length, written so it never looks like a timestamp
  sec = Math.max(0, Math.round(sec));
  return sec < 60 ? `${sec}s` : `${Math.floor(sec / 60)}m ${String(sec % 60).padStart(2, "0")}s`;
};
const SPIKE_SVG = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 1.6 13.6 4.8v6.4L8 14.4 2.4 11.2V4.8z" fill="none" stroke="currentColor" stroke-width="1.7"/><circle cx="8" cy="8" r="2.1" fill="currentColor"/></svg>';
const spikeIcon = () => { const i = el("span", { class: "spike-ico" }); i.innerHTML = SPIKE_SVG; return i; };
const known = (sc) => sc && sc[0] != null && sc[1] != null;
// which HUD side is the team being watched: detected per game from the WON / LOST banners
const sideOf = (game) => games.find((g) => g.game === game)?.our_side || null;
const oursFirst = (sc, game) => (sideOf(game) === "r" ? [sc[1], sc[0]] : sc);
function resultOf(r) {
  const side = sideOf(r.game);
  if (r.winner && side) return r.winner === side ? "w" : "l";     // the score change, when it was read
  return r.banner === "win" ? "w" : r.banner === "loss" ? "l" : null;   // else that round's banner
}

async function openVod(id) {
  let d;
  try { d = await api(`/api/vods/${id}`); } catch (_) { toast("That VOD is no longer in the library", true); location.hash = "#/"; return; }
  if (d.status !== "ready" || !d.result) {
    toast(d.status === "failed" ? "Processing failed for this VOD. Retry it from the library." : "Still processing. It opens once it is ready.");
    location.hash = "#/";
    return;
  }
  view = "viewer";
  $("#library-view").hidden = true;
  $("#viewer-view").hidden = false;
  closeMenu();
  if (current?.id === d.id) return;
  current = d;
  document.title = `${d.name} · Coach dnunz`;
  shownGame = null; playingGame = null;
  useBreakdown(d);
  const v = $("#video");
  v.src = `/api/vods/${d.id}/video`;
  v.playbackRate = speed;
  update();
}

function useBreakdown(d) {
  const res = d.result;
  segs = [...res.segments].sort((a, b) => a.start - b.start);
  pauses = res.pauses || [];
  games = res.games;
  duration = res.duration || d.duration;
  rounds = buildRounds(res);
  activeKey = undefined; activeRound = null;
  $("#v-name").textContent = d.name;
  $("#v-meta").textContent = [fmt(duration), plural(games.length, "game"), plural(rounds.length, "round")].join(" · ");
  showGame(games.some((g) => g.game === shownGame) ? shownGame : games[0]?.game ?? null);
}

let reloading = false;
async function reloadCurrent() {
  if (reloading) return;
  reloading = true;
  try {
    const d = await api(`/api/vods/${current.id}`);
    if (d.result && current?.id === d.id) { current = d; useBreakdown(d); update(); }
  } catch (_) {}
  reloading = false;
}

function buildRounds(result) {
  const map = new Map();
  for (const s of result.segments) {
    if (s.game == null) continue;
    const key = `${s.game}:${s.round}`;
    if (!map.has(key)) map.set(key, { game: s.game, round: s.round, key });
    map.get(key)[{ PRE_ROUND: "pre", ROUND: "live", POST_PLANT: "post", ROUND_END: "end" }[s.phase]] = s;
  }
  const list = [...map.values()].map((r) => {
    const first = r.pre || r.live || r.post || r.end;
    r.start = first.start;
    r.liveStart = (r.live || r.post || r.end).start;          // the round "starts" when it goes live
    r.finish = (r.end || r.post || r.live || r.pre).end;
    r.playTime = Math.max(0, (r.post || r.live || r.end).end - r.liveStart);   // live + post-plant
    // score going into the round, read once it is live: at the buy phase the previous result may
    // not have settled on the HUD yet
    r.score = (r.live || r.post || first).score;
    r.timeouts = pauses.filter((p) => p.start < r.finish && p.end > r.start);
    r.banner = (r.end || first).result ?? first.result ?? null;
    return r;
  }).sort((a, b) => a.start - b.start);
  // who took the round: the side whose score is one higher when the next round starts
  list.forEach((r, i) => {
    const next = list[i + 1];
    // the next round's score, or for a game's last round the score shown at its round end
    const after = next && next.game === r.game ? next.score : r.end?.score;
    if (known(r.score) && known(after)) {
      const dl = after[0] - r.score[0], dr = after[1] - r.score[1];
      if (dl + dr === 1 && dl >= 0 && dr >= 0) { r.after = after; r.winner = dl ? "l" : "r"; }
    }
  });
  return list;
}

const scoreText = (sc, game) => (known(sc) ? oursFirst(sc, game).join("–") : "");   // ours first when known

/* rounds panel */
function showGame(g) {
  shownGame = g;
  $("#game-tabs").replaceChildren(...games.map((x) => el("button", {
    class: x.game === g ? "on" : "", role: "tab", title: `Jump to game ${x.game}, round 1`,
    onclick: () => {
      const first = rounds.find((r) => r.game === x.game);
      if (x.game !== activeRound?.game && first) seek(first.start);   // another game: start at its round 1
      showGame(x.game);
    },
  }, games.length > 1 ? `Game ${x.game}` : "Rounds", el("span", { class: "final" }, `${x.rounds}`),
  activeRound?.game === x.game && x.game !== g ? el("span", { class: "live-dot", title: "Playing" }) : null)));
  const list = rounds.filter((r) => r.game === g);
  $("#rounds").replaceChildren(...(games.length ? list.map(roundRow) : [el("p", { class: "empty-rounds muted" },
    "No Valorant rounds were found in this video. It may not be a match recording, or its HUD layout is one the detector does not know yet.")]));
  markActive(true);
}

function roundRow(r) {
  const res = resultOf(r);
  const order = sideOf(r.game) ? "your team first" : "left team first";
  const sc = r.after
    ? el("span", { class: "sc", title: `Score after the round, ${order}` }, scoreText(r.after, r.game))
    : el("span", { class: "sc faint", title: `Score going into the round, ${order}` }, scoreText(r.score, r.game));
  const marks = el("span", { class: "marks" },
    r.post ? el("span", { class: "planted", title: "Spike planted" }, spikeIcon(), "Planted") : null,
    r.timeouts.length ? el("span", { class: "to-mark", title: "Timeout during this round" }, "Timeout") : null);
  return el("div", { class: "rrow" + (res ? ` ${res}` : ""), "data-key": r.key, title: `Jump to round ${r.round}`, onclick: () => seek(r.start) },
    el("span", { class: "no" }, `R${r.round}`),
    el("span", { class: "res" + (res ? ` ${res}` : ""), title: res === "w" ? "Won" : res === "l" ? "Lost" : "" }, res ? res.toUpperCase() : ""),
    sc, marks,
    el("span", { class: "len", title: "How long the round was live, including the post-plant" }, dur(r.playTime)));
}

function markActive(scroll) {
  document.querySelectorAll(".rrow.now").forEach((n) => n.classList.remove("now"));
  if (!activeRound) return;
  const node = document.querySelector(`.rrow[data-key="${activeRound.key}"]`);
  if (!node) return;
  node.classList.add("now");
  if (scroll) {
    const panel = $("#rounds");
    const top = node.offsetTop - panel.offsetTop;
    if (top < panel.scrollTop + 10 || top > panel.scrollTop + panel.clientHeight - 60) panel.scrollTo({ top: top - panel.clientHeight * 0.3, behavior: "smooth" });
  }
}

/* round bar under the video */
let phaseEls = [];
function renderRoundBar(r, s) {
  const box = $("#phases");
  phaseEls = [];
  const res = r ? resultOf(r) : null;
  $("#rb-result").className = "res" + (res ? ` ${res}` : "");
  $("#rb-result").textContent = res === "w" ? "Won" : res === "l" ? "Lost" : "";
  renderClock(r);
  if (!r) {
    const next = rounds.find((x) => x.start > ($("#video").currentTime || 0));
    $("#rb-game").textContent = "";
    $("#rb-round").textContent = s ? "Between rounds" : "–";
    $("#rb-score").textContent = "";
    box.replaceChildren(el("div", { class: "between" },
      next ? el("span", {}, `Up next: ${games.length > 1 ? `Game ${next.game}, ` : ""}Round ${next.round}`) : el("span", {}, "No more rounds after this point"),
      next ? el("button", { onclick: () => seek(next.start) }, "Jump there") : null));
    return;
  }
  $("#rb-game").textContent = games.length > 1 ? `Game ${r.game}` : "";
  $("#rb-round").textContent = `Round ${r.round}`;
  $("#rb-score").textContent = scoreText(r.score, r.game);
  $("#rb-score").title = `Score going into the round, ${sideOf(r.game) ? "your team" : "left team"} first`;
  const items = PHASES.map(([slot, name, none], i) => {
    const seg = r[slot];
    const b = el("button", {
      class: "phase" + (seg ? "" : " missing") + (slot === "post" && seg ? " plant" : ""), disabled: !seg,
      title: seg ? `Jump to ${name.toLowerCase()} (key ${i + 1})` : none,
      onclick: () => seg && seek(seg.start),
    }, el("span", { class: "n" }, slot === "post" && seg ? spikeIcon() : null, seg ? name : none),
    el("span", { class: "d" }, seg ? dur(seg.end - seg.start) : ""),
    el("kbd", {}, String(i + 1)), el("i", { class: "fill" }));
    if (seg) phaseEls.push({ seg, el: b, fill: b.lastChild });
    return b;
  });
  for (const p of r.timeouts) {
    items.push(el("button", { class: "phase timeout", title: `Timer frozen at ${p.timer}. Jump to the timeout.`, onclick: () => seek(p.start) },
      el("span", { class: "n" }, "Timeout"), el("span", { class: "d" }, dur(p.end - p.start))));
  }
  box.replaceChildren(...items);
}

/* round clock: the live round on the game's own timer, click anywhere to jump there */
let clockRound = null;
function clockSpan(r) { return [r.liveStart, Math.max(r.finish, r.liveStart + 1)]; }
function renderClock(r) {
  clockRound = r && (r.live || r.post) ? r : null;
  $("#clock").hidden = !clockRound;
  if (!clockRound) return;
  const [a, b] = clockSpan(r);
  const pct = (t) => `${((t - a) / (b - a)) * 100}%`;
  const bar = $("#clock-bar");
  bar.querySelectorAll(".zone").forEach((z) => z.remove());
  const liveEnd = (r.post || r.end || { start: b }).start;
  if (r.post) bar.prepend(el("i", { class: "zone post", style: `left:${pct(r.post.start)};width:${((r.post.end - r.post.start) / (b - a)) * 100}%` }));
  if (r.end) bar.prepend(el("i", { class: "zone end", style: `left:${pct(r.end.start)};right:0` }));
  const ticks = [];
  for (let k = 0; k * 20 <= ROUND_CLOCK; k++) {
    const t = a + k * 20;
    if (t > liveEnd - 6) break;
    ticks.push(el("button", { class: "tick", style: `left:${pct(t)}`, title: `Jump to ${fmt(ROUND_CLOCK - k * 20)} on the round clock`, onclick: () => seek(t) }, fmt(ROUND_CLOCK - k * 20)));
  }
  if (r.post) ticks.push(el("button", { class: "tick spike", style: `left:${pct(r.post.start)}`, title: "Jump to the plant", onclick: () => seek(r.post.start) }, spikeIcon(), "Plant"));
  $("#clock-ticks").replaceChildren(...ticks);
}
const clockTime = (e) => {
  const [a, b] = clockSpan(clockRound), box = $("#clock-bar").getBoundingClientRect();
  return a + Math.min(Math.max((e.clientX - box.left) / box.width, 0), 1) * (b - a);
};
$("#clock-bar").addEventListener("click", (e) => { if (clockRound) seek(clockTime(e)); });
$("#clock-bar").addEventListener("mousemove", (e) => {
  if (!clockRound) return;
  const t = clockTime(e), [a, b] = clockSpan(clockRound);
  $("#clock-ghost").style.left = `${((t - a) / (b - a)) * 100}%`;
  showTip(e, clockAt(clockRound, t), "click to jump here");
});
$("#clock-bar").addEventListener("mouseleave", hideTip);

/* where in the round a moment is, the way the game shows it */
function clockAt(r, t) {
  if (t < r.liveStart) return `Buy phase · ${dur(r.liveStart - t)} left`;
  if (r.end && t >= r.end.start) return "Round over";
  if (r.post && t >= r.post.start) return `Spike planted · ${dur(SPIKE_CLOCK - (t - r.post.start))} left`;
  return `Round clock ${fmt(Math.max(0, ROUND_CLOCK - (t - r.liveStart)))}`;
}
function statusText(r, s, t, p) {
  if (!r) return s ? "Menus, lobby or a break" : "";
  if (p) return `Timeout · ${dur(t - p.start)} so far`;
  return clockAt(r, t);
}

function showTip(e, text, sub) {
  const tip = $("#tip");
  tip.hidden = false;
  tip.replaceChildren(text, sub ? el("small", {}, sub) : "");
  tip.style.left = `${Math.min(e.clientX + 14, innerWidth - tip.offsetWidth - 8)}px`;
  tip.style.top = `${e.clientY - 44}px`;
}
function hideTip() { $("#tip").hidden = true; }

function seek(t) {
  const v = $("#video");
  v.currentTime = Math.min(Math.max(t, 0), (v.duration || duration) - 0.1);
  v.play().catch(() => {});
}

function segAt(t) {
  let lo = 0, hi = segs.length - 1, ans = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (segs[mid].start <= t) { ans = mid; lo = mid + 1; } else hi = mid - 1;
  }
  return ans >= 0 && t < segs[ans].end + 1 ? segs[ans] : null;
}
const pauseAt = (t) => pauses.find((p) => t >= p.start && t <= p.end + 1 && p.end - p.start >= 5);
const roundOf = (s) => (s && s.game != null ? rounds.find((r) => r.game === s.game && r.round === s.round) : null);

let activeKey, activeRound = null, statusKey = "", playingGame = null;
function update() {
  if (view !== "viewer" || !current) return;
  const t = $("#video").currentTime || 0;
  const s = segAt(t), p = pauseAt(t);
  const r = roundOf(s);
  const key = r ? r.key : s ? "between" : null;
  if (key !== activeKey) {
    activeKey = key;
    activeRound = r;
    renderRoundBar(r, s);
    // follow playback into another game, but leave a tab the coach picked alone otherwise
    if (r && r.game !== playingGame && r.game !== shownGame) showGame(r.game);
    else { markActive(true); if (games.length > 1) refreshTabs(); }
    if (r) playingGame = r.game;
  }
  for (const ph of phaseEls) {
    const on = t >= ph.seg.start && t < ph.seg.end;
    ph.el.classList.toggle("on", on);
    ph.el.classList.toggle("past", !on && t >= ph.seg.end);
    ph.fill.style.width = on ? `${((t - ph.seg.start) / Math.max(ph.seg.end - ph.seg.start, 0.1)) * 100}%` : "0";
  }
  if (clockRound) {
    const [a, b] = clockSpan(clockRound);
    const head = $("#clock-head");
    head.style.left = `${Math.min(Math.max((t - a) / (b - a), 0), 1) * 100}%`;
    head.classList.toggle("dim", t < a);
  }
  const st = statusText(r, s, t, p);
  if (st !== statusKey) { statusKey = st; $("#rb-status").textContent = st; }
}
function refreshTabs() {
  for (const [i, b] of [...$("#game-tabs").children].entries()) {
    b.querySelector(".live-dot")?.remove();
    const g = games[i]?.game;
    if (activeRound?.game === g && g !== shownGame) b.append(el("span", { class: "live-dot", title: "Playing" }));
  }
}

function autoSkip() {
  const v = $("#video");
  if (!$("#skip").checked || v.paused || v.seeking) return;
  const t = v.currentTime;
  const s = segAt(t);
  if (s && s.game == null) {
    if (s.end + 1 >= (v.duration || duration) - 1) { v.pause(); return; }
    v.currentTime = s.end + 0.05;
    return;
  }
  const p = pauseAt(t);
  if (p) v.currentTime = p.end + 1;
}

function stepRound(dir) {
  const t = $("#video").currentTime;
  const here = roundOf(segAt(t));
  let target;
  if (dir > 0) target = rounds.find((r) => r.start > t + 0.5);
  else {
    // back: restart the current round if more than 3 s in, otherwise the previous one
    const before = rounds.filter((r) => r.start < t - 3);
    target = before[before.length - 1] || here;
  }
  if (target) seek(target.start);
}

let speed = 1;
$("#speed").addEventListener("click", (e) => {
  const b = e.target.closest("button");
  if (!b) return;
  speed = Number(b.dataset.v);
  $("#video").playbackRate = speed;
});
$("#video").addEventListener("ratechange", () => {
  speed = $("#video").playbackRate;
  for (const b of $("#speed").children) b.classList.toggle("on", Number(b.dataset.v) === speed);
});
$("#video").addEventListener("loadedmetadata", () => { $("#video").playbackRate = speed; });
$("#prev").onclick = () => stepRound(-1);
$("#next").onclick = () => stepRound(1);
$("#video").addEventListener("timeupdate", () => { update(); autoSkip(); });
$("#video").addEventListener("seeked", update);
(function loop() { if (!$("#video").paused) { update(); autoSkip(); } requestAnimationFrame(loop); })();

$("#v-name").addEventListener("click", () => startRename(current, $("#v-name")));
$("#v-more").addEventListener("click", (e) => {
  e.stopPropagation();
  openMenu(e.currentTarget, [
    { label: "Rename", fn: () => startRename(current, $("#v-name")) },
    { label: "Re-run detection", fn: () => reprocess(current, true) },
    { label: "Delete", danger: true, fn: () => removeVod(current) },
  ]);
});

document.addEventListener("keydown", (e) => {
  const typing = ["INPUT", "SELECT", "TEXTAREA"].includes(document.activeElement?.tagName);
  if (e.key === "Escape") { closeMenu(); if (typing) document.activeElement.blur(); return; }
  if (typing || e.ctrlKey || e.metaKey || e.altKey || dlg.open) return;
  if (e.key === "/") { e.preventDefault(); $("#search").focus(); return; }
  if (view !== "viewer") return;
  if (e.key === "]") stepRound(1);
  else if (e.key === "[") stepRound(-1);
  else if (/^[1-4]$/.test(e.key) && activeRound) {
    const seg = activeRound[PHASES[Number(e.key) - 1][0]];
    if (seg) seek(seg.start);
  }
});

/* ---------- boot ---------- */
(async function init() {
  try { config = await api("/api/config"); } catch (_) {}
  await refresh();
  route();
  setInterval(refresh, 2000);
})();
