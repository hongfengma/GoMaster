# 围棋教练 AI 复盘与解说系统 —— 本次工作概述

## 本轮完成（v0.2）

在 v0.1 基础上，整合了老马确认的技术决策与 DeepSeek 专家建议，迭代为 v0.2。

### 关键决策已确认
- 目标平台：Windows + macOS 跨平台（Electron 打包）
- 前端：React（Electron + React + Zustand）
- LLM：已有 DeepSeek Key，走官方兼容 OpenAI 协议
- KataGo：CPU 模式、无独显；stonebase 未配成功，后续老马发 GitHub 地址，由我下载配置到本地
- 商业模式：暂时自用，授权模块后置

### v0.2 新增/强化章节
- 竞品与现状：补充 AI Sensei / KaTrain / 星阵 / AlphaGo Teach / 开源实验
- KataGo 本地部署与集成：CPU 模式参数调优、部署计划（老马发地址后执行）、stonebase 失败说明
- Prompt 工程：纳入 DeepSeek 专家给出的具体复盘 Prompt 示例 + 4 个提升技巧（RAG 棋理库、局面自动检测、变化图约束、语气层次）
- 风险：强化 CPU 慢的应对（只分析关键手、缓存、低 visits）
- 附录：DeepSeek 专家的非开发替代方案（KaTrain+ChatGPT、AI Sensei 润色、GPT-4V）

## 待办
- 老马发 KataGo GitHub 地址 → 我下载配置本地、验证 CPU 模式
- 确认 DeepSeek 模型名
- 选定阶段1 执行启动时机
