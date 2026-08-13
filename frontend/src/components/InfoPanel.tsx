import { useAppStore } from "../store";
import MarkdownView from "./MarkdownView";

const pct = (x: number) => (x * 100).toFixed(1) + "%";
const sign = (x: number) => (x >= 0 ? "+" : "") + (x * 100).toFixed(1) + "%";

export default function InfoPanel() {
  const current = useAppStore((s) => s.current);
  const entries = useAppStore((s) => s.entries);
  const mistakes = useAppStore((s) => s.mistakes);
  const meta = useAppStore((s) => s.meta);

  if (!meta) return null;
  if (current < 1) {
    return (
      <div className="panel">
        <h3>当前局面</h3>
        <div className="kv">
          <span className="k">状态</span>
          <span className="v">开局（尚未落子）</span>
        </div>
      </div>
    );
  }
  const e = entries.find((x) => x.no === current);
  if (!e) {
    return (
      <div className="panel">
        <h3>第 {current} 手</h3>
        <div className="kv">
          <span className="k">状态</span>
          <span className="v">分析中…</span>
        </div>
      </div>
    );
  }
  const isMistake = mistakes.includes(current);
  const cn = e.color === "B" ? "黑" : "白";
  const deltaCls = e.delta >= 0 ? "delta-bad" : "delta-good";

  return (
    <div className="panel">
      <h3>
        第 {current} 手（{cn}方）
        {isMistake && <span className="badge-mistake">⚠ 失误手</span>}
      </h3>
      <div className="kv">
        <span className="k">你的落子</span>
        <span className="v">{e.actual_gtp ?? e.actual}</span>
        <span className="k">AI 推荐</span>
        <span className="v best">{e.best_gtp ?? e.best}</span>
        <span className="k">胜率(推荐)</span>
        <span className="v">{pct(e.ai_wr)}</span>
        <span className="k">胜率(实际)</span>
        <span className="v">{pct(e.actual_wr)}</span>
        <span className="k">胜率差</span>
        <span className={`v ${deltaCls}`}>{sign(e.delta)}</span>
      </div>
      <h4>教练讲解</h4>
      {e.explain ? (
        <MarkdownView text={e.explain} />
      ) : (
        <div className="explain-empty">（该手暂无讲解）</div>
      )}
    </div>
  );
}
