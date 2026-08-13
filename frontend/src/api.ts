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
