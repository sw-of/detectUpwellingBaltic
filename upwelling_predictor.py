import os
import json
import requests
from datetime import datetime

# Wissenschaftliche Quellenangaben für das Log-Protokoll
ATTRIBUTION_NOTICE = """
================================================================================
DATA ATTRIBUTION NOTICE (Open Science Compliance)
- Meteorological Data: © Deutscher Wetterdienst (DWD)
- Oceanographic Service: Provided via Open-Meteo API (Licensed under CC-BY 4.0)
================================================================================
"""

# Erweiterte Konfiguration der 15 Überwachungspunkte an der deutschen Ostseeküste
MONITORED_LOCATIONS = {
    # --- SCHLESWIG-HOLSTEIN ---
    "Flensburg": {
        "lat": 54.79, "lon": 9.44,
        "crit_dir_min": 140, "crit_dir_max": 220,  # Süd-Südost bis Südwest (Förden-Sonderlage)
        "min_speed_ms": 6.0
    },
    "Maasholm": {
        "lat": 54.68, "lon": 9.99,
        "crit_dir_min": 130, "crit_dir_max": 180,  # Südost bis Süd
        "min_speed_ms": 6.0
    },
    "Eckernförde": {
        "lat": 54.47, "lon": 9.84,
        "crit_dir_min": 130, "crit_dir_max": 180,  # Südost bis Süd (Buchtlage)
        "min_speed_ms": 6.0
    },
    "Kiel": {
        "lat": 54.32, "lon": 10.14,
        "crit_dir_min": 140, "crit_dir_max": 200,  # Südost bis Süd-Südwest
        "min_speed_ms": 6.0
    },
    "Heiligenhafen": {
        "lat": 54.37, "lon": 10.98,
        "crit_dir_min": 90,  "crit_dir_max": 160,  # Ost bis Süd-Südost
        "min_speed_ms": 6.0
    },
    "Travemünde": {
        "lat": 53.96, "lon": 10.87,
        "crit_dir_min": 130, "crit_dir_max": 180,  # Südost bis Süd (Lübecker Bucht)
        "min_speed_ms": 6.0
    },
    # --- MECKLENBURG-VORPOMMERN ---
    "Wismar": {
        "lat": 53.90, "lon": 11.46,
        "crit_dir_min": 230, "crit_dir_max": 290,  # Südwest bis West-Nordwest
        "min_speed_ms": 6.0
    },
    "Kühlungsborn": {
        "lat": 54.15, "lon": 11.75,
        "crit_dir_min": 240, "crit_dir_max": 290,  # Westwindzone
        "min_speed_ms": 6.0
    },
    "Warnemünde": {
        "lat": 54.18, "lon": 12.08,
        "crit_dir_min": 240, "crit_dir_max": 290,  # Westwindzone
        "min_speed_ms": 6.0
    },
    "Graal-Müritz": {
        "lat": 54.26, "lon": 12.24,
        "crit_dir_min": 240, "crit_dir_max": 290,  # Westwindzone
        "min_speed_ms": 6.0
    },
    "Zingst": {
        "lat": 54.43, "lon": 12.69,
        "crit_dir_min": 240, "crit_dir_max": 290,  # Westwindzone (Darß/Zingst)
        "min_speed_ms": 6.0
    },
    "Dranske": {
        "lat": 54.63, "lon": 13.23,
        "crit_dir_min": 0,   "crit_dir_max": 70,   # Nord bis Nordost (Westküste Wittow/Rügen)
        "min_speed_ms": 6.0
    },
    "Sassnitz": {
        "lat": 54.52, "lon": 13.64,
        "crit_dir_min": 180, "crit_dir_max": 240,  # Süd bis Südwest (Ostküste Jasmund)
        "min_speed_ms": 6.0
    },
    "Greifswald": {
        "lat": 54.10, "lon": 13.38,
        "crit_dir_min": 220, "crit_dir_max": 270,  # Südwest bis West (Boddenrand)
        "min_speed_ms": 6.0
    },
    "Heringsdorf": {
        "lat": 53.95, "lon": 14.17,
        "crit_dir_min": 220, "crit_dir_max": 280,  # Südwest bis West (Usedom)
        "min_speed_ms": 6.0
    }
}

def fetch_and_archive(lat, lon, location_name):
    """Fragt die DWD-Daten ab und archiviert die Rohdaten als JSON."""
    url = f"https://open-meteo.com{lat}&longitude={lon}&hourly=windspeed_10m,winddirection_10m&forecast_days=3"
    
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        data = response.json()
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M")
        
        # Sicherer Ordnername ohne Umlaute/Sonderzeichen
        safe_name = location_name.lower().replace("ü", "ue").replace("ö", "oe").replace("ä", "ae").replace(" ", "_").replace("/", "-")
        archive_dir = os.path.join("archive", safe_name)
        os.makedirs(archive_dir, exist_ok=True)
        
        file_path = os.path.join(archive_dir, f"forecast_{timestamp}.json")
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
            
        return data
        
    except Exception as e:
        print(f"❌ Fehler beim Datenabruf für {location_name}: {e}")
        return None

def analyze_upwelling(data, config):
    """Prüft, ob in den nächsten 24 Stunden anhaltender Upwelling-Wind weht."""
    if not data or "hourly" not in data:
        return False, 0
        
    hourly_data = data["hourly"]
    speeds = hourly_data.get("windspeed_10m", [])
    directions = hourly_data.get("winddirection_10m", [])
    
    hours_to_check = min(24, len(speeds))
    matching_hours = 0
    
    for i in range(hours_to_check):
        speed_ms = speeds[i] / 3.6  # km/h -> m/s
        direction = directions[i]
        
        if speed_ms >= config["min_speed_ms"] and config["crit_dir_min"] <= direction <= config["crit_dir_max"]:
            matching_hours += 1
            
    # Mindestens 12 von 24 Stunden müssen dem Kriterium entsprechen
    is_probable = matching_hours >= 12
    return is_probable, matching_hours

def main():
    print(ATTRIBUTION_NOTICE)
    triggered_locations = []
    
    print(f"Starte Analyse für {len(MONITORED_LOCATIONS)} Stationen entlang der Ostseeküste...\n")
    
    for name, config in MONITORED_LOCATIONS.items():
        raw_data = fetch_and_archive(config["lat"], config["lon"], name)
        
        if raw_data:
            is_upwelling, hours = analyze_upwelling(raw_data, config)
            if is_upwelling:
                triggered_locations.append(f"- {name}: {hours} Std. Upwelling-Wind in den nächsten 24 Std.")
                
    print("\n------------------ ERGEBNISSE ------------------")
    if triggered_locations:
        alert_msg = "⚠️ HOHES UPWELLING-POTENZIAL ERKANNT!\n\n" + "\n".join(triggered_locations)
        print(alert_msg)
    else:
        print("✅ Keine akuten Upwelling-Bedingungen an den überwachten Abschnitten erkannt.")
    print("------------------------------------------------")

if __name__ == "__main__":
    main()
