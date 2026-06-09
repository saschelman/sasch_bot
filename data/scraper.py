import os
import math
import time
from datetime import datetime
from pathlib import Path
import pandas as pd
from tvDatafeed import TvDatafeed, Interval

# 1. Verbindung herstellen
tv = TvDatafeed()

# Defaults; can be overridden by CLI args or environment
SYMBOL = "EURUSD"
EXCHANGE = "OANDA"

def parse_args():
    import argparse
    parser = argparse.ArgumentParser(description="Scrape TradingView data for a symbol")
    parser.add_argument("--symbol", "-s", default=SYMBOL, help="Ticker symbol, e.g. USDCAD")
    parser.add_argument("--exchange", "-e", default=EXCHANGE, help="Exchange name, e.g. OANDA")
    parser.add_argument("--outdir", "-o", default=None, help="Base output directory (default: scraping)")
    parser.add_argument("--show-trend", dest="show_trend", action="store_true", help="Compute and include simple trend columns in CSV")
    return parser.parse_args()

args = parse_args()
SYMBOL = args.symbol
EXCHANGE = args.exchange
OUTDIR = args.outdir or "scraping"
SHOW_TREND = bool(args.show_trend)

# Konfiguration: Wir fügen die "minuten_pro_bar" hinzu, damit Python rechnen kann
# bars_full wurde auf 2 Jahre Daten angepasst (vorher 6 Monate), außer 30min und 15min (nur letzte 10h)
intervalle = [
    {"name": "1 Woche", "tv_interval": Interval.in_weekly, "bars_full": 104, "minuten_pro_bar": 10080, "datei": "usdcad_6m_1w.csv"},
    {"name": "1 Tag", "tv_interval": Interval.in_daily, "bars_full": 560, "minuten_pro_bar": 1440, "datei": "usdcad_6m_daily.csv"},
    {"name": "4 Stunden", "tv_interval": Interval.in_4_hour, "bars_full": 3360, "minuten_pro_bar": 240, "datei": "usdcad_6m_4h.csv"},
    {"name": "2 Stunden", "tv_interval": Interval.in_2_hour, "bars_full": 6720, "minuten_pro_bar": 120, "datei": "usdcad_6m_2h.csv"},
    {"name": "1 Stunde", "tv_interval": Interval.in_1_hour, "bars_full": 13440, "minuten_pro_bar": 60, "datei": "usdcad_6m_1h.csv"},
    {"name": "30 Minuten", "tv_interval": Interval.in_30_minute, "bars_full": 20, "minuten_pro_bar": 30, "datei": "usdcad_10h_30m.csv"},
    {"name": "15 Minuten", "tv_interval": Interval.in_15_minute, "bars_full": 40, "minuten_pro_bar": 15, "datei": "usdcad_10h_15m.csv"}
]

print(f"Starte zeitstempel-basierten Daten-Sync für {SYMBOL} ({EXCHANGE})...\n")

# Erzeuge für jeden Lauf einen eigenen Ordner unter `scraping/`, z.B. scraping/USDCAD_20260606_153012/
# Use a persistent folder per symbol (no timestamp) so subsequent runs reuse existing CSVs
base_dir = Path(OUTDIR) / SYMBOL.lower()
base_dir.mkdir(parents=True, exist_ok=True)
print(f"Schreibe Ausgabedateien nach: {base_dir}\n")
def normalisiere_zeitreihe(df: pd.DataFrame) -> pd.DataFrame:
    """Stellt sicher, dass der Zeitstempel sauber im Index liegt und sortiert ist."""
    if "datetime" in df.columns:
        df = df.copy()
        df["datetime"] = pd.to_datetime(df["datetime"])
        df = df.set_index("datetime")
    else:
        df = df.copy()
        df.index = pd.to_datetime(df.index)

    return df.sort_index()


def entferne_timezone(ts: pd.Timestamp) -> pd.Timestamp:
    if ts.tzinfo is not None:
        return ts.tz_localize(None)
    return ts

for config in intervalle:
    zielpfad = base_dir / config['datei']
    
    # Schritt A: Existiert die Datei schon?
    if zielpfad.exists():
        df_alt = normalisiere_zeitreihe(pd.read_csv(zielpfad))
        letzter_zeitstempel = entferne_timezone(pd.Timestamp(df_alt.index[-1]))
        
        print(f"🔄 [{config['name']}]: Letzter Eintrag war am {letzter_zeitstempel.strftime('%d.%m.%Y um %H:%M')} Uhr.")

        # Erst nur die neueste Kerze prüfen. Wenn sie nicht neuer ist, sparen wir den eigentlichen Nachlade-Call.
        df_letzte_kerze = tv.get_hist(
            symbol=SYMBOL,
            exchange=EXCHANGE,
            interval=config['tv_interval'],
            n_bars=1
        )

        if df_letzte_kerze is None or df_letzte_kerze.empty:
            print(f"   ❌ Fehler: Konnte letzte Kerze nicht prüfen.\n")
            continue

        aktuelle_zeit = entferne_timezone(pd.Timestamp(df_letzte_kerze.index[-1]))

        if aktuelle_zeit <= letzter_zeitstempel:
            print(f"   ✅ Daten sind bereits aktuell! Überspringe Download.\n")
            continue

        minuten_vergangen = (aktuelle_zeit - letzter_zeitstempel).total_seconds() / 60.0
        bars_zu_laden = max(1, math.ceil(minuten_vergangen / config['minuten_pro_bar']) + 1)

        print(f"   ⬇️  Neue Daten gefunden bis {aktuelle_zeit.strftime('%d.%m.%Y um %H:%M')} Uhr.")
        print(f"   ⬇️  Lade {bars_zu_laden} fehlende Kerzen nach...")
        
    else:
        # Wenn es die Datei nicht gibt, machen wir den Erstabruf
        bars_zu_laden = config['bars_full']
        df_alt = None
        print(f"📥 [{config['name']}]: Erstabruf (lade komplette Historie mit {bars_zu_laden} Kerzen)...")

    # Schritt B: Neue Daten abrufen
    df_neu = tv.get_hist(
        symbol=SYMBOL,
        exchange=EXCHANGE,
        interval=config['tv_interval'],
        n_bars=bars_zu_laden
    )

    # Schritt C: Zusammenfügen und Speichern
    if df_neu is not None and not df_neu.empty:
        if df_alt is not None:
            # Beide Datensätze zusammenkleben
            df_neu = normalisiere_zeitreihe(df_neu)
            df_kombiniert = pd.concat([df_alt, df_neu])
            # Duplikate anhand der Zeitstempel rausschmeißen (wir behalten die jeweils aktuellste)
            df_kombiniert = df_kombiniert[~df_kombiniert.index.duplicated(keep='last')]
            df_finale = df_kombiniert.sort_index()
        else:
            df_finale = normalisiere_zeitreihe(df_neu)
            
        # Optional: compute simple trend columns
        if SHOW_TREND:
            if 'close' in df_finale.columns:
                df_finale = df_finale.copy()
                df_finale['trend'] = df_finale['close'].diff()
                df_finale['trend_pct'] = df_finale['close'].pct_change().fillna(0)
            else:
                print("   ⚠️ Show-trend requested but 'close' column not found.")

        # to_csv akzeptiert Path-Objekte
        df_finale.to_csv(zielpfad)
        print(f"   💾 Gespeichert! Zeilen in Datei: {len(df_finale)}\n")
    else:
        print(f"   ❌ Fehler: Keine Daten erhalten.\n")
        
    time.sleep(1)

print("🎉 Synchronisation komplett abgeschlossen!")