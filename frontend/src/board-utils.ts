// 棋盘坐标与绘制工具（平移自 web/app.js，行为保持一致：SGF 连续字母坐标，
// 边线标签跳过字母 I 以符合标准围棋记谱）。

export interface XY {
  x: number;
  y: number;
}

/** SGF 两位字母坐标 -> 内部 (x,y)，x 列 0=最左，y 行 0=最上。 */
export function sgfToXY(coord: string, size: number): XY | null {
  if (!coord || coord.length < 2) return null;
  const cc = coord.toLowerCase();
  const c = cc.charCodeAt(0) - 97;
  const r = cc.charCodeAt(1) - 97;
  if (c < 0 || c >= size || r < 0 || r >= size) return null;
  return { x: c, y: r };
}

/** 列索引 -> 边线标签（跳过字母 I，符合标准记谱）。 */
export function colLabel(i: number): string {
  return i < 8
    ? String.fromCharCode(97 + i)
    : String.fromCharCode(97 + i + 1);
}

/** 星位坐标列表。 */
export function hoshi(size: number): [number, number][] {
  let edges: number[];
  if (size === 19) edges = [3, 9, 15];
  else if (size === 13) edges = [3, 6, 9];
  else if (size === 9) edges = [2, 6];
  else {
    const m = Math.floor(size / 2);
    edges = Array.from(new Set([2, m, size - 3]));
  }
  const pts: [number, number][] = [];
  edges.forEach((a) => edges.forEach((b) => pts.push([a, b])));
  if (size % 2 === 1) {
    const c = (size - 1) / 2;
    pts.push([c, c]);
  }
  return pts;
}

export interface Stone {
  x: number;
  y: number;
  color: "B" | "W";
}

export interface PvStone {
  x: number;
  y: number;
  isBlack: boolean;
  order: number; // 1 起；1 为 AI 推荐点（绿圈）
}

export interface DrawData {
  size: number;
  margin: number;
  cell: number;
  stones: Stone[];
  highlight?: XY; // 当前手实际落子红圈
  pv?: PvStone[]; // 推荐后续变化（带序号黑白子）
}

export function drawBoard(ctx: CanvasRenderingContext2D, d: DrawData): void {
  const { size, margin, cell, stones } = d;
  const boardPx = margin * 2 + cell * (size - 1);

  // 木色背景
  ctx.fillStyle = "#e9b96e";
  ctx.fillRect(0, 0, boardPx, boardPx);

  // 网格线
  ctx.strokeStyle = "#5b3f1e";
  ctx.lineWidth = 1;
  for (let i = 0; i < size; i++) {
    const p = margin + i * cell;
    ctx.beginPath();
    ctx.moveTo(margin, p);
    ctx.lineTo(margin + (size - 1) * cell, p);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(p, margin);
    ctx.lineTo(p, margin + (size - 1) * cell);
    ctx.stroke();
  }

  // 坐标标记（列 a..t 跳过 i；行 底=1 顶=size）
  ctx.fillStyle = "#3a2a12";
  ctx.font = "12px sans-serif";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  for (let col = 0; col < size; col++) {
    const x = margin + col * cell;
    ctx.fillText(colLabel(col), x, margin / 2);
    ctx.fillText(colLabel(col), x, boardPx - margin / 2);
  }
  for (let row = 0; row < size; row++) {
    const y = margin + row * cell;
    ctx.fillText(String(size - row), margin / 2, y);
    ctx.fillText(String(size - row), boardPx - margin / 2, y);
  }

  // 星位
  ctx.fillStyle = "#5b3f1e";
  hoshi(size).forEach(([x, y]) => {
    ctx.beginPath();
    ctx.arc(margin + x * cell, margin + y * cell, 3.2, 0, Math.PI * 2);
    ctx.fill();
  });

  // 棋子
  for (const s of stones) {
    const x = margin + s.x * cell;
    const y = margin + s.y * cell;
    const r = cell * 0.42;
    ctx.beginPath();
    ctx.arc(x, y, r, 0, Math.PI * 2);
    ctx.fillStyle = s.color === "B" ? "#1a1a1a" : "#fafafa";
    ctx.fill();
    if (s.color !== "B") {
      ctx.strokeStyle = "#b9b9b9";
      ctx.lineWidth = 1;
      ctx.stroke();
    }
    // 中心小点（最后一手/普通手都画，保持视觉一致）
    ctx.fillStyle = s.color === "B" ? "#fafafa" : "#1a1a1a";
    ctx.beginPath();
    ctx.arc(x, y, 2.2, 0, Math.PI * 2);
    ctx.fill();
  }

  // 当前手高亮：实际落子红圈
  if (d.highlight) {
    const x = margin + d.highlight.x * cell;
    const y = margin + d.highlight.y * cell;
    ctx.strokeStyle = "#e23b3b";
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.arc(x, y, cell * 0.46, 0, Math.PI * 2);
    ctx.stroke();
  }

  // PV 序列：带序号的黑白子，order=1 为 AI 推荐点（绿圈）
  if (d.pv) {
    for (const p of d.pv) {
      const x = margin + p.x * cell;
      const y = margin + p.y * cell;
      const r = cell * 0.36;
      ctx.beginPath();
      ctx.arc(x, y, r, 0, Math.PI * 2);
      ctx.fillStyle = p.isBlack
        ? "rgba(26,26,26,0.88)"
        : "rgba(250,250,250,0.92)";
      ctx.fill();
      if (!p.isBlack) {
        ctx.strokeStyle = "#888";
        ctx.lineWidth = 1;
        ctx.stroke();
      }
      if (p.order === 1) {
        ctx.strokeStyle = "#1faa59";
        ctx.lineWidth = 3;
        ctx.beginPath();
        ctx.arc(x, y, r + 2.5, 0, Math.PI * 2);
        ctx.stroke();
      }
      ctx.fillStyle = p.isBlack ? "#fff" : "#111";
      ctx.font = `${Math.floor(cell * 0.3)}px sans-serif`;
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText(String(p.order), x, y);
    }
  }
}
