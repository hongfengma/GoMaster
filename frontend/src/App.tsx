import { useState } from "react";
import { useAppStore } from "./store";
import Toolbar from "./components/Toolbar";
import Board from "./components/Board";
import Navigator from "./components/Navigator";
import InfoPanel from "./components/InfoPanel";
import MistakeList from "./components/MistakeList";
import Settings from "./components/Settings";
import ReportView from "./components/ReportView";
import WinRateChart from "./components/WinRateChart";
import type { ReviewEntry } from "./types";

const sign = (x: number) => (x >= 0 ? "+" : "") + (x * 100).toFixed(1) + "%";

function PerspectiveBar() {
  const perspective = useAppStore((s) => s.perspective);
  const setPerspective = useAppStore((s) => s.setPerspective);
  return (
    <div className="perspective-bar">
      <span className="perspective-label">查看视角</span>
      <div className="seg">
        <button
          className={"seg-btn" + (perspective === "B" ? " active" : "")}
          onClick={() => setPerspective("B")}
        >
          黑方
        </button>
        <button
          className={"seg-btn" + (perspective === "W" ? " active" : "")}
          onClick={() => setPerspective("W")}
        >
          白方
        </button>
      </div>
    </div>
  );
}

function Overview() {
  const meta = useAppStore((s) => s.meta);
  const entries = useAppStore((s) => s.entries);
  const mistakes = useAppStore((s) => s.mistakes);
  const perspective = useAppStore((s) => s.perspective);
  if (!meta) return null;
  // 仅统计「当前视角方」的失误手
  const sideMistakeNos = mistakes.filter((no) => {
    const e = entries.find((x) => x.no === no);
    return e && e.color === perspective;
  });
  const sideEntries = entries.filter((e) => e.color === perspective);
  const biggest = sideEntries.reduce<ReviewEntry | null>(
    (acc, e) => (!acc || e.delta > acc.delta ? e : acc),
    null
  );
  const sideCn = perspective === "B" ? "黑方" : "白方";
  const bigTxt = biggest
    ? `${sideCn}最大偏差出现在第 ${biggest.no} 手，胜率下降约 ${sign(biggest.delta)}。`
    : "（该方暂无失误手）";
  return (
    <div className="panel overview">
      <h3>本局总览（{sideCn}）</h3>
      <div className="kv">
        <span className="k">总手数</span>
        <span className="v">{meta.total_moves}</span>
        <span className="k">已分析</span>
        <span className="v">
          {entries.length} / {meta.total_moves}
        </span>
        <span className="k">{sideCn}失误手</span>
        <span className="v mistake-count">{sideMistakeNos.length} 个</span>
      </div>
      <p className="overview-note">{bigTxt}</p>
      <h4>{sideCn}失误手列表</h4>
      <MistakeList />
    </div>
  );
}

export default function App() {
  const meta = useAppStore((s) => s.meta);
  const status = useAppStore((s) => s.status);
  const error = useAppStore((s) => s.error);
  const winrates = useAppStore((s) => s.winrates);
  const goToMove = useAppStore((s) => s.goToMove);
  const [showSettings, setShowSettings] = useState(false);
  const [showReport, setShowReport] = useState(false);

  return (
    <div className="app">
      <header className="app-header">
        <div className="app-title-row">
          <div>
            <h1>围棋教练 · AI 复盘</h1>
            <p className="subtitle">
              导入棋谱 → 逐手复盘 → 看清你与高手之间的那几目棋
            </p>
          </div>
          <div className="header-actions">
            {meta && status === "done" && (
              <button className="btn" onClick={() => setShowReport(true)}>
                查看报告
              </button>
            )}
            <button className="btn settings-btn" onClick={() => setShowSettings(true)}>
              设置
            </button>
          </div>
        </div>
      </header>
      <Toolbar />
      {error && <div className="err-banner">复盘出错：{error}</div>}
      {meta ? (
        <div className="review-layout">
          <div className="left">
            <Board />
            <Navigator />
          </div>
          <div className="right">
            <PerspectiveBar />
            {winrates.length > 0 && status === "done" && (
              <WinRateChart points={winrates} onSelect={goToMove} />
            )}
            <InfoPanel />
            <Overview />
          </div>
        </div>
      ) : (
          <div className="empty-hint">
          {status === "pending" ? "正在提交棋谱…" : "请导入 SGF 棋谱开始复盘。"}
        </div>
      )}
      {showSettings && <Settings onClose={() => setShowSettings(false)} />}
      {showReport && meta && (
        <ReportView onClose={() => setShowReport(false)} />
      )}
    </div>
  );
}
