# -*- coding: utf-8 -*-
"""
洛雪TV Python Spider — 兼容 FongMi/TV (T3) 与 WebHomeTV / PeekPro (T4)
站点: https://tv.lxyy.club/

站点说明:
  该站不是标准苹果CMS，而是 ceshi / WebHomeTV 前端，数据全部走 /api/proxy.php:
    ?action=config    -> 采集源配置（源名、排序、player_api、解析线路 official_routes）
    ?action=home      -> 首页推荐（5 分类 × 12 条，自带封面）
    ?action=search    -> 搜索 / 全站列表（wd=% 时等价于"最新全站"，每页 140 条）
    ?action=detail    -> 详情（需 source + id，返回 episodes 多线路分组）
    ?action=posters   -> 按 source+id 批量补封面（列表接口本身不带图）

线路对齐（与网页端播放页三段线路保持一致）:
  网页端播放页分「普通线路 / 播放线路 / 解析线路」三段；TV 壳子只有一层线路 Tab，
  本脚本按如下规则对齐:
    - 普通线路: 详情页按标题跨采集源聚合。标题归一化（去空白/标点/"第X季/seasonN"/
              年份）后模糊匹配（完全一致=0 / 前缀=1 / 包含=2，含季数全名一致优先），
              每个源取最优一条，最多 12 个源，按站点 source_order 排序，点击源置顶。
              和网页端一样：这部片在哪个源有，哪个源就出一条线路，切线路不用回列表。
    - 播放线路: 保留详情接口 episodes.group 分组。单分组的源线路名 = 源名
              （如 4k60帧🔥）；多分组的源线路名 = "源名·分组名"（如 自营🔥·jlplayer），
              纯技术命名（xxxm3u8/hls/mp4）与网页端一致显示为"线路 N"。
    - 解析线路: 读取 config 的 official_routes（默认解析 / 闪电 / m1907）。
              官采蓝光(qilin)的非直链线路会追加"解析·接口名"线路，可在壳子里
              手动切换解析接口；官源默认先走内置解析（与"闪电"同源）直出 m3u8，
              失败回退"默认解析"接口交给壳子。
  注: 网页端每张源卡片上的"资源正常/无法连接"由浏览器实时探测首集得出；TV 端
      由本脚本在详情页对直链线路做同等探测（可用靠前/失效垫后，结果缓存 30 分钟），
      避免壳子默认播到失效线路出现 0 KB/s 卡住触发"自动切换站源"。

弹窗:
  homeContent 返回 msg 字段，TVBox / 影视仓 等支持该约定的壳子会在打开本源时
  弹出公告弹窗（内容由 NOTICE_MSG 常量定义，可自行修改）。不支持该约定的壳子
  会忽略该字段，不影响正常浏览与播放。

搜索（搜不全的三个原因都堵在这）:
  站点 action=search 是"字面子串匹配"，且限流只有 5 次/分钟，踩线就返回
  {"success":false,"need_captcha":true}（实测约 1/4 概率），而原始实现直接把
  空 results 透传出去，于是表现为"有的片子搜不到"。处理方式:
    1. 自动过验证: 验证码是纯算术题("4 + 1 = ?")，action=captcha 拿 token 后
       由 _api 自动解题重发（token 一次性，故必须重发原请求）。
    2. 关键词变体: 片名带间隔号时字面搜不到（电影《破·局》在 7 个源里都写作
       "破·局"，搜 "破局" 返回的 102 条全是蹭词短剧）。对 2~3 字纯汉字片名
       并发补搜"插回间隔号"的写法；完全搜空时再兜底季数写法
       （搜 "庆余年2" 搜不到，资源叫 "庆余年第二季"）。4 字以上不补搜，省限流额度。
    3. 相关性排序 + 本地分页: 归一化后完全一致 > 前缀 > 包含 > 不匹配，同档短标题
       优先，正片压过蹭词片；一次搜全量后本地切片，翻页不再打接口（站点 page
       参数的 total 不可信，实测标 102 实际 258 条）。搜索结果卡片额外标出
       类型（"动作片 · HD国语"），短剧和正片一眼可辨。

二级分类:
  站点接口没有"按类型取列表"的参数（列表只在 action=search 里按关键词字面匹配返回），
  所以二级分类落在本地池子上：每个一级分类给一组子类型入口（电影·剧情/喜剧/动作…、
  剧集·国产/港台/日韩/欧美/短剧…、动漫·国漫/日韩/少儿…、综艺·大陆/港台/日韩/欧美），
  选中后按站点真实 type 过滤池子。词表来自全站枚举（1920 条样本 / 60 种 type），
  并把 国产剧/陆剧/内地剧 这类同义写法归并到一个入口下。

性能优化:
  - 池子本地文件缓存（30min TTL）：冷启动后分类浏览秒开，不再每次重拉全站
  - 并发预热（线程池），无线程环境自动回退串行
  - 详情跨源聚合结果进程内缓存（10min TTL），同片二次打开直出
  - 官源解析结果内存 + 文件缓存（6h TTL），二次播放直出，免 BFQ 等待
  - detailContent 对官源线路后台预解析，点播大概率已缓存 -> 秒播
  - 全链路容错，任何异常都返回空结果而不是崩溃
"""

import sys
import os
import json
import re
import time
import base64
from urllib.parse import quote, urlencode

sys.path.append('..')

# 健康探测用（urllib 为标准库，任何壳子的 Python 环境都有）
try:
    import urllib.request as _urlreq
except Exception:
    _urlreq = None
try:
    import ssl as _ssl
    _SSL_CTX = _ssl._create_unverified_context()
except Exception:
    _SSL_CTX = None


# 并发预热 / 预解析（不可用环境自动回退串行）
try:
    import threading
    _HAS_THREAD = True
except Exception:
    _HAS_THREAD = False

# ===== 兼容导入 =====
try:
    from base.spider import Spider
except ImportError:
    import requests as _rq
    try:
        import urllib3
        urllib3.disable_warnings()
    except Exception:
        pass

    class Spider:
        def fetch(self, url, headers=None, **kw):
            timeout = kw.pop('timeout', 15)
            r = _rq.get(url, headers=headers, timeout=timeout, verify=False, **kw)
            r.encoding = 'utf-8'
            return r


# ============================================================
# 缓存路径（脚本所在目录，可写则持久化，否则回退 /tmp）
# ============================================================
def _cache_dir():
    try:
        return os.path.dirname(os.path.abspath(__file__)) or "/tmp"
    except Exception:
        return "/tmp"


POOL_CACHE = os.path.join(_cache_dir(), ".lxyy_pool_v1.json")
RESOLVE_CACHE = os.path.join(_cache_dir(), ".lxyy_resolve_v1.json")
POOL_CACHE_TTL = 1800       # 池子缓存 30 分钟
RESOLVE_CACHE_TTL = 21600   # 解析缓存 6 小时
PROBE_TTL = 1800            # 直链健康探测缓存 30 分钟
PROBE_TIMEOUT = 5           # 单条探测超时（秒）
PROBE_JOIN_TIMEOUT = 6      # 并发探测等待上限（秒）
SEARCH_CACHE_TTL = 180      # 搜索结果进程内缓存 3 分钟（翻页/重进不再打接口）


# ============================================================
# 常量
# ============================================================

HOST = "https://tv.lxyy.club"
API = HOST + "/api/proxy.php"
UA = "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"

LIMIT = 20
MAX_PAGES = 50
PRELOAD_PAGES = 12          # 首次预热页数（12 页 ≈ 1680 条，一轮并发，覆盖绝大多数分类首页）
POSTER_BATCH = 60

# 采集源显示名（config 拉不到时用这里的兜底，与网页端一致）
SOURCE_NAMES = {
    "qilin": "官采蓝光",
    "mj": "4k60帧🔥",
    "jl": "自营🔥",
    "wsy": "无水印",
    "360zy": "360资源",
    "dytt": "电影天堂",
    "ik": "ikun",
    "md": "魔都",
}

# 采集源排序兜底（config 拉不到时用）
SOURCE_ORDER = ["qilin", "mj", "jl", "wsy", "360zy", "dytt", "ik", "md"]

# 解析线路兜底（config 拉不到时用，与网页端 official_routes 一致）
FALLBACK_ROUTES = [
    {"name": "默认解析", "api": "https://svip.qlplayer.cyou/?url="},
    {"name": "闪电", "api": "https://bfq.txnp.cn/excessive?url="},
    {"name": "m1907", "api": "https://im1907.top/?jx="},
]

# 解析线路 Tab 前缀（对应网页端"解析线路"区块）
PARSER_FLAG = "解析"

# 播放线路分组显示名（official group 别名，与网页端 lineLabel 一致）
# 采集源分组（mjzy / jlm3u8 等）保留原名，不做映射
LINE_NAMES = {
    "qiyi": "爱奇艺", "iqiyi": "爱奇艺", "qq": "腾讯视频", "youku": "优酷",
    "mgtv": "芒果", "imgo": "芒果", "bilibili": "B站", "b站": "B站",
    "letv": "乐视", "sohu": "搜狐", "pptv": "PPTV", "1905": "1905电影网",
    "xigua": "西瓜", "fenghuang": "凤凰",
}

# 跨源聚合上限（与网页端 buildCandidates 一致）
AGG_MAX_SOURCES = 12
AGG_JOIN_TIMEOUT = 8        # 并发拉取各源详情的等待上限（秒）
AGG_CACHE_TTL = 600         # 聚合结果进程内缓存（秒）

# BFQ 官源解析（与"闪电"解析同源；config 拉不到时的兜底）
BFQ_PLAYER = "https://bfq.txnp.cn/player?url="
BFQ_REFERER = "https://bfq.txnp.cn/excessive?url="

# ============================================================
# 标题归一化 / 匹配打分（与网页端 normalizeTitle / titleScore 对齐）
# ============================================================
_SPACE_RE = re.compile(r"[\s\u3000]+")
_PUNCT_RE = re.compile(r"[·•・:：,，.。!！?？'‘’“”\"()（）\[\]【】{}<>《》\-_/\\]")
_SEASON_RE = re.compile(r"(?:第?[一二三四五六七八九十百零0-9]+季|season[0-9]+)", re.I)
_YEAR_TAIL_RE = re.compile(r"(?:20\d{2}|19\d{2})$")
# 纯技术命名的分组（与网页端一致显示为"线路 N"）
_TECH_NAME_RE = re.compile(r"^[a-z0-9_.\-]*(?:m3u8|hls|mp4)[a-z0-9_.\-]*$", re.I)


def _norm_title(s):
    """去空白、标点、"第X季/seasonN"、结尾年份（网页端 normalizeTitle）"""
    s = _SPACE_RE.sub("", (s or "").lower())
    s = _PUNCT_RE.sub("", s)
    s = _SEASON_RE.sub("", s)
    s = _YEAR_TAIL_RE.sub("", s)
    return s


def _strict_name(s):
    """仅去空白与标点（季数参与比对，用于"同季"优先匹配）；中文数字季数归一成阿拉伯数字"""
    s = _SPACE_RE.sub("", (s or "").lower())
    s = _PUNCT_RE.sub("", s)
    s = _CN_SEASON_RE.sub(lambda m: "第%s季" % _cn2num(m.group(1)), s)
    return s


_CN_NUM = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
           "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_CN_SEASON_RE = re.compile(r"第([一二三四五六七八九十百零0-9]+)季")


def _cn2num(s):
    """中文数字 -> 阿拉伯数字（支持到百位；纯数字原样返回）"""
    if s.isdigit():
        return s
    total, num = 0, 0
    for ch in s:
        if ch in _CN_NUM:
            num = _CN_NUM[ch]
        elif ch == "十":
            total += (num or 1) * 10
            num = 0
        elif ch == "百":
            total += (num or 1) * 100
            num = 0
    return str(total + num)


def _title_score(name, wanted):
    """网页端 titleScore: 0 完全一致 / 1 前缀 / 2 包含(≥3字) / 99 不匹配"""
    a = _norm_title(name)
    b = _norm_title(wanted)
    if not a or not b:
        return 99
    if a == b:
        return 0
    if a.startswith(b) or b.startswith(a):
        return 1
    if (a.find(b) >= 0 or b.find(a) >= 0) and min(len(a), len(b)) >= 3:
        return 2
    return 99


# ============================================================
# 搜索关键词变体（解决"片名带间隔号 → 搜不到"）
# ============================================================
# 站点搜索是字面子串匹配：电影《破·局》（郭富城/王千源）在 7 个源里的标题都写作
# "破·局"。用户按记忆搜 "破局" 时，站点返回的 102 条全是含"破局"二字的短剧，
# 是一部正片都搜不到。这里把关键词拆成若干等价写法一并搜索再合并。
_SEP_STRIP_RE = re.compile(r"[\s\u3000·•・.。:：,，、\-_/\\|｜]+")
_ASK_RE = re.compile(r"(\d+)\s*([+\-*xX×÷])\s*(\d+)")


def _search_variants(key):
    """生成等价搜索写法，分两组返回 (首轮, 补搜)。

    首轮 = 原文 + 去分隔符（用户自己带符号时才多一次）
    补搜 = 把间隔号插回短片名的各个位置（破局 -> 破·局）

    为什么必须有补搜：站点搜索是字面子串匹配，搜 "破局" 匹配不到 "破·局"；
    而站里又确实存在大量标题就叫"破局"的蹭词短剧，光看首轮结果无法判断
    "没搜到"还是"搜到了同名的另一部片"，所以对 2~3 字纯汉字片名直接补搜。
    4 字及以上不做补搜，避免白白吃掉站点 5 次/分钟的限流额度。
    """
    key = (key or "").strip()
    if not key:
        return [], []
    primary = [key]
    bare = _SEP_STRIP_RE.sub("", key)
    if bare and bare != key and bare not in primary:
        primary.append(bare)
    extra = []
    if bare and 2 <= len(bare) <= 3 \
            and all("\u4e00" <= c <= "\u9fff" for c in bare):
        for i in range(1, len(bare)):
            v = bare[:i] + "·" + bare[i:]
            if v not in primary and v not in extra:
                extra.append(v)
    return primary[:2], extra[:2]


# 尾部季数标记（"庆余年2" / "庆余年第二季" / "三体 第2季"），用于搜空后的兜底改写
_SEASON_TAIL_RE = re.compile(r"[\s._\-·•]*(?:第?([0-9一二三四五六七八九十]+)季|[0-9]+)\s*$")


def _num2cn(n):
    """阿拉伯数字 -> 中文（用于 "第二季" 这类资源站常见写法）"""
    s = str(n)
    if not s.isdigit():
        return s
    if len(s) == 1:
        return "零一二三四五六七八九"[int(s)]
    if len(s) == 2 and s[0] == "1":
        return "十" + ("零一二三四五六七八九"[int(s[1])] if s[1] != "0" else "")
    if len(s) == 2:
        return "零一二三四五六七八九"[int(s[0])] + "十" + \
               ("零一二三四五六七八九"[int(s[1])] if s[1] != "0" else "")
    return s


def _search_fallbacks(key):
    """完全搜空时的兜底写法：季数标记换个说法再搜。

    站点对季数写法并不统一：搜 "庆余年2" 是 0 条，资源却叫 "庆余年第二季"。
    只在首轮一个结果都没有时才发这些请求，正常搜索不受影响。
    """
    out = []
    k = (key or "").strip()
    m = _SEASON_TAIL_RE.search(k) if k else None
    if not m:
        return out
    stem = k[:m.start()].strip(" ._-·•")
    num = m.group(1) or m.group(0).strip()
    if not stem:
        return out
    if "季" not in stem:
        out.append(stem)                                  # 庆余年2 -> 庆余年
    if num.isdigit():
        cn = _num2cn(num)
        for v in ("%s第%s季" % (stem, cn), "%s第%s季" % (stem, num)):
            if v not in out and v != k:
                out.append(v)                              # 庆余年2 -> 庆余年第二季 / 庆余年第2季
        out = out[:1] + [v for v in out[1:] if v != stem][:1]
    return [x for x in dict.fromkeys(out) if x and x != k][:2]


# ============================================================
# 首页公告弹窗（msg）
# ============================================================
# TVBox / 影视仓 等支持约定的壳子，会在打开本源时弹出此 msg 作为公告弹窗。
# 不支持该约定的壳子会忽略此字段，不影响使用。
# 可自行修改为站点公告、使用须知、免责声明等；留空字符串则不弹窗。
NOTICE_MSG = (
    "【洛雪TV】\n"
    "本站为第三方影视聚合，内容版权归原平台所有。\n"
    "请遵守当地法律法规，仅作个人学习研究使用。"
)

# ============================================================
# 一级分类（4 个）与所包含的站点真实 type（大类容器，用于客户端归类）
# ============================================================
# 这些 type 取自全站枚举统计（1920 条样本、60 种 type），作为大类边界。
# 站点 type 词表比早期版本硬编码的宽得多，这里按实测补齐，避免有内容落不进任何
# 一级分类而"浏览不到"（旧版就漏了 内地剧 / 东南亚剧 / 纪录剧集 / 中国动漫 /
# 少儿动漫，以及整个「综艺」大类约 250 条）。
_MOVIE_TYPES = ["剧情片", "喜剧片", "动作片", "动画片", "科幻片", "奇幻片", "恐怖片",
                "惊悚片", "爱情片", "悬疑片", "犯罪片", "战争片", "伦理片",
                "记录片", "纪录片", "动漫电影", "其他片", "电影", "电影（B站）",
                "冒险篇", "短片", "影视解说",
                "剧情", "喜剧", "动作", "恐怖", "悬疑"]

_SERIES_TYPES = ["国产剧", "陆剧", "内地剧", "电视剧", "电视剧（B站）",
                 "美剧", "欧美剧", "海外剧",
                 "日本剧", "日剧", "韩国剧", "韩剧", "日韩剧",
                 "泰国剧", "泰剧", "东南亚剧", "香港剧", "台湾剧", "台剧", "纪录剧集",
                 "短剧", "爽文短剧", "其他短剧", "反转爽剧", "现代都市短剧",
                 "年代穿越短剧", "女频恋爱短剧", "古装仙侠短剧", "脑洞悬疑短剧",
                 "AI漫剧"]

_ANIME_TYPES = ["国产动漫", "中国动漫", "日韩动漫", "日本动漫", "欧美动漫", "港台动漫",
                "国创", "国创（B站）", "国创(b站)", "番剧（B站）", "番剧(b站)",
                "动漫", "动画", "少儿", "少儿动漫"]

_VARIETY_TYPES = ["综艺", "大陆综艺", "日韩综艺", "港台综艺", "韩国综艺",
                  "香港综艺", "台湾综艺", "欧美综艺", "网球", "篮球"]

CLASSES = [
    {"type_name": "电影", "type_id": "movie"},
    {"type_name": "剧集", "type_id": "series"},
    {"type_name": "动漫", "type_id": "anime"},
    {"type_name": "综艺", "type_id": "variety"},
]

CLASS_TYPES = {
    "movie": _MOVIE_TYPES,
    "series": _SERIES_TYPES,
    "anime": _ANIME_TYPES,
    "variety": _VARIETY_TYPES,
}

# ============================================================
# 二级分类（每个一级分类下的子类型）
# ============================================================
# 站点接口没有"按类型取列表"的参数，列表只在 /api/proxy.php?action=search 里按
# 关键词字面匹配返回，所以二级分类只能落在本地池子上：把每个子类映射成一组
# 站点真实 type（用 | 连接），客户端选中后在池子里按 type 过滤。
# 这样既保留了站点原有的类型粒度，又能把 国产剧/陆剧/内地剧 这类同义写法归并到
# 一个用户看得懂的入口下。
_SUB_SEP = "|"

_MOVIE_SUB = [
    ("全部", ""),
    ("剧情", "剧情片|剧情"),
    ("喜剧", "喜剧片|喜剧"),
    ("动作", "动作片|动作"),
    ("爱情", "爱情片"),
    ("科幻奇幻", "科幻片|奇幻片"),
    ("恐怖", "恐怖片|恐怖"),
    ("惊悚", "惊悚片"),
    ("悬疑", "悬疑片|悬疑"),
    ("犯罪", "犯罪片"),
    ("战争", "战争片"),
    ("伦理", "伦理片"),
    ("纪录", "记录片|纪录片"),
    ("动画", "动画片|动漫电影"),
    ("解说", "影视解说"),
    ("其他", "其他片|电影|电影（B站）|冒险篇|短片"),
]

_SERIES_SUB = [
    ("全部", ""),
    ("国产", "国产剧|陆剧|内地剧|电视剧|电视剧（B站）"),
    ("港台", "香港剧|台湾剧|台剧"),
    ("日韩", "日本剧|日剧|韩国剧|韩剧|日韩剧"),
    ("欧美", "美剧|欧美剧"),
    ("泰国", "泰国剧|泰剧|东南亚剧"),
    ("海外", "海外剧"),
    ("短剧", "短剧|爽文短剧|其他短剧|反转爽剧|现代都市短剧|年代穿越短剧|"
             "女频恋爱短剧|古装仙侠短剧|脑洞悬疑短剧"),
    ("漫剧", "AI漫剧"),
    ("纪录", "纪录剧集"),
]

_ANIME_SUB = [
    ("全部", ""),
    ("国漫", "国产动漫|中国动漫|国创|国创（B站）|国创(b站)"),
    ("日韩", "日韩动漫|日本动漫"),
    ("欧美", "欧美动漫"),
    ("港台", "港台动漫"),
    ("番剧", "番剧（B站）|番剧(b站)"),
    ("少儿", "少儿|少儿动漫"),
    ("综合", "动漫|动画"),
]

_VARIETY_SUB = [
    ("全部", ""),
    ("大陆", "大陆综艺|综艺"),
    ("港台", "港台综艺|香港综艺|台湾综艺"),
    ("日韩", "日韩综艺|韩国综艺"),
    ("欧美", "欧美综艺"),
    ("体育", "网球|篮球"),
]

SUB_FILTERS = {
    "movie": _MOVIE_SUB,
    "series": _SERIES_SUB,
    "anime": _ANIME_SUB,
    "variety": _VARIETY_SUB,
}

# ============================================================
# 筛选器（每个一级分类：二级分类 + 采集源 + 状态）
# ============================================================

_SOURCE_FILTER = {"key": "source", "name": "采集源", "value": [
    {"n": "全部", "v": ""},
    {"n": "官采蓝光", "v": "qilin"},
    {"n": "4k60帧", "v": "mj"},
    {"n": "自营", "v": "jl"},
    {"n": "360资源", "v": "360zy"},
    {"n": "电影天堂", "v": "dytt"},
    {"n": "ikun", "v": "ik"},
    {"n": "魔都", "v": "md"},
    {"n": "官方源", "v": "fy"},
]}

_STATE_FILTER = {"key": "state", "name": "状态", "value": [
    {"n": "全部", "v": ""},
    {"n": "连载中", "v": "serial"},
    {"n": "已完结", "v": "done"},
]}


def _sub_filter(tid):
    """把子类型映射表包装成 TVBox 的 filters 维度"""
    pairs = SUB_FILTERS.get(tid) or []
    if not pairs:
        return None
    return {
        "key": "sub",
        "name": "类型",
        "value": [{"n": n, "v": v} for n, v in pairs],
    }


FILTERS = {}
for _c in CLASSES:
    _tid = _c["type_id"]
    _dims = []
    _sf = _sub_filter(_tid)
    if _sf:
        _dims.append(_sf)
    _dims.append(_SOURCE_FILTER)
    _dims.append(_STATE_FILTER)
    FILTERS[_tid] = _dims


def _sub_types(value):
    """把筛选值（"国产剧|陆剧" 这样的多类型串）解析成集合"""
    v = (value or "").strip()
    if not v:
        return set()
    return set(x for x in v.split(_SUB_SEP) if x)


# ============================================================
# Spider 主类
# ============================================================

class Spider(Spider):

    def getName(self):
        return "洛雪TV"

    # ===== 初始化 =====
    def init(self, extend=""):
        if isinstance(extend, list):
            self.extend = ""
        else:
            self.extend = extend or ""

        self.header = {
            "User-Agent": UA,
            "Referer": HOST + "/",
            "Accept": "application/json, text/plain, */*",
        }

        # 全站池
        self._pool = []
        self._pool_keys = set()
        self._pool_pages = 0
        self._pool_done = False

        # 封面缓存  "source@id" -> pic
        self._pic_cache = {}

        # 源配置
        self._cfg_ok = False
        self._source_names = dict(SOURCE_NAMES)
        self._source_order = list(SOURCE_ORDER)
        self._name_to_key = dict((v, k) for k, v in SOURCE_NAMES.items())
        self._player_apis = {}
        self._official_routes = [dict(r) for r in FALLBACK_ROUTES]
        self._official_source = "qilin"
        self._default_parse = ""

        # 首页缓存（10 分钟）
        self._home_cache = []
        self._home_cache_time = 0

        # 解析缓存（官源 URL -> 直链），带 TTL
        self._resolve_cache = {}
        self._rc_lock = threading.Lock() if _HAS_THREAD else None

        # 直链健康探测缓存（首集 URL -> {ts, ok}），随解析缓存文件持久化
        self._probe_cache = {}

        # 详情跨源聚合缓存："source@id" -> (ts, vod)
        self._agg_cache = {}
        # 本次会话内 detail 拉取失败的源（不再重复请求）
        self._dead_sources = set()

        # 人机验证串行锁（多线程搜索时避免同时解题互相踩 token）
        self._cap_lock = threading.Lock() if _HAS_THREAD else None
        # 搜索结果缓存：key -> (ts, rows)，翻页/重进搜索页不再重复打接口
        self._search_cache = {}

        # 加载本地缓存（同步，命中则分类浏览秒开）
        self._load_pool_cache()
        self._load_resolve_cache()

    # ===== 缓存: 池子 =====
    def _load_pool_cache(self):
        try:
            if not os.path.exists(POOL_CACHE):
                return
            d = json.load(open(POOL_CACHE, encoding="utf-8"))
            if time.time() - float(d.get("ts", 0)) > POOL_CACHE_TTL:
                return
            pool = d.get("pool") or []
            if not pool:
                return
            self._pool = pool
            self._pic_cache = d.get("pic") or {}
            self._pool_keys = set(
                "%s@%s" % (i.get("source", ""), i.get("id", "")) for i in self._pool
            )
            self._pool_pages = int(d.get("pages", 0) or 0)
            self._pool_done = bool(d.get("done", False))
        except Exception:
            pass

    def _save_pool_cache(self):
        try:
            json.dump(
                {
                    "ts": time.time(),
                    "pool": self._pool,
                    "pic": self._pic_cache,
                    "pages": self._pool_pages,
                    "done": self._pool_done,
                },
                open(POOL_CACHE, "w", encoding="utf-8"),
                ensure_ascii=False,
            )
        except Exception:
            pass

    # ===== 缓存: 解析结果 =====
    def _load_resolve_cache(self):
        try:
            if not os.path.exists(RESOLVE_CACHE):
                return
            d = json.load(open(RESOLVE_CACHE, encoding="utf-8"))
            now = time.time()
            for k, v in (d.get("items") or {}).items():
                if now - float(v.get("ts", 0)) <= RESOLVE_CACHE_TTL:
                    self._resolve_cache[k] = v.get("url", "")
            for k, v in (d.get("probe") or {}).items():
                if isinstance(v, dict) and now - float(v.get("ts", 0)) <= PROBE_TTL:
                    self._probe_cache[k] = v
        except Exception:
            pass

    def _save_resolve_cache(self):
        try:
            items = {k: {"ts": time.time(), "url": u}
                     for k, u in self._resolve_cache.items() if u}
            probe = dict(self._probe_cache or {})
            json.dump({"items": items, "probe": probe},
                      open(RESOLVE_CACHE, "w", encoding="utf-8"),
                      ensure_ascii=False)
        except Exception:
            pass

    def _put_resolve(self, url, link):
        if not link:
            return
        if self._rc_lock:
            with self._rc_lock:
                self._resolve_cache[url] = link
                self._save_resolve_cache()
        else:
            self._resolve_cache[url] = link
            self._save_resolve_cache()

    # ===== 网络工具 =====
    def _rsp_text(self, rsp):
        try:
            return rsp.text
        except Exception:
            try:
                return rsp.content.decode("utf-8", "ignore")
            except Exception:
                return ""

    def _get_json(self, url, timeout=15):
        try:
            rsp = self.fetch(url, headers=self.header, timeout=timeout)
            text = self._rsp_text(rsp)
            if not text:
                return None
            return json.loads(text)
        except Exception:
            return None

    def _txt(self, url, referer=None, timeout=15):
        headers = dict(self.header)
        if referer:
            headers["Referer"] = referer
        try:
            rsp = self.fetch(url, headers=headers, timeout=timeout)
            return self._rsp_text(rsp)
        except Exception:
            return ""

    def _match(self, pattern, text, flags=0):
        m = re.search(pattern, text, flags)
        return m.group(1) if m else ""

    def _solve_captcha(self):
        """自动解站点的人机验证。

        站点对搜索接口限流很激进（实测约 1/4 的请求返回
        {"success":false,"need_captcha":true}），不处理就会静默返回空结果，
        表现为"有的片子搜不到"。验证码是纯算术题（"4 + 1 = ?"），
        配合 action=captcha 拿 token 即可自动通过，token 一次性。
        """
        try:
            data = self._get_json(API + "?" + urlencode({"action": "captcha"}), timeout=8)
        except Exception:
            return None
        if not data:
            return None
        token = str(data.get("token") or "")
        m = _ASK_RE.search(str(data.get("question") or ""))
        if not token or not m:
            return None
        try:
            a, op, b = int(m.group(1)), m.group(2), int(m.group(3))
            if op == "+":
                val = a + b
            elif op == "-":
                val = a - b
            elif op in "*xX×":
                val = a * b
            elif op == "÷":
                if b == 0 or a % b:
                    return None
                val = a // b
            else:
                return None
        except Exception:
            return None
        return token, str(val)

    def _api(self, params, timeout=15, _retry_cap=1):
        """站点 API 封装。遇到人机验证自动解题重试一次（token 一次性，必须重发原请求）。"""
        data = self._get_json(API + "?" + urlencode(params), timeout=timeout)
        if data and data.get("need_captcha") and _retry_cap > 0:
            # 串行化，避免多线程同时触发验证导致 token 互相踩踏
            if self._cap_lock:
                self._cap_lock.acquire()
            try:
                sol = self._solve_captcha()
            finally:
                if self._cap_lock:
                    self._cap_lock.release()
            if sol:
                p2 = dict(params)
                p2["captcha"] = sol[0]
                p2["captcha_answer"] = sol[1]
                time.sleep(0.2)
                data = self._get_json(API + "?" + urlencode(p2), timeout=timeout)
        return data

    # ===== 配置 =====
    def _load_config(self):
        if self._cfg_ok:
            return
        self._cfg_ok = True
        try:
            data = self._api({"action": "config"}, timeout=10)
            if not data or not data.get("success"):
                return
            sources = data.get("sources") or {}
            for key, info in sources.items():
                name = (info or {}).get("name")
                if name:
                    self._source_names[key] = str(name)
                api = (info or {}).get("player_api")
                if api:
                    self._player_apis[key] = api

            # 解析线路（网页端"解析线路"区块：默认解析 / 闪电 / m1907 ...）
            routes = []
            for r in (data.get("official_routes") or []):
                api = (r or {}).get("api") or ""
                if not api:
                    continue
                routes.append({
                    "name": str((r or {}).get("name") or "解析").strip(),
                    "api": api,
                })
            if routes:
                self._official_routes = routes
            self._official_source = str(data.get("official_source") or "qilin").strip() or "qilin"

            # 采集源排序（网页端按此排"普通线路"卡片）
            order = [str(x) for x in (data.get("source_order") or []) if str(x)]
            if not order:
                try:
                    order = [k for k, _ in sorted(
                        sources.items(),
                        key=lambda kv: float((kv[1] or {}).get("order", 99)),
                    )]
                except Exception:
                    order = []
            if order:
                self._source_order = order

            self._default_parse = str(data.get("player_api") or "")
            if not self._default_parse and self._official_routes:
                self._default_parse = self._official_routes[0].get("api", "")

            # 源显示名 -> key 反查表（用于 playerContent 的 flag 识别）
            n2k = {}
            for k in list(self._source_names.keys()) + list(self._source_order):
                nm = self._source_names.get(k)
                if nm:
                    n2k.setdefault(nm, k)
            self._name_to_key = n2k
        except Exception:
            pass

    def _source_rank(self, key):
        """源在站点配置中的排序（普通线路卡片顺序）"""
        try:
            return self._source_order.index(key)
        except ValueError:
            return 900

    def _line_label(self, gname, index=0):
        """播放线路分组显示名（与网页端 lineLabel 一致）"""
        raw = (gname or "").strip()
        if not raw or _TECH_NAME_RE.match(raw):
            return "线路 %d" % (index + 1)
        alias = LINE_NAMES.get(raw.lower()) or LINE_NAMES.get(raw)
        return alias or raw

    def _route_by_name(self, name):
        name = (name or "").strip().lower()
        if not name:
            return None
        for r in self._official_routes:
            if str(r.get("name", "")).strip().lower() == name:
                return r
        for r in self._official_routes:
            if str(r.get("name", "")).strip().lower().startswith(name):
                return r
        return None

    def _default_route_api(self):
        if self._official_routes:
            return self._official_routes[0].get("api", "")
        return self._default_parse or ""

    def _source_api_from_flag(self, flag):
        """从线路名识别采集源，返回该源自己的解析接口（网页端 player_api 行为）
        识别不到时返回空串 -> 交给壳子直接嗅探（与网页端"默认播放器"一致）"""
        flag = (flag or "").strip()
        best_key, best_len = "", 0
        for nm, key in (self._name_to_key or {}).items():
            if nm and flag.startswith(nm) and len(nm) > best_len:
                best_key, best_len = key, len(nm)
        if not best_key:
            key = flag.split("·", 1)[0].strip()
            if key in self._player_apis:
                best_key = key
        return self._player_apis.get(best_key, "")

    # ===== 封面补齐 =====
    def _fill_pics(self, items):
        if not items:
            return items
        miss = []
        for it in items:
            key = "%s@%s" % (it.get("source", ""), it.get("id", ""))
            cached = self._pic_cache.get(key)
            if cached:
                it["pic"] = cached
            elif not it.get("pic"):
                miss.append(it)

        if not miss:
            return items

        try:
            payload = [{"source": it.get("source", ""), "id": it.get("id", "")}
                       for it in miss[:POSTER_BATCH]]
            data = self._api({
                "action": "posters",
                "items": json.dumps(payload, ensure_ascii=False),
            }, timeout=12)
            got = (data or {}).get("items") or []
            mapping = {}
            for row in got:
                pic = row.get("pic") or ""
                if pic:
                    mapping["%s@%s" % (row.get("source", ""), row.get("id", ""))] = pic
            for it in miss:
                key = "%s@%s" % (it.get("source", ""), it.get("id", ""))
                pic = mapping.get(key, "")
                if pic:
                    self._pic_cache[key] = pic
                    it["pic"] = pic
        except Exception:
            pass
        return items

    # ===== 全站池 =====
    def _load_page(self, page):
        if self._pool_done or page > MAX_PAGES:
            return 0
        params = {"action": "search", "wd": "%", "page": str(page)}
        data = self._api(params, timeout=20)
        rows = (data or {}).get("results") or []
        if not rows:
            # 站点偶发返回空页，重试一次再判定到底，避免池子被提前截断
            time.sleep(0.3)
            data = self._api(params, timeout=20)
            rows = (data or {}).get("results") or []
            if not rows:
                self._pool_done = True
                return 0

        added = 0
        for r in rows:
            key = "%s@%s" % (r.get("source", ""), r.get("id", ""))
            if key in self._pool_keys:
                continue
            self._pool_keys.add(key)
            item = {
                "source": r.get("source", ""),
                "id": r.get("id", ""),
                "name": r.get("name", ""),
                "type": r.get("type", ""),
                "pic": r.get("pic", ""),
                "remarks": r.get("remarks", ""),
            }
            if item["pic"]:
                self._pic_cache[key] = item["pic"]
            self._pool.append(item)
            added += 1
        self._pool_pages = max(self._pool_pages, page)
        return added

    def _ensure_pool(self, pages):
        """确保池子至少拉取到 pages 页（并发拉取，无线程环境回退串行）"""
        target = min(int(pages), MAX_PAGES)
        if self._pool_pages >= target or self._pool_done:
            return

        before = len(self._pool)
        need = list(range(self._pool_pages + 1, target + 1))
        if _HAS_THREAD and len(need) > 1:
            ths = []
            for p in need:
                try:
                    t = threading.Thread(target=self._load_page, args=(p,))
                    t.daemon = True
                    ths.append(t)
                    t.start()
                except Exception:
                    self._load_page(p)
            for t in ths:
                try:
                    t.join(20)
                except Exception:
                    pass
        else:
            for p in need:
                self._load_page(p)

        self._pool_pages = max(self._pool_pages, target)
        # 有新增且（拉到底 或 达到本轮目标）时落盘，避免高频写文件
        if len(self._pool) > before and (self._pool_done or self._pool_pages >= target):
            self._save_pool_cache()

    # ===== 条目过滤 =====
    def _hit(self, it, types, sub, src_kw, state_kw):
        t = it.get("type", "")
        if types and t not in types:
            return False
        if sub and t not in sub:
            return False
        if src_kw and it.get("source", "") != src_kw:
            return False
        if state_kw:
            rem = it.get("remarks", "") or ""
            if state_kw == "done":
                if not ("全剧集" in rem or "集全" in rem or "完结" in rem or rem.endswith("全")):
                    return False
            elif state_kw == "serial":
                if "更新至" not in rem and "更新到" not in rem:
                    return False
        return True

    def _collect(self, types, sub, src_kw, state_kw, need):
        """从池子收集匹配项（按大类 type + 二级分类 + 采集源 + 状态过滤），不足则继续拉页"""
        if self._pool_pages == 0:
            self._ensure_pool(PRELOAD_PAGES)

        def _scan():
            out = []
            seen = set()
            for it in self._pool:
                if not self._hit(it, types, sub, src_kw, state_kw):
                    continue
                nm = it.get("name", "")
                if nm in seen:
                    continue
                seen.add(nm)
                out.append(it)
            return out

        matched = _scan()
        step = PRELOAD_PAGES
        while len(matched) < need and not self._pool_done and self._pool_pages < MAX_PAGES:
            before = len(self._pool)
            self._ensure_pool(min(self._pool_pages + step, MAX_PAGES))
            # 又拉了一轮但池子没有任何新增（后面全是重复/空页），再拉也没意义
            if len(self._pool) == before:
                break
            matched = _scan()
            step = min(step * 2, 24)
        return matched

    # ===== 卡片 =====
    def _card(self, it, show_type=False):
        rem = it.get("remarks", "") or ""
        if show_type and it.get("type") and it["type"] not in rem:
            # 搜索结果里"短剧"和"动作片"混在一起，标出类型用户才认得出哪条是正片
            rem = ("%s · %s" % (it["type"], rem)) if rem else it["type"]
        return {
            "vod_id": "%s@%s" % (it.get("source", ""), it.get("id", "")),
            "vod_name": it.get("name", ""),
            "vod_pic": it.get("pic", ""),
            "vod_remarks": rem or it.get("type", "") or "HD",
        }

    def _parse_ext(self, extend):
        ext = {}
        if not extend:
            return ext
        try:
            if isinstance(extend, dict):
                ext = extend
            elif isinstance(extend, str):
                ext = json.loads(extend)
        except Exception:
            ext = {}
        return ext or {}

    # ===== 媒体判断 =====
    def _is_direct_media(self, url):
        u = (url or "").lower()
        # 注意 ".m3u" 是 ".m3u8" 的前缀子串，同时覆盖 jl 等源用的 smart.m3u
        return ".m3u" in u or ".mp4" in u or ".flv" in u or ".mkv" in u

    def _is_official(self, url):
        u = (url or "").lower()
        if self._is_direct_media(u):
            return False
        keys = ("iqiyi.com", "qiyi.com", "youku.com", "mgtv.com", "v.qq.com",
                "bilibili.com", "le.com", "letv.com", "sohu.com", "pptv.com", "1905.com")
        return any(k in u for k in keys)

    def _extract_referer(self, url):
        try:
            if "://" in url:
                scheme = url.split("://")[0]
                host = url.split("://")[1].split("/")[0]
                return scheme + "://" + host + "/"
        except Exception:
            pass
        return HOST + "/"

    # ===== BFQ 官源解析 =====
    def _aes_cbc_decrypt_text(self, cipher_text):
        try:
            from Crypto.Cipher import AES
            key = cipher_text[-32:-16].encode("utf-8")
            iv = cipher_text[-16:].encode("utf-8")
            data = base64.b64decode(cipher_text[:-32])
            raw = AES.new(key, AES.MODE_CBC, iv).decrypt(data)
            pad = raw[-1] if raw else 0
            if 0 < pad <= 16:
                raw = raw[:-pad]
            return raw.decode("utf-8", "ignore")
        except Exception:
            return ""

    def _resolve_official(self, src_url):
        """用 BFQ 把官源播放页解析成 m3u8 直链"""
        if not src_url or not self._is_official(src_url):
            return ""
        try:
            q = quote(src_url, safe="")
            html = self._txt(BFQ_PLAYER + q, referer=BFQ_REFERER + q, timeout=12)
            result = self._match(r'result\s*=\s*"([^"]+)"', html, re.S)
            if not result:
                return ""
            text = self._aes_cbc_decrypt_text(result)
            if not text:
                return ""
            data = json.loads(text)
            video = ((data.get("video_info") or {}).get("video") or {})
            media = (video.get("url") or "").replace("\\/", "/")
            if not media:
                vlist = (data.get("video_info") or {}).get("video")
                if isinstance(vlist, list) and vlist:
                    media = (vlist[0].get("url") or "").replace("\\/", "/")
            if media and self._is_direct_media(media):
                return media
        except Exception:
            pass
        return ""

    def _strip_tags(self, s):
        return re.sub(r'<[^>]+>', '', s or '').strip()

    # ===== 直链健康探测（对齐网页端"资源正常/无法连接"） =====
    def _probe_url(self, url):
        """实测直链：m3u/m3u8 必须返回播放列表（防"HTTP 200 包 404 JSON"假活），其他 2xx 即可"""
        if _urlreq is None:
            return True
        try:
            req = _urlreq.Request(
                url,
                headers={
                    "User-Agent": UA,
                    "Referer": self._extract_referer(url),
                },
            )
            with _urlreq.urlopen(req, timeout=PROBE_TIMEOUT, context=_SSL_CTX) as rsp:
                chunk = rsp.read(512)
            text = (chunk or b"").decode("utf-8", "ignore")
            if ".m3u" in (url or "").lower():
                return ("#EXTM3U" in text) or ("#EXT-X" in text)
            return bool(chunk)
        except Exception:
            return False

    def _probe_ok(self, url):
        """带缓存的探测结果"""
        if not url:
            return False
        now = time.time()
        hit = self._probe_cache.get(url)
        if hit and now - float(hit.get("ts", 0)) <= PROBE_TTL:
            return bool(hit.get("ok"))
        ok = self._probe_url(url)
        self._probe_cache[url] = {"ts": now, "ok": 1 if ok else 0}
        return ok

    def _health_sort(self, play_from, play_url):
        """直链线路按首集探测结果排序：可用在前、失效垫后（不删除线路）。"""
        try:
            idxs = []
            for i, u in enumerate(play_url):
                first = (u or "").split("#", 1)[0]
                ep_url = first.split("$", 1)[1] if "$" in first else first
                if self._is_direct_media(ep_url):
                    idxs.append((i, ep_url))
            if len(idxs) <= 1:
                return play_from, play_url

            now = time.time()
            need = [(i, eu) for i, eu in idxs
                    if eu not in self._probe_cache
                    or now - float(self._probe_cache[eu].get("ts", 0)) > PROBE_TTL]
            if need:
                if _HAS_THREAD and len(need) > 1:
                    ths = []
                    for _, eu in need:
                        try:
                            t = threading.Thread(target=self._probe_ok, args=(eu,))
                            t.daemon = True
                            ths.append(t)
                            t.start()
                        except Exception:
                            self._probe_ok(eu)
                    for t in ths:
                        try:
                            t.join(PROBE_JOIN_TIMEOUT)
                        except Exception:
                            pass
                else:
                    for _, eu in need:
                        self._probe_ok(eu)
                self._save_resolve_cache()

            verdict = {}
            for i, eu in idxs:
                v = self._probe_cache.get(eu)
                verdict[i] = bool(v and v.get("ok"))
            ok_idx = sorted(i for i in verdict if verdict[i])
            bad_idx = sorted(i for i in verdict if not verdict[i])
            rest = [i for i in range(len(play_from)) if i not in verdict]
            if not ok_idx or not bad_idx:
                return play_from, play_url
            order = ok_idx + rest + bad_idx
            return ([play_from[i] for i in order],
                    [play_url[i] for i in order])
        except Exception:
            return play_from, play_url

    # ============================================================
    # 详情：跨源聚合（网页端"普通线路"）
    # ============================================================

    def _fetch_detail(self, source, vod_id, tries=2):
        for _ in range(max(1, tries)):
            data = self._api({"action": "detail", "source": source, "id": vod_id}, timeout=10)
            if data and data.get("success") and data.get("details"):
                return data["details"][0]
            time.sleep(0.25)
        return None

    def _search_rows(self, wd, timeout=12, tries=3):
        """标题搜索。

        站点限流 5 次/分钟，超了返回 success=false + need_captcha（_api 会自动解题重发）。
        只有"请求失败"才退避重试；success=true 但 results 为空是"确实没这部片"，
        重试没有意义，只会白白吃掉限流额度。
        """
        for i in range(max(1, tries)):
            data = self._api({"action": "search", "wd": wd, "page": "1"}, timeout=timeout)
            if not data:
                time.sleep(0.4 * (i + 1))
                continue
            if data.get("success"):
                return data.get("results") or []
            # success=false：验证码已在 _api 内处理过一次，仍失败则退避
            time.sleep(0.6 * (i + 1))
        return []

    def _search_batch(self, words, sink):
        """并发跑多个关键词的搜索（无线程环境自动回退串行）"""
        words = [w for w in words if w]
        if not words:
            return
        if _HAS_THREAD and len(words) > 1:
            ths = []
            for w in words:
                try:
                    t = threading.Thread(target=sink, args=(w,))
                    t.daemon = True
                    ths.append(t)
                    t.start()
                except Exception:
                    sink(w)
            for t in ths:
                try:
                    t.join(16)
                except Exception:
                    pass
        else:
            for w in words:
                sink(w)

    def _search_all(self, key):
        """全写法搜索 + 合并去重（"破局" 同时搜到 蹭词短剧 和 正片"破·局"）。"""
        primary, extra = _search_variants(key)
        rows = {}

        def _sink(wd):
            for r in self._search_rows(wd):
                k = "%s@%s" % (r.get("source", ""), r.get("id", ""))
                if k and k not in rows:
                    rows[k] = r

        # 同一轮并发发出，省掉一次串行往返
        # （搜"破局"首轮全是 破局1950 / 反诈破局 这类蹭词片，正片"破·局"全靠补搜轮）
        self._search_batch(primary + extra, _sink)

        # 一个结果都没有：季数写法可能对不上（"庆余年2" vs "庆余年第二季"），换说法再试
        if not rows:
            self._search_batch(_search_fallbacks(key), _sink)

        items = []
        for r in rows.values():
            item = {
                "source": str(r.get("source", "")),
                "id": str(r.get("id", "")),
                "name": r.get("name", ""),
                "type": r.get("type", ""),
                "pic": r.get("pic", ""),
                "remarks": r.get("remarks", ""),
            }
            if not item["source"] or not item["id"]:
                continue
            items.append(item)
        return items

    def _search_rank(self, name, key):
        """搜索结果排序键：归一化完全一致 > 前缀 > 包含 > 不匹配；
        同档内短标题优先（正片《破·局》压过《破局1950》这类蹭词片）。"""
        s = _title_score(name, key)
        if s >= 99:
            return (3, 0, 0, "")
        n = _norm_title(name)
        return (s, 0, len(n), name or "")

    def _title_candidates(self, source, vod_id, name):
        """跨源找同名影片（普通线路）。

        打分与网页端一致：归一化（去季数）后 0/1/2/99；
        另加"含季数全名一致"优先层，保证能对上同一季就不会拿别的季顶替。
        每个源取最优一条，按 source_order 排序，点击源置顶，最多 12 个源。
        """
        rows = {}

        def _add(s, i, nm, p=""):
            s = str(s or "")
            i = str(i or "")
            if not s or not i:
                return
            k = "%s@%s" % (s, i)
            cur = rows.get(k)
            if cur is None:
                rows[k] = {"source": s, "id": i, "name": nm or "", "pic": p or ""}
            elif p and not cur.get("pic"):
                cur["pic"] = p

        # 点击的条目永远参与
        _add(source, vod_id, name)

        # 池子优先（免请求；浏览过分类后池子已含全站数据）
        for it in list(self._pool):
            _add(it.get("source"), it.get("id"), it.get("name"), it.get("pic"))

        def _covered():
            return len(set(
                r["source"] for r in rows.values()
                if _title_score(r["name"], name) < 99
            ))

        base = _norm_title(name)
        need_base = bool(base) and base != _strict_name(name) and base != (name or "").strip()
        pool_ready = self._pool_pages >= 2 or self._pool_done
        did_search = False

        if pool_ready and _covered() > 1:
            # 池子已能覆盖多个源，零搜索直接聚合
            pass
        elif not pool_ready:
            # 冷启动：全名 + 基础名两次搜索并发跑（_search_rows 内部已过验证码 + 退避重试）
            jobs = [name] + ([base] if need_base else [])
            got = {}

            def _search(wd):
                got[wd] = self._search_rows(wd)

            self._search_batch(jobs, _search)
            for wd in jobs:
                for r in (got.get(wd) or []):
                    _add(r.get("source"), r.get("id"), r.get("name"), r.get("pic"))
            did_search = True
        else:
            # 池子有但覆盖不足：先全名搜索，仍不足再补基础名搜索
            for r in self._search_rows(name):
                _add(r.get("source"), r.get("id"), r.get("name"), r.get("pic"))
            if _covered() <= 1 and need_base:
                for r in self._search_rows(base):
                    _add(r.get("source"), r.get("id"), r.get("name"), r.get("pic"))
            did_search = True

        # 打分：每个源取最优一行（tier0 同季精确 > tier1 网页端模糊）
        # 同分并列按服务器返回顺序取第一条（与网页端 buildCandidates 一致）
        strict = _strict_name(name)
        best = {}
        for idx, r in enumerate(rows.values()):
            sc = _title_score(r["name"], name)
            if sc >= 99:
                continue
            tier = 0 if (strict and _strict_name(r["name"]) == strict) else 1
            cand = (tier, sc, idx)
            cur = best.get(r["source"])
            if cur is None or cand < cur[0]:
                best[r["source"]] = (cand, r)

        picked = [{"source": source, "id": vod_id, "name": name}]
        for s in sorted(best.keys(), key=self._source_rank):
            if s == source:
                continue
            if len(picked) >= AGG_MAX_SOURCES:
                break
            r = best[s][1]
            picked.append({"source": s, "id": r["id"], "name": r["name"]})
        return picked, did_search

    def _fetch_candidate_details(self, cands, cand_details, preferred_source):
        """并发拉取各候选源的详情（失败源本会话内跳过，网页端对应"无法连接"）"""
        todo = []
        for c in cands:
            s = c["source"]
            if s in cand_details or s in self._dead_sources:
                continue
            todo.append(c)
        if not todo:
            return

        def work(c):
            d = self._fetch_detail(c["source"], c["id"], tries=1)
            if d:
                cand_details[c["source"]] = d
            else:
                self._dead_sources.add(c["source"])

        if _HAS_THREAD and len(todo) > 1:
            ths = []
            for c in todo:
                try:
                    t = threading.Thread(target=work, args=(c,))
                    t.daemon = True
                    ths.append(t)
                    t.start()
                except Exception:
                    work(c)
            for t in ths:
                try:
                    t.join(AGG_JOIN_TIMEOUT)
                except Exception:
                    pass
        else:
            for c in todo:
                work(c)

    def _build_lines(self, preferred, cand_details):
        """把各源详情组装成与网页端一致的三段线路。

        线路顺序: 点击源(普通线路置顶) -> 其余采集源(按站点顺序)
                 -> 官采蓝光(官方线路) -> 解析·接口名(解析线路)
        """
        official_key = self._official_source
        play_from, play_url = [], []
        used = set()
        official_groups = []
        first_official = ""

        def _push(label, eps):
            label = (label or "").strip() or "线路"
            if label in used:
                n = 2
                while ("%s·%d" % (label, n)) in used:
                    n += 1
                label = "%s·%d" % (label, n)
            used.add(label)
            play_from.append(label)
            play_url.append("#".join(eps))

        def _groups_of(d):
            out = []
            for g in (d.get("episodes") or []):
                eps = []
                for ep in (g.get("episodes") or []):
                    en = str(ep.get("name", "") or "").strip()
                    eu = str(ep.get("url", "") or "").strip()
                    if not eu:
                        continue
                    eps.append("%s$%s" % (en or ("第%d集" % (len(eps) + 1)), eu))
                if eps:
                    out.append((str(g.get("group", "") or "").strip(), eps))
            if not out:
                raw = str(d.get("play_url", "") or "").strip()
                if raw:
                    out.append(("", [x for x in raw.split("#") if x.strip()]))
            return out

        def _disp(key):
            return self._source_names.get(key) or SOURCE_NAMES.get(key) or key

        others = [s for s in cand_details.keys() if s != preferred]
        others.sort(key=self._source_rank)
        seq = [preferred] + [s for s in others if s != official_key]
        if official_key != preferred and official_key in cand_details:
            seq.append(official_key)

        for src in seq:
            d = cand_details.get(src)
            if not d:
                continue
            disp = _disp(src)
            groups = _groups_of(d)
            is_official_src = (src == official_key)
            for gi, (gname, eps) in enumerate(groups):
                first_url = ""
                for s in eps:
                    if "$" in s:
                        first_url = s.split("$", 1)[1]
                        break
                direct = self._is_direct_media(first_url)
                if len(groups) == 1:
                    label = disp
                else:
                    label = "%s·%s" % (disp, self._line_label(gname, gi))
                # 官方采集源的非直链分组：并入"解析线路"供手动换接口
                if is_official_src and not direct:
                    official_groups.append((self._line_label(gname, gi), eps))
                    if not first_official and first_url:
                        first_official = first_url
                _push(label, eps)

        # 解析线路：官源合集 × 站点配置的解析接口（默认解析 / 闪电 / m1907 ...）
        if official_groups and self._official_routes:
            multi = len(official_groups) > 1
            for route in self._official_routes:
                eps = []
                for gl, ge in official_groups:
                    for s in ge:
                        if multi and "$" in s:
                            nm, _, uu = s.partition("$")
                            eps.append("%s %s$%s" % (gl, nm, uu))
                        else:
                            eps.append(s)
                _push("%s·%s" % (PARSER_FLAG, route.get("name", "解析")), eps)

        return play_from, play_url, first_official

    # ============================================================
    # 首页
    # ============================================================

    def homeContent(self, filter):
        result = {
            "class": CLASSES,
            "filters": FILTERS,
        }
        # 公告弹窗：支持该约定的壳子会在打开本源时弹出 NOTICE_MSG
        if NOTICE_MSG:
            result["msg"] = NOTICE_MSG
        return result

    def homeVideoContent(self, filter=None):
        now = int(time.time())
        if self._home_cache and now - self._home_cache_time < 600:
            return {"list": self._home_cache[:72]}

        videos = []
        data = self._api({"action": "home"}, timeout=15)
        if data and data.get("success"):
            cats = data.get("categories") or {}
            for name in cats:
                for r in (cats.get(name) or []):
                    item = {
                        "source": r.get("source", "") or "qilin",
                        "id": r.get("id", ""),
                        "name": r.get("name", ""),
                        "type": r.get("type", "") or name,
                        "pic": r.get("pic", ""),
                        "remarks": r.get("remarks", "") or r.get("year", ""),
                    }
                    key = "%s@%s" % (item["source"], item["id"])
                    if item["pic"]:
                        self._pic_cache[key] = item["pic"]
                    if key not in self._pool_keys:
                        self._pool_keys.add(key)
                        self._pool.append(item)
                    videos.append(self._card(item))

        self._home_cache = videos[:72]
        self._home_cache_time = now
        return {"list": self._home_cache}

    # ============================================================
    # 分类列表（二级筛选在这里生效）
    # ============================================================

    def categoryContent(self, tid, pg, filter, extend):
        try:
            page = int(pg or 1)
            if page < 1:
                page = 1

            ext = self._parse_ext(extend)
            tid = str(tid)
            types = CLASS_TYPES.get(tid, [])
            if not types and tid not in CLASS_TYPES:
                types = [tid]

            # 二级分类：把子类型映射成站点真实 type 集合，与一级分类取交集。
            # 交集为空说明拿到的是旧值/脏值（子类映射表改过），此时整个维度作废退回
            # 大类全量，而不是让用户点开一个空分类。
            sub = _sub_types(ext.get("sub", ""))
            if sub:
                narrowed = [t for t in types if t in sub]
                if narrowed:
                    types = narrowed
                else:
                    sub = set()

            src_kw = ext.get("source", "")
            state_kw = ext.get("state", "")

            matched = self._collect(types, sub, src_kw, state_kw, page * LIMIT)
            total = len(matched)
            start = (page - 1) * LIMIT
            slice_items = matched[start:start + LIMIT]

            self._fill_pics(slice_items)
            vods = [self._card(it) for it in slice_items]

            has_more = len(slice_items) >= LIMIT
            pagecount = page + 1 if has_more else page

            return {
                "list": vods,
                "page": page,
                "pagecount": pagecount,
                "limit": LIMIT,
                "total": total,
            }
        except Exception:
            return {"page": 1, "pagecount": 1, "limit": LIMIT, "total": 0, "list": []}

    # ============================================================
    # 详情
    # ============================================================

    def detailContent(self, ids):
        if isinstance(ids, str):
            ids = [ids]
        raw = str(ids[0] or "")

        if "@" in raw:
            source, vod_id = raw.split("@", 1)
        else:
            source, vod_id = self._official_source, raw
        source = source or self._official_source

        # 聚合结果进程内缓存（同片二次打开直出）
        self._load_config()
        cached = self._agg_cache.get(raw)
        if cached and time.time() - cached[0] < AGG_CACHE_TTL:
            return {"list": [cached[1]]}

        d = self._fetch_detail(source, vod_id, tries=2)
        if not d:
            return {"list": []}

        name = d.get("name", "")
        pic = d.get("pic", "") or ""
        self._pic_cache["%s@%s" % (source, vod_id)] = pic

        # ===== 普通线路：跨源聚合同名影片 =====
        cands, searched = self._title_candidates(source, vod_id, name)
        cand_details = {source: d}
        if len(cands) > 1:
            self._fetch_candidate_details(cands, cand_details, source)

        play_from, play_url, first_official = self._build_lines(source, cand_details)

        # 直链健康探测：可用线路排前、失效线路垫后（防默认播到死链卡 0 KB/s）
        play_from, play_url = self._health_sort(play_from, play_url)

        if not play_url:
            return {"list": []}

        # 官源首条线路后台预解析，点播时大概率已缓存 -> 秒播
        if first_official and _HAS_THREAD:
            try:
                t = threading.Thread(
                    target=self._prefetch_resolve,
                    args=(first_official,),
                    daemon=True,
                )
                t.start()
            except Exception:
                pass

        content = self._strip_tags(d.get("content", ""))[:500]

        vod = {
            "vod_id": raw,
            "vod_name": name,
            "vod_pic": pic,
            "type_name": d.get("type", ""),
            "vod_year": d.get("year", ""),
            "vod_area": d.get("area", ""),
            "vod_remarks": d.get("remarks", "") or "HD",
            "vod_actor": d.get("actor", ""),
            "vod_director": d.get("director", ""),
            "vod_content": content,
            "vod_play_from": "$$$".join(play_from),
            "vod_play_url": "$$$".join(play_url),
        }

        # 缓存控制（简单上限清理）；搜索被限流导致聚合降级时不缓存，下次打开重试
        if len(play_from) >= 2 or not searched:
            if len(self._agg_cache) > 60:
                for k in sorted(self._agg_cache, key=lambda x: self._agg_cache[x][0])[:30]:
                    self._agg_cache.pop(k, None)
            self._agg_cache[raw] = (time.time(), vod)

        return {"list": [vod]}

    def _prefetch_resolve(self, official_url):
        """后台预解析官源首集，结果写入缓存"""
        if not official_url or not self._is_official(official_url):
            return
        if self._resolve_cache.get(official_url):
            return
        link = self._resolve_official(official_url)
        if link:
            self._put_resolve(official_url, link)

    # ============================================================
    # 搜索
    # ============================================================

    def searchContent(self, key, quick, pg="1"):
        try:
            page = int(pg or 1)
            if page < 1:
                page = 1

            ck = (key or "").strip()
            hit = self._search_cache.get(ck)
            if not hit or time.time() - hit[0] > SEARCH_CACHE_TTL:
                items = self._search_all(ck)
                self._search_cache = {ck: (time.time(), items)}
            else:
                items = hit[1]

            # 相关性排序：正片顶到前面，蹭词的短剧沉底；同档按站点源顺序
            items = sorted(items, key=lambda it: (
                self._search_rank(it.get("name", ""), ck),
                self._source_rank(it.get("source", "")),
            ))

            # 入池（详情页跨源聚合可直接复用，省一次搜索）
            for it in items:
                k = "%s@%s" % (it.get("source", ""), it.get("id", ""))
                if it.get("pic"):
                    self._pic_cache[k] = it["pic"]
                if k not in self._pool_keys:
                    self._pool_keys.add(k)
                    self._pool.append(it)

            self._fill_pics(items)

            # 本地分页：一次搜全量，翻页不再打接口（站点 page 参数的 total 不可信）
            start = (page - 1) * LIMIT
            chunk = items[start:start + LIMIT]
            vods = [self._card(it, show_type=True) for it in chunk]
            return {
                "list": vods,
                "page": page,
                "pagecount": max(1, (len(items) + LIMIT - 1) // LIMIT),
                "limit": LIMIT,
                "total": len(items),
            }
        except Exception:
            return {"list": []}

    # ============================================================
    # 播放解析
    # ============================================================

    def playerContent(self, flag, id, vipFlags):
        if not id:
            return {"parse": 0, "playUrl": "", "url": ""}

        play_url = str(id).replace("\\/", "/")
        flag = str(flag or "")

        # 1. 直链（m3u8/mp4）-> 直接播
        if self._is_direct_media(play_url):
            is_m3u8 = ".m3u8" in play_url.lower()
            return {
                "parse": 0,
                "playUrl": "",
                "url": play_url,
                "header": {
                    "User-Agent": UA,
                    "Referer": self._extract_referer(play_url),
                },
                "format": "application/x-mpegURL" if is_m3u8 else "",
                "contentType": "application/x-mpegURL" if is_m3u8 else "",
            }

        # 2. 解析线路 Tab（网页端"解析线路"手动选择的接口，如 解析·闪电 / 解析·m1907）
        if flag.startswith(PARSER_FLAG + "·"):
            route = self._route_by_name(flag[len(PARSER_FLAG) + 1:])
            if route and route.get("api"):
                return {
                    "parse": 1,
                    "playUrl": route["api"],
                    "url": play_url,
                    "header": {
                        "User-Agent": UA,
                        "Referer": HOST + "/",
                    },
                }

        # 3. 官源 -> 先看解析缓存，命中则直出（免 BFQ 等待）
        if self._is_official(play_url):
            cached = self._resolve_cache.get(play_url)
            if cached:
                is_m3u8 = ".m3u8" in cached.lower()
                return {
                    "parse": 0,
                    "playUrl": "",
                    "url": cached,
                    "header": {
                        "User-Agent": UA,
                        "Referer": self._extract_referer(play_url),
                    },
                    "format": "application/x-mpegURL" if is_m3u8 else "",
                    "contentType": "application/x-mpegURL" if is_m3u8 else "",
                }

            resolved = self._resolve_official(play_url)
            if resolved:
                self._put_resolve(play_url, resolved)
                is_m3u8 = ".m3u8" in resolved.lower()
                return {
                    "parse": 0,
                    "playUrl": "",
                    "url": resolved,
                    "header": {
                        "User-Agent": UA,
                        "Referer": self._extract_referer(play_url),
                    },
                    "format": "application/x-mpegURL" if is_m3u8 else "",
                    "contentType": "application/x-mpegURL" if is_m3u8 else "",
                }

            # 4. 内置解析失败 -> 交给壳子用站点"默认解析"接口
            self._load_config()
            return {
                "parse": 1,
                "playUrl": self._default_route_api(),
                "url": play_url,
                "header": {
                    "User-Agent": UA,
                    "Referer": HOST + "/",
                },
            }

        # 5. 其他网页源（如 jlplayer 分组）-> 用该采集源自己的解析接口（与网页端一致）
        self._load_config()
        return {
            "parse": 1,
            "playUrl": self._source_api_from_flag(flag),
            "url": play_url,
            "header": {
                "User-Agent": UA,
                "Referer": HOST + "/",
            },
        }

    # ===== 本地代理 =====
    def localProxy(self, param):
        return [200, "video/MP2T", b"", ""]

    # ===== 清理 =====
    def destroy(self):
        self._pool = []
        self._pool_keys = set()
        self._pic_cache = {}
        self._resolve_cache = {}
        self._probe_cache = {}
        self._agg_cache = {}
        self._dead_sources = set()

    def close(self):
        self.destroy()
