# config.py
import os
from dotenv import load_dotenv

load_dotenv()

STATION_MAP = {
    "Ankara Gar": {"id": 98, "name": "ANKARA GAR"},
    "Ankara (Eryaman YHT)": {"id": 97, "name": "ERYAMAN YHT"},
    "Gebze": {"id": 20, "name": "GEBZE"},
    "İstanbul (Söğütlüçeşme)": {"id": 12, "name": "SÖĞÜTLÜÇEŞME"},
    "İstanbul (Pendik)": {"id": 13, "name": "PENDİK"},
    "İstanbul (Halkalı)": {"id": 11, "name": "HALKALI"},
    "Eskişehir": {"id": 44, "name": "ESKİŞEHİR"},
    "Konya": {"id": 61, "name": "KONYA"},
    "Karaman": {"id": 62, "name": "KARAMAN"},
    "Sivas": {"id": 110, "name": "SİVAS"}
}

HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "tr",
    "Authorization": os.getenv("TOKEN"), # Yukarıda SITE_AUTH_TOKEN olarak tanımladığımız uzun token
    "Content-Type": "application/json",
    "Origin": "https://ebilet.tcddtasimacilik.gov.tr", # "Orgin" düzeltildi
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    # İçerideki çift tırnakların karışmaması için dışarıyı tek tırnak (') ile sardık:
    "Sec-Ch-Ua": '"Chromium";v="148", "Google Chrome";v="148", "Not/A)Brand";v="99"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"', # Tarayıcılar platformu da çift tırnakla yollar
    "unit-id": "3895"
}

# Aşamalar (States)
GENDER, TRANSPORT, DATE, DEPARTURE, DEPARTURE_SELECT, ARRIVAL, ARRIVAL_SELECT, TIME,CABIN_CLASS = range(9)