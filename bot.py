#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
import logging
import qrcode
import time
import signal
import sys
from datetime import date, datetime
from threading import Thread, Event
from flask import Flask, jsonify
from PIL import Image, ImageDraw
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from telegram.error import NetworkError, TimedOut, RetryAfter, TelegramError

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

# ======================== تنظیمات Logging ========================
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

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
    try:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        logger.error(f"خطا در خواندن دیتابیس: {e}")
        # بازیابی خودکار: دیتابیس خراب رو با یه دیتابیس خالی جایگزین کن
        backup_path = f"{DATA_FILE}.backup"
        if os.path.exists(backup_path):
            try:
                with open(backup_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                pass
    return {}

def save_data(data):
    try:
        # پشتیبان‌گیری قبل از ذخیره
        if os.path.exists(DATA_FILE):
            os.rename(DATA_FILE, f"{DATA_FILE}.backup")
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        # پاک کردن پشتیبان بعد از ذخیره موفق
        if os.path.exists(f"{DATA_FILE}.backup"):
            os.remove(f"{DATA_FILE}.backup")
    except Exception as e:
        logger.error(f"خطا در ذخیره دیتابیس: {e}")

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

# ======================== وب‌سرور Flask ========================
flask_app = Flask(__name__)

@flask_app.route("/")
def home():
    return jsonify({"status": "running", "bot": "QR Bot", "uptime": time.time() - start_time})

@flask_app.route("/health")
def health():
    return jsonify({"status": "ok", "uptime": time.time() - start_time})

def run_web_server():
    try:
        flask_app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False, threaded=True)
    except Exception as e:
        logger.error(f"خطا در وب‌سرور: {e}")

# ======================== توابع کمکی ========================
def round_corners(image, radius):
    mask = Image.new('L', image.size, 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle([(0, 0), image.size], radius=radius, fill=255)
    result = Image.new('RGBA', image.size, (0, 0, 0, 0))
    result.putalpha(mask)
    result.paste(image, (0, 0), mask)
    return result

def generate_qr_code(text, color='black', bg_color='white', corner_radius=0, size=10):
    try:
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=size,
            border=2
        )
        qr.add_data(text)
        qr.make(fit=True)
        
        img = qr.make_image(fill_color=color, back_color=bg_color).convert('RGBA')
        
        if corner_radius > 0:
            img = round_corners(img, corner_radius)
        
        return img
    except Exception as e:
        logger.error(f"خطا در ساخت کیوآر کد: {e}")
        raise

def cleanup_temp_files():
    """پاک کردن فایل‌های موقت قدیمی"""
    try:
        for file in os.listdir('.'):
            if file.startswith('qr_') and file.endswith('.png'):
                path = os.path.join('.', file)
                try:
                    os.remove(path)
                    logger.info(f"فایل موقت حذف شد: {file}")
                except:
                    pass
    except Exception as e:
        logger.error(f"خطا در پاک کردن فایل‌های موقت: {e}")

# ======================== دیکشنری رنگ‌ها ========================
COLORS = {
    '⚫ مشکی': 'black',
    '🔴 قرمز': 'red',
    '🔵 آبی': 'blue',
    '🟢 سبز': 'green',
    '🟡 زرد': 'gold',
    '🟣 بنفش': 'purple',
    '🟠 نارنجی': 'orange',
    '🩷 صورتی': 'pink'
}

BACKGROUNDS = {
    '⚪ سفید': 'white',
    '🟡 کرم': 'ivory',
    '🔵 آبی روشن': 'lightblue',
    '🟢 سبز روشن': 'lightgreen',
    '🩷 صورتی روشن': 'lightpink',
    '🟣 بنفش روشن': 'lavender'
}

CORNERS = {
    '🔲 بدون گردی': 0,
    '🔘 گردی کم': 20,
    '⭕ گردی متوسط': 40,
    '🟣 گردی زیاد': 60
}

# ======================== دیتای موقت کاربران ========================
user_temp = {}
stop_event = Event()
start_time = time.time()

# ======================== دستورات ربات ========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
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
    except Exception as e:
        logger.error(f"خطا در start: {e}")
        await update.message.reply_text("❌ خطایی رخ داده است. لطفاً دوباره تلاش کنید.")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        await query.answer()
        user_id = query.from_user.id
        has_sub = get_user(user_id).get("subscription", {}).get("active", False)
        
        # ==================== بازگشت به منوی اصلی ====================
        if query.data == 'main_menu':
            remaining = get_remaining(user_id)
            update_user(user_id, {"waiting_for_text": False})
            if user_id in user_temp:
                del user_temp[user_id]
            await query.edit_message_text(
                f"👋 به ربات کیوآر کد خوش آمدید!\n\n"
                f"📊 سهمیه باقی‌مانده امروز: {remaining}\n"
                f"🔥 هر روز {FREE_DAILY_LIMIT} سهمیه رایگان\n"
                f"👥 با دعوت دوستان، {REFERRAL_BONUS} سهمیه اضافه بگیر!\n\n"
                f"برای شروع، دکمه 'ساخت کیوآر کد جدید' را بزنید.",
                reply_markup=get_main_keyboard(has_sub)
            )
            return
        
        # ==================== ساخت کیوآر کد جدید ====================
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
            
            update_user(user_id, {"waiting_for_text": True})
            keyboard = [[InlineKeyboardButton("🔙 انصراف", callback_data='main_menu')]]
            await query.edit_message_text(
                f"📝 لطفاً متنی که می‌خواهید کیوآر کد شود را ارسال کنید:\n"
                f"(سهمیه باقی‌مانده: {remaining} عدد)",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return
        
        # ==================== انتخاب ساده یا پیشرفته ====================
        if query.data == 'simple_mode':
            text = user_temp.get(user_id, {}).get('text', '')
            if not text:
                await query.edit_message_text(
                    "❌ خطا! لطفاً دوباره تلاش کنید.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data='main_menu')]])
                )
                return
            
            if not use_credit(user_id):
                await query.edit_message_text(
                    f"❌ سهمیه شما تمام شده!",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data='main_menu')]])
                )
                return
            
            try:
                img = generate_qr_code(text)
                path = f"qr_{user_id}_{int(time.time())}.png"
                img.save(path)
                
                remaining = get_remaining(user_id)
                
                await query.edit_message_text("⏳ در حال ساخت کیوآر کد...")
                with open(path, "rb") as photo:
                    await query.message.reply_photo(
                        photo=photo,
                        caption=f"✅ کیوآر کد ساده ساخته شد!\n📊 سهمیه باقی‌مانده: {remaining}"
                    )
                await query.message.reply_text(
                    "🔹 برای بازگشت به منو، دکمه زیر را بزنید:",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data='main_menu')]])
                )
                
                # پاک کردن فایل
                try:
                    os.remove(path)
                except:
                    pass
                
                if user_id in user_temp:
                    del user_temp[user_id]
                    
            except Exception as e:
                logger.error(f"خطا در ساخت ساده: {e}")
                await query.edit_message_text(f"❌ خطا در ساخت: {str(e)}")
            return
        
        # ==================== انتخاب پیشرفته ====================
        if query.data == 'advanced_mode':
            text = user_temp.get(user_id, {}).get('text', '')
            if not text:
                await query.edit_message_text(
                    "❌ خطا! لطفاً دوباره تلاش کنید.",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data='main_menu')]])
                )
                return
            
            user_temp[user_id]['step'] = 'corner'
            keyboard = []
            for name, value in CORNERS.items():
                keyboard.append([InlineKeyboardButton(name, callback_data=f'corner_{value}')])
            keyboard.append([InlineKeyboardButton("🔙 انصراف", callback_data='main_menu')])
            
            await query.edit_message_text(
                "🎨 مرحله ۱ از ۳: گردی گوشه\n\n"
                "لطفاً میزان گردی گوشه کیوآر کد را انتخاب کنید:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return
        
        # ==================== انتخاب گردی گوشه ====================
        if query.data.startswith('corner_'):
            corner = int(query.data.replace('corner_', ''))
            user_temp[user_id]['corner'] = corner
            user_temp[user_id]['step'] = 'bg_color'
            
            keyboard = []
            for name, code in BACKGROUNDS.items():
                keyboard.append([InlineKeyboardButton(name, callback_data=f'bg_{code}')])
            keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data='main_menu')])
            
            await query.edit_message_text(
                f"✅ گردی گوشه: {corner} پیکسل\n\n"
                "🎨 مرحله ۲ از ۳: رنگ پس‌زمینه\n\n"
                "لطفاً رنگ پس‌زمینه کیوآر کد را انتخاب کنید:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return
        
        # ==================== انتخاب رنگ پس‌زمینه ====================
        if query.data.startswith('bg_'):
            bg_color = query.data.replace('bg_', '')
            user_temp[user_id]['bg_color'] = bg_color
            user_temp[user_id]['step'] = 'color'
            
            keyboard = []
            for name, code in COLORS.items():
                keyboard.append([InlineKeyboardButton(name, callback_data=f'color_{code}')])
            keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data='main_menu')])
            
            await query.edit_message_text(
                f"✅ گردی گوشه: {user_temp[user_id]['corner']} پیکسل\n"
                f"✅ رنگ پس‌زمینه: {bg_color}\n\n"
                "🎨 مرحله ۳ از ۳: رنگ کیوآر کد\n\n"
                "لطفاً رنگ خود کیوآر کد را انتخاب کنید:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return
        
        # ==================== انتخاب رنگ کیوآر کد و ساخت نهایی ====================
        if query.data.startswith('color_'):
            color = query.data.replace('color_', '')
            user_temp[user_id]['color'] = color
            
            data = user_temp[user_id]
            text = data.get('text', '')
            corner = data.get('corner', 0)
            bg_color = data.get('bg_color', 'white')
            color = data.get('color', 'black')
            
            if not use_credit(user_id):
                await query.edit_message_text(
                    f"❌ سهمیه شما تمام شده!",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data='main_menu')]])
                )
                return
            
            try:
                img = generate_qr_code(text, color, bg_color, corner)
                path = f"qr_{user_id}_{int(time.time())}.png"
                img.save(path)
                
                remaining = get_remaining(user_id)
                
                await query.edit_message_text("⏳ در حال ساخت کیوآر کد پیشرفته...")
                with open(path, "rb") as photo:
                    await query.message.reply_photo(
                        photo=photo,
                        caption=f"✅ کیوآر کد پیشرفته ساخته شد!\n\n"
                                f"🎨 رنگ: {color}\n"
                                f"⬜ پس‌زمینه: {bg_color}\n"
                                f"⭕ گردی گوشه: {corner} پیکسل\n"
                                f"📊 سهمیه باقی‌مانده: {remaining}"
                    )
                await query.message.reply_text(
                    "🔹 برای بازگشت به منو، دکمه زیر را بزنید:",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data='main_menu')]])
                )
                
                try:
                    os.remove(path)
                except:
                    pass
                
                if user_id in user_temp:
                    del user_temp[user_id]
                    
            except Exception as e:
                logger.error(f"خطا در ساخت پیشرفته: {e}")
                await query.edit_message_text(f"❌ خطا در ساخت: {str(e)}")
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
            
    except Exception as e:
        logger.error(f"خطا در button_handler: {e}")
        try:
            await query.edit_message_text("❌ خطایی رخ داده است. لطفاً دوباره تلاش کنید.")
        except:
            pass

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.message.from_user.id
        user = get_user(user_id)
        
        if not user.get("waiting_for_text", False):
            await update.message.reply_text(
                "❌ لطفاً اول دکمه 'ساخت کیوآر کد جدید' را بزنید.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data='main_menu')]])
            )
            return
        
        text = update.message.text
        
        user_temp[user_id] = {
            'text': text,
            'step': 'select_mode'
        }
        
        update_user(user_id, {"waiting_for_text": False})
        
        keyboard = [
            [InlineKeyboardButton("⚡ ساده (پیش‌فرض)", callback_data='simple_mode')],
            [InlineKeyboardButton("🎨 پیشرفته (تنظیمات)", callback_data='advanced_mode')],
            [InlineKeyboardButton("🔙 انصراف", callback_data='main_menu')]
        ]
        
        await update.message.reply_text(
            f"✅ متن ذخیره شد!\n\n"
            f"📝 متن: {text}\n\n"
            f"حالا انتخاب کنید که کیوآر کد را به چه صورتی بسازید:\n\n"
            f"⚡ ساده: با تنظیمات پیش‌فرض (مشکی/سفید)\n"
            f"🎨 پیشرفته: با انتخاب رنگ و گردی گوشه",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except Exception as e:
        logger.error(f"خطا در handle_text: {e}")
        await update.message.reply_text("❌ خطایی رخ داده است. لطفاً دوباره تلاش کنید.")

# ======================== دستورات ادمین ========================
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
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
    except Exception as e:
        logger.error(f"خطا در admin_panel: {e}")
        await update.message.reply_text("❌ خطایی رخ داده است.")

async def admin_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
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
    except Exception as e:
        logger.error(f"خطا در admin_button: {e}")

async def activate_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
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
    except Exception as e:
        logger.error(f"خطا در activate_user: {e}")
        await update.message.reply_text("❌ خطایی رخ داده است.")

async def remove_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
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
    except Exception as e:
        logger.error(f"خطا در remove_user: {e}")
        await update.message.reply_text("❌ خطایی رخ داده است.")

# ======================== مدیریت سیگنال‌ها ========================
def signal_handler(sig, frame):
    logger.info("دریافت سیگنال خاتمه، در حال بستن ربات...")
    stop_event.set()
    sys.exit(0)

# ======================== تابع اصلی با ری‌استارت خودکار ========================
def run_bot():
    """اجرای ربات با قابلیت ری‌استارت خودکار"""
    while not stop_event.is_set():
        try:
            logger.info("راه‌اندازی ربات...")
            
            # پاک کردن فایل‌های موقت
            cleanup_temp_files()
            
            # ساخت اپلیکیشن
            application = Application.builder().token(TOKEN).build()
            
            # اضافه کردن هندلرها
            application.add_handler(CommandHandler("start", start))
            application.add_handler(CommandHandler("admin", admin_panel))
            application.add_handler(CommandHandler("activate", activate_user))
            application.add_handler(CommandHandler("remove", remove_user))
            
            application.add_handler(CallbackQueryHandler(button_handler))
            application.add_handler(CallbackQueryHandler(admin_button, pattern="^admin_"))
            application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
            
            # اجرای ربات با timeout و reconnect
            logger.info("ربات شروع به کار کرد...")
            
            # استفاده از run_polling با تنظیمات پایدار
            application.run_polling(
                poll_interval=1.0,
                timeout=30,
                drop_pending_updates=True,
                allowed_updates=None
            )
            
        except NetworkError as e:
            logger.error(f"خطای شبکه: {e} - تلاش برای اتصال مجدد...")
            time.sleep(5)
            continue
            
        except TimedOut as e:
            logger.error(f"خطای Timeout: {e} - تلاش مجدد...")
            time.sleep(5)
            continue
            
        except RetryAfter as e:
            logger.error(f"Rate Limit: {e} - صبر کردن...")
            time.sleep(e.retry_after + 1)
            continue
            
        except TelegramError as e:
            logger.error(f"خطای تلگرام: {e} - تلاش مجدد...")
            time.sleep(10)
            continue
            
        except Exception as e:
            logger.error(f"خطای ناشناخته در ربات: {e} - تلاش مجدد در ۱۰ ثانیه...")
            time.sleep(10)
            continue
            
        finally:
            # اگر حلقه به اینجا رسید، یعنی ربات متوقف شده
            if not stop_event.is_set():
                logger.info("ربات متوقف شد، راه‌اندازی مجدد در ۵ ثانیه...")
                time.sleep(5)

# ======================== اصلی ========================
def main():
    try:
        logger.info("شروع برنامه...")
        
        # تنظیم سیگنال‌ها
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        # پاک کردن فایل‌های موقت در شروع
        cleanup_temp_files()
        
        # اجرای وب‌سرور در ترد جداگانه
        web_thread = Thread(target=run_web_server, daemon=True)
        web_thread.start()
        logger.info(f"✅ وب‌سرور Flask روی پورت {PORT} روشن شد")
        
        # اجرای ربات با ری‌استارت خودکار
        run_bot()
        
    except Exception as e:
        logger.error(f"خطای اصلی: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
