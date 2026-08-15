# -*- coding: utf-8 -*-
"""DeepSeek 解说生成器（GoMaster v0.8 Phase A · 准确性优先）。

改造要点（相对 v0.7）：
  - 提示词从「具体棋理 + 语气鼓励/生活化比喻」改为「精确、可验证、规范棋术语」，
    删除软性口语要求，加入「禁止杜撰棋理/棋谚、不确定明说」硬约束。
  - 输出结构化为 5 个 Markdown 分段（问题定性/关键棋理/推荐点意图/后续推演/不确定点），
    便于前端分区展示、也便于人工校验「引用的棋理是否真实存在」。
  - 温度 0.25 → 0.1，降低发散与编造。
  - RAG 检索 query 增强：带 阶段(phase) + 区域(zone) 概念标签，命中更准（见 _zone_of）。
  - 所有坐标统一 GTP 记号 + 基于真实局面讲解 + 坐标铁律，继承自 v0.7 并保留。
"""
import json
import re
import ssl
import time
import urllib.request

from config import (DEEPSEEK_API_KEY, DEEPSEEK_MODEL, DEEPSEEK_URL, USER_LEVEL)
from go_board import gtp_to_xy

try:
    from rag import retrieve as _rag_retrieve
except Exception:  # rag 模块缺失时优雅降级，不影响主流程
    _rag_retrieve = None


def _call_deepseek(system: str, user: str, max_tokens=800, temperature=0.1,
                   retries=2):
    """调用 DeepSeek。对空内容/瞬时错误/非法坐标自动重试或抛异常，由上层 fallback。"""
    last_err = None
    for attempt in range(retries + 1):
        try:
            payload = {
                "model": DEEPSEEK_MODEL,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "max_tokens": max_tokens,
                "temperature": temperature,
                "stream": False,
            }
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                DEEPSEEK_URL,
                data=data,
                headers={
                    "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
                    "Content-Type": "application/json",
                },
            )
            ctx = ssl.create_default_context()
            with urllib.request.urlopen(req, timeout=60, context=ctx) as r:
                resp = json.loads(r.read().decode("utf-8"))
            msg = resp["choices"][0]["message"]
            content = (msg.get("content") or "").strip()
            if not content:
                content = (msg.get("reasoning_content") or "").strip()
            if not content:
                raise ValueError("DeepSeek 返回空内容（疑似偶发）")
            # 坐标格式硬校验：不允许出现 ddd、qq、ehh、fch 等连续 2+ 位小写字母
            if _has_bad_coords(content):
                raise ValueError(f"DeepSeek 输出含非法坐标: {_bad_coord_samples(content)}")
            return content
        except Exception as e:
            last_err = e
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
                continue
    raise last_err


def _has_bad_coords(text: str) -> bool:
    """检测是否包含 dd、qq、ehh、fch 等非法坐标（连续 2+ 个小写字母）。"""
    for m in re.finditer(r"[a-z]{2,}", text):
        w = m.group()
        if w in {"as", "is", "it", "of", "to", "in", "on", "at", "by", "for", "or", "if", "up", "so"}:
            continue
        return True
    return False


def _bad_coord_samples(text: str) -> str:
    samples = []
    for m in re.finditer(r"[a-z]{2,}", text):
        w = m.group()
        if w not in {"as", "is", "it", "of", "to", "in", "on", "at", "by", "for", "or", "if", "up", "so"}:
            samples.append(w)
            if len(samples) >= 3:
                break
    return ",".join(samples) if samples else "(unknown)"


def _fmt_pv(pv_gtp, n=6):
    """把 GTP 变化序列直出为「A16 → B17 → …」字符串（不再转回 SGF）。"""
    if not pv_gtp:
        return "（无）"
    out = []
    for c in pv_gtp[:n]:
        if not c or str(c).lower() in ("pass", "resign"):
            out.append("PASS")
        else:
            out.append(str(c).upper())
    return " → ".join(out)


def _zone_of(gtp, size):
    """由 GTP 坐标推断盘面区域：角部 / 边上 / 中腹（供 RAG 检索与讲解方位）。"""
    if not gtp or str(gtp).lower() in ("pass", "resign"):
        return ""
    xy = gtp_to_xy(str(gtp).upper(), size)
    if not xy:
        return ""
    x, y = xy  # 0-based
    if x < 0 or y < 0 or x >= size or y >= size:
        return ""  # 越界坐标（理论上不该出现）不做区域判断
    edge = lambda d: min(d, size - 1 - d)
    ce, re = edge(x), edge(y)
    if ce <= 2 and re <= 2:
        return "角部"
    if ce <= 2 or re <= 2:
        return "边上"
    return "中腹"


def _fallback_explain(move_no, color_cn, actual_gtp, best_gtp,
                      ai_wr, actual_wr, delta, size, phase="中盘",
                      best_pv_gtp=None, zone=""):
    """LLM 调用失败时的兜底讲解：完全基于 KataGo 数据，保证每个失误手都有内容。"""
    pv = _fmt_pv(best_pv_gtp or [], 5)
    return (
        f"### 问题定性\n这手 {actual_gtp} 不如 AI 推荐的 **{best_gtp}**："
        f"走推荐点，{color_cn}方胜率约 **{ai_wr:.1f}%**；实际走子后降到约 {actual_wr:.1f}%，"
        f"下降了 **{delta:.1f} 个百分点**。当前处于「{phase}」阶段（{zone}）。\n\n"
        f"### 推荐点意图\n若改走 {best_gtp}，后续大致为：{pv}；相比实际落子，能更好占到要点、减少被对方反抢。\n\n"
        f"### 关键棋理\n（大模型暂不可用，以下仅基于数据，未引用棋理，建议摆谱验证。）\n\n"
        f"### 后续推演\n关注这一手是否加固了自己、是否把关键位置让给了对方。\n\n"
        f"### 不确定点\n无（兜底内容不含棋理判断，请以 KataGo 数据为准）。"
    )


def explain_move(move_no, color_cn, actual_sgf, best_sgf,
                 ai_wr, actual_wr, delta, best_pv_gtp, size,
                 recent_moves_sgf, level=USER_LEVEL, top3=None, phase="中盘",
                 board_ascii=None):
    """生成单手复盘讲解文本（结构化 Markdown，准确性优先）。

    参数说明：
      - actual_sgf / best_sgf：GTP 记号（如 Q16），由 review.py 转换后传入。
      - recent_moves_sgf：最近几手（GTP 记号）字符串列表。
      - board_ascii：落子前的真实局面 ASCII 快照（含 ★推荐点 / ◆实际点）。
      - top3: AI 前三候选 [{move,wr,pv}]；phase: 布局/中盘/官子。
    """
    recent = "，".join(recent_moves_sgf[-6:]) if recent_moves_sgf else "（开局，盘面基本为空）"
    pv_str = _fmt_pv(best_pv_gtp, 6)
    cand_lines = []
    for idx, t in enumerate((top3 or [])[:3], 1):
        tpv = _fmt_pv(t.get("pv", []), 4)
        cand_lines.append(f"{idx}. {t.get('move','?')}  胜率约 {t.get('wr',0):.1f}%"
                          + (f"（后续：{tpv}）" if tpv != "（无）" else ""))
    cand_text = "\n".join(cand_lines) if cand_lines else "（无）"

    zone = _zone_of(actual_sgf, size)

    # —— RAG 知识库检索（增强 query：带 phase + zone 概念标签）——
    rag_text = ""
    if _rag_retrieve:
        try:
            q = (f"{color_cn}方 第{move_no}手 实际{actual_sgf} 推荐{best_sgf} "
                 f"{phase} {zone}")
            chunks = _rag_retrieve(q, top_k=3, meta={
                "phase": phase, "zone": zone, "color": color_cn})
            if chunks:
                rag_text = "\n\n".join(
                    f"· 《{c.get('title','')}》（{c.get('category','')}）：{c.get('content','')}"
                    for c in chunks
                )
        except Exception:
            rag_text = ""

    system = (
        f"你是一位严谨的围棋教练，正在为「{level}」水平的爱好者做逐手复盘。\n"
        f"【核心要求：准确优先于通顺】\n"
        f"1. 讲解必须精确、可验证，使用规范棋术语（定式、棋形、手筋、厚薄、势力、眼位、官子、先手/后手等）。\n"
        f"2. 紧扣本手得失，给出「具体棋理 + 局部棋形 + 后续推演」。禁止空泛套话，"
        f"禁止为了通顺而编造棋理或用生活化比喻搪塞（如「好比……」「就像……」）。\n"
        f"3. 若引用定式、棋谚或棋形：必须来自公认棋理或下方【参考资料】，并说明它在本局面如何体现；"
        f"不得凭空杜撰名称。若你不确定某条棋理是否适用，必须在「不确定点」里明说，"
        f"或写「此处建议摆谱验证」，绝不可含糊带过。\n"
        f"4. 描述落点时务必使用方位词（左上/右上/左下/右下/星位/小目/三三/边上/中腹）。\n"
        f"5. 输出必须严格按下列 5 个 Markdown 标题分段，不要增减段落：\n"
        f"### 问题定性\n### 关键棋理\n### 推荐点意图\n### 后续推演\n### 不确定点\n"
        f"6. 全程使用 Markdown（**加粗**、列表），总篇幅控制在 280 字以内。\n\n"
        f"【坐标铁律】本系统所有坐标均采用 GTP 记号：1 个大写英文字母 + 1–2 位数字，"
        f"例如 Q16、D4、K10。你输出中提到的任何落点，都必须是这种格式。"
        f"绝对禁止输出 dd、qq、ddd、ehh、fch 等两位或三位小写字母串。"
        f"如果某个点在脑中是小写两位字母（如 dd），你必须先转换成 GTP（如 D4）再写。"
        f"\n\n【正确示例】Q16、D6、F6、K10、A1、T19。"
        f"【错误示例】dd、qq、ddd、ehh、fch。"
        f"输出前请自检：每出现一次坐标，必须满足「首字符大写字母 A–T（跳 I）+ 数字」。"
    )

    board_block = (
        f"【当前局面】是第 {move_no} 手（{color_cn}方）落子前的真实棋盘"
        f"（ASCII 表示：列 A..T 从左到右、行 1..{size} 从下到上；"
        f"X=黑子 O=白子 .=空点；★=AI 推荐点 ◆=本手实际落子点）：\n\n{board_ascii}\n\n"
        if board_ascii else
        f"【当前局面】第 {move_no} 手（{color_cn}方）落子前。"
    )

    user = (
        f"这是一盘 {size} 路棋盘的复盘，本手处于「{phase}」阶段、位于「{zone or '棋盘'}」。\n\n"
        f"{board_block}"
        f"【该方实际落子】{actual_sgf}（即盘面上 ◆ 处）\n"
        f"【AI 推荐落子】{best_sgf}（即盘面上 ★ 处）\n"
        f"【前情】最近几手依次是：{recent}（均为 GTP 坐标：列字母+行数字）\n"
        f"【胜率对比】若走推荐点，{color_cn}方胜率约 {ai_wr:.1f}%；实际走子后降到约 {actual_wr:.1f}%，"
        f"下降了约 {delta:.1f} 个百分点。\n"
        f"【AI 前三候选（{color_cn}方视角胜率）】\n{cand_text}\n"
        f"【AI 推荐后续变化（仅是推演，不是已经下的子）】{best_sgf} → {pv_str}\n\n"
        f"请严格按下列要求讲解（Markdown，280 字以内，5 段结构）：\n"
        f"### 问题定性\n实际这手（{actual_sgf}）的问题具体是什么"
        f"（子力重复/方向偏差/忽视弱棋/被抢要点/死活误判/官子损目/孤棋未安顿…）？"
        f"结合盘面方位（如「右上角」「左边星位」「三三」「小目」「中腹」）与棋形说清。\n"
        f"### 关键棋理\n点出本局面相关的 1–2 条棋理/定式/棋形/棋谚，并说明它在此处如何体现；"
        f"若下方【参考资料】中有相关条目，优先引用并注明。\n"
        f"### 推荐点意图\n{best_sgf} 实现了什么意图"
        f"（拆边/挂角/守角/打入/侵消/补强/出头/做活/杀棋/收官/争先…）。\n"
        f"### 后续推演\n若走 {best_sgf}，对方大概会怎么应、2~3 手后预期形势；相比实际落子具体多出了什么。\n"
        f"### 不确定点\n若对棋理适用性或后续变化无把握，在此明说；若确信无误，写「无」。\n\n"
        f"注意：变化图（【AI 推荐后续变化】）只是假设性推演，绝不可把变化图里的子当作已经落下的子来讲解，"
        f"也绝不可只按变化图各子的位置铺陈。必须基于上面的【当前局面】和【该方实际落子 {actual_sgf}】来讲。"
    )
    if rag_text:
        user += f"\n\n【参考资料】（若与本题相关请引用并注明出处，不相关则忽略）\n{rag_text}\n"

    try:
        return _call_deepseek(system, user, max_tokens=700, temperature=0.1)
    except Exception:
        return _fallback_explain(move_no, color_cn, actual_sgf, best_sgf,
                                 ai_wr, actual_wr, delta, size, phase=phase,
                                 best_pv_gtp=best_pv_gtp, zone=zone)
