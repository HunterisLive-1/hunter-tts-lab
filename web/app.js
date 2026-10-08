/* Hunter TTS Lab. Built & customized by The Hunter AI.
   The page: four views over one state object that the local server hands out.
   No framework and nothing loaded from the internet. User text is only ever
   put on the page as text, never as HTML. */
"use strict";

const TOKEN = document.querySelector('meta[name="app-token"]').content;
const main = document.getElementById("main");
const store = {
  get: (k, d = "") => { try { return localStorage.getItem("htl." + k) ?? d; } catch { return d; } },
  set: (k, v) => { try { localStorage.setItem("htl." + k, v); } catch { /* private window: fine */ } },
};

let S = null; // what the server last told us
const ui = {
  view: "studio",
  text: store.get("text"),
  voice: store.get("voice"),
  model: store.get("model"),
  language: "",
  script: "",
  undo: null,
  polishing: false,
  adding: null, // null | "record" | "draft"
  draft: null,
  rec: null,
  lastJobs: {},
};

/* ---------------------------------------------------------------- helpers */

function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "text") el.textContent = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "value") el.value = v;
    else if (v === true) el.setAttribute(k, "");
    else el.setAttribute(k, v);
  }
  for (const kid of kids.flat()) {
    if (kid === null || kid === undefined || kid === false) continue;
    el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  }
  return el;
}

const ICONS = {
  play: '<path d="M8 5.5v13l11-6.5z" fill="currentColor"/>',
  pause: '<path d="M7 5h4v14H7zM13 5h4v14h-4z" fill="currentColor"/>',
  down: '<path d="M12 4v10m0 0l-4-4m4 4l4-4M5 19h14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>',
  mic: '<path d="M12 15a3 3 0 0 0 3-3V7a3 3 0 0 0-6 0v5a3 3 0 0 0 3 3zm-6-3a6 6 0 0 0 12 0M12 18v3" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>',
  wave: '<path d="M4 10v4M8 7v10M12 4v16M16 8v8M20 11v2" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"/>',
};
function icon(name) {
  const s = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  s.setAttribute("viewBox", "0 0 24 24");
  s.setAttribute("aria-hidden", "true");
  s.innerHTML = ICONS[name];
  return s;
}

async function call(method, path, body, raw) {
  const opt = { method, headers: { "X-App-Token": TOKEN } };
  if (raw) opt.body = raw;
  else if (body !== undefined) { opt.body = JSON.stringify(body); opt.headers["Content-Type"] = "application/json"; }
  let res;
  try { res = await fetch(path, opt); }
  catch { throw new Error("The app is not answering. Is its black window still open?"); }
  let data = {};
  try { data = await res.json(); } catch { /* not JSON */ }
  if (!res.ok) throw new Error(data.error || "That did not work (" + res.status + ").");
  return data;
}
const api = { get: (p) => call("GET", p), post: (p, b) => call("POST", p, b || {}), send: (p, blob) => call("POST", p, undefined, blob) };

function toast(message, bad) {
  const t = h("div", { class: "toast" + (bad ? " error" : ""), role: bad ? "alert" : "status", text: message });
  document.getElementById("toasts").append(t);
  setTimeout(() => t.remove(), bad ? 9000 : 4500);
}
async function attempt(fn) {
  try { return await fn(); } catch (e) { toast(e.message, true); return undefined; }
}

function seconds(v) {
  if (v < 10) return v.toFixed(1) + " s";
  if (v < 60) return Math.round(v) + " s";
  return Math.floor(v / 60) + " min " + Math.round(v % 60) + " s";
}
function clock(v) {
  v = Math.max(0, Math.round(v));
  return Math.floor(v / 60) + ":" + String(v % 60).padStart(2, "0");
}
const gb = (v) => (Math.round(v * 10) / 10) + " GB";
const installed = () => (S ? S.models.filter((m) => m.installed) : []);
const activeJobs = (kind) => (S ? S.jobs.filter((j) => (j.status === "waiting" || j.status === "running") && (!kind || j.kind === kind)) : []);

/* ---------------------------------------------------------------- audio: one player, drawn waveforms */

const player = new Audio();
let playing = null; // {key, canvas}
const peaksCache = new Map();

function peaksFromWav(buf, bars) {
  const v = new DataView(buf);
  let at = 12, rate = 0, channels = 1, dataAt = 0, dataLen = 0;
  while (at + 8 <= v.byteLength) {
    const id = String.fromCharCode(v.getUint8(at), v.getUint8(at + 1), v.getUint8(at + 2), v.getUint8(at + 3));
    const size = v.getUint32(at + 4, true);
    if (id === "fmt ") { channels = v.getUint16(at + 10, true); rate = v.getUint32(at + 12, true); }
    if (id === "data") { dataAt = at + 8; dataLen = Math.min(size, v.byteLength - dataAt); break; }
    at += 8 + size + (size % 2);
  }
  const frames = Math.floor(dataLen / (2 * channels));
  const out = new Float32Array(bars);
  if (!frames || !rate) return out;
  const per = frames / bars;
  for (let b = 0; b < bars; b++) {
    let peak = 0;
    const from = Math.floor(b * per), to = Math.min(frames, Math.floor((b + 1) * per) + 1);
    const step = Math.max(1, Math.floor((to - from) / 400));
    for (let f = from; f < to; f += step) {
      const s = Math.abs(v.getInt16(dataAt + f * 2 * channels, true)) / 32768;
      if (s > peak) peak = s;
    }
    out[b] = peak;
  }
  return out;
}

async function peaksFor(url) {
  if (peaksCache.has(url)) return peaksCache.get(url);
  const res = await fetch(url);
  const p = peaksFromWav(await res.arrayBuffer(), 150);
  peaksCache.set(url, p);
  return p;
}

function drawWave(canvas, peaks, played) {
  const css = getComputedStyle(document.documentElement);
  const ratio = window.devicePixelRatio || 1;
  const w = canvas.clientWidth, hgt = canvas.clientHeight;
  if (!w) return;
  if (canvas.width !== Math.round(w * ratio)) { canvas.width = Math.round(w * ratio); canvas.height = Math.round(hgt * ratio); }
  const g = canvas.getContext("2d");
  g.setTransform(ratio, 0, 0, ratio, 0, 0);
  g.clearRect(0, 0, w, hgt);
  const n = peaks.length, slot = w / n, bar = Math.max(1.5, slot * 0.62);
  let top = 0;
  for (const p of peaks) if (p > top) top = p;
  const scale = top > 0.05 ? 1 / top : 1;
  for (let i = 0; i < n; i++) {
    const tall = Math.max(2, peaks[i] * scale * (hgt - 4));
    g.fillStyle = i / n < played ? css.getPropertyValue("--genda") : css.getPropertyValue("--soft");
    g.globalAlpha = i / n < played ? 1 : 0.55;
    g.beginPath();
    g.roundRect(i * slot + (slot - bar) / 2, (hgt - tall) / 2, bar, tall, bar / 2);
    g.fill();
  }
  g.globalAlpha = 1;
}

function waveFor(url) {
  const canvas = h("canvas", { class: "wave", role: "img", "aria-label": "Sound of this clip" });
  canvas.dataset.url = url;
  peaksFor(url).then((p) => { canvas._peaks = p; drawWave(canvas, p, playing && playing.key === url ? player.currentTime / (player.duration || 1) : 0); }).catch(() => {});
  canvas.addEventListener("click", (e) => {
    const box = canvas.getBoundingClientRect();
    const at = (e.clientX - box.left) / box.width;
    if (!playing || playing.key !== url) startPlay(url, canvas);
    const seek = () => { if (player.duration) player.currentTime = at * player.duration; };
    if (player.readyState >= 1) seek(); else player.addEventListener("loadedmetadata", seek, { once: true });
  });
  return canvas;
}

function playButton(url, canvasGetter) {
  const b = h("button", { class: "play", type: "button", "aria-label": "Play" }, icon("play"));
  b.dataset.url = url;
  b.addEventListener("click", () => {
    if (playing && playing.key === url && !player.paused) player.pause();
    else if (playing && playing.key === url) player.play();
    else startPlay(url, canvasGetter ? canvasGetter() : null);
  });
  return b;
}

function startPlay(url, canvas) {
  player.pause();
  playing = { key: url, canvas };
  player.src = url;
  player.play().catch(() => {});
  syncPlayButtons();
}
function syncPlayButtons() {
  document.querySelectorAll("button.play").forEach((b) => {
    const on = playing && playing.key === b.dataset.url && !player.paused;
    b.replaceChildren(icon(on ? "pause" : "play"));
    b.setAttribute("aria-label", on ? "Pause" : "Play");
  });
}
function paintPlayhead() {
  if (playing && playing.canvas && playing.canvas._peaks && playing.canvas.isConnected) {
    drawWave(playing.canvas, playing.canvas._peaks, player.duration ? player.currentTime / player.duration : 0);
  }
  if (playing && !player.paused) requestAnimationFrame(paintPlayhead);
}
player.addEventListener("play", () => { syncPlayButtons(); requestAnimationFrame(paintPlayhead); });
player.addEventListener("pause", syncPlayButtons);
player.addEventListener("ended", () => { syncPlayButtons(); paintPlayhead(); });
window.addEventListener("resize", () => document.querySelectorAll("canvas.wave").forEach((c) => c._peaks && drawWave(c, c._peaks, 0)));

/* ---------------------------------------------------------------- studio */

const studio = {
  mount() {
    const box = h("textarea", {
      class: "script", id: "script", spellcheck: "false", "aria-label": "Script",
      placeholder: "Type or paste what the voice should say. Hindi, Hinglish or English.",
    });
    box.value = ui.text;
    box.addEventListener("input", () => { ui.text = box.value; store.set("text", ui.text); studio.updateGo(); });
    box.addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) studio.go(); });

    main.replaceChildren(
      h("header", { class: "view-head" },
        h("h1", { class: "view-title", text: "Studio" }),
        h("p", { class: "view-sub", text: "Write a script, pick a voice, and the model speaks it in that voice. Everything is made on this PC." })),
      h("div", { id: "studio-callout" }),
      h("div", { class: "chain", id: "chain" },
        h("section", { class: "stage", id: "stage-script" },
          h("div", { class: "node", text: "1" }),
          h("div", { class: "stage-head" }, h("h2", { text: "Script" }), h("span", { class: "spacer" }), h("div", { id: "lang" })),
          h("div", { class: "stage-body" }, box,
            h("div", { class: "script-foot" }, h("div", { id: "polish" }), h("span", { class: "count", id: "count" })))),
        h("section", { class: "stage", id: "stage-voice" },
          h("div", { class: "node", text: "2" }),
          h("div", { class: "stage-head" }, h("h2", { text: "Voice" })),
          h("div", { class: "stage-body" }, h("div", { class: "chips", id: "voice-chips" }), h("p", { class: "note", id: "voice-note", style: "margin-top:8px" }))),
        h("section", { class: "stage", id: "stage-model" },
          h("div", { class: "node", text: "3" }),
          h("div", { class: "stage-head" }, h("h2", { text: "Model" })),
          h("div", { class: "stage-body" }, h("div", { class: "chips", id: "model-chips" }), h("p", { class: "note", id: "model-note", style: "margin-top:8px" }))),
        h("div", { class: "transport" },
          h("div", { class: "node" }, icon("wave")),
          h("div", {},
            h("div", { class: "go-row" },
              h("button", { class: "go", id: "go", type: "button", text: "Make the voice", onclick: () => studio.go() }),
              h("p", { class: "go-note", id: "go-note" })),
            h("div", { id: "speak-progress" })))),
      h("hr", { class: "rule" }),
      h("div", { class: "stage-head" },
        h("h2", { class: "section-title", text: "Your clips", style: "margin:0" }), h("span", { class: "spacer" }),
        h("button", { class: "btn small", type: "button", text: "Open the clips folder", onclick: () => attempt(() => api.post("/api/open", { what: "outputs" })) })),
      h("div", { id: "clips" }));
    this.update();
  },

  update() {
    if (!S || !document.getElementById("chain")) return;
    const ready = installed();
    if (!ui.language) ui.language = S.settings.language;
    if (!ui.script) ui.script = S.settings.script;
    if (!ready.find((m) => m.id === ui.model)) ui.model = ready.length ? ready[0].id : "";
    const model = ready.find((m) => m.id === ui.model);
    if (!S.voices.find((v) => v.id === ui.voice)) ui.voice = model && !model.needs_voice && ui.voice === "" && store.get("voice") === "" && store.get("picked") ? "" : (S.voices[0] ? S.voices[0].id : "");
    if (model && model.needs_voice && !ui.voice && S.voices[0]) ui.voice = S.voices[0].id;

    // callout when nothing can be made yet
    const callout = document.getElementById("studio-callout");
    callout.replaceChildren(ready.length || activeJobs("install").length ? "" : h("div", { class: "callout" },
      h("p", {}, h("b", { text: "No model is installed yet." })),
      h("p", { text: "A model is the part that speaks. Pick one that suits this PC and install it; it is a one-time download." }),
      h("a", { class: "btn primary", href: "#models", text: "Choose a model" })));

    // language
    document.getElementById("lang").replaceChildren(h("div", { class: "seg", role: "group", "aria-label": "Language of the script" },
      ...[["hi", "Hindi or Hinglish"], ["en", "English"]].map(([id, label]) =>
        h("button", { type: "button", "aria-pressed": String(ui.language === id), text: label, onclick: () => { ui.language = id; studio.update(); } }))));

    // polish
    const canPolish = S.settings.has_key && S.settings.gemini_model;
    const mode = h("select", { "aria-label": "How to write the polished script", onchange: (e) => { ui.script = e.target.value; } },
      h("option", { value: "keep", text: "Keep my spelling" }),
      h("option", { value: "devanagari", text: "Write Hindi in Devanagari" }),
      h("option", { value: "english", text: "English script" }));
    mode.value = ui.script;
    document.getElementById("polish").replaceChildren(
      canPolish
        ? h("div", { class: "polish" },
          h("button", { class: "btn", type: "button", disabled: ui.polishing, text: ui.polishing ? "Polishing" : "Polish script", onclick: () => studio.polish() }), mode)
        : h("a", { class: "btn", href: "#settings", text: "Set up script polishing" }),
      ui.undo !== null ? h("button", { class: "btn quiet", type: "button", text: "Undo polish", onclick: () => studio.setText(ui.undo, true) }) : "");

    // voices
    const chips = S.voices.map((v) => h("button", {
      class: "chip", type: "button", "aria-pressed": String(ui.voice === v.id),
      onclick: () => { ui.voice = v.id; store.set("voice", v.id); store.set("picked", "1"); studio.update(); },
    }, v.name, v.builtin ? h("small", { text: "computer made" }) : ""));
    if (model && !model.needs_voice) {
      chips.push(h("button", { class: "chip", type: "button", "aria-pressed": String(ui.voice === ""), text: "Model's own voice",
        onclick: () => { ui.voice = ""; store.set("voice", ""); store.set("picked", "1"); studio.update(); } }));
    }
    chips.push(h("a", { class: "chip add", href: "#voices", text: "Add your voice" }));
    document.getElementById("voice-chips").replaceChildren(...chips);
    const onlySample = S.voices.length === 1 && S.voices[0].builtin;
    document.getElementById("voice-note").textContent = onlySample ? "Only the sample voice is here so far. Add 5 to 10 seconds of your own voice and clips will sound like you." : "";

    // models
    document.getElementById("model-chips").replaceChildren(...(ready.length
      ? ready.map((m) => h("button", {
        class: "chip", type: "button", "aria-pressed": String(ui.model === m.id),
        onclick: () => { ui.model = m.id; store.set("model", m.id); studio.update(); },
      }, m.name, h("small", { text: m.device === "cpu" ? "on the processor" : "on the graphics card" })))
      : [h("a", { class: "chip add", href: "#models", text: "Install a model" })]));
    document.getElementById("model-note").textContent = model ? model.summary : "";

    document.getElementById("stage-voice").classList.toggle("lit", !!ui.voice || (!!model && !model.needs_voice));
    document.getElementById("stage-model").classList.toggle("lit", !!model);
    this.updateGo();
    this.updateProgress();
    this.updateClips();
  },

  updateGo() {
    const go = document.getElementById("go");
    if (!go || !S) return;
    const text = ui.text.trim();
    const model = installed().find((m) => m.id === ui.model);
    const count = document.getElementById("count");
    count.textContent = text.length ? text.length.toLocaleString() + " characters" : "";
    document.getElementById("stage-script").classList.toggle("lit", !!text);
    const speaking = activeJobs("speak").length > 0;
    let why = "";
    if (!model) why = activeJobs("install").length ? "A model is being installed. This will be ready when it finishes." : "Install a model first.";
    else if (!text) why = "Write a script first.";
    else if (text.length > S.limits.script) why = "This script is too long. Keep it under " + S.limits.script.toLocaleString() + " characters.";
    else if (model.needs_voice && !ui.voice) why = "Pick a voice.";
    go.disabled = !!why || speaking;
    const note = document.getElementById("go-note");
    if (why) note.textContent = why;
    else if (speaking) note.textContent = "";
    else {
      const voice = text.length / 16; // a spoken second is about 16 characters of script
      note.textContent = "About " + seconds(voice) + " of voice" + (model.per10 ? ", ready in about " + seconds(Math.max(2, voice * model.per10 / 10)) + " on this PC." : ".");
    }
  },

  updateProgress() {
    const box = document.getElementById("speak-progress");
    if (!box) return;
    const job = activeJobs("speak")[0];
    document.getElementById("chain").classList.toggle("running", !!job);
    if (!job) { box.replaceChildren(); return; }
    const words = job.status === "waiting" ? "Waiting for the job before this one" : (job.detail || "Starting the model");
    const wide = Math.round((job.progress || 0) * 100) + "%";
    const old = box.querySelector('.progress[data-job="' + job.id + '"]');
    if (old) { // same job: change the words and the bar, leave the Cancel button where it is
      old.querySelector("span").textContent = words;
      old.querySelector(".bar").classList.toggle("unknown", !job.progress);
      old.querySelector(".bar i").style.width = wide;
      return;
    }
    box.replaceChildren(h("div", { class: "progress", "data-job": job.id },
      h("div", { class: "row" },
        h("span", { text: words }),
        h("button", { class: "btn small", type: "button", text: "Cancel", onclick: () => attempt(() => api.post("/api/jobs/cancel", { id: job.id })) })),
      h("div", { class: "bar" + (job.progress ? "" : " unknown") }, h("i", { style: "width:" + wide }))));
  },

  updateClips() {
    const box = document.getElementById("clips");
    if (!box) return;
    if (!S.clips.length) {
      box.replaceChildren(h("p", { class: "empty", text: "Clips you make appear here, ready to play and download." }));
      return;
    }
    const have = new Map([...box.querySelectorAll(".clip")].map((el) => [el.dataset.id, el]));
    const rows = S.clips.slice(0, 60).map((c) => have.get(c.id) || studio.clipRow(c));
    box.replaceChildren(...rows);
    syncPlayButtons();
  },

  clipRow(c) {
    const url = "/media/clip/" + c.id + ".wav";
    const canvas = waveFor(url);
    const made = c.audio + " s of voice, made in " + seconds(c.seconds);
    const row = h("article", { class: "clip" },
      playButton(url, () => canvas), canvas,
      h("div", { class: "clip-actions" },
        h("a", { class: "btn small", href: url + "?download=1", download: "" }, icon("down"), "Download WAV"),
        h("button", { class: "btn small quiet", type: "button", text: "Use this script", onclick: () => studio.setText(c.text) }),
        h("button", { class: "btn small quiet danger", type: "button", text: "Delete", onclick: async () => {
          if (playing && playing.key === url) player.pause();
          if (await attempt(() => api.post("/api/clips/delete", { id: c.id }))) { row.remove(); refresh(); }
        } })),
      h("p", { class: "clip-text", text: c.text }),
      h("p", { class: "clip-meta", text: [c.voice, c.model_name, made, c.created].join(", ") }));
    row.dataset.id = c.id;
    return row;
  },

  setText(text, isUndo) {
    ui.undo = isUndo ? null : ui.undo;
    ui.text = text;
    store.set("text", text);
    const box = document.getElementById("script");
    if (box) { box.value = text; box.focus(); window.scrollTo({ top: 0, behavior: "smooth" }); }
    this.update();
  },

  async polish() {
    const text = ui.text.trim();
    if (!text) { toast("Write a script first.", true); return; }
    ui.polishing = true;
    this.update();
    const out = await attempt(() => api.post("/api/polish", { text, script: ui.script }));
    ui.polishing = false;
    if (out && out.text) {
      ui.undo = ui.text;
      ui.text = out.text;
      store.set("text", out.text);
      const box = document.getElementById("script");
      if (box) box.value = out.text;
      toast("Script polished. Read it once before making the voice.");
    }
    this.update();
  },

  async go() {
    const go = document.getElementById("go");
    if (!go || go.disabled) return;
    go.disabled = true;
    const sent = await attempt(() => api.post("/api/generate", { text: ui.text, voice: ui.voice, model: ui.model, language: ui.language }));
    if (sent) { ui.undo = null; await refresh(); } else this.updateGo();
  },
};

/* ---------------------------------------------------------------- voices */

const READ_ALOUD = "Namaste doston, main apni awaaz ka ek chhota sa sample record kar raha hoon. Aaj mausam bahut achha hai, aur main ek naya video banane wala hoon.";

const voicesView = {
  mount() {
    main.replaceChildren(
      h("header", { class: "view-head" },
        h("h1", { class: "view-title", text: "Voices" }),
        h("p", { class: "view-sub", text: "A voice is a short recording the model copies. Save yours once and use it for every clip." })),
      h("div", { id: "voice-list" }),
      h("hr", { class: "rule" }),
      h("h2", { class: "section-title", text: "Add a voice" }),
      h("div", { class: "adder", id: "adder" }));
    this.update();
    this.renderAdder();
  },

  update() {
    const box = document.getElementById("voice-list");
    if (!box || !S) return;
    box.replaceChildren(...S.voices.map((v) => {
      const url = "/media/voice/" + v.id + ".wav";
      return h("article", { class: "voice" },
        playButton(url),
        h("div", {},
          h("h3", { text: v.name }),
          h("p", { class: "note", text: v.builtin ? v.note : v.seconds + " seconds, added " + v.created })),
        h("div", { class: "actions" }, v.builtin ? "" : [
          h("button", { class: "btn small", type: "button", text: "Rename", onclick: async () => {
            const name = prompt("Name for this voice", v.name);
            if (name && await attempt(() => api.post("/api/voices/rename", { id: v.id, name }))) refresh();
          } }),
          h("button", { class: "btn small danger", type: "button", text: "Delete", onclick: async () => {
            if (confirm("Delete the voice \"" + v.name + "\"? Clips already made with it are kept.") && await attempt(() => api.post("/api/voices/delete", { id: v.id }))) refresh();
          } }),
        ]));
    }));
    syncPlayButtons();
  },

  renderAdder() {
    const box = document.getElementById("adder");
    if (!box) return;
    if (ui.adding === "record") return this.renderRecording(box);
    if (ui.adding === "draft" && ui.draft) return this.renderDraft(box);
    const file = h("input", { type: "file", accept: "audio/*,video/mp4,.wav,.mp3,.m4a,.ogg,.flac,.aac", hidden: true, onchange: (e) => e.target.files[0] && this.fromFile(e.target.files[0]) });
    box.replaceChildren(
      h("p", { text: "Use a recording of one person speaking normally. 5 to 10 seconds is enough; a longer one does not clone better." }),
      h("div", { class: "adder-ways" },
        h("button", { class: "btn primary", type: "button", onclick: () => this.record() }, icon("mic"), "Record now"),
        h("button", { class: "btn", type: "button", text: "Choose an audio file", onclick: () => file.click() }), file),
      h("ul", { class: "tips" },
        h("li", { text: "A quiet room, no music and no echo." }),
        h("li", { text: "Speak the way you want the clips to sound: the model copies the mood and speed too." }),
        h("li", { text: "Keep the microphone a hand's width away so the sound does not distort." })));
  },

  async record() {
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false } });
    } catch {
      toast("The browser could not use the microphone. Allow microphone access for this page, or choose an audio file instead.", true);
      return;
    }
    const ctx = new AudioContext();
    const analyser = ctx.createAnalyser();
    analyser.fftSize = 1024;
    ctx.createMediaStreamSource(stream).connect(analyser);
    const recorder = new MediaRecorder(stream);
    const chunks = [];
    recorder.ondataavailable = (e) => e.data.size && chunks.push(e.data);
    recorder.onstop = async () => {
      stream.getTracks().forEach((t) => t.stop());
      ctx.close();
      const cancelled = ui.rec && ui.rec.cancelled;
      ui.rec = null;
      if (cancelled) { ui.adding = null; this.renderAdder(); return; }
      await this.fromBuffer(await new Blob(chunks).arrayBuffer(), "My voice");
    };
    ui.rec = { recorder, analyser, started: performance.now(), cancelled: false };
    ui.adding = "record";
    recorder.start();
    this.renderAdder();
  },

  renderRecording(box) {
    const time = h("div", { class: "rec-time", text: "0:00" });
    const level = h("i");
    box.replaceChildren(
      h("p", {}, h("b", { text: "Recording. " }), "Read this aloud, or say anything in your normal voice:"),
      h("p", { class: "read-this", text: READ_ALOUD }),
      time, h("div", { class: "meter" }, level),
      h("div", { class: "adder-ways" },
        h("button", { class: "btn primary", type: "button", text: "Stop and listen", onclick: () => ui.rec && ui.rec.recorder.stop() }),
        h("button", { class: "btn quiet", type: "button", text: "Cancel", onclick: () => { if (ui.rec) { ui.rec.cancelled = true; ui.rec.recorder.stop(); } } })));
    const data = new Uint8Array(1024);
    const tick = () => {
      if (!ui.rec || !time.isConnected) return;
      const t = (performance.now() - ui.rec.started) / 1000;
      time.textContent = clock(t);
      ui.rec.analyser.getByteTimeDomainData(data);
      let peak = 0;
      for (const v of data) peak = Math.max(peak, Math.abs(v - 128) / 128);
      level.style.width = Math.min(100, Math.round(peak * 130)) + "%";
      if (t >= 20) { ui.rec.recorder.stop(); return; }
      requestAnimationFrame(tick);
    };
    tick();
  },

  async fromFile(file) {
    await this.fromBuffer(await file.arrayBuffer(), file.name.replace(/\.[^.]+$/, "").slice(0, 40));
  },

  async fromBuffer(buf, name) {
    let wav;
    try { wav = await prepareVoice(buf); }
    catch (e) { toast(e.message || "That recording could not be read as audio.", true); ui.adding = null; this.renderAdder(); return; }
    if (ui.draft) URL.revokeObjectURL(ui.draft.url);
    ui.draft = { blob: wav.blob, seconds: wav.seconds, cut: wav.cut, url: URL.createObjectURL(wav.blob), name };
    ui.adding = "draft";
    this.renderAdder();
  },

  renderDraft(box) {
    const d = ui.draft;
    const name = h("input", { type: "text", maxlength: "40", value: d.name, "aria-label": "Name of this voice" });
    const mine = h("input", { type: "checkbox" });
    const save = h("button", { class: "btn primary", type: "button", text: "Save voice", disabled: true });
    mine.addEventListener("change", () => { save.disabled = !mine.checked; });
    save.addEventListener("click", async () => {
      save.disabled = true;
      const out = await attempt(() => api.send("/api/voices?name=" + encodeURIComponent(name.value.trim() || "My voice"), d.blob));
      if (!out) { save.disabled = false; return; }
      URL.revokeObjectURL(d.url);
      ui.draft = null; ui.adding = null;
      ui.voice = out.voice.id; store.set("voice", ui.voice); store.set("picked", "1");
      toast("Voice saved. It is selected in the Studio.");
      await refresh();
      this.renderAdder();
    });
    const short = d.seconds < S.limits.voice_min;
    box.replaceChildren(
      h("p", {}, h("b", { text: "Listen before saving. " }), d.seconds.toFixed(1) + " seconds" + (d.cut ? ", cut down from a longer recording." : ".")),
      short ? h("p", { class: "note", text: "This is very short. Record at least " + S.limits.voice_min + " seconds of speech." }) : "",
      h("div", { class: "draft" },
        h("audio", { controls: true, src: d.url }),
        h("label", { class: "field" }, h("span", { text: "Name" }), name),
        h("label", { class: "check" }, mine, h("span", { text: "This is my own voice, or I have this person's permission to copy it." })),
        h("div", { class: "adder-ways" }, save,
          h("button", { class: "btn quiet", type: "button", text: "Discard", onclick: () => { URL.revokeObjectURL(d.url); ui.draft = null; ui.adding = null; this.renderAdder(); } }))));
  },
};

/* Any audio the browser can read becomes what the engines want: one channel,
   48 kHz, 16-bit, silence trimmed from both ends, at most 15 seconds. */
async function prepareVoice(buf) {
  const RATE = 48000, MAX = 15;
  const probe = new AudioContext();
  let audio;
  try { audio = await probe.decodeAudioData(buf); }
  catch { throw new Error("That file could not be read as audio. Try a WAV, MP3 or M4A file."); }
  finally { probe.close(); }
  const off = new OfflineAudioContext(1, Math.max(1, Math.ceil(audio.duration * RATE)), RATE);
  const src = off.createBufferSource();
  src.buffer = audio;
  src.connect(off.destination);
  src.start();
  const mono = (await off.startRendering()).getChannelData(0);
  let a = 0, b = mono.length - 1;
  while (a < b && Math.abs(mono[a]) < 0.012) a++;
  while (b > a && Math.abs(mono[b]) < 0.012) b--;
  a = Math.max(0, a - Math.round(RATE * 0.12));
  b = Math.min(mono.length - 1, b + Math.round(RATE * 0.2));
  let cut = false;
  if (b - a > MAX * RATE) { b = a + MAX * RATE; cut = true; }
  const part = mono.subarray(a, b + 1);
  let peak = 0;
  for (const v of part) if (Math.abs(v) > peak) peak = Math.abs(v);
  if (peak < 0.01) throw new Error("That recording is silent. Check the microphone and try again.");
  const gain = 0.9 / peak, fade = Math.round(RATE * 0.02);
  const out = new DataView(new ArrayBuffer(44 + part.length * 2));
  const put = (at, s) => { for (let i = 0; i < s.length; i++) out.setUint8(at + i, s.charCodeAt(i)); };
  put(0, "RIFF"); out.setUint32(4, 36 + part.length * 2, true); put(8, "WAVEfmt ");
  out.setUint32(16, 16, true); out.setUint16(20, 1, true); out.setUint16(22, 1, true);
  out.setUint32(24, RATE, true); out.setUint32(28, RATE * 2, true); out.setUint16(32, 2, true); out.setUint16(34, 16, true);
  put(36, "data"); out.setUint32(40, part.length * 2, true);
  for (let i = 0; i < part.length; i++) {
    const edge = Math.min(1, i / fade, (part.length - 1 - i) / fade);
    out.setInt16(44 + i * 2, Math.max(-32767, Math.min(32767, Math.round(part[i] * gain * edge * 32767))), true);
  }
  return { blob: new Blob([out.buffer], { type: "audio/wav" }), seconds: part.length / RATE, cut };
}

/* ---------------------------------------------------------------- models */

const modelsView = {
  mount() {
    main.replaceChildren(
      h("header", { class: "view-head" },
        h("h1", { class: "view-title", text: "Models" }),
        h("p", { class: "view-sub", text: "A model is the part that speaks. The app looks at this PC, says which model suits it, then downloads, sets up and tests it for you." })),
      h("div", { id: "models-body" }));
    this.update();
  },

  update() {
    const box = document.getElementById("models-body");
    if (!box || !S) return;
    if (!S.hw || !S.plan) { box.replaceChildren(h("p", { class: "loading", text: "Looking at this PC" })); return; }
    const hw = S.hw, g = hw.gpus[0];
    const busy = S.jobs.some((j) => j.status === "waiting" || j.status === "running");
    this.shape = S.jobs.filter((j) => j.status === "waiting" || j.status === "running").map((j) => j.id + j.status).join("|");
    box.replaceChildren(
      h("dl", { class: "pc" },
        h("div", {}, h("dt", { text: "Processor" }), h("dd", {}, hw.cpu.name.replace(/\s+\d+-Core Processor$/, ""), h("small", { text: hw.cpu.threads + " threads" }))),
        h("div", {}, h("dt", { text: "Memory" }), h("dd", {}, Math.round(hw.ram_gb) + " GB RAM", h("small", { text: gb(hw.disk_free_gb) + " free on this drive" }))),
        h("div", {}, h("dt", { text: "Graphics card" }), h("dd", {}, g ? g.name.replace(/^NVIDIA GeForce |^AMD |\(R\)|\(TM\)/g, "") : "None found",
          h("small", { text: g ? gb(g.vram_gb) + " of graphics memory" : "Voices are made on the processor" })))),
      h("p", { class: "verdict", text: S.plan.headline }),
      ...S.plan.notes.map((n) => h("p", { class: "note", text: n })),
      h("div", { class: "stage-head", style: "margin-top:14px" },
        h("span", { text: "Make voices on" }),
        h("div", { class: "seg", role: "group", "aria-label": "Where voices are made" },
          ...[["auto", "Best for this PC"], ["cpu", "Processor only"]].map(([id, label]) =>
            h("button", { type: "button", "aria-pressed": String(S.settings.device === id), disabled: busy, text: label, onclick: () => this.setDevice(id) }))),
        h("button", { class: "btn small quiet", type: "button", text: "Check this PC again", onclick: async () => { if (await attempt(() => api.post("/api/hardware/refresh"))) { await refresh(); toast("Checked."); } } })),
      ...S.models.map((m) => this.row(m)));
  },

  row(m) {
    const fit = m.fit || { level: "no", why: "", need_gb: 0, have_gb: 0 };
    const job = S.jobs.find((j) => j.kind === "install" && j.about.model === m.id && (j.status === "waiting" || j.status === "running"));
    const failed = S.jobs.find((j) => j.kind === "install" && j.about.model === m.id && j.status === "failed");
    const side = h("div", { class: "model-side" });
    if (job) {
      side.append(
        h("p", { class: "status", text: job.status === "waiting" ? "Waiting its turn" : "Installing" }),
        h("div", { class: "bar" + (job.progress ? "" : " unknown"), "data-job-bar": job.id }, h("i", { style: "width:" + Math.round((job.progress || 0) * 100) + "%" })),
        h("p", { class: "note", "data-job-detail": job.id, text: job.detail || "Getting ready" }),
        h("button", { class: "btn small", type: "button", text: "Cancel", onclick: () => attempt(() => api.post("/api/jobs/cancel", { id: job.id })) }));
    } else if (m.installed) {
      side.append(
        h("p", { class: "status on", text: "Installed" }),
        h("p", { class: "note", text: "Runs on " + m.runs_on + "." }),
        m.per10 ? h("p", { class: "note", text: "On this PC, 10 seconds of voice takes about " + seconds(m.per10) + "." }) : "",
        h("button", { class: "btn small", type: "button", text: "Test again", onclick: async () => {
          if (await attempt(() => api.post("/api/models/install", { id: m.id }))) refresh();
        } }),
        h("button", { class: "btn small danger", type: "button", text: "Remove", onclick: async () => {
          if (confirm("Remove " + m.name + "? Its " + gb(m.size_gb) + " download is deleted. Your voices and clips stay.") && await attempt(() => api.post("/api/models/remove", { id: m.id }))) { toast(m.name + " removed."); refresh(); }
        } }));
    } else {
      side.append(
        h("button", { class: "btn" + (fit.level === "no" ? "" : " primary"), type: "button", text: "Install", onclick: async () => {
          if (fit.level === "no" && !confirm(m.name + " needs more memory than this PC has, so it will probably fail or be very slow. Install it anyway?")) return;
          if (await attempt(() => api.post("/api/models/install", { id: m.id }))) refresh();
        } }),
        h("p", { class: "note", text: gb(m.size_gb) + " download, plus the engine the first time." }),
        failed ? h("p", { class: "note", style: "color:var(--signal)", text: failed.error }) : "");
    }
    const share = fit.have_gb ? Math.min(100, Math.round(fit.need_gb / fit.have_gb * 100)) : 100;
    return h("article", { class: "model" },
      h("div", {},
        h("h3", {}, m.name, fit.recommended ? h("span", { class: "badge", text: "Best for this PC" }) : "", fit.level === "no" ? h("span", { class: "badge plain", text: "Too heavy for this PC" }) : ""),
        h("p", { class: "by" }, "by " + m.by + ", " + m.license + " licence. ", h("a", { class: "link", href: m.home, target: "_blank", rel: "noopener", text: "About this model" })),
        h("p", { class: "summary", text: m.summary + " " + m.detail }),
        h("div", { class: "fit " + fit.level },
          h("div", { class: "track", role: "img", "aria-label": fit.why }, h("i", { style: "width:" + share + "%" })),
          h("p", { text: fit.why + (m.installed ? "" : " " + fit.speed_guess) }))),
      side,
      m.notes.length ? h("p", { class: "model-notes", text: m.notes.join(" ") }) : "");
  },

  /* While an install runs, only its bar and its line of text change. Redrawing
     the whole list twice a second would pull a button out from under the
     pointer, so the list is rebuilt only when a job starts or ends. */
  patch(jobs) {
    const live = jobs.filter((j) => j.status === "waiting" || j.status === "running");
    const shape = live.map((j) => j.id + j.status).join("|");
    if (shape !== this.shape) { this.shape = shape; this.update(); return; }
    for (const j of live) {
      const bar = document.querySelector('[data-job-bar="' + j.id + '"]');
      const detail = document.querySelector('[data-job-detail="' + j.id + '"]');
      if (bar) { bar.classList.toggle("unknown", !j.progress); bar.firstChild.style.width = Math.round((j.progress || 0) * 100) + "%"; }
      if (detail) detail.textContent = j.detail || "Getting ready";
    }
  },

  async setDevice(id) {
    if (S.settings.device === id) return;
    if (installed().length && !confirm("Models that are installed will be set up again for this choice and tested. That needs a download. Continue?")) return;
    if (await attempt(() => api.post("/api/settings", { device: id }))) refresh();
  },
};

/* ---------------------------------------------------------------- settings */

const settingsView = {
  models: null,
  mount() {
    main.replaceChildren(
      h("header", { class: "view-head" }, h("h1", { class: "view-title", text: "Settings" })),
      h("div", { class: "settings" },
        h("h2", { class: "section-title", text: "Script polishing" }),
        h("p", { class: "view-sub", style: "margin-bottom:16px", text: "Optional. With a free Google Gemini key the app can tidy a script before it is spoken: punctuation, numbers written as words, and Hinglish turned into Hindi script, which the models read more clearly." }),
        h("div", { id: "gemini" }),
        h("hr", { class: "rule" }),
        h("h2", { class: "section-title", text: "Your files" }),
        h("p", { class: "view-sub", style: "margin-bottom:14px", text: "Voices, clips, models and settings live in the app's data folder on this PC." }),
        h("div", { class: "adder-ways" },
          h("button", { class: "btn", type: "button", text: "Open the clips folder", onclick: () => attempt(() => api.post("/api/open", { what: "outputs" })) }),
          h("button", { class: "btn", type: "button", text: "Open the data folder", onclick: () => attempt(() => api.post("/api/open", { what: "data" })) })),
        h("hr", { class: "rule" }),
        h("div", { class: "about", id: "about" })));
    this.update();
    if (S && S.settings.has_key && !this.models) this.loadModels();
  },

  update() {
    const box = document.getElementById("gemini");
    if (!box || !S) return;
    const s = S.settings;
    if (!s.has_key) {
      const key = h("input", { type: "password", autocomplete: "off", placeholder: "Paste your Gemini API key", "aria-label": "Gemini API key" });
      box.replaceChildren(
        h("div", { class: "inline" }, key,
          h("button", { class: "btn primary", type: "button", text: "Save key", onclick: async () => {
            const value = key.value.trim();
            if (!value) { toast("Paste the key first.", true); return; }
            const list = await attempt(() => api.post("/api/gemini/models", { key: value })); // also proves the key works
            if (!list) return;
            const pick = (list.models.find((m) => m.free) || list.models[0] || {}).id || "";
            if (await attempt(() => api.post("/api/settings", { gemini_key: value, gemini_model: pick }))) { this.models = list.models; toast("Key saved."); refresh(); }
          } })),
        h("p", { class: "note", style: "margin-top:10px" }, "The key is free. ",
          h("a", { class: "link", href: "https://aistudio.google.com/apikey", target: "_blank", rel: "noopener", text: "Get one from Google AI Studio" }),
          ". It is kept on this PC and sent only to Google, and only when you press Polish script."));
    } else {
      const pick = h("select", { "aria-label": "Gemini model", onchange: async (e) => { if (await attempt(() => api.post("/api/settings", { gemini_model: e.target.value }))) refresh(); } });
      const list = this.models || (s.gemini_model ? [{ id: s.gemini_model, name: s.gemini_model, free: true }] : []);
      const free = list.filter((m) => m.free), paid = list.filter((m) => !m.free);
      if (free.length) pick.append(h("optgroup", { label: "Usually free" }, ...free.map((m) => h("option", { value: m.id, text: m.name }))));
      if (paid.length) pick.append(h("optgroup", { label: "Other models" }, ...paid.map((m) => h("option", { value: m.id, text: m.name }))));
      pick.value = s.gemini_model;
      box.replaceChildren(
        h("p", { style: "margin-bottom:14px" }, h("b", { text: "Key saved" }), " (ends in " + s.key_hint.replace("…", "") + "). ",
          h("button", { class: "btn small quiet danger", type: "button", text: "Remove key", onclick: async () => { if (await attempt(() => api.post("/api/settings", { gemini_key: "" }))) { this.models = null; refresh(); } } })),
        h("label", { class: "field" }, h("span", { text: "Model" }), pick),
        h("p", { class: "note" }, "Google decides which models are free and how much you can use them. If one says its limit is used up, pick another. ",
          h("button", { class: "btn small quiet", type: "button", text: "Refresh the list", onclick: () => this.loadModels(true) })));
    }
    const a = S.app;
    document.getElementById("about").replaceChildren(
      h("h2", { class: "section-title", text: "About" }),
      h("p", {}, h("b", { text: a.name + " " + a.version + ". " }), a.credit + "."),
      h("p", {}, "Tutorials and updates: ", h("a", { href: a.channel_url, target: "_blank", rel: "noopener", text: a.channel + " on YouTube" }), ". Source code: ", h("a", { href: a.repo_url, target: "_blank", rel: "noopener", text: "GitHub" }), "."),
      h("p", { text: "Voices are made on this PC by the audio.cpp engine (ShugoAI, Apache 2.0) with the Chatterbox (Resemble AI, MIT) and VoxCPM2 (OpenBMB, Apache 2.0) models. Nothing you write or record leaves this PC, except a script you choose to polish, which goes to Google." }),
      h("p", { text: "Copy only your own voice, or a voice you have permission to copy." }));
  },

  async loadModels(say) {
    const list = await attempt(() => api.post("/api/gemini/models", {}));
    if (list) { this.models = list.models; this.update(); if (say) toast("List refreshed."); }
  },
};

/* ---------------------------------------------------------------- routing and refresh */

const VIEWS = { studio, voices: voicesView, models: modelsView, settings: settingsView };

function show(view) {
  if (ui.rec) { ui.rec.cancelled = true; ui.rec.recorder.stop(); }
  ui.view = VIEWS[view] ? view : "studio";
  document.querySelectorAll(".nav a").forEach((a) => a.dataset.view === ui.view ? a.setAttribute("aria-current", "page") : a.removeAttribute("aria-current"));
  document.title = ui.view.charAt(0).toUpperCase() + ui.view.slice(1) + " - Hunter TTS Lab";
  VIEWS[ui.view].mount();
  window.scrollTo(0, 0);
}
window.addEventListener("hashchange", () => show(location.hash.slice(1)));

function paintRail() {
  const chip = document.getElementById("pc-chip");
  if (!S || !S.hw) return;
  const g = S.hw.gpus[0];
  chip.hidden = false;
  chip.replaceChildren(h("b", { text: g ? g.name.replace(/^NVIDIA GeForce |^AMD |\(R\)|\(TM\)/g, "") : "No graphics card" }),
    (g ? gb(g.vram_gb) + " graphics, " : "") + Math.round(S.hw.ram_gb) + " GB RAM");
  const sub = document.getElementById("subscribe");
  sub.href = S.app.channel_url;
}

async function refresh() {
  const next = await attempt(() => api.get("/api/state"));
  if (!next) return;
  S = next;
  paintRail();
  VIEWS[ui.view].update();
}

function noticeJobs(jobs) {
  let finished = false;
  for (const j of jobs) {
    const before = ui.lastJobs[j.id];
    // A quick job can start and end between two looks, so "never seen" counts as a change too.
    if (before !== j.status && ["done", "failed", "cancelled"].includes(j.status)) {
      finished = true;
      if (j.status === "failed") toast(j.error || "That did not work.", true);
      else if (j.status === "done" && j.kind === "install") toast(j.title.replace("Installing", "Installed") + ". It is ready in the Studio.");
      else if (j.status === "done" && j.kind === "speak") {
        toast("Your clip is ready.");
        const id = j.result && j.result.clip && j.result.clip.id;
        if (id) setTimeout(() => { const c = document.querySelector('.clip[data-id="' + id + '"] canvas'); if (c && ui.view === "studio") startPlay("/media/clip/" + id + ".wav", c); }, 250);
      }
    }
    ui.lastJobs[j.id] = j.status;
  }
  return finished;
}

async function tick() {
  let wait = 2500;
  try {
    const data = await api.get("/api/jobs");
    const finished = noticeJobs(data.jobs);
    if (S) S.jobs = data.jobs;
    if (finished || !S || !S.hw) await refresh();
    else if (ui.view === "studio") { studio.updateProgress(); studio.updateGo(); }
    else if (ui.view === "models") modelsView.patch(data.jobs);
    if (data.jobs.some((j) => j.status === "running" || j.status === "waiting") || !S || !S.hw) wait = 600;
  } catch { wait = 4000; }
  setTimeout(tick, wait);
}

/* ---------------------------------------------------------------- start */

(function theme() {
  const button = document.getElementById("theme");
  const apply = (t) => {
    if (t) document.documentElement.dataset.theme = t; else delete document.documentElement.dataset.theme;
    const dark = t ? t === "dark" : !matchMedia("(prefers-color-scheme: light)").matches;
    button.textContent = dark ? "Light look" : "Dark look";
    document.querySelectorAll("canvas.wave").forEach((c) => c._peaks && drawWave(c, c._peaks, 0));
  };
  apply(store.get("theme") || "");
  button.addEventListener("click", () => {
    const dark = document.documentElement.dataset.theme ? document.documentElement.dataset.theme === "dark" : !matchMedia("(prefers-color-scheme: light)").matches;
    const next = dark ? "light" : "dark";
    store.set("theme", next);
    apply(next);
  });
})();

(async function start() {
  await refresh();
  for (const j of (S ? S.jobs : [])) ui.lastJobs[j.id] = j.status;
  show(location.hash.slice(1) || "studio");
  tick();
})();
