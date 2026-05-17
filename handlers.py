# handlers.py
import logging
import unicodedata
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from tcdd_api import check_train_tickets
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, ConversationHandler

from config import (
    ARRIVAL,
    ARRIVAL_SELECT,
    CABIN_CLASS,
    DATE,
    DEPARTURE,
    DEPARTURE_SELECT,
    GENDER,
    TIME,
    TRANSPORT,
)

logger = logging.getLogger(__name__)

ISTANBUL_TZ = ZoneInfo("Europe/Istanbul")
CHECK_INTERVAL_SECONDS = 60
CABIN_OPTIONS = {"ekonomi": "Ekonomi", "business": "Business", "pulman": "Pulman"}


# ──────────────────────────────────────────────────────────────
# Yardımcı fonksiyonlar
# ──────────────────────────────────────────────────────────────

def _norm(text):
    """Türkçe karakterleri de hesaba katan basit arama normalizasyonu."""
    text = str(text or "").casefold().replace("ı", "i")
    text = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in text if not unicodedata.combining(ch))


def _get_station_list(context):
    stations = context.bot_data.get("station_list", [])
    if isinstance(stations, list):
        return stations
    return []


def _station_button_text(station):
    name = str(station.get("name", "")).title()
    station_id = station.get("id")
    return f"{name} | ID:{station_id}"


def _find_stations(context, query_text, limit=15):
    q = _norm(query_text).strip()
    if not q:
        return []

    matches = []
    for station in _get_station_list(context):
        station_name = station.get("name", "")
        if q in _norm(station_name):
            matches.append(station)

    unique = []
    seen = set()
    for station in matches:
        key = (station.get("id"), station.get("name"))
        if key in seen:
            continue
        seen.add(key)
        unique.append(station)

    return unique[:limit]


def _cabin_keyboard(secimler):
    """Mevcut seçimlere göre kabin klavyesini üretir."""
    def btn(key, label):
        prefix = "✅" if key in secimler else "⬜"
        return InlineKeyboardButton(f"{prefix} {label}", callback_data=f"cabin:{key}")

    return [
        [btn("ekonomi", "Ekonomi"), btn("business", "Business")],
        [btn("pulman", "Pulman"), InlineKeyboardButton("☑️ Hepsi", callback_data="cabin:hepsi")],
        [InlineKeyboardButton("✔️ Tamam", callback_data="cabin:tamam")],
    ]


# ──────────────────────────────────────────────────────────────
# Konuşma adımları — GENDER → TRANSPORT → DATE → DEPARTURE →
#   DEPARTURE_SELECT → ARRIVAL → ARRIVAL_SELECT →
#   CABIN_CLASS → TIME → (job başlar)
# ──────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    keyboard = [
        [
            InlineKeyboardButton("👨 Erkek", callback_data="Erkek"),
            InlineKeyboardButton("👩 Kadın", callback_data="Kadin"),
        ]
    ]
    msg = "Hoş geldin! Sana uygun biletleri bulabilmem için cinsiyetini seçer misin?"
    try:
        if update.message:
            await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await update.callback_query.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception as e:
        logger.error("Start komutunda hata: %s", e)
    return GENDER


async def select_gender(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["gender"] = query.data

    keyboard = [[InlineKeyboardButton("🚂 Tren", callback_data="Tren")]]
    await query.edit_message_text(
        text=f"✅ Cinsiyet kaydedildi: {query.data}\n\nLütfen seyahat türünü seç:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return TRANSPORT


async def select_transport(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    today = datetime.now(ISTANBUL_TZ)
    keyboard = []
    row = []

    for i in range(8):
        d = today + timedelta(days=i)
        tarih_gorsel = d.strftime("%d.%m.%Y")
        tcdd_format = d.strftime("%d-%m-%Y 00:00:00")

        if i == 0:
            btn_text = f"Bugün ({tarih_gorsel})"
        elif i == 1:
            btn_text = f"Yarın ({tarih_gorsel})"
        else:
            btn_text = tarih_gorsel

        row.append(InlineKeyboardButton(btn_text, callback_data=tcdd_format))
        if len(row) == 2:
            keyboard.append(row)
            row = []

    if row:
        keyboard.append(row)

    await query.edit_message_text(
        text="🚂 Tren seçildi. Lütfen tarihi seçin:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return DATE


async def select_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data["tcdd_tarih"] = query.data

    await query.edit_message_text(
        text=(
            f"📅 Tarih onaylandı: {query.data[:10]}\n\n"
            "📍 Lütfen sadece KALKIŞ yapacağınız şehri veya istasyonu yazın.\n\n"
            "Örnek: Ankara veya Söğütlüçeşme"
        )
    )
    return DEPARTURE


async def search_departure(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query_text = update.message.text.strip()
    matches = _find_stations(context, query_text)

    if not matches:
        await update.message.reply_text(
            "❌ İstasyon bulunamadı. Lütfen kalkış şehrini tekrar yazın. Örnek: Ankara"
        )
        return DEPARTURE

    context.user_data["departure_matches"] = matches
    keyboard = [
        [InlineKeyboardButton(_station_button_text(s), callback_data=f"dep:{i}")]
        for i, s in enumerate(matches)
    ]
    await update.message.reply_text(
        "🔍 Şunları buldum, lütfen doğru istasyonu seçin. Aynı isim varsa ID'ye dikkat et:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return DEPARTURE_SELECT


async def select_departure(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    try:
        index = int(query.data.split(":", 1)[1])
        station = context.user_data["departure_matches"][index]
    except Exception:
        await query.edit_message_text("Seçim okunamadı. Lütfen /start yazarak tekrar başlat.")
        return ConversationHandler.END

    context.user_data["kalkis"] = station
    await query.edit_message_text(
        f"✅ Kalkış onaylandı: {_station_button_text(station)}\n\n"
        "🎯 Lütfen sadece VARIŞ yapacağınız şehri yazın.\n\n"
        "Örnek: Konya veya Gebze"
    )
    return ARRIVAL


async def search_arrival(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query_text = update.message.text.strip()
    matches = _find_stations(context, query_text)

    if not matches:
        await update.message.reply_text("❌ İstasyon bulunamadı. Lütfen varış şehrini tekrar yazın:")
        return ARRIVAL

    context.user_data["arrival_matches"] = matches
    keyboard = [
        [InlineKeyboardButton(_station_button_text(s), callback_data=f"arr:{i}")]
        for i, s in enumerate(matches)
    ]
    await update.message.reply_text(
        "🔍 Şunları buldum, lütfen doğru istasyonu seçin. Aynı isim varsa ID'ye dikkat et:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return ARRIVAL_SELECT


async def select_arrival(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Varış istasyonu seçildikten sonra kabin sınıfı seçimine geçer."""
    query = update.callback_query
    await query.answer()

    try:
        index = int(query.data.split(":", 1)[1])
        station = context.user_data["arrival_matches"][index]
    except Exception:
        await query.edit_message_text("Seçim okunamadı. Lütfen /start yazarak tekrar başlat.")
        return ConversationHandler.END

    context.user_data["varis"] = station
    context.user_data["cabin_secimler"] = []  # sıfırla

    secimler = []
    await query.edit_message_text(
        f"✅ Varış onaylandı: {_station_button_text(station)}\n\n"
        "🪑 Hangi vagon sınıflarını istiyorsunuz?\n"
        "_(Birden fazla seçebilirsiniz, bitince ✔️ Tamam'a basın)_\n\n"
        "Seçilenler: *Henüz seçilmedi*",
        reply_markup=InlineKeyboardMarkup(_cabin_keyboard(secimler)),
        parse_mode="Markdown",
    )
    return CABIN_CLASS


async def select_cabin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Kabin sınıfı toggle/hepsi/tamam işlemleri."""
    query = update.callback_query
    await query.answer()

    print(f"[CABIN] Butona basıldı: {query.data}")
    
    secim = query.data.split(":", 1)[1]
    secimler = context.user_data.get("cabin_secimler", [])

    if secim == "hepsi":
        secimler = list(CABIN_OPTIONS.keys())
        context.user_data["cabin_secimler"] = secimler

    elif secim == "tamam":
        # Hiç seçilmediyse hepsini al
        if not secimler:
            secimler = list(CABIN_OPTIONS.keys())
            context.user_data["cabin_secimler"] = secimler

        # Saat seçimine geç
        secilen_text = ", ".join(CABIN_OPTIONS[k] for k in secimler)
        keyboard = [
            [
                InlineKeyboardButton("08:00 ve Sonrası", callback_data="08:00"),
                InlineKeyboardButton("12:00 ve Sonrası", callback_data="12:00"),
            ],
            [
                InlineKeyboardButton("16:00 ve Sonrası", callback_data="16:00"),
                InlineKeyboardButton("Fark Etmez", callback_data="00:00"),
            ],
        ]
        await query.edit_message_text(
            f"✅ Vagon sınıfları: *{secilen_text}*\n\n⏰ Son olarak saat kısıtlaması seçin:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown",
        )
        return TIME

    else:
        # Toggle: varsa çıkar, yoksa ekle
        if secim in secimler:
            secimler.remove(secim)
        else:
            secimler.append(secim)
        context.user_data["cabin_secimler"] = secimler

    # Menüyü güncel seçimlerle yeniden göster
    secilen_text = ", ".join(CABIN_OPTIONS[k] for k in secimler) if secimler else "Henüz seçilmedi"
    await query.edit_message_text(
        f"🪑 Vagon sınıfı seçin (birden fazla olabilir):\n\nSeçilenler: *{secilen_text}*",
        reply_markup=InlineKeyboardMarkup(_cabin_keyboard(secimler)),
        parse_mode="Markdown",
    )
    return CABIN_CLASS


async def check_ticket_job(context: ContextTypes.DEFAULT_TYPE):
    """Periyodik bilet kontrol görevi."""
    job_data = context.job.data
    chat_id = job_data["chat_id"]
    kalkis = job_data["kalkis"]
    varis = job_data["varis"]

    sonuc = check_train_tickets(
        kalkis_id=kalkis["id"],
        kalkis_name=kalkis["name"],
        varis_id=varis["id"],
        varis_name=varis["name"],
        tcdd_tarih=job_data["tcdd_tarih"],
        hedef_saat=job_data["hedef_saat"],
        kullanici_cinsiyet=job_data["gender"],
        izin_verilen_siniflar=job_data.get("cabin_siniflar"),
    )

    if sonuc["success"] and sonuc["data"]:
        mesaj = (
            "🎉 BOŞ KOLTUK BULUNDU!\n\n"
            f"🚉 {kalkis['name']} ➡️ {varis['name']}\n"
            f"📅 Tarih: {job_data['tcdd_tarih'][:10]}\n\n"
        )
        for tren in sonuc["data"]:
            mesaj += f"🚄 {tren['tren_adi']} | Saat: {tren['saat']} | Boş: {tren['bos_koltuk']}\n"
        mesaj += "\n🔗 Bilet Al: https://ebilet.tcddtasimacilik.gov.tr/"

        try:
            await context.bot.send_message(chat_id=chat_id, text=mesaj)
            context.job.schedule_removal()
        except Exception as e:
            logger.error("Telegram mesajı gönderilemedi: %s", e)

    elif not sonuc["success"]:
        if sonuc["error"] == "auth_error":
            try:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="⚠️ Sistem hatası: TCDD token süresi dolmuş. Görev durduruldu.",
                )
            except Exception:
                pass
            context.job.schedule_removal()
        else:
            logger.warning("Sessiz hata, yeniden denenecek: %s", sonuc["error"])


async def select_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Saat seçimi tamamlandıktan sonra periyodik görevi başlatır."""
    query = update.callback_query
    await query.answer()

    hedef_saat = query.data
    chat_id = query.message.chat_id

    try:
        if context.job_queue is None:
            await query.edit_message_text(
                "JobQueue aktif değil. Şunu kurup tekrar çalıştır:\n"
                "pip install \"python-telegram-bot[job-queue]\""
            )
            return ConversationHandler.END

        await query.edit_message_text(
            "✅ Arama aktif!\n\n"
            f"⏳ Her {CHECK_INTERVAL_SECONDS // 60} dakikada bir kontrol edilecek. "
            "Bilet bulunduğunda sana buradan mesaj atacağım."
        )

        # Varsa eski görevi durdur
        for job in context.job_queue.get_jobs_by_name(f"ticket_{chat_id}"):
            job.schedule_removal()

        context.job_queue.run_repeating(
            check_ticket_job,
            interval=CHECK_INTERVAL_SECONDS,
            first=5,
            data={
                "chat_id": chat_id,
                "kalkis": context.user_data["kalkis"],
                "varis": context.user_data["varis"],
                "tcdd_tarih": context.user_data["tcdd_tarih"],
                "hedef_saat": hedef_saat,
                "gender": context.user_data["gender"],
                "cabin_siniflar": context.user_data.get("cabin_secimler"),
            },
            name=f"ticket_{chat_id}",
        )
    except Exception as e:
        logger.error("Görevi başlatırken hata: %s", e)
        await query.message.reply_text("Sistemde bir hata oluştu, lütfen /start yazarak tekrar deneyin.")

    context.user_data.clear()
    return ConversationHandler.END