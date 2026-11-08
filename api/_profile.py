"""公司简介(代码拼装,不用 AI):
1) 中文维基百科的开头段(人写的大白话;名字对不上就放弃,宁缺毋滥);
2) 没有中文条目时,用 Yahoo 里的年报业务描述,机器翻译并裁成三句以内;
3) 基本信息卡:总部、员工、CEO、行业、官网(Yahoo)。
所有来源都在返回里标明。"""
import re, time, urllib.parse
import _core as C

WIKI_UA = {"User-Agent": "StocksMonitor/1.0 (personal stock dashboard; https://stock-monitor-kappa-three.vercel.app)"}
SECTOR_ZH = {"Technology": "科技", "Communication Services": "通信与传媒", "Consumer Cyclical": "可选消费", "Consumer Defensive": "必需消费", "Healthcare": "医疗健康",
             "Financial Services": "金融", "Industrials": "工业", "Energy": "能源", "Utilities": "公用事业", "Real Estate": "房地产", "Basic Materials": "基础材料"}
COUNTRY_ZH = {"United States": "美国", "China": "中国", "Taiwan": "中国台湾", "Hong Kong": "中国香港", "Japan": "日本", "United Kingdom": "英国", "Canada": "加拿大", "Germany": "德国",
              "France": "法国", "Netherlands": "荷兰", "Switzerland": "瑞士", "Ireland": "爱尔兰", "Luxembourg": "卢森堡", "Israel": "以色列", "Brazil": "巴西", "India": "印度",
              "South Korea": "韩国", "Singapore": "新加坡", "Australia": "澳大利亚", "Bermuda": "百慕大", "Cayman Islands": "开曼群岛", "Argentina": "阿根廷", "Mexico": "墨西哥"}
KEYWORDS = r"company|corporation|manufacturer|retailer|firm|conglomerate|bank|brand|operator|provider|maker|producer|developer|supplier|chain|stores?|business|enterprise|airline|automaker|group|platform|multinational"


def _clean_name(n):
    n = re.sub(r"[,.]", " ", n or "")
    n = re.sub(r"\b(Inc|Incorporated|Corp|Corporation|Co|Company|Ltd|Limited|PLC|Holdings|Group|Class [A-Z]|N\.?V|S\.?A|LLC|Technologies|The)\b", " ", n, flags=re.I)
    return re.sub(r"\s+", " ", n).strip()


def _sentences(zh, max_chars=260, max_n=3):
    zh = re.sub(r"[（(][^）)]{0,80}[）)]", "", zh or "")           # 去掉括号里的外文名和注释
    zh = re.sub(r"\s+", " ", zh).strip().replace("。 ", "。")
    zh = re.sub(r"([，。、；：]) +", r"\1", zh)
    out = ""
    for i, s in enumerate([x for x in zh.split("。") if x.strip()]):
        if i >= max_n or (out and len(out) + len(s) > max_chars):
            break
        out += s.strip() + "。"
    return out


def _wiki_zh(name):
    q = _clean_name(name)
    if not q:
        return None
    first = q.split()[0].lower()
    d = C._get("https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode({
        "action": "query", "generator": "search", "gsrsearch": q + " company", "gsrlimit": 3, "prop": "extracts|langlinks", "exintro": 1, "explaintext": 1,
        "exchars": 400, "exlimit": 3, "lllang": "zh", "format": "json"}), 86400, WIKI_UA)
    pages = sorted((d.get("query") or {}).get("pages", {}).values(), key=lambda p: p.get("index", 99))
    for p in pages:
        if first not in [w.lower() for w in re.findall(r"\w+", p.get("title", ""))]:
            continue                                                  # 标题里没有公司名第一个词,多半搜偏了
        if not re.search(KEYWORDS, (p.get("extract") or "")[:400], re.I):
            continue                                                  # 看起来不是公司条目
        zl = (p.get("langlinks") or [{}])[0].get("*")
        if not zl:
            return {"en_title": p["title"], "zh": None}
        z = C._get("https://zh.wikipedia.org/w/api.php?" + urllib.parse.urlencode({
            "action": "query", "titles": zl, "prop": "extracts", "exintro": 1, "explaintext": 1, "variant": "zh-cn", "format": "json"}), 86400, WIKI_UA)
        txt = _sentences(next(iter(z["query"]["pages"].values())).get("extract", ""))
        return {"en_title": p["title"], "zh_title": zl, "zh": txt or None, "url": "https://zh.wikipedia.org/wiki/" + urllib.parse.quote(zl)}
    return None


def _facts(sym):
    r = C._yh_open(f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{urllib.parse.quote(sym)}?modules=assetProfile,price")["quoteSummary"]["result"][0]
    ap, pr = r.get("assetProfile") or {}, r.get("price") or {}
    ceo = next((o for o in ap.get("companyOfficers", []) if re.search(r"chief executive|\bceo\b", (o.get("title") or ""), re.I)), None)
    name = re.sub(r"^(Mr|Ms|Mrs|Dr|Prof)\.?\s+", "", (ceo or {}).get("name") or "")
    loc = "、".join(x for x in (COUNTRY_ZH.get(ap.get("country"), ap.get("country")), ap.get("state"), ap.get("city")) if x)
    return {"name": pr.get("longName") or pr.get("shortName"), "sector": ap.get("sector"), "industry": ap.get("industry"), "emp": ap.get("fullTimeEmployees"),
            "loc": loc or None, "web": ap.get("website"), "ceo": re.sub(r"\s+", " ", name) or None, "summary": ap.get("longBusinessSummary"), "type": pr.get("quoteType")}


def profile(sym):
    hit = C._cache.get("prof:" + sym)
    if hit and time.time() - hit[0] < 43200:
        return hit[1]
    f = _facts(sym)
    if f.get("type") not in (None, "EQUITY"):
        out = {"error": "not_stock"}
    else:
        w = None
        try:
            w = _wiki_zh(f["name"])
        except Exception as e:
            C.DBG["wiki"] = f"{sym}: {type(e).__name__}"
        if w and w.get("zh"):
            text, src, url = w["zh"], "中文维基百科「" + w["zh_title"] + "」", w["url"]
        else:
            zh = C._zh(C._head(f["summary"] or "", 800)) if f.get("summary") else None
            text, src, url = _sentences(zh, 320, 4) if zh else None, "公司年报业务描述(Yahoo),机器翻译", None
        ind = C._zh(f["industry"]) if f.get("industry") else None
        out = {"text": text, "src": src, "url": url, "orig": f.get("summary") if not (w and w.get("zh")) else None,
               "facts": {"name": f["name"], "sector": SECTOR_ZH.get(f["sector"], f["sector"]), "industry": (ind or f["industry"] or "").rstrip("。"), "emp": f["emp"], "loc": f["loc"],
                         "web": f["web"], "ceo": f["ceo"]}, "asof": time.strftime("%Y-%m-%d")}
    C._cache["prof:" + sym] = (time.time(), out)
    return out
