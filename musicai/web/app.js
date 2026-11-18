"use strict";
// ====================================================================
//  music-Ai フロントエンド（素の JavaScript、外部ライブラリなし）
// ====================================================================
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const h = (tag, attrs = {}, ...kids) => {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "html") el.innerHTML = v;
    else if (v !== undefined && v !== null && v !== false) el.setAttribute(k, v === true ? "" : v);
  }
  for (const c of kids.flat()) if (c !== null && c !== undefined) el.append(c.nodeType ? c : String(c));
  return el;
};
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const debounce = (fn, ms = 350) => { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; };

async function api(path, body) {
  const opt = body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  const r = await fetch(path, opt);
  const j = await r.json().catch(() => ({ error: "サーバーと通信できません（アプリのウィンドウが閉じていませんか？）" }));
  if (!r.ok || j.error && !("phrases" in j)) throw new Error(j.error || r.statusText);
  return j;
}
function toast(msg, isError = false) {
  const t = $("#toast");
  t.textContent = msg; t.className = isError ? "error" : ""; t.hidden = false;
  clearTimeout(toast._t); toast._t = setTimeout(() => (t.hidden = true), isError ? 7000 : 3000);
}
async function busy(msg, fn) {
  $("#busy-msg").textContent = msg; $("#busy").hidden = false;
  try { return await fn(); } catch (e) { toast(e.message, true); throw e; } finally { $("#busy").hidden = true; }
}

// ---------------- タブ ----------------
function showTab(name, opts = {}) {
  $$(".tabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  $$(".tab").forEach((t) => t.classList.toggle("active", t.id === "tab-" + name));
  if (name === "home") refreshSongs();
  if (name === "kaeuta") refreshSongs().then(() => kLoad());
  if (name === "editor" && !opts.noload) refreshSongs().then(() => { if (!E.cur && $("#e-song").value) eLoad($("#e-song").value); });
  window.scrollTo(0, 0);
}
$$(".tabs button").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.tab)));
$$("[data-goto]").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.goto)));

// ---------------- 曲リスト ----------------
let SONGS = [];
async function refreshSongs() {
  SONGS = (await api("/api/songs")).songs;
  const ul = $("#home-songs");
  ul.replaceChildren(...SONGS.map((s) => h("li", {}, h("button", { onclick: () => openInEditor(s.name) }, s.title, h("span", { class: "sub" }, s.name + ".yaml")))));
  if (!SONGS.length) ul.append(h("li", { class: "muted" }, "まだありません"));
  for (const sel of [$("#e-song"), $("#k-song")]) {
    const v = sel.id === "e-song" && E.cur ? E.cur.name : sel.value;
    sel.replaceChildren(...SONGS.map((s) => h("option", { value: s.name }, `${s.title}（${s.name}）`)));
    if (v && SONGS.some((s) => s.name === v)) sel.value = v;
  }
}

// ---------------- 共通 ----------------
const TONICS = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"];
const COLORS = { low: "#4a9fe0", mid: "#f0a03c", high: "#ff5d8f", inst: "#9b8fd6" };
let PROGS = [];

async function loadProgressions() {
  PROGS = (await api("/api/progressions?key=C")).items;
}

async function moraOf(text) {
  if (!text.trim()) return { phrases: [] };
  return api("/api/mora", { text });
}

// ====================================================================
//  作曲
// ====================================================================
const PART_TYPES = {
  "イントロ": { energy: "low", prog: "王道進行", bars: 4 },
  "Aメロ": { energy: "low", prog: "カノン進行" },
  "Bメロ": { energy: "mid", prog: "Bメロ定番" },
  "サビ": { energy: "high", prog: "王道進行" },
  "間奏": { energy: "mid", prog: "王道進行", bars: 4 },
  "Cメロ": { energy: "mid", prog: "小室進行" },
  "アウトロ": { energy: "low", prog: "IV V I I", bars: 4 },
};
const TEMPLATES = {
  jpop: {
    tempo: 124, style: "pop", key: ["G", "major"], parts: [
      ["イントロ"],
      ["Aメロ", "new", "", "まどをあけたら\nかぜがはこんだ\n{新|あたら}しいきせつの\nにおいがしたよ"],
      ["Bメロ", "new", "", "ふあんもあるけど\nこころがはしりだす"],
      ["サビ", "new", "", "はじまりのうたを\n{今|いま}うたおう\n{空|そら}までとどけ\nぼくらのこえ"],
      ["間奏"],
      ["Aメロ2", "second", "Aメロ", "きのうのぼくに\nさよならをして\nまだしらないみちを\nあるいてゆくよ"],
      ["Bメロ", "repeat", "Bメロ"],
      ["サビ", "repeat", "サビ"],
      ["アウトロ"],
    ],
  },
  short: {
    tempo: 132, style: "pop", key: ["C", "major"], parts: [
      ["イントロ", "new", "", "", 2],
      ["Aメロ", "new", "", "ここにうたを\nかいてみよう"],
      ["サビ", "new", "", "ららら きみと\nうたおうよ"],
      ["アウトロ", "new", "", "", 2],
    ],
  },
  ballad: {
    tempo: 76, style: "ballad", key: ["D", "major"], parts: [
      ["イントロ"],
      ["Aメロ", "new", "", "しずかなよるに\nきみをおもう\nとおいまちの\nあかりのなか"],
      ["サビ", "new", "", "あいたいよ\nいますぐに\nこのこえが\nとどくまで"],
      ["アウトロ"],
    ],
  },
};

const C = { parts: [] };
let partSeq = 0;

function newPart(type, kind = "new", ref = "", lyrics = "", bars) {
  const base = PART_TYPES[type.replace(/\d+$/, "")] || PART_TYPES["Aメロ"];
  return { uid: ++partSeq, id: type, kind, ref, prog: base.prog, custom: "", energy: base.energy, lyrics,
           bars: bars || base.bars || 4 };
}

function applyTemplate(name) {
  const t = TEMPLATES[name];
  $("#c-tempo").value = t.tempo; $("#c-tempo-out").textContent = t.tempo;
  $("#c-style").value = t.style; $("#c-tonic").value = t.key[0]; $("#c-mode").value = t.key[1];
  C.parts = t.parts.map(([type, kind, ref, lyr, bars]) => newPart(type, kind || "new", ref || "", lyr || "", bars));
  renderParts();
}

function keyStr() { return `${$("#c-tonic").value} ${$("#c-mode").value}`; }

function definedBefore(i) {
  return C.parts.slice(0, i).filter((p) => p.kind !== "repeat").map((p) => p.id);
}

function renderParts() {
  const box = $("#c-sections");
  box.replaceChildren(...C.parts.map((p, i) => partCard(p, i)));
}

function partCard(p, i) {
  const color = p.kind === "repeat" ? "#aaa" : (p.lyrics.trim() || p.kind === "second" ? COLORS[p.energy] : COLORS.inst);
  const card = h("div", { class: "sec-card", style: `--c:${color}` });
  const refs = definedBefore(i);
  const nameIn = h("input", { class: "name", value: p.id, title: "パートの名前",
    onchange: (e) => { const old = p.id; p.id = e.target.value.trim() || old;
      C.parts.forEach((q) => { if (q.ref === old) q.ref = p.id; }); renderParts(); } });
  const kindSel = h("select", { onchange: (e) => { p.kind = e.target.value; if (p.kind !== "new" && !p.ref) p.ref = refs[0] || ""; renderParts(); } },
    h("option", { value: "new" }, "新しいメロディを作る"),
    refs.length ? h("option", { value: "second" }, "前のパートと同じメロディ・歌詞だけ変える（2番）") : null,
    refs.length ? h("option", { value: "repeat" }, "前のパートをもう一度（そのまま）") : null);
  kindSel.value = p.kind;
  const refSel = p.kind !== "new" ? h("select", { onchange: (e) => { p.ref = e.target.value; if (p.kind === "repeat") p.id = p.ref; renderParts(); } },
    ...refs.map((r) => h("option", { value: r }, r))) : null;
  if (refSel) refSel.value = p.ref;

  const head = h("div", { class: "sec-head" },
    h("span", { class: "num" }, i + 1),
    p.kind === "repeat" ? h("b", {}, p.ref) : nameIn,
    kindSel, refSel,
    h("span", { class: "spacer" }),
    h("button", { class: "iconbtn ghost", title: "上へ", onclick: () => { if (i > 0) { [C.parts[i - 1], C.parts[i]] = [C.parts[i], C.parts[i - 1]]; renderParts(); } } }, "↑"),
    h("button", { class: "iconbtn ghost", title: "下へ", onclick: () => { if (i < C.parts.length - 1) { [C.parts[i + 1], C.parts[i]] = [C.parts[i], C.parts[i + 1]]; renderParts(); } } }, "↓"),
    h("button", { class: "iconbtn ghost danger", title: "削除", onclick: () => { C.parts.splice(i, 1); renderParts(); } }, "✕"));
  card.append(head);
  if (p.kind === "repeat") {
    card.append(h("div", { class: "hint" }, `「${p.ref}」をメロディも歌詞もそのままもう一度演奏します`));
    return card;
  }

  // 左: 進行・盛り上がり
  const left = h("div");
  if (p.kind === "new") {
    const progSel = h("select", { onchange: (e) => { p.prog = e.target.value; updateChords(); renderParts(); } },
      ...PROGS.map((g) => h("option", { value: g.name }, `${g.name}（${g.desc}）`)),
      h("option", { value: "__custom" }, "自分で入力（例: I V vi IV / C G Am F）"));
    const isCustom = !PROGS.some((g) => g.name === p.prog);
    progSel.value = isCustom ? "__custom" : p.prog;
    left.append(h("label", {}, "コード進行", progSel));
    if (isCustom || p.prog === "__custom") {
      left.append(h("input", { value: p.custom || (p.prog !== "__custom" ? p.prog : ""), placeholder: "I V vi IV",
        oninput: debounce((e) => { p.custom = e.target.value; updateChords(); }) }));
    }
    const prev = h("div", { class: "chords-preview" });
    left.append(prev);
    const updateChords = async () => {
      const prog = p.prog === "__custom" ? p.custom : p.prog;
      if (!prog) { prev.textContent = ""; return; }
      try { prev.textContent = (await api("/api/chords", { key: keyStr(), progression: prog })).chords.join("  "); prev.classList.remove("bad"); }
      catch (e) { prev.textContent = e.message; prev.classList.add("bad"); }
    };
    updateChords();
    card._updateChords = updateChords;
  } else {
    left.append(h("div", { class: "hint" }, `メロディとコードは「${p.ref}」と同じ。歌詞の文字数が違っても自動で合わせます。`));
  }
  const enSel = h("select", { onchange: (e) => { p.energy = e.target.value; renderParts(); } },
    h("option", { value: "low" }, "静か（Aメロ・イントロ向き）"),
    h("option", { value: "mid" }, "ふつう（Bメロ向き）"),
    h("option", { value: "high" }, "盛り上がる（サビ向き・音域も高く）"));
  enSel.value = p.energy;
  left.append(h("label", {}, "盛り上がり", enSel));
  if (!p.lyrics.trim() && p.kind === "new") {
    left.append(h("label", {}, "小節数（歌詞なしの時）",
      h("input", { type: "number", min: 1, max: 32, value: p.bars, onchange: (e) => (p.bars = +e.target.value || 4) })));
  }

  // 右: 歌詞
  const moraBox = h("div", { class: "mora-lines" });
  const ta = h("textarea", { rows: 4, placeholder: "歌詞（なしならインスト）\n1 行 = 1 フレーズ", oninput: (e) => { p.lyrics = e.target.value; updMora(); } });
  ta.value = p.lyrics;
  const updMora = debounce(async () => {
    const r = await moraOf(p.lyrics).catch((e) => ({ error: e.message, phrases: [] }));
    let ref = null;
    if (p.kind === "second") {
      const rp = C.parts.find((q) => q.id === p.ref && q.kind !== "repeat");
      if (rp && rp.lyrics.trim()) ref = (await moraOf(rp.lyrics).catch(() => ({ phrases: [] }))).phrases.map((x) => x.length);
    }
    moraBox.replaceChildren(...(r.error ? [h("div", { class: "bad" }, r.error)] : r.phrases.map((ph, k) => {
      const n = ph.length;
      let cls = n > 14 ? "warnc" : "ok", note = n > 14 ? "長め（4 小節使います）" : "";
      if (ref) { cls = ref[k] === n ? "ok" : "warnc"; note = ref[k] === undefined ? "（元にない行）" : ref[k] === n ? "1番と同じ" : `1番は ${ref[k]}（自動で合わせます）`; }
      return h("div", {}, h("span", { class: "n " + cls }, `${n} モーラ`), h("span", { class: "muted" }, ph.join("・")), h("span", { class: cls }, note));
    })));
    card.style.setProperty("--c", p.lyrics.trim() || p.kind === "second" ? COLORS[p.energy] : COLORS.inst);
  }, 250);
  updMora();
  const right = h("div", {}, h("label", {}, "歌詞"), ta, moraBox);
  card.append(h("div", { class: "sec-body" }, left, right));
  return card;
}

function buildSpec() {
  const sections = {};
  const structure = [];
  for (const p of C.parts) {
    if (p.kind === "repeat") {
      if (!sections[p.ref]) throw new Error(`「${p.ref}」がまだ作られていません（順番を確認してください）`);
      structure.push(p.ref);
      continue;
    }
    if (sections[p.id]) throw new Error(`パート名「${p.id}」が重複しています。もう一度使うときは「前のパートをもう一度」を選ぶか、名前を変えてください`);
    structure.push(p.id);
    if (p.kind === "second") {
      sections[p.id] = { base: p.ref, energy: p.energy };
      if (p.lyrics.trim()) sections[p.id].lyrics = p.lyrics;
    } else {
      const prog = p.prog === "__custom" ? p.custom : p.prog;
      if (!prog.trim()) throw new Error(`「${p.id}」のコード進行が空です`);
      sections[p.id] = { progression: prog, energy: p.energy };
      if (p.lyrics.trim()) sections[p.id].lyrics = p.lyrics;
      else sections[p.id].bars = p.bars;
    }
  }
  if (!structure.length) throw new Error("パートがありません");
  return { title: $("#c-title").value || "untitled", key: keyStr(), tempo: +$("#c-tempo").value,
           style: $("#c-style").value, seed: +$("#c-seed").value, structure, sections };
}

$("#c-tempo").addEventListener("input", (e) => ($("#c-tempo-out").textContent = e.target.value));
$("#c-tonic").addEventListener("change", () => $$(".sec-card").forEach((c) => c._updateChords && c._updateChords()));
$("#c-mode").addEventListener("change", () => $$(".sec-card").forEach((c) => c._updateChords && c._updateChords()));
$("#c-add").addEventListener("click", () => {
  const used = new Set(C.parts.map((p) => p.id));
  let name = "Aメロ", k = 2;
  for (const t of Object.keys(PART_TYPES)) if (!used.has(t)) { name = t; break; }
  while (used.has(name)) name = name.replace(/\d+$/, "") + k++;
  C.parts.push(newPart(name)); renderParts();
});
$$("[data-template]").forEach((b) => b.addEventListener("click", () => applyTemplate(b.dataset.template)));
$("#c-dice").addEventListener("click", () => { $("#c-seed").value = Math.floor(Math.random() * 1000); $("#c-go").click(); });
$("#c-go").addEventListener("click", async () => {
  let spec;
  try { spec = buildSpec(); } catch (e) { return toast(e.message, true); }
  const r = await busy("メロディを作っています…", () => api("/api/compose", { spec }));
  toast("作曲しました！音を作ります");
  await openInEditor(r.name, true);
});

// ====================================================================
//  替え歌
// ====================================================================
const K = { song: null };
async function kLoad() {
  const name = $("#k-song").value;
  if (!name) { $("#k-sections").replaceChildren(h("p", { class: "muted" }, "曲がありません。")); return; }
  if (K.song && K.song.name === name) return;
  K.song = await api("/api/song?name=" + encodeURIComponent(name));
  $("#k-title").placeholder = K.song.view.title + "（替え歌）";
  const secs = K.song.view.sections.filter((s) => s.has_melody);
  const order = K.song.view.structure.filter((n, i, a) => a.indexOf(n) === i);
  secs.sort((a, b) => order.indexOf(a.name) - order.indexOf(b.name));
  $("#k-sections").replaceChildren(...secs.map(kSection));
  $("#k-report-panel").hidden = true;
}
function kSection(sec) {
  const orig = sec.phrases.length ? sec.phrases : [];
  // 元の歌詞があればそのモーラ数、なければ（取り込んだ曲など）メロディのフレーズごとの音の数
  const counts = orig.length ? orig.map((p) => p.length) : (sec.mel_phrases || []);
  const origBox = h("div", { class: "k-orig" },
    h("b", {}, `【${sec.name}】`), h("span", { class: "muted" }, ` 歌う音 ${sec.sung} 個`),
    ...(orig.length ? orig.map((ph) => h("div", { class: "phr" }, ph.join(""), h("span", { class: "cnt" }, `${ph.length}`)))
      : counts.map((c, k) => h("div", { class: "phr" }, `フレーズ${k + 1}`, h("span", { class: "cnt" }, `${c} 音`)))));
  const status = h("div", { class: "mora-lines" });
  const ta = h("textarea", { rows: Math.max(2, counts.length), "data-sec": sec.name,
    placeholder: counts.length ? `新しい歌詞（${counts.length} 行に分けて書くと合わせやすい。空欄ならこのパートは元のまま）` : "新しい歌詞" });
  const upd = debounce(async () => {
    const r = await moraOf(ta.value).catch((e) => ({ error: e.message, phrases: [] }));
    if (r.error) return status.replaceChildren(h("div", { class: "bad" }, r.error));
    const rows = r.phrases.map((ph, k) => {
      const want = counts[k] !== undefined ? counts[k] : null;
      const n = ph.length;
      let msg = "", cls = "ok";
      if (want === null) { msg = ""; }
      else if (n === want) msg = "✓ ぴったり";
      else if (n > want) { msg = `+${n - want} → 音符を割って合わせます`; cls = "warnc"; }
      else { msg = `${n - want} → 音を伸ばして合わせます`; cls = "warnc"; }
      return h("div", {}, h("span", { class: "n " + cls }, `${n}${want !== null ? " / " + want : ""}`), h("span", { class: "muted" }, ph.join("・")), h("span", { class: cls }, msg));
    });
    if (r.phrases.length && counts.length && r.phrases.length !== counts.length)
      rows.push(h("div", { class: "warnc" }, `フレーズ数が違います（元 ${counts.length} / 新 ${r.phrases.length}）。全体で配分します。改行で揃えると自然になります`));
    const total = r.phrases.reduce((a, p) => a + p.length, 0);
    if (total) rows.push(h("div", { class: "muted" }, `合計 ${total} モーラ（元の歌う音 ${sec.sung}）`));
    status.replaceChildren(...rows);
  }, 250);
  ta.addEventListener("input", upd);
  return h("div", { class: "k-sec" }, origBox, h("div", {}, ta, status));
}
$("#k-song").addEventListener("change", () => { K.song = null; kLoad(); });

// ---- 取り込み（YouTube / 音声ファイル）----
$$(".seg-btn").forEach((b) => b.addEventListener("click", () => {
  $$(".seg-btn").forEach((x) => x.classList.toggle("active", x === b));
  $("#k-src-saved").hidden = b.dataset.src !== "saved";
  $("#k-src-import").hidden = b.dataset.src !== "import";
  if (b.dataset.src === "import") importInfo();
}));
async function importInfo() {
  try {
    const r = await api("/api/import_info");
    $("#i-info").textContent = (r.demucs ? " ✓ 高精度のボーカル分離（demucs）が使えます。" : "")
      + (r.ytdlp ? "" : " ※ YouTube の取得には yt-dlp が必要です（音声ファイルは使えます）。");
  } catch { /* 無視 */ }
}
$("#i-url").addEventListener("input", () => { if ($("#i-url").value) $("#i-file").value = ""; });
$("#i-file").addEventListener("change", () => { if ($("#i-file").files.length) $("#i-url").value = ""; });
$("#i-go").addEventListener("click", async () => {
  const url = $("#i-url").value.trim(), file = $("#i-file").files[0];
  if (!url && !file) return toast("YouTube の URL を貼るか、音声ファイルを選んでください", true);
  if (url && !/^https?:\/\//.test(url)) return toast("URL は https:// から始まるものを貼ってください", true);
  const prog = $("#i-progress"), msg = $("#i-msg"), btn = $("#i-go");
  prog.hidden = false; btn.disabled = true; $("#i-log").hidden = true;
  try {
    const body = { start: $("#i-start").value, end: $("#i-end").value, title: $("#i-title").value };
    if (file) {
      msg.textContent = "ファイルを送っています…";
      const up = await fetch("/api/upload", { method: "POST", headers: { "X-Filename": encodeURIComponent(file.name) }, body: file });
      const uj = await up.json();
      if (!up.ok) throw new Error(uj.error || "アップロードに失敗しました");
      body.upload = uj.upload;
    } else body.url = url;
    const { job } = await api("/api/import", body);
    let st;
    for (;;) {
      await new Promise((r) => setTimeout(r, 800));
      st = await api("/api/job?id=" + job);
      msg.textContent = st.message || "";
      if (st.state !== "running") break;
    }
    if (st.state === "error") throw new Error(st.error);
    const res = st.result;
    $("#i-log").textContent = "✓ 「" + res.title + "」を取り込みました\n" + res.log.join("\n")
      + "\n\n下の ② で新しい歌詞を書いてください。聴き取り結果は「編集・再生」の「元の音源と聴き比べ」で確認できます。";
    $("#i-log").hidden = false;
    await refreshSongs();
    $("#k-song").value = res.name;
    K.song = null;
    await kLoad();
    $("#k-title").value = "";
    toast("取り込みました！");
  } catch (e) {
    toast(e.message, true);
  } finally {
    prog.hidden = true; btn.disabled = false;
  }
});
$("#k-go").addEventListener("click", async () => {
  if (!K.song) return;
  const lyrics = {};
  $$("#k-sections textarea").forEach((t) => { if (t.value.trim()) lyrics[t.dataset.sec] = t.value; });
  if (!Object.keys(lyrics).length) return toast("新しい歌詞を 1 つ以上入れてください", true);
  const title = $("#k-title").value.trim() || K.song.view.title + "（替え歌）";
  const r = await busy("替え歌を作っています…", () => api("/api/kaeuta", { yaml: K.song.yaml, lyrics, title }));
  $("#k-report").textContent = r.report.join("\n");
  const panel = $("#k-report-panel");
  panel.hidden = false;
  $("#k-listen")?.remove();
  panel.append(h("button", { id: "k-listen", class: "primary", onclick: () => openInEditor(r.name, true) }, "▶ 聴いてみる"));
  panel.scrollIntoView({ behavior: "smooth" });
});

// ====================================================================
//  編集・再生
// ====================================================================
const E = { cur: null, notes: [], raf: 0, pxPerBeat: 26 };

async function openInEditor(name, autoplay = false) {
  showTab("editor", { noload: true });
  await eLoad(name);
  await refreshSongs();
  if (autoplay) await ePlay();
}

async function eLoad(name) {
  const r = await api("/api/song?name=" + encodeURIComponent(name));
  E.cur = { name: r.name, yaml: r.yaml, view: r.view, dirty: false };
  $("#e-yaml").value = r.yaml;
  $("#e-audio").removeAttribute("src");
  E.offset = 0;
  $("#e-downloads").replaceChildren();
  eShow(r.view);
  hLoad(r.name);
  pLoad(r.name);
}

function eShow(v) {
  E.cur.view = v;
  const dur = Math.round(v.duration_sec);
  $("#e-meta").textContent = `${v.title} ／ キー ${v.key} ／ ${v.tempo} BPM ／ ${Math.floor(dur / 60)}:${String(dur % 60).padStart(2, "0")}`;
  $("#e-tempo").value = v.tempo;
  $("#e-style").value = v.style;
  $("#e-acc-wrap").hidden = !v.source;
  $("#e-acc").value = v.accompaniment || "generated";
  $("#e-orig").hidden = !(v.source && v.source.original_url);
  const byName = Object.fromEntries(v.sections.map((s) => [s.name, s]));
  const order = v.structure.filter((n, i, a) => a.indexOf(n) === i);
  $("#e-sections").replaceChildren(...order.map((n) => {
    const s = byName[n];
    const col = s.has_melody ? COLORS[s.energy] || COLORS.mid : COLORS.inst;
    const chords = [...new Set(s.chords.map((c) => c.name).filter((c) => c !== "N.C."))].join(" ");
    return h("div", { class: "secbox", style: `--c:${col}` }, h("b", {}, s.name), h("span", { class: "muted" }, `  ${s.bars}小節`),
      h("div", { class: "muted" }, chords), h("div", { class: "lyr" }, s.phrases.map((p) => p.join("")).join("\n") || (s.has_melody ? "（歌詞なし）" : "（インスト）")));
  }));
  const w = $("#e-warn");
  w.hidden = !v.warnings.length;
  w.textContent = "⚠ " + v.warnings.join("\n⚠ ");
  // ピアノロール用の絶対時間ノート
  E.notes = [];
  E.lines = [];
  for (const t of v.timeline) {
    const s = byName[t.name];
    let line = [], lastEnd = null;
    for (const n of s.notes) {
      if (lastEnd !== null && n.t - lastEnd > 0.01 && line.length) { E.lines.push(line); line = []; }
      const ev = { ...n, t: n.t + t.start, sec: t.name };
      E.notes.push(ev); line.push(ev); lastEnd = n.t + n.d;
    }
    if (line.length) E.lines.push(line);
  }
  drawRoll(-1);
}

function drawRoll(beat) {
  const v = E.cur?.view; if (!v) return;
  const cv = $("#e-roll");
  const total = v.timeline.reduce((a, t) => Math.max(a, t.start + t.length), 0);
  const ppb = E.pxPerBeat;
  const W = Math.max(cv.parentElement.clientWidth, total * ppb + 20);
  const H = 320, top = 40;
  const dpr = window.devicePixelRatio || 1;
  if (cv.width !== Math.round(W * dpr)) { cv.width = Math.round(W * dpr); cv.style.width = W + "px"; cv.height = H * dpr; cv.style.height = H + "px"; }
  const g = cv.getContext("2d");
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  const css = getComputedStyle(document.documentElement);
  const col = (n) => css.getPropertyValue(n).trim();
  g.fillStyle = col("--roll-bg"); g.fillRect(0, 0, W, H);
  const ps = E.notes.map((n) => n.p);
  const lo = (ps.length ? Math.min(...ps) : 60) - 3, hi = (ps.length ? Math.max(...ps) : 72) + 3;
  const rowH = (H - top - 8) / (hi - lo + 1);
  const y = (p) => top + (hi - p) * rowH;
  // 黒鍵の行
  for (let p = lo; p <= hi; p++) if ([1, 3, 6, 8, 10].includes(p % 12)) { g.fillStyle = col("--roll-grid"); g.fillRect(0, y(p), W, rowH); }
  // セクション帯
  const byName = Object.fromEntries(v.sections.map((s) => [s.name, s]));
  g.font = "bold 12px system-ui, sans-serif";
  for (const t of v.timeline) {
    const s = byName[t.name];
    const c = s.has_melody ? COLORS[s.energy] : COLORS.inst;
    g.fillStyle = c; g.globalAlpha = 0.9; g.fillRect(t.start * ppb + 1, 0, t.length * ppb - 2, 18); g.globalAlpha = 1;
    g.fillStyle = "#fff"; g.fillText(t.name, t.start * ppb + 6, 13);
    g.font = "11px system-ui, sans-serif"; g.fillStyle = col("--muted");
    for (const ch of s.chords) if (ch.name !== "N.C.") g.fillText(ch.name, (t.start + ch.t) * ppb + 3, 32);
    g.font = "bold 12px system-ui, sans-serif";
  }
  // 小節線
  for (let b = 0; b <= total; b += v.beats_per_bar) { g.fillStyle = col("--roll-bar"); g.fillRect(b * ppb, top - 4, 1, H); }
  // ノート
  g.font = "11px system-ui, sans-serif";
  for (const n of E.notes) {
    const x = n.t * ppb, w = Math.max(3, n.d * ppb - 2), yy = y(n.p);
    const active = beat >= n.t && beat < n.t + n.d;
    g.fillStyle = active ? col("--accent-2") : col("--accent");
    g.globalAlpha = n.m ? 0.55 : 1;
    roundRect(g, x + 1, yy + 1, w, Math.max(4, rowH - 2), 3); g.fill();
    g.globalAlpha = 1;
    if (n.l && !n.m) { g.fillStyle = col("--text"); g.fillText(n.l, x + 2, yy - 2); }
  }
  if (beat >= 0) { g.fillStyle = col("--accent-2"); g.fillRect(beat * ppb, 0, 2, H); }
}
function roundRect(g, x, y, w, h, r) { g.beginPath(); g.moveTo(x + r, y); g.arcTo(x + w, y, x + w, y + h, r); g.arcTo(x + w, y + h, x, y + h, r); g.arcTo(x, y + h, x, y, r); g.arcTo(x, y, x + w, y, r); g.closePath(); }

function tick() {
  const a = $("#e-audio");
  const beat = (a.currentTime - (E.offset || 0)) * (E.cur?.view.tempo || 120) / 60;
  drawRoll(beat);
  // 自動スクロール
  const wrap = $(".roll-wrap"), x = beat * E.pxPerBeat;
  if (x < wrap.scrollLeft + 40 || x > wrap.scrollLeft + wrap.clientWidth - 80) wrap.scrollLeft = Math.max(0, x - 80);
  // 歌詞表示
  const line = E.lines?.find((l) => beat >= l[0].t - 1.0 && beat < l[l.length - 1].t + l[l.length - 1].d + 0.5);
  const box = $("#e-lyrics-now");
  if (line) {
    box.innerHTML = line.filter((n) => !n.m).map((n) => `<span class="${beat >= n.t ? "done" : "todo"}">${esc(n.l)}</span>`).join("");
  } else box.textContent = "";
  if (!a.paused) E.raf = requestAnimationFrame(tick);
}
$("#e-audio").addEventListener("play", () => { cancelAnimationFrame(E.raf); E.raf = requestAnimationFrame(tick); });
$("#e-audio").addEventListener("pause", () => cancelAnimationFrame(E.raf));
$("#e-audio").addEventListener("seeked", tick);
$("#e-roll").addEventListener("click", (e) => {
  const a = $("#e-audio"); if (!a.src || !E.cur) return;
  const r = e.target.getBoundingClientRect();
  a.currentTime = ((e.clientX - r.left) / E.pxPerBeat) * 60 / E.cur.view.tempo + (E.offset || 0);
});

function setYamlField(field, value) {
  const ta = $("#e-yaml");
  const re = new RegExp(`^${field}:.*$`, "m");
  ta.value = re.test(ta.value) ? ta.value.replace(re, `${field}: ${value}`) : `${field}: ${value}\n` + ta.value;
  E.cur.dirty = true;
}
$("#e-tempo").addEventListener("change", (e) => { setYamlField("tempo", +e.target.value); eCheck(true); });
$("#e-style").addEventListener("change", (e) => { setYamlField("style", e.target.value); eCheck(true); });
$("#e-acc").addEventListener("change", (e) => { setYamlField("accompaniment", e.target.value); eCheck(true); });
$("#e-orig").addEventListener("click", async () => {
  const src = E.cur?.view.source; if (!src?.original_url) return;
  const a = $("#e-audio");
  E.offset = src.offset;  // 元の音源では 1 小節目が offset 秒の位置
  a.src = src.original_url + "?t=" + Date.now();
  a.addEventListener("loadedmetadata", () => { a.currentTime = src.offset; a.play().catch(() => {}); }, { once: true });
  toast("元の音源を再生します（ピアノロールは聴き取った音符）");
});
$("#e-yaml").addEventListener("input", () => E.cur && (E.cur.dirty = true));

async function eCheck(quiet = false) {
  const r = await api("/api/check", { yaml: $("#e-yaml").value }).catch((e) => { toast(e.message, true); throw e; });
  eShow(r.view);
  if (!quiet) toast(r.view.warnings.length ? "警告があります（パート一覧の下）" : "問題ありません ✓");
}

async function ePlay() {
  if (!E.cur) return;
  const mute = $("#e-karaoke").checked ? ["vocal"] : [];
  const r = await busy("音を作っています…（30 秒ほどかかることがあります）", () =>
    api("/api/render", { yaml: $("#e-yaml").value, name: E.cur.name, mute }));
  eShow(r.view);
  const f = r.files;
  const a = $("#e-audio");
  E.offset = 0;
  a.src = "/output/" + encodeURIComponent(f.mp3 || f.wav) + "?t=" + Date.now();
  const dl = (label, file) => file ? h("a", { href: "/output/" + encodeURIComponent(file) + "?dl=1" }, label) : null;
  $("#e-downloads").replaceChildren(h("span", { class: "muted" }, "ダウンロード:"),
    dl("MP3", f.mp3), dl("WAV", f.wav), dl("MIDI", f.midi), dl("楽譜(MusicXML)", f.musicxml), dl("歌詞", f.lyrics));
  try { await a.play(); } catch { /* 自動再生がブロックされた場合 */ }
}
$("#e-play").addEventListener("click", ePlay);
$("#e-check").addEventListener("click", () => eCheck());
$("#e-song").addEventListener("change", async (e) => {
  if (E.cur?.dirty && !confirm("保存していない変更があります。破棄して切り替えますか？")) { e.target.value = E.cur.name; return; }
  eLoad(e.target.value);
});
async function eSave(name) {  // 保存できたら true。失敗（形式エラーなど）は画面に出して false
  try {
    const r = await api("/api/save", { yaml: $("#e-yaml").value, name });
    E.cur.name = r.name; E.cur.dirty = false;
    await refreshSongs(); $("#e-song").value = r.name;
    K.song = null;
    toast(`保存しました（songs/${r.name}.yaml）`);
    eCheck(true);
    return true;
  } catch (e) { toast(e.message, true); return false; }
}
$("#e-save").addEventListener("click", () => E.cur && eSave(E.cur.name));
$("#e-saveas-btn").addEventListener("click", () => {
  const n = $("#e-saveas").value.trim();
  if (!n) return toast("新しい名前を入れてください", true);
  if (!E.cur) E.cur = { name: n, view: null };
  eSave(n);
});
$("#e-delete").addEventListener("click", async () => {
  if (!E.cur || !confirm(`「${E.cur.view.title}」（${E.cur.name}.yaml）を削除しますか？`)) return;
  await api("/api/delete", { name: E.cur.name });
  E.cur = null; await refreshSongs();
  hClear(); pClear();
  if ($("#e-song").value) eLoad($("#e-song").value);
  toast("削除しました");
});
window.addEventListener("resize", debounce(() => drawRoll(-1), 200));

// ---------------- バージョン（履歴） ----------------
const H = { name: null, versions: [], sel: [] };
const fmtAt = (iso) => { const d = new Date(iso); return isNaN(d) ? iso : d.toLocaleString("ja-JP", { dateStyle: "medium", timeStyle: "short" }); };

function hClear() { H.name = null; H.versions = []; H.sel = []; $("#h-list").replaceChildren(); $("#h-diff").replaceChildren(); }
function hOff(message) {
  hClear();
  $("#h-off").textContent = "📜 " + message + "（ほかの機能はふつうに使えます）";
  $("#h-off").hidden = false; $("#h-on").hidden = true;
}
function hOn() { $("#h-off").hidden = true; $("#h-on").hidden = false; }

async function hLoad(name) {
  try {
    const r = await api("/api/history?name=" + encodeURIComponent(name));
    if (r.available === false) return hOff(r.message);
    hOn();
    H.name = name; H.versions = r.versions; H.sel = [];
    hRender();
  } catch (e) { hOff("履歴機能は使えません"); }
}

function hRender() {
  const list = $("#h-list");
  $("#h-diff").replaceChildren();
  if (!H.versions.length) {
    list.replaceChildren(h("li", { class: "muted" }, "まだバージョンがありません。"));
    return;
  }
  list.replaceChildren(...[...H.versions].reverse().map((v) => {
    const cb = h("input", { type: "checkbox", id: "h-v" + v.no });
    cb.checked = H.sel.includes(v.no);
    cb.addEventListener("change", () => {
      H.sel = H.sel.filter((n) => n !== v.no);
      if (cb.checked) { H.sel.push(v.no); if (H.sel.length > 2) H.sel.shift(); }
      hRender(); if (H.sel.length === 2) hDiff();
    });
    return h("li", {}, h("label", { class: "inline", for: "h-v" + v.no }, cb,
      h("b", {}, `バージョン ${v.no}`), h("span", { class: "muted" }, ` ${fmtAt(v.at)}`)),
      v.note ? h("div", { class: "note" }, v.note) : null,
      h("div", { class: "muted" }, v.summary),
      h("div", { class: "vtools" }, h("button", { class: "ghost chip", title: "この時点の内容に戻します（戻したことも新しいバージョンとして残ります）",
        onclick: () => hRestore(v.no) }, "↩ このバージョンに戻す")));
  }));
}

async function hRestore(no) {
  if (!E.cur) return;
  if (!confirm(`バージョン ${no} の内容に戻しますか？\n\n・今の内容がまだバージョンになっていなければ、先に自動で残します\n・戻したことも新しいバージョンとして記録されるので、あとからやり直せます`)) return;
  if (!(await eSave(E.cur.name))) return;  // 作業中の編集を先にファイルへ（失うものが無いように）
  const r = await busy("戻しています…", () => api("/api/version/restore", { name: E.cur.name, no })).catch(() => null);
  if (!r) return;
  if (r.available === false) return hOff(r.message);
  await eLoad(E.cur.name);  // 画面を、戻した内容で読み直す（バージョン一覧も更新される）
  toast(r.message + (r.auto_saved ? `（戻す前の内容は、バージョン ${r.auto_saved} に残しました）` : ""));
}

async function hCompare(a, b) {
  $("#e-audio").pause();
  const mute = $("#e-karaoke").checked ? ["vocal"] : [];
  const rs = await busy("2 つのバージョンの音を作っています…（1 分ほどかかることがあります）", async () => {
    const ra = await api("/api/version/render", { name: H.name, no: a, mute });
    const rb = await api("/api/version/render", { name: H.name, no: b, mute });
    return [ra, rb];
  }).catch(() => null);
  if (!rs) return;
  if (rs.some((r) => r.available === false)) return hOff(rs[0].message);
  const mk = (r, label) => {
    const f = r.files.mp3 || r.files.wav;
    const au = h("audio", { controls: true, preload: "auto", src: "/output/" + encodeURIComponent(f) + "?t=" + Date.now() });
    return { label, au };
  };
  const A = mk(rs[0], `バージョン ${a}`), B = mk(rs[1], `バージョン ${b}`);
  const switchTo = (to, from) => {  // 同じ位置から、もう一方に切り替えて続きを聴く
    const t = from.au.currentTime;
    from.au.pause();
    to.au.currentTime = t;
    to.au.play().catch(() => {});
  };
  const box = h("div", { class: "ab" },
    h("h3", {}, "🎧 聴き比べ"),
    h("p", { class: "hint" }, "再生中に切り替えると、同じ位置から続きが聞けます。"),
    h("div", { class: "row gap wrap" },
      h("button", { class: "primary", onclick: () => switchTo(A, B) }, `${A.label} を聴く`),
      h("button", { class: "primary", onclick: () => switchTo(B, A) }, `${B.label} を聴く`)),
    h("div", { class: "abplayers" },
      h("div", {}, h("div", { class: "muted" }, A.label), A.au), h("div", {}, h("div", { class: "muted" }, B.label), B.au)));
  $("#h-diff").querySelector(".ab")?.remove();
  $("#h-diff").append(box);
}

async function hDiff() {
  const [a, b] = [...H.sel].sort((x, y) => x - y);
  const r = await api(`/api/history/diff?name=${encodeURIComponent(H.name)}&a=${a}&b=${b}`).catch((e) => { toast(e.message, true); throw e; });
  if (r.available === false) return hOff(r.message);
  const box = $("#h-diff");
  const changed = r.sections.filter((s) => s.changed);
  box.replaceChildren(h("h3", {}, `バージョン ${a} → バージョン ${b} の歌詞の違い`),
    h("div", { class: "vtools" }, h("button", { class: "ghost", onclick: () => hCompare(a, b) }, "🎧 この 2 つを聴き比べ")),
    !changed.length ? h("p", { class: "muted" }, "歌詞に違いはありません。") : null,
    ...changed.map((s) => h("div", { class: "dsec" },
      h("b", {}, `【${s.name}】`), s.status === "added" ? h("span", { class: "muted" }, " （このパートが追加されました）") : null,
      s.status === "removed" ? h("span", { class: "muted" }, " （このパートが削除されました）") : null,
      ...s.lines.map((l) => l.type === "change"
        ? h("div", { class: "dl change" }, h("div", { class: "remove" }, "－ " + l.old), h("div", { class: "add" }, "＋ " + l.new))
        : h("div", { class: "dl " + l.type }, (l.type === "add" ? "＋ " : l.type === "remove" ? "－ " : "　 ") + l.text)))));
}

// ---------------- 提案（AI の修正案） ----------------
const P = { name: null, items: [] };
function pClear() { P.name = null; P.items = []; pRender(); }

async function pLoad(name) {
  try {
    const r = await api("/api/proposals?song=" + encodeURIComponent(name));
    P.name = name; P.items = r.proposals;
  } catch { P.name = name; P.items = []; }
  pRender();
}

function pRender() {
  const pending = P.items.filter((x) => x.status === "pending").length;
  const badge = $("#p-count");
  badge.hidden = !pending; badge.textContent = `${pending} 件`;
  $("#p-list").replaceChildren(...(P.items.length ? P.items.map(pItem)
    : [h("li", { class: "muted" }, "提案はありません。")]));
}

function pItem(x) {
  const open = x.status === "pending";
  const box = h("div", { class: "pdetail" });
  const audio = h("div", { class: "pdetail" });
  return h("li", { class: "prop " + x.status },
    h("div", {}, h("b", {}, x.title), " ", h("span", { class: "tag " + x.status }, x.status_label),
      h("span", { class: "muted" }, ` ${fmtAt(x.at)}`)),
    x.reason ? h("div", { class: "note" }, x.reason) : null,
    h("div", { class: "muted" }, "変更: " + x.summary),
    x.warnings.length ? h("div", { class: "pwarn" }, "⚠ " + x.warnings.join(" ／ ")) : null,
    x.stale ? h("div", { class: "pwarn" }, "⚠ この提案を出したあとに、曲が変わっています。そのままでは採用できません。") : null,
    x.status === "adopted" && x.adopted_version ? h("div", { class: "muted" }, `バージョン ${x.adopted_version} として記録しました`) : null,
    h("div", { class: "vtools row gap wrap" },
      h("button", { class: "ghost chip", onclick: () => pDetail(x.id, box) }, "👁 内容を見る"),
      open ? h("button", { class: "ghost chip", onclick: () => pPlay(x.id, audio) }, "🎧 試聴") : null,
      open ? h("button", { class: "primary chip", disabled: x.stale, onclick: () => pAdopt(x) }, "✔ 採用") : null,
      open ? h("button", { class: "ghost chip", onclick: () => pReject(x) }, "✖ 却下") : null),
    box, audio);
}

async function pDetail(id, box) {
  if (box.childElementCount) return box.replaceChildren();  // もう一度押すと閉じる
  const d = await api(`/api/proposal?song=${encodeURIComponent(P.name)}&id=${id}`).catch((e) => { toast(e.message, true); throw e; });
  const changed = d.lyrics.filter((s) => s.changed);
  box.replaceChildren(h("h3", {}, "歌詞の違い（今の曲 → 提案）"),
    !changed.length ? h("p", { class: "muted" }, "歌詞に違いはありません（メロディ・コードなどの変更です）。") : null,
    ...changed.map((s) => h("div", { class: "dsec" },
      h("b", {}, `【${s.name}】`),
      s.status === "added" ? h("span", { class: "muted" }, " （このパートが追加されます）") : null,
      s.status === "removed" ? h("span", { class: "muted" }, " （このパートが削除されます）") : null,
      ...s.lines.map((l) => l.type === "change"
        ? h("div", { class: "dl change" }, h("div", { class: "remove" }, "－ " + l.old), h("div", { class: "add" }, "＋ " + l.new))
        : h("div", { class: "dl " + l.type }, (l.type === "add" ? "＋ " : l.type === "remove" ? "－ " : "　 ") + l.text)))));
}

async function pPlay(id, holder) {
  $("#e-audio").pause();
  const mute = $("#e-karaoke").checked ? ["vocal"] : [];
  const r = await busy("提案の音を作っています…（30 秒ほどかかることがあります）", () =>
    api("/api/proposal/render", { song: P.name, id, mute })).catch(() => null);
  if (!r) return;
  const f = r.files.mp3 || r.files.wav;
  const au = h("audio", { controls: true, autoplay: true, src: "/output/" + encodeURIComponent(f) + "?t=" + Date.now() });
  holder.replaceChildren(h("div", { class: "muted" }, "提案の試聴（曲のファイルは変わりません）"), au);
  au.play().catch(() => {});
}

async function pAdopt(x) {
  if (!E.cur) return;
  if (!confirm(`「${x.title}」を採用しますか？\n\n・曲がこの提案の内容に変わります\n・採用する直前の内容は、先にバージョンとして残します（あとから戻せます）`)) return;
  if (E.cur.dirty) {  // 編集中の内容が、採用で失われないように
    if (!confirm("保存していない編集があります。先に保存してから採用します。よろしいですか？")) return;
    if (!(await eSave(E.cur.name))) return;
  }
  const r = await api("/api/proposal/adopt", { song: P.name, id: x.id }).catch((e) => { toast(e.message, true); return null; });
  if (!r) return pLoad(P.name);  // 失敗（曲が変わっていた等）は、一覧を読み直して状態を見せる
  await eLoad(P.name);  // 画面を、採用した内容で読み直す
  toast(r.message);
}

async function pReject(x) {
  const r = await api("/api/proposal/reject", { song: P.name, id: x.id }).catch((e) => { toast(e.message, true); return null; });
  if (r) toast(r.message);
  pLoad(P.name);
}

$("#h-save").addEventListener("click", async () => {
  if (!E.cur) return toast("曲を選んでください", true);
  if (!(await eSave(E.cur.name))) return;  // 作業中の内容をまず保存してから、バージョンにする（保存できなければ中止）
  const r = await api("/api/version/save", { name: E.cur.name, note: $("#h-note").value }).catch((e) => { toast(e.message, true); throw e; });
  if (r.available === false) return hOff(r.message);
  if (r.saved) $("#h-note").value = "";
  toast(r.message);
  hLoad(E.cur.name);
});

// ====================================================================
//  音楽のきほん
// ====================================================================
async function lUpdate() {
  const r = await api("/api/progressions?key=" + encodeURIComponent($("#l-key").value));
  $("#l-prog").replaceChildren(...r.items.map((g) => h("tr", {}, h("td", {}, g.name), h("td", {}, g.degrees), h("td", {}, g.chords.join(" ")), h("td", {}, g.desc))));
}
$("#l-key").addEventListener("change", lUpdate);

// ---------------- 起動 ----------------
(async function init() {
  for (const t of TONICS) { $("#c-tonic").append(h("option", { value: t }, t)); }
  for (const t of TONICS) for (const m of ["major", "minor"]) $("#l-key").append(h("option", { value: `${t} ${m}` }, `${t} ${m === "major" ? "メジャー" : "マイナー"}`));
  try {
    await loadProgressions();
    applyTemplate("jpop");
    await refreshSongs();
    lUpdate();
  } catch (e) { toast(e.message, true); }
})();
