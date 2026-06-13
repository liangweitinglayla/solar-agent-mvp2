import pandas as pd
import pvlib

# Plant coordinates (from dataset coordinate files)
PLANTS = {
    "Plant A": {"latitude": 53.269, "longitude": 12.121, "altitude": 50, "tz": "Europe/Berlin"},
    "Plant B": {"latitude": 53.269, "longitude": 12.121, "altitude": 50, "tz": "Europe/Berlin"},
}

# Rated DC capacity per inverter (kWp) — from System_Overview.xlsx
# Plant A inverters mapped to their PDC values
INVERTER_KWP = {
    "INV 01.01.001": 30.6, "INV 01.01.002": 30.6, "INV 01.01.003": 30.6,
    "INV 01.01.004": 24.48, "INV 01.01.005": 30.6, "INV 01.01.006": 30.6,
    "INV 01.01.007": 30.6, "INV 01.02.008": 30.6, "INV 01.02.009": 30.6,
    "INV 01.02.010": 30.6,
}
DEFAULT_KWP = 30.0  # fallback for unknown inverters


def get_clearsky_power(timestamps: pd.DatetimeIndex, inverter_id: str, plant_id: str = "Plant A") -> pd.Series:
    """
    Calculate physics-based expected AC power (kW) using pvlib clear-sky model.
    Uses the Ineichen clear-sky irradiance model + a simple PVWatts efficiency.

    Returns a Series indexed by timestamp with expected power in kW.
    """
    cfg = PLANTS.get(plant_id, PLANTS["Plant A"])
    location = pvlib.location.Location(
        latitude=cfg["latitude"],
        longitude=cfg["longitude"],
        tz=cfg["tz"],
        altitude=cfg["altitude"],
    )

    # Localize timestamps to Berlin time for pvlib
    ts_local = pd.DatetimeIndex(timestamps).tz_localize(cfg["tz"], ambiguous="NaT", nonexistent="NaT")
    ts_local = ts_local.dropna()

    # Solar position
    solar_pos = location.get_solarposition(ts_local)

    # Clear-sky irradiance (Ineichen model)
    clearsky = location.get_clearsky(ts_local, model="ineichen")
    ghi = clearsky["ghi"]  # Global Horizontal Irradiance (W/m²)

    # Simple PVWatts model: P_ac = GHI * efficiency * kWp / 1000
    # Typical system efficiency ~0.80 (inverter + wiring + temp losses)
    kwp = INVERTER_KWP.get(inverter_id, DEFAULT_KWP)
    efficiency = 0.78

    expected_kw = (ghi * efficiency * kwp / 1000.0).clip(lower=0)
    expected_kw.index = expected_kw.index.tz_localize(None)  # strip tz for DuckDB compatibility

    # Reindex to original timestamps (fill missing with 0)
    return expected_kw.reindex(timestamps, fill_value=0.0)


def add_clearsky_to_df(ts_df: pd.DataFrame, inverter_id: str, plant_id: str = "Plant A") -> pd.DataFrame:
    """
    Add a 'clearsky_power' column to the impact time-series dataframe.
    ts_df must have a 'timestamp' column.
    """
    timestamps = pd.DatetimeIndex(ts_df["timestamp"])
    clearsky = get_clearsky_power(timestamps, inverter_id, plant_id)
    ts_df = ts_df.copy()
    ts_df["clearsky_power"] = clearsky.values
    return ts_df
