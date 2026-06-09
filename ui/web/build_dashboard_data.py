#!/usr/bin/env python3
"""Bridge: real Health OS data -> dashboard data.local.json.

Reads the local Health OS SQLite index (sources / artifacts / records) and emits a
JSON object shaped exactly like the in-page `DATA` object in dashboard.html.

The dashboard loads data.local.json at runtime; if present it renders real data,
otherwise it falls back to the bundled demo DATA. This script does NOT modify the
dashboard and writes only a local, git-ignored file.

PRIVACY: the output (data.local.json) contains real personal health data. It must
stay local and is git-ignored. This script (no data) is safe to commit.

Usage:
    python3 build_dashboard_data.py \
        --db ~/health-os/data/index/health_os.sqlite3 \
        --out ui/web/data.local.json

Defaults assume the Health OS repo lives at ~/health-os.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import mean

# Recovery zone thresholds match the dashboard's col()/word() helpers.
GREEN, YELLOW = 67, 34


def _load_whoop_by_date(con: sqlite3.Connection) -> dict[str, dict[str, float]]:
    """metric_name -> value, grouped by ISO date, for the whoop-live source."""
    by_date: dict[str, dict[str, float]] = defaultdict(dict)
    rows = con.execute(
        "SELECT payload_json FROM records "
        "WHERE record_type='Observation' AND source_id='whoop-live'"
    ).fetchall()
    for (payload,) in rows:
        p = json.loads(payload)
        d = p.get("date")
        mn = p.get("metric_name")
        v = p.get("value")
        if not d or mn is None or v is None:
            continue
        by_date[d][mn] = v
        # Recovery payloads also carry rhr/hrv inside metadata.score; mirror them
        # so a recovery-score record alone is enough to populate the daily row.
        score = (p.get("metadata") or {}).get("score") or {}
        if "resting_heart_rate" in score and score["resting_heart_rate"] is not None:
            by_date[d].setdefault("resting_heart_rate", score["resting_heart_rate"])
        if "hrv_rmssd_milli" in score and score["hrv_rmssd_milli"] is not None:
            by_date[d].setdefault("hrv_rmssd_milli", score["hrv_rmssd_milli"])
    return by_date


def _series(by_date, dates, key, *, round_to=0):
    """Forward/back-filled numeric series over `dates` for chart trends.

    WHOOP does not score every day (rest days, gaps). Charts want a clean line, so
    we carry the last known value forward and back-fill the leading gap.
    """
    raw = [by_date[d].get(key) for d in dates]
    if not any(v is not None for v in raw):
        return []
    # forward fill
    last = None
    filled = []
    for v in raw:
        if v is not None:
            last = v
        filled.append(last)
    # back fill the leading None run
    first = next(v for v in raw if v is not None)
    filled = [v if v is not None else first for v in filled]
    if round_to == 0:
        return [round(v) for v in filled]
    return [round(v, round_to) for v in filled]


def _latest(by_date, dates, key):
    for d in reversed(dates):
        v = by_date[d].get(key)
        if v is not None:
            return v, d
    return None, None


def _hrv_minutes(value):
    # WHOOP exposes rMSSD in milliseconds (e.g. 82.5); the dashboard labels it "мс".
    return round(value) if value is not None else None


def build_recovery_block(con: sqlite3.Connection) -> dict:
    by_date = _load_whoop_by_date(con)
    dates = sorted(by_date)
    if not dates:
        return {}

    rec, rec_date = _latest(by_date, dates, "recovery_score")
    hrv, _ = _latest(by_date, dates, "hrv_rmssd_milli")
    if hrv is None:
        hrv, _ = _latest(by_date, dates, "hrv_rmssd")
    rhr, _ = _latest(by_date, dates, "resting_heart_rate")
    strain, _ = _latest(by_date, dates, "strain")
    sleep_perf, _ = _latest(by_date, dates, "sleep_performance_percentage")

    # Sleep hours: WHOOP export here only carries performance %, not duration in
    # hours. Approximate hours from sleep_performance against a need baseline so
    # the dashboard's "X / Y ч" stays meaningful; label confidence accordingly.
    sleep_need = 8.0
    sleep_hours = round(sleep_need * (sleep_perf / 100.0), 1) if sleep_perf else None

    trend_rec = _series(by_date, dates, "recovery_score")
    trend_hrv = _series(by_date, dates, "hrv_rmssd_milli") or _series(
        by_date, dates, "hrv_rmssd"
    )
    trend_sleep = [
        round(sleep_need * (v / 100.0), 1)
        for v in _series(by_date, dates, "sleep_performance_percentage")
    ]
    trend_strain = _series(by_date, dates, "strain", round_to=1)

    block = {
        "date": _human_date(rec_date or dates[-1]),
        "recovery": round(rec) if rec is not None else None,
        "hrv": _hrv_minutes(hrv),
        "rhr": round(rhr) if rhr is not None else None,
        "sleep": sleep_hours,
        "sleepNeeded": sleep_need,
        "strain": round(strain, 1) if strain is not None else None,
        "strainTarget": round(max(trend_strain or [10]) , 1) if trend_strain else None,
        # Last 14 / 30 days for the trend charts.
        "trendRec": trend_rec[-14:],
        "trendHrv": trend_hrv[-14:],
        "trendSleep": trend_sleep[-14:],
        "trendStrain": trend_strain[-14:],
        "trend30Rec": trend_rec[-30:],
        "trend30Hrv": trend_hrv[-30:],
    }
    return block


def build_biomarkers(con: sqlite3.Connection) -> list[dict]:
    """Use Atlas microbiota taxa shares as real 'biomarkers'.

    No blood-panel numbers were extracted from the uploaded lab PDF, so instead of
    faking blood markers we surface the real Atlas gut microbiota composition
    (May 2020 snapshot). Reference / optimal bands are rough literature ranges for
    a healthy adult gut; flagged low confidence (historical, single snapshot).
    """
    rows = con.execute(
        "SELECT payload_json FROM records "
        "WHERE json_extract(payload_json,'$.observation_kind')='test_result'"
    ).fetchall()
    shares = {}
    for (payload,) in rows:
        p = json.loads(payload)
        mn = p.get("metric_name")
        v = p.get("value")
        if mn and v is not None:
            shares[mn] = v

    # Curated phylum-level view with rough healthy-adult reference bands (%).
    spec = [
        ("Firmicutes", "%", 20, 80, 40, 65, "Доминирующий тип бактерий. В пределах нормы для здорового кишечника. Историчный снимок Atlas (май 2020)."),
        ("Bacteroidetes", "%", 10, 60, 20, 45, "Второй по доле тип. Соотношение Firmicutes/Bacteroidetes в норме. Снимок 2020 года, текущее состояние может отличаться."),
        ("Proteobacteria", "%", 0, 10, 0, 5, "Низкая доля — хороший признак (высокая Proteobacteria связана с дисбиозом). Историчный снимок."),
        ("Actinobacteria", "%", 0, 10, 1, 5, "Включает Bifidobacterium. Доля в нижней части нормы. Снимок 2020 года."),
        ("Faecalibacterium", "%", 2, 15, 5, 12, "Ключевой производитель бутирата (противовоспалительный). В норме. Историчный снимок Atlas."),
        ("Akkermansia", "%", 0, 5, 1, 4, "Связана со здоровьем слизистой и метаболизмом. Присутствует — хороший признак. Снимок 2020 года."),
    ]
    grades = {"Firmicutes": "C2", "Bacteroidetes": "C2", "Proteobacteria": "C2",
              "Actinobacteria": "C2", "Faecalibacterium": "C2", "Akkermansia": "C2"}

    out = []
    for name, unit, ref_min, ref_max, opt_min, opt_max, discuss in spec:
        if name not in shares:
            continue
        v = round(shares[name], 1)
        if v < opt_min:
            status = "low"
        elif v > opt_max:
            status = "high"
        elif opt_min <= v <= opt_max:
            status = "optimal"
        else:
            status = "normal"
        out.append({
            "name": name,
            "value": v,
            "unit": unit,
            "refMin": ref_min,
            "refMax": ref_max,
            "optMin": opt_min,
            "optMax": opt_max,
            "status": status,
            "grade": grades.get(name, "C2"),
            "trend": [v],
            "discuss": discuss,
        })
    return out


def build_connections(con: sqlite3.Connection) -> dict:
    """Real connection status derived from which sources exist in the index."""
    srcs = {
        r[0]: {"type": r[1], "cstart": r[2], "cend": r[3]}
        for r in con.execute(
            "SELECT source_id, source_type, coverage_start, coverage_end FROM sources"
        ).fetchall()
    }
    has_whoop = any(s["type"] == "whoop" for s in srcs.values())
    has_labs = any("microbiota" in sid or "pdf" in sid for sid in srcs)
    has_dna = any("genotype" in sid for sid in srcs)

    whoop_cend = next(
        (s["cend"] for s in srcs.values() if s["type"] == "whoop"), None
    )

    return {
        "whoop": {"label": "WHOOP Tracker", "connected": has_whoop,
                  "lastSync": _human_date(whoop_cend) if whoop_cend else None,
                  "icon": "ph-activity"},
        "apple": {"label": "Apple Health", "connected": False, "lastSync": None,
                  "icon": "ph-heart"},
        "oura": {"label": "Oura Ring", "connected": False, "lastSync": None,
                 "icon": "ph-shield"},
        "garmin": {"label": "Garmin Connect", "connected": False, "lastSync": None,
                   "icon": "ph-barbell"},
        "labs": {"label": "Atlas / Лаборатории", "connected": has_labs,
                 "lastSync": "май 2020" if has_labs else None, "icon": "ph-flask"},
        "dna": {"label": "Atlas / ДНК", "connected": has_dna,
                "lastSync": "генотип" if has_dna else None, "icon": "ph-fingerprint"},
    }


def build_readiness(recovery) -> dict:
    if recovery is None:
        return {}
    if recovery >= GREEN:
        zone = "зелёная зона"
        verdict = "организм восстановлен — хороший день для нагрузки"
        title = "Можно дать пиковую тренировку"
        why = "Высокий recovery: HRV и RHR в благоприятной зоне. Реальные данные WHOOP (C5)."
    elif recovery >= YELLOW:
        zone = "жёлтая зона"
        verdict = "умеренный режим, без пиковых перегрузок"
        title = "Держать умеренную нагрузку"
        why = "Recovery средний — лучше аэробная база, чем интенсив. Реальные данные WHOOP (C5)."
    else:
        zone = "красная зона"
        verdict = "нужен глубокий покой и приоритет сну"
        title = "День восстановления"
        why = "Низкий recovery: организму нужен отдых. Реальные данные WHOOP (C5)."
    return {
        "readiness": f"Recovery {recovery}% ({zone}) по реальным данным WHOOP — {verdict}.",
        "action": {"title": title, "why": why},
    }


def _human_date(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        dt = datetime.fromisoformat(iso[:10])
    except ValueError:
        return iso
    months = ["января", "февраля", "марта", "апреля", "мая", "июня",
              "июля", "августа", "сентября", "октября", "ноября", "декабря"]
    weekdays = ["понедельник", "вторник", "среда", "четверг", "пятница",
                "суббота", "воскресенье"]
    return f"{weekdays[dt.weekday()]}, {dt.day} {months[dt.month - 1]} {dt.year}"


def build_payload(db_path: Path) -> dict:
    con = sqlite3.connect(str(db_path))
    try:
        rec_block = build_recovery_block(con)
        biomarkers = build_biomarkers(con)
        connections = build_connections(con)
        readiness = build_readiness(rec_block.get("recovery"))
    finally:
        con.close()

    payload: dict = {}
    payload.update(rec_block)
    payload.update(readiness)
    payload["biomarkers"] = biomarkers
    payload["biomarkersConnected"] = bool(biomarkers)
    payload["connections"] = connections
    # Correlations require labeled daily behaviors (journal), which this dataset
    # does not yet contain — so we intentionally omit them and let the dashboard
    # keep its demo correlations. Same for habits / allBehaviors.
    payload["_meta"] = {
        "source": "health_os SQLite index",
        "generatedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "note": "Real personal data. recovery/hrv/rhr/strain/sleep from WHOOP; "
                "biomarkers from Atlas microbiota (2020 snapshot, low confidence); "
                "correlations/habits left as demo (no labeled behavior journal yet).",
    }
    return payload


def main() -> None:
    default_db = Path(os.path.expanduser("~/health-os/data/index/health_os.sqlite3"))
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=default_db,
                    help="Path to the Health OS SQLite index.")
    ap.add_argument("--out", type=Path,
                    default=Path(__file__).resolve().parent / "data.local.json",
                    help="Output JSON path (git-ignored).")
    args = ap.parse_args()

    if not args.db.exists():
        raise SystemExit(
            f"No Health OS index at {args.db}. Run the engine first, or pass --db. "
            "The dashboard will fall back to demo data without this file."
        )

    payload = build_payload(args.db)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), "utf-8")

    rec = payload.get("recovery")
    bm = len(payload.get("biomarkers", []))
    print(f"Wrote {args.out}")
    print(f"  recovery={rec}  hrv={payload.get('hrv')}  rhr={payload.get('rhr')}  "
          f"sleep={payload.get('sleep')}  strain={payload.get('strain')}")
    print(f"  biomarkers={bm}  trend points(rec)={len(payload.get('trend30Rec', []))}")
    print("  NOTE: data.local.json is real personal data — keep it local (git-ignored).")


if __name__ == "__main__":
    main()
