import type { AnalyzeResponse, Snapshot } from "./types";

const BASE = ""; // 同源，由 server.py / Electron 静态托管提供

export async function startAnalyze(body: {
  sgf: string;
  visits?: number;
  threshold?: number;
  level?: string;
}): Promise<AnalyzeResponse> {
  const res = await fetch(`${BASE}/api/analyze`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = (await res.json().catch(() => ({}))) as Partial<AnalyzeResponse> & {
    error?: string;
  };
  if (!res.ok) throw new Error(data.error || `提交失败 ${res.status}`);
  return data as AnalyzeResponse;
}

export async function getSnapshot(taskId: string): Promise<Snapshot> {
  const res = await fetch(`${BASE}/api/analyze/${taskId}`);
  if (!res.ok) throw new Error(`轮询失败 ${res.status}`);
  return (await res.json()) as Snapshot;
}

export async function getHealth(): Promise<{ status: string }> {
  const res = await fetch(`${BASE}/api/health`);
  if (!res.ok) throw new Error("服务不可用");
  return (await res.json()) as { status: string };
}

export interface UserConfig {
  katago_exe: string;
  katago_cfg: string;
  analysis_dir: string;
  llm_base_url: string;
  llm_api_key: string;
  llm_model: string;
}

export async function getConfig(): Promise<UserConfig> {
  const res = await fetch(`${BASE}/api/config`);
  if (!res.ok) throw new Error(`读取配置失败 ${res.status}`);
  return (await res.json()) as UserConfig;
}

export async function saveConfig(cfg: UserConfig): Promise<UserConfig> {
  const res = await fetch(`${BASE}/api/config`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(cfg),
  });
  if (!res.ok) throw new Error(`保存配置失败 ${res.status}`);
  return (await res.json()) as UserConfig;
}

export async function testLLM(cfg: {
  base_url: string;
  api_key: string;
  model: string;
}): Promise<{ ok: boolean; model?: string; error?: string }> {
  const res = await fetch(`${BASE}/api/test-llm`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(cfg),
  });
  return (await res.json()) as { ok: boolean; model?: string; error?: string };
}
