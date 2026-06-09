import json
import os
from datetime import date as date_class
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlencode
from urllib.request import urlopen

from .storage import read_json, write_json


class EnvironmentService:
    def __init__(self, cache_path: Path):
        self.cache_path = cache_path
        self.provider = (
            os.getenv("OPENHEALTH_ENVIRONMENT_PROVIDER")
            or os.getenv("OPENHEALTH_WEATHER_PROVIDER", "open-meteo")
        )
        self.static_payload = (
            os.getenv("OPENHEALTH_ENVIRONMENT_STATIC")
            or os.getenv("OPENHEALTH_WEATHER_STATIC", "")
        )

    def daily_context(
        self,
        date_value: str,
        location: Optional[str] = None,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
        timezone_name: str = "auto",
    ) -> Optional[Dict[str, Any]]:
        if not date_value:
            return None
        cache = self._load_cache()
        cache_key = self._cache_key(date_value, location, latitude, longitude, timezone_name)
        if cache_key in cache:
            return cache[cache_key]
        if self.provider == "disabled":
            return None
        if self.provider == "static":
            payload = self._lookup_static(cache_key)
        else:
            payload = self._lookup_open_meteo(date_value, location, latitude, longitude, timezone_name)
        if payload:
            cache[cache_key] = payload
            write_json(self.cache_path, cache)
        return payload

    def _cache_key(
        self,
        date_value: str,
        location: Optional[str],
        latitude: Optional[float],
        longitude: Optional[float],
        timezone_name: str,
    ) -> str:
        return "|".join(
            [
                location or "unknown-location",
                str(latitude) if latitude is not None else "none",
                str(longitude) if longitude is not None else "none",
                timezone_name or "auto",
                date_value,
            ]
        )

    def _load_cache(self) -> Dict[str, Any]:
        if not self.cache_path.exists():
            return {}
        return read_json(self.cache_path)

    def _lookup_static(self, cache_key: str) -> Optional[Dict[str, Any]]:
        if not self.static_payload:
            return None
        payload = json.loads(self.static_payload)
        if cache_key in payload:
            return payload.get(cache_key)
        parts = cache_key.split("|")
        if len(parts) >= 5:
            legacy_key = "%s|%s" % (parts[0], parts[-1])
            return payload.get(legacy_key)
        return None

    def _lookup_open_meteo(
        self,
        date_value: str,
        location: Optional[str],
        latitude: Optional[float],
        longitude: Optional[float],
        timezone_name: str,
    ) -> Optional[Dict[str, Any]]:
        resolved_lat, resolved_lon, resolved_label = self._resolve_coordinates(location, latitude, longitude)
        if resolved_lat is None or resolved_lon is None:
            return None
        endpoint = self._select_endpoint(date_value)
        params = {
            "latitude": resolved_lat,
            "longitude": resolved_lon,
            "start_date": date_value,
            "end_date": date_value,
            "timezone": timezone_name or "auto",
            "daily": ",".join(
                [
                    "sunrise",
                    "sunset",
                    "daylight_duration",
                    "temperature_2m_max",
                    "temperature_2m_min",
                    "apparent_temperature_max",
                    "apparent_temperature_min",
                    "precipitation_sum",
                    "weathercode",
                    "windspeed_10m_max",
                ]
            ),
            "hourly": "relative_humidity_2m,surface_pressure",
        }
        response = self._fetch_json("%s?%s" % (endpoint, urlencode(params)))
        daily = response.get("daily") or {}
        if not daily:
            return None
        humidity_metrics = _aggregate_hourly_metric(response.get("hourly"), "relative_humidity_2m")
        pressure_metrics = _aggregate_hourly_metric(response.get("hourly"), "surface_pressure")
        return {
            "provider": "open-meteo",
            "location": resolved_label or location,
            "latitude": resolved_lat,
            "longitude": resolved_lon,
            "date": date_value,
            "timezone": response.get("timezone") or timezone_name,
            "sunrise": _first_item(daily.get("sunrise")),
            "sunset": _first_item(daily.get("sunset")),
            "daylight_duration_seconds": _first_item(daily.get("daylight_duration")),
            "temperature_c_max": _first_item(daily.get("temperature_2m_max")),
            "temperature_c_min": _first_item(daily.get("temperature_2m_min")),
            "apparent_temperature_c_max": _first_item(daily.get("apparent_temperature_max")),
            "apparent_temperature_c_min": _first_item(daily.get("apparent_temperature_min")),
            "precipitation_mm": _first_item(daily.get("precipitation_sum")),
            "weather_code": _first_item(daily.get("weathercode")),
            "wind_speed_max_kmh": _first_item(daily.get("windspeed_10m_max")),
            "humidity_relative": humidity_metrics,
            "surface_pressure_hpa": pressure_metrics,
            "fetched_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        }

    def _resolve_coordinates(
        self,
        location: Optional[str],
        latitude: Optional[float],
        longitude: Optional[float],
    ) -> Tuple[Optional[float], Optional[float], Optional[str]]:
        if latitude is not None and longitude is not None:
            return latitude, longitude, location
        if not location:
            return None, None, None
        response = self._fetch_json(
            "https://geocoding-api.open-meteo.com/v1/search?%s"
            % urlencode({"name": location, "count": 1, "language": "en", "format": "json"})
        )
        results = response.get("results") or []
        if not results:
            return None, None, None
        first = results[0]
        return first.get("latitude"), first.get("longitude"), first.get("name") or location

    def _select_endpoint(self, date_value: str) -> str:
        target = date_class.fromisoformat(date_value)
        today = datetime.now(timezone.utc).date()
        if target < today:
            return "https://archive-api.open-meteo.com/v1/archive"
        return "https://api.open-meteo.com/v1/forecast"

    def _fetch_json(self, url: str) -> Dict[str, Any]:
        with urlopen(url, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))


def _first_item(items: Any) -> Any:
    if isinstance(items, list) and items:
        return items[0]
    return None


def _aggregate_hourly_metric(hourly: Any, key: str) -> Optional[Dict[str, Any]]:
    if not isinstance(hourly, dict):
        return None
    values = hourly.get(key) or []
    numbers = [value for value in values if isinstance(value, (int, float))]
    if not numbers:
        return None
    return {
        "min": min(numbers),
        "max": max(numbers),
        "avg": round(sum(numbers) / len(numbers), 2),
    }
