# -*- coding: utf-8 -*-
import os
import time
import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from google import genai
from google.genai import types

import config

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s", level=logging.INFO
)
log = logging.getLogger("gymbot")

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
GEMINI_KEY = os.environ["GEMINI_API_KEY"]
MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

client = genai.Client(api_key=GEMINI_KEY)
G = config.GYM

SYSTEM_PROMPT = f"""
تو دستیار هوشمند «{G['name']}» هستی و فقط به فارسی روان جواب می‌دهی.
وظیفه‌ات: جواب دادن به سؤال‌های مشتری‌ها درباره باشگاه، ورزش بدنسازی، تمرین و تغذیه.

اطلاعات باشگاه:
آدرس: {G['address']} | تلفن: {G['phone']}
ساعت کاری:
{G['hours']}
قیمت‌ها:
{G['prices']}
مربیان:
{G['coaches']}
مکمل‌ها: {G['supplements']}
قوانین:
{G['rules']}
امکانات: {G['facilities']}
سایت: {config.LINKS['site']} | ثبت‌نام: {config.LINKS['register']} | همراه دوندگی: {config.LINKS['running']} | فروشگاه: {config.LINKS['shop']}

قوانین مهم:
- اگر اطلاعاتی درباره باشگاه در بالا نیست، حدس نزن و بگو با شماره باشگاه تماس بگیرند.
- هیچ تشخیص یا درمان پزشکی نده. برای درد، مصدومیت یا بیماری بگو به پزشک مراجعه کنند.
- هرگز استروئید، مواد نیروزا یا روش‌های خطرناک کاهش وزن توصیه نکن.
- جواب‌ها کوتاه، مفید و دوستانه باشند. از علامت‌های مارک‌داون مثل ** و # استفاده نکن؛
  از ایموجی و شماره‌گذاری ساده استفاده کن.
- وقتی مناسب بود لینک مرتبط سایت را بده.
""".strip()

GOALS = {"mass": "افزایش حجم", "cut": "کاهش وزن", "fit": "تناسب اندام", "str": "افزایش قدرت"}
LEVELS = {"beg": "مبتدی", "mid": "متوسط", "adv": "پیشرفته"}
DAYS = ["۲", "۳", "۴", "۵", "۶"]

COOLDOWN = 3  # ثانیه بین پیام‌های هر کاربر
_last_msg: dict[int, float] = {}


# ----------------------------- ابزارها -----------------------------
def normalize(t: str) -> str:
    t = t.replace("ي", "ی").replace("ك", "ک").replace("\u200c", " ")
    return t.lower().strip()


def find_keyword(text: str):
    n = normalize(text)
    for entry in config.KEYWORDS:
        for w in entry["words"]:
            if normalize(w) in n:
                return entry
    return None


def main_menu() -> InlineKeyboardMarkup:
    rows = []
    kws = config.KEYWORDS
    for i in range(0, len(kws), 2):
        rows.append(
            [InlineKeyboardButton(k["title"], callback_data=f"kw:{k['id']}") for k in kws[i : i + 2]]
        )
    rows.append([InlineKeyboardButton("📋 برنامه تمرینی و غذایی اختصاصی", callback_data="plan")])
    rows.append([InlineKeyboardButton("📸 تحلیل عکس بدن", callback_data="photo")])
    rows.append([InlineKeyboardButton("🌐 وب‌سایت باشگاه", url=config.LINKS["site"])])
    return InlineKeyboardMarkup(rows)


def back_button(extra=None) -> InlineKeyboardMarkup:
    rows = []
    if extra:
        rows.append([InlineKeyboardButton(extra[0], url=extra[1])])
    rows.append([InlineKeyboardButton("🔙 منوی اصلی", callback_data="menu")])
    return InlineKeyboardMarkup(rows)


async def send_long(message, text: str, reply_markup=None):
    chunks = [text[i : i + 3800] for i in range(0, len(text), 3800)] or ["..."]
    for i, c in enumerate(chunks):
        await message.reply_text(c, reply_markup=reply_markup if i == len(chunks) - 1 else None)


async def ask_ai(contents, system: str = SYSTEM_PROMPT) -> str:
    try:
        resp = await client.aio.models.generate_content(
            model=MODEL,
            contents=contents,
            config=types.GenerateContentConfig(system_instruction=system),
        )
        return (resp.text or "").strip() or "متأسفانه جوابی دریافت نشد. دوباره تلاش کنید."
    except Exception as e:  # noqa
        log.exception("Gemini error: %s", e)
        return "⚠️ در حال حاضر مشکلی در ارتباط با هوش مصنوعی پیش آمده. چند دقیقه دیگر دوباره تلاش کنید."


def rate_limited(user_id: int) -> bool:
    now = time.time()
    if now - _last_msg.get(user_id, 0) < COOLDOWN:
        return True
    _last_msg[user_id] = now
    return False


# ----------------------------- دستورها -----------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        f"سلام {update.effective_user.first_name or ''} 👋\n"
        f"به ربات {G['name']} خوش اومدی 💪\n\n"
        "از منو یکی را انتخاب کن، یا هر سؤالی داری همین‌جا بنویس تا مربی هوشمند جواب بدهد.",
        reply_markup=main_menu(),
    )


async def menu_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("منوی اصلی 👇", reply_markup=main_menu())


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "راهنما:\n"
        "• سؤالت را بنویس (مثلاً «قیمت اشتراک چنده؟»)\n"
        "• /plan برای برنامه تمرینی و غذایی\n"
        "• /photo برای تحلیل عکس بدن\n"
        "• /menu منوی اصلی\n"
        "• /cancel لغو",
    )


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("step", None)
    await update.message.reply_text("لغو شد.", reply_markup=main_menu())


# ----------------------------- برنامه اختصاصی -----------------------------
def goal_kb():
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(v, callback_data=f"goal:{k}")] for k, v in GOALS.items()]
    )


def level_kb():
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(v, callback_data=f"level:{k}") for k, v in LEVELS.items()]]
    )


def days_kb():
    return InlineKeyboardMarkup([[InlineKeyboardButton(d, callback_data=f"days:{d}") for d in DAYS]])


async def start_plan(message, context):
    context.user_data["profile"] = {}
    context.user_data["step"] = "goal"
    await message.reply_text("هدفت چیست؟ 🎯", reply_markup=goal_kb())


async def plan_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start_plan(update.message, context)


async def photo_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["step"] = "photo"
    await update.message.reply_text(
        "📸 یک عکس از بدنت بفرست (ترجیحاً از روبرو، با نور خوب). می‌توانی زیر عکس هدفت را هم بنویسی.\n\n"
        "⚠️ این تحلیل فقط یک نظر کلی ورزشی است و تشخیص پزشکی نیست. عکس‌ها ذخیره نمی‌شوند "
        "و فقط برای همین تحلیل به سرویس هوش مصنوعی ارسال می‌شوند."
    )


async def generate_plan(message, context):
    p = context.user_data.get("profile", {})
    context.user_data["step"] = None
    await message.chat.send_action(ChatAction.TYPING)
    prompt = f"""
برای این مشتری یک برنامه کامل بساز:
هدف: {p.get('goal')}
سطح: {p.get('level')}
تعداد روز تمرین در هفته: {p.get('days')}
قد، وزن، سن و مصدومیت‌ها (به نقل از خود کاربر): {p.get('body')}

خروجی را در این بخش‌ها بده:
۱) برنامه تمرینی هفتگی (هر روز: نام عضلات، حرکات، تعداد ست و تکرار، زمان استراحت)
۲) برنامه غذایی نمونه یک روز (وعده‌ها با مقدار تقریبی، محدوده کالری و پروتئین روزانه)
۳) ۴ نکته مهم (آب، خواب، پیشرفت تدریجی، ...)
۴) اگر مصدومیتی گفته شده، حرکات جایگزین و توصیه مراجعه به پزشک
در پایان یک جمله بگو این برنامه عمومی است و برای برنامه دقیق‌تر می‌تواند با مربی باشگاه صحبت کند.
بدون علامت مارک‌داون (** و #)، با ایموجی و شماره‌گذاری ساده.
"""
    text = await ask_ai(prompt)
    await send_long(
        message, text, reply_markup=back_button(("🏋️ رزرو مربی در سایت", config.LINKS["register"]))
    )


# ----------------------------- دکمه‌ها -----------------------------
async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    msg = q.message

    if data == "menu":
        await msg.reply_text("منوی اصلی 👇", reply_markup=main_menu())
    elif data.startswith("kw:"):
        kid = data[3:]
        entry = next((k for k in config.KEYWORDS if k["id"] == kid), None)
        if entry:
            await msg.reply_text(entry["text"], reply_markup=back_button(entry["button"]))
    elif data == "plan":
        await start_plan(msg, context)
    elif data == "photo":
        context.user_data["step"] = "photo"
        await msg.reply_text(
            "📸 یک عکس از بدنت بفرست. می‌توانی زیر عکس هدفت را هم بنویسی.\n\n"
            "⚠️ این تحلیل تشخیص پزشکی نیست. عکس‌ها ذخیره نمی‌شوند."
        )
    elif data.startswith("goal:"):
        context.user_data.setdefault("profile", {})["goal"] = GOALS[data[5:]]
        context.user_data["step"] = "level"
        await msg.reply_text("سطح تمرینی‌ات؟ 💪", reply_markup=level_kb())
    elif data.startswith("level:"):
        context.user_data.setdefault("profile", {})["level"] = LEVELS[data[6:]]
        context.user_data["step"] = "days"
        await msg.reply_text("چند روز در هفته می‌توانی تمرین کنی؟ 📅", reply_markup=days_kb())
    elif data.startswith("days:"):
        context.user_data.setdefault("profile", {})["days"] = data[5:]
        context.user_data["step"] = "body"
        await msg.reply_text(
            "آخرین مرحله ✍️\n"
            "قد، وزن، سن و هر مصدومیت یا بیماری‌ای که داری را در یک پیام بنویس.\n"
            "مثال: قد ۱۷۵، وزن ۸۰، سن ۲۸، درد زانوی راست"
        )


# ----------------------------- پیام متنی -----------------------------
async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text or ""

    if rate_limited(user.id):
        return

    step = context.user_data.get("step")

    if step == "body":
        context.user_data.setdefault("profile", {})["body"] = text[:500]
        await generate_plan(update.message, context)
        return
    if step in ("goal", "level", "days"):
        await update.message.reply_text("لطفاً یکی از دکمه‌های بالا را انتخاب کن 👆 یا /cancel")
        return
    if step == "photo":
        await update.message.reply_text("منتظر عکس هستم 📸 (یا /cancel)")
        return

    # ۱) کلمه کلیدی
    entry = find_keyword(text)
    if entry:
        await update.message.reply_text(entry["text"], reply_markup=back_button(entry["button"]))
        return

    # ۲) هوش مصنوعی
    await update.message.chat.send_action(ChatAction.TYPING)
    hist = context.user_data.setdefault("history", [])
    hist.append(("user", text))
    contents = [
        types.Content(role=r, parts=[types.Part(text=t)]) for r, t in hist[-10:]
    ]
    answer = await ask_ai(contents)
    hist.append(("model", answer))
    context.user_data["history"] = hist[-10:]
    await send_long(update.message, answer, reply_markup=back_button())


# ----------------------------- عکس -----------------------------
async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if rate_limited(user.id):
        return
    await update.message.chat.send_action(ChatAction.TYPING)

    photo = update.message.photo[-1]
    tg_file = await photo.get_file()
    data = bytes(await tg_file.download_as_bytearray())
    caption = update.message.caption or "بدون توضیح"
    profile = context.user_data.get("profile", {})

    prompt = f"""
این عکس بدن یک مشتری باشگاه است. توضیح خود کاربر: {caption}
اطلاعات قبلی (اگر هست): {profile}

لطفاً:
۱) نقاط قوت ظاهری (مثلاً تقارن، عضله‌های رشدکرده) را محترمانه بگو.
۲) نقاط قابل پیشرفت را بگو.
۳) برای هر کدام ۲ تا ۳ حرکت پیشنهادی بده.
۴) یک توصیه تغذیه‌ای کلی بده.
قوانین: درصد چربی یا وزن دقیق حدس نزن، توهین یا مقایسه‌ی منفی نکن، تشخیص پزشکی نده.
اگر عکس بدن نیست یا فرد زیر ۱۸ سال به نظر می‌رسد، فقط توصیه‌ی عمومی و سالم بده و رژیم کاهش وزن نده.
در پایان بگو این فقط نظر کلی ورزشی است و برای بررسی دقیق‌تر به مربی باشگاه مراجعه کند.
بدون علامت مارک‌داون، با ایموجی.
"""
    contents = [types.Part.from_bytes(data=data, mime_type="image/jpeg"), prompt]
    text = await ask_ai(contents)
    context.user_data["step"] = None
    await send_long(
        update.message,
        text,
        reply_markup=InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("📋 ساخت برنامه تمرینی", callback_data="plan")],
                [InlineKeyboardButton("🔙 منوی اصلی", callback_data="menu")],
            ]
        ),
    )


async def on_error(update, context: ContextTypes.DEFAULT_TYPE):
    log.error("Update error", exc_info=context.error)


def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("plan", plan_cmd))
    app.add_handler(CommandHandler("photo", photo_cmd))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.PHOTO, on_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_error_handler(on_error)
    log.info("Bot started (model=%s)", MODEL)
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
