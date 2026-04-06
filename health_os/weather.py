import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlencode
from urllib.request import urlopen

from .storage import read_json, write_json


class WeatherEnricher:
    def __init__(self, cache_path: Path):
        self.cache_path = cache_path
        self.provider = os.getenv("HEALTH_OS_WEATHER_PROVIDER", "disabled")
        self.static_payload = os.getenv("HEALTH_OS_WEATHER_STATIC", "")

    def enrich(self, date_value: Optional[str], location: Optional[str]) -> Optional[Dict[str, Any]]:
        if not date_value or not location:
            return None
        cache = self._load_cache()
        cache_key = "%s|%s" % (location, date_value)
        if cache_key in cache:
            return cache[cache_key]
        if self.provider == "disabled":
            return None
        if self.provider == "static":
            payload = self._lookup_static(cache_key)
        elif self.provider == "open-meteo":
            payload = self._lookup_open_meteo(date_value, location)
        else:
            payload = None
        if payload:
            cache[cache_key] = payload
            write_json(self.cache_path, cache)
        return payload

    def _load_cache(self) -> Dict[str, Any]:
        if not self.cache_path.exists():
            return {}
        return read_json(self.cache_path)

    def _lookup_static(self, cache_key: str) -> Optional[Dict[str, Any]]:
        if not self.static_payload:
            return None
        payload = json.loads(self.static_payload)
        return payload.get(cache_key)

    def _lookup_open_meteo(self, date_value: str, location: str) -> Optional[Dict[str, Any]]:
        latitude, longitude = self._geocode(location)
        if latitude is None or longitude is None:
            return None
        weather_url = "https://archive-api.open-meteo.com/v1/archive?" + urlencode(
            {
                "latitude": latitude,
                "longitude": longitude,
                "start_date": date_value,
                "end_date": date_value,
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,windspeed_10m_max",
                "timezone": "UTC",
            }
        )
        response = self._fetch_json(weather_url)
        daily = response.get("daily", {})
        if not daily:
            return None
        return {
            "provider": "open-meteo",
            "location": location,
            "date": date_value,
            "temperature_c_max": _first_item(daily.get("temperature_2m_max")),
            "temperature_c_min": _first_item(daily.get("temperature_2m_min")),
            "precipitation_mm": _first_item(daily.get("precipitation_sum")),
            "wind_speed_max_kmh": _first_item(daily.get("windspeed_10m_max")),
            "fetched_at": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        }

    def _geocode(self, location: str) -> Any:
        geocode_url = "https://geocoding-api.open-meteo.com/v1/search?" + urlencode(
            {"name": location, "count": 1, "language": "en", "format": "json"}
        )
        response = self._fetch_json(geocode_url)
        results = response.get("results") or []
        if not results:
            return None, None
        first = results[0]
        return first.get("latitude"), first.get("longitude")

    def _fetch_json(self, url: str) -> Dict[str, Any]:
        with urlopen(url, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))


def _first_item(items: Any) -> Any:
    if isinstance(items, list) and items:
        return items[0]
    return None
