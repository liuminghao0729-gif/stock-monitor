"""通过 Telegram 机器人发消息(替代之前的 ntfy)。
环境变量(都是保密信息,只放在 GitHub Secrets,绝不写进代码):
  TELEGRAM_BOT_TOKEN  机器人令牌(@BotFather 创建机器人时给的)
  TELEGRAM_CHAT_ID    收消息的聊天编号;要发给多个人/群,用英文逗号隔开,如 "123456,-1001234567"
"""
import html, json, os, urllib.request


def configured():
    return bool(os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID"))


def send_tg(title, message, click="", silent=False):
    """发一条消息:标题加粗,正文,最后一行是链接。任何一个收件人失败都会抛错。"""
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    text = f"<b>{html.escape(title)}</b>\n{html.escape(message)}"
    if click:
        text += f"\n{html.escape(click)}"
    text = text[:4000]  # Telegram 单条上限 4096
    errs = []
    for chat in [c.strip() for c in os.environ["TELEGRAM_CHAT_ID"].split(",") if c.strip()]:
        body = json.dumps({"chat_id": chat, "text": text, "parse_mode": "HTML",
                           "disable_web_page_preview": True, "disable_notification": silent}).encode()
        try:
            urllib.request.urlopen(urllib.request.Request(
                f"https://api.telegram.org/bot{token}/sendMessage", data=body,
                headers={"Content-Type": "application/json"}), timeout=20).read()
        except Exception as e:  # 不把令牌打印出来
            errs.append(f"chat {chat}: {type(e).__name__} {getattr(e, 'code', '')}")
    if errs:
        raise RuntimeError("Telegram 发送失败 → " + "; ".join(errs))
