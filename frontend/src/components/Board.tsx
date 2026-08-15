import { useEffect, useRef, useState } from "react";
import { useAppStore } from "../store";
import { coordToXY, drawBoard } from "../board-utils";
import type { ReviewEntry, StoneColor } from "../types";

export default function Board() {
  const size = useAppStore((s) => s.meta?.size ?? 0);
  const entries = useAppStore((s) => s.entries);
  const current = useAppStore((s) => s.current);
  const showPV = useAppStore((s) => s.showPV);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [, setTick] = useState(0);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || size <= 0) return;
    // 棋盘尺寸：左栏约占 60%，尽量撑满；最小 600px，最大 860px
    const targetBoard = Math.max(600, Math.min(860, Math.floor(window.innerWidth * 0.6)));
    const margin = Math.max(30, Math.floor(targetBoard * 0.048));
    const maxCell = Math.floor(targetBoard * 0.09);
    const cell = Math.min(maxCell, Math.floor((targetBoard - margin * 2) / (size - 1)));
    const boardPx = margin * 2 + cell * (size - 1);
    const dpr = window.devicePixelRatio || 1;
    canvas.width = boardPx * dpr;
    canvas.height = boardPx * dpr;
    canvas.style.width = `${boardPx}px`;
    canvas.style.height = `${boardPx}px`;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    // 重建第 1..current 手的棋子（优先用 SGF 坐标绘制，兼容旧数据）
    const stones: { x: number; y: number; color: StoneColor }[] = [];
    for (const e of entries as ReviewEntry[]) {
      if (e.no > current) break;
      const xy = coordToXY(e.actual_sgf ?? e.actual, size);
      if (xy)
        stones.push({ ...xy, color: e.color });
    }

    // 当前手：实际落子红圈（始终显示）
    let highlight: { x: number; y: number } | undefined;
    let pv:
      | { x: number; y: number; isBlack: boolean; order: number }[]
      | undefined;
    if (current >= 1) {
      const e = entries.find((x) => x.no === current);
      if (e) {
        const ha = coordToXY(e.actual_sgf ?? e.actual, size);
        if (ha) highlight = ha;
        // 后续推演（变化图）仅在用户开启开关时绘制，避免遮挡已有棋局
        if (showPV) {
          const seq = (e.best_pv_sgf || []).filter((c) => c && c !== "PASS");
          pv = seq
            .map((c, k) => {
              const xy = coordToXY(c, size);
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
    }

    drawBoard(ctx, { size, margin, cell, stones, highlight, pv });
  }, [size, entries, current, showPV]);

  // 窗口大小变化时重绘棋盘，避免初始尺寸过小或用户拉伸后不变
  useEffect(() => {
    function onResize() {
      if (!size) return;
      // 通过强制更新触发上面的 useEffect 重新计算棋盘尺寸
      // eslint-disable-next-line @typescript-eslint/no-unused-vars
      setTick((t) => t + 1);
    }
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [size]);

  if (size <= 0) return null;
  return <canvas ref={canvasRef} className="board-canvas" />;
}
