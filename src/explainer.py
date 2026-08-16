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
from go_board import gtp_to_xy, zone_of_gtp

try:
    from rag import retrieve as _rag_retrieve
except Exception:  # rag 模块缺失时优雅降级，不影响主流程
    _rag_retrieve = None

try:
    from fact_extractor import fact_to_text as _fact_to_text
except Exception:  # 事实抽取模块缺失时优雅降级
    _fact_to_text = None


def _full_chat_url(base_url: str) -> str:
    """把「OpenAI 兼容 base_url」规范化为完整 chat completions 端点。

    兼容以下写法：
      - https://api.deepseek.com/v1/chat/completions  → 原样返回
      - https://api.deepseek.com/v1                  → 补 /chat/completions
      - http://localhost:11434/v1                    → 补 /chat/completions（Ollama）
    """
    base_url = (base_url or "").strip().rstrip("/")
    if base_url.endswith("/chat/completions"):
        return base_url
    return base_url + "/chat/completions"


def _call_deepseek(system: str, user: str, max_tokens=800, temperature=0.1,
                   retries=2, llm=None):
    """调用大模型（默认 DeepSeek，可由 llm 覆盖 base_url/api_key/model）。

    对空内容/瞬时错误/非法坐标自动重试或抛异常，由上层 fallback。
    """
    llm = llm or {}
    base_url = llm.get("base_url") or DEEPSEEK_URL
    api_key = llm.get("api_key") or DEEPSEEK_API_KEY
    model = llm.get("model") or DEEPSEEK_MODEL
    last_err = None
    for attempt in range(retries + 1):
        try:
            payload = {
                "model": model,
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
                _full_chat_url(base_url),
                data=data,
                headers={
                    "Authorization": f"Bearer {api_key}",
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


def _zone_of(gtp, size, fact_sheet=None):
    """由 GTP 坐标推断盘面区域：角部 / 边上 / 中腹（供 RAG 检索与讲解方位）。

    优先使用事实单里的 zone；没有时本地计算。区域定义：
      - 第四线及以下为边/角；
      - 第五线及以上为中腹。
    避免把第四线说成中腹。
    """
    if fact_sheet and fact_sheet.get("zone"):
        return fact_sheet["zone"]
    return zone_of_gtp(gtp, size)


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


_GTP_COORD_RE = re.compile(r"[A-HJ-T][0-9]{1,2}")


def _extract_gtp_coords(text):
    """从讲解文本中提取所有合法 GTP 坐标（列 A–T 跳 I + 数字），返回 [(原始串, (x,y))]。"""
    out = []
    if not text:
        return out
    for m in _GTP_COORD_RE.finditer(text):
        xy = gtp_to_xy(m.group(), 19)
        if xy:
            out.append((m.group(), xy))
    return out


def verify_explain(text, fact_sheet, size=19):
    """规则校验器（Verifier）：用事实单核对讲解中的事实声明，不调用 API。

    命中明显矛盾时返回告警字符串列表；无矛盾返回空列表。
    仅做轻量关键词/信号比对，目的不是穷尽 NLP，而是拦住最刺眼的幻觉。
    """
    warns = []
    if not fact_sheet or not text:
        return warns
    bad = fact_sheet.get("shape_bad", [])
    phase = fact_sheet.get("phase", "")

    if "接不归/自紧气" in bad and any(
            k in text for k in ("做活", "安定", "已活", "安全", "活棋", "眼位")):
        warns.append("事实单显示该手为接不归/自紧气（仅1气），与文中『做活/安定』表述矛盾")

    if bad and any(k in text for k in ("好形", "好形状", "形状很好", "漂亮的形状")):
        warns.append(f"事实单识别出坏形（{', '.join(bad)}），文中却称好形，请以事实单为准")

    if phase == "官子" and "战斗" in text and "收官" not in text and "官子" not in text:
        warns.append("事实单判定本手处于官子阶段，文中提及战斗但未见收官表述，请确认")

    conn = fact_sheet.get("connection") or {}
    if conn.get("connects_groups") and any(k in text for k in ("隔离", "分断", "切断", "断开")):
        warns.append("事实单显示本手为补断/联络，文中却用「隔离/分断/切断」，请以事实单为准")

    # 跨盘关联检测（窗口内显式关联）：仅当「关系词 + 两个坐标」出现在同一分句
    # 时才判定，避免「实战 O5、推荐 D3」这类正常对比被误判为跨盘拆二。
    # 关系词限定为必须连接两个点的词，过滤掉「扩张/连接/补断/形成」等单点/模糊表述。
    relation_kw = ("拆二", "拆三", "配合", "联络", "压迫", "连成", "呼应")
    clauses = re.split(r"[，。！？；、\n]", text)
    seen_pairs = set()
    for cl in clauses:
        c_in = _extract_gtp_coords(cl)
        if len(c_in) < 2:
            continue
        if not any(k in cl for k in relation_kw):
            continue
        for i in range(len(c_in)):
            for j in range(i + 1, len(c_in)):
                a, b = c_in[i][1], c_in[j][1]
                dist = abs(a[0] - b[0]) + abs(a[1] - b[1])
                key = tuple(sorted((c_in[i][0], c_in[j][0])))
                if dist > 3 and key not in seen_pairs:
                    seen_pairs.add(key)
                    warns.append(
                        f"事实单未支撑跨盘关联：{c_in[i][0]} 与 {c_in[j][0]} "
                        f"相距 {dist} 格且同句描述为拆二/配合/压迫等关系，"
                        f"请仅引用事实单内相邻坐标")

    return warns


def verify_and_correct(content, fact_sheet, llm=None):
    """LLM 级审核员：检查讲解与事实单是否矛盾，必要时输出修正版（多一次调用）。

    若审核认为无矛盾，返回原 content；若发现坐标/阶段/棋形/定式/区域/变化图等错误，
    返回修正后的完整讲解。审核失败则优雅降级，返回原文。
    """
    if not fact_sheet or not _fact_to_text:
        return content
    fact_text = _fact_to_text(fact_sheet)
    if not fact_text or not content:
        return content

    v_system = (
        "你是一名严格的围棋讲解事实审核员。请检查下方的【讲解】是否与【事实单】一致。\n"
        "重点排查：\n"
        "1. 坐标引用错误（如把黑棋说成白棋、坐标与描述的棋子不对应、提到事实单里没有的坐标）；\n"
        "2. 区域概念错误（第四线及以下只能叫角部/边上，不能叫中腹）；\n"
        "3. 阶段/棋形/定式名称与事实单矛盾；\n"
        "4. 把【AI 后续主变】变化图里的子当作已经落下的子来讲解；\n"
        "5. 虚构事实单未列出的棋理或棋谚；\n"
        "6. 跨盘关联错误：把相距 3 格以上的远端子说成「拆二/配合/压迫/扩张」，"
        "或把【推荐点事实】中落入「对方强势力」的点说成「压迫对方」（应讲成打入/破空/侵消）。\n"
        "若发现任何矛盾，请直接输出修正后的完整讲解（严格保持原来的 5 个 Markdown 标题分段，"
        "280 字以内，坐标必须正确且来自事实单）。若讲解与事实单完全一致，"
        "请仅输出「无矛盾」三个字，不要输出其他内容。"
    )
    v_user = (
        f"【事实单】\n{fact_text}\n\n"
        f"【讲解】\n{content}\n\n"
        "请先逐项自检坐标、区域、阶段、棋形/定式、变化图描述是否与事实单一致，"
        "然后按上面要求输出。"
    )
    try:
        corrected = _call_deepseek(
            v_system, v_user, max_tokens=700, temperature=0.0, llm=llm)
        if corrected.startswith("无矛盾"):
            return content
        # 兜底保护：若修正结果被「废掉」（含暂不可用/长度骤减），保留原文，
        # 避免二次校验把正常讲解整段清空。
        if ("暂不可用" in corrected or "大模型暂不可用" in corrected
                or len(corrected) < 0.5 * len(content)):
            return content
        # 简单校验修正结果仍含 5 段标题，否则降级
        if all(h in corrected for h in (
                "### 问题定性", "### 关键棋理", "### 推荐点意图",
                "### 后续推演", "### 不确定点")):
            return corrected
    except Exception:
        pass
    return content


def explain_move(move_no, color_cn, actual_sgf, best_sgf,
                 ai_wr, actual_wr, delta, best_pv_gtp, size,
                 recent_moves_sgf, level=USER_LEVEL, top3=None, phase="中盘",
                 board_ascii=None, fact_sheet=None, llm=None, verify=True):
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

    zone = _zone_of(actual_sgf, size, fact_sheet)

    # —— RAG 知识库检索（增强 query：带 phase + zone + 事实标签，命中更准）——
    rag_text = ""
    if _rag_retrieve:
        try:
            facts = []
            if fact_sheet:
                facts += list(fact_sheet.get("shape_bad", []))
                facts += list(fact_sheet.get("shape_good", []))
                jt = fact_sheet.get("joseki") or {}
                if jt.get("matched"):
                    facts.append(jt["matched"])
            q = (f"{color_cn}方 第{move_no}手 实际{actual_sgf} 推荐{best_sgf} "
                 f"{phase} {zone} " + " ".join(facts))
            chunks = _rag_retrieve(q, top_k=3, meta={
                "phase": phase, "zone": zone, "color": color_cn,
                "board_features": facts})
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
        f"3. 若引用定式、棋谚或棋形：必须来自公认棋理或下方【参考资料】/【事实单】，"
        f"并说明它在本局面如何体现；不得凭空杜撰名称。若你不确定某条棋理是否适用，"
        f"必须在「不确定点」里明说，或写「此处建议摆谱验证」，绝不可含糊带过。\n"
        f"4. 描述落点时务必使用方位词（左上/右上/左下/右下/星位/小目/三三/边上/中腹/一二线）。\n"
        f"区域定义以事实单为准：第四线及以下为「角部」或「边上」，第五线及以上才称「中腹」；"
        f"一二线必须描述为「边线」「底线」或「靠近边线」，绝不可说成中腹。"
        f"严禁把四线或更低线的棋子描述成中腹。\n"
        f"5. 若下方出现【事实单】，其内容为程序对棋盘的确定性计算结果"
        f"（阶段/棋形/定式/形势/涉及坐标/后续主变/联络特征/边线提示），你必须以其为准；"
        f"事实单未提及的棋理、定式、棋形名称、具体坐标不得自行断言。"
        f"讲解中引用的任何坐标，必须来自事实单里的「涉及坐标」「角部已落子」或「实际/推荐点」；"
        f"禁止凭空编造坐标，禁止把变化图里的坐标当作已落下的子来引用。\n"
        f"6. 若事实单写明「补断/联络」，本手具有连接己方棋块的作用，"
        f"你绝不可把它讲成「隔离」「分断」「切断」对方；"
        f"若事实单写明「边线提示」，必须承认它靠近边线，不可说其深入中腹。\n"
        f"6.5 严禁跨盘关联：描述某点与周边子的「拆二/配合/联络/压迫/扩张」关系时，"
        f"只能引用距该点 3 格以内的棋子（参见【事实单】的涉及坐标与推荐点事实）。"
        f"不得将同列隔多条线、或对角的远量子说成「拆二/配合/压迫」；"
        f"若【推荐点事实】显示其落入「对方强势力」，应讲成打入/破空/侵消，而非「压迫对方」。\n"
        f"7. 输出必须严格按下列 5 个 Markdown 标题分段，不要增减段落：\n"
        f"### 问题定性\n### 关键棋理\n### 推荐点意图\n### 后续推演\n### 不确定点\n"
        f"8. 全程使用 Markdown（**加粗**、列表），总篇幅控制在 280 字以内。\n\n"
        f"【坐标铁律】本系统所有坐标均采用 GTP 记号：1 个大写英文字母 + 1–2 位数字，"
        f"例如 Q16、D4、K10。你输出中提到的任何落点，都必须是这种格式。"
        f"绝对禁止输出 dd、qq、ddd、ehh、fch 等两位或三位小写字母串。"
        f"如果某个点在脑中是小写两位字母（如 dd），你必须先转换成 GTP（如 D4）再写。"
        f"\n\n【正确示例】Q16、D6、F6、K10、A1、T19。"
        f"【错误示例】dd、qq、ddd、ehh、fch。"
        f"输出前请自检：每出现一次坐标，必须满足「首字符大写字母 A–T（跳 I）+ 数字」，"
        f"且该坐标确实对应事实单中提到的棋子或空点，不得张冠李戴。"
    )

    board_block = (
        f"【当前局面】是第 {move_no} 手（{color_cn}方）落子前的真实棋盘"
        f"（ASCII 表示：列 A..T 从左到右、行 1..{size} 从下到上；"
        f"X=黑子 O=白子 .=空点；★=AI 推荐点 ◆=本手实际落子点）：\n\n{board_ascii}\n\n"
        if board_ascii else
        f"【当前局面】第 {move_no} 手（{color_cn}方）落子前。"
    )
    fact_block = _fact_to_text(fact_sheet) if (_fact_to_text and fact_sheet) else ""

    user = (
        f"这是一盘 {size} 路棋盘的复盘，本手处于「{phase}」阶段、位于「{zone or '棋盘'}」。\n\n"
        f"{board_block}"
        f"{fact_block}\n\n" if fact_block else ""
        f"【该方实际落子】{actual_sgf}（即盘面上 ◆ 处）\n"
        f"【AI 推荐落子】{best_sgf}（即盘面上 ★ 处）\n"
        f"【前情】最近几手依次是：{recent}（均为 GTP 坐标：列字母+行数字）\n"
        f"【胜率对比】若走推荐点，{color_cn}方胜率约 {ai_wr:.1f}%；实际走子后降到约 {actual_wr:.1f}%，"
        f"下降了约 {delta:.1f} 个百分点。\n"
        f"【AI 前三候选（{color_cn}方视角胜率）】\n{cand_text}\n"
        f"【AI 推荐后续变化（仅是推演，不是已经下的子）】{best_sgf} → {pv_str}\n\n"
        f"请严格按下列要求讲解（Markdown，280 字以内，5 段结构）：\n"
        f"### 问题定性\n实际这手（{actual_sgf}）的问题具体是什么"
        f"（子力重复/方向偏差/忽视弱棋/被抢要点/死活误判/官子损目/孤棋未安顿/联络/补断…）？"
        f"结合盘面方位（如「右上角」「左边星位」「三三」「小目」「中腹」「一二线边线」）与棋形说清；"
        f"若事实单提示「补断/联络」或「边线提示」，必须体现，不可反说。\n"
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
        content = _call_deepseek(system, user, max_tokens=700, temperature=0.1, llm=llm)
        # 模型偶尔把「不确定点」写成「无矛盾」，统一收敛成「无」
        content = re.sub(r"(?m)^\s*无矛盾\s*$", "无", content)
    except Exception:
        return _fallback_explain(move_no, color_cn, actual_sgf, best_sgf,
                                 ai_wr, actual_wr, delta, size, phase=phase,
                                 best_pv_gtp=best_pv_gtp, zone=zone)
    # Verifier：规则校验（不增 API 调用），命中矛盾则附系统提示
    if fact_sheet:
        warns = verify_explain(content, fact_sheet, size)
        if warns:
            content = content.rstrip() + "\n\n> 系统校验提示：" + "；".join(warns)

    # LLM 级审核：多花一次调用，专门揪坐标/区域/变化图等细节矛盾
    # 用户可在设置中关闭以节省耗时（每失误手省一次 API 调用）。
    if fact_sheet and verify:
        content = verify_and_correct(content, fact_sheet, llm=llm)
        # 再次轻量规则校验，防止修正后仍留痕
        warns2 = verify_explain(content, fact_sheet, size)
        if warns2:
            content = content.rstrip() + "\n\n> 系统校验提示：" + "；".join(warns2)
    return content
