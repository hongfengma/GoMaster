# -*- coding: utf-8 -*-
"""轻量级 RAG 检索器（零依赖，纯标准库）。

作用：把「围棋知识库」（kb/ 目录下的 .md / .json）切分为片段，在每次生成讲解前，
根据当前手信息做一次关键词检索，把最相关的若干片段作为【参考资料】注入 DeepSeek 提示词，
从而提升讲解的棋理准确性与专业性（尤其对定式、死活、官子、常见失误类型）。

为何不用向量库：
  - 本程序定位是「本地、离线、无 GPU」的个人复盘工具；引入 sentence-transformers /
    FAISS 需要下载模型且吃算力，与轻量目标冲突。
  - 关键词 + 二元组（bigram）召回对「棋理 / 定式 / 死活 / 官子」这类主题明确的短文本已足够好，
    且完全离线、零安装。后续若想升级为语义检索，只需把 retrieve() 换成 embedding 向量检索即可，
    接口（输入 query、输出 [{title,content}]）保持不变。

知识库格式：
  - *.md：按 `## ` 二级标题自动分块；文件名/首个 `# ` 作为文档标题。
  - *.json：支持 [{title, content, tags}] 列表，或单个 {title, content, tags}。
添加新知识：在 kb/ 下新建 .md / .json 即可，无需改代码。
"""
import os
import re
import json

KB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kb")
_CHUNKS = None  # 简单缓存


def _tokenize(text):
    """中文按「字 + 二元组」、英文/数字按词切分，作为命中单元。"""
    text = (text or "").lower()
    ascii_words = re.findall(r"[a-z0-9]+", text)
    cjk = re.findall(r"[一-鿿]", text)
    toks = list(ascii_words)
    toks += cjk
    toks += [cjk[i] + cjk[i + 1] for i in range(len(cjk) - 1)]
    return toks


def _make_chunk(title, content, tags=None):
    return {
        "title": title,
        "content": content.strip(),
        "tags": tags or [],
        "_t": _tokenize(title + " " + content + " " + " ".join(tags or [])),
    }


def _load():
    global _CHUNKS
    if _CHUNKS is not None:
        return _CHUNKS
    chunks = []
    if os.path.isdir(KB_DIR):
        for fn in sorted(os.listdir(KB_DIR)):
            path = os.path.join(KB_DIR, fn)
            if fn.endswith(".json"):
                try:
                    data = json.load(open(path, encoding="utf-8"))
                except Exception:
                    continue
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    chunks.append(_make_chunk(
                        item.get("title", fn),
                        item.get("content", ""),
                        item.get("tags", []),
                    ))
            elif fn.endswith(".md"):
                try:
                    text = open(path, encoding="utf-8").read()
                except Exception:
                    continue
                doc_title = os.path.splitext(fn)[0]
                m = re.search(r"^#\s+(.+)$", text, re.M)
                if m:
                    doc_title = m.group(1).strip()
                sections = re.split(r"(?m)^##\s+", text)
                head = sections[0].strip()
                if head:
                    chunks.append(_make_chunk(doc_title, head, [doc_title]))
                for sec in sections[1:]:
                    lines = sec.splitlines()
                    sec_title = lines[0].strip() if lines else ""
                    body = "\n".join(lines[1:]).strip()
                    if not body:
                        continue
                    title = f"{doc_title} · {sec_title}" if sec_title else doc_title
                    chunks.append(_make_chunk(title, body, [doc_title, sec_title]))
    _CHUNKS = chunks
    return chunks


def retrieve(query, top_k=3):
    """返回与 query 最相关的 top_k 个片段：[{title, content}]。"""
    chunks = _load()
    if not chunks:
        return []
    q_toks = _tokenize(query)
    qset = set(q_toks)
    if not qset:
        return []
    scored = []
    for c in chunks:
        inter = sum(1 for t in c["_t"] if t in qset)
        title_hit = sum(1 for t in q_toks if t and t in c["title"])
        score = inter + title_hit * 2
        if score > 0:
            scored.append((score, c))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [{"title": c["title"], "content": c["content"]}
            for _, c in scored[:top_k]]


if __name__ == "__main__":
    # 简单自测
    for q in ["黑方 第3手 实际C16 推荐Q4 布局", "白方 死活 做眼", "官子 扳粘"]:
        print("Q:", q)
        for c in retrieve(q, 2):
            print("  -", c["title"])
