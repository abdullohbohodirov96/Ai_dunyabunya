"""
AI Sales Analyzer PRO
=====================
amoCRM webhook → OpenAI analiz → SQLite saqlash → Telegram natija + bot komandalar.
"""

import json
import logging
import os
import re
import threading
import time
import traceback
from datetime import datetime, timezone, timedelta

import requests
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from database import init_db, save_analysis, get_today_stats, get_operator_stats
from database import get_leads_by_status, get_top_operators, UZB_TZ

# ─── .env faylni yuklash ──────────────────────────────────────────────────────
load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
AMOCRM_SUBDOMAIN = os.getenv("AMOCRM_SUBDOMAIN", "")

# ─── Logging sozlash ─────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("ai_sales_analyzer")

# ─── FastAPI ilovasi ──────────────────────────────────────────────────────────
app = FastAPI(
    title="AI Sales Analyzer PRO",
    description="amoCRM webhook → OpenAI analiz → SQLite → Telegram",
    version="2.0.0",
)


# ═══════════════════════════════════════════════════════════════════════════════
# amoCRM webhook ma'lumotlarni ajratib olish
# ═══════════════════════════════════════════════════════════════════════════════


def extract_lead_data(data: dict) -> dict:
    """amoCRM webhook JSON dan lead ma'lumotlarini ajratib oladi."""
    result = {
        "lead_id": None,
        "lead_name": None,
        "lead_url": None,
        "operator_name": None,
        "operator_id": None,
        "comment": None,
        "phone": None,
    }

    subdomain = AMOCRM_SUBDOMAIN
    account = data.get("account", {})
    if isinstance(account, dict):
        subdomain = account.get("subdomain", subdomain)

    # ── Leads ma'lumotlarini olish ────────────────────────────────────────
    leads = data.get("leads", {})
    if isinstance(leads, dict):
        for action in ("add", "update", "status"):
            items = leads.get(action, [])
            if isinstance(items, list):
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    result["lead_id"] = str(item.get("id", "")) or result["lead_id"]
                    result["lead_name"] = item.get("name") or result["lead_name"]
                    result["operator_id"] = str(item.get("responsible_user_id", "")) or result["operator_id"]

                    # Custom fields dan telefon olish
                    for cf in item.get("custom_fields", []):
                        if not isinstance(cf, dict):
                            continue
                        fname = str(cf.get("name", "")).lower()
                        if any(w in fname for w in ("телефон", "phone", "telefon", "mobil")):
                            vals = cf.get("values", [])
                            if vals and isinstance(vals, list):
                                result["phone"] = vals[0].get("value") if isinstance(vals[0], dict) else str(vals[0])

    # ── Note / comment olish ─────────────────────────────────────────────
    notes = data.get("note") or data.get("notes") or []
    if isinstance(notes, dict):
        notes = [notes]
    for note in notes:
        if not isinstance(note, dict):
            continue
        text = note.get("text") or note.get("body") or ""
        if isinstance(text, str) and text.strip():
            result["comment"] = text.strip()
        if not result["lead_id"]:
            result["lead_id"] = str(note.get("entity_id", "")) or result["lead_id"]
        params = note.get("params", {})
        if isinstance(params, dict) and not result["comment"]:
            t = params.get("text", "")
            if isinstance(t, str) and t.strip():
                result["comment"] = t.strip()

    # ── To'g'ridan-to'g'ri text maydoni ──────────────────────────────────
    if not result["comment"]:
        if isinstance(data.get("text"), str) and data["text"].strip():
            result["comment"] = data["text"].strip()

    # ── Message text (chat webhook) ──────────────────────────────────────
    if not result["comment"]:
        msg = data.get("message_text") or ""
        if not msg:
            msg_obj = data.get("message", {})
            if isinstance(msg_obj, dict):
                msg = msg_obj.get("text", "")
        if isinstance(msg, str) and msg.strip():
            result["comment"] = msg.strip()

    # ── Kontaktdan telefon olish ─────────────────────────────────────────
    contacts = data.get("contacts", {})
    if isinstance(contacts, dict) and not result["phone"]:
        for action in ("add", "update"):
            for item in contacts.get(action, []):
                if not isinstance(item, dict):
                    continue
                for cf in item.get("custom_fields", []):
                    if not isinstance(cf, dict):
                        continue
                    fname = str(cf.get("name", "")).lower()
                    if any(w in fname for w in ("телефон", "phone", "telefon")):
                        vals = cf.get("values", [])
                        if vals and isinstance(vals, list):
                            result["phone"] = vals[0].get("value") if isinstance(vals[0], dict) else str(vals[0])

    # ── Operator nomi (account.current_user yoki _embedded) ──────────────
    current_user = account.get("current_user") if isinstance(account, dict) else None
    if isinstance(current_user, dict):
        result["operator_name"] = current_user.get("name") or result["operator_name"]
        if not result["operator_id"]:
            result["operator_id"] = str(current_user.get("id", ""))

    # ── CRM link yaratish ────────────────────────────────────────────────
    if result["lead_id"] and subdomain:
        result["lead_url"] = f"https://{subdomain}.amocrm.ru/leads/detail/{result['lead_id']}"

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# OpenAI analiz (JSON formatda)
# ═══════════════════════════════════════════════════════════════════════════════

SYSTEM_PROMPT = """Sen Dunyabunya qurilish materiallari gipermarketi uchun professional sotuv analizatori va sotuvchi yordamchisan.

Biznes haqida:
- Dunyabunya — qurilish materiallari gipermarketi
- 30 000+ mahsulot bor (gipsokarton, profil, kafel, santexnika, pol, aboy va boshqalar)
- Yetkazib berish xizmati bor (50+ mashina)
- 3 oydan 12 oygacha nasiya mavjud
- Maqsad: leadni sotuvga olib kelish

Senga operator yozgan izoh beriladi.

Vazifang:
1. Leadni bahola (1 dan 5 gacha)
2. Lead holatini aniqla:
   - issiq (tayyor sotib olishga)
   - iliq (qiziqgan, lekin o'ylayapti)
   - sovuq (aniq niyati yo'q)

3. Operator xatosini top:
   - savol bermagan
   - value tushuntirmagan
   - narxni noto'g'ri taqdim qilgan
   - follow-up qilmagan
   - mijoz ehtiyojini aniqlamagan
   - Agar xato yo'q bo'lsa "Xato topilmadi" deb yoz

4. Dunyabunya asosida TO'G'RI SOTUV STRATEGIYA ber:
   - Agar mijoz "qimmat" desa:
     → nasiya taklif qil (3-12 oy)
     → arzonroq alternativ ayt
     → sifat va uzoq xizmat qilishini tushuntir
   - Agar mijoz javob bermasa:
     → follow-up savol ber
   - Agar mijoz qiziqsa:
     → konkret mahsulot yoki variantga olib bor

5. Real sotuvchi kabi yoz:
   - oddiy tilda, aniq, sotuvga olib boradigan gaplar bilan

6. Keyingi savol yoz:
   → mijozni gapirtiradigan savol bo'lsin

7. Yopish strategiyasi ber:
   → qanday qilib sotuvga olib kelish mumkin

Sen FAQAT JSON formatda javob ber. Boshqa hech narsa yozma.
JSON formati:
{
  "score": "3/5",
  "status": "iliq",
  "operator_error": "Xato tavsifi yoki 'Xato topilmadi'",
  "next_question": "Mijozni gapirtiradigan savol",
  "recommendation": "Dunyabunya asosida yopish strategiyasi"
}

Qoidalar:
- status faqat "issiq", "iliq" yoki "sovuq" bo'lishi mumkin.
- score 1/5 dan 5/5 gacha bo'lishi kerak.
- Barcha javoblar o'zbek tilida bo'lsin.
- Real sotuvchi kabi professional va amaliy maslahat ber.
- Agar ma'lumot kam bo'lsa ham, mavjud ma'lumotlar asosida eng yaxshi tahlilni ber."""


def analyze_with_openai(text: str) -> dict:
    """OpenAI API orqali matnni analiz qiladi. Natija dict formatda qaytariladi."""
    fallback = {
        "score": "?/5", "status": "noaniq",
        "operator_error": "Aniqlab bo'lmadi",
        "next_question": "Qo'shimcha ma'lumot kerak",
        "recommendation": "Ma'lumot yetarli emas"
    }

    if not OPENAI_API_KEY:
        logger.error("❌ OPENAI_API_KEY sozlanmagan!")
        return fallback

    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Tahlil qil:\n\n{text}"},
        ],
        "temperature": 0.7,
        "max_tokens": 800,
        "response_format": {"type": "json_object"},
    }

    try:
        logger.info("🤖 OpenAI API ga so'rov yuborilmoqda...")
        resp = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers=headers, json=payload, timeout=30,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        logger.info("✅ OpenAI javobi olindi.")
        parsed = json.loads(content)
        # Kerakli kalitlar borligini tekshiramiz
        for key in ("score", "status", "operator_error", "next_question", "recommendation"):
            if key not in parsed:
                parsed[key] = fallback[key]
        return parsed
    except json.JSONDecodeError:
        logger.error(f"❌ OpenAI javobini JSON parse qilib bo'lmadi: {content[:200]}")
        return fallback
    except requests.exceptions.Timeout:
        logger.error("❌ OpenAI API timeout (30s)")
        return fallback
    except requests.exceptions.HTTPError as e:
        logger.error(f"❌ OpenAI API HTTP xatosi: {e}")
        return fallback
    except Exception as e:
        logger.error(f"❌ OpenAI kutilmagan xato: {e}")
        logger.error(traceback.format_exc())
        return fallback


# ═══════════════════════════════════════════════════════════════════════════════
# Telegram xabar yuborish
# ═══════════════════════════════════════════════════════════════════════════════


def send_telegram(text: str, chat_id: str = None) -> bool:
    """Telegram ga xabar yuborish. Markdown xatosida oddiy text bilan qayta yuboradi."""
    chat_id = chat_id or TELEGRAM_CHAT_ID
    if not TELEGRAM_BOT_TOKEN or not chat_id:
        logger.error("❌ TELEGRAM_BOT_TOKEN yoki CHAT_ID sozlanmagan!")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}

    try:
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code == 400:
            # Markdown xatosi - oddiy text yuboramiz
            payload.pop("parse_mode", None)
            resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        return True
    except Exception as e:
        logger.error(f"❌ Telegram xato: {e}")
        return False


def format_analysis_message(lead: dict, ai: dict) -> str:
    """Chiroyli Telegram xabar formatlash."""
    lines = [
        "🔔 *Yangi Lead Tahlili*",
        "━━━━━━━━━━━━━━━━━━━━",
        "",
        f"👤 *Lead:* {lead.get('lead_name') or 'Noma\\'lum'}",
        f"🆔 *Lead ID:* {lead.get('lead_id') or '—'}",
    ]
    if lead.get("lead_url"):
        lines.append(f"🔗 *CRM:* {lead['lead_url']}")
    if lead.get("phone"):
        lines.append(f"📞 *Telefon:* {lead['phone']}")
    lines.append(f"👨‍💼 *Operator:* {lead.get('operator_name') or lead.get('operator_id') or '—'}")
    if lead.get("comment"):
        comment_short = lead["comment"][:150]
        if len(lead["comment"]) > 150:
            comment_short += "..."
        lines.append(f"✍️ *Izoh:* {comment_short}")

    lines += [
        "",
        "━━━━━━━━━━━━━━━━━━━━",
        "",
        f"📊 *Lead bahosi:* {ai.get('score', '?/5')}",
        f"🔥 *Lead holati:* {ai.get('status', 'noaniq')}",
        f"❌ *Operator xatosi:* {ai.get('operator_error', '—')}",
        f"❓ *Keyingi savol:* {ai.get('next_question', '—')}",
        f"✅ *Tavsiya:* {ai.get('recommendation', '—')}",
        "",
        "━━━━━━━━━━━━━━━━━━━━",
        f"📌 _Manba: amoCRM Webhook_",
    ]
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# Telegram Bot Polling (komandalar uchun)
# ═══════════════════════════════════════════════════════════════════════════════

# Operator nomlari ro'yxati (komandalar uchun)
OPERATOR_COMMANDS = {
    "elmira": "Elmira",
    "zebo": "Zebo",
    "ali": "Ali",
}


def handle_bot_command(text: str, chat_id: str):
    """Bot komandalarini qayta ishlash."""
    text = text.strip().lower()
    now_str = datetime.now(UZB_TZ).strftime("%d.%m.%Y")

    try:
        # ── /hisobot_bugun ───────────────────────────────────────────────
        if text == "/hisobot_bugun":
            rows = get_today_stats()
            if not rows:
                send_telegram(f"📊 *Bugungi hisobot ({now_str})*\n\nBugun hali ma'lumot yo'q.", chat_id)
                return

            lines = [f"📊 *Bugungi umumiy hisobot*", f"📅 Sana: {now_str}", "━━━━━━━━━━━━━━━━━━━━", ""]
            total_all = 0
            for r in rows:
                name = r["operator_name"] or "Noma'lum"
                lines.append(f"👨‍💼 *{name}*")
                lines.append(f"   📋 Jami: {r['total']} ta lead")
                lines.append(f"   🔥 Issiq: {r['issiq']} | 🌤 Iliq: {r['iliq']} | ❄️ Sovuq: {r['sovuq']}")
                lines.append(f"   ⭐ O'rtacha baho: {r['avg_score']}/5")
                lines.append("")
                total_all += r["total"]
            lines.append(f"📈 *Jami:* {total_all} ta lead tahlil qilindi")
            send_telegram("\n".join(lines), chat_id)
            return

        # ── /hisobot_{operator} ──────────────────────────────────────────
        for cmd_key, display_name in OPERATOR_COMMANDS.items():
            if text == f"/hisobot_{cmd_key}":
                stats, errors, last_rec = get_operator_stats(cmd_key)
                if not stats or stats["total"] == 0:
                    send_telegram(f"👨‍💼 *{display_name}* - bugun ({now_str}) hali ma'lumot yo'q.", chat_id)
                    return

                lines = [
                    f"👨‍💼 *{display_name} - Bugungi hisobot*",
                    f"📅 Sana: {now_str}",
                    "━━━━━━━━━━━━━━━━━━━━",
                    "",
                    f"📋 *Jami leadlar:* {stats['total']} ta",
                    f"🔥 *Issiq:* {stats['issiq']} ta",
                    f"🌤 *Iliq:* {stats['iliq']} ta",
                    f"❄️ *Sovuq:* {stats['sovuq']} ta",
                    f"⭐ *O'rtacha baho:* {stats['avg_score']}/5",
                    "",
                ]

                if errors:
                    lines.append("❌ *Eng ko'p xatolar:*")
                    for i, err in enumerate(errors, 1):
                        lines.append(f"   {i}. {err['operator_error']} ({err['cnt']} marta)")
                    lines.append("")

                if last_rec:
                    lines.append(f"💡 *Oxirgi AI tavsiya:*\n   {last_rec['recommendation']}")

                send_telegram("\n".join(lines), chat_id)
                return

        # ── /top_operatorlar ─────────────────────────────────────────────
        if text == "/top_operatorlar":
            rows = get_top_operators()
            if not rows:
                send_telegram(f"🏆 *Top operatorlar ({now_str})*\n\nBugun hali ma'lumot yo'q.", chat_id)
                return

            lines = [f"🏆 *Top operatorlar*", f"📅 Sana: {now_str}", "━━━━━━━━━━━━━━━━━━━━", ""]
            for i, r in enumerate(rows, 1):
                medal = ["🥇", "🥈", "🥉"][i - 1] if i <= 3 else f"{i}."
                lines.append(f"{medal} *{r['operator_name'] or 'Noma\\'lum'}*")
                lines.append(f"   ⭐ {r['avg_score']}/5 | 📋 {r['total']} lead | 🔥 {r['issiq']} issiq | ❄️ {r['sovuq']} sovuq")
                lines.append("")
            send_telegram("\n".join(lines), chat_id)
            return

        # ── /sovuq_leadlar ───────────────────────────────────────────────
        if text == "/sovuq_leadlar":
            rows = get_leads_by_status("sovuq")
            if not rows:
                send_telegram(f"❄️ *Sovuq leadlar ({now_str})*\n\nBugun sovuq lead yo'q.", chat_id)
                return

            lines = [f"❄️ *Sovuq leadlar*", f"📅 Sana: {now_str}", "━━━━━━━━━━━━━━━━━━━━", ""]
            for r in rows:
                lines.append(f"• *{r['lead_name'] or 'Nomsiz'}* (ID: {r['lead_id'] or '—'})")
                lines.append(f"  👨‍💼 {r['operator_name'] or '—'} | ⭐ {r['ai_score']}")
                if r["phone"]:
                    lines.append(f"  📞 {r['phone']}")
                lines.append("")
            send_telegram("\n".join(lines), chat_id)
            return

        # ── /issiq_leadlar ───────────────────────────────────────────────
        if text == "/issiq_leadlar":
            rows = get_leads_by_status("issiq")
            if not rows:
                send_telegram(f"🔥 *Issiq leadlar ({now_str})*\n\nBugun issiq lead yo'q.", chat_id)
                return

            lines = [f"🔥 *Issiq leadlar*", f"📅 Sana: {now_str}", "━━━━━━━━━━━━━━━━━━━━", ""]
            for r in rows:
                lines.append(f"• *{r['lead_name'] or 'Nomsiz'}* (ID: {r['lead_id'] or '—'})")
                lines.append(f"  👨‍💼 {r['operator_name'] or '—'} | ⭐ {r['ai_score']}")
                if r["phone"]:
                    lines.append(f"  📞 {r['phone']}")
                lines.append("")
            send_telegram("\n".join(lines), chat_id)
            return

    except Exception as e:
        logger.error(f"❌ Komanda ishlov berishda xato: {e}")
        logger.error(traceback.format_exc())
        send_telegram(f"⚠️ Xatolik yuz berdi: {e}", chat_id)


class TelegramPoller:
    """Background thread orqali Telegram bot komandalarini polling qiladi."""

    def __init__(self):
        self.running = False
        self.last_update_id = 0
        self.thread = None

    def start(self):
        if not TELEGRAM_BOT_TOKEN:
            logger.warning("⚠️ TELEGRAM_BOT_TOKEN yo'q, bot polling ishlamaydi.")
            return
        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()
        logger.info("🤖 Telegram bot polling boshlandi.")

    def stop(self):
        self.running = False

    def _loop(self):
        while self.running:
            try:
                url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
                params = {"offset": self.last_update_id + 1, "timeout": 30}
                resp = requests.get(url, params=params, timeout=35)
                updates = resp.json().get("result", [])
                for upd in updates:
                    self.last_update_id = upd["update_id"]
                    msg = upd.get("message", {})
                    text = msg.get("text", "")
                    chat_id = str(msg.get("chat", {}).get("id", ""))
                    if text.startswith("/"):
                        logger.info(f"📨 Bot komanda: {text} (chat: {chat_id})")
                        handle_bot_command(text, chat_id)
            except Exception as e:
                logger.error(f"❌ Polling xato: {e}")
                time.sleep(5)


bot_poller = TelegramPoller()


# ═══════════════════════════════════════════════════════════════════════════════
# API Endpointlar
# ═══════════════════════════════════════════════════════════════════════════════


@app.get("/")
async def root():
    """Health check endpoint."""
    return {
        "status": "✅ AI Sales Analyzer ishlayapti",
        "version": "2.0.0",
        "endpoints": {
            "health": "GET /",
            "webhook": "POST /webhook/amocrm",
        },
    }


@app.post("/webhook/amocrm")
async def amocrm_webhook(request: Request):
    """amoCRM webhook endpointi. Ma'lumot oladi, analiz qiladi, saqlaydi, Telegram ga yuboradi."""
    try:
        # ── 1. Ma'lumotni qabul qilish ───────────────────────────────────
        content_type = request.headers.get("content-type", "")
        if "application/json" in content_type:
            data = await request.json()
        else:
            form = await request.form()
            data = dict(form)

        # ── 2. To'liq log ────────────────────────────────────────────────
        logger.info("=" * 60)
        logger.info("📥 amoCRM WEBHOOK QABUL QILINDI")
        logger.info("=" * 60)
        logger.info(f"📋 Ma'lumot:\n{json.dumps(data, indent=2, ensure_ascii=False, default=str)}")

        # ── 3. Lead ma'lumotlarini ajratish ───────────────────────────────
        lead = extract_lead_data(data)
        logger.info(f"📊 Ajratilgan: lead_id={lead['lead_id']}, operator={lead['operator_name']}, comment={bool(lead['comment'])}")

        # ── 4. Analiz uchun matn tayyorlash ───────────────────────────────
        if lead["comment"]:
            analysis_text = lead["comment"]
        else:
            analysis_text = json.dumps(data, ensure_ascii=False, indent=2, default=str)

        # ── 5. OpenAI analiz (JSON) ───────────────────────────────────────
        ai = analyze_with_openai(analysis_text)

        # ── 6. Databasega saqlash ─────────────────────────────────────────
        db_record = {
            **lead,
            "ai_score": ai.get("score"),
            "lead_status": ai.get("status"),
            "operator_error": ai.get("operator_error"),
            "recommendation": ai.get("recommendation"),
            "next_question": ai.get("next_question"),
        }
        save_analysis(db_record)

        # ── 7. Telegram ga yuborish ───────────────────────────────────────
        message = format_analysis_message(lead, ai)
        sent = send_telegram(message)

        return JSONResponse(status_code=200, content={
            "status": "success",
            "message": "Webhook qabul qilindi, analiz qilindi, saqlandi",
            "telegram_sent": sent,
        })

    except json.JSONDecodeError as e:
        logger.error(f"❌ JSON parse xatosi: {e}")
        return JSONResponse(status_code=400, content={"status": "error", "message": str(e)})
    except Exception as e:
        logger.error(f"❌ Webhook xato: {e}")
        logger.error(traceback.format_exc())
        return JSONResponse(status_code=500, content={"status": "error", "message": str(e)})


# ═══════════════════════════════════════════════════════════════════════════════
# Startup / Shutdown
# ═══════════════════════════════════════════════════════════════════════════════


@app.on_event("startup")
async def startup_event():
    """Ilova ishga tushganda: DB yaratish, sozlamalarni tekshirish, bot polling boshlash."""
    logger.info("🚀 AI Sales Analyzer PRO ishga tushmoqda...")

    # Database yaratish
    init_db()

    # Muhit o'zgaruvchilarini tekshirish
    checks = {
        "OPENAI_API_KEY": bool(OPENAI_API_KEY),
        "TELEGRAM_BOT_TOKEN": bool(TELEGRAM_BOT_TOKEN),
        "TELEGRAM_CHAT_ID": bool(TELEGRAM_CHAT_ID),
    }
    for key, ok in checks.items():
        logger.info(f"   {key}: {'✅' if ok else '❌ SOZLANMAGAN'}")

    if all(checks.values()):
        logger.info("✅ Barcha sozlamalar tayyor!")
    else:
        missing = [k for k, v in checks.items() if not v]
        logger.warning(f"⚠️ Yo'q: {', '.join(missing)}")

    # Telegram bot polling boshlash
    bot_poller.start()

    logger.info("📡 Webhook: https://YOUR-APP.onrender.com/webhook/amocrm")


@app.on_event("shutdown")
async def shutdown_event():
    """Ilova to'xtashda bot pollingni to'xtatish."""
    bot_poller.stop()
    logger.info("🛑 AI Sales Analyzer to'xtadi.")
