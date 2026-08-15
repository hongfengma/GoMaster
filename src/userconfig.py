# -*- coding: utf-8 -*-
"""用户可编辑配置（设置界面持久化）。

存于用户主目录 `~/.gomaster/config.json`，跨平台一致（开发态与打包态通用），
不进入版本库（gitignore 忽略）。首次运行无配置时返回默认值 + 运行时探测到的 KataGo 路径，
便于设置界面预填、也保证「未配置即使用内置默认」的降级行为。

字段说明：
  - katago_exe   : 本地 KataGo 可执行文件路径（留空=自动探测 config.KATAGO_EXE）
  - katago_cfg   : KataGo analysis 配置文件路径（留空=自动探测 config.ANALYSIS_CFG）
  - nn_path      : 神经网络权重文件（.bin.gz）。留空=自动探测并优先选最小网络（CPU 更快）；
                   指定后强制使用该文件。不同 KataGo 构建需匹配对应格式权重。
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
    "nn_path",
    "analysis_dir",
    "llm_base_url",
    "llm_api_key",
    "llm_model",
    "llm_verify",
)
# 布尔型字段：保存时不能按「空字符串」过滤
BOOL_KEYS = {"llm_verify"}


def _default_value():
    """默认值：自动探测内置 KataGo 路径，供设置界面预填。"""
    try:
        from config import KATAGO_EXE, ANALYSIS_CFG, WEIGHT
        katago_exe = KATAGO_EXE
        katago_cfg = ANALYSIS_CFG
        nn_path = WEIGHT
    except Exception:
        katago_exe = ""
        katago_cfg = ""
        nn_path = ""
    return {
        "katago_exe": katago_exe,
        "katago_cfg": katago_cfg,
        "nn_path": nn_path,
        "analysis_dir": "",
        "llm_base_url": "https://api.deepseek.com/v1",
        "llm_api_key": "",
        "llm_model": "deepseek-chat",
        "llm_verify": True,
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
        out = {}
        for k in KEYS:
            if k in BOOL_KEYS:
                out[k] = bool(user.get(k, defaults[k]))
            else:
                out[k] = user.get(k, defaults[k])
        return out
    except Exception:
        return defaults


def save(cfg: dict):
    """保存用户配置（仅持久化 KEYS 中的键）。"""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    merged = {}
    defaults = _default_value()
    for k in KEYS:
        if k in BOOL_KEYS:
            merged[k] = bool(cfg.get(k, defaults[k]))
        else:
            merged[k] = cfg.get(k) or ""
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)
    return load()


def resolve_katago(exe=None, cfg=None, nn=None):
    """把用户配置解析为实际可用的 (exe, cfg, weight)。

    exe/cfg/nn 均可被用户覆盖；任一为 None 时回退到 config.py 自动探测值。
    nn（神经网络权重文件）留空则走 config.WEIGHT（已按「最小网络优先」策略选出）。
    """
    from config import KATAGO_EXE, ANALYSIS_CFG, WEIGHT
    return (
        exe or KATAGO_EXE,
        cfg or ANALYSIS_CFG,
        nn or WEIGHT,
    )


def llm_section(cfg: dict):
    """从配置中提取 LLM 配置子字典（兼容默认 DeepSeek）。"""
    return {
        "base_url": cfg.get("llm_base_url") or "https://api.deepseek.com/v1",
        "api_key": cfg.get("llm_api_key") or "",
        "model": cfg.get("llm_model") or "deepseek-chat",
    }
