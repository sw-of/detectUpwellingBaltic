import os
import json
import requests
from datetime import datetime, timezone

ATTRIBUTION_NOTICE = """
================================================================================
DATA ATTRIBUTION NOTICE (Open Science Compliance)
- Meteorological Data: © Deutscher Wetterdienst (DWD)
- Oceanographic Model: ICON-EU via Open-Meteo API (Licensed under CC-BY 4.0)
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

def get_archive_dir(location_name):
    """Generiert den sicheren Ordnerpfad für eine Station."""
    safe_name = location_name.lower().replace("ü", "ue").replace("ö", "oe").replace("ä", "ae").replace(" ", "_").replace("/", "-")
    return os.path.join("archive", safe_name)

def fetch_and_archive_json(lat, lon, archive_dir):
    """Fragt DWD-Daten ab und speichert die rohe JSON-Datei."""
    # REPARIERT: /v1/forecast? wurde korrekt eingesetzt
    url = f"https://open-meteo.com{lat}&longitude={lon}&hourly=windspeed_10m,winddirection_10m&models=dwd_icon&forecast_days=3&past_days=1"
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        data = response.json()
        
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
        os.makedirs(archive_dir, exist_ok=True)
        
        file_path = os.path.join(archive_dir, f"forecast_{timestamp}.json")
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
            
        return data
    except Exception as e:
        print(f"❌ Fehler beim Datenabruf: {e}")
        return None

def write_to_tabular_log(archive_dir, is_upwelling, net_hours, status_msg):
    """Schreibt oder erweitert die tabellarische status_log.csv im Ortsordner."""
    log_path = os.path.join(archive_dir, "status_log.csv")
    timestamp_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    
    decision = "Ja" if is_upwelling else "Nein"
    clean_msg = status_msg.replace(";", ",").replace("\n", " ")
    log_line = f"{timestamp_utc};{decision};{net_hours};{clean_msg}\n"
    
    file_exists = os.path.exists(log_path)
    
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            if not file_exists:
                f.write("timestamp_utc;upwelling_predicted;net_wind_hours;details\n")
            f.write(log_line)
    except Exception as e:
        print(f"❌ Fehler beim Schreiben des tabellarischen Logs: {e}")

def analyze_strict_36h_window(data, config):
    if not data or "hourly" not in data:
        return False, 0, "Datenfehler: 'hourly' fehlt im JSON"
        
    hourly = data["hourly"]
    times = hourly.get("time", [])
    speeds = hourly.get("windspeed_10m_dwd_icon", hourly.get("windspeed_10m", []))
    directions = hourly.get("winddirection_10m_dwd_icon", hourly.get("winddirection_10m", []))
    
    if not times or not speeds or not directions:
        return False, 0, "Datenfehler: Unvollständige Arrays"

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
    
    if start_window < 0 or end_window > len(speeds):
        return False, 0, f"Fehler: Zeitgrenzen überschritten (Index {now_index})"

    window_speeds = speeds[start_window:end_window]
    window_directions = directions[start_window:end_window]
    window_times = times[start_window:end_window]

    binary_sequence = []
    for s, d in zip(window_speeds, window_directions):
        if s is None or d is None:
            binary_sequence.append(0)
            continue
        speed_ms = s / 3.6
        if speed_ms >= config["min_speed_ms"] and config["crit_dir_min"] <= d <= config["crit_dir_max"]:
            binary_sequence.append(1)
        else:
            binary_sequence.append(0)

    past_sequence = binary_sequence[0:6]
    past_net_hours = sum(past_sequence)
    
    if past_net_hours < 4:
         return False, past_net_hours, f"Ausgeschlossen (Küstenvorgeschichte unzureichend: Nur {past_net_hours}/6h aktiv)"

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
        return False, sum(binary_sequence), f"Ausgeschlossen (Windunterbrechung von {max_gap_found}h verletzt die Kontinuität)"

    total_net_hours = sum(binary_sequence)
    if total_net_hours < 34:
        return False, total_net_hours, f"Kriterien nicht erfüllt (Gesamtdauer nur {total_net_hours}/36h)"

    return True, total_net_hours, f"Kriterien perfekt erfüllt ({total_net_hours}/36h aktiv)"

def main():
    print(ATTRIBUTION_NOTICE)
    triggered_locations = []
    success_fetches = 0
    
    print(f"Starte 36h-Prüfung und tabellarische Archivierung für {len(MONITORED_LOCATIONS)} Orte...\n")
    
    for name, config in MONITORED_LOCATIONS.items():
        archive_dir = get_archive_dir(name)
        raw_data = fetch_and_archive_json(config["lat"], config["lon"], archive_dir)
        
        if raw_data:
            success_fetches += 1
            is_upwelling, net_hours, status_msg = analyze_strict_36h_window(raw_data, config)
            
            write_to_tabular_log(archive_dir, is_upwelling, net_hours, status_msg)
            
            if is_upwelling:
                triggered_locations.append(f"- {name}: {status_msg}")
            else:
                print(f"ℹ️ [{name}] {status_msg}")
                
    print("\n------------------ ERGEBNISSE ------------------")
    if success_fetches == 0:
        print("❌ FEHLER: Keine Daten geladen.")
    elif triggered_locations:
        alert_msg = "⚠️ SEHR HOHE UPWELLING-WAHRSCHEINLICHKEIT:\n\n" + "\n".join(triggered_locations)
        print(alert_msg)
    else:
        print("✅ Verbindung stabil. Tabellarische Status-Logs aktualisiert. Keine akuten Ereignisse.")
    print("------------------------------------------------")

if __name__ == "__main__":
    main()
