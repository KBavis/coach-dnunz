"use strict";
const $ = (s) => document.querySelector(s);
const el = (tag, attrs = {}, ...kids) => {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") n.className = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else n.setAttribute(k, v);
  }
  n.append(...kids);
  return n;
};
const fmt = (t) => {
  t = Math.max(0, Math.floor(t));
  const h = Math.floor(t / 3600), m = Math.floor((t % 3600) / 60), s = t % 60;
  const ss = String(s).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${ss}` : `${m}:${ss}`;
};
const parseTime = (str) => {
  const parts = String(str).trim().split(":").map(Number);
  if (parts.some(Number.isNaN)) return NaN;
  return parts.reduce((acc, p) => acc * 60 + p, 0);
};
const api = async (path, opts) => {
  const r = await fetch(path, opts);
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail || msg; } catch (_) {}
    throw new Error(msg);
  }
  return r.json();
};

const PHASE = {
  PRE_ROUND: { cls: "pre", name: "Pre-round" },
  ROUND: { cls: "live", name: "Live round" },
  POST_PLANT: { cls: "post", name: "Post-plant" },
  ROUND_END: { cls: "end", name: "Round end" },
  NON_GAME: { cls: "dead", name: "Dead time" },
};

let vods = [];
let current = null;      // detail of the selected VOD
let segs = [];           // all segments sorted by start
let pauses = [];
let rounds = [];         // [{game, round, pre, live, post, end, liveStart, total}]
let duration = 0;

/* ---------- library ---------- */
async function refreshLibrary() {
  vods = await api("/api/vods");
  renderLibrary();
  if (current && ["queued", "processing"].includes(current.status)) await selectVod(current.id, true);
}

function renderLibrary() {
  const ul = $("#library");
  ul.replaceChildren(...vods.map((v) => {
    const sub = v.status === "ready" ? fmt(v.duration)
      : v.status === "failed" ? "failed" : `${v.stage || "waiting"} · ${Math.round(v.pct)}%`;
    const name = el("span", { class: "li-name", title: v.name }, v.name);
    const li = el("li", { class: v.id === current?.id ? "active" : "", onclick: () => selectVod(v.id) },
      el("div", { class: "li-top" }, name,
        el("span", { class: `badge ${v.status}` }, v.status),
        el("button", { class: "li-btn", title: "Rename", onclick: (e) => { e.stopPropagation(); startRename(v.id, name); } }, "✎"),
        el("button", { class: "li-btn", title: "Delete", onclick: (e) => { e.stopPropagation(); removeVod(v); } }, "✕")),
      el("div", { class: "li-sub" }, sub));
    if (v.status === "processing" || v.status === "queued")
      li.append(el("div", { class: "bar" }, el("div", { style: `width:${v.pct}%` })));
    return li;
  }));
}

function startRename(id, target) {
  const vod = vods.find((v) => v.id === id) || current;
  const input = el("input", { class: "rename", value: vod.name });
  target.replaceWith(input);
  input.focus(); input.select();
  let done = false;
  const finish = async (save) => {
    if (done) return; done = true;
    const name = input.value.trim();
    if (save && name && name !== vod.name) {
      try { await api(`/api/vods/${id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name }) }); }
      catch (e) { alert(e.message); }
    }
    await refreshLibrary();
    if (current?.id === id) { current.name = name || current.name; $("#v-name").textContent = current.name; $("#p-name").textContent = current.name; }
  };
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") finish(true); if (e.key === "Escape") finish(false); });
  input.addEventListener("blur", () => finish(true));
  input.addEventListener("click", (e) => e.stopPropagation());
}

async function removeVod(v) {
  if (!confirm(`Delete "${v.name}" from the library?\n\nThe processed results are removed; a file you imported by path is not deleted.`)) return;
  try { await api(`/api/vods/${v.id}`, { method: "DELETE" }); } catch (e) { return alert(e.message); }
  if (current?.id === v.id) { current = null; history.replaceState(null, "", "#"); show("empty"); }
  refreshLibrary();
}

/* ---------- upload ---------- */
function upload(file) {
  return new Promise((resolve) => {
    const box = $("#upload-status");
    box.hidden = false;
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/vods");
    xhr.upload.onprogress = (e) => { if (e.lengthComputable) box.textContent = `Uploading ${file.name} — ${Math.round((e.loaded / e.total) * 100)}%`; };
    xhr.onload = () => {
      box.hidden = true;
      if (xhr.status >= 200 && xhr.status < 300) resolve(JSON.parse(xhr.responseText).id);
      else { let m = xhr.statusText; try { m = JSON.parse(xhr.responseText).detail; } catch (_) {} alert(`${file.name}: ${m}`); resolve(null); }
    };
    xhr.onerror = () => { box.hidden = true; alert(`Upload of ${file.name} failed`); resolve(null); };
    const fd = new FormData(); fd.append("file", file);
    xhr.send(fd);
  });
}
async function uploadAll(files) {
  let last = null;
  for (const f of files) last = (await upload(f)) || last;
  await refreshLibrary();
  if (last) selectVod(last);
}
$("#url-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const btn = $("#url-add"), input = $("#url");
  btn.disabled = true;
  try {
    const r = await api("/api/vods/from-url", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ url: input.value }) });
    input.value = "";
    await refreshLibrary();
    selectVod(r.id);
  } catch (err) { alert(err.message); }
  btn.disabled = false;
});
const drop = $("#drop");
["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); }));
["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
drop.addEventListener("drop", (e) => uploadAll([...e.dataTransfer.files]));
$("#file").addEventListener("change", (e) => { uploadAll([...e.target.files]); e.target.value = ""; });
// dropping anywhere on the page should not navigate away to the raw file
window.addEventListener("dragover", (e) => e.preventDefault());
window.addEventListener("drop", (e) => { e.preventDefault(); if (e.dataTransfer.files.length && !drop.contains(e.target)) uploadAll([...e.dataTransfer.files]); });

/* ---------- selecting a VOD ---------- */
function show(which) {
  for (const id of ["empty", "processing", "viewer"]) $("#" + id).hidden = id !== which;
}

async function selectVod(id, polling = false) {
  let d;
  try { d = await api(`/api/vods/${id}`); } catch (e) { return; }
  const wasReady = current?.id === id && current.status === "ready";
  current = d;
  history.replaceState(null, "", `#vod=${id}`);
  renderLibrary();
  if (d.status === "ready" && d.result) {
    if (!wasReady) openViewer(d);
  } else {
    show("processing");
    $("#p-name").textContent = d.name;
    $("#p-stage").textContent = d.status === "failed" ? "Processing failed" : `${d.stage || "Waiting"} — ${Math.round(d.pct)}%`;
    $("#p-bar").style.width = `${d.pct}%`;
    $("#p-error").hidden = d.status !== "failed";
    $("#p-error").textContent = d.error;
    $("#p-retry").hidden = d.status !== "failed";
    $("#p-retry").onclick = async () => { await api(`/api/vods/${id}/reprocess`, { method: "POST" }); refreshLibrary(); selectVod(id); };
  }
}

/* ---------- viewer ---------- */
function buildRounds(result) {
  const map = new Map();
  for (const s of result.segments) {
    if (s.game == null) continue;
    const key = `${s.game}:${s.round}`;
    if (!map.has(key)) map.set(key, { game: s.game, round: s.round });
    const r = map.get(key);
    const slot = { PRE_ROUND: "pre", ROUND: "live", POST_PLANT: "post", ROUND_END: "end" }[s.phase];
    r[slot] = s;
  }
  return [...map.values()].map((r) => {
    const first = r.pre || r.live || r.post || r.end;
    r.start = first.start;
    r.liveStart = (r.live || r.post || r.end).start;          // the round "starts" when it goes live
    const last = r.end || r.post || r.live || r.pre;
    r.finish = last.end;
    r.playTime = Math.max(0, ((r.post || r.live || r.end).end) - r.liveStart);   // live + post-plant length
    return r;
  }).sort((a, b) => a.start - b.start);
}

function openViewer(d) {
  const res = d.result;
  segs = [...res.segments].sort((a, b) => a.start - b.start);
  pauses = res.pauses || [];
  duration = res.duration || d.duration;
  rounds = buildRounds(res);
  activeKey = null; activeRound = null; lastKey = ""; nowKey = "";
  show("viewer");
  $("#v-name").textContent = d.name;
  const games = res.games.length;
  $("#v-meta").textContent = `${fmt(duration)} · ${games} game${games === 1 ? "" : "s"} · ${rounds.length} rounds · ${pauses.length} pause${pauses.length === 1 ? "" : "s"}`;
  const v = $("#video");
  v.src = `/api/vods/${d.id}/video`;
  v.playbackRate = Number($("#speed").value);
  renderTimeline(res);
  renderRounds(res);
  // Go-to form
  $("#g-game").replaceChildren(...res.games.map((g) => el("option", { value: g.game }, `Game ${g.game}`)));
  $("#g-game").style.display = games > 1 ? "" : "none";
  updateCaption();
}

function renderTimeline() {
  const tl = $("#timeline");
  tl.replaceChildren();
  for (const s of segs) {
    tl.append(el("div", {
      class: `seg ${PHASE[s.phase].cls}` + (s.phase === "ROUND" ? " round-start" : ""),
      style: `left:${(s.start / duration) * 100}%;width:${Math.max(((s.end - s.start) / duration) * 100, 0.08)}%`,
      onclick: () => seek(s.start),          // clicking a labelled section jumps to where it starts
    }));
  }
  tl.append(el("div", { id: "round-band", style: "display:none" }), el("div", { id: "playhead" }));
  $("#tl-games").replaceChildren(...current.result.games.map((g) => el("span", {
    style: `left:${(g.start / duration) * 100}%;width:${((g.end - g.start) / duration) * 100}%`,
  }, `Game ${g.game} · ${g.rounds} rounds`)));
  $("#pauses").replaceChildren(...pauses.map((p) => el("div", {
    class: "p", title: `Timeout · ${fmt(p.end - p.start)} · timer stuck at ${p.timer} · ${fmt(p.start)}`,
    style: `left:${(p.start / duration) * 100}%;width:${((p.end - p.start) / duration) * 100}%`,
    onclick: () => seek(p.start),
  })));
}

const labelFor = (s) => s.game == null ? "Dead time" : `Game ${s.game} · Round ${s.round} · ${PHASE[s.phase].name}`;

const TICK_OFFSETS = [30, 60, 90, 120, 150];

function renderRounds(res) {
  const box = $("#rounds");
  box.replaceChildren();
  for (const g of res.games) {
    const rs = rounds.filter((r) => r.game === g.game);
    box.append(el("div", { class: "game-h", "data-game": g.game }, `Game ${g.game} · ${fmt(g.start)}–${fmt(g.end)} · ${rs.length} rounds`));
    for (const r of rs) box.append(roundCard(r));
  }
}

function roundCard(r) {
  const span = Math.max(r.finish - r.start, 1);
  const pct = (t) => ((t - r.start) / span) * 100;
  const card = el("div", { class: "round", "data-key": `${r.game}:${r.round}` });
  card.append(el("div", { class: "r-top" }, el("b", {}, `Round ${r.round}`),
    el("span", { title: "Length of the live round, including the post-plant" }, `${fmt(r.playTime)} live`)));

  // labelled sections: click one to jump to where it starts; it fills as the video plays through it
  const sections = el("div", { class: "sections" });
  r.secs = [];
  const defs = [[r.pre, "pre", "Pre-round", 92], [r.live, "live", "Live round", 94], [r.post, "post", "Post-plant", 96], [r.end, "end", "Round end", 90]];
  for (const [seg, cls, name, minw] of defs) {
    if (!seg) continue;
    const dur = seg.end - seg.start;
    const fill = el("i", { class: "fill" });
    const btn = el("button", {
      class: `sec ${cls}${seg.start >= 3600 ? " long" : ""}`, title: `Jump to the start of ${name.toLowerCase()} (${fmt(seg.start)})`,
      style: `flex:${Math.max(dur, cls === "end" ? 6 : 14)} 1 0;min-width:${minw}px`, onclick: () => seek(seg.start),
    }, el("span", { class: "n" }, name), el("span", { class: "d" }, cls === "end" ? fmt(seg.start) : `${fmt(dur)} · ${fmt(seg.start)}`), fill);
    sections.append(btn);
    r.secs.push({ seg, el: btn, fill });
  }
  card.append(sections);

  const tos = pauses.filter((p) => p.start < r.finish && p.end > r.start);
  if (tos.length) {
    card.append(el("div", { class: "timeouts" }, ...tos.map((p) => el("button", {
      class: "timeout", title: `Timer stuck at ${p.timer}. Jump to the start of the timeout.`, onclick: () => seek(p.start),
    }, `Timeout ${fmt(p.end - p.start)} · ${fmt(p.start)}`))));
  }

  // fine scrubber: click anywhere inside the round, with ticks every 30 s of live round
  const mini = el("div", { class: "mini" });
  for (const seg of [r.pre, r.live, r.post, r.end].filter(Boolean)) {
    mini.append(el("div", { class: `seg ${PHASE[seg.phase].cls}`, style: `left:${pct(seg.start)}%;width:${((seg.end - seg.start) / span) * 100}%` }));
  }
  const offs = TICK_OFFSETS.filter((o) => r.liveStart + o < r.finish - 3);
  for (const o of offs) mini.append(el("div", { class: "tickline", style: `left:${pct(r.liveStart + o)}%` }));
  mini.append(el("div", { class: "ghost" }), el("div", { class: "mph" }));
  const timeAt = (e) => { const b = mini.getBoundingClientRect(); return r.start + Math.min(Math.max((e.clientX - b.left) / b.width, 0), 1) * span; };
  mini.addEventListener("click", (e) => seek(timeAt(e)));
  mini.addEventListener("mousemove", (e) => {
    const t = timeAt(e);
    mini.querySelector(".ghost").style.left = `${pct(t)}%`;
    showTip(e, describe(t, r), `video ${fmt(t)}`);
  });
  mini.addEventListener("mouseleave", hideTip);
  card.append(mini);
  const ticks = el("div", { class: "ticks" });
  for (const o of offs) ticks.append(el("span", { class: "tick", style: `left:${pct(r.liveStart + o)}%`, title: `${fmt(o)} into the live round`, onclick: () => seek(r.liveStart + o) }, `+${fmt(o)}`));
  card.append(ticks);
  r.mph = mini.querySelector(".mph");
  r.pct = pct;
  return card;
}

/* what is happening at video time t, phrased for a coach */
function describe(t, r) {
  const s = segAt(t);
  if (!s || s.game == null) return "Dead time";
  r = r || roundOf(s);
  const base = `Game ${s.game} · Round ${s.round}`;
  if (s.phase === "PRE_ROUND") return `${base} · Pre-round — live round starts in ${fmt(Math.max(0, r.liveStart - t))}`;
  if (s.phase === "ROUND_END") return `${base} · Round end`;
  return `${base} · ${PHASE[s.phase].name} — ${fmt(t - r.liveStart)} into the round`;
}

/* floating tooltip */
function showTip(e, text, sub) {
  const tip = $("#tip");
  tip.hidden = false;
  tip.replaceChildren(text, el("small", {}, sub || ""));
  const w = tip.offsetWidth;
  tip.style.left = `${Math.min(e.clientX + 14, window.innerWidth - w - 8)}px`;
  tip.style.top = `${e.clientY + 16}px`;
}
const hideTip = () => { $("#tip").hidden = true; };

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
const roundOf = (s) => s && s.game != null ? rounds.find((r) => r.game === s.game && r.round === s.round) : null;

let lastKey = "";
let activeKey = null, activeRound = null;
function updateCaption() {
  const v = $("#video");
  const t = v.currentTime || 0;
  $("#playhead") && ($("#playhead").style.left = `${(t / duration) * 100}%`);
  const s = segAt(t);
  const cap = $("#caption");
  if (!s) { cap.hidden = true; return; }
  cap.hidden = false;
  const info = PHASE[s.phase];
  cap.className = info.cls;
  const p = pauseAt(t);
  if (p && s.game != null) cap.className = "paused";
  let head, body;
  if (s.game == null) { head = "DEAD TIME"; body = "Menus / lobby"; }
  else {
    const r = roundOf(s);
    head = `GAME ${s.game} · ROUND ${s.round}`;
    body = `${info.name} — ${fmt(t - s.start)} in`;
    if (r && (s.phase === "ROUND" || s.phase === "POST_PLANT")) body += ` · ${fmt(t - r.liveStart)} into the round`;
    if (p) body = `Timeout — ${fmt(t - p.start)} in (timer stuck at ${p.timer})`;
  }
  const key = head + body;
  if (key !== lastKey) { cap.replaceChildren(el("b", {}, head), body); lastKey = key; }
  updateNowBar(s, t, p);
  const rk = s.game != null ? `${s.game}:${s.round}` : null;
  if (rk !== activeKey) {
    document.querySelectorAll(".round.now").forEach((n) => n.classList.remove("now"));
    if (activeRound?.mph) activeRound.mph.style.display = "none";
    for (const sec of activeRound?.secs || []) { sec.el.classList.remove("active"); sec.fill.style.width = "0"; }
    activeKey = rk;
    activeRound = rk ? roundOf(s) : null;
    document.querySelectorAll(".game-h.now").forEach((n) => n.classList.remove("now"));
    if (activeRound) document.querySelector(`.game-h[data-game="${activeRound.game}"]`)?.classList.add("now");
    const band = $("#round-band");
    if (band) {
      band.style.display = activeRound ? "block" : "none";
      if (activeRound) { band.style.left = `${(activeRound.start / duration) * 100}%`; band.style.width = `${Math.max(((activeRound.finish - activeRound.start) / duration) * 100, 0.3)}%`; }
    }
    const card = rk && document.querySelector(`.round[data-key="${rk}"]`);
    if (card) {
      card.classList.add("now");
      if ($("#follow").checked) {
        const panel = $("#rounds");
        panel.scrollTo({ top: card.offsetTop - panel.offsetTop - panel.clientHeight * 0.25 });
      }
    }
  }
  for (const sec of activeRound?.secs || []) {
    const on = t >= sec.seg.start && t < sec.seg.end;
    sec.el.classList.toggle("active", on);
    sec.fill.style.width = on ? `${((t - sec.seg.start) / Math.max(sec.seg.end - sec.seg.start, 0.1)) * 100}%` : "0";
  }
  if (activeRound?.mph) {
    activeRound.mph.style.display = "block";
    activeRound.mph.style.left = `${activeRound.pct(Math.min(Math.max(t, activeRound.start), activeRound.finish))}%`;
  }
}

let nowKey = "";
function updateNowBar(s, t, p) {
  const bar = $("#now");
  let game = "GAME –", round = "ROUND –", phase, cls, time;
  if (!s || s.game == null) { phase = "Dead time"; cls = "dead"; time = "menus / lobby"; }
  else {
    const r = roundOf(s);
    game = `GAME ${s.game}`; round = `ROUND ${s.round}`;
    cls = PHASE[s.phase].cls; phase = PHASE[s.phase].name;
    if (s.phase === "PRE_ROUND") time = `live round starts in ${fmt(Math.max(0, r.liveStart - t))}`;
    else if (s.phase === "ROUND_END") time = "round has ended";
    else time = `${fmt(t - r.liveStart)} into the live round`;
    if (p) { cls = "paused"; phase = "Timeout"; time = `timer stuck at ${p.timer} · ${fmt(t - p.start)} into the timeout`; }
  }
  const key = [game, round, phase, time].join("|");
  if (key === nowKey) return;
  nowKey = key;
  bar.className = cls;
  $("#now-game").textContent = game; $("#now-round").textContent = round;
  $("#now-phase").textContent = phase; $("#now-time").textContent = time;
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
    // back: restart the current round if we're > 3s in, otherwise the previous one
    const candidates = rounds.filter((r) => r.start < t - 3);
    target = candidates[candidates.length - 1];
    if (!target && here) target = here;
  }
  if (target) seek(target.start);
}

$("#prev").onclick = () => stepRound(-1);
$("#next").onclick = () => stepRound(1);
$("#speed").onchange = (e) => { $("#video").playbackRate = Number(e.target.value); };
$("#video").addEventListener("ratechange", () => { $("#speed").value = String($("#video").playbackRate); });
$("#video").addEventListener("timeupdate", () => { updateCaption(); autoSkip(); });
$("#video").addEventListener("seeked", updateCaption);
$("#video").addEventListener("loadedmetadata", () => { $("#video").playbackRate = Number($("#speed").value); });
(function loop() { if (!$("#video").paused) { updateCaption(); autoSkip(); } requestAnimationFrame(loop); })();

$("#timeline").addEventListener("mousemove", (e) => {
  const r = $("#timeline").getBoundingClientRect();
  const t = ((e.clientX - r.left) / r.width) * duration;
  const seg = segAt(t);
  showTip(e, describe(t), seg ? `click to jump to the start of this section · ${fmt(seg.start)}` : `video ${fmt(t)}`);
});
$("#timeline").addEventListener("mouseleave", hideTip);

$("#goto").addEventListener("submit", (e) => {
  e.preventDefault();
  const game = Number($("#g-game").value) || 1;
  const n = Number($("#g-round").value);
  const off = parseTime($("#g-off").value);
  const r = rounds.find((x) => x.game === game && x.round === n);
  if (!r) return alert(`Game ${game} has no round ${n}`);
  if (Number.isNaN(off)) return alert("Offset should look like 1:00");
  const base = $("#g-into").value === "live" ? r.liveStart : (r.pre ? r.pre.start : r.start);
  seek(base + off);
});

$("#v-name").addEventListener("click", () => startRename(current.id, $("#v-name")));
$("#v-reprocess").addEventListener("click", async () => {
  if (!confirm("Re-run detection from scratch on this VOD? It can take a long time.")) return;
  await api(`/api/vods/${current.id}/reprocess`, { method: "POST" });
  current.status = "queued";
  await refreshLibrary();
  selectVod(current.id);
});

document.addEventListener("keydown", (e) => {
  if (["INPUT", "SELECT", "TEXTAREA"].includes(document.activeElement?.tagName) || e.ctrlKey || e.metaKey || e.altKey) return;
  if (e.key === "]") stepRound(1);
  else if (e.key === "[") stepRound(-1);
});

/* ---------- boot ---------- */
(async function init() {
  await refreshLibrary();
  const m = location.hash.match(/vod=(\w+)/);
  if (m && vods.some((v) => v.id === m[1])) selectVod(m[1]);
  setInterval(() => refreshLibrary().catch(() => {}), 2500);
})();
