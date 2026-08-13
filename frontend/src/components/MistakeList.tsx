import { useAppStore } from "../store";

const sign = (x: number) => (x >= 0 ? "+" : "") + (x * 100).toFixed(1) + "%";

export default function MistakeList() {
  const mistakes = useAppStore((s) => s.mistakes);
  const entries = useAppStore((s) => s.entries);
  const goToMove = useAppStore((s) => s.goToMove);

  if (!mistakes.length) {
    return (
      <div className="mistake-list">
        <div className="pending">（暂无可讲解的失误手）</div>
      </div>
    );
  }
  // 按手序（从小到大）排列，便于用户顺着棋谱顺序回顾失误手
  const ordered = [...mistakes].sort((a, b) => a - b);
  return (
    <div className="mistake-list">
      {ordered.map((no) => {
        const e = entries.find((x) => x.no === no);
        const cn = e ? (e.color === "B" ? "黑" : "白") : "";
        const ready = e && e.explain;
        return (
          <div
            key={no}
            className="mistake-item"
            onClick={() => goToMove(no)}
          >
            <span>
              第 {no} 手（{cn}） 你:{e?.actual_gtp ?? e?.actual ?? "…"} → 推荐:{e?.best_gtp ?? e?.best ?? "…"}
            </span>
            <span className="delta">
              {e ? sign(e.delta) : "…"}
              {ready ? "" : " · 讲解中"}
            </span>
          </div>
        );
      })}
    </div>
  );
}
