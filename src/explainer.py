# -*- coding: utf-8 -*-
"""DeepSeek 解说生成器。

把 KataGo 的结构化分析（实际落子 / 推荐选点 / 胜率差 / 变化树）与「落子前真实局面」
的 ASCII 快照组装成面向初学者友好的 Prompt，调用 deepseek-chat 生成讲解。

核心改进：
  - 所有坐标统一用 GTP 记号（如 Q16），不再使用 SGF 两位字母（qd），模型可定位。
  - 把「落子前真实局面」渲染成 ASCII 棋盘喂给模型，使其具备左右上下的空间认知，
    从根本上解决「讲解被变化图带偏 / 方位说不清」的问题。
  - 明确约束：变化图（PV）只是推演，绝非已落子，禁止按变化图各子位置铺陈。
  - 可选接入 RAG 知识库（rag.py），把相关棋理/定式作为【参考资料】喂给模型。
"""
import json
import ssl
import time
import urllib.request

from config import (DEEPSEEK_API_KEY, DEEPSEEK_MODEL, DEEPSEEK_URL, USER_LEVEL)

try:
    from rag import retrieve as _rag_retrieve
except Exception:  # rag 模块缺失时优雅降级，不影响主流程
    _rag_retrieve = None


def _call_deepseek(system: str, user: str, max_tokens=800, temperature=0.25,
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
    import re
    # 匹配连续两个及以上小写字母，且不是英语常见短词（如 as/is 可放行，但围棋坐标不会单独出现）
    for m in re.finditer(r"[a-z]{2,}", text):
        w = m.group()
        # 放行少量常见英文单词，其余视为非法坐标
        if w in {"as", "is", "it", "of", "to", "in", "on", "at", "by", "for", "or", "if", "up", "so"}:
            continue
        return True
    return False


def _bad_coord_samples(text: str) -> str:
    import re
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


def _fallback_explain(move_no, color_cn, actual_gtp, best_gtp,
                      ai_wr, actual_wr, delta, size, phase="中盘",
                      best_pv_gtp=None):
    """LLM 调用失败时的兜底讲解：完全基于 KataGo 数据，保证每个失误手都有内容。"""
    pv = _fmt_pv(best_pv_gtp or [], 5)
    return (
        f"这手 {actual_gtp} 不如 AI 推荐的 **{best_gtp}**："
        f"走推荐点，{color_cn}方胜率约 **{ai_wr:.1f}%**；实际走子后降到约 {actual_wr:.1f}%，"
        f"下降了 **{delta:.1f} 个百分点**。\n\n"
        f"当前处于「{phase}」阶段，差距主要源于落点方向或子力效率。"
        f"若改走 {best_gtp}，后续大致为：{pv}；相比实际落子，能更好占到要点、减少被对方反抢。\n\n"
        f"建议复盘时重点看：这一手是否加固了自己、是否把关键位置让给了对方。"
    )


def explain_move(move_no, color_cn, actual_sgf, best_sgf,
                 ai_wr, actual_wr, delta, best_pv_gtp, size,
                 recent_moves_sgf, level=USER_LEVEL, top3=None, phase="中盘",
                 board_ascii=None):
    """生成单手复盘讲解文本。

    参数说明：
      - actual_sgf / best_sgf：已经是 GTP 记号（如 Q16），由 review.py 转换后传入。
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

    # —— 可选：RAG 知识库检索，作为【参考资料】注入 ——
    rag_text = ""
    if _rag_retrieve:
        try:
            q = f"{color_cn}方 第{move_no}手 实际{actual_sgf} 推荐{best_sgf} {phase}"
            chunks = _rag_retrieve(q, top_k=3)
            if chunks:
                rag_text = "\n\n".join(
                    f"· 《{c.get('title','')}》：{c.get('content','')}" for c in chunks
                )
        except Exception:
            rag_text = ""

    system = (
        f"你是一位资深围棋教练，正在为「{level}」水平的爱好者做逐手复盘。"
        f"讲解要求：紧扣本手得失，给出「具体棋理 + 局部棋形 + 后续推演」，禁止空泛套话；"
        f"可引用定式、棋形、手筋、厚薄、势力、眼位、官子等，但必须结合本局面解释「为什么」；"
        f"若引用棋谚，须说明它在当前局面如何体现，不得只甩「敌之要点即我之要点」而不解释。"
        f"描述落点时务必使用方位词（左上/右上/左下/右下/星位/小目/三三/边上/中腹）。"
        f"语气鼓励、易懂，控制在 240 字以内，可用 Markdown（**加粗**、列表）。"
        f"\n\n【坐标铁律】本系统所有坐标均采用 GTP 记号：1 个大写英文字母 + 1–2 位数字，"
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
        f"这是一盘 {size} 路棋盘的复盘。\n\n"
        f"{board_block}"
        f"【该方实际落子】{actual_sgf}（即盘面上 ◆ 处）\n"
        f"【AI 推荐落子】{best_sgf}（即盘面上 ★ 处）\n"
        f"【前情】最近几手依次是：{recent}（均为 GTP 坐标：列字母+行数字）\n"
        f"【胜率对比】若走推荐点，{color_cn}方胜率约 {ai_wr:.1f}%；实际走子后降到约 {actual_wr:.1f}%，"
        f"下降了约 {delta:.1f} 个百分点。\n"
        f"【AI 前三候选（{color_cn}方视角胜率）】\n{cand_text}\n"
        f"【AI 推荐后续变化（仅是推演，不是已经下的子）】{best_sgf} → {pv_str}\n\n"
        f"请严格按下列要求讲解（用 Markdown，240 字以内）：\n"
        f"1）**必须基于上面的【当前局面】和【该方实际落子 {actual_sgf}】来讲**。"
        f"变化图（【AI 推荐后续变化】）只是假设性推演，绝不可把变化图里的子当作已经落下的子来讲解，"
        f"也绝不可只按变化图各子的位置铺陈。\n"
        f"2）**问题**：实际这手（{actual_sgf}）的问题具体是什么"
        f"（子力重复/方向偏差/忽视弱棋/被抢要点/死活误判/官子损目…）？结合盘面方位"
        f"（如「右上角」「左边星位」「三三」「小目」「中腹」等）与棋形说清。\n"
        f"3）**为什么推荐 {best_sgf}**：它实现了什么意图"
        f"（拆边/挂角/守角/打入/侵消/补强/出头/做活/杀棋/收官…）。\n"
        f"4）**推演**：若走 {best_sgf}，对方大概会怎么应、2~3 手后预期形势；相比实际落子具体多出了什么。\n"
        f"5）**棋理点睛**：用一条贴切棋谚收束，并说明它在此处如何体现。"
    )
    if rag_text:
        user += f"\n\n【参考资料】（若与本题相关请引用，不相关则忽略）\n{rag_text}\n"

    try:
        return _call_deepseek(system, user, max_tokens=600, temperature=0.25)
    except Exception:
        return _fallback_explain(move_no, color_cn, actual_sgf, best_sgf,
                                 ai_wr, actual_wr, delta, size, phase=phase,
                                 best_pv_gtp=best_pv_gtp)
