export type StoneColor = "B" | "W";

export interface Top3Entry {
  move: string; // SGF 坐标
  wr: number; // 百分比数值
  pv: string[]; // GTP 坐标原始序列
}

export interface ReviewEntry {
  no: number;
  color: StoneColor;
  actual: string; // SGF 坐标或 "PASS"
  best: string; // SGF 坐标或 "PASS"
  best_pv: string[];
  best_pv_sgf: string[]; // SGF 坐标序列
  top3: Top3Entry[];
  phase: string;
  ai_wr: number; // 0..1，落子方视角
  actual_wr: number; // 0..1，落子方视角
  delta: number; // 0..1，ai_wr - actual_wr
  explain?: string;
}

export interface Meta {
  size: number;
  total_moves: number;
  komi: number;
  black_name?: string;
  white_name?: string;
}

export interface AnalyzeResponse {
  task_id: string;
  meta: Meta;
}

export type TaskStatus = "pending" | "running" | "done" | "error";

export interface Snapshot {
  task_id: string;
  status: TaskStatus;
  current?: number;
  meta?: Meta;
  entries: ReviewEntry[];
  mistakes: number[];
  error?: string;
  report_path?: string;
  created_at?: string;
}
