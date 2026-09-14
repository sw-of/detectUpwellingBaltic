import os
import json
import argparse  # Für die Argumenten-Abfrage aus GitHub
from datetime import datetime, timezone, timedelta

# ==============================================================================
# 1. IMPORTS AUS DEINEM HAUPTSKRIPT
# ==============================================================================
try:
    from upwelling_predictor import (
        MONITORED_LOCATIONS, 
        get_archive_dir, 
        check_for_revocation, 
        analyze_predictive_window, 
        write_to_tabular_log,
        REQUIRED_MIN_PAST_HOURS,
        send_ntfy_notification,
        NTFY_LEVEL_LEVELS,
        NTFY_LEVEL_REVOKE,
        NTFY_LEVEL_ROUTINE
    )
except ImportError:
    print("❌ Fehler: Hauptskript 'upwelling.py' nicht im selben Ordner gefunden!")
    exit(1)

# ==============================================================================
# 2. GENERIERUNG GESTEUERTER TESTDATEN
# ==============================================================================
def generate_mock_api_data(target_location):
    """
    Generiert künstliche Wetterdaten. Nur der 'target_location' erhält perfekten Upwelling-Wind.
    Alle anderen Orte verbleiben im ruhigen Modus.
    """
    mock_batch = []
    base_time_utc = datetime.now(timezone.utc).replace(hour=12, minute=0, second=0, microsecond=0)
    
    time_array = []
    for hour_offset in range(-24, 96):
        current_hour = base_time_utc + timedelta(hours=hour_offset)
        time_array.append(current_hour.strftime("%Y-%m-%dT%H:%M"))
        
    for name, config in MONITORED_LOCATIONS.items():
        wind_speeds = []
        wind_directions = []
        crit_dir_center = (config["crit_dir_min"] + config["crit_dir_max"]) // 2
        
        for hour_offset in range(-24, 96):
            # NUR der ausgewählte Zielort bekommt den Sturm!
            if name == target_location and 12 <= hour_offset <= 60:
                wind_speeds.append(12.0)          # 12 m/s = Starker Upwelling-Wind
                wind_directions.append(crit_dir_center) # Perfekter Sektor
            else:
                wind_speeds.append(2.0)           # Normaler, harmloser Wind
                wind_directions.append(0)         # Unkritische Richtung
                
        location_data = {
            "latitude": config["lat"],
            "longitude": config["lon"],
            "hourly": {
                "time": time_array,
                "windspeed_10m": wind_speeds,
                "winddirection_10m": wind_directions
            }
        }
        mock_batch.append(location_data)
        
    return mock_batch, base_time_utc

# ==============================================================================
# 3. MAIN SIMULATION (MIT STEUERUNG)
# ==============================================================================
def main_simulation():
    # Argument Parser einrichten
    parser = argparse.ArgumentParser(description="Upwelling Simulations-Testlauf")
    parser.add_argument("--location", default="Kiel", help="Der Ort, für den Upwelling simuliert werden soll")
    args = parser.parse_args()
    
    target_location = args.location
    if target_location not in MONITORED_LOCATIONS:
        print(f"❌ Fehler: Ort '{target_location}' ist nicht in MONITORED_LOCATIONS konfiguriert!")
        exit(1)
        
    print(f"🚀 STARTE LOGIK-TEST FÜR ORT: {target_location.upper()} (Simulation ohne API) 🚀")
    
    triggered_by_level = {
        "Stufe 1 (Fernprognose)": [], "Stufe 2 (Nahe Prognose)": [],
        "Stufe 3 (Akute Warnung)": [], "Stufe 4 (Bestätigt/Messdaten)": []
    }
    revoked_locations, global_summary_data = [], {}
    global_log_path = "upwellingWarning_TEST.csv"
    
    batch_data, base_time_utc = generate_mock_api_data(target_location)
    base_time_str = base_time_utc.strftime("%Y-%m-%d %H:%M")
    print(f"📊 Simulierte Basiszeit: {base_time_str} UTC")
    
    location_items = list(MONITORED_LOCATIONS.items())

    for idx, single_location_data in enumerate(batch_data):
        name, config = location_items[idx]
        archive_dir = get_archive_dir(name)
        os.makedirs(archive_dir, exist_ok=True)
        
        had_active_alert = check_for_revocation(archive_dir)
        
        # Speichert die Test-JSON im Archiv ab
        with open(os.path.join(archive_dir, f"forecast_SIMULATION.json"), "w", encoding="utf-8") as f:
            json.dump(single_location_data, f, indent=4, ensure_ascii=False)
            
        result_status, total_duration, status_msg = analyze_predictive_window(single_location_data, config, base_time_utc)
        
        is_upwelling = (result_status != "Nein")
        write_to_tabular_log(archive_dir, is_upwelling, total_duration, status_msg)
        global_summary_data[name] = result_status
        
        if is_upwelling:
            act_time_utc = datetime.strptime(result_status, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
            hours_in_past = (base_time_utc - act_time_utc).total_seconds() / 3600.0 if act_time_utc < base_time_utc else 0.0
            hours_until_event = (act_time_utc - base_time_utc).total_seconds() / 3600.0
            
            if hours_in_past >= REQUIRED_MIN_PAST_HOURS: level, emoji = "Stufe 4 (Bestätigt/Messdaten)", "🚨"
            elif hours_until_event < 48: level, emoji = "Stufe 3 (Akute Warnung)", "🟠"
            elif hours_until_event < 72: level, emoji = "Stufe 2 (Nahe Prognose)", "🟡"
            else: level, emoji = "Stufe 1 (Fernprognose)", "⏳"
                
            triggered_by_level[level].append(f"{emoji} {name} (Kern-Start: {result_status} UTC)\n   ┗ ℹ️ {status_msg}")
            print(f"🎯 SIM-LOG: [{name}] {level} getriggert! {status_msg}")
        else:
            if had_active_alert: revoked_locations.append(f"🟢 {name}: {status_msg}")
            # Nur eine kurze Info auf der Konsole für die restlichen Orte
            if name == target_location:
                print(f"ℹ️ SIM-LOG: [{name}] Keine Kriterien erfuellt.")
                
    # Globales Test-CSV Log schreiben
    file_exists = os.path.exists(global_log_path)
    sorted_places = sorted(list(MONITORED_LOCATIONS.keys()))
    with open(global_log_path, "a", encoding="utf-8") as f:
        if not file_exists: f.write("base_time_utc," + ",".join(sorted_places) + "\n")
        f.write(f"{base_time_str}," + ",".join([global_summary_data.get(p, "Nein") for p in sorted_places]) + "\n")
                
    # TEST-MELDUNGEN PER NTFY ABSENDEN
    print("\n📱 Sende ntfy-Testbenachrichtigungen...")
    if revoked_locations:
        revoke_msg = f"[TEST] Warnungen WIDERRAFEN (Basiszeit: {base_time_str} UTC):\n\n" + "\n".join(revoked_locations)
        send_ntfy_notification(revoke_msg, priority=NTFY_LEVEL_REVOKE, title="TEST-UPWELLING-WIDERRUF")

    total_alerts_sent = 0
    for level_name in ["Stufe 1 (Fernprognose)", "Stufe 2 (Nahe Prognose)", "Stufe 3 (Akute Warnung)", "Stufe 4 (Bestätigt/Messdaten)"]:
        locations = triggered_by_level[level_name]
        if locations:
            total_alerts_sent += len(locations)
            alert_msg = f"[TEST-ALARM] Basiszeit: {base_time_str} UTC\n\n" + "\n".join(locations)
            send_ntfy_notification(alert_msg, priority=NTFY_LEVEL_LEVELS[level_name], title=f"!! TEST: {level_name.upper()} !!")

    print(f"✅ Simulation fuer {target_location} beendet. Test-Warnung gesendet.")

if __name__ == "__main__":
    main_simulation()
