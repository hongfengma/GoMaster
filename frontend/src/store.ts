import { create } from "zustand";
import type { Meta, ReviewEntry, Snapshot, TaskStatus, WinRatePoint, StoneColor } from "./types";
import { startAnalyze, getSnapshot } from "./api";

let pollTimer: ReturnType<typeof setTimeout> | null = null;

interface AppState {
  taskId: string | null;
  status: TaskStatus | null;
  meta: Meta | null;
  entries: ReviewEntry[];
  mistakes: number[];
  winrates: WinRatePoint[];
  current: number;
  error: string | null;
  reportPath: string | null;
  level: string;
  visits: number;
  showPV: boolean; // 后续推演（变化图）是否在棋盘上显示，默认关
  perspective: StoneColor; // 胜率曲线与失误列表的查看视角："B"黑方 / "W"白方
  setPerspective: (p: StoneColor) => void;
  setLevel: (l: string) => void;
  setVisits: (v: number) => void;
  togglePV: () => void;
  startReview: (sgf: string) => Promise<void>;
  goToMove: (no: number) => void;
  stop: () => void;
}

export const useAppStore = create<AppState>((set, get) => ({
  taskId: null,
  status: null,
  meta: null,
  entries: [],
  mistakes: [],
  winrates: [],
  current: 0,
  error: null,
  reportPath: null,
  level: "入门",
  visits: 80,
  showPV: false,
  perspective: "B",
  setPerspective: (p) => set({ perspective: p }),
  setLevel: (l) => set({ level: l }),
  setVisits: (v) => set({ visits: v }),
  togglePV: () => set((s) => ({ showPV: !s.showPV })),
  startReview: async (sgf) => {
    if (pollTimer) {
      clearTimeout(pollTimer);
      pollTimer = null;
    }
    set({
      taskId: null,
      status: "pending",
      meta: null,
      entries: [],
      mistakes: [],
      winrates: [],
      current: 0,
      error: null,
      reportPath: null,
    });
    const d = await startAnalyze({
      sgf,
      visits: get().visits,
      level: get().level,
    });
    set({ taskId: d.task_id, meta: d.meta, current: d.meta.total_moves });
    schedulePoll();
  },
  goToMove: (no) => {
    const total = get().meta?.total_moves ?? 0;
    set({ current: Math.max(0, Math.min(total, no)) });
  },
  stop: () => {
    if (pollTimer) {
      clearTimeout(pollTimer);
      pollTimer = null;
    }
  },
}));

function schedulePoll() {
  if (pollTimer) clearTimeout(pollTimer);
  pollTimer = setTimeout(poll, 1000);
}

async function poll() {
  const st = useAppStore.getState();
  if (!st.taskId) return;
  try {
    const d: Snapshot = await getSnapshot(st.taskId);
    useAppStore.setState((s) => ({
      status: d.status,
      meta: d.meta ?? s.meta,
      entries: d.entries ?? s.entries,
      mistakes: (d.mistakes ?? []).slice().sort((a, b) => a - b),
      winrates: d.winrates ?? s.winrates,
      error: d.error ?? null,
      reportPath: d.report_path ?? null,
    }));
    if (d.status === "running" || d.status === "pending") schedulePoll();
    else pollTimer = null;
  } catch {
    // 网络抖动时继续重试
    schedulePoll();
  }
}
