# -*- coding: utf-8 -*-
"""DeepSeek 解说生成器。

把 KataGo 的结构化分析（实际落子 / 推荐选点 / 胜率差 / 变化树）组装成
面向初学者友好的 Prompt，调用 deepseek-v4-flash 生成讲解。
"""
import json
import ssl
import time
import urllib.request

from config import (DEEPSEEK_API_KEY, DEEPSEEK_MODEL, DEEPSEEK_URL, USER_LEVEL)
from go_board import gtp_to_xy, xy_to_sgf


def _call_deepseek(system: str, user: str, max_tokens=1500, temperature=0.6,
                   retries=2):
    """调用 DeepSeek。对空内容/瞬时错误自动重试，避免偶发空响应导致讲解缺失。"""
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
            # 兼容推理模型（如仍用 deepseek-v4-flash）：正文可能在 reasoning_content
            if not content:
                content = (msg.get("reasoning_content") or "").strip()
            if not content:
                raise ValueError("DeepSeek 返回空内容（疑似偶发）")
            return content
        except Exception as e:
            last_err = e
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))  # 简单退避后重试
                continue
    raise last_err


def _fmt_pv(pv_gtp, size, n=6):
    """把 GTP 变化序列转成 SGF 坐标串，最多 n 手。"""
    if not pv_gtp:
        return "（无）"
    out = []
    for c in pv_gtp[:n]:
        xy = gtp_to_xy(c, size)
        if xy is None:
            out.append("PASS")
        else:
            out.append(xy_to_sgf(*xy))
    return " → ".join(out)


def _fallback_explain(move_no, color_cn, actual_sgf, best_sgf,
                      ai_wr, actual_wr, delta, size, phase="中盘",
                      best_pv_gtp=None):
    """LLM 调用失败时的兜底讲解：完全基于 KataGo 数据，保证每个失误手都有内容。"""
    pv = _fmt_pv(best_pv_gtp or [], size, 5)
    return (
        f"这手 {actual_sgf} 不如 AI 推荐的 **{best_sgf}**："
        f"走推荐点，{color_cn}方胜率约 **{ai_wr:.1f}%**；实际走子后降到约 {actual_wr:.1f}%，"
        f"下降了 **{delta:.1f} 个百分点**。\n\n"
        f"当前处于「{phase}」阶段，差距主要源于落点方向或子力效率。"
        f"若改走 {best_sgf}，后续大致为：{pv}；相比实际落子，能更好占到要点、减少被对方反抢。\n\n"
        f"建议复盘时重点看：这一手是否加固了自己、是否把关键位置让给了对方。"
    )


def explain_move(move_no, color_cn, actual_sgf, best_sgf,
                 ai_wr, actual_wr, delta, best_pv_gtp, size,
                 recent_moves_sgf, level=USER_LEVEL, top3=None, phase="中盘"):
    """生成单手复盘讲解文本。top3: AI 前三候选 [{move,wr,pv}]；phase: 布局/中盘/官子。"""
    recent = "，".join(recent_moves_sgf[-6:]) if recent_moves_sgf else "（开局）"
    pv_str = _fmt_pv(best_pv_gtp, size, 6)
    cand_lines = []
    for idx, t in enumerate((top3 or [])[:3], 1):
        tpv = _fmt_pv(t.get("pv", []), size, 4)
        cand_lines.append(f"{idx}. {t.get('move','?')}  胜率约 {t.get('wr',0):.1f}%"
                          + (f"（后续：{tpv}）" if tpv != "（无）" else ""))
    cand_text = "\n".join(cand_lines) if cand_lines else "（无）"

    system = (
        f"你是一位资深围棋教练，正在为「{level}」水平的爱好者做逐手复盘。"
        f"讲解要求：紧扣本手得失，给出「具体棋理 + 局部棋形 + 后续推演」，禁止空泛套话；"
        f"可引用定式、棋形、手筋、厚薄、势力、眼位、官子等，但必须结合本局面解释「为什么」；"
        f"若引用棋谚，须说明它在当前局面如何体现，不得只甩「敌之要点即我之要点」而不解释。"
        f"语气鼓励、易懂，控制在 240 字以内，可用 Markdown（**加粗**、列表）。"
    )
    user = (
        f"这是一盘 {size} 路棋盘的复盘。第 {move_no} 手（{color_cn}方，当前处于「{phase}」阶段）"
        f"出现了明显分岔，请讲解：\n\n"
        f"【前情】最近几手依次是：{recent}\n"
        f"【该方实际落子】{actual_sgf}\n"
        f"【AI 推荐落子】{best_sgf}\n"
        f"【胜率对比】若走推荐点，{color_cn}方胜率约 {ai_wr:.1f}%；实际走子后降到约 {actual_wr:.1f}%，"
        f"下降了约 {delta:.1f} 个百分点。\n"
        f"【AI 前三候选（{color_cn}方视角胜率）】\n{cand_text}\n"
        f"【AI 推荐后续变化】{best_sgf} → {pv_str}\n\n"
        f"请按如下结构讲解（用 Markdown）：\n"
        f"1）**问题**：实际这手的问题具体是什么（子力重复 / 方向偏差 / 忽视弱棋 / 被抢要点 / 死活误判 / 官子损目等）？结合棋形说清。\n"
        f"2）**为什么推荐 {best_sgf}**：它实现了什么战略或战术意图（拆边 / 挂角 / 守角 / 打入 / 侵消 / 补强 / 出头 / 做活 / 杀棋 / 收官…）。\n"
        f"3）**推演**：若走 {best_sgf}，对方大概会怎么应、2~3 手后预期形势如何；相比实际落子具体多出了什么。\n"
        f"4）**棋理点睛**：用一条贴切的棋理或棋谚收束，并说明它在此处如何体现。"
    )
    try:
        return _call_deepseek(system, user, max_tokens=1800, temperature=0.5)
    except Exception:
        return _fallback_explain(move_no, color_cn, actual_sgf, best_sgf,
                                 ai_wr, actual_wr, delta, size, phase=phase,
                                 best_pv_gtp=best_pv_gtp)
