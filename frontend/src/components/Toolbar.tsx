import { useState, type ChangeEvent } from "react";
import { useAppStore } from "../store";

const DEMO_SGF =
  "(;GM[1]FF[4]CA[UTF-8]SZ[9]KM[7.5]PB[黑方(你)]PW[白方(对手)];B[cc];W[gg];B[cg];W[gc];B[ee];W[gi];B[ce];W[ig];B[eg];W[ii];B[ca];W[ih];B[cb];W[hi];B[ac];W[hg];B[aa];W[gh];B[bb];W[fi])";

export default function Toolbar() {
  const level = useAppStore((s) => s.level);
  const visits = useAppStore((s) => s.visits);
  const setLevel = useAppStore((s) => s.setLevel);
  const setVisits = useAppStore((s) => s.setVisits);
  const startReview = useAppStore((s) => s.startReview);
  const status = useAppStore((s) => s.status);
  const [fileText, setFileText] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const run = async (sgf: string) => {
    if (!sgf.trim()) {
      setErr("请选择 SGF 文件或粘贴内容");
      return;
    }
    setErr(null);
    setBusy(true);
    try {
      await startReview(sgf);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "提交失败");
    } finally {
      setBusy(false);
    }
  };

  const onFile = (e: ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (!f) return;
    const reader = new FileReader();
    reader.onload = () => setFileText(String(reader.result));
    reader.readAsText(f);
  };

  const analyzing = status === "running" || status === "pending";

  return (
    <div className="toolbar">
      <div className="toolbar-row">
        <label className="file-label">
          选择 SGF 文件
          <input type="file" accept=".sgf,text/plain" onChange={onFile} />
        </label>
        <span className="or">或</span>
        <textarea
          className="sgf-text"
          placeholder="在此粘贴 SGF 文本…"
          value={fileText}
          onChange={(e) => setFileText(e.target.value)}
        />
      </div>
      <div className="toolbar-row">
        <label>
          用户水平
          <select value={level} onChange={(e) => setLevel(e.target.value)}>
            <option value="入门">入门</option>
            <option value="进阶">进阶</option>
            <option value="挑战">挑战</option>
          </select>
        </label>
        <label>
          分析精度 (visits)
          <input
            type="number"
            min={20}
            max={400}
            step={10}
            value={visits}
            onChange={(e) => setVisits(Number(e.target.value) || 80)}
          />
        </label>
        <button
          className="btn primary"
          disabled={busy || analyzing}
          onClick={() => run(fileText)}
        >
          {analyzing ? "分析中…" : "开始复盘"}
        </button>
        <button
          className="btn"
          disabled={busy || analyzing}
          onClick={() => {
            setFileText(DEMO_SGF);
            run(DEMO_SGF);
          }}
        >
          载入示例
        </button>
      </div>
      {err && <div className="err">{err}</div>}
    </div>
  );
}
