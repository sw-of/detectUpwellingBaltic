import os
import json
import requests
from datetime import datetime, timezone, timedelta

ATTRIBUTION_NOTICE = """
================================================================================
DATA ATTRIBUTION NOTICE (Open Science Compliance)
- Meteorological Data: © Deutscher Wetterdienst (DWD)
- Oceanographic Model: ICON-EU via Open-Meteo API (Licensed under CC-BY 4.0)
================================================================================
"""

# ==============================================================================
# DYNAMISCHE PARAMETER (Wissenschaftliche Konfiguration)
# ==============================================================================
NTFY_TOPIC = "upwellingWarning_HyFiVeBaltic"
NTFY_LEVEL_ROUTINE = "low"
NTFY_LEVEL_REVOKE = "default"

# Mapping der 4 neuen Alarmstufen auf ntfy-Prioritäten
NTFY_LEVELS = {
    "Stufe 1 (Fernprognose)": "default",      # ntfy default (3)
    "Stufe 2 (Nahe Prognose)": "high",        # ntfy high (4)
    "Stufe 3 (Akute Warnung)": "high",        # ntfy high (4)
    "Stufe 4 (Bestätigt/Messdaten)": "max"    # ntfy max (5)
}

# 1. Zeiträume für das gleitende Analysefenster
HOURS_PAST = 6                 # Historische Betrachtung vor dem Fenster-Start
HOURS_WINDOW_SIZE = 36         # Feste Größe des zu bewertenden Upwelling-Fensters
FORECAST_DAYS_API = 4          # 4 Tage (96h) vorausschauende Prädiktion

# 2. Globale Kriterien für optimalen Upwelling-Wind
MIN_WIND_SPEED_MS = 6.0        # Schwellenwert für Transport-Aktivität
REQUIRED_NET_HOURS = 34        # Mindestanzahl aktiver Stunden im 36h-Fenster

# 3. Getrennte Parameter für Kontinitätsunterbrechungen (Gaps)
ALLOWED_MAX_FLAUTE_HOURS = 3   # Wie lange (Stunden) darf eine Flaute maximal anstehen?
ALLOWED_MAX_DIRECTION_GAP_HOURS = 1 # Wie lange (Stunden) darf ein Gegenwind maximal anstehen?

# Ab wann gilt ein Wind physikalisch als absolute Flaute?
FLAUTE_SPEED_MS = 4.0          

# Richtungsabweichung: Toleranz in Grad außerhalb des kritischen Fensters
REVOKE_DIRECTION_MARGIN_DEG = 10 

# Maximale Abweichung (Alter) der berechneten Basiszeit zur Echtzeit,
# bevor die Kette abgebrochen und auf die Gegenwart synchronisiert wird.
MAX_BASE_TIME_AGE_HOURS = 12
# ==============================================================================

MONITORED_LOCATIONS = {
    "Flensburg": {"lat": 54.79, "lon": 9.44, "crit_dir_min": 140, "crit_dir_max": 220, "min_speed_ms": MIN_WIND_SPEED_MS},
    "Maasholm": {"lat": 54.68, "lon": 9.99, "crit_dir_min": 130, "crit_dir_max": 180, "min_speed_ms": MIN_WIND_SPEED_MS},
    "Eckernförde": {"lat": 54.47, "lon": 9.84, "crit_dir_min": 130, "crit_dir_max": 180, "min_speed_ms": MIN_WIND_SPEED_MS},
    "Kiel": {"lat": 54.32, "lon": 10.14, "crit_dir_min": 140, "crit_dir_max": 200, "min_speed_ms": MIN_WIND_SPEED_MS},
    "Heiligenhafen": {"lat": 54.37, "lon": 10.98, "crit_dir_min": 90,  "crit_dir_max": 160, "min_speed_ms": MIN_WIND_SPEED_MS},
    "Travemünde": {"lat": 53.96, "lon": 10.87, "crit_dir_min": 130, "crit_dir_max": 180, "min_speed_ms": MIN_WIND_SPEED_MS},
    "Wismar": {"lat": 53.90, "lon": 11.46, "crit_dir_min": 230, "crit_dir_max": 290, "min_speed_ms": MIN_WIND_SPEED_MS},
    "Kühlungsborn": {"lat": 54.15, "lon": 11.75, "crit_dir_min": 240, "crit_dir_max": 290, "min_speed_ms": MIN_WIND_SPEED_MS},
    "Warnemünde": {"lat": 54.18, "lon": 12.08, "crit_dir_min": 240, "crit_dir_max": 290, "min_speed_ms": MIN_WIND_SPEED_MS},
    "Graal-Müritz": {"lat": 54.26, "lon": 12.24, "crit_dir_min": 240, "crit_dir_max": 290, "min_speed_ms": MIN_WIND_SPEED_MS},
    "Zingst": {"lat": 54.43, "lon": 12.69, "crit_dir_min": 240, "crit_dir_max": 290, "min_speed_ms": MIN_WIND_SPEED_MS},
    "Dranske": {"lat": 54.63, "lon": 13.23, "crit_dir_min": 0,   "crit_dir_max": 70,  "min_speed_ms": MIN_WIND_SPEED_MS},
    "Sassnitz": {"lat": 54.52, "lon": 13.64, "crit_dir_min": 180, "crit_dir_max": 240, "min_speed_ms": MIN_WIND_SPEED_MS},
    "Greifswald": {"lat": 54.10, "lon": 13.38, "crit_dir_min": 220, "crit_dir_max": 270, "min_speed_ms": MIN_WIND_SPEED_MS},
    "Heringsdorf": {"lat": 53.95, "lon": 14.17, "crit_dir_min": 220, "crit_dir_max": 280, "min_speed_ms": MIN_WIND_SPEED_MS}
}

def send_ntfy_notification(message, priority="default", title="Upwelling Predictor"):
    if not NTFY_TOPIC:
        return
    url = f"https://ntfy.sh/{NTFY_TOPIC}"
    headers = {
        "Title": title,
        "Priority": priority,
        "X-Tags": "ocean" if priority in ["high", "max"] else "bar_chart"
    }
    try:
        requests.post(url, data=message.encode('utf-8'), headers=headers, timeout=10)
    except Exception as e:
        print(f"❌ ntfy-Fehler: {e}")

def get_archive_dir(location_name):
    safe_name = location_name.lower().replace("ü", "ue").replace("ö", "oe").replace("ä", "ae").replace(" ", "_").replace("/", "-")
    return os.path.join("archive", safe_name)

def fetch_all_batch():
    """Holt alle Wetterdaten über die korrekte Basis-URL im Batch-Verfahren."""
    base_url = "https://open-meteo.com"
    latitudes = [str(config["lat"]) for config in MONITORED_LOCATIONS.values()]
    longitudes = [str(config["lon"]) for config in MONITORED_LOCATIONS.values()]
    api_params = {
        "latitude": ",".join(latitudes), "longitude": ",".join(longitudes),
        "hourly": "windspeed_10m,winddirection_10m", "models": "dwd_icon",
        "forecast_days": FORECAST_DAYS_API, "past_days": 1
    }
    try:
        response = requests.get(base_url, params=api_params, timeout=25)
        response.raise_for_status()
        results = response.json()
        return results if isinstance(results, list) else [results]
    except Exception as e:
        print(f"❌ API-Fehler: {e}")
        return None

def write_to_tabular_log(archive_dir, is_upwelling, net_hours, status_msg):
    log_path = os.path.join(archive_dir, "status_log.csv")
    timestamp_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    decision = "Ja" if is_upwelling else "Nein"
    clean_msg = status_msg.replace('"', '""')
    log_line = f'{timestamp_utc},{decision},{net_hours},"{clean_msg}"\n'
    file_exists = os.path.exists(log_path)
    with open(log_path, "a", encoding="utf-8") as f:
        if not file_exists:
            f.write("timestamp_utc,upwelling_predicted,net_wind_hours,details\n")
        f.write(log_line)

def check_for_revocation(archive_dir):
    log_path = os.path.join(archive_dir, "status_log.csv")
    if not os.path.exists(log_path):
        return False
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f.readlines() if line.strip()]
            if len(lines) < 2:
                return False
            last_line = lines[-1].split(",")
            if len(last_line) >= 2:
                return last_line[1] == "Ja"
    except Exception:
        return False
    return False

def get_next_raster_base_time(log_path="upwellingWarning.csv"):
    """
    Versucht, die letzte Basiszeit aus der globalen CSV zu lesen und 6 Stunden aufzuaddieren.
    Inklusive Sicherheitscheck gegen veraltete Ketten-Stände.
    """
    now_utc = datetime.now(timezone.utc)

    # 1. VERSUCH: Auslesen aus der globalen upwellingWarning.csv
    if os.path.exists(log_path):
        try:
            with open(log_path, "r", encoding="utf-8") as f:
                lines = [line.strip() for line in f.readlines() if line.strip()]
                if len(lines) >= 2:
                    last_line = lines[-1].split(",")
                    last_base_str = last_line[0]
                    
                    last_base_time = datetime.strptime(last_base_str, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
                    next_base_time = last_base_time + timedelta(hours=6)
                    
                    # Sicherheitscheck: Ist die geplante Zeit zu weit in der Vergangenheit?
                    time_age_hours = (now_utc - next_base_time).total_seconds() / 3600.0
                    
                    if time_age_hours > MAX_BASE_TIME_AGE_HOURS:
                        print(f"⚠️ Sicherheitscheck: Berechnete Basiszeit ({next_base_time.strftime('%Y-%m-%d %H:%M')} UTC) "
                              f"weist {time_age_hours:.1f}h Rückstand auf. Limit ({MAX_BASE_TIME_AGE_HOURS}h) ueberschritten!")
                    else:
                        print(f"🔄 Kontinuierlicher Modus: Letzte Basiszeit war {last_base_str}. Setze fort bei +6h ({next_base_time.strftime('%Y-%m-%d %H:%M')} UTC).")
                        return next_base_time
        except Exception as e:
            print(f"⚠️ Hinweis beim CSV-Lesen (Wechsle auf Fallback): {e}")

    # 2. FALLBACK: Berechnung anhand der aktuellen Echtzeit (nächstes 6h-Raster)
    print("⏱️ Fallback-Modus: Synchronisiere Basiszeit neu anhand der aktuellen Echtzeit.")
    if now_utc.hour < 3:
        target_hour = 3
    elif now_utc.hour < 9:
        target_hour = 9
    elif now_utc.hour < 15:
        target_hour = 15
    elif now_utc.hour < 21:
        target_hour = 21
    else:
        tomorrow = now_utc + timedelta(days=1)
        return tomorrow.replace(hour=3, minute=0, second=0, microsecond=0)
    
    return now_utc.replace(hour=target_hour, minute=0, second=0, microsecond=0)

def analyze_predictive_window(data, config, base_time_utc):
    """Sucht im 4-Tages-Horizont nach dem frühesten erfüllten 36-Stunden-Fenster."""
    if not data or "hourly" not in data:
        return "Nein", 0, "Datenfehler: 'hourly' fehlt"
    
    hourly = data["hourly"]
    times = hourly.get("time", [])
    speeds = hourly.get("windspeed_10m_dwd_icon", hourly.get("windspeed_10m", []))
    directions = hourly.get("winddirection_10m_dwd_icon", hourly.get("winddirection_10m", []))

    if not times or not speeds or not directions:
        return "Nein", 0, "Datenfehler: Unvollständige Arrays"

    parsed_times = []
    for t_str in times:
        try:
            parsed_times.append(datetime.strptime(t_str, "%Y-%m-%dT%H:%M").replace(tzinfo=timezone.utc))
        except ValueError:
            parsed_times.append(None)

    base_index = None
    for idx, t_obj in enumerate(parsed_times):
        if t_obj and t_obj == base_time_utc:
            base_index = idx
            break

    if base_index is None:
        return "Nein", 0, "Fehler: Basiszeit nicht im API-Zeitfenster enthalten"

    total_len = len(speeds)
    binary_sequence = [0] * total_len
    gap_types = ["Keine Daten"] * total_len

    for idx in range(total_len):
        s = speeds[idx]
        d = directions[idx]
        if s is None or d is None:
            continue
            
        speed_ms = s / 3.6
        in_sector = config["crit_dir_min"] <= d <= config["crit_dir_max"]
        outside_margin = (d < (config["crit_dir_min"] - REVOKE_DIRECTION_MARGIN_DEG)) or (d > (config["crit_dir_max"] + REVOKE_DIRECTION_MARGIN_DEG))

        if speed_ms >= config["min_speed_ms"] and in_sector:
            binary_sequence[idx] = 1
            gap_types[idx] = "OK"
        else:
            if speed_ms < FLAUTE_SPEED_MS:
                gap_types[idx] = "Flaute"
            elif outside_margin:
                gap_types[idx] = "Gegenwind"
            else:
                gap_types[idx] = "Schwacher Wind"

    max_search_index = total_len - HOURS_WINDOW_SIZE
    
    for start_idx in range(base_index, max_search_index + 1):
        window_start_time = parsed_times[start_idx]
        sub_binary = binary_sequence[start_idx : start_idx + HOURS_WINDOW_SIZE]
        sub_gaps = gap_types[start_idx : start_idx + HOURS_WINDOW_SIZE]
        
        history_start = start_idx - HOURS_PAST
        if history_start >= 0:
            past_net_hours = sum(binary_sequence[history_start : start_idx])
            max_allowed_past_gap = max(ALLOWED_MAX_FLAUTE_HOURS, ALLOWED_MAX_DIRECTION_GAP_HOURS)
            if past_net_hours < (HOURS_PAST - max_allowed_past_gap):
                continue
        
        current_flaute_gap = 0
        current_direction_gap = 0
        max_flaute_found = 0
        max_direction_found = 0
        
        for val, cause in zip(sub_binary, sub_gaps):
            if val == 0:
                if cause == "Flaute":
                    current_flaute_gap += 1
                    current_direction_gap = 0
                elif cause == "Gegenwind":
                    current_direction_gap += 1
                    current_flaute_gap = 0
                else:
                    current_flaute_gap += 1
                    current_direction_gap += 1
                    
                if current_flaute_gap > max_flaute_found: max_flaute_found = current_flaute_gap
                if current_direction_gap > max_direction_found: max_direction_found = current_direction_gap
            else:
                current_flaute_gap = 0
                current_direction_gap = 0

        if max_flaute_found > ALLOWED_MAX_FLAUTE_HOURS or max_direction_found > ALLOWED_MAX_DIRECTION_GAP_HOURS:
            continue

        total_net_hours = sum(sub_binary)
        if total_net_hours >= REQUIRED_NET_HOURS:
            activation_time_str = window_start_time.strftime("%Y-%m-%d %H:%M")
            return activation_time_str, total_net_hours, f"Kriterien ab {activation_time_str} erfuellt ({total_net_hours}h aktiv)"

    return "Nein", 0, "Kriterien im gesamten Prognosezeitraum nicht erfuellt"

def main():
    print(ATTRIBUTION_NOTICE)
    triggered_by_level = {
        "Stufe 1 (Fernprognose)": [],
        "Stufe 2 (Nahe Prognose)": [],
        "Stufe 3 (Akute Warnung)": [],
        "Stufe 4 (Bestätigt/Messdaten)": []
    }
    revoked_locations = []
    global_summary_data = {}
    
    global_log_path = "upwellingWarning.csv"
    
    # 1. Ermittlung der logischen Berechnungs-Basiszeit
    base_time_utc = get_next_raster_base_time(global_log_path)
    base_time_str = base_time_utc.strftime("%Y-%m-%d %H:%M")
    print(f"📊 Berechnungs-Basiszeit fuer diesen Lauf: {base_time_str} UTC")
    
    batch_data = fetch_all_batch()
    if not batch_data or not isinstance(batch_data, list):
        send_ntfy_notification("Kritischer Fehler: Wetter-API liefert keine Daten!", priority="high", title="Systemfehler")
        return
        
    location_items = list(MONITORED_LOCATIONS.items())

    for idx, single_location_data in enumerate(batch_data):
        if idx >= len(location_items): 
            break
            
        name, config = location_items[idx]
        archive_dir = get_archive_dir(name)
        os.makedirs(archive_dir, exist_ok=True)
        
        had_active_alert = check_for_revocation(archive_dir)
        
        timestamp_file = base_time_utc.strftime("%Y%m%d_%H%M")
        with open(os.path.join(archive_dir, f"forecast_{timestamp_file}.json"), "w", encoding="utf-8") as f:
            json.dump(single_location_data, f, indent=4, ensure_ascii=False)
            
        result_status, net_hours, status_msg = analyze_predictive_window(single_location_data, config, base_time_utc)
        
        is_upwelling = (result_status != "Nein")
        write_to_tabular_log(archive_dir, is_upwelling, net_hours, status_msg)
        
        global_summary_data[name] = result_status
        
        if is_upwelling:
            # 2. Berechnung der Dringlichkeitsstufe ab der Basiszeit
            act_time_utc = datetime.strptime(result_status, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
            hours_until_event = (act_time_utc - base_time_utc).total_seconds() / 3600.0
            
            if hours_until_event >= 72:
                level = "Stufe 1 (Fernprognose)"
                emoji = "⏳"
            elif 48 <= hours_until_event < 72:
                level = "Stufe 2 (Nahe Prognose)"
                emoji = "🟡"
            elif 0 < hours_until_event < 48:
                level = "Stufe 3 (Akute Warnung)"
                emoji = "🟠"
            else:
                level = "Stufe 4 (Bestätigt/Messdaten)"
                emoji = "🚨"
                
            triggered_by_level[level].append(f"{emoji} {name} (Start: {result_status} UTC, {net_hours}h Wind)")
        else:
            if had_active_alert:
                revoked_locations.append(f"🟢 {name}: {status_msg}")
            print(f"ℹ️ [{name}] {status_msg}")
                
    # 3. Globales Log schreiben (Basiszeit in Spalte 1)
    file_exists = os.path.exists(global_log_path)
    sorted_places = sorted(list(MONITORED_LOCATIONS.keys()))
    with open(global_log_path, "a", encoding="utf-8") as f:
        if not file_exists:
            f.write("base_time_utc," + ",".join(sorted_places) + "\n")
        f.write(f"{base_time_str}," + ",".join([global_summary_data.get(p, "Nein") for p in sorted_places]) + "\n")
                
    # 4. NTFY-Versand mit Fokus auf die Basiszeit
    if revoked_locations:
        revoke_msg = (
            f"Folgende aktive Warnungen werden hiermit WIDERRAFEN, da die "
            f"Kontinuitaet zum Berechnungszeitpunkt {base_time_str} UTC gebrochen wurde:\n\n"
            + "\n".join(revoked_locations)
        )
        send_ntfy_notification(revoke_msg, priority=NTFY_LEVEL_REVOKE, title="UPWELLING-WIDERRUF")

    total_alerts_sent = 0
    for level_name in ["Stufe 1 (Fernprognose)", "Stufe 2 (Nahe Prognose)", "Stufe 3 (Akute Warnung)", "Stufe 4 (Bestätigt/Messdaten)"]:
        locations = triggered_by_level[level_name]
        if locations:
            total_alerts_sent += len(locations)
            alert_msg = (
                f"Upwelling-Kriterien erfuellt.\n"
                f"Berechnungs-Basiszeit: {base_time_str} UTC\n\n"
                + "\n".join(locations)
            )
            ntfy_priority = NTFY_LEVELS[level_name]
            send_ntfy_notification(alert_msg, priority=ntfy_priority, title=f"!! {level_name.upper()} !!")

    if total_alerts_sent == 0 and not revoked_locations:
        routine_msg = f"Routine-Lauf erfolgreich durchgefuehrt.\nBerechnungs-Basiszeit: {base_time_str} UTC\nKeine akuten Upwelling-Ereignisse detektiert."
        send_ntfy_notification(routine_msg, priority=NTFY_LEVEL_ROUTINE, title="Routine-Check Ostsee")

if __name__ == "__main__":
    main()
