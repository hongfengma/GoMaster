# -*- coding: utf-8 -*-
"""用户可编辑配置（设置界面持久化）。

存于用户主目录 `~/.gomaster/config.json`，跨平台一致（开发态与打包态通用），
不进入版本库（gitignore 忽略）。首次运行无配置时返回默认值 + 运行时探测到的 KataGo 路径，
便于设置界面预填、也保证「未配置即使用内置默认」的降级行为。

字段说明：
  - katago_exe   : 本地 KataGo 可执行文件路径（留空=自动探测 config.KATAGO_EXE）
  - katago_cfg   : KataGo analysis 配置文件路径（留空=自动探测 config.ANALYSIS_CFG）
  - analysis_dir : 复盘报告输出目录（留空=SGF 同目录）
  - llm_base_url : 解读大模型 API base_url（OpenAI 兼容，如 https://api.deepseek.com/v1）
  - llm_api_key  : 解读大模型 API Key
  - llm_model    : 解读模型名（如 deepseek-chat）
"""
import os
import json

CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".gomaster")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")

KEYS = (
    "katago_exe",
    "katago_cfg",
    "analysis_dir",
    "llm_base_url",
    "llm_api_key",
    "llm_model",
)


def _default_value():
    """默认值：自动探测内置 KataGo 路径，供设置界面预填。"""
    try:
        from config import KATAGO_EXE, ANALYSIS_CFG
        katago_exe = KATAGO_EXE
        katago_cfg = ANALYSIS_CFG
    except Exception:
        katago_exe = ""
        katago_cfg = ""
    return {
        "katago_exe": katago_exe,
        "katago_cfg": katago_cfg,
        "analysis_dir": "",
        "llm_base_url": "https://api.deepseek.com/v1",
        "llm_api_key": "",
        "llm_model": "deepseek-chat",
    }


def load():
    """返回合并后的配置 dict（用户配置覆盖默认值）。"""
    defaults = _default_value()
    if not os.path.isfile(CONFIG_PATH):
        return defaults
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            user = json.load(f)
        if not isinstance(user, dict):
            return defaults
        return {k: user.get(k, defaults[k]) for k in KEYS}
    except Exception:
        return defaults


def save(cfg: dict):
    """保存用户配置（仅持久化 KEYS 中的键）。"""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    merged = {k: (cfg.get(k) or "") for k in KEYS}
    # 过滤空值（空字符串视为「使用默认」）
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)
    return load()


def resolve_katago(exe=None, cfg=None):
    """把用户配置解析为实际可用的 (exe, cfg, weight)。

    用户仅覆盖 exe/cfg；权重文件仍走 config.py 自动探测（不同 KataGo 二进制
    对应的权重文件路径不易预测，且分析质量主要取决于权重，故保持内置自动探测）。
    """
    from config import KATAGO_EXE, ANALYSIS_CFG, WEIGHT
    return (
        exe or KATAGO_EXE,
        cfg or ANALYSIS_CFG,
        WEIGHT,
    )


def llm_section(cfg: dict):
    """从配置中提取 LLM 配置子字典（兼容默认 DeepSeek）。"""
    return {
        "base_url": cfg.get("llm_base_url") or "https://api.deepseek.com/v1",
        "api_key": cfg.get("llm_api_key") or "",
        "model": cfg.get("llm_model") or "deepseek-chat",
    }
