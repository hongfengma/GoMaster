import { useEffect, useRef, useState } from "react";
import { useAppStore } from "../store";
import { coordToXY, drawBoard } from "../board-utils";
import MarkdownView from "./MarkdownView";
import type { ReviewEntry, StoneColor } from "../types";

const pct = (x: number) => (x * 100).toFixed(1) + "%";
const sign = (x: number) => (x >= 0 ? "+" : "") + (x * 100).toFixed(1) + "%";

/** 单手棋盘图例：绘制该手之后完整局面 + 实际落子红圈 + AI 推荐变化图（绿圈+序号） */
function ReportBoard({ entry, size }: { entry: ReviewEntry; size: number }) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const canvas = ref.current;
    if (!canvas || size <= 0) return;
    const target = 360;
    const margin = 18;
    const maxCell = Math.floor(target * 0.1);
    const cell = Math.min(maxCell, Math.floor((target - margin * 2) / (size - 1)));
    const boardPx = margin * 2 + cell * (size - 1);
    const dpr = window.devicePixelRatio || 1;
    canvas.width = boardPx * dpr;
    canvas.height = boardPx * dpr;
    canvas.style.width = `${boardPx}px`;
    canvas.style.height = `${boardPx}px`;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    const stones: { x: number; y: number; color: StoneColor }[] =
      entry.stones && entry.stones.length
        ? entry.stones
        : [];
    const highlight = coordToXY(entry.actual_sgf ?? entry.actual, size) || undefined;

    // 推荐变化图：始终在报告中展示（与界面 showPV 开关无关）
    const seq = (entry.best_pv_sgf || []).filter((c) => c && c !== "PASS");
    const pv = seq
      .map((c, k) => {
        const xy = coordToXY(c, size);
        if (!xy) return null;
        const isBlack = entry.color === "B" ? k % 2 === 0 : k % 2 === 1;
        return { ...xy, isBlack, order: k + 1 };
      })
      .filter(
        (v): v is { x: number; y: number; isBlack: boolean; order: number } =>
          v !== null
      );

    drawBoard(ctx, { size, margin, cell, stones, highlight, pv });
  }, [entry, size]);
  return <canvas ref={ref} className="report-board-canvas" />;
}

export default function ReportView({ onClose }: { onClose: () => void }) {
  const meta = useAppStore((s) => s.meta);
  const entries = useAppStore((s) => s.entries);
  const mistakes = useAppStore((s) => s.mistakes);
  const reportRef = useRef<HTMLDivElement>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  if (!meta) return null;

  const onExport = async () => {
    if (!reportRef.current) return;
    setBusy(true);
    setMsg(null);
    try {
      // 把 canvas 图例转成 base64 图片，避免 innerHTML 序列化丢失位图
      const clone = reportRef.current.cloneNode(true) as HTMLElement;
      clone.querySelectorAll("canvas").forEach((c) => {
        const cv = c as HTMLCanvasElement;
        const img = document.createElement("img");
        img.src = cv.toDataURL("image/png");
        img.style.width = cv.style.width;
        img.style.height = cv.style.height;
        cv.parentNode?.replaceChild(img, cv);
      });
      const html = clone.innerHTML;
      const css = Array.from(document.querySelectorAll("style"))
        .map((s) => s.textContent || "")
        .join("\n");

      const api = (window as any).electronAPI;
      if (api && api.exportReportPDF) {
        const r = await api.exportReportPDF(html, css);
        if (r.ok) setMsg(`已导出 PDF：${r.path || ""}`);
        else setMsg(`导出失败：${r.error || "未知错误"}`);
      } else {
        // 非 Electron 环境（纯 web 模式）：调用浏览器打印，用户另存为 PDF
        window.print();
      }
    } catch (e) {
      setMsg(`导出出错：${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusy(false);
    }
  };

  const cards = mistakes
    .map((no) => entries.find((x) => x.no === no))
    .filter((e): e is ReviewEntry => !!e);

  return (
    <div className="report-overlay" onClick={onClose}>
      <div className="report-modal" onClick={(e) => e.stopPropagation()} ref={reportRef}>
        <div className="report-toolbar no-print">
          <h2 className="report-title">复盘报告（{meta.size} 路）</h2>
          <div className="report-actions">
            <button className="btn primary" onClick={onExport} disabled={busy}>
              {busy ? "导出中…" : "导出 PDF"}
            </button>
            <button className="btn" onClick={onClose}>
              关闭
            </button>
          </div>
        </div>
        {msg && <div className="report-msg no-print">{msg}</div>}

        <div className="report-meta">
          <span>黑方：{meta.black_name || "（未署名）"}</span>
          <span>白方：{meta.white_name || "（未署名）"}</span>
          <span>贴目：{meta.komi}</span>
          <span>总手数：{meta.total_moves}</span>
          <span>失误手：{mistakes.length} 个</span>
        </div>

        {cards.length === 0 && (
          <div className="report-empty">本局没有命中失误手。</div>
        )}

        {cards.map((e) => {
          const cn = e.color === "B" ? "黑" : "白";
          const deltaCls = e.delta >= 0 ? "delta-bad" : "delta-good";
          return (
            <div className="report-card" key={e.no}>
              <div className="report-card-board">
                <ReportBoard entry={e} size={meta.size} />
                <div className="report-board-cap">
                  第 {e.no} 手（{cn}方）　实际 <b>{e.actual}</b> · 推荐{" "}
                  <b className="best">{e.best}</b>
                </div>
              </div>
              <div className="report-card-explain">
                <div className="kv">
                  <span className="k">胜率(推荐)</span>
                  <span className="v">{pct(e.ai_wr)}</span>
                  <span className="k">胜率(实际)</span>
                  <span className="v">{pct(e.actual_wr)}</span>
                  <span className="k">胜率差</span>
                  <span className={`v ${deltaCls}`}>{sign(e.delta)}</span>
                </div>
                {e.explain ? (
                  <MarkdownView text={e.explain} />
                ) : (
                  <div className="explain-empty">（该手暂无讲解）</div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
