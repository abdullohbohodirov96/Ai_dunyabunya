# 🤖 AI Sales Analyzer MVP

amoCRM webhook orqali kelgan lead/note ma'lumotlarini **OpenAI API** yordamida analiz qilib, natijani **Telegram** guruhga yuboruvchi tizim.

## 📋 Qanday ishlaydi?

```
amoCRM Webhook → FastAPI Backend → OpenAI Analiz → Telegram Guruh
```

1. **amoCRM** da lead yangilanganda yoki note qo'shilganda webhook ishga tushadi
2. **FastAPI** webhook ma'lumotni qabul qiladi va log qiladi
3. **OpenAI** ma'lumotni professional sales analyst sifatida analiz qiladi
4. **Telegram** guruhga natija yuboriladi

## 🧠 AI Tahlil Natijasi

AI quyidagi ma'lumotlarni chiqaradi:

| Bo'lim | Tavsif |
|--------|--------|
| 📊 Lead bahosi | 1/5 dan 5/5 gacha |
| 🌡 Lead holati | issiq / iliq / sovuq |
| ❌ Operator xatosi | Aniqlangan xatolar |
| ❓ Savol tavsiyasi | Qanday savol berish kerak |
| ✅ Yopish tavsiyasi | Leadni sotuvga aylantirish yo'li |

## 🛠 Stack

- **Python** + **FastAPI** + **Uvicorn**
- **OpenAI API** (gpt-4o-mini)
- **Telegram Bot API**
- **python-dotenv**
- **requests**

## 🚀 O'rnatish

### 1. Repozitoriyani klonlash

```bash
git clone https://github.com/YOUR_USERNAME/ai-sales-analyzer.git
cd ai-sales-analyzer
```

### 2. Virtual muhit yaratish

```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
# yoki
venv\Scripts\activate     # Windows
```

### 3. Kutubxonalarni o'rnatish

```bash
pip install -r requirements.txt
```

### 4. .env faylni sozlash

```bash
cp .env.example .env
```

`.env` faylni oching va quyidagilarni to'ldiring:

```env
OPENAI_API_KEY=sk-your-api-key
TELEGRAM_BOT_TOKEN=your-bot-token
TELEGRAM_CHAT_ID=-100your-chat-id
```

### 5. Ishga tushirish

```bash
uvicorn main:app --reload --port 8000
```

Brauzerda oching: [http://localhost:8000](http://localhost:8000)

## 📡 API Endpointlar

| Metod | URL | Tavsif |
|-------|-----|--------|
| `GET` | `/` | Health check – ilova ishlayaptimi? |
| `POST` | `/webhook/amocrm` | amoCRM webhook qabul qilish |

## 🧪 Webhook Test

Lokal test uchun `curl` yoki Postman ishlatishingiz mumkin:

```bash
curl -X POST http://localhost:8000/webhook/amocrm \
  -H "Content-Type: application/json" \
  -d '{
    "leads": {
      "update": [{
        "id": 12345,
        "name": "Test Lead",
        "price": 5000000,
        "status_id": 142,
        "custom_fields": [
          {"id": 1, "name": "Telefon", "values": [{"value": "+998901234567"}]}
        ]
      }]
    }
  }'
```

Note/comment bilan test:

```bash
curl -X POST http://localhost:8000/webhook/amocrm \
  -H "Content-Type: application/json" \
  -d '{
    "note": [{
      "text": "Mijoz narx so'\''radi, 5 mln dedi, javob berildi. Ertaga qayta qo'\''ng'\''iroq qilishni so'\''radi."
    }]
  }'
```

## ☁️ Render ga Deploy

### 1. GitHub ga push qiling

```bash
git add .
git commit -m "AI Sales Analyzer MVP"
git push origin main
```

### 2. Render.com da yangi Web Service yarating

- **Build Command:** `pip install -r requirements.txt`
- **Start Command:** `uvicorn main:app --host 0.0.0.0 --port $PORT`

### 3. Environment Variables qo'shing

Render dashboard → Environment tab:

| Key | Value |
|-----|-------|
| `OPENAI_API_KEY` | `sk-...` |
| `TELEGRAM_BOT_TOKEN` | `123456:ABC...` |
| `TELEGRAM_CHAT_ID` | `-100...` |

### 4. amoCRM da webhook sozlang

Render URL ni oling va amoCRM webhook URL sifatida qo'ying:

```
https://your-app-name.onrender.com/webhook/amocrm
```

## 📁 Loyiha strukturasi

```
ai-sales-analyzer/
├── main.py              # Asosiy FastAPI ilova
├── requirements.txt     # Python kutubxonalar
├── .env.example         # Muhit o'zgaruvchilari namunasi
├── .env                 # Haqiqiy sozlamalar (git ignore)
└── README.md            # Hujjat
```

## ⚠️ Muhim eslatmalar

- `.env` faylni **hech qachon** git ga push qilmang
- Render da **Free plan** da server 15 daqiqa ishlamasdan tursa uyquga ketadi
- amoCRM webhook ni bir nechta event uchun sozlash mumkin (lead yaratildi, yangilandi, note qo'shildi)
- OpenAI API dan `gpt-4o-mini` model ishlatiladi (arzon va tez)

## 📄 Litsenziya

MIT License
