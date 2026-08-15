import { useEffect, useState } from "react";
import {
  getConfig,
  saveConfig,
  testLLM,
  type UserConfig,
} from "../api";

const EMPTY: UserConfig = {
  katago_exe: "",
  katago_cfg: "",
  nn_path: "",
  analysis_dir: "",
  llm_base_url: "https://api.deepseek.com/v1",
  llm_api_key: "",
  llm_model: "deepseek-chat",
};

export default function Settings({ onClose }: { onClose: () => void }) {
  const [cfg, setCfg] = useState<UserConfig>(EMPTY);
  const [loaded, setLoaded] = useState(false);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [msg, setMsg] = useState<{ type: "ok" | "err"; text: string } | null>(
    null
  );

  useEffect(() => {
    getConfig()
      .then((c) => setCfg(c))
      .catch(() => setMsg({ type: "err", text: "读取默认配置失败" }))
      .finally(() => setLoaded(true));
  }, []);

  const set = (k: keyof UserConfig, v: string) =>
    setCfg((c) => ({ ...c, [k]: v }));

  const onSave = async () => {
    setSaving(true);
    setMsg(null);
    try {
      const saved = await saveConfig(cfg);
      setCfg(saved);
      setMsg({ type: "ok", text: "已保存到本地 ~/.gomaster/config.json" });
    } catch (e) {
      setMsg({ type: "err", text: e instanceof Error ? e.message : "保存失败" });
    } finally {
      setSaving(false);
    }
  };

  const onTest = async () => {
    setTesting(true);
    setMsg(null);
    try {
      const r = await testLLM({
        base_url: cfg.llm_base_url,
        api_key: cfg.llm_api_key,
        model: cfg.llm_model,
      });
      if (r.ok) {
        const fb = r.fallback ? "，使用 .env 默认 Key" : "";
        setMsg({ type: "ok", text: `连接成功（模型：${r.model}${fb}）` });
      } else setMsg({ type: "err", text: r.error || "连接失败" });
    } catch (e) {
      setMsg({ type: "err", text: e instanceof Error ? e.message : "测试失败" });
    } finally {
      setTesting(false);
    }
  };

  if (!loaded) return null;

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h3>设置</h3>
          <button className="btn" onClick={onClose}>
            关闭
          </button>
        </div>
        <div className="modal-body">
          <h4>本地 KataGo</h4>
          <label>
            程序路径 (katago.exe / katago)
            <input
              type="text"
              value={cfg.katago_exe}
              placeholder="留空 = 自动探测内置版本"
              onChange={(e) => set("katago_exe", e.target.value)}
            />
          </label>
          <label>
            配置文件 (analysis_example.cfg)
            <input
              type="text"
              value={cfg.katago_cfg}
              placeholder="留空 = 自动探测内置版本"
              onChange={(e) => set("katago_cfg", e.target.value)}
            />
          </label>
          <label>
            神经网络文件 (.bin.gz)
            <div className="path-row">
              <input
                type="text"
                value={cfg.nn_path}
                placeholder="留空 = 自动探测（优先选最小网络，CPU 更快）"
                onChange={(e) => set("nn_path", e.target.value)}
              />
              <button
                type="button"
                className="btn small"
                onClick={async () => {
                  try {
                    const p = await window.electronAPI?.selectWeightFile?.();
                    if (p) set("nn_path", p);
                  } catch {
                    /* 非 Electron 环境忽略 */
                  }
                }}
              >
                浏览
              </button>
            </div>
            {cfg.current_nn && (
              <small className="field-hint">
                当前使用：{cfg.current_nn}
              </small>
            )}
            <small className="field-hint">
              网络越小 CPU 推理越快（如 b6c96 ~3.6MB 远快于 b10c384 ~37MB）。
              想提速可下载小网络放到 KataGo 目录并在此处指定，或留空让其自动探测。
            </small>
          </label>

          <h4>分析输出</h4>
          <label>
            复盘报告目录
            <input
              type="text"
              value={cfg.analysis_dir}
              placeholder="留空 = 与 SGF 同目录"
              onChange={(e) => set("analysis_dir", e.target.value)}
            />
          </label>

          <h4>解读大模型（OpenAI 兼容）</h4>
          <label>
            API Base URL
            <input
              type="text"
              value={cfg.llm_base_url}
              placeholder="https://api.deepseek.com/v1"
              onChange={(e) => set("llm_base_url", e.target.value)}
            />
          </label>
          <label>
            API Key
            <input
              type="password"
              value={cfg.llm_api_key}
              placeholder="留空 = 使用 .env 中的 DeepSeek Key"
              onChange={(e) => set("llm_api_key", e.target.value)}
            />
            <small className="field-hint">
              留空时测试连接与实际复盘都会使用 .env 中的默认 DeepSeek Key
            </small>
          </label>
          <label>
            模型名
            <input
              type="text"
              value={cfg.llm_model}
              placeholder="deepseek-chat"
              onChange={(e) => set("llm_model", e.target.value)}
            />
          </label>

          {msg && (
            <div className={msg.type === "ok" ? "ok-msg" : "err-msg"}>
              {msg.text}
            </div>
          )}
        </div>
        <div className="modal-footer">
          <button className="btn" disabled={testing} onClick={onTest}>
            {testing ? "测试中…" : "测试连接"}
          </button>
          <button
            className="btn primary"
            disabled={saving}
            onClick={onSave}
          >
            {saving ? "保存中…" : "保存"}
          </button>
        </div>
      </div>
    </div>
  );
}
