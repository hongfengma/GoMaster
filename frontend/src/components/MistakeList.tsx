import { useAppStore } from "../store";

const sign = (x: number) => (x >= 0 ? "+" : "") + (x * 100).toFixed(1) + "%";

export default function MistakeList() {
  const mistakes = useAppStore((s) => s.mistakes);
  const entries = useAppStore((s) => s.entries);
  const goToMove = useAppStore((s) => s.goToMove);
  const perspective = useAppStore((s) => s.perspective);

  // 仅展示「当前视角方」的失误手
  const sideNos = mistakes.filter((no) => {
    const e = entries.find((x) => x.no === no);
    return e && e.color === perspective;
  });
  if (!sideNos.length) {
    return (
      <div className="mistake-list">
        <div className="pending">（该方暂无可讲解的失误手）</div>
      </div>
    );
  }
  // 按手序（从小到大）排列，便于用户顺着棋谱顺序回顾失误手
  const ordered = [...sideNos].sort((a, b) => a - b);
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
              第 {no} 手（{cn}） 你:{e?.actual ?? "…"} → 推荐:{e?.best ?? "…"}
            </span>
            <span className="delta">
              {e ? sign(e.delta) : "…"}
              {ready ? "" : " · 讲解中"}
            </span>
            {e?.category && (
              <div className="mistake-category">{e.category}</div>
            )}
            {e?.fact_tags && e.fact_tags.length > 0 && (
              <div className="fact-tags">
                {e.fact_tags.map((t) => (
                  <span
                    key={t}
                    className={
                      "fact-tag" +
                      (/接不归|自紧气|空三角|方四|凝形|裂形/.test(t)
                        ? " bad"
                        : /定式偏离|星位|小目|三三|目外|高目|超高目/.test(t)
                        ? " joseki"
                        : "")
                    }
                  >
                    {t}
                  </span>
                ))}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
