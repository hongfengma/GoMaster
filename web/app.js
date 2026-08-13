/* 围棋教练 AI 复盘 - 前端逻辑（零依赖原生 JS） */
(function () {
  "use strict";

  const API = "";
  const DEMO_SGF = "(;GM[1]FF[4]CA[UTF-8]SZ[9]KM[7.5]PB[黑方(你)]PW[白方(对手)];B[cc];W[gg];B[cg];W[gc];B[ee];W[gi];B[ce];W[ig];B[eg];W[ii];B[ca];W[ih];B[cb];W[hi];B[ac];W[hg];B[aa];W[gh];B[bb];W[fi])";
  const state = {
    taskId: null,
    meta: null,            // {size, total_moves, komi, ...}
    entriesByNo: new Map(), // no -> entry（已到达的逐手分析）
    mistakes: [],          // 失误手 no 列表
    current: 0,            // 当前显示到第几手（0=开局）
    status: null,
    pollTimer: null,
    margin: 30,
    cell: 36,
  };

  const $ = (id) => document.getElementById(id);

  /* ---------- 坐标工具 ---------- */
  function sgfToXY(coord, size) {
    if (!coord || coord.length < 2) return null;
    const cc = coord.toLowerCase();
    const c = cc.charCodeAt(0) - 97;
    const r = cc.charCodeAt(1) - 97;
    if (c < 0 || c >= size || r < 0 || r >= size) return null;
    return { c, r };
  }
  function coordToPx(coord) {
    const xy = sgfToXY(coord, state.meta.size);
    if (!xy) return null;
    return { x: state.margin + xy.c * state.cell, y: state.margin + xy.r * state.cell };
  }
  function hoshi(size) {
    let edges;
    if (size === 19) edges = [3, 9, 15];
    else if (size === 13) edges = [3, 6, 9];
    else if (size === 9) edges = [2, 6];
    else {
      const m = Math.floor(size / 2);
      edges = [2, m, size - 3].filter((v, i, a) => a.indexOf(v) === i);
    }
    const pts = [];
    edges.forEach((a) => edges.forEach((b) => pts.push([a, b])));
    if (size % 2 === 1) {
      const c = (size - 1) / 2;
      pts.push([c, c]);
    }
    return pts;
  }

  /* ---------- 状态/进度 ---------- */
  function setStatus(msg, type) {
    const el = $("status");
    el.textContent = msg || "";
    el.className = "status" + (type ? " " + type : "");
  }

  function syncEntries(arr) {
    arr.forEach((e) => state.entriesByNo.set(e.no, e));
  }

  /* ---------- 棋盘绘制 ---------- */
  function drawBoard(moveNo) {
    const size = state.meta.size;
    const m = state.margin, c = state.cell;
    const boardPx = m * 2 + c * (size - 1);
    const cv = $("board");
    const dpr = window.devicePixelRatio || 1;
    cv.width = boardPx * dpr;
    cv.height = boardPx * dpr;
    cv.style.width = boardPx + "px";
    cv.style.height = boardPx + "px";
    const ctx = cv.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, boardPx, boardPx);

    // 木色背景
    ctx.fillStyle = "#e9b96e";
    ctx.fillRect(0, 0, boardPx, boardPx);

    // 网格线
    ctx.strokeStyle = "#5b3f1e";
    ctx.lineWidth = 1;
    for (let i = 0; i < size; i++) {
      const p = m + i * c;
      ctx.beginPath(); ctx.moveTo(m, p); ctx.lineTo(m + (size - 1) * c, p); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(p, m); ctx.lineTo(p, m + (size - 1) * c); ctx.stroke();
    }
    // 坐标标记（标准记谱：列 a..t 跳过 i；行 底=1 顶=size）
    ctx.fillStyle = "#3a2a12";
    ctx.font = "12px sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    for (let col = 0; col < size; col++) {
      const x = m + col * c;
      const letter = col < 8 ? String.fromCharCode(97 + col) : String.fromCharCode(97 + col + 1);
      ctx.fillText(letter, x, m / 2);
      ctx.fillText(letter, x, boardPx - m / 2);
    }
    for (let row = 0; row < size; row++) {
      const y = m + row * c;
      ctx.fillText(String(size - row), m / 2, y);
      ctx.fillText(String(size - row), boardPx - m / 2, y);
    }

    // 星位
    ctx.fillStyle = "#5b3f1e";
    hoshi(size).forEach(([x, y]) => {
      ctx.beginPath();
      ctx.arc(m + x * c, m + y * c, 3.2, 0, Math.PI * 2);
      ctx.fill();
    });

    // 棋子
    const drawStone = (x, y, color) => {
      const r = state.cell * 0.42;
      ctx.beginPath();
      ctx.arc(x, y, r, 0, Math.PI * 2);
      ctx.fillStyle = color === "B" ? "#1a1a1a" : "#fafafa";
      ctx.fill();
      if (color !== "B") { ctx.strokeStyle = "#b9b9b9"; ctx.lineWidth = 1; ctx.stroke(); }
      // 最后一手标记
      ctx.fillStyle = color === "B" ? "#fafafa" : "#1a1a1a";
      ctx.beginPath(); ctx.arc(x, y, 2.2, 0, Math.PI * 2); ctx.fill();
    };

    const lastNo = Math.min(moveNo, state.entriesByNo.size);
    for (let k = 1; k <= lastNo; k++) {
      const e = state.entriesByNo.get(k);
      if (!e || !e.actual || e.actual === "PASS") continue;
      const p = coordToPx(e.actual);
      if (p) drawStone(p.x, p.y, e.color);
    }

    // 当前手高亮：实际落子红圈；AI 推荐及后续变化用「带序号的黑白子」直观展示
    if (moveNo >= 1) {
      const e = state.entriesByNo.get(moveNo);
      if (e) {
        if (e.actual && e.actual !== "PASS") {
          const p = coordToPx(e.actual);
          if (p) {
            ctx.strokeStyle = "#e23b3b"; ctx.lineWidth = 3;
            ctx.beginPath(); ctx.arc(p.x, p.y, state.cell * 0.46, 0, Math.PI * 2); ctx.stroke();
          }
        }
        // PV：best_pv_sgf[0] 即 AI 推荐点，其后为推荐后续变化
        const seq = (e.best_pv_sgf || []).filter((x) => x && x !== "PASS");
        for (let k = 0; k < seq.length; k++) {
          const p = coordToPx(seq[k]);
          if (!p) continue;
          const isBlack = (e.color === "B") ? (k % 2 === 0) : (k % 2 === 1);
          const r = state.cell * 0.36;
          ctx.beginPath();
          ctx.arc(p.x, p.y, r, 0, Math.PI * 2);
          ctx.fillStyle = isBlack ? "rgba(26,26,26,0.88)" : "rgba(250,250,250,0.92)";
          ctx.fill();
          if (!isBlack) { ctx.strokeStyle = "#888"; ctx.lineWidth = 1; ctx.stroke(); }
          if (k === 0) {
            ctx.strokeStyle = "#1faa59"; ctx.lineWidth = 3;
            ctx.beginPath(); ctx.arc(p.x, p.y, r + 2.5, 0, Math.PI * 2); ctx.stroke();
          }
          ctx.fillStyle = isBlack ? "#fff" : "#111";
          ctx.font = (state.cell * 0.3 | 0) + "px sans-serif";
          ctx.textAlign = "center"; ctx.textBaseline = "middle";
          ctx.fillText(String(k + 1), p.x, p.y);
        }
      }
    }
  }

  /* ---------- 信息面板 ---------- */
  function pct(x) { return (x * 100).toFixed(1) + "%"; }
  function sign(x) { return (x >= 0 ? "+" : "") + (x * 100).toFixed(1) + "%"; }

  function updateMoveDetail() {
    const el = $("move-detail");
    const no = state.current;
    if (no < 1) {
      el.innerHTML = '<h3>当前局面</h3><div class="kv"><div class="k">状态</div><div class="v">开局（尚未落子）</div></div>';
      return;
    }
    const e = state.entriesByNo.get(no);
    if (!e) {
      el.innerHTML = `<h3>第 ${no} 手</h3><div class="kv"><div class="k">状态</div><div class="v">分析中…</div></div>`;
      return;
    }
    const isMistake = state.mistakes.indexOf(no) >= 0;
    const cn = e.color === "B" ? "黑" : "白";
    const deltaCls = e.delta >= 0 ? "delta-bad" : "delta-good";
    const explainHtml = e.explain
      ? `<div class="explain">${renderMarkdown(e.explain)}</div>`
      : `<div class="explain empty">（该手暂无讲解）</div>`;
    el.innerHTML = `
      <h3>第 ${no} 手（${cn}方）${isMistake ? " ⚠ 失误手" : ""}</h3>
      <div class="kv">
        <div class="k">你的落子</div><div class="v">${e.actual}</div>
        <div class="k">AI 推荐</div><div class="v" style="color:#1faa59">${e.best}</div>
        <div class="k">胜率(推荐)</div><div class="v">${pct(e.ai_wr)}</div>
        <div class="k">胜率(实际)</div><div class="v">${pct(e.actual_wr)}</div>
        <div class="k">胜率差</div><div class="v ${deltaCls}">${sign(e.delta)}</div>
      </div>
      ${explainHtml}`;
  }

  function updateOverview() {
    const el = $("overview");
    const total = state.meta ? state.meta.total_moves : 0;
    const entries = Array.from(state.entriesByNo.values());
    let biggest = null;
    entries.forEach((e) => { if (!biggest || e.delta > biggest.delta) biggest = e; });
    const mCount = state.mistakes.length;
    const bigTxt = biggest
      ? `最大偏差出现在第 <b>${biggest.no}</b> 手（${biggest.color === "B" ? "黑" : "白"}），胜率下降约 <b>${sign(biggest.delta)}</b>。`
      : "（分析中…）";
    el.innerHTML = `
      <h3>本局总览</h3>
      <div class="kv">
        <div class="k">总手数</div><div class="v">${total}</div>
        <div class="k">已分析</div><div class="v">${entries.length} / ${total}</div>
        <div class="k">失误手</div><div class="v" style="color:#c0392b">${mCount} 个</div>
      </div>
      <p style="font-size:13px;color:#55606d;margin:10px 0 0">${bigTxt}</p>`;
  }

  function updateMistakeList() {
    const ul = $("mistake-list");
    if (!state.mistakes.length) {
      ul.innerHTML = '<li class="pending">（暂无可讲解的失误手）</li>';
      return;
    }
    ul.innerHTML = "";
    state.mistakes.forEach((no) => {
      const e = state.entriesByNo.get(no);
      const li = document.createElement("li");
      const deltaTxt = e ? sign(e.delta) : "…";
      const ready = e && e.explain;
      li.innerHTML = `<span>第 ${no} 手（${e ? (e.color === "B" ? "黑" : "白") : ""}） 你:${e ? e.actual : "…"} → 推荐:${e ? e.best : "…"}</span><span class="delta">${deltaTxt}${ready ? "" : " · 讲解中"}</span>`;
      li.addEventListener("click", () => { goToMove(no); });
      ul.appendChild(li);
    });
  }

  function render() {
    if (!state.meta) return;
    drawBoard(state.current);
    updateMoveDetail();
    updateOverview();
    updateMistakeList();
    $("move-label").textContent = `第 ${state.current} / ${state.meta.total_moves} 手`;
  }

  /* ---------- 导航 ---------- */
  function goToMove(no) {
    const total = state.meta ? state.meta.total_moves : 0;
    state.current = Math.max(0, Math.min(total, no));
    $("move-slider").value = state.current;
    render();
  }

  /* ---------- 轮询 ---------- */
  function schedulePoll() {
    state.pollTimer = setTimeout(poll, 1200);
  }
  function stopPoll() {
    if (state.pollTimer) { clearTimeout(state.pollTimer); state.pollTimer = null; }
  }
  function poll() {
    if (!state.taskId) return;
    fetch(API + "/api/analyze/" + state.taskId)
      .then((r) => r.json())
      .then((d) => {
        state.status = d.status;
        if (d.meta) state.meta = d.meta;
        if (d.entries) syncEntries(d.entries);
        if (d.mistakes) state.mistakes = d.mistakes;
        if (d.status === "running" || d.status === "pending") {
          setStatus(`分析中… 已完成第 ${d.current || 0} / ${state.meta ? state.meta.total_moves : "?"} 手`, "run");
          render();
          schedulePoll();
        } else if (d.status === "done") {
          setStatus("复盘完成 ✓ 可点击右侧失误手查看讲解", "ok");
          render();
          stopPoll();
        } else if (d.status === "error") {
          setStatus("复盘出错：" + (d.error || "未知错误"), "err");
          stopPoll();
        }
      })
      .catch((e) => {
        setStatus("轮询失败：" + e, "err");
        schedulePoll();
      });
  }

  /* ---------- 启动 ---------- */
  function startReview() {
    stopPoll();
    const fileInput = $("sgf-file");
    const text = $("sgf-text").value.trim();
    const doStart = (sgf) => {
      if (!sgf) { setStatus("请选择 SGF 文件或粘贴内容", "err"); return; }
      setStatus("正在提交棋谱…", "run");
      fetch(API + "/api/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sgf,
          level: $("level").value,
          visits: parseInt($("visits").value, 10) || 80,
        }),
      })
        .then((r) => r.json())
        .then((d) => {
          if (d.error) { setStatus("错误：" + d.error, "err"); return; }
          state.taskId = d.task_id;
          state.meta = d.meta;
          state.entriesByNo = new Map();
          state.mistakes = [];
          state.current = state.meta.total_moves;
          $("review-area").classList.remove("hidden");
          const sl = $("move-slider");
          sl.max = state.meta.total_moves;
          sl.value = state.meta.total_moves;
          render();
          poll();
        })
        .catch((e) => setStatus("请求失败：" + e, "err"));
    };
    if (fileInput.files && fileInput.files[0]) {
      const reader = new FileReader();
      reader.onload = () => doStart(reader.result);
      reader.readAsText(fileInput.files[0]);
    } else if (text) {
      doStart(text);
    } else {
      setStatus("请选择 SGF 文件或粘贴内容", "err");
    }
  }

  function escapeHtml(s) {
    return (s || "").replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
  }

  // 极简、安全的 Markdown -> HTML（标题/加粗/斜体/行内代码/列表/引用/段落），用于渲染讲解
  function renderMarkdown(md) {
    if (!md) return "";
    const esc = (s) => s.replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
    const inline = (t) => esc(t)
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/\*([^*\n]+)\*/g, "<em>$1</em>")
      .replace(/`([^`]+)`/g, "<code>$1</code>");
    const lines = md.split(/\r?\n/);
    let html = "", inList = false;
    for (const raw of lines) {
      const line = raw.replace(/\s+$/, "");
      const li = line.match(/^\s*[-*]\s+(.*)$/);
      if (li) {
        if (!inList) { html += "<ul>"; inList = true; }
        html += "<li>" + inline(li[1]) + "</li>";
        continue;
      } else if (inList) { html += "</ul>"; inList = false; }
      const h = line.match(/^(#{1,3})\s+(.*)$/);
      if (h) { const lv = h[1].length; html += `<h${lv}>${inline(h[2])}</h${lv}>`; continue; }
      const q = line.match(/^>\s?(.*)$/);
      if (q) { html += `<blockquote>${inline(q[1])}</blockquote>`; continue; }
      if (line.trim() === "") continue;
      html += "<p>" + inline(line) + "</p>";
    }
    if (inList) html += "</ul>";
    return html;
  }

  /* ---------- 绑定 ---------- */
  window.addEventListener("DOMContentLoaded", () => {
    $("start-btn").addEventListener("click", startReview);
    $("demo-btn").addEventListener("click", () => { $("sgf-text").value = DEMO_SGF; startReview(); });
    $("prev").addEventListener("click", () => goToMove(state.current - 1));
    $("next").addEventListener("click", () => goToMove(state.current + 1));
    $("move-slider").addEventListener("input", (e) => goToMove(parseInt(e.target.value, 10)));
  });
})();
