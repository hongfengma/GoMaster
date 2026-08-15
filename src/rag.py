# -*- coding: utf-8 -*-
"""围棋知识库 RAG 检索引擎（GoMaster v0.8 Phase A）。

设计目标：
  - 零依赖优先：默认用「双字重叠系数 + 结构化特征加权」做离线检索，无网也能用。
  - 可选 embedding：若 settings 里配置了 OpenAI 协议 embedding 接口，可切换为向量语义排序（见 _embed_rank）。
  - 优雅降级：index.json 缺失或异常时返回 []，不影响主流程（explainer 已有 try/except）。

对外暴露：retrieve(query, top_k=3, meta=None) -> List[dict]
  dict 字段：{title, content, category, tags, source}
"""
import os
import json

# index.json 与本模块同位于 src/ 的上一级 knowledge/ 目录
_HERE = os.path.dirname(os.path.abspath(__file__))
_INDEX_PATH = os.path.join(os.path.dirname(_HERE), "knowledge", "index.json")

_cache = None  # 进程内缓存


def _load_index():
    global _cache
    if _cache is not None:
        return _cache
    try:
        with open(_INDEX_PATH, "r", encoding="utf-8") as f:
            _cache = json.load(f)
    except Exception:
        _cache = {"entries": []}
    return _cache


def _bigrams(text):
    """取文本的所有 2 字片段（中文按字、英文按词处理均可，这里统一按字符）。"""
    if not text:
        return set()
    return set(text[i:i + 2] for i in range(len(text) - 1))


def _overlap_coeff(a, b):
    """重叠系数 = |a∩b| / min(|a|,|b|)，对短查询更友好。"""
    if not a or not b:
        return 0.0
    inter = len(a & b)
    return inter / min(len(a), len(b))


def _structured_boost(entry, meta):
    """结构化特征加权：phase / zone 命中标 features 时加分。"""
    boost = 0.0
    feats = set(entry.get("board_features", []))
    if not meta:
        return boost
    for key in ("phase", "zone", "color"):
        v = meta.get(key)
        if v and v in feats:
            boost += 0.25
    # 阶段词直接命中（布局/中盘/官子）
    phase = meta.get("phase")
    if phase and phase in feats:
        boost += 0.15
    return boost


def _embed_rank(entries, query, top_k):
    """（可选）向量语义排序。需外部 embedding 接口，未配置时回退 None。

    预留接口：未来在 config/settings 里提供 EMBEDDING_URL / EMBEDDING_KEY / EMBEDDING_MODEL
    后，可在此调用 /embeddings 拿到 query 与每条 entry 的向量做余弦排序。
    当前 Phase A 默认不启用，保证零依赖离线可用。
    """
    return None


def retrieve(query, top_k=3, meta=None, use_embedding=False):
    """检索知识库，返回 top_k 条相关条目。

    query: 检索文本（explainer 会拼入 阶段/区域/落子描述 等）
    meta: 可选结构化信息 {phase, zone, color, level}
    """
    idx = _load_index()
    entries = idx.get("entries", [])
    if not entries or not query:
        return []

    q_bg = _bigrams(query)
    if use_embedding:
        ranked = _embed_rank(entries, query, top_k)
        if ranked is not None:
            return ranked[:top_k]

    scored = []
    for e in entries:
        text = " ".join([
            e.get("title", ""),
            e.get("content", ""),
            " ".join(e.get("tags", [])),
            " ".join(e.get("board_features", [])),
        ])
        sim = _overlap_coeff(q_bg, _bigrams(text))
        score = sim + _structured_boost(e, meta)
        if score > 0:
            scored.append((score, e))

    scored.sort(key=lambda x: x[0], reverse=True)
    out = []
    for score, e in scored[:top_k]:
        out.append({
            "title": e.get("title", ""),
            "content": e.get("content", ""),
            "category": e.get("category", ""),
            "tags": e.get("tags", []),
            "source": e.get("source", ""),
        })
    return out


# 便于本地调试：python rag.py "星位 点三三 布局"
if __name__ == "__main__":
    import sys
    q = sys.argv[1] if len(sys.argv) > 1 else "星位 点三三 布局 角部"
    for r in retrieve(q, top_k=5, meta={"phase": "布局", "zone": "角部"}):
        print(f"- [{r['category']}] {r['title']}：{r['content'][:40]}...")
