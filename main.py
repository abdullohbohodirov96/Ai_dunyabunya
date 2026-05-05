"""
AI Sales Analyzer MVP
=====================
amoCRM webhook orqali kelgan lead/note ma'lumotlarini OpenAI API yordamida
analiz qilib, natijani Telegram guruhga yuboruvchi FastAPI ilova.
"""

import json
import logging
import os
import traceback

import requests
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

# ─── .env faylni yuklash ──────────────────────────────────────────────────────
load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# ─── Logging sozlash ─────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("ai_sales_analyzer")

# ─── FastAPI ilovasi ──────────────────────────────────────────────────────────
app = FastAPI(
    title="AI Sales Analyzer",
    description="amoCRM webhook → OpenAI analiz → Telegram natija",
    version="1.0.0",
)


# ═══════════════════════════════════════════════════════════════════════════════
# Yordamchi funksiyalar
# ═══════════════════════════════════════════════════════════════════════════════


def extract_comment(data: dict) -> str | None:
    """
    Webhook JSON ichidan operator izohi / note / comment textini topishga harakat qiladi.
    amoCRM turli formatlarda ma'lumot yuborishi mumkin, shuning uchun bir nechta
    joydan qidiramiz.
    """
    # 1. To'g'ridan-to'g'ri "text" maydoni
    if isinstance(data.get("text"), str) and data["text"].strip():
        return data["text"].strip()

    # 2. note[0].text yoki note[0].params.text
    notes = data.get("note") or data.get("notes") or []
    if isinstance(notes, dict):
        notes = [notes]
    for note in notes:
        if isinstance(note, dict):
            text = note.get("text") or note.get("body") or ""
            if isinstance(text, str) and text.strip():
                return text.strip()
            params = note.get("params", {})
            if isinstance(params, dict):
                t = params.get("text", "")
                if isinstance(t, str) and t.strip():
                    return t.strip()

    # 3. unsorted → add → 0 → note (amoCRM v4 webhook formati)
    unsorted = data.get("unsorted", {})
    if isinstance(unsorted, dict):
        for action_type in ("add", "update"):
            items = unsorted.get(action_type, [])
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, dict):
                        note_text = item.get("note", "")
                        if isinstance(note_text, str) and note_text.strip():
                            return note_text.strip()

    # 4. leads → add/update → custom_fields ichidan
    leads = data.get("leads", {})
    if isinstance(leads, dict):
        for action_type in ("add", "update", "status"):
            items = leads.get(action_type, [])
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, dict):
                        # name + custom_fields kombinatsiyasini qaytaramiz
                        name = item.get("name", "")
                        cf = item.get("custom_fields", [])
                        if cf:
                            return f"Lead: {name}\nCustom fields: {json.dumps(cf, ensure_ascii=False)}"

    # 5. message_text (chat webhook)
    msg_text = data.get("message_text") or data.get("message", {}).get("text", "")
    if isinstance(msg_text, str) and msg_text.strip():
        return msg_text.strip()

    return None


def analyze_with_openai(text: str) -> str:
    """
    OpenAI API orqali matnni professional sales analyst sifatida analiz qiladi.
    Natija o'zbek tilida qaytariladi.
    """
    if not OPENAI_API_KEY:
        logger.error("❌ OPENAI_API_KEY sozlanmagan!")
        return "⚠️ OpenAI API kaliti sozlanmagan. .env faylni tekshiring."

    system_prompt = """Sen professional CRM sales analyst bo'lib ishlaysan.
Senga amoCRM tizimidan kelgan lead yoki operator izoh ma'lumotlari beriladi.
Sen quyidagi formatda o'zbek tilida tahlil berishing kerak:

📊 **Lead bahosi:** X/5
🌡 **Lead holati:** issiq / iliq / sovuq
❌ **Operator xatosi:** (agar xato bo'lsa aniq yoz, bo'lmasa "Xato topilmadi" deb yoz)
❓ **Qanday savol berish kerak:** (keyingi qadamda qanday savol berish kerakligini yoz)
✅ **Leadni yopish uchun tavsiya:** (qanday qilib leadni sotuvga aylantirish mumkinligini yoz)

Har bir bo'limni aniq va qisqa yoz. Professional va amaliy maslahat ber.
Agar ma'lumot kam bo'lsa ham, mavjud ma'lumotlar asosida eng yaxshi tahlilni ber."""

    user_message = f"Quyidagi CRM ma'lumotini tahlil qil:\n\n{text}"

    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        "temperature": 0.7,
        "max_tokens": 1000,
    }

    try:
        logger.info("🤖 OpenAI API ga so'rov yuborilmoqda...")
        response = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=30,
        )
        response.raise_for_status()
        result = response.json()
        answer = result["choices"][0]["message"]["content"]
        logger.info("✅ OpenAI javobi muvaffaqiyatli olindi.")
        return answer
    except requests.exceptions.Timeout:
        logger.error("❌ OpenAI API timeout xatosi (30s)")
        return "⚠️ OpenAI API javob bermadi (timeout). Keyinroq qayta urinib ko'ring."
    except requests.exceptions.HTTPError as e:
        logger.error(f"❌ OpenAI API HTTP xatosi: {e}")
        logger.error(f"   Javob: {e.response.text if e.response else 'Javob yo''q'}")
        return f"⚠️ OpenAI API xatosi: {e}"
    except Exception as e:
        logger.error(f"❌ OpenAI API kutilmagan xato: {e}")
        logger.error(traceback.format_exc())
        return f"⚠️ Kutilmagan xato: {e}"


def send_to_telegram(message: str) -> bool:
    """
    Telegram Bot API orqali xabarni guruhga yuboradi.
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.error("❌ TELEGRAM_BOT_TOKEN yoki TELEGRAM_CHAT_ID sozlanmagan!")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown",
    }

    try:
        logger.info("📤 Telegram ga xabar yuborilmoqda...")
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        logger.info("✅ Telegram xabar muvaffaqiyatli yuborildi.")
        return True
    except requests.exceptions.HTTPError as e:
        logger.error(f"❌ Telegram API HTTP xatosi: {e}")
        logger.error(f"   Javob: {e.response.text if e.response else 'Javob yo''q'}")
        # Markdown parse xatosi bo'lsa, oddiy text sifatida qayta yuboramiz
        if e.response and e.response.status_code == 400:
            logger.info("🔄 Markdown xatosi, oddiy text sifatida qayta yuborilmoqda...")
            payload["parse_mode"] = None
            try:
                response = requests.post(url, json=payload, timeout=10)
                response.raise_for_status()
                logger.info("✅ Telegram xabar oddiy text sifatida yuborildi.")
                return True
            except Exception as retry_err:
                logger.error(f"❌ Qayta yuborish ham muvaffaqiyatsiz: {retry_err}")
        return False
    except Exception as e:
        logger.error(f"❌ Telegram xabar yuborishda xato: {e}")
        logger.error(traceback.format_exc())
        return False


# ═══════════════════════════════════════════════════════════════════════════════
# API Endpointlar
# ═══════════════════════════════════════════════════════════════════════════════


@app.get("/")
async def root():
    """Health check endpoint."""
    return {
        "status": "✅ AI Sales Analyzer ishlayapti",
        "version": "1.0.0",
        "endpoints": {
            "health": "GET /",
            "webhook": "POST /webhook/amocrm",
        },
    }


@app.post("/webhook/amocrm")
async def amocrm_webhook(request: Request):
    """
    amoCRM webhook endpointi.
    Kelgan ma'lumotni qabul qiladi, AI orqali analiz qiladi va Telegram ga yuboradi.
    """
    try:
        # ── 1. Ma'lumotni qabul qilish ───────────────────────────────────────
        content_type = request.headers.get("content-type", "")

        if "application/json" in content_type:
            data = await request.json()
        else:
            # amoCRM ba'zan form-data sifatida ham yuboradi
            form = await request.form()
            data = dict(form)

        # ── 2. To'liq log qilish ─────────────────────────────────────────────
        logger.info("=" * 60)
        logger.info("📥 amoCRM WEBHOOK QABUL QILINDI")
        logger.info("=" * 60)
        logger.info(f"📋 Ma'lumot:\n{json.dumps(data, indent=2, ensure_ascii=False, default=str)}")
        logger.info("=" * 60)

        # ── 3. Comment/note topish ────────────────────────────────────────────
        comment = extract_comment(data)

        if comment:
            logger.info(f"💬 Topilgan izoh/comment: {comment[:200]}...")
            analysis_text = comment
        else:
            logger.info("ℹ️ Comment topilmadi. Butun JSON analiz qilinadi.")
            analysis_text = json.dumps(data, ensure_ascii=False, indent=2, default=str)

        # ── 4. OpenAI orqali analiz ───────────────────────────────────────────
        ai_result = analyze_with_openai(analysis_text)

        # ── 5. Telegram ga yuborish ───────────────────────────────────────────
        telegram_message = (
            "🔔 *Yangi Lead Tahlili*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"{ai_result}\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "📌 _Manba: amoCRM Webhook_"
        )

        sent = send_to_telegram(telegram_message)

        return JSONResponse(
            status_code=200,
            content={
                "status": "success",
                "message": "Webhook qabul qilindi va analiz qilindi",
                "telegram_sent": sent,
            },
        )

    except json.JSONDecodeError as e:
        logger.error(f"❌ JSON parse xatosi: {e}")
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": f"Noto'g'ri JSON format: {e}"},
        )
    except Exception as e:
        logger.error(f"❌ Webhook ishlov berishda xato: {e}")
        logger.error(traceback.format_exc())
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": f"Server xatosi: {e}"},
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Startup loglari
# ═══════════════════════════════════════════════════════════════════════════════


@app.on_event("startup")
async def startup_event():
    """Ilova ishga tushganda sozlamalarni tekshirish."""
    logger.info("🚀 AI Sales Analyzer ishga tushmoqda...")

    # Muhit o'zgaruvchilarini tekshirish
    checks = {
        "OPENAI_API_KEY": bool(OPENAI_API_KEY),
        "TELEGRAM_BOT_TOKEN": bool(TELEGRAM_BOT_TOKEN),
        "TELEGRAM_CHAT_ID": bool(TELEGRAM_CHAT_ID),
    }

    for key, is_set in checks.items():
        status = "✅" if is_set else "❌ SOZLANMAGAN"
        logger.info(f"   {key}: {status}")

    if all(checks.values()):
        logger.info("✅ Barcha sozlamalar tayyor. Ilova ishlashga tayyor!")
    else:
        missing = [k for k, v in checks.items() if not v]
        logger.warning(f"⚠️ Quyidagi sozlamalar yo'q: {', '.join(missing)}")
        logger.warning("   .env faylni tekshiring yoki muhit o'zgaruvchilarini sozlang.")

    logger.info(f"📡 Webhook URL: https://YOUR-APP.onrender.com/webhook/amocrm")
