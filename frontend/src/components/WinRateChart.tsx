import { useMemo } from "react";
import type { WinRatePoint } from "../types";

interface Props {
  points: WinRatePoint[];
  onSelect?: (move: number) => void;
}

const W = 680;
const H = 260;
const PAD_L = 46;
const PAD_R = 16;
const PAD_T = 18;
const PAD_B = 30;
const PLOT_W = W - PAD_L - PAD_R;
const PLOT_H = H - PAD_T - PAD_B;

function pct(v: number) {
  return (v * 100).toFixed(0) + "%";
}

export default function WinRateChart({ points, onSelect }: Props) {
  const model = useMemo(() => {
    if (!points.length) return null;
    const valid = points.filter((p) => p.wr != null) as (WinRatePoint & {
      wr: number;
    })[];
    if (!valid.length) return null;
    const maxMove = points[points.length - 1].move;
    const minMove = points[0].move;
    const span = Math.max(1, maxMove - minMove);
    const xOf = (move: number) =>
      PAD_L + ((move - minMove) / span) * PLOT_W;
    const yOf = (wr: number) => PAD_T + (1 - wr) * PLOT_H;

    // 折线：遇到 wr=null 处断开
    let d = "";
    let started = false;
    for (const p of valid) {
      const x = xOf(p.move);
      const y = yOf(p.wr);
      d += (started ? " L" : "M") + x.toFixed(1) + " " + y.toFixed(1);
      started = true;
    }

    // 横向网格 + 刻度
    const yTicks = [0, 0.25, 0.5, 0.75, 1];
    const yGrid = yTicks.map((v) => ({
      v,
      y: PAD_T + (1 - v) * PLOT_H,
    }));

    // X 轴刻度（约 5 个）
    const xTickCount = Math.min(5, maxMove - minMove + 1);
    const xTicks: number[] = [];
    for (let k = 0; k < xTickCount; k++) {
      const move = Math.round(minMove + (span * k) / Math.max(1, xTickCount - 1));
      xTicks.push(move);
    }

    return { valid, xOf, yOf, d, yGrid, xTicks, maxMove, minMove };
  }, [points]);

  if (!model) {
    return (
      <div className="panel winrate-panel">
        <h3>全局胜率曲线</h3>
        <p className="winrate-empty">（暂无数据）</p>
      </div>
    );
  }

  const { valid, xOf, yOf, d, yGrid, xTicks } = model;
  const mistakes = valid.filter((p) => p.is_mistake);

  return (
    <div className="panel winrate-panel">
      <h3>全局胜率曲线 <span className="wr-sub">（黑方视角）</span></h3>
      <svg
        className="winrate-svg"
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="xMidYMid meet"
        role="img"
        aria-label="全局胜率曲线"
      >
        {/* 横向网格 + 百分比刻度 */}
        {yGrid.map((g) => (
          <g key={g.v}>
            <line
              x1={PAD_L}
              y1={g.y}
              x2={W - PAD_R}
              y2={g.y}
              className={g.v === 0.5 ? "wr-grid wr-grid-mid" : "wr-grid"}
            />
            <text x={PAD_L - 8} y={g.y + 4} className="wr-axis" textAnchor="end">
              {pct(g.v)}
            </text>
          </g>
        ))}

        {/* X 轴刻度 */}
        {xTicks.map((m) => (
          <text
            key={m}
            x={xOf(m)}
            y={H - PAD_B + 16}
            className="wr-axis"
            textAnchor="middle"
          >
            {m}
          </text>
        ))}
        <text x={W - PAD_R} y={H - PAD_B + 16} className="wr-axis" textAnchor="end">
          手
        </text>

        {/* 胜率折线 */}
        <path d={d} className="wr-line" />

        {/* 失误点（红）— 可点击跳到该手 */}
        {mistakes.map((p) => (
          <circle
            key={p.move}
            cx={xOf(p.move)}
            cy={yOf(p.wr)}
            r={4}
            className="wr-dot"
            onClick={() => onSelect && onSelect(p.move)}
          >
            <title>第 {p.move} 手（失误）</title>
          </circle>
        ))}
      </svg>
      <p className="winrate-note">
        红线为失误手（胜率较 AI 最佳下降 ≥ 阈值），点击可跳到该手查看讲解。
      </p>
    </div>
  );
}
