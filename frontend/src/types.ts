export type StoneColor = "B" | "W";

export interface Top3Entry {
  move: string; // GTP 记号（如 Q16），供讲解展示
  wr: number; // 百分比数值
  pv: string[]; // GTP 坐标原始序列
}

export interface ReviewEntry {
  no: number;
  color: StoneColor;
  actual: string; // GTP 记号（如 D6 / Q16），界面展示与讲解用
  actual_sgf?: string; // SGF 坐标（如 dd / qd），棋盘高亮绘制用；缺失时取 actual 兼容旧数据
  best: string; // GTP 记号（如 F6 / Q16），界面展示与讲解用
  best_sgf?: string; // SGF 坐标（变化图绘制用）；缺失时取 best 兼容旧数据
  best_pv: string[];
  best_pv_sgf: string[]; // SGF 坐标序列
  stones?: { x: number; y: number; color: StoneColor }[]; // 该手落子后的完整局面（报告图例用）
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
  winrates?: WinRatePoint[];
  error?: string;
  report_path?: string;
  created_at?: string;
}

export interface WinRatePoint {
  move: number; // 手序（1 起）
  wr: number | null; // 黑方视角胜率 0..1，null 表示该手分析缺失
  is_mistake: boolean;
}
