# tcdd_api.py
import requests
import logging
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo
from config import HEADERS

logger = logging.getLogger(__name__)

ISTANBUL_TZ = ZoneInfo("Europe/Istanbul")
TCDD_AVAILABILITY_URL = (
    "https://web-api-prod-ytp.tcddtasimacilik.gov.tr/tms/train/"
    "train-availability?environment=dev&userId=1"
)
TCDD_STATIONS_URL = "https://web-api-prod-ytp.tcddtasimacilik.gov.tr/tms/train/station/all"

def _headers():
    """Config'deki tokenları bozmadan web sitesinin beklediği temel headerları tamamlar."""
    headers = dict(HEADERS or {})
    headers.setdefault("Accept", "application/json, text/plain, */*")
    headers.setdefault("Accept-Language", "tr")
    headers.setdefault("Content-Type", "application/json")
    headers.setdefault("Origin", "https://ebilet.tcddtasimacilik.gov.tr")
    headers.setdefault("Sec-Fetch-Dest", "empty")
    headers.setdefault("Sec-Fetch-Mode", "cors")
    headers.setdefault("Sec-Fetch-Site", "same-site")
    headers.setdefault("unit-id", "3895")
    headers.setdefault(
        "User-Agent",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/148.0.0.0 Safari/537.36",
    )
    return headers


def get_all_stations():
    """
    TCDD'den tüm istasyonları çeker.

    Eski sürümde dict key olarak sadece istasyon adı kullanılıyordu. Aynı isimli istasyonlar
    birbirini eziyordu. Örnek: KONYA için 61 ve 796 gibi farklı ID'ler olabiliyor.
    Bu yüzden artık liste dönüyoruz ve duplicate istasyonları koruyoruz.
    """
    try:
        r = requests.get(TCDD_STATIONS_URL, headers=_headers(), timeout=20)
        if r.status_code != 200:
            logger.error("İstasyon listesi alınamadı. Status: %s | Body: %s", r.status_code, r.text[:300])
            return None

        stations = r.json()
        station_list = []
        seen = set()

        for s in stations:
            station_id = s.get("id")
            station_name = s.get("name")
            if station_id is None or not station_name:
                continue

            key = (int(station_id), str(station_name).upper())
            if key in seen:
                continue
            seen.add(key)

            station_list.append({"id": int(station_id), "name": str(station_name).upper()})

        return station_list

    except Exception as e:
        logger.error("İstasyon listesi alınamadı: %s", e)
        return None


def _parse_selected_date(tcdd_tarih):
    """Botun tuttuğu tarihi Europe/Istanbul yerel tarihi olarak parse eder."""
    raw = str(tcdd_tarih).strip()

    for fmt in ("%d-%m-%Y %H:%M:%S", "%d-%m-%Y"):
        try:
            parsed = datetime.strptime(raw, fmt)
            return parsed.date()
        except ValueError:
            continue

    raise ValueError(f"Desteklenmeyen tarih formatı: {tcdd_tarih}")


def _format_date_for_tcdd(tcdd_tarih):
    """
    Web sitesinin isteğine benzer tarih üretir.

    TCDD web tarafı Türkiye'de seçilen günün 00:00 saatini UTC karşılığı gibi gönderiyor.
    Örnek: 24-05-2026 seçilince API tarafına çoğunlukla 23-05-2026 21:00:00 gider.
    """
    selected_date = _parse_selected_date(tcdd_tarih)

    local_midnight = datetime.combine(selected_date, time(0, 0, 0), tzinfo=ISTANBUL_TZ)
    api_dt = local_midnight.astimezone(timezone.utc)

    return api_dt.strftime("%d-%m-%Y %H:%M:%S"), selected_date


def _extract_trains(response_json):
    """trainLegs içindeki tüm trains listelerini güvenli şekilde toplar."""
    trains = []
    for leg in response_json.get("trainLegs", []) or []:
        for availability in leg.get("trainAvailabilities", []) or []:
            trains.extend(availability.get("trains", []) or [])
    return trains


def _safe_int(value, default=0):
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _sum_train_availability(train, kullanici_cinsiyet):
    """YHT ve diğer tren veri yapılarına göre boş koltuk sayısını hesaplar."""
    toplam_bos = 0

    # YHT / vagon detaylı yapı
    train_cars = train.get("trainCars", []) or []
    if train_cars:
        for car in train_cars:
            for avail in car.get("availabilities", []) or []:
                adet = _safe_int(avail.get("availability"), 0)
                if adet <= 0:
                    continue

                g_code_str = str(avail.get("gender", "0"))

                if kullanici_cinsiyet == "Erkek" and g_code_str in {"1", "3", "0", "None", ""}:
                    toplam_bos += adet
                elif kullanici_cinsiyet == "Kadin" and g_code_str in {"2", "3", "0", "None", ""}:
                    toplam_bos += adet
        return toplam_bos

    # Anahat / ekspres tarzı yapı
    for cabin in train.get("cabinClassAvailabilities", []) or []:
        toplam_bos += _safe_int(cabin.get("availabilityCount"), 0)
        toplam_bos += _safe_int(cabin.get("availableSeatCount"), 0)

    return toplam_bos

def check_train_tickets(kalkis_id, kalkis_name, varis_id, varis_name, tcdd_tarih, hedef_saat, kullanici_cinsiyet):
    """TCDD API'sine istek atar ve uygun koltukları döner."""
    try:
        api_tarih, selected_date = _format_date_for_tcdd(tcdd_tarih)
        bugun_tr = datetime.now(ISTANBUL_TZ).date()

        if selected_date < bugun_tr:
            return {
                "success": False,
                "data": None,
                "error": f"Geçmiş tarih seçilmiş: {selected_date.strftime('%d-%m-%Y')}",
            }

    except Exception as e:
        return {
            "success": False,
            "data": None,
            "error": f"Tarih formatı çözülemedi: {tcdd_tarih} | {e}",
        }
    if varis_name and varis_name.upper().strip() == "KONYA":
        if int(varis_id) != 796:
            print(f"[X-RAY FIX] KONYA ID düzeltildi: {varis_id} -> 796")
            varis_id = 796
    # Web sitesinden alınan çalışan cURL'e göre body sade tutuldu.
    # Özellikle searchType kaldırıldı ve blTrainTypes TURISTIK_TREN yapıldı.
    body = {
        "searchRoutes": [
            {
                "departureStationId": int(kalkis_id),
                "departureStationName": str(kalkis_name).upper(),
                "arrivalStationId": int(varis_id),
                "arrivalStationName": str(varis_name).upper(),
                "departureDate": api_tarih,
            }
        ],
        "passengerTypeCounts": [{"id": 0, "count": 1}],
        "searchReservation": False,
        "blTrainTypes": ["TURISTIK_TREN"],
    }

    try:
        r = requests.post(TCDD_AVAILABILITY_URL, headers=_headers(), json=body, timeout=20)

        print(f"\n[X-RAY] TCDD API İstek Atıldı. Durum Kodu: {r.status_code}")
        print("[X-RAY BODY]", body)
        print("[X-RAY RESPONSE]", r.text[:1000])

        if r.status_code == 200:
            bulunan_trenler = []
            response_json = r.json()
            trains = _extract_trains(response_json)

            print(f"[X-RAY] Toplam {len(trains)} adet tren rotada listelendi.")

            for train in trains:
                segments = train.get("segments", []) or []
                if not segments:
                    continue

                dep_ms = segments[0].get("departureTime", 0)
                if not dep_ms:
                    continue

                saat_str = (
                    datetime.fromtimestamp(dep_ms / 1000, tz=timezone.utc)
                    .astimezone(ISTANBUL_TZ)
                    .strftime("%H:%M")
                )

                if hedef_saat and saat_str < hedef_saat:
                    continue

                train_name = train.get("name") or train.get("trainName") or "Tren"
                toplam_bos = _sum_train_availability(train, kullanici_cinsiyet)

                print(f"👉 [X-RAY TREN] {saat_str} - {train_name} | Bulunan Uygun Koltuk: {toplam_bos}")

                if toplam_bos > 0:
                    bulunan_trenler.append(
                        {
                            "saat": saat_str,
                            "tren_adi": train_name,
                            "bos_koltuk": toplam_bos,
                        }
                    )

            return {"success": True, "data": bulunan_trenler, "error": None}

        if r.status_code == 401:
            return {"success": False, "data": None, "error": "auth_error"}

        if r.status_code == 403:
            return {
                "success": False,
                "data": None,
                "error": "403 Forbidden: TCDD isteği engelledi. Endpoint veya header/token eksik olabilir.",
            }

        if r.status_code == 400:
            try:
                err = r.json()
                if err.get("code") == 604:
                    # Teknik hata değil; bu kriterlerle API sefer döndürmedi.
                    return {"success": True, "data": [], "error": None}
            except Exception:
                pass

            return {
                "success": False,
                "data": None,
                "error": f"API Hatası: 400 | {r.text[:300]}",
            }

        return {
            "success": False,
            "data": None,
            "error": f"API Hatası: {r.status_code} | {r.text[:300]}",
        }

    except requests.exceptions.Timeout:
        return {"success": False, "data": None, "error": "TCDD isteği zaman aşımına uğradı"}
    except requests.exceptions.RequestException as e:
        return {"success": False, "data": None, "error": f"TCDD bağlantı hatası: {e}"}
    except Exception as e:
        print(f"[X-RAY CRITICAL ERROR] İstek sırasında hata oluştu: {e}")
        return {"success": False, "data": None, "error": str(e)}
