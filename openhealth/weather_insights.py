from datetime import date as date_class
from datetime import timedelta
from typing import Any, Dict, List, Optional

from . import index
from .contexts import refresh_contexts
from .environment import EnvironmentService
from .models import InsightHypothesis, Observation, SourceManifest
from .storage import ensure_repo_structure, load_json_if_exists, now_utc, write_json

WEATHER_SOURCE_ID = "weather-intelligence"


def assess_weather_impact(
    root,
    date_value: str,
    location: Optional[str] = None,
    timezone_name: Optional[str] = None,
    environment_service: Optional[EnvironmentService] = None,
) -> Dict[str, Any]:
    paths = ensure_repo_structure(root)
    config = load_json_if_exists(paths.google_calendar_config_path, {}) or {}
    home_location = config.get("home_location") or {}
    timezone_name = timezone_name or config.get("timezone") or "UTC"
    environment_service = environment_service or EnvironmentService(paths.environment_cache_path)
    current = environment_service.daily_context(
        date_value=date_value,
        location=location or home_location.get("label"),
        latitude=home_location.get("latitude"),
        longitude=home_location.get("longitude"),
        timezone_name=timezone_name,
    )
    if not current:
        return {"date": date_value, "findings": [], "suppressed": ["No environment data available."]}
    previous_date = (date_class.fromisoformat(date_value) - timedelta(days=1)).isoformat()
    previous = environment_service.daily_context(
        date_value=previous_date,
        location=location or home_location.get("label"),
        latitude=home_location.get("latitude"),
        longitude=home_location.get("longitude"),
        timezone_name=timezone_name,
    )
    registry = load_json_if_exists(paths.weather_evidence_registry_path, {"factors": []}) or {"factors": []}
    profile = load_json_if_exists(paths.weather_susceptibility_path, {}) or {}
    active_factors = _derive_active_factors(current, previous)
    findings: List[Dict[str, Any]] = []
    suppressed: List[str] = []
    for factor, details in active_factors.items():
        entry = next((item for item in registry.get("factors", []) if item.get("factor") == factor), None)
        if not entry:
            suppressed.append("%s: no registry entry available." % factor)
            continue
        domains = entry.get("affected_domains") or []
        profile_match = any(
            domain in (profile.get("declared_sensitivities") or []) or domain in (profile.get("personally_supported_signals") or [])
            for domain in domains
        )
        evidence_strength = entry.get("evidence_strength", "insufficient")
        if not profile_match:
            suppressed.append("%s: no personal sensitivity signal." % factor)
            continue
        findings.append(
            {
                "factor": factor,
                "evidence_strength": evidence_strength,
                "domains": domains,
                "factor_state": details,
                "message": _finding_message(factor, domains, evidence_strength, details),
            }
        )
        if evidence_strength == "insufficient":
            suppressed.append("%s: general evidence is insufficient, so keep this as a personal hypothesis only." % factor)
    return {
        "date": date_value,
        "environment": current,
        "active_factors": active_factors,
        "findings": findings,
        "suppressed": suppressed or ["No personal weather sensitivities matched active factors."],
    }


def sync_weather_assessment(
    root,
    date_value: str,
    location: Optional[str] = None,
    timezone_name: Optional[str] = None,
    environment_service: Optional[EnvironmentService] = None,
) -> Dict[str, Any]:
    paths = ensure_repo_structure(root)
    index.init_db(paths.db_path)
    assessment = assess_weather_impact(
        root=root,
        date_value=date_value,
        location=location,
        timezone_name=timezone_name,
        environment_service=environment_service,
    )
    source = SourceManifest(
        source_id=WEATHER_SOURCE_ID,
        source_type="manual-notes",
        owner="ilya",
        label="Weather intelligence",
        created_at=now_utc(),
        coverage_start=date_value,
        coverage_end=date_value,
        files=[],
        parser_status="generated",
        notes=["Weather outputs are gated by evidence strength and personal sensitivity profile."],
        metadata={"kind": "weather-intelligence"},
    )
    index.upsert_source(paths.db_path, source.to_dict())
    write_json(paths.source_manifests / ("%s.json" % WEATHER_SOURCE_ID), source.to_dict())
    if assessment.get("environment"):
        env = assessment["environment"]
        env_record = Observation(
            id="weather-context-%s" % date_value,
            record_type="Observation",
            source_id=WEATHER_SOURCE_ID,
            title="Daily weather context for %s" % date_value,
            summary="Open environment context used for cautious daily assessment.",
            artifact_ids=[],
            evidence_class="contextual",
            confidence=0.78,
            date=date_value,
            location=env.get("location"),
            tags=["weather", "environment", "derived"],
            metadata=env,
            observation_kind="environment_context",
            metric_name="weather_code",
            value=env.get("weather_code"),
            unit=None,
        )
        index.upsert_record(paths.db_path, env_record.to_dict())
    insight = InsightHypothesis(
        id="weather-insight-%s" % date_value,
        record_type="InsightHypothesis",
        source_id=WEATHER_SOURCE_ID,
        title="Weather hypothesis for %s" % date_value,
        summary=_assessment_summary(assessment),
        artifact_ids=[],
        evidence_class="derived-hypothesis",
        confidence=0.42 if assessment.get("findings") else 0.2,
        date=date_value,
        tags=["weather", "hypothesis", "derived"],
        metadata={
            "active_factors": assessment.get("active_factors"),
            "suppressed": assessment.get("suppressed"),
        },
        statement=_assessment_summary(assessment),
        evidence_record_ids=["weather-context-%s" % date_value] if assessment.get("environment") else [],
        open_questions=[
            "Does the same factor align with any symptoms in personal records?",
            "Should this factor stay suppressed because evidence is mixed or insufficient?",
        ],
    )
    index.upsert_record(paths.db_path, insight.to_dict())
    write_json(paths.data_index / "latest-weather-assessment.json", assessment)
    refresh_contexts(paths, index)
    return assessment


def _derive_active_factors(current: Dict[str, Any], previous: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    active: Dict[str, Dict[str, Any]] = {}
    humidity = (current.get("humidity_relative") or {}).get("avg")
    if humidity is not None and humidity < 45:
        active["low_relative_humidity"] = {"avg": humidity}
    pressure = (current.get("surface_pressure_hpa") or {}).get("avg")
    previous_pressure = ((previous or {}).get("surface_pressure_hpa") or {}).get("avg")
    if pressure is not None and previous_pressure is not None and abs(pressure - previous_pressure) >= 6:
        active["barometric_pressure_change"] = {"today_hpa": pressure, "yesterday_hpa": previous_pressure}
    apparent_max = current.get("apparent_temperature_c_max")
    if apparent_max is not None and apparent_max >= 28:
        active["heat_load"] = {"apparent_temperature_c_max": apparent_max}
    temp_min = current.get("temperature_c_min")
    if temp_min is not None and temp_min <= 2:
        active["cold_exposure"] = {"temperature_c_min": temp_min}
    wind = current.get("wind_speed_max_kmh")
    if wind is not None and wind >= 30:
        active["high_wind"] = {"wind_speed_max_kmh": wind}
    return active


def _finding_message(factor: str, domains: List[str], evidence_strength: str, details: Dict[str, Any]) -> str:
    return (
        "%s is active today for %s. Evidence=%s. Treat this as a cautious prompt for domains: %s."
        % (factor, details, evidence_strength, ", ".join(domains))
    )


def _assessment_summary(assessment: Dict[str, Any]) -> str:
    findings = assessment.get("findings") or []
    if findings:
        top = findings[0]
        return (
            "Weather-sensitive factor `%s` is active on %s. OpenHealth flags it only because a matching personal sensitivity is declared or supported; this is not a confident causal claim."
            % (top["factor"], assessment["date"])
        )
    suppressed = assessment.get("suppressed") or []
    return "No confident weather effect is emitted for %s. %s" % (assessment["date"], suppressed[0] if suppressed else "No supported match.")
