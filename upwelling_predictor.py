import os
import json
import requests
from datetime import datetime

ATTRIBUTION_NOTICE = """
================================================================================
DATA ATTRIBUTION NOTICE (Open Science Compliance)
- Meteorological Data: © Deutscher Wetterdienst (DWD)
- Oceanographic Service: Provided via Open-Meteo API (Licensed under CC-BY 4.0)
================================================================================
"""

MONITORED_LOCATIONS = {
    "Flensburg": {"lat": 54.79, "lon": 9.44, "crit_dir_min": 140, "crit_dir_max": 220, "min_speed_ms": 6.0},
    "Maasholm": {"lat": 54.68, "lon": 9.99, "crit_dir_min": 130, "crit_dir_max": 180, "min_speed_ms": 6.0},
    "Eckernförde": {"lat": 54.47, "lon": 9.84, "crit_dir_min": 130, "crit_dir_max": 180, "min_speed_ms": 6.0},
    "Kiel": {"lat": 54.32, "lon": 10.14, "crit_dir_min": 140, "crit_dir_max": 200, "min_speed_ms": 6.0},
    "Heiligenhafen": {"lat": 54.37, "lon": 10.98, "crit_dir_min": 90,  "crit_dir_max": 160, "min_speed_ms": 6.0},
    "Travemünde": {"lat": 53.96, "lon": 10.87, "crit_dir_min": 130, "crit_dir_max": 180, "min_speed_ms": 6.0},
    "Wismar": {"lat": 53.90, "lon": 11.46, "crit_dir_min": 230, "crit_dir_max": 290, "min_speed_ms": 6.0},
    "Kühlungsborn": {"lat": 54.15, "lon": 11.75, "crit_dir_min": 240, "crit_dir_max": 290, "min_speed_ms": 6.0},
    "Warnemünde": {"lat": 54.18, "lon": 12.08, "crit_dir_min": 240, "crit_dir_max": 290, "min_speed_ms": 6.0},
    "Graal-Müritz": {"lat": 54.26, "lon": 12.24, "crit_dir_min": 240, "crit_dir_max": 290, "min_speed_ms": 6.0},
    "Zingst": {"lat": 54.43, "lon": 12.69, "crit_dir_min": 240, "crit_dir_max": 290, "min_speed_ms": 6.0},
    "Dranske": {"lat": 54.63, "lon": 13.23, "crit_dir_min": 0,   "crit_dir_max": 70,  "min_speed_ms": 6.0},
    "Sassnitz": {"lat": 54.52, "lon": 13.64, "crit_dir_min": 180, "crit_dir_max": 240, "min_speed_ms": 6.0},
    "Greifswald": {"lat": 54.10, "lon": 13.38, "crit_dir_min": 220, "crit_dir_max": 270, "min_speed_ms": 6.0},
    "Heringsdorf": {"lat": 53.95, "lon": 14.17, "crit_dir_min": 220, "crit_dir_max": 280, "min_speed_ms": 6.0}
}

def fetch_and_archive(lat, lon, location_name):
    url = f"https://open-meteo.com{lat}&longitude={lon}&hourly=windspeed_10m,winddirection_10m&forecast_days=2&past_days=1"
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        data = response.json()
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M")
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

def analyze_strict_36h_window(data, config):
    if not data or "hourly" not in data:
        return False, None, "Datenfehler"
        
    hourly = data["hourly"]
    times = hourly.get("time", [])
    speeds = hourly.get("windspeed_10m", [])
    directions = hourly.get("winddirection_10m", [])
    
    # Bestimmung der aktuellen UTC-Stunde
    current_hour_str = datetime.utcnow().strftime("%Y-%m-%dT%H:00")
    try:
        now_index = times.index(current_hour_str)
    except ValueError:
        now_index = 24  # Standard-Fallback bei 1 Tag Vergangenheit

    # Wir schneiden das feste Fenster aus: 6h Vergangenheit bis 30h Zukunft (= 36 Stunden)
    start_window = now_index - 6
    end_window = now_index + 30
    
    if start_window < 0 or end_window > len(speeds):
        return False, None, "Unzureichender Datenumfang in API-Antwort"

    window_speeds = speeds[start_window:end_window]
    window_directions = directions[start_window:end_window]
    window_times = times[start_window:end_window]

    # 1. Erstelle die stündliche Binärsequenz für das exakte 36h-Fenster
    binary_sequence = []
    for s, d in zip(window_speeds, window_directions):
        speed_ms = s / 3.6
        if speed_ms >= config["min_speed_ms"] and config["crit_dir_min"] <= d <= config["crit_dir_max"]:
            binary_sequence.append(1)
        else:
            binary_sequence.append(0)

    # 2. Strikte Prüfung der ersten 6 Stunden (Vergangenheit, Indizes 0 bis 5)
    past_sequence = binary_sequence[0:6]
    past_net_hours = sum(past_sequence)
    
    # Da die maximale Gesamtlücke im 36h-Fenster nur 2h betragen darf,
    # darf auch in der Vergangenheit bereits maximal 2 Stunden lang kein optimaler Wind gewesen sein.
    if past_net_hours < 4:
         return False, None, f"Ausgeschlossen (Reale Messdaten der letzten 6h unzureichend: Nur {past_net_hours}/6h aktiv)"

    # 3. Prüfung auf maximale zusammenhängende Lücken (max. 2h Lücke am Stück erlaubt)
    gap_counter = 0
    max_gap_found = 0
    for val in binary_sequence:
        if val == 0:
            gap_counter += 1
            if gap_counter > max_gap_found:
                max_gap_found = gap_counter
        else:
            gap_counter = 0

    if max_gap_found > 2:
        return False, None, f"Ausgeschlossen (Windunterbrechung von {max_gap_found}h verletzt die Kontinuität von max. 2h)"

    # 4. Endgültige Netto-Stundenzählung (mindestens 34 von 36 Stunden)
    total_net_hours = sum(binary_sequence)
    if total_net_hours < 34:
        return False, None, f"Kriterien nicht erfüllt (Gesamtdauer nur {total_net_hours}/36h)"

    # Wenn alle Bedingungen erfüllt sind, ist das Upwelling-Ereignis extrem wahrscheinlich
    event_info = {
        "net_hours": total_net_hours,
        "past_active": past_net_hours,
        "start": window_times[0].replace("T", " "),
        "end": window_times[-1].replace("T", " ")
    }
    return True, event_info, "Kriterien perfekt erfüllt"

def main():
    print(ATTRIBUTION_NOTICE)
    triggered_locations = []
    
    print(f"Starte strikte 36h-Kontinuitätsprüfung (6h Ist + 30h Prognose) für {len(MONITORED_LOCATIONS)} Orte...\n")
    
    for name, config in MONITORED_LOCATIONS.items():
        raw_data = fetch_and_archive(config["lat"], config["lon"], name)
        
        if raw_data:
            is_upwelling, info, status_msg = analyze_strict_36h_window(raw_data, config)
            if is_upwelling:
                triggered_locations.append(
                    f"- {name}:\n"
                    f"  ⏱️ Volles 36h-Fenster: {info['start']} bis {info['end']} UTC\n"
                    f"  💨 Kontinuierlicher Wind: {info['net_hours']} von 36 Std. aktiv (Vergangenheit: {info['past_active']}/6h)"
                )
            else:
                # Zeige im Serverlog detailliert an, warum Stationen aussortiert wurden
                print(f"ℹ️ [{name}] {status_msg}")
                
    print("\n------------------ ERGEBNISSE ------------------")
    if triggered_locations:
        alert_msg = "⚠️ SEHR HOHE UPWELLING-WAHRSCHEINLICHKEIT (STRIKTE KONTINUITÄT ERFÜLLT):\n\n" + "\n".join(triggered_locations)
        print(alert_msg)
    else:
        print("✅ Keine akuten Ereignisse. Die extrem strikten Kontinuitätskriterien wurden an keinem Ort vollständig erreicht.")
    print("------------------------------------------------")

if __name__ == "__main__":
    main()
