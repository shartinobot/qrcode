#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
import logging
import qrcode
from datetime import date
from threading import Thread
from flask import Flask, jsonify
from PIL import Image, ImageDraw
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

# ======================== تنظیمات ========================
TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "YourAdminUsername")
PORT = int(os.environ.get("PORT", 10000))
DATA_FILE = "user_data.json"
FREE_DAILY_LIMIT = int(os.environ.get("FREE_DAILY_LIMIT", 3))
PREMIUM_DAILY_LIMIT = int(os.environ.get("PREMIUM_DAILY_LIMIT", 10))
REFERRAL_BONUS = int(os.environ.get("REFERRAL_BONUS", 2))
PRICE_FA = os.environ.get("PRICE_FA", "۲۰۰,۰۰۰")

# ======================== متون فارسی ========================
TEXTS = {
    "welcome": "👋 به ربات کیوآر کد سفارشی خوش آمدید!\n\n📊 سهمیه باقی‌مانده امروز: {}\n🔥 هر روز {} سهمیه رایگان\n👥 با دعوت دوستان، {} سهمیه اضافه بگیر!\n\nبرای شروع، دکمه 'ساخت کیوآر کد جدید' را بزنید.",
    "no_credit": "❌ سهمیه روزانه شما تمام شده!\n\n💡 راه‌های دریافت سهمیه بیشتر:\n🔗 با لینک دعوت دوستان خود را دعوت کنید (هر دعوت {} سهمیه)\n💳 یا اشتراک دائمی تهیه کنید.\n\n📞 برای خرید اشتراک، دکمه زیر را بزنید.",
    "subscription": "💳 خرید اشتراک دائمی\n\n💰 قیمت اشتراک دائمی:\n• {} تومان (یک بار پرداخت، مادام‌العمر)\n\n✅ پس از خرید، شما روزانه {} سهمیه خواهید داشت.\n✅ بدون تاریخ انقضا - برای همیشه فعال\n\n💎 روش پرداخت (فقط رمز ارز):\n• USDT (TRC20)\n• TON\n\n📞 برای خرید، به ادمین پیام دهید:\n👤 @{}\n\nپس از پرداخت، ادمین اشتراک دائمی شما را فعال میکند.",
    "already_sub": "✅ شما قبلاً اشتراک دائمی دارید!\n\n📊 سهمیه روزانه شما: {} عدد",
    "sub_active": "🎉 اشتراک دائمی شما فعال شد!\n\n📊 از این به بعد روزانه {} سهمیه خواهید داشت.",
    "sub_removed": "❌ اشتراک شما لغو شد.",
    "enter_text": "📝 لطفاً متنی که می‌خواهید کیوآر کد شود را ارسال کنید:\n(سهمیه باقی‌مانده: {} عدد)",
    "text_saved": "✅ متن ذخیره شد!",
    "go_to_settings": "حالا برای شخصی‌سازی ظاهر کیوآر کد، دکمه زیر را بزنید:",
    "settings": "🎨 تنظیمات کیوآر کد:\n\n📝 متن: {}\n🎨 رنگ: {}\n⬜ پس‌زمینه: {}\n⭕ گردی گوشه: {} پیکسل\n📐 سایز: {}\n📊 سهمیه باقی‌مانده: {}\n\n👇 تنظیمات مورد نظر را انتخاب کنید:",
    "generating": "⏳ در حال ساخت کیوآر کد...",
    "qr_done": "✅ کیوآر کد ساخته شد!\n📊 سهمیه باقی‌مانده: {}",
    "status": "📊 وضعیت سهمیه شما:\n\n✅ سهمیه روزانه: {} عدد\n📌 استفاده شده امروز: {} عدد\n🎁 سهمیه اضافی (از دعوت): {} عدد\n📊 باقی‌مانده: {} عدد\n\n👥 دوستان دعوت شده: {} نفر",
    "referral": "🔗 لینک دعوت اختصاصی شما:\n\n`{}`\n\n📋 این لینک را برای دوستان خود بفرستید.\n🎁 با هر دعوت، {} سهمیه اضافی دریافت می‌کنید!\n\n📊 دوستان دعوت شده: {} نفر",
    "help": "📖 راهنمای ربات:\n\n1️⃣ هر روز {} سهمیه رایگان برای ساخت کیوآر کد دارید.\n2️⃣ با دعوت دوستان، سهمیه بیشتری دریافت کنید.\n3️⃣ می‌توانید رنگ، اندازه و گردی گوشه را تنظیم کنید.\n4️⃣ بعد از تمام شدن سهمیه، میتوانید اشتراک دائمی تهیه کنید.\n\n🔗 لینک دعوت: با دکمه مربوطه دریافت کنید.",
    "buttons": {
        "new_qr": "🎨 ساخت کیوآر کد جدید",
        "status": "📊 وضعیت سهمیه",
        "referral": "🔗 لینک دعوت",
        "help": "📖 راهنما",
        "buy": "💳 خرید اشتراک دائمی",
        "settings": "🎨 رفتن به تنظیمات",
        "generate": "✅ ساخت نهایی",
        "reset": "🔄 ریست تنظیمات"
    }
}

# ======================== مدیریت دیتابیس ========================
def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_data(data):
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def get_user(user_id):
    data = load_data()
    uid = str(user_id)
    if uid not in data:
        data[uid] = {
            "daily_count": 0,
            "last_date": str(date.today()),
            "extra_credits": 0,
            "invited_by": None,
            "invited_users": [],
            "subscription": {"active": False}
        }
        save_data(data)
    return data[uid]

def update_user(user_id, updates):
    data = load_data()
    uid = str(user_id)
    if uid not in data:
        data[uid] = {
            "daily_count": 0,
            "last_date": str(date.today()),
            "extra_credits": 0,
            "invited_by": None,
            "invited_users": [],
            "subscription": {"active": False}
        }
    data[uid].update(updates)
    save_data(data)

def get_daily_limit(user_id):
    user = get_user(user_id)
    if user.get("subscription", {}).get("active", False):
        return PREMIUM_DAILY_LIMIT
    return FREE_DAILY_LIMIT

def get_remaining(user_id):
    user = get_user(user_id)
    today = str(date.today())
    
    if user["last_date"] != today:
        user["daily_count"] = 0
        user["last_date"] = today
        update_user(user_id, {"daily_count": 0, "last_date": today})
    
    limit = get_daily_limit(user_id)
    remaining = limit - user["daily_count"] + user.get("extra_credits", 0)
    return max(0, remaining)

def use_credit(user_id):
    user = get_user(user_id)
    today = str(date.today())
    
    if user["last_date"] != today:
        user["daily_count"] = 0
        user["last_date"] = today
    
    if get_remaining(user_id) <= 0:
        return False
    
    if user.get("extra_credits", 0) > 0:
        user["extra_credits"] -= 1
    else:
        user["daily_count"] += 1
    
    update_user(user_id, {
        "daily_count": user["daily_count"],
        "last_date": user["last_date"],
        "extra_credits": user.get("extra_credits", 0)
    })
    return True

def add_referral(referrer_id, new_user_id):
    referrer = get_user(referrer_id)
    new_user = get_user(new_user_id)
    
    if new_user.get("invited_by") is None:
        referrer["extra_credits"] = referrer.get("extra_credits", 0) + REFERRAL_BONUS
        if "invited_users" not in referrer:
            referrer["invited_users"] = []
        referrer["invited_users"].append(new_user_id)
        new_user["invited_by"] = referrer_id
        
        update_user(referrer_id, {
            "extra_credits": referrer["extra_credits"],
            "invited_users": referrer["invited_users"]
        })
        update_user(new_user_id, {"invited_by": referrer_id})
        return True
    return False

# ======================== وب‌سرور ========================
flask_app = Flask(__name__)

@flask_app.route("/")
def home():
    return jsonify({"status": "running", "bot": "QR Bot"})

@flask_app.route("/health")
def health():
    return jsonify({"status": "ok"})

def run_web_server():
    flask_app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False)

# ======================== توابع کمکی ========================
def round_corners(image, radius):
    mask = Image.new('L', image.size, 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle([(0, 0), image.size], radius=radius, fill=255)
    result = Image.new('RGBA', image.size, (0, 0, 0, 0))
    result.putalpha(mask)
    result.paste(image, (0, 0), mask)
    return result

COLORS = {
    '⚫ مشکی': 'black', '🔴 قرمز': 'red', '🔵 آبی': 'blue',
    '🟢 سبز': 'green', '🟡 زرد': 'gold', '🟣 بنفش': 'purple',
    '🟠 نارنجی': 'orange', '🩷 صورتی': 'pink'
}

BACKGROUNDS = {
    '⚪ سفید': 'white', '🟡 کرم': 'ivory', '🔵 آبی روشن': 'lightblue',
    '🟢 سبز روشن': 'lightgreen', '🩷 صورتی روشن': 'lightpink',
    '🟣 بنفش روشن': 'lavender', '⬛ خاکستری': 'lightgray'
}

user_settings = {}

# ======================== دستورات ربات ========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    
    # پردازش لینک دعوت
    args = context.args
    if args and args[0].startswith('ref_'):
        try:
            referrer_id = int(args[0].replace('ref_', ''))
            if referrer_id != user_id:
                if add_referral(referrer_id, user_id):
                    await update.message.reply_text("🎉 شما توسط یک دوست دعوت شدید!")
                    try:
                        await context.bot.send_message(
                            referrer_id,
                            f"🎉 کاربر جدید با لینک دعوت شما وارد شد!\n{REFERRAL_BONUS} سهمیه اضافی به حساب شما اضافه شد."
                        )
                    except:
                        pass
        except:
            pass
    
    # نمایش منوی اصلی
    remaining = get_remaining(user_id)
    btns = TEXTS["buttons"]
    
    keyboard = [
        [InlineKeyboardButton(btns["new_qr"], callback_data='new_qr')],
        [InlineKeyboardButton(btns["status"], callback_data='status')],
        [InlineKeyboardButton(btns["referral"], callback_data='referral')],
        [InlineKeyboardButton(btns["help"], callback_data='help')]
    ]
    
    if not get_user(user_id).get("subscription", {}).get("active", False):
        keyboard.append([InlineKeyboardButton(btns["buy"], callback_data='buy')])
    
    await update.message.reply_text(
        TEXTS["welcome"].format(remaining, FREE_DAILY_LIMIT, REFERRAL_BONUS),
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    btns = TEXTS["buttons"]
    
    # ساخت کیوآر کد جدید
    if query.data == 'new_qr':
        remaining = get_remaining(user_id)
        if remaining <= 0:
            keyboard = [[InlineKeyboardButton(btns["buy"], callback_data='buy')]]
            await query.edit_message_text(
                TEXTS["no_credit"].format(REFERRAL_BONUS),
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return
        
        user_settings[user_id] = {
            'text': None,
            'color': 'black',
            'bg_color': 'white',
            'corner_radius': 0,
            'size': 10
        }
        await query.edit_message_text(TEXTS["enter_text"].format(remaining))
        return
    
    # خرید اشتراک
    if query.data == 'buy':
        if get_user(user_id).get("subscription", {}).get("active", False):
            await query.edit_message_text(TEXTS["already_sub"].format(get_daily_limit(user_id)))
            return
        
        await query.edit_message_text(
            TEXTS["subscription"].format(PRICE_FA, PREMIUM_DAILY_LIMIT, ADMIN_USERNAME)
        )
        return
    
    # وضعیت سهمیه
    if query.data == 'status':
        user = get_user(user_id)
        remaining = get_remaining(user_id)
        limit = get_daily_limit(user_id)
        await query.edit_message_text(
            TEXTS["status"].format(
                limit, user["daily_count"], 
                user.get("extra_credits", 0), remaining, 
                len(user.get("invited_users", []))
            )
        )
        return
    
    # لینک دعوت
    if query.data == 'referral':
        bot_username = (await context.bot.get_me()).username
        link = f"https://t.me/{bot_username}?start=ref_{user_id}"
        user = get_user(user_id)
        await query.edit_message_text(
            TEXTS["referral"].format(link, REFERRAL_BONUS, len(user.get("invited_users", []))),
            parse_mode='Markdown'
        )
        return
    
    # راهنما
    if query.data == 'help':
        await query.edit_message_text(TEXTS["help"].format(FREE_DAILY_LIMIT))
        return
    
    # تنظیمات رنگ
    if query.data.startswith('color_'):
        color = query.data.replace('color_', '')
        if user_id in user_settings:
            user_settings[user_id]['color'] = color
        await show_settings(query)
        return
    
    if query.data.startswith('bg_'):
        bg = query.data.replace('bg_', '')
        if user_id in user_settings:
            user_settings[user_id]['bg_color'] = bg
        await show_settings(query)
        return
    
    if query.data.startswith('corner_'):
        radius = int(query.data.replace('corner_', ''))
        if user_id in user_settings:
            user_settings[user_id]['corner_radius'] = radius
        await show_settings(query)
        return
    
    if query.data.startswith('size_'):
        size = int(query.data.replace('size_', ''))
        if user_id in user_settings:
            user_settings[user_id]['size'] = size
        await show_settings(query)
        return
    
    if query.data == 'generate':
        await generate_qr(query, context)
        return
    
    if query.data == 'reset':
        if user_id in user_settings:
            user_settings[user_id] = {
                'text': user_settings[user_id].get('text'),
                'color': 'black',
                'bg_color': 'white',
                'corner_radius': 0,
                'size': 10
            }
        await show_settings(query)
        return

async def show_settings(query):
    user_id = query.from_user.id
    settings = user_settings.get(user_id)
    
    if not settings:
        await query.edit_message_text("❌ خطا! لطفاً دوباره تلاش کنید.")
        return
    
    btns = TEXTS["buttons"]
    remaining = get_remaining(user_id)
    
    # دکمه‌های رنگ
    color_buttons = []
    row = []
    for name, code in COLORS.items():
        row.append(InlineKeyboardButton(
            f"{'✅ ' if settings['color'] == code else ''}{name}", 
            callback_data=f'color_{code}'
        ))
        if len(row) == 2:
            color_buttons.append(row)
            row = []
    if row:
        color_buttons.append(row)
    
    # دکمه‌های پس‌زمینه
    bg_buttons = []
    row = []
    for name, code in BACKGROUNDS.items():
        row.append(InlineKeyboardButton(
            f"{'✅ ' if settings['bg_color'] == code else ''}{name}", 
            callback_data=f'bg_{code}'
        ))
        if len(row) == 2:
            bg_buttons.append(row)
            row = []
    if row:
        bg_buttons.append(row)
    
    # دکمه‌های گردی گوشه
    corner_buttons = [
        [
            InlineKeyboardButton(f"{'✅' if settings['corner_radius']==0 else ''} 🔲 بدون گردی", callback_data='corner_0'),
            InlineKeyboardButton(f"{'✅' if settings['corner_radius']==20 else ''} 🔘 گردی کم", callback_data='corner_20')
        ],
        [
            InlineKeyboardButton(f"{'✅' if settings['corner_radius']==40 else ''} ⭕ گردی متوسط", callback_data='corner_40'),
            InlineKeyboardButton(f"{'✅' if settings['corner_radius']==60 else ''} 🟣 گردی زیاد", callback_data='corner_60')
        ]
    ]
    
    # دکمه‌های سایز
    size_buttons = [
        [
            InlineKeyboardButton(f"{'✅' if settings['size']==5 else ''} 📐 کوچک", callback_data='size_5'),
            InlineKeyboardButton(f"{'✅' if settings['size']==10 else ''} 📐 متوسط", callback_data='size_10')
        ],
        [
            InlineKeyboardButton(f"{'✅' if settings['size']==15 else ''} 📐 بزرگ", callback_data='size_15')
        ]
    ]
    
    # دکمه‌های اصلی
    action_buttons = [
        [
            InlineKeyboardButton(btns["generate"], callback_data='generate'),
            InlineKeyboardButton(btns["reset"], callback_data='reset')
        ]
    ]
    
    keyboard = color_buttons + bg_buttons + corner_buttons + size_buttons + action_buttons
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        TEXTS["settings"].format(
            settings['text'] or '❌ ارسال نشده', 
            settings['color'], 
            settings['bg_color'], 
            settings['corner_radius'], 
            settings['size'], 
            remaining
        ),
        reply_markup=reply_markup
    )

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    
    if user_id not in user_settings:
        await update.message.reply_text("❌ لطفاً اول دکمه 'ساخت کیوآر کد جدید' را بزنید.")
        return
    
    user_settings[user_id]['text'] = update.message.text
    await update.message.reply_text(TEXTS["text_saved"])
    
    keyboard = [[InlineKeyboardButton(TEXTS["buttons"]["settings"], callback_data='new_qr')]]
    await update.message.reply_text(
        TEXTS["go_to_settings"],
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def generate_qr(query, context):
    user_id = query.from_user.id
    settings = user_settings.get(user_id)
    
    if not settings or not settings['text']:
        await query.edit_message_text("❌ ابتدا یک متن ارسال کنید!")
        return
    
    if not use_credit(user_id):
        await query.edit_message_text(TEXTS["no_credit"].format(REFERRAL_BONUS))
        return
    
    try:
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=settings['size'],
            border=2
        )
        qr.add_data(settings['text'])
        qr.make(fit=True)
        
        img = qr.make_image(
            fill_color=settings['color'], 
            back_color=settings['bg_color']
        ).convert('RGBA')
        
        if settings['corner_radius'] > 0:
            img = round_corners(img, settings['corner_radius'])
        
        path = f"qr_{user_id}.png"
        img.save(path)
        
        remaining = get_remaining(user_id)
        await query.edit_message_text(TEXTS["generating"])
        await query.message.reply_photo(
            photo=open(path, "rb"),
            caption=TEXTS["qr_done"].format(remaining)
        )
        os.remove(path)
        
    except Exception as e:
        await query.edit_message_text(f"❌ خطا در ساخت: {str(e)}")

# ======================== دستورات ادمین ========================
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    
    if user_id != ADMIN_ID:
        await update.message.reply_text("⛔ دسترسی محدود!")
        return
    
    data = load_data()
    total_users = len(data)
    subscribed = sum(1 for u in data.values() if u.get("subscription", {}).get("active", False))
    
    keyboard = [
        [InlineKeyboardButton("📊 آمار کلی", callback_data='admin_stats')],
        [InlineKeyboardButton("👥 لیست کاربران", callback_data='admin_users')],
        [InlineKeyboardButton("➕ فعال‌سازی اشتراک", callback_data='admin_activate')],
        [InlineKeyboardButton("➖ لغو اشتراک", callback_data='admin_remove')]
    ]
    
    await update.message.reply_text(
        f"👑 پنل ادمین\n\n"
        f"📊 کل کاربران: {total_users}\n"
        f"✅ اشتراک فعال: {subscribed}\n"
        f"📌 کاربران رایگان: {total_users - subscribed}",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def admin_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    if user_id != ADMIN_ID:
        await query.edit_message_text("⛔ دسترسی محدود!")
        return
    
    if query.data == 'admin_stats':
        data = load_data()
        total = len(data)
        sub = sum(1 for u in data.values() if u.get("subscription", {}).get("active", False))
        today = str(date.today())
        active_today = sum(1 for u in data.values() if u.get("last_date") == today)
        
        await query.edit_message_text(
            f"📊 آمار کلی:\n\n"
            f"👥 کل کاربران: {total}\n"
            f"✅ اشتراک فعال: {sub}\n"
            f"📌 کاربران رایگان: {total - sub}\n"
            f"🔥 کاربران فعال امروز: {active_today}"
        )
        return
    
    elif query.data == 'admin_users':
        data = load_data()
        users = list(data.keys())[:10]
        text = "👥 لیست ۱۰ کاربر اول:\n\n"
        for uid in users:
            user = data[uid]
            sub = "✅" if user.get("subscription", {}).get("active", False) else "❌"
            text += f"🆔 {uid} {sub}\n"
        text += f"\n📌 کل کاربران: {len(data)} نفر"
        await query.edit_message_text(text)
        return
    
    elif query.data == 'admin_activate':
        await query.edit_message_text(
            "🆔 آی‌دی عددی کاربر را ارسال کنید:\n\n"
            "مثال: `/activate 123456789`"
        )
        return
    
    elif query.data == 'admin_remove':
        await query.edit_message_text(
            "🆔 آی‌دی عددی کاربر را ارسال کنید:\n\n"
            "مثال: `/remove 123456789`"
        )
        return

async def activate_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    
    if user_id != ADMIN_ID:
        await update.message.reply_text("⛔ دسترسی محدود!")
        return
    
    try:
        target_id = int(context.args[0])
        user = get_user(target_id)
        user["subscription"] = {"active": True}
        update_user(target_id, {"subscription": {"active": True}})
        
        await update.message.reply_text(f"✅ اشتراک دائمی کاربر {target_id} فعال شد!")
        
        # ارسال پیام به کاربر
        try:
            await context.bot.send_message(
                target_id,
                TEXTS["sub_active"].format(PREMIUM_DAILY_LIMIT)
            )
        except:
            pass
            
    except (IndexError, ValueError):
        await update.message.reply_text("❌ دستور صحیح: /activate USER_ID")

async def remove_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    
    if user_id != ADMIN_ID:
        await update.message.reply_text("⛔ دسترسی محدود!")
        return
    
    try:
        target_id = int(context.args[0])
        user = get_user(target_id)
        user["subscription"] = {"active": False}
        update_user(target_id, {"subscription": {"active": False}})
        
        await update.message.reply_text(f"❌ اشتراک کاربر {target_id} لغو شد!")
        
        try:
            await context.bot.send_message(
                target_id,
                TEXTS["sub_removed"]
            )
        except:
            pass
            
    except (IndexError, ValueError):
        await update.message.reply_text("❌ دستور صحیح: /remove USER_ID")

# ======================== اصلی ========================
def main():
    logging.basicConfig(level=logging.INFO)
    
    # اجرای وب‌سرور در ترد جداگانه
    web_thread = Thread(target=run_web_server, daemon=True)
    web_thread.start()
    print(f"✅ وب‌سرور Flask روی پورت {PORT} روشن شد")
    
    # اجرای ربات
    app = Application.builder().token(TOKEN).build()
    
    # دستورات عمومی
    app.add_handler(CommandHandler("start", start))
    
    # دستورات ادمین
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CommandHandler("activate", activate_user))
    app.add_handler(CommandHandler("remove", remove_user))
    
    # هندلرها
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(CallbackQueryHandler(admin_button, pattern="^admin_"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    print("🤖 ربات روشن شد...")
    app.run_polling()

if __name__ == "__main__":
    main()
