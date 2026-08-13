# -*- coding: utf-8 -*-
"""围棋教练 AI 复盘 - 全局配置"""
import os


def _load_dotenv():
    """极简 .env 加载（零依赖）：若项目根目录存在 .env，把 KEY=VALUE 注入环境变量。

    这样 API Key 等敏感信息不进入版本库，仅本机/部署机持有 .env 即可。
    """
    dotenv = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    if not os.path.isfile(dotenv):
        return
    try:
        with open(dotenv, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
    except Exception:
        pass


_load_dotenv()

# 项目根目录：src/config.py 的上一级，跨平台自动定位（不再硬编码 Windows 路径）
HERE = os.path.dirname(os.path.abspath(__file__))
# 开发态：HERE=仓库根/src，PROJ=仓库根
# 打包态：server.py 位于 resources/，src 经 --extra-resource 落到 resources/src，
#         HERE=resources/src，PROJ=resources
PROJ = os.path.dirname(HERE)
# deps（KataGo 权重/exe、分析配置）经 --extra-resource 落到与 src 同级的 deps 目录，
# 故直接基于 HERE 的上一级定位，开发态=仓库根/deps，打包态=resources/deps，两者通用。
DEPS = os.path.join(HERE, "..", "deps")

# KataGo 可执行文件：跨平台自动探测（Windows 为 katago.exe，macOS/Linux 为 katago）
_KATAGO_DIR = os.path.join(DEPS, "katago")
if os.path.isfile(os.path.join(_KATAGO_DIR, "katago.exe")):
    KATAGO_EXE = os.path.join(_KATAGO_DIR, "katago.exe")
elif os.path.isfile(os.path.join(_KATAGO_DIR, "katago")):
    KATAGO_EXE = os.path.join(_KATAGO_DIR, "katago")
else:
    KATAGO_EXE = os.path.join(_KATAGO_DIR, "katago.exe")  # 缺失时保留默认名以便报错定位

# 权重文件：CPU 无独显机器，首选「小网络」以获得可用速度；缺失时回退大网络。
# 推荐小网络（CPU 友好，沙箱/本机均可从 katagoarchive.org 下载）：
#  - g170-b10c128（10 block × 128 ch，~11MB，棋力职业级以上，速度/棋力平衡，默认首选）
#  - g170-b6c96  （6 block × 96 ch，~3.6MB，极快，棋力约业余初级，最省时备选）
# 下载直链（放 deps/ 下对应文件名即被自动识别）：
#   https://katagoarchive.org/g170/neuralnets/g170-b10c128-s197428736-d67404019.bin.gz
#   https://katagoarchive.org/g170/neuralnets/g170-b6c96-s175395328-d26788732.bin.gz
#  - katago_b10c384h6nbttflrs 为老马本机既有大网络（GPU 设计），棋力强但 CPU 极慢，作兜底。
WEIGHT_CANDIDATES = [
    # g170 系列 = 二进制格式（.bin.gz），适配 KataGo v1.17.1；kata1 系列是旧文本格式，已废弃。
    os.path.join(DEPS, "g170-b10c128-s197428736-d67404019.bin.gz"),   # 二进制 b10c128（更强，需另下）
    os.path.join(DEPS, "g170-b6c96-s175395328-d26788732.bin.gz"),     # 二进制 b6c96（极快，已就绪）
    os.path.join(DEPS, "katago_b10c384h6nbttflrs.bin.gz"),            # 二进制大网络（兜底，但 CPU 极慢）
]


def _choose_weight():
    for p in WEIGHT_CANDIDATES:
        if os.path.isfile(p):
            return p
    return WEIGHT_CANDIDATES[-1]


WEIGHT = _choose_weight()
ANALYSIS_CFG = os.path.join(DEPS, "analysis_example.cfg")

# DeepSeek
# 注意：deepseek-v4-flash 是「推理模型」，会把 max_tokens 预算优先用于思维链(reasoning_content)，
# 导致真实讲解 content 在长 prompt 下被挤空、被误判为“空响应”走兜底。
# 改用 deepseek-chat —— DeepSeek 同样将其指向 v4 底层，但关闭推理，稳定返回中文正文。
# API Key 从环境变量或项目根目录 .env 读取（不硬编码，避免泄漏到版本库）。
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_MODEL = "deepseek-chat"
DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"

# KataGo 分析参数（CPU / eigen 后端，针对无独显机器调优）
KATAGO_BACKEND = "eigen"
# 搜索线程：约半数 CPU 核心（KataGo 启动时用 -override-config 注入），避免拖垮整机。
KATAGO_THREADS = max(1, (os.cpu_count() or 4) // 2)
DEFAULT_MAX_VISITS = 40           # 小网络下 40 足够 9 路；19 路可调到 60~120
DEFAULT_THRESHOLD = 0.05          # 胜率下降超过 5% 视为“失误手”，触发讲解

# 用户水平（影响讲解语气），可选: 入门 / 进阶 / 挑战
USER_LEVEL = "入门"
