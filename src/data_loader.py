"""
Data loading, validation, and shipment-stratified train/val/test splitting.

The prediction unit is (shipment_id, container_id, window_id).
One container always carries exactly one product type.
Splitting is done by shipment_id to prevent temporal leakage.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, Tuple

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split

logger = logging.getLogger(__name__)

EXPECTED_COLUMNS = [
    "window_id", "leg_id", "shipment_id", "container_id", "product_id",
    "window_start", "window_end",
    "avg_temp_c", "max_temp_c", "min_temp_c", "temp_slope_c_per_hr",
    "humidity_avg_pct", "shock_count", "door_open_count",
    "minutes_outside_range", "current_delay_min", "battery_avg_pct",
    "transit_phase", "target_spoilage_risk_6h",
]

TARGET = "target_spoilage_risk_6h"

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def load_product_profiles(path: Path | None = None) -> Dict[str, dict]:
    path = path or DATA_DIR / "product_profiles.json"
    with open(path) as f:
        return json.load(f)


def load_raw(csv_path: Path | None = None, force_csv: bool = False) -> pd.DataFrame:
    """
    Load telemetry data. Tries Supabase window_features first, falls back to local CSV.
    Set force_csv=True to skip Supabase entirely.
    """
    if not force_csv:
        try:
            from src.supabase_client import fetch_window_features, is_available
            if is_available():
                df = fetch_window_features()
                if df is not None and not df.empty:
                    logger.info("Loaded %d rows from Supabase window_features", len(df))
                    return df
                logger.info("Supabase window_features empty; falling back to CSV")
        except Exception as e:
            logger.warning("Supabase fetch failed (%s); falling back to CSV", e)

    csv_path = csv_path or DATA_DIR / "single_table.csv"
    df = pd.read_csv(csv_path, parse_dates=["window_start", "window_end"])
    logger.info("Loaded %d rows from %s", len(df), csv_path.name)
    return df


def load_product_profiles_smart() -> Dict[str, dict]:
    """Load product profiles from Supabase, fall back to local JSON."""
    try:
        from src.supabase_client import load_profiles_with_fallback
        return load_profiles_with_fallback()
    except Exception:
        return load_product_profiles()


def validate(df: pd.DataFrame) -> pd.DataFrame:
    """Run structural and semantic checks, log warnings, return cleaned df."""
    missing = set(EXPECTED_COLUMNS) - set(df.columns)
    if missing:
        raise ValueError(f"Missing columns: {missing}")

    nulls = df.isnull().sum()
    if nulls.any():
        logger.warning("Null values found:\n%s", nulls[nulls > 0])

    cp = df.groupby("container_id")["product_id"].nunique()
    if not (cp == 1).all():
        bad = cp[cp > 1].index.tolist()
        raise ValueError(f"Containers with multiple products: {bad}")

    if not df["window_id"].is_unique:
        dups = df["window_id"].duplicated().sum()
        raise ValueError(f"{dups} duplicate window_ids")

    df = df.sort_values(["shipment_id", "leg_id", "window_start"]).reset_index(drop=True)
    logger.info(
        "Validated: %d rows, %d shipments, %d legs, %d products",
        len(df), df["shipment_id"].nunique(),
        df["leg_id"].nunique(), df["product_id"].nunique(),
    )
    return df


def shipment_stratified_split(
    df: pd.DataFrame,
    train_frac: float = 0.6,
    val_frac: float = 0.2,
    seed: int = 42,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Split by shipment_id so no shipment's windows leak across sets.
    Stratification is approximate: we stratify on the *shipment-level*
    majority label (whether the shipment contains any positive window).
    """
    ship_label = (
        df.groupby("shipment_id")[TARGET]
        .max()
        .rename("has_positive")
    )

    shipments = ship_label.index.to_numpy()
    labels = ship_label.values

    train_ships, temp_ships = train_test_split(
        shipments, test_size=1 - train_frac,
        stratify=labels, random_state=seed,
    )
    temp_labels = ship_label.loc[temp_ships].values
    relative_val = val_frac / (1 - train_frac)
    val_ships, test_ships = train_test_split(
        temp_ships, test_size=1 - relative_val,
        stratify=temp_labels, random_state=seed,
    )

    train_set = set(train_ships)
    val_set = set(val_ships)
    test_set = set(test_ships)

    df_train = df[df["shipment_id"].isin(train_set)].copy()
    df_val = df[df["shipment_id"].isin(val_set)].copy()
    df_test = df[df["shipment_id"].isin(test_set)].copy()

    for name, part in [("train", df_train), ("val", df_val), ("test", df_test)]:
        pos_rate = part[TARGET].mean()
        logger.info(
            "  %s: %d rows, %d shipments, %.1f%% positive",
            name, len(part), part["shipment_id"].nunique(), pos_rate * 100,
        )

    return df_train, df_val, df_test


def load_and_split(
    csv_path: Path | None = None,
    profiles_path: Path | None = None,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, Dict[str, dict]]:
    """Convenience: load, validate, split, return (train, val, test, profiles)."""
    df = load_raw(csv_path)
    df = validate(df)
    profiles = load_product_profiles(profiles_path)
    train, val, test = shipment_stratified_split(df)
    return train, val, test, profiles
