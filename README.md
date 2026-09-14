# Baltic Sea Upwelling Predictor

An automated, open-science early warning and data-archiving system for coastal upwelling events along the German Baltic Sea coast. 

This system uses meteorological forecasts from the German Weather Service (DWD) and oceanographic data from the Federal Maritime and Hydrographic Agency (BSH) to identify wind-driven Ekman transport conditions that trigger the upwelling of cold deep water.

## 📊 Features
* **Automated Pipeline:** Runs every 6 hours via GitHub Actions.
* **Data Archiving:** Saves raw forecast JSON files locally in the repository for reproducibility and future validation.
* **Smart Alerting:** Evaluates wind speed, duration, and direction thresholds for specific coastal segments.
* **Double Check:** Evaluates forecast values with nowcast and archive data (reanalyses)

## 🗺️ Monitored Regions & Upwelling Conditions
* **Mecklenburg-Vorpommern Coast (e.g., Rostock-Warnemünde, Darß):** Triggered by sustained Westerly winds (West to Southwest).
* **Schleswig-Holstein Coast (e.g., Eckernförde, Fehmarn):** Triggered by sustained Easterly/Southeasterly winds.

## 📈 Data Sources & Attribution
This project relies entirely on open data provided under German open-data laws:
* **Meteorological Data:** © Deutscher Wetterdienst (DWD), fetched via the non-commercial Open-Meteo DWD API (licensed under CC-BY 4.0).
* **Meteorological Data:** © Copernicus Climate Change Service (ECMWF) – ERA5 / ERA5-Land Reanalysis (Produced via Open-Meteo API under CC-BY 4.0).

## 🛠️ Repository Structure
* `/archive/` - Contains a folder for each analysed place. Each folder contains the historical raw forecast JSON payloads and a csv with all single results for validation.
* `upwelling_predictor.py` - The core Python script containing the detection logic.
* `upwellingWarning.csv` - contains a result overview
* `simulate_upwelling.py` - A test script wich generates data wich raise a warning
