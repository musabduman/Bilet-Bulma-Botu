# main.py
import logging
import os
from dotenv import load_dotenv

from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)

from config import (
    ARRIVAL,
    ARRIVAL_SELECT,
    CABIN_CLASS,        # ← eklendi
    DATE,
    DEPARTURE,
    DEPARTURE_SELECT,
    GENDER,
    STATION_MAP,
    TIME,
    TRANSPORT,
)
from handlers import (
    search_arrival,
    search_departure,
    select_arrival,
    select_cabin,       # ← eklendi
    select_date,
    select_departure,
    select_gender,
    select_time,
    select_transport,
    start,
)
from tcdd_api import get_all_stations

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def normalize_station_source(source):
    """API veya config fallback verisini duplicate istasyonları ezmeden listeye çevirir."""
    if not source:
        return []

    if isinstance(source, list):
        stations = []
        for s in source:
            if not isinstance(s, dict):
                continue
            station_id = s.get("id")
            station_name = s.get("name")
            if station_id is None or not station_name:
                continue
            stations.append({"id": station_id, "name": str(station_name).upper()})
        return stations

    if isinstance(source, dict):
        stations = []
        for key, value in source.items():
            if isinstance(value, dict):
                station_id = value.get("id")
                station_name = value.get("name") or key
            else:
                station_id = None
                station_name = key

            if station_id is None or not station_name:
                continue

            stations.append({"id": station_id, "name": str(station_name).upper()})
        return stations

    return []


def main():
    application = (
        Application.builder()
        .token(TELEGRAM_TOKEN)
        .connect_timeout(30.0)
        .read_timeout(30.0)
        .write_timeout(30.0)
        .pool_timeout(30.0)
        .build()
    )

    stations = get_all_stations()
    station_list = normalize_station_source(stations)

    if not station_list:
        logger.warning("TCDD istasyon listesi alınamadı. Config içindeki STATION_MAP kullanılacak.")
        station_list = normalize_station_source(STATION_MAP)

    if not station_list:
        logger.error("Hiç istasyon yüklenemedi. Bot çalışır ama istasyon araması sonuç vermeyebilir.")

    application.bot_data["station_list"] = station_list

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            GENDER:           [CallbackQueryHandler(select_gender)],
            TRANSPORT:        [CallbackQueryHandler(select_transport)],
            DATE:             [CallbackQueryHandler(select_date)],
            DEPARTURE:        [MessageHandler(filters.TEXT & ~filters.COMMAND, search_departure)],
            DEPARTURE_SELECT: [CallbackQueryHandler(select_departure, pattern=r"^dep:\d+$")],
            ARRIVAL:          [MessageHandler(filters.TEXT & ~filters.COMMAND, search_arrival)],
            ARRIVAL_SELECT:   [CallbackQueryHandler(select_arrival, pattern=r"^arr:\d+$")],
            CABIN_CLASS:      [CallbackQueryHandler(select_cabin, pattern=r"^cabin:")],  # ← eklendi
            TIME:             [CallbackQueryHandler(select_time)],
        },
        fallbacks=[CommandHandler("start", start)],
    )

    application.add_handler(conv_handler)

    print("🚀 Bot başarıyla başlatıldı ve dinleniyor...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()