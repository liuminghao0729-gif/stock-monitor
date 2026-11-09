"""按人推送:盘中每小时摘要里「你的自选股和持仓」部分,发到每个人自己的 Telegram。
数据来自 Supabase 的 user_data 表(用户登录网站后自己填的自选股、持仓、Telegram Id)。
环境变量(保密信息,只放在 GitHub Secrets,绝不写进代码):
  SUPABASE_URL           项目地址
  SUPABASE_SERVICE_KEY   服务端密钥(能读所有人的行,只给推送任务用,绝不能放进网页或代码)
  TELEGRAM_BOT_TOKEN     机器人令牌
没配置时什么都不做。只含信息,不是买卖建议。"""
import datetime, json, os, urllib.request, urllib.parse

MAX_USERS = 20           # 保险:一次最多处理这么多人
MAX_SYMS = 60            # 每人最多看这么多只


def configured():
    return bool(os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SERVICE_KEY"))


def fetch_users():
    """所有填了 Telegram Id 并且开启了摘要的用户。"""
    url = os.environ["SUPABASE_URL"].rstrip("/") + "/rest/v1/user_data?" + urllib.parse.urlencode(
        {"select": "user_id,watch,holdings,tg_chat_id,tg_hourly", "tg_chat_id": "not.is.null", "tg_hourly": "eq.true", "limit": str(MAX_USERS)})
    key = os.environ["SUPABASE_SERVICE_KEY"]
    req = urllib.request.Request(url, headers={"apikey": key, "Authorization": "Bearer " + key})
    return json.loads(urllib.request.urlopen(req, timeout=20).read().decode())


def clean(u):
    """整理一个用户的数据,过滤掉格式不对的内容。"""
    chat = str(u.get("tg_chat_id") or "").strip()
    if not (chat.lstrip("-").isdigit() and 5 <= len(chat.lstrip("-")) <= 15):
        return None
    watch = [s.upper() for s in (u.get("watch") or []) if isinstance(s, str)][:MAX_SYMS]
    hold = [{"sym": h["sym"].upper(), "qty": float(h["qty"]), "cost": float(h["cost"])} for h in (u.get("holdings") or [])
            if isinstance(h, dict) and isinstance(h.get("sym"), str) and float(h.get("qty") or 0) > 0 and float(h.get("cost") or 0) > 0][:MAX_SYMS]
    return {"chat": chat, "watch": watch, "hold": hold}


def usd(x, sign=False):
    s = f"{abs(x):,.0f}"
    return ("+" if sign and x >= 0 else "-" if x < 0 else "") + "$" + s


def build(t, u, quotes, news=None, head=None, extra=None, min_pct=None):
    """u: clean() 的结果;quotes: {代码: {"price","pct"}}(取不到的不在里面);news: [(标签, 标题)]。返回 (标题, 正文) 或 None。
    min_pct:只列今天涨跌幅(相对昨收)绝对值 >= 这个数的股票(持仓和自选都按这个);None = 全部列出。
    只看异动时:没有异动、也没有 extra(盘中选股更新)就返回 None,不发消息。"""
    held = {h["sym"] for h in u["hold"]}
    if not u["hold"] and not u["watch"]:
        return None
    big = lambda pct: min_pct is None or abs(pct or 0) >= min_pct
    rows, missing, tv, tc, day, movers = [], [], 0.0, 0.0, 0.0, []
    for h in u["hold"]:
        q = quotes.get(h["sym"])
        if not q:
            missing.append(h["sym"]); continue
        px, pct = q["price"], (q["pct"] or 0.0)
        prev = px / (1 + pct / 100) if pct > -100 else px
        v, c, d = h["qty"] * px, h["qty"] * h["cost"], h["qty"] * (px - prev)
        tv += v; tc += c; day += d
        if big(pct):
            rows.append((abs(pct), h["sym"], f"· {h['sym']} {px:,.2f}({pct:+.2f}%) 今日 {usd(d, True)},累计 {(px / h['cost'] - 1) * 100:+.1f}%"))
    wrows = [(abs(quotes[s]["pct"] or 0), s, f"{s} {quotes[s]['price']:,.2f}({(quotes[s]['pct'] or 0):+.2f}%)") for s in u["watch"] if s not in held and s in quotes and big(quotes[s]["pct"])]
    movers = [r[1] for r in rows] + [r[1] for r in wrows]
    title = f"我的持仓异动 {t.strftime('%H:%M')}" if min_pct is not None else f"我的持仓 {t.strftime('%H:%M')}"
    lines = [title + " 美西" + (f"(只列今天涨跌超过 ±{min_pct:g}% 的)" if min_pct is not None else "")] + list(head or [])
    if min_pct is not None and not movers:
        if not extra:
            return None
        lines.append(f"【异动】你的持仓和自选股今天都没有超过 ±{min_pct:g}% 的" + (f"(没取到报价:{'、'.join(missing)})" if missing else ""))
    else:
        if rows:
            lines.append("【持仓" + ("异动" if min_pct is not None else "") + "】")
            lines += [r[2] for r in sorted(rows, key=lambda r: -r[0])]
        if wrows:
            lines.append("【自选" + ("异动" if min_pct is not None else "") + "】" + "  ".join(r[2] for r in sorted(wrows, key=lambda r: -r[0])))
        if u["hold"] and tv > 0:
            lines.append(f"【持仓合计】今日 {usd(day, True)}" + (f"({day / (tv - day) * 100:+.2f}%)" if tv - day > 0 else "") + f",总市值 {usd(tv)},累计盈亏 {usd(tv - tc, True)}({(tv / tc - 1) * 100:+.1f}%)")
        if missing:
            lines.append("(没取到报价:" + "、".join(missing) + ")")
        if min_pct is None:
            if not [s for s in u["watch"] if s not in held]:
                lines.append("【自选】你的自选股都已在上面的持仓里" if u["watch"] else "【自选】云端还没有你的自选股(在网页里添加后等几秒,下一次就会出现)")
    lines.append(f"(云端已同步:自选 {len(u['watch'])} 只、持仓 {len(u['hold'])} 只)")
    nl = [(tag, h) for tag, h in (news or []) if min_pct is None or tag in movers]
    if nl:
        lines.append("【和这些股票有关的要闻】")
        lines += [f"· [{tag}] {h}" for tag, h in nl[:3]]
    lines += list(extra or [])
    lines.append("只含信息,不是买卖建议;模型信号不保证收益,可能亏损,请自行判断风险")
    return title, "\n".join(lines)


def run(t, quote_fn, news_fn=None, send_fn=None, dry=False, users=None, head=None, extra=None, min_pct=None):
    """给每个开启了摘要的用户发一条。quote_fn(代码)->{"price","pct"}|None;news_fn(代码列表)->{代码:[(标签,标题)]};
    head:每个人消息开头都带的共用行;extra:结尾的共用行(盘中选股更新);min_pct:只列涨跌幅超过这个数的股票(没有异动就不发)。
    返回「已经成功发给个人版的聊天编号」集合,共用摘要不再重复发给他们。任何一个人出错不影响其他人。"""
    if users is None:
        if not configured():
            print("没有设置 SUPABASE_URL / SUPABASE_SERVICE_KEY,跳过按人推送")
            return set()
        users = fetch_users()
    people = [p for p in (clean(u) for u in users) if p]
    syms = sorted({s for p in people for s in p["watch"] + [h["sym"] for h in p["hold"]]})
    quotes = {}
    for s in syms:                                   # 所有人的股票合并后只查一次
        q = quote_fn(s)
        if q:
            quotes[s] = q
    news = news_fn(syms) if news_fn else {}
    served, nsent = set(), 0
    for p in people:
        try:
            mine = p["watch"] + [h["sym"] for h in p["hold"]]
            nl = [(s, h) for s in dict.fromkeys(mine) for h in news.get(s, [])]
            if p["watch"] or p["hold"]:
                served.add(p["chat"])                  # 填了股票的人,不管今天有没有异动,都不再收共用摘要;还没填股票的照旧收共用摘要
            r = build(t, p, quotes, nl, head, extra, min_pct)
            if not r:
                continue
            if dry or os.environ.get("DRY_RUN"):
                print("====", r[0], "→ chat", p["chat"][:3] + "***", "====\n" + r[1] + "\n")
            else:
                (send_fn or _send)(r[0], r[1], p["chat"])
            nsent += 1
        except Exception as e:
            served.discard(p["chat"])                  # 这个人的个人版没发出去:退回共用摘要,不让他什么都收不到
            print("按人推送失败(这个人改收共用摘要):", type(e).__name__, str(e)[:80])
    print(f"按人推送:{len(people)} 人开启了提醒,实际发送 {nsent} 条(没有异动的人不发)" if min_pct is not None else f"按人推送:{len(people)} 人,发送 {nsent} 条")
    return served


def split_message(text, limit=3800):
    """Telegram 单条消息上限约 4096 字:太长就按行拆成几条(不在一行中间断开)。"""
    parts, cur = [], ""
    for line in text.splitlines(keepends=True):
        while len(line) > limit:                     # 单行本身就超长:硬切
            if cur:
                parts.append(cur); cur = ""
            parts.append(line[:limit]); line = line[limit:]
        if len(cur) + len(line) > limit:
            parts.append(cur); cur = ""
        cur += line
    if cur:
        parts.append(cur)
    return parts


def _send(title, message, chat):
    import tg
    old = os.environ.get("TELEGRAM_CHAT_ID")
    os.environ["TELEGRAM_CHAT_ID"] = chat            # 只发给这个人
    try:
        for i, part in enumerate(split_message(message)):
            tg.send_tg(title if i == 0 else title + "(续)", part)
    finally:
        if old is None:
            os.environ.pop("TELEGRAM_CHAT_ID", None)
        else:
            os.environ["TELEGRAM_CHAT_ID"] = old


def remaining_chats(all_ids, served):
    """共用摘要还要发给谁:TELEGRAM_CHAT_ID 里的人,去掉已经收到个人版的。返回逗号分隔的字符串,空表示都不用发。"""
    return ",".join(c.strip() for c in (all_ids or "").split(",") if c.strip() and c.strip() not in served)
