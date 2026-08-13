import { useAppStore } from "./store";
import Toolbar from "./components/Toolbar";
import Board from "./components/Board";
import Navigator from "./components/Navigator";
import InfoPanel from "./components/InfoPanel";
import MistakeList from "./components/MistakeList";
import type { ReviewEntry } from "./types";

const sign = (x: number) => (x >= 0 ? "+" : "") + (x * 100).toFixed(1) + "%";

function Overview() {
  const meta = useAppStore((s) => s.meta);
  const entries = useAppStore((s) => s.entries);
  const mistakes = useAppStore((s) => s.mistakes);
  if (!meta) return null;
  const biggest = entries.reduce<ReviewEntry | null>(
    (acc, e) => (!acc || e.delta > acc.delta ? e : acc),
    null
  );
  const bigTxt = biggest
    ? `最大偏差出现在第 ${biggest.no} 手（${biggest.color === "B" ? "黑" : "白"}），胜率下降约 ${sign(biggest.delta)}。`
    : "（分析中…）";
  return (
    <div className="panel overview">
      <h3>本局总览</h3>
      <div className="kv">
        <span className="k">总手数</span>
        <span className="v">{meta.total_moves}</span>
        <span className="k">已分析</span>
        <span className="v">
          {entries.length} / {meta.total_moves}
        </span>
        <span className="k">失误手</span>
        <span className="v mistake-count">{mistakes.length} 个</span>
      </div>
      <p className="overview-note">{bigTxt}</p>
      <h4>失误手列表</h4>
      <MistakeList />
    </div>
  );
}

export default function App() {
  const meta = useAppStore((s) => s.meta);
  const status = useAppStore((s) => s.status);
  const error = useAppStore((s) => s.error);

  return (
    <div className="app">
      <header className="app-header">
        <h1>围棋教练 · AI 复盘</h1>
        <p className="subtitle">
          导入棋谱 → 逐手复盘 → 看清你与高手之间的那几目棋
        </p>
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
            <InfoPanel />
            <Overview />
          </div>
        </div>
      ) : (
        <div className="empty-hint">
          {status === "pending" ? "正在提交棋谱…" : "请导入 SGF 棋谱开始复盘。"}
        </div>
      )}
    </div>
  );
}
