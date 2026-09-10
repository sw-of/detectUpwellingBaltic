import os
import json
import requests
from datetime import datetime, timezone

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
    """Fragt DWD-Daten über den reparierten API-Endpunkt ab."""
    # KORREKTUR: Das fehlende /v1/dwd? wurde wieder eingefügt
    url = f"https://open-meteo.com{lat}&longitude={lon}&hourly=windspeed_10m,winddirection_10m&forecast_days=3&past_days=1"
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
        return False, None, "Datenfehler: 'hourly' fehlt im JSON"
        
    hourly = data["hourly"]
    times = hourly.get("time", [])
    speeds = hourly.get("windspeed_10m", [])
    directions = hourly.get("winddirection_10m", [])
    
    if not times or not speeds or not directions:
        return False, None, "Datenfehler: Unvollständige Arrays"

    now_utc = datetime.now(timezone.utc)
    now_index = 0
    min_diff = float('inf')
    
    for idx, t_str in enumerate(times):
        try:
            t_obj = datetime.strptime(t_str, "%Y-%m-%dT%H:%M").replace(tzinfo=timezone.utc)
            diff = abs((t_obj - now_utc).total_seconds())
            if diff < min_diff:
                min_diff = diff
                now_index = idx
        except ValueError:
            continue

    start_window = now_index - 6
    end_window = now_index + 30
    
    if start_window < 0:
        return False, None, f"Fehler: Nicht genügend Vergangenheitsdaten (Start-Index {start_window} negativ)"
    if end_window > len(speeds):
        return False, None, f"Fehler: Nicht genügend Prognosedaten (End-Index {end_window} größer als Array-Länge {len(speeds)})"

    window_speeds = speeds[start_window:end_window]
    window_directions = directions[start_window:end_window]
    window_times = times[start_window:end_window]

    binary_sequence = []
    for s, d in zip(window_speeds, window_directions):
        speed_ms = s / 3.6
        if speed_ms >= config["min_speed_ms"] and config["crit_dir_min"] <= d <= config["crit_dir_max"]:
            binary_sequence.append(1)
        else:
            binary_sequence.append(0)

    past_sequence = binary_sequence[0:6]
    past_net_hours = sum(past_sequence)
    
    if past_net_hours < 4:
         return False, None, f"Ausgeschlossen (Reale Messdaten der letzten 6h unzureichend: Nur {past_net_hours}/6h aktiv)"

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

    total_net_hours = sum(binary_sequence)
    if total_net_hours < 34:
        return False, None, f"Kriterien nicht erfüllt (Gesamtdauer nur {total_net_hours}/36h)"

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
    success_fetches = 0
    
    print(f"Starte strikte 36h-Kontinuitätsprüfung (6h Ist + 30h Prognose) für {len(MONITORED_LOCATIONS)} Orte...\n")
    
    for name, config in MONITORED_LOCATIONS.items():
        raw_data = fetch_and_archive(config["lat"], config["lon"], name)
        
        if raw_data:
            success_fetches += 1
            is_upwelling, info, status_msg = analyze_strict_36h_window(raw_data, config)
            if is_upwelling:
                triggered_locations.append(
                    f"- {name}:\n"
                    f"  ⏱️ Volles 36h-Fenster: {info['start']} bis {info['end']} UTC\n"
                    f"  💨 Kontinuierlicher Wind: {info['net_hours']} von 36 Std. aktiv (Vergangenheit: {info['past_active']}/6h)"
                )
            else:
                print(f"ℹ️ [{name}] {status_msg}")
                
    print("\n------------------ ERGEBNISSE ------------------")
    if success_fetches == 0:
        print("❌ FEHLER: Es konnten von keinem einzigen Ort Daten geladen werden. Bitte API-Endpunkt überprüfen.")
    elif triggered_locations:
        alert_msg = "⚠️ SEHR HOHE UPWELLING-WAHRSCHEINLICHKEIT (STRIKTE KONTINUITÄT ERFÜLLT):\n\n" + "\n".join(triggered_locations)
        print(alert_msg)
    else:
        print("✅ Verbindung stabil. Keine akuten Ereignisse an den 15 überwachten Stationen.")
    print("------------------------------------------------")

if __name__ == "__main__":
    main()
