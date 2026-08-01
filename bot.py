#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
import logging
import qrcode
from datetime import date
from threading import Thread
from flask import Flask, jsonify
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

# ======================== دکمه‌های اصلی ========================
def get_main_keyboard(has_subscription=False):
    keyboard = [
        [InlineKeyboardButton("🎨 ساخت کیوآر کد جدید", callback_data='new_qr')],
        [InlineKeyboardButton("📊 وضعیت سهمیه", callback_data='status')],
        [InlineKeyboardButton("🔗 لینک دعوت", callback_data='referral')],
        [InlineKeyboardButton("📖 راهنما", callback_data='help')]
    ]
    if not has_subscription:
        keyboard.append([InlineKeyboardButton("💳 خرید اشتراک دائمی", callback_data='buy')])
    return InlineKeyboardMarkup(keyboard)

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
            "subscription": {"active": False},
            "waiting_for_text": False
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
            "subscription": {"active": False},
            "waiting_for_text": False
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
    
    remaining = get_remaining(user_id)
    has_sub = get_user(user_id).get("subscription", {}).get("active", False)
    
    await update.message.reply_text(
        f"👋 به ربات کیوآر کد خوش آمدید!\n\n"
        f"📊 سهمیه باقی‌مانده امروز: {remaining}\n"
        f"🔥 هر روز {FREE_DAILY_LIMIT} سهمیه رایگان\n"
        f"👥 با دعوت دوستان، {REFERRAL_BONUS} سهمیه اضافه بگیر!\n\n"
        f"برای شروع، دکمه 'ساخت کیوآر کد جدید' را بزنید.",
        reply_markup=get_main_keyboard(has_sub)
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    has_sub = get_user(user_id).get("subscription", {}).get("active", False)
    
    # ==================== بازگشت به منوی اصلی ====================
    if query.data == 'main_menu':
        remaining = get_remaining(user_id)
        update_user(user_id, {"waiting_for_text": False})
        await query.edit_message_text(
            f"👋 به ربات کیوآر کد خوش آمدید!\n\n"
            f"📊 سهمیه باقی‌مانده امروز: {remaining}\n"
            f"🔥 هر روز {FREE_DAILY_LIMIT} سهمیه رایگان\n"
            f"👥 با دعوت دوستان، {REFERRAL_BONUS} سهمیه اضافه بگیر!\n\n"
            f"برای شروع، دکمه 'ساخت کیوآر کد جدید' را بزنید.",
            reply_markup=get_main_keyboard(has_sub)
        )
        return
    
    # ==================== ساخت کیوآر کد ====================
    if query.data == 'new_qr':
        remaining = get_remaining(user_id)
        if remaining <= 0:
            keyboard = [
                [InlineKeyboardButton("💳 خرید اشتراک", callback_data='buy')],
                [InlineKeyboardButton("🔙 بازگشت", callback_data='main_menu')]
            ]
            await query.edit_message_text(
                f"❌ سهمیه روزانه شما تمام شده!\n\n"
                f"💡 راه‌های دریافت سهمیه بیشتر:\n"
                f"🔗 با لینک دعوت دوستان خود را دعوت کنید (هر دعوت {REFERRAL_BONUS} سهمیه)\n"
                f"💳 یا اشتراک دائمی تهیه کنید.",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return
        
        # فعال کردن حالت انتظار برای متن
        update_user(user_id, {"waiting_for_text": True})
        
        keyboard = [[InlineKeyboardButton("🔙 انصراف", callback_data='main_menu')]]
        await query.edit_message_text(
            f"📝 لطفاً متنی که می‌خواهید کیوآر کد شود را ارسال کنید:\n"
            f"(سهمیه باقی‌مانده: {remaining} عدد)",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
    
    # ==================== خرید اشتراک ====================
    if query.data == 'buy':
        if has_sub:
            await query.edit_message_text(
                f"✅ شما قبلاً اشتراک دائمی دارید!\n\n📊 سهمیه روزانه شما: {get_daily_limit(user_id)} عدد",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data='main_menu')]])
            )
            return
        
        await query.edit_message_text(
            f"💳 خرید اشتراک دائمی\n\n"
            f"💰 قیمت: {PRICE_FA} تومان (یک بار پرداخت، مادام‌العمر)\n\n"
            f"✅ پس از خرید، روزانه {PREMIUM_DAILY_LIMIT} سهمیه خواهید داشت.\n"
            f"✅ بدون تاریخ انقضا - برای همیشه فعال\n\n"
            f"📞 برای خرید، به ادمین پیام دهید:\n"
            f"👤 @{ADMIN_USERNAME}\n\n"
            f"پس از پرداخت، ادمین اشتراک شما را فعال میکند.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data='main_menu')]])
        )
        return
    
    # ==================== وضعیت سهمیه ====================
    if query.data == 'status':
        user = get_user(user_id)
        remaining = get_remaining(user_id)
        limit = get_daily_limit(user_id)
        await query.edit_message_text(
            f"📊 وضعیت سهمیه شما:\n\n"
            f"✅ سهمیه روزانه: {limit} عدد\n"
            f"📌 استفاده شده امروز: {user['daily_count']} عدد\n"
            f"🎁 سهمیه اضافی (از دعوت): {user.get('extra_credits', 0)} عدد\n"
            f"📊 باقی‌مانده: {remaining} عدد\n\n"
            f"👥 دوستان دعوت شده: {len(user.get('invited_users', []))} نفر",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data='main_menu')]])
        )
        return
    
    # ==================== لینک دعوت ====================
    if query.data == 'referral':
        bot_username = (await context.bot.get_me()).username
        link = f"https://t.me/{bot_username}?start=ref_{user_id}"
        user = get_user(user_id)
        await query.edit_message_text(
            f"🔗 لینک دعوت اختصاصی شما:\n\n"
            f"`{link}`\n\n"
            f"📋 این لینک را برای دوستان خود بفرستید.\n"
            f"🎁 با هر دعوت، {REFERRAL_BONUS} سهمیه اضافی دریافت می‌کنید!\n\n"
            f"📊 دوستان دعوت شده: {len(user.get('invited_users', []))} نفر",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data='main_menu')]])
        )
        return
    
    # ==================== راهنما ====================
    if query.data == 'help':
        await query.edit_message_text(
            f"📖 راهنمای ربات:\n\n"
            f"1️⃣ هر روز {FREE_DAILY_LIMIT} سهمیه رایگان برای ساخت کیوآر کد دارید.\n"
            f"2️⃣ با دعوت دوستان، سهمیه بیشتری دریافت کنید.\n"
            f"3️⃣ بعد از تمام شدن سهمیه، میتوانید اشتراک دائمی تهیه کنید.\n\n"
            f"🔗 لینک دعوت: با دکمه مربوطه دریافت کنید.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data='main_menu')]])
        )
        return

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    user = get_user(user_id)
    
    # اگر کاربر در حالت انتظار برای متن نباشه
    if not user.get("waiting_for_text", False):
        await update.message.reply_text(
            "❌ لطفاً اول دکمه 'ساخت کیوآر کد جدید' را بزنید.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data='main_menu')]])
        )
        return
    
    # دریافت متن
    text = update.message.text
    
    # بررسی سهمیه
    if not use_credit(user_id):
        update_user(user_id, {"waiting_for_text": False})
        await update.message.reply_text(
            f"❌ سهمیه شما تمام شده!\n\nبرای دریافت سهمیه بیشتر:\n🔗 دوستان خود را دعوت کنید (هر دعوت {REFERRAL_BONUS} سهمیه)\n💳 یا اشتراک تهیه کنید.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💳 خرید اشتراک", callback_data='buy')],
                [InlineKeyboardButton("🔙 بازگشت", callback_data='main_menu')]
            ])
        )
        return
    
    # ساخت کیوآر کد
    try:
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=2
        )
        qr.add_data(text)
        qr.make(fit=True)
        
        img = qr.make_image(fill_color="black", back_color="white")
        
        path = f"qr_{user_id}.png"
        img.save(path)
        
        remaining = get_remaining(user_id)
        
        # غیرفعال کردن حالت انتظار
        update_user(user_id, {"waiting_for_text": False})
        
        await update.message.reply_text("⏳ در حال ساخت کیوآر کد...")
        await update.message.reply_photo(
            photo=open(path, "rb"),
            caption=f"✅ کیوآر کد ساخته شد!\n📊 سهمیه باقی‌مانده: {remaining}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data='main_menu')]])
        )
        os.remove(path)
        
    except Exception as e:
        update_user(user_id, {"waiting_for_text": False})
        await update.message.reply_text(
            f"❌ خطا در ساخت: {str(e)}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data='main_menu')]])
        )

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
        [InlineKeyboardButton("➖ لغو اشتراک", callback_data='admin_remove')],
        [InlineKeyboardButton("🔙 بازگشت", callback_data='main_menu')]
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
            f"🔥 کاربران فعال امروز: {active_today}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data='admin_panel_back')]])
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
        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data='admin_panel_back')]])
        )
        return
    
    elif query.data == 'admin_activate':
        await query.edit_message_text(
            "🆔 آی‌دی عددی کاربر را ارسال کنید:\n\nمثال: `/activate 123456789`",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data='admin_panel_back')]])
        )
        return
    
    elif query.data == 'admin_remove':
        await query.edit_message_text(
            "🆔 آی‌دی عددی کاربر را ارسال کنید:\n\nمثال: `/remove 123456789`",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data='admin_panel_back')]])
        )
        return
    
    elif query.data == 'admin_panel_back':
        await admin_panel(update, context)
        return

async def activate_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    
    if user_id != ADMIN_ID:
        await update.message.reply_text("⛔ دسترسی محدود!")
        return
    
    try:
        target_id = int(context.args[0])
        update_user(target_id, {"subscription": {"active": True}})
        
        await update.message.reply_text(f"✅ اشتراک دائمی کاربر {target_id} فعال شد!")
        
        try:
            await context.bot.send_message(
                target_id,
                f"🎉 اشتراک دائمی شما فعال شد!\n\n📊 از این به بعد روزانه {PREMIUM_DAILY_LIMIT} سهمیه خواهید داشت."
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
        update_user(target_id, {"subscription": {"active": False}})
        
        await update.message.reply_text(f"❌ اشتراک کاربر {target_id} لغو شد!")
        
        try:
            await context.bot.send_message(
                target_id,
                "❌ اشتراک شما لغو شد."
            )
        except:
            pass
            
    except (IndexError, ValueError):
        await update.message.reply_text("❌ دستور صحیح: /remove USER_ID")

# ======================== اصلی ========================
def main():
    logging.basicConfig(level=logging.INFO)
    
    # وب‌سرور
    web_thread = Thread(target=run_web_server, daemon=True)
    web_thread.start()
    print(f"✅ وب‌سرور روی پورت {PORT} روشن شد")
    
    # ربات
    app = Application.builder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CommandHandler("activate", activate_user))
    app.add_handler(CommandHandler("remove", remove_user))
    
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(CallbackQueryHandler(admin_button, pattern="^admin_"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    print("🤖 ربات روشن شد...")
    app.run_polling()

if __name__ == "__main__":
    main()
