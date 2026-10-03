/* Sparky in the browser.

   Talks to sparky/web/server.py over /api/*, with the page's token in the
   X-Sparky-Token header. Replies stream as server-sent events, read from
   fetch() because EventSource cannot POST. Model output is drawn by a small
   Markdown renderer that builds DOM nodes and only ever inserts text nodes,
   so nothing a model writes is ever parsed as HTML. No build step, no
   dependencies, no network requests beyond this computer. The saved theme
   is applied earlier, by theme-init.js. */

(function () {
  "use strict";

  const tokenMeta = document.querySelector('meta[name="sparky-token"]');
  const TOKEN = tokenMeta ? tokenMeta.content : "";

  const IMAGE_TYPES = ["image/png", "image/jpeg", "image/gif", "image/webp"];
  const MAX_IMAGE_BYTES = 20 * 1024 * 1024;
  const MAX_IMAGES = 8;
  const MAX_TOOL_OUTPUT = 40000;

  const S = {
    state: null,        // the last /api/state
    streaming: false,
    stopping: false,
    controller: null,
    turn: null,         // the assistant turn being written
    images: [],         // [{media_type, data, url, name}] waiting to be sent
    stick: true,        // keep the newest text in view while it streams
    stopTimer: 0,
  };

  let $log, $main, $input;
  const $ = (id) => document.getElementById(id);

  // ------------------------------------------------------------------ DOM helpers

  function h(tag, attrs, ...kids) {
    const node = document.createElement(tag);
    if (attrs) {
      for (const k of Object.keys(attrs)) {
        const v = attrs[k];
        if (v === false || v === null || v === undefined) continue;
        if (k === "class") node.className = v;
        else if (k === "hidden") node.hidden = true;
        else node.setAttribute(k, v === true ? "" : String(v));
      }
    }
    for (const kid of kids) if (kid !== null && kid !== undefined && kid !== false) node.append(kid);
    return node;
  }

  const SVG_NS = "http://www.w3.org/2000/svg";
  function icon(d, size) {
    const svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("viewBox", "0 0 20 20");
    svg.setAttribute("width", size || 14);
    svg.setAttribute("height", size || 14);
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("focusable", "false");
    const path = document.createElementNS(SVG_NS, "path");
    path.setAttribute("d", d);
    path.setAttribute("fill", "none");
    path.setAttribute("stroke", "currentColor");
    path.setAttribute("stroke-width", "2.4");
    path.setAttribute("stroke-linecap", "round");
    svg.append(path);
    return svg;
  }
  const ICON_X = "M5 5l10 10M15 5L5 15";

  function announce(text) {
    const s = $("status");
    s.textContent = "";
    // a fresh node each time, so repeating the same words is still read out
    requestAnimationFrame(() => { s.textContent = text; });
  }

  // ------------------------------------------------------------------ Markdown

  const md = (function () {
    const FENCE = /^ {0,3}(`{3,}|~{3,})(.*)$/;
    const FENCE_CLOSE = /^ {0,3}(`{3,}|~{3,})[ \t]*$/;
    const HEADING = /^ {0,3}(#{1,6})(?:[ \t]+(.*?))?(?:[ \t]+#+)?[ \t]*$/;
    const HR = /^ {0,3}(?:(?:\*[ \t]*){3,}|(?:-[ \t]*){3,}|(?:_[ \t]*){3,})$/;
    const QUOTE = /^ {0,3}>[ ]?(.*)$/;
    const ITEM = /^( *)([-*+]|\d{1,9}[.)])([ \t]+)(.*)$/;
    const TABLE_SEP = /^ *\|? *:?-+:? *(\| *:?-+:? *)*\|? *$/;
    const ESCAPABLE = "\\`*_{}[]()#+-.!|~<>";
    const WORD = /[\p{L}\p{N}]/u;

    const blank = (l) => !l.trim();
    const indentOf = (l) => l.length - l.replace(/^ +/, "").length;
    const isTable = (l, next) => next !== undefined && l.includes("|") && next.includes("|") && next.includes("-") && TABLE_SEP.test(next);

    function startsBlock(l, next) {
      return FENCE.test(l) || HEADING.test(l) || HR.test(l) || QUOTE.test(l) || ITEM.test(l) || isTable(l, next);
    }

    function render(src) {
      const lines = String(src).replace(/\r\n?/g, "\n").replace(/\u0000/g, "").split("\n")
        .map((l) => l.replace(/^\t+/, (t) => "    ".repeat(t.length)));
      const frag = document.createDocumentFragment();
      blocks(lines, frag);
      return frag;
    }

    function blocks(lines, parent) {
      let i = 0;
      while (i < lines.length) {
        const line = lines[i];
        if (blank(line)) { i++; continue; }
        let m = FENCE.exec(line);
        if (m && !(m[1][0] === "`" && m[2].includes("`"))) {
          const fence = m[1];
          const lang = m[2].trim().split(/\s+/)[0] || "";
          const strip = indentOf(line);
          const body = [];
          let closed = false;
          i++;
          while (i < lines.length) {
            const c = FENCE_CLOSE.exec(lines[i]);
            if (c && c[1][0] === fence[0] && c[1].length >= fence.length) { i++; closed = true; break; }
            body.push(strip ? lines[i].replace(new RegExp("^ {0," + strip + "}"), "") : lines[i]);
            i++;
          }
          // a fence still streaming in has no closing line yet
          if (!closed) while (body.length && !body[body.length - 1].trim()) body.pop();
          parent.append(codeBlock(body.join("\n"), lang));
          continue;
        }
        if ((m = HEADING.exec(line))) {
          const level = m[1].length;
          const node = h("h" + Math.min(level + 2, 6), { class: "md-h" + level });
          inline(m[2] || "", node);
          parent.append(node);
          i++;
          continue;
        }
        if (HR.test(line)) { parent.append(h("hr")); i++; continue; }
        if (QUOTE.test(line)) {
          const inner = [];
          while (i < lines.length && !blank(lines[i])) {
            const q = QUOTE.exec(lines[i]);
            if (q) inner.push(q[1]);
            else if (!startsBlock(lines[i], lines[i + 1])) inner.push(lines[i]);
            else break;
            i++;
          }
          const bq = h("blockquote");
          blocks(inner, bq);
          parent.append(bq);
          continue;
        }
        if (isTable(line, lines[i + 1])) { i = table(lines, i, parent); continue; }
        if (ITEM.test(line)) { i = list(lines, i, parent); continue; }

        const para = [line.trim()];
        i++;
        while (i < lines.length && !blank(lines[i]) && !startsBlock(lines[i], lines[i + 1])) {
          para.push(lines[i].trim());
          i++;
        }
        const p = h("p");
        inline(para.join("\n"), p);
        parent.append(p);
      }
    }

    function list(lines, i, parent) {
      const first = ITEM.exec(lines[i]);
      const ordered = /\d/.test(first[2]);
      const node = h(ordered ? "ol" : "ul");
      if (ordered) {
        const start = parseInt(first[2], 10);
        if (start !== 1) node.setAttribute("start", String(start));
      }
      while (i < lines.length) {
        const m = ITEM.exec(lines[i]);
        if (!m || /\d/.test(m[2]) !== ordered) break;
        const w = m[1].length;
        const gap = m[3].length > 4 ? 1 : m[3].length;
        const col = w + m[2].length + gap;
        const item = [m[3].length > 4 ? m[3].slice(1) + m[4] : m[4]];
        let sawBlank = false;
        i++;
        while (i < lines.length) {
          const l = lines[i];
          if (blank(l)) { item.push(""); sawBlank = true; i++; continue; }
          const ind = indentOf(l);
          const sub = ITEM.test(l);
          if (ind >= col || (sub && ind > w)) {
            item.push(l.slice(Math.min(ind, col)));
            sawBlank = false;
            i++;
            continue;
          }
          if (sub) break;
          if (!sawBlank && !startsBlock(l, lines[i + 1])) { item.push(l.trim()); i++; continue; }
          break;
        }
        while (item.length && item[item.length - 1] === "") item.pop();
        const li = h("li");
        blocks(item, li);
        node.append(li);
        // blank lines before something that is not a sibling item end the list
        if (sawBlank && !(i < lines.length && ITEM.test(lines[i]))) break;
      }
      parent.append(node);
      return i;
    }

    function splitRow(line) {
      let s = line.trim();
      if (s.startsWith("|")) s = s.slice(1);
      if (s.endsWith("|") && !s.endsWith("\\|")) s = s.slice(0, -1);
      const cells = [];
      let cur = "";
      for (let k = 0; k < s.length; k++) {
        if (s[k] === "\\" && s[k + 1] === "|") { cur += "|"; k++; }
        else if (s[k] === "|") { cells.push(cur.trim()); cur = ""; }
        else cur += s[k];
      }
      cells.push(cur.trim());
      return cells;
    }

    function table(lines, i, parent) {
      const head = splitRow(lines[i]);
      const aligns = splitRow(lines[i + 1]).map((c) =>
        c.startsWith(":") && c.endsWith(":") ? "center" : c.endsWith(":") ? "right" : "");
      const cell = (tag, text, k) => {
        const node = h(tag, aligns[k] ? { class: "al-" + aligns[k] } : null);
        inline(text || "", node);
        return node;
      };
      const thead = h("thead", null, h("tr", null, ...head.map((c, k) => cell("th", c, k))));
      const tbody = h("tbody");
      i += 2;
      while (i < lines.length && !blank(lines[i]) && lines[i].includes("|")) {
        const cells = splitRow(lines[i]);
        tbody.append(h("tr", null, ...head.map((_, k) => cell("td", cells[k], k))));
        i++;
      }
      parent.append(h("div", { class: "table-wrap" }, h("table", null, thead, tbody)));
      return i;
    }

    // Closing delimiter for emphasis, or -1. A run of delimiters closes from
    // its end, so ***both*** nests cleanly; code spans are skipped over.
    function findClose(src, from, mk) {
      const c = mk[0];
      let j = from;
      while (j < src.length) {
        const ch = src[j];
        if (ch === "\\") { j += 2; continue; }
        if (ch === "`") {
          let run = 1;
          while (src[j + run] === "`") run++;
          const end = src.indexOf("`".repeat(run), j + run);
          j = end === -1 ? j + run : end + run;
          continue;
        }
        if (ch === c) {
          let r = 1;
          while (src[j + r] === c) r++;
          const fits = mk.length === 2 ? r >= 2 : r !== 2;
          if (fits && j > from && !/\s/.test(src[j - 1])) {
            const pos = j + r - mk.length;
            const next = src[pos + mk.length];
            if (c !== "_" || !next || !WORD.test(next)) return pos;
          }
          j += r;
          continue;
        }
        j++;
      }
      return -1;
    }

    function matching(src, from, open, close) {
      let depth = 0;
      for (let k = from; k < src.length; k++) {
        const ch = src[k];
        if (ch === "\\") { k++; continue; }
        if (ch === "\n" && open === "(") return -1;
        if (ch === open) depth++;
        else if (ch === close) { if (depth === 0) return k; depth--; }
      }
      return -1;
    }

    function link(href, kids) {
      return h("a", { href: href, target: "_blank", rel: "noopener noreferrer" }, ...kids);
    }

    function inline(src, parent) {
      let buf = "";
      const flush = () => { if (buf) { parent.append(buf); buf = ""; } };
      const n = src.length;
      let i = 0;
      while (i < n) {
        const c = src[i];
        if (c === "\\" && i + 1 < n && ESCAPABLE.includes(src[i + 1])) { buf += src[i + 1]; i += 2; continue; }
        if (c === "\n") { flush(); parent.append(h("br")); i++; continue; }

        if (c === "`") {
          let run = 1;
          while (src[i + run] === "`") run++;
          let j = i + run;
          let close = -1;
          while (j < n) {
            if (src[j] === "`") {
              let r = 1;
              while (src[j + r] === "`") r++;
              if (r === run) { close = j; break; }
              j += r;
            } else j++;
          }
          if (close === -1) { buf += src.slice(i, i + run); i += run; continue; }
          let code = src.slice(i + run, close).replace(/\n/g, " ");
          if (code.length > 2 && code[0] === " " && code[code.length - 1] === " " && code.trim()) code = code.slice(1, -1);
          flush();
          parent.append(h("code", null, code));
          i = close + run;
          continue;
        }

        if (c === "*" || c === "_" || (c === "~" && src[i + 1] === "~")) {
          const dbl = src[i + 1] === c;
          const mk = dbl ? c + c : c;
          const prev = i > 0 ? src[i - 1] : " ";
          const after = src[i + mk.length];
          if (after && !/\s/.test(after) && !(c === "_" && WORD.test(prev))) {
            const close = findClose(src, i + mk.length, mk);
            if (close > i + mk.length) {
              flush();
              const node = h(c === "~" ? "del" : dbl ? "strong" : "em");
              inline(src.slice(i + mk.length, close), node);
              parent.append(node);
              i = close + mk.length;
              continue;
            }
          }
          buf += mk;
          i += mk.length;
          continue;
        }

        if (c === "[") {
          const endLabel = matching(src, i + 1, "[", "]");
          if (endLabel !== -1 && src[endLabel + 1] === "(") {
            const endTarget = matching(src, endLabel + 2, "(", ")");
            if (endTarget !== -1) {
              const image = buf.endsWith("!");
              if (image) buf = buf.slice(0, -1);
              let target = src.slice(endLabel + 2, endTarget).trim().split(/\s+/)[0] || "";
              if (target.startsWith("<") && target.endsWith(">")) target = target.slice(1, -1);
              flush();
              const label = h("span");
              if (image) label.append("Image: ");
              inline(src.slice(i + 1, endLabel), label);
              // only web links become links; anything else stays as its text
              parent.append(/^https?:\/\//i.test(target) ? link(target, [...label.childNodes]) : label);
              i = endTarget + 1;
              continue;
            }
          }
        }

        if ((c === "h" || c === "H") && /^https?:\/\//i.test(src.slice(i, i + 8)) && (i === 0 || !WORD.test(src[i - 1]))) {
          const found = /^https?:\/\/[^\s<>"'`]+/i.exec(src.slice(i));
          let url = found ? found[0] : "";
          for (;;) {
            if (/[.,;:!?*_~]$/.test(url)) { url = url.slice(0, -1); continue; }
            if (url.endsWith(")") && (url.match(/\(/g) || []).length < (url.match(/\)/g) || []).length) { url = url.slice(0, -1); continue; }
            break;
          }
          if (url.length > 8) {
            flush();
            parent.append(link(url, [url]));
            i += url.length;
            continue;
          }
        }

        buf += c;
        i++;
      }
      flush();
    }

    function codeBlock(code, lang) {
      const copy = h("button", { type: "button", class: "copy", "aria-label": lang ? "Copy " + lang + " code" : "Copy code" }, "Copy");
      copy.addEventListener("click", () => copyText(code, copy));
      return h("div", { class: "code-block" },
        h("div", { class: "code-bar" }, h("span", { class: "code-lang" }, lang || "code"), copy),
        h("pre", null, h("code", lang ? { "data-lang": lang } : null, code)));
    }

    return { render, inline };
  })();

  async function copyText(text, btn) {
    let ok = false;
    try {
      await navigator.clipboard.writeText(text);
      ok = true;
    } catch (e) {
      const ta = h("textarea", { class: "visually-hidden", readonly: true, "aria-hidden": "true" });
      ta.value = text;
      document.body.append(ta);
      ta.select();
      try { ok = document.execCommand("copy"); } catch (e2) { ok = false; }
      ta.remove();
    }
    btn.textContent = ok ? "Copied" : "Copy failed";
    announce(ok ? "Copied to the clipboard" : "Could not copy");
    setTimeout(() => { btn.textContent = "Copy"; }, 1600);
  }

  // ------------------------------------------------------------------ server

  async function errorText(res) {
    if (res.status === 403) {
      return "The server did not accept this page's access token. Open Sparky again from the address it printed in the terminal.";
    }
    if (res.status === 409) {
      return "Sparky is still writing another reply. Wait for it to finish, or stop it, then send again.";
    }
    let msg = "";
    try {
      const body = await res.text();
      try {
        const j = JSON.parse(body);
        msg = j.error || j.message || body;
      } catch (e) { msg = body; }
    } catch (e) { /* no body */ }
    msg = String(msg || res.statusText || "Request failed").trim();
    return msg + " (HTTP " + res.status + ")";
  }

  async function api(path, body) {
    const opts = { method: body === undefined ? "GET" : "POST", headers: { "X-Sparky-Token": TOKEN } };
    if (body !== undefined) {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body);
    }
    let res;
    try {
      res = await fetch(path, opts);
    } catch (e) {
      throw new Error("Could not reach Sparky. Is its terminal window still open?");
    }
    if (!res.ok) throw new Error(await errorText(res));
    const type = res.headers.get("Content-Type") || "";
    return type.includes("json") ? res.json() : null;
  }

  // ------------------------------------------------------------------ state and controls

  const modelLabel = (m) => (m && (m.label || m.name)) || "the model";
  const modelByName = (name) => (S.state && (S.state.models || []).find((m) => m.name === name)) || (name ? { name } : null);
  const currentModel = () => (S.state && (S.state.models || []).find((m) => m.name === S.state.model)) || (S.state ? { name: S.state.model } : null);
  const currentMode = () => (S.state && (S.state.modes || []).find((m) => m.id === S.state.mode)) || null;

  function sizeText(gb) {
    const n = Number(gb);
    if (!isFinite(n) || n <= 0) return "";
    return (n < 10 ? n.toFixed(1) : n.toFixed(0)) + " GB";
  }

  function applyState(st) {
    S.state = st;
    const models = Array.isArray(st.models) ? st.models : [];
    const sel = $("model");
    sel.replaceChildren();
    for (const m of models) {
      const bits = [sizeText(m.size_gb), m.speed || "", m.vision ? "sees images" : ""].filter(Boolean).join(", ");
      const label = modelLabel(m) + (bits ? " (" + bits + ")" : "");
      sel.append(h("option", { value: m.name, title: m.note || m.name }, label));
    }
    if (st.model && !models.some((m) => m.name === st.model)) sel.append(h("option", { value: st.model }, st.model));
    if (!sel.options.length) sel.append(h("option", { value: "" }, "No models installed"));
    sel.value = st.model || "";
    const cur = models.find((m) => m.name === st.model);
    sel.title = cur && cur.note ? cur.note : st.model ? "Model: " + st.model : "";

    const modes = Array.isArray(st.modes) ? st.modes : [];
    const msel = $("mode");
    msel.replaceChildren();
    for (const m of modes) msel.append(h("option", { value: m.id, title: m.blurb || "" }, m.label || m.id));
    if (!msel.options.length) msel.append(h("option", { value: st.mode || "" }, st.mode || "Chat"));
    msel.value = st.mode || "";
    const mode = currentMode();
    msel.title = mode && mode.blurb ? mode.blurb : "";

    // a model that cannot think gets the toggle switched off and greyed out
    const canThink = st.think_supported !== false;
    const think = $("think");
    if (think.dataset.title === undefined) think.dataset.title = think.title;
    think.disabled = !canThink;
    think.title = canThink ? think.dataset.title : modelLabel(cur || { name: st.model }) + " cannot think aloud before answering.";
    setThink(!!st.think && canThink);
    $("yolo").hidden = !st.yolo;
    $("version").textContent = st.version ? "Sparky " + st.version : "";
    updateControls();
    updateEmptyText();
    updateVisionHint();
  }

  function updateControls() {
    const models = (S.state && S.state.models) || [];
    $("model").disabled = S.streaming || !models.length;
    $("mode").disabled = S.streaming || !S.state;
  }

  function setThink(on) {
    $("think").setAttribute("aria-pressed", on ? "true" : "false");
  }

  async function loadState(withHistory) {
    let st;
    try {
      st = await api("/api/state");
    } catch (e) {
      $log.replaceChildren();
      addNote($log, "error", e.message);
      updateEmpty();
      return null;
    }
    applyState(st || {});
    if (withHistory) {
      renderHistory(Array.isArray(st.history) ? st.history : []);
      if (st.busy && !S.streaming) addBusyNote();
    }
    return st;
  }

  async function refreshState() {
    try { applyState(await api("/api/state")); } catch (e) { /* the controls keep their last values */ }
  }

  // The settings endpoints answer with the full state; anything else means
  // reading it again.
  async function applyResult(st) {
    if (st && typeof st === "object" && Array.isArray(st.models)) applyState(st);
    else await refreshState();
  }

  function updateEmptyText() {
    const st = S.state || {};
    const sub = $("empty-sub");
    if (!(st.models || []).length) {
      sub.textContent = "No models are installed yet. In the terminal, run sparky.cmd models recommend, then sparky.cmd models add with one of the names it suggests.";
      return;
    }
    const mode = currentMode();
    const parts = [modelLabel(currentModel()) + (mode ? ", " + (mode.label || mode.id) + " mode." : ".")];
    if (mode && mode.blurb) parts.push(mode.blurb.replace(/\.?$/, "."));
    parts.push("It runs on this computer, so nothing you type leaves it.");
    sub.textContent = parts.join(" ");
  }

  function updateEmpty() {
    $("empty").hidden = $log.children.length > 0;
  }

  // A small line in the conversation recording a change of model or mode.
  function addSys(text) {
    if (!$log.children.length) return;
    $log.append(h("p", { class: "sys" }, text));
    scrollToEnd(true);
  }

  // ------------------------------------------------------------------ the conversation

  function scrollToEnd(force) {
    if (force || S.stick) $main.scrollTop = $main.scrollHeight;
  }

  function addNote(parent, kind, text, extra) {
    const label = kind === "error" ? "Error" : "Note";
    const note = h("div", { class: "note note-" + kind },
      h("p", null, h("strong", null, label + ": "), String(text || "")), extra || null);
    parent.append(note);
    updateEmpty();
    scrollToEnd();
    return note;
  }

  function addUser(text, images) {
    const bubble = h("div", { class: "bubble" }, h("span", { class: "visually-hidden" }, "You: "));
    if (images && images.length) {
      bubble.append(h("div", { class: "bubble-images" },
        ...images.map((im, k) => h("img", { src: im.url, alt: im.name ? "Attached: " + im.name : "Attached image " + (k + 1) }))));
    }
    if (text) bubble.append(h("p", { class: "bubble-text" }, text));
    $log.append(h("article", { class: "msg msg-user" }, bubble));
    updateEmpty();
  }

  function newTurn() {
    const body = h("div", { class: "msg-body" });
    const foot = h("div", { class: "msg-foot" });
    const el = h("article", { class: "msg msg-bot", "aria-busy": "true" },
      h("span", { class: "tile tile-small", "aria-hidden": "true" }, h("img", { src: "/static/icon.svg", width: 22, height: 22, alt: "" })),
      h("div", { class: "msg-main" }, h("span", { class: "visually-hidden" }, "Sparky: "), body, foot));
    $log.append(el);
    updateEmpty();
    return {
      el, body, foot,
      text: null, reason: null, spin: null, stats: null,
      tools: [], confirms: [],
      hasText: false, ended: false, raf: 0, dirty: new Set(),
      tokens: 0, seconds: 0,
    };
  }

  // New blocks go before the "thinking" line, which always stays last.
  function place(t, node) {
    t.body.insertBefore(node, t.spin && t.spin.parentNode === t.body ? t.spin : null);
  }

  function showSpinner(t, label) {
    if (!t.spin) {
      t.spin = h("div", { class: "working" },
        h("span", { class: "pix", "aria-hidden": "true" }, h("i"), h("i"), h("i")),
        h("span", { class: "working-text" }));
    }
    t.spin.lastChild.textContent = label;
    t.body.append(t.spin);
    scrollToEnd();
  }

  function hideSpinner(t) {
    if (t.spin) t.spin.remove();
  }

  function schedule(t, seg) {
    t.dirty.add(seg);
    if (!t.raf) t.raf = requestAnimationFrame(() => flushTurn(t));
  }

  function flushTurn(t) {
    if (t.raf) cancelAnimationFrame(t.raf);
    t.raf = 0;
    for (const seg of t.dirty) renderSeg(seg);
    t.dirty.clear();
    scrollToEnd();
  }

  function renderSeg(seg) {
    if (seg.kind === "text") seg.el.replaceChildren(md.render(seg.src));
    else seg.pre.textContent = seg.src.replace(/^\s+/, "").replace(/\s+$/, "");
  }

  function appendText(t, s) {
    if (!s) return;
    if (t.reason) closeReason(t);
    if (!t.text) {
      t.text = { kind: "text", el: h("div", { class: "md" }), src: "" };
      place(t, t.text.el);
    }
    t.text.src += s;
    if (s.trim()) t.hasText = true;
    schedule(t, t.text);
  }

  function closeText(t) {
    if (!t.text) return;
    renderSeg(t.text);
    t.dirty.delete(t.text);
    t.text = null;
  }

  function wordCount(s) {
    const n = (s.trim().match(/\S+/g) || []).length;
    return n === 1 ? "1 word" : n + " words";
  }

  function appendReason(t, s) {
    if (!s) return;
    if (t.text) closeText(t);
    if (!t.reason) {
      const pre = h("div", { class: "reason-text" });
      const state = h("span", { class: "reason-state" }, "in progress");
      const det = h("details", { class: "reason is-live" }, h("summary", null, h("span", null, "Reasoning"), state), pre);
      place(t, det);
      t.reason = { kind: "reason", el: det, pre, state, src: "" };
      t.hasReason = true;
    }
    t.reason.src += s;
    schedule(t, t.reason);
  }

  function closeReason(t) {
    const r = t.reason;
    if (!r) return;
    renderSeg(r);
    t.dirty.delete(r);
    r.el.classList.remove("is-live");
    r.state.textContent = wordCount(r.src);
    t.reason = null;
  }

  function closeSegments(t) {
    closeText(t);
    closeReason(t);
  }

  function stringify(v) {
    if (v === null || v === undefined) return "";
    if (typeof v === "string") return v;
    try { return JSON.stringify(v, null, 2); } catch (e) { return String(v); }
  }

  // One line saying what a tool was asked to do: the command, the path, the
  // pattern, or failing those the first short string in its input.
  function toolSummary(input) {
    if (input === null || input === undefined) return "";
    if (typeof input !== "object") return String(input).split("\n")[0];
    for (const k of ["command", "cmd", "path", "file_path", "file", "pattern", "query", "url", "name"]) {
      if (typeof input[k] === "string" && input[k]) {
        let s = input[k].split("\n")[0];
        if (k === "pattern" && typeof input.path === "string" && input.path) s += "  in " + input.path;
        return s;
      }
    }
    for (const v of Object.values(input)) if (typeof v === "string" && v) return v.split("\n")[0];
    const json = stringify(input);
    return json === "{}" ? "" : json.replace(/\s+/g, " ");
  }

  function addTool(t, ev) {
    const summary = toolSummary(ev.input);
    const state = h("span", { class: "tool-state" }, "running");
    const out = h("pre", { class: "tool-pre" });
    const outLabel = h("span", null, "Output");
    const det = h("details", { class: "tool-out", hidden: true }, h("summary", null, outLabel), out);
    const card = h("div", { class: "tool is-running" },
      h("div", { class: "tool-head" },
        h("span", { class: "tool-dot", "aria-hidden": "true" }),
        h("code", { class: "tool-name" }, String(ev.name || "tool")),
        h("span", { class: "tool-sum", title: summary || null }, summary),
        state),
      det);
    place(t, card);
    const tool = { name: ev.name, card, state, det, out, outLabel, done: false };
    t.tools.push(tool);
    scrollToEnd();
    return tool;
  }

  function finishTool(t, ev) {
    const open = t.tools.filter((x) => !x.done);
    const tool = open.reverse().find((x) => x.name === ev.name) || open[0] || addTool(t, { name: ev.name });
    tool.done = true;
    tool.card.classList.remove("is-running");
    let text = stringify(ev.output);
    if (text.length > MAX_TOOL_OUTPUT) text = text.slice(0, MAX_TOOL_OUTPUT) + "\n\n[cut here: " + (text.length - MAX_TOOL_OUTPUT) + " more characters]";
    if (text.trim()) {
      const lines = text.replace(/\n+$/, "").split("\n").length;
      tool.out.textContent = text;
      tool.outLabel.textContent = "Output, " + (lines === 1 ? "1 line" : lines + " lines");
      tool.det.hidden = false;
      tool.state.textContent = /^error\b/i.test(text.trim()) ? "failed" : "done";
      if (tool.state.textContent === "failed") tool.card.classList.add("is-failed");
    } else {
      tool.state.textContent = "done, no output";
    }
    scrollToEnd();
  }

  function addConfirm(t, ev) {
    const run = h("button", { type: "button", class: "key key-primary" }, "Run");
    const skip = h("button", { type: "button", class: "key" }, "Don't run");
    const actions = h("div", { class: "confirm-actions" }, run, skip);
    const result = h("p", { class: "confirm-result", hidden: true });
    const card = h("div", { class: "confirm", role: "group", "aria-label": "A command is waiting for your approval" },
      h("p", { class: "confirm-title" }, "Sparky wants to run this command:"),
      h("pre", { class: "confirm-cmd" }, h("code", null, String(ev.command || ""))),
      actions, result);
    const entry = { card, actions, result, answered: false };
    const answer = async (approved) => {
      run.disabled = skip.disabled = true;
      try {
        await api("/api/confirm", { id: ev.id, approved: approved });
        entry.answered = true;
        actions.remove();
        result.textContent = approved ? "You let it run." : "You chose not to run it.";
        result.hidden = false;
        card.classList.add(approved ? "is-yes" : "is-no");
        $input.focus();
      } catch (e) {
        run.disabled = skip.disabled = false;
        result.textContent = "Your answer did not reach Sparky: " + e.message;
        result.hidden = false;
      }
    };
    run.addEventListener("click", () => answer(true));
    skip.addEventListener("click", () => answer(false));
    // The approval belongs to the shell tool that asked for it, so it sits
    // inside that tool's card, above where the output will appear.
    const tool = t.tools.filter((x) => !x.done).pop();
    if (tool) tool.card.insertBefore(card, tool.det);
    else place(t, card);
    t.confirms.push(entry);
    announce("A command is waiting for your approval.");
    scrollToEnd(true);
  }

  function addStats(t, ev) {
    t.tokens += Number(ev.tokens) || 0;
    t.seconds += Number(ev.seconds) || 0;
    const tps = t.seconds > 0 ? t.tokens / t.seconds : Number(ev.tps);
    const parts = [];
    if (ev.model) parts.push(String(ev.model));
    if (t.tokens) parts.push(t.tokens + " tokens");
    // a rate measured over a single token says nothing
    if (t.tokens > 1 && isFinite(tps) && tps > 0) parts.push(tps.toFixed(1) + " tokens per second");
    if (!parts.length) return;
    if (!t.stats) {
      t.stats = h("p", { class: "stats" });
      t.foot.prepend(t.stats);
    }
    t.stats.textContent = parts.join(" \u00b7 ");
  }

  function onEvent(t, ev) {
    switch (ev.type) {
      case "thinking":
        showSpinner(t, modelLabel(ev.model ? modelByName(ev.model) : currentModel()) + " is thinking");
        break;
      case "delta":
        hideSpinner(t);
        appendText(t, ev.text || "");
        break;
      case "think_delta":
        hideSpinner(t);
        appendReason(t, ev.text || "");
        break;
      case "tool_start":
        hideSpinner(t);
        closeSegments(t);
        addTool(t, ev);
        break;
      case "tool_result":
        finishTool(t, ev);
        break;
      case "confirm":
        hideSpinner(t);
        closeSegments(t);
        addConfirm(t, ev);
        break;
      case "notice":
        closeSegments(t);
        addNote(t.body, "notice", ev.text);
        if (t.spin && t.spin.parentNode) t.body.append(t.spin);
        break;
      case "stats":
        addStats(t, ev);
        break;
      case "done":
        if (!t.hasText && typeof ev.text === "string" && ev.text.trim()) appendText(t, ev.text);
        if (ev.stopped) t.stopped = true;
        t.ended = true;
        return true;
      case "error":
        hideSpinner(t);
        closeSegments(t);
        addNote(t.body, "error", ev.message || ev.text || "Something went wrong.");
        t.failed = true;
        break;
      default:
        break;
    }
    return false;
  }

  // One SSE event block: its data lines joined, parsed as JSON. A named
  // `event:` field fills in a missing type.
  function parseEvent(block) {
    const data = [];
    let name = "";
    for (const line of block.split(/\r?\n/)) {
      if (line.startsWith("data:")) data.push(line.slice(line[5] === " " ? 6 : 5));
      else if (line.startsWith("event:")) name = line.slice(6).trim();
    }
    if (!data.length) return null;
    let ev;
    try { ev = JSON.parse(data.join("\n")); } catch (e) { return null; }
    if (!ev || typeof ev !== "object") return null;
    if (!ev.type && name) ev.type = name;
    return ev;
  }

  async function stream(payload) {
    S.stopping = false;
    setStreaming(true);
    const t = S.turn = newTurn();
    showSpinner(t, "Waiting for " + modelLabel(currentModel()));
    S.stick = true;
    scrollToEnd(true);
    S.controller = new AbortController();
    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "X-Sparky-Token": TOKEN, "Content-Type": "application/json", Accept: "text/event-stream" },
        body: JSON.stringify(payload),
        signal: S.controller.signal,
      });
      if (!res.ok) throw new Error(await errorText(res));
      if (!res.body) throw new Error("This browser cannot read a streamed reply.");
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      let finished = false;
      while (!finished) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        let m;
        while (!finished && (m = /\r?\n\r?\n/.exec(buf))) {
          const ev = parseEvent(buf.slice(0, m.index));
          buf = buf.slice(m.index + m[0].length);
          if (ev && onEvent(t, ev)) finished = true;
        }
      }
      if (!finished) {
        buf += decoder.decode();
        const ev = buf.trim() ? parseEvent(buf) : null;
        if (ev) onEvent(t, ev);
      }
      if (finished) reader.cancel().catch(() => {});
    } catch (e) {
      if (e && e.name === "AbortError") {
        if (!S.stopping) addNote(t.body, "error", "The connection to Sparky closed.");
      } else {
        hideSpinner(t);
        closeSegments(t);
        addNote(t.body, "error", e && e.message ? e.message : String(e));
        t.failed = true;
      }
    } finally {
      endTurn(t);
    }
  }

  function endTurn(t) {
    clearTimeout(S.stopTimer);
    hideSpinner(t);
    closeSegments(t);
    flushTurn(t);
    const stopped = S.stopping || t.stopped;
    for (const tool of t.tools) {
      if (tool.done) continue;
      tool.card.classList.remove("is-running");
      tool.state.textContent = stopped ? "stopped" : "no result";
    }
    for (const c of t.confirms) {
      if (c.answered) continue;
      c.actions.remove();
      c.result.textContent = "Not run. The reply ended before you answered.";
      c.result.hidden = false;
      c.card.classList.add("is-no");
    }
    if (stopped) t.foot.append(h("p", { class: "stopped" }, "Stopped."));
    else if (!t.hasText && !t.tools.length && !t.failed && !t.body.querySelector(".note")) {
      t.foot.append(h("p", { class: "stopped" }, t.hasReason
        ? "No answer: the model spent the whole reply reasoning. Ask again, or turn Thinking off."
        : "No reply."));
    }
    t.el.setAttribute("aria-busy", "false");
    S.turn = null;
    S.controller = null;
    S.stopping = false;
    setStreaming(false);
    scrollToEnd();
    // the server may have switched model (a fallback), so read the settings again
    refreshState();
  }

  function setStreaming(on) {
    S.streaming = on;
    document.body.classList.toggle("is-streaming", on);
    const send = $("send");
    send.classList.toggle("key-primary", !on);
    send.classList.toggle("key-stop", on);
    send.disabled = false;
    updateControls();
  }

  async function stop() {
    if (!S.streaming || S.stopping) return;
    S.stopping = true;
    $("send").disabled = true;
    announce("Stopping the reply");
    try {
      await api("/api/stop", {});
    } catch (e) { /* falls through to closing the connection */ }
    // the server ends the stream itself; if it does not, close it from here
    clearTimeout(S.stopTimer);
    S.stopTimer = setTimeout(() => { if (S.streaming && S.controller) S.controller.abort(); }, 4000);
  }

  function waitIdle(ms) {
    return new Promise((resolve) => {
      const until = Date.now() + ms;
      (function check() {
        if (!S.streaming || Date.now() > until) resolve();
        else setTimeout(check, 80);
      })();
    });
  }

  function renderHistory(history) {
    $log.replaceChildren();
    for (const item of history) {
      if (!item || typeof item.text !== "string") continue;
      if (item.role === "user") addUser(item.text, []);
      else if (item.role === "assistant") {
        const t = newTurn();
        appendText(t, item.text);
        closeText(t);
        t.el.setAttribute("aria-busy", "false");
      }
    }
    updateEmpty();
    S.stick = true;
    scrollToEnd(true);
  }

  function addBusyNote() {
    const btn = h("button", { type: "button", class: "key key-small" }, "Stop it");
    const note = addNote($log, "notice",
      "Sparky is still writing a reply that was started before this page loaded. Wait for it to finish, or stop it.", btn);
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      try { await api("/api/stop", {}); } catch (e) { /* reloaded below either way */ }
      setTimeout(() => { note.remove(); loadState(true); }, 800);
    });
  }

  // ------------------------------------------------------------------ sending

  async function send() {
    if (S.streaming) return;
    const text = $input.value.replace(/^\s*\n/, "").replace(/\s+$/, "");
    const images = S.images.slice();
    if (!text.trim() && !images.length) return;
    if (!images.length && /^\/\S/.test(text) && runCommand(text.trim())) {
      $input.value = "";
      autosize();
      return;
    }
    // sent before the first state arrived: wait for it rather than wrongly
    // reporting that there is no model
    if (!S.state && S.loading) {
      try { await S.loading; } catch (e) { /* reported by loadState */ }
    }
    if (!(S.state && (S.state.models || []).length)) {
      addNote($log, "error", "There is no model to answer yet. Install one first: sparky.cmd models add <name> in the terminal.");
      return;
    }
    addUser(text, images);
    $input.value = "";
    autosize();
    S.images = [];
    renderThumbs();
    await stream({ text: text, images: images.map((im) => ({ media_type: im.media_type, data: im.data })) });
  }

  const HELP = [
    "Commands you can type here:",
    "",
    "- `/model` lists the models; `/model name` switches to one",
    "- `/mode` lists the modes; `/mode name` switches (chat, code, write, study)",
    "- `/think` turns thinking on or off",
    "- `/clear` starts a new chat",
    "",
    "Anything else that starts with a slash, such as `/pull` or `/context`, is sent to Sparky as you typed it.",
    "",
    "Enter sends, Shift+Enter adds a line, Esc stops a reply. Attach images with the picture button, by pasting them, or by dropping them on the page.",
  ].join("\n");

  function addLocal(markdown) {
    const box = h("div", { class: "note note-local" });
    box.append(md.render(markdown));
    $log.append(box);
    updateEmpty();
    scrollToEnd(true);
  }

  function findByName(list, arg, keys) {
    const q = arg.toLowerCase();
    const val = (x, k) => String(x[k] || "").toLowerCase();
    return list.find((x) => keys.some((k) => val(x, k) === q)) ||
      list.find((x) => keys.some((k) => val(x, k).startsWith(q)));
  }

  // Commands with their own endpoint are handled here; the rest go to the server.
  function runCommand(text) {
    const parts = text.slice(1).split(/\s+/);
    const cmd = parts[0].toLowerCase();
    const arg = parts.slice(1).join(" ").trim();
    const st = S.state || {};
    switch (cmd) {
      case "help":
      case "?":
        addLocal(HELP);
        return true;
      case "clear":
      case "new":
        newChat();
        return true;
      case "think":
        $("think").click();
        return true;
      case "models":
      case "model": {
        const models = st.models || [];
        if (!arg) {
          addLocal(models.length
            ? "Models on this stick:\n\n" + models.map((m) => "- `" + m.name + "` " + modelLabel(m) + (sizeText(m.size_gb) ? ", " + sizeText(m.size_gb) : "") + (m.name === st.model ? " (in use)" : "")).join("\n")
            : "No models are installed yet.");
          return true;
        }
        const hit = findByName(models, arg, ["name", "label"]);
        if (!hit) { addNote($log, "error", "No installed model is called " + arg + ". Type /model to see the list."); return true; }
        $("model").value = hit.name;
        $("model").dispatchEvent(new Event("change"));
        return true;
      }
      case "mode": {
        const modes = st.modes || [];
        if (!arg) {
          addLocal("Modes:\n\n" + modes.map((m) => "- **" + (m.label || m.id) + "**" + (m.blurb ? ": " + m.blurb : "") + (m.id === st.mode ? " (in use)" : "")).join("\n"));
          return true;
        }
        const hit = findByName(modes, arg, ["id", "label"]);
        if (!hit) { addNote($log, "error", "There is no mode called " + arg + ". Type /mode to see them."); return true; }
        $("mode").value = hit.id;
        $("mode").dispatchEvent(new Event("change"));
        return true;
      }
      case "img":
      case "paste":
      case "v":
        addLocal("In the browser, attach images with the picture button next to the message box, paste them, or drop them on the page.");
        return true;
      case "quit":
      case "exit":
        addLocal("Close this tab when you are done. Sparky keeps running in its terminal window until you press Ctrl-C there.");
        return true;
      default:
        return false;
    }
  }

  async function newChat() {
    if (S.streaming) {
      await stop();
      await waitIdle(5000);
    }
    try {
      await applyResult(await api("/api/clear", {}));
    } catch (e) {
      addNote($log, "error", "Could not start a new chat. " + e.message);
      return;
    }
    $log.replaceChildren();
    updateEmpty();
    announce("New chat");
    $input.focus();
  }

  // ------------------------------------------------------------------ images

  function autosize() {
    $input.style.height = "auto";
    const max = Math.max(120, Math.round(window.innerHeight * 0.4));
    $input.style.height = Math.min($input.scrollHeight, max) + "px";
    $input.style.overflowY = $input.scrollHeight > max ? "auto" : "hidden";
  }

  function readAsBase64(file) {
    return new Promise((resolve, reject) => {
      const r = new FileReader();
      r.onload = () => {
        const s = String(r.result);
        resolve(s.slice(s.indexOf(",") + 1));
      };
      r.onerror = () => reject(r.error || new Error("could not read the file"));
      r.readAsDataURL(file);
    });
  }

  // Models read PNG, JPEG, GIF and WebP. Anything else the browser can draw
  // (BMP, AVIF, some clipboard formats) is redrawn as a PNG first.
  async function toSupported(file) {
    if (IMAGE_TYPES.includes(file.type)) return file;
    const bmp = await createImageBitmap(file);
    const canvas = h("canvas", { width: bmp.width, height: bmp.height });
    canvas.getContext("2d").drawImage(bmp, 0, 0);
    const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/png"));
    if (!blob) throw new Error("could not convert it");
    const base = (file.name || "image").replace(/\.[^.]+$/, "");
    return new File([blob], base + ".png", { type: "image/png" });
  }

  async function addFiles(fileList) {
    const files = Array.from(fileList || []);
    const problems = [];
    for (const raw of files) {
      if (!raw.type || !raw.type.startsWith("image/")) { problems.push((raw.name || "That file") + " is not an image."); continue; }
      if (S.images.length >= MAX_IMAGES) { problems.push("At most " + MAX_IMAGES + " images go with one message."); break; }
      if (raw.size > MAX_IMAGE_BYTES) { problems.push((raw.name || "That image") + " is larger than 20 MB."); continue; }
      try {
        const file = await toSupported(raw);
        const data = await readAsBase64(file);
        S.images.push({ media_type: file.type, data, url: URL.createObjectURL(file), name: raw.name || "" });
      } catch (e) {
        problems.push("Could not read " + (raw.name || "that image") + ": " + (e && e.message ? e.message : e));
      }
    }
    renderThumbs();
    if (problems.length) addNote($log, "error", problems.join(" "));
    else if (files.length) announce(files.length === 1 ? "Image attached" : files.length + " images attached");
  }

  function renderThumbs() {
    const box = $("thumbs");
    box.replaceChildren(...S.images.map((im, k) => {
      const name = im.name || "image " + (k + 1);
      const x = h("button", { type: "button", class: "thumb-x", "aria-label": "Remove " + name, title: "Remove" }, icon(ICON_X, 12));
      x.addEventListener("click", () => {
        S.images.splice(k, 1);
        URL.revokeObjectURL(im.url);
        renderThumbs();
        announce("Removed " + name);
        $input.focus();
      });
      return h("li", { class: "thumb" }, h("img", { src: im.url, alt: name }), x);
    }));
    box.hidden = !S.images.length;
    updateVisionHint();
  }

  function updateVisionHint() {
    const hint = $("vision");
    const m = currentModel();
    const show = S.images.length > 0 && m && m.vision === false;
    hint.hidden = !show;
    if (show) hint.textContent = modelLabel(m) + " cannot read images. Pick a model marked \"sees images\" before you send.";
  }

  // ------------------------------------------------------------------ theme

  function effectiveTheme() {
    const set = document.documentElement.getAttribute("data-theme");
    if (set === "light" || set === "dark") return set;
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }

  function labelTheme() {
    const next = effectiveTheme() === "dark" ? "light" : "dark";
    $("theme").setAttribute("aria-label", "Switch to the " + next + " theme");
    $("theme").title = "Switch to the " + next + " theme";
  }

  // ------------------------------------------------------------------ wiring

  function bind() {
    $("form").addEventListener("submit", (e) => {
      e.preventDefault();
      if (S.streaming) stop();
      else send();
    });

    $input.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey && !e.isComposing && e.keyCode !== 229) {
        e.preventDefault();
        if (!S.streaming) send();
      }
    });
    $input.addEventListener("input", autosize);

    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && S.streaming) {
        e.preventDefault();
        stop();
      }
    });

    $main.addEventListener("scroll", () => {
      S.stick = $main.scrollHeight - $main.scrollTop - $main.clientHeight < 80;
    }, { passive: true });

    $("model").addEventListener("change", async (e) => {
      const sel = e.target;
      const prev = S.state && S.state.model;
      const name = sel.value;
      if (!name || name === prev) return;
      sel.disabled = true;
      try {
        await applyResult(await api("/api/model", { name: name }));
        const label = modelLabel(currentModel());
        addSys("Model: " + label);
        announce("Model set to " + label);
      } catch (err) {
        sel.value = prev || "";
        addNote($log, "error", "Could not switch model. " + err.message);
      } finally {
        updateControls();
      }
    });

    $("mode").addEventListener("change", async (e) => {
      const sel = e.target;
      const prev = S.state && S.state.mode;
      const id = sel.value;
      if (!id || id === prev) return;
      sel.disabled = true;
      try {
        await applyResult(await api("/api/mode", { id: id }));
        const mode = currentMode();
        const label = mode ? mode.label || mode.id : id;
        addSys("Mode: " + label);
        announce("Mode set to " + label);
      } catch (err) {
        sel.value = prev || "";
        addNote($log, "error", "Could not change mode. " + err.message);
      } finally {
        updateControls();
      }
    });

    $("think").addEventListener("click", async () => {
      const on = $("think").getAttribute("aria-pressed") !== "true";
      setThink(on);
      try {
        await applyResult(await api("/api/think", { on: on }));
        announce(on ? "Thinking on" : "Thinking off");
      } catch (err) {
        setThink(!on);
        addNote($log, "error", "Could not change thinking. " + err.message);
      }
    });

    $("new").addEventListener("click", newChat);

    $("theme").addEventListener("click", () => {
      const next = effectiveTheme() === "dark" ? "light" : "dark";
      document.documentElement.setAttribute("data-theme", next);
      try { localStorage.setItem("sparky-theme", next); } catch (e) { /* not kept, still applied */ }
      labelTheme();
    });
    if (window.matchMedia) {
      const mq = window.matchMedia("(prefers-color-scheme: dark)");
      if (mq.addEventListener) mq.addEventListener("change", labelTheme);
    }

    for (const chip of document.querySelectorAll(".chip")) {
      chip.addEventListener("click", () => {
        $input.value = chip.getAttribute("data-fill") || chip.textContent;
        autosize();
        $input.focus();
        $input.setSelectionRange($input.value.length, $input.value.length);
      });
    }

    $("attach").addEventListener("click", () => $("file").click());
    $("file").addEventListener("change", (e) => {
      addFiles(e.target.files);
      e.target.value = "";
    });

    // A pasted image is attached. When the clipboard also holds text (Excel
    // and Word put a picture of the selection next to it), the text wins.
    document.addEventListener("paste", (e) => {
      const items = Array.from((e.clipboardData && e.clipboardData.items) || []);
      if (items.some((it) => it.kind === "string" && it.type === "text/plain")) return;
      const files = items.filter((it) => it.kind === "file" && it.type.startsWith("image/")).map((it) => it.getAsFile()).filter(Boolean);
      if (!files.length) return;
      e.preventDefault();
      addFiles(files);
    });

    const drop = $("drop");
    let depth = 0;
    const hasFiles = (e) => e.dataTransfer && Array.from(e.dataTransfer.types || []).includes("Files");
    window.addEventListener("dragenter", (e) => {
      if (!hasFiles(e)) return;
      depth++;
      drop.hidden = false;
    });
    window.addEventListener("dragleave", (e) => {
      if (!hasFiles(e)) return;
      depth = Math.max(0, depth - 1);
      if (!depth) drop.hidden = true;
    });
    window.addEventListener("dragover", (e) => {
      if (!hasFiles(e)) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = "copy";
    });
    window.addEventListener("drop", (e) => {
      if (!hasFiles(e)) return;
      e.preventDefault();
      depth = 0;
      drop.hidden = true;
      addFiles(e.dataTransfer.files);
    });
  }

  function start() {
    $log = $("log");
    $main = $("main");
    $input = $("input");
    labelTheme();
    bind();
    autosize();
    if (!TOKEN || TOKEN === "{{TOKEN}}") {
      addNote($log, "error", "This page has no access token, so Sparky will refuse every request. Open it from the address Sparky printed in the terminal.");
      return;
    }
    S.loading = loadState(true);
    S.loading.then(() => {
      // no focus on touch screens, where it would pop the keyboard up unasked
      if (window.matchMedia && window.matchMedia("(pointer: fine)").matches) $input.focus({ preventScroll: true });
    });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
})();
