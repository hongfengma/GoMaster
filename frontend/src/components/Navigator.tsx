import { useAppStore } from "../store";

export default function Navigator() {
  const total = useAppStore((s) => s.meta?.total_moves ?? 0);
  const current = useAppStore((s) => s.current);
  const goToMove = useAppStore((s) => s.goToMove);
  const status = useAppStore((s) => s.status);

  if (total === 0) return null;
  const analyzing = status === "running" || status === "pending";

  return (
    <div className="navigator">
      <button
        className="btn"
        onClick={() => goToMove(current - 1)}
        disabled={current <= 0}
      >
        ◀ 上一手
      </button>
      <input
        type="range"
        min={0}
        max={total}
        value={current}
        onChange={(e) => goToMove(Number(e.target.value))}
      />
      <button
        className="btn"
        onClick={() => goToMove(current + 1)}
        disabled={current >= total}
      >
        下一手 ▶
      </button>
      <span className="move-label">
        第 {current} / {total} 手
      </span>
      {analyzing && <span className="status-run">分析中…</span>}
    </div>
  );
}
