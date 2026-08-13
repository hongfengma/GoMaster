import { useEffect, useRef } from "react";
import { useAppStore } from "../store";
import { sgfToXY, drawBoard } from "../board-utils";
import type { ReviewEntry, StoneColor } from "../types";

export default function Board() {
  const size = useAppStore((s) => s.meta?.size ?? 0);
  const entries = useAppStore((s) => s.entries);
  const current = useAppStore((s) => s.current);
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || size <= 0) return;
    const margin = 30;
    const cell = Math.min(38, Math.floor((560 - margin * 2) / (size - 1)));
    const boardPx = margin * 2 + cell * (size - 1);
    const dpr = window.devicePixelRatio || 1;
    canvas.width = boardPx * dpr;
    canvas.height = boardPx * dpr;
    canvas.style.width = `${boardPx}px`;
    canvas.style.height = `${boardPx}px`;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    // 重建第 1..current 手的棋子
    const stones: { x: number; y: number; color: StoneColor }[] = [];
    for (const e of entries as ReviewEntry[]) {
      if (e.no > current) break;
      const xy = sgfToXY(e.actual, size);
      if (xy && e.actual !== "PASS")
        stones.push({ ...xy, color: e.color });
    }

    // 当前手：实际落子红圈 + 推荐后续变化（带序号黑白子）
    let highlight: { x: number; y: number } | undefined;
    let pv:
      | { x: number; y: number; isBlack: boolean; order: number }[]
      | undefined;
    if (current >= 1) {
      const e = entries.find((x) => x.no === current);
      if (e) {
        const ha = sgfToXY(e.actual, size);
        if (ha && e.actual !== "PASS") highlight = ha;
        const seq = (e.best_pv_sgf || []).filter((c) => c && c !== "PASS");
        pv = seq
          .map((c, k) => {
            const xy = sgfToXY(c, size);
            if (!xy) return null;
            const isBlack = e.color === "B" ? k % 2 === 0 : k % 2 === 1;
            return { ...xy, isBlack, order: k + 1 };
          })
          .filter(
            (v): v is { x: number; y: number; isBlack: boolean; order: number } =>
              v !== null
          );
      }
    }

    drawBoard(ctx, { size, margin, cell, stones, highlight, pv });
  }, [size, entries, current]);

  if (size <= 0) return null;
  return <canvas ref={canvasRef} className="board-canvas" />;
}
