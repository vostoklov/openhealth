import json
import tempfile
import unittest
from pathlib import Path

from openhealth import index
from openhealth.circadian import build_circadian_plan, record_morning_light_checkin, sync_circadian_schedule
from openhealth.connectors.google_calendar import ensure_derived_calendar, sync_google_calendar
from openhealth.ingest import init_workspace
from openhealth.storage import ensure_repo_structure, write_json
from openhealth.weather_insights import assess_weather_impact, sync_weather_assessment
from openhealth.whoop import sync_whoop


class FakeWhoopClient:
    def get_profile(self):
        return {"user_id": 123}

    def get_body_measurements(self):
        return {}

    def list_cycles(self, start, end):
        return [{"records": [{"id": 1, "start": "2026-04-20T00:00:00Z", "end": "2026-04-20T23:59:59Z"}]}]

    def list_recoveries(self, start, end):
        return [{"records": [{"cycle_id": 1, "created_at": "2026-04-20T06:15:00Z", "score": {"recovery_score": 74}}]}]

    def list_sleeps(self, start, end):
        return [
            {
                "records": [
                    {
                        "id": 1001,
                        "start": "2026-04-19T22:50:00Z",
                        "end": "2026-04-20T06:40:00Z",
                        "score": {"sleep_performance_percentage": 90},
                        "sleep_stage_summary": {"total_in_bed_time_milli": 28200000},
                    },
                    {
                        "id": 1002,
                        "start": "2026-04-18T22:40:00Z",
                        "end": "2026-04-19T06:35:00Z",
                        "score": {"sleep_performance_percentage": 88},
                        "sleep_stage_summary": {"total_in_bed_time_milli": 28500000},
                    },
                ]
            }
        ]

    def list_workouts(self, start, end):
        return [{"records": []}]


class FakeEnvironmentService:
    def daily_context(self, date_value, location=None, latitude=None, longitude=None, timezone_name="UTC"):
        if date_value == "2026-04-20":
            return {
                "provider": "static",
                "location": location or "Tbilisi",
                "date": date_value,
                "timezone": timezone_name,
                "sunrise": "2026-04-20T06:18:00+04:00",
                "sunset": "2026-04-20T19:48:00+04:00",
                "daylight_duration_seconds": 48600,
                "temperature_c_max": 27,
                "temperature_c_min": 12,
                "apparent_temperature_c_max": 29,
                "precipitation_mm": 0,
                "weather_code": 1,
                "wind_speed_max_kmh": 34,
                "humidity_relative": {"avg": 32, "min": 24, "max": 48},
                "surface_pressure_hpa": {"avg": 1004, "min": 1002, "max": 1007},
            }
        if date_value == "2026-04-19":
            return {
                "provider": "static",
                "location": location or "Tbilisi",
                "date": date_value,
                "timezone": timezone_name,
                "sunrise": "2026-04-19T06:20:00+04:00",
                "sunset": "2026-04-19T19:46:00+04:00",
                "daylight_duration_seconds": 48400,
                "temperature_c_max": 21,
                "temperature_c_min": 10,
                "apparent_temperature_c_max": 22,
                "precipitation_mm": 0,
                "weather_code": 1,
                "wind_speed_max_kmh": 12,
                "humidity_relative": {"avg": 46, "min": 39, "max": 57},
                "surface_pressure_hpa": {"avg": 1013, "min": 1011, "max": 1015},
            }
        return None


class FakeCalendarClient:
    def __init__(self):
        self.calendars = {
            "primary": {"id": "primary", "summary": "Personal", "primary": True, "accessRole": "owner"},
            "work": {"id": "work", "summary": "Work", "primary": False, "accessRole": "reader"},
        }
        self.events = {
            "primary": [
                {
                    "id": "personal-1",
                    "summary": "Deep work",
                    "status": "confirmed",
                    "start": {"dateTime": "2026-04-20T09:00:00+04:00"},
                    "end": {"dateTime": "2026-04-20T11:00:00+04:00"},
                }
            ],
            "work": [
                {
                    "id": "work-1",
                    "summary": "Client calls",
                    "status": "confirmed",
                    "start": {"dateTime": "2026-04-20T13:00:00+04:00"},
                    "end": {"dateTime": "2026-04-20T15:30:00+04:00"},
                }
            ],
        }
        self.upserts = []
        self.deletes = []

    def calendar_list(self):
        return list(self.calendars.values())

    def list_events(self, calendar_id, time_min, time_max):
        return list(self.events.get(calendar_id, []))

    def create_calendar(self, summary, description, time_zone):
        payload = {"id": "derived-openhealth", "summary": summary, "description": description, "timeZone": time_zone, "accessRole": "owner"}
        self.calendars[payload["id"]] = payload
        self.events[payload["id"]] = []
        return payload

    def upsert_event(self, calendar_id, event_id, payload):
        if calendar_id not in self.events:
            self.events[calendar_id] = []
        item = dict(payload)
        item["id"] = event_id
        existing = [event for event in self.events[calendar_id] if event["id"] != event_id]
        existing.append(item)
        self.events[calendar_id] = existing
        self.upserts.append((calendar_id, event_id))
        return item

    def delete_event(self, calendar_id, event_id):
        self.events[calendar_id] = [event for event in self.events.get(calendar_id, []) if event["id"] != event_id]
        self.deletes.append((calendar_id, event_id))


class CalendarCircadianWeatherTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        init_workspace(self.root)
        self.paths = ensure_repo_structure(self.root)
        config = json.loads(self.paths.google_calendar_config_path.read_text(encoding="utf-8"))
        config["selected_calendar_ids"] = ["primary", "work"]
        config["timezone"] = "Asia/Tbilisi"
        config["home_location"] = {"label": "Tbilisi", "latitude": 41.7151, "longitude": 44.8271}
        write_json(self.paths.google_calendar_config_path, config)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_calendar_sync_and_circadian_writeback(self):
        calendar_client = FakeCalendarClient()
        sync_result = sync_google_calendar(
            root=self.root,
            start="2026-04-20T00:00:00Z",
            end="2026-04-21T00:00:00Z",
            client=calendar_client,
        )
        self.assertEqual(sync_result["selected_calendar_ids"], ["primary", "work"])
        records = index.list_records(self.paths.db_path)
        density = [record for record in records if record.get("metric_name") == "busy_minutes"]
        self.assertTrue(density)

        sync_whoop(
            root=self.root,
            start="2026-04-18T00:00:00Z",
            end="2026-04-21T00:00:00Z",
            client=FakeWhoopClient(),
        )
        record_morning_light_checkin(self.root, "2026-04-20T06:55:00+04:00", duration_minutes=20, source="manual")
        derived = ensure_derived_calendar(self.root, client=calendar_client)
        self.assertEqual(derived["id"], "derived-openhealth")

        plan = build_circadian_plan(self.root, "2026-04-20", environment_service=FakeEnvironmentService())
        self.assertEqual(plan["date"], "2026-04-20")
        self.assertEqual(len(plan["phases"]), 5)
        self.assertGreater(plan["confidence"], 0.4)
        self.assertIn("Hypothetical circadian windows", plan["hypothesis"]["summary"])
        # Rise-style energy schedule rides on the SAME sleep anchor.
        energy = plan["energy"]
        self.assertEqual(len(energy["curve"]), 96)
        self.assertEqual(len(energy["phases"]), 7)
        self.assertIn("melatonin_window", energy)
        self.assertEqual(energy["wake_time"][11:16], "%02d:%02d" % divmod(plan["anchor"]["wake_minutes"], 60))
        self.assertTrue(all(p["advice_ru"] for p in energy["phases"]))

        writeback = sync_circadian_schedule(
            self.root,
            start_date="2026-04-20",
            end_date="2026-04-20",
            client=calendar_client,
            environment_service=FakeEnvironmentService(),
        )
        self.assertEqual(writeback["generated_events"], 5)
        self.assertEqual(writeback["deleted_events"], 0)
        self.assertTrue(all(calendar_id == "derived-openhealth" for calendar_id, _ in calendar_client.upserts))
        self.assertEqual(len(calendar_client.events["derived-openhealth"]), 5)

    def test_weather_assessment_is_evidence_gated(self):
        profile = {
            "declared_sensitivities": ["dry_eyes", "migraine"],
            "personally_supported_signals": [],
        }
        write_json(self.paths.weather_susceptibility_path, profile)
        assessment = assess_weather_impact(
            self.root,
            date_value="2026-04-20",
            environment_service=FakeEnvironmentService(),
        )
        active = assessment["active_factors"]
        self.assertIn("low_relative_humidity", active)
        self.assertIn("barometric_pressure_change", active)
        self.assertTrue(assessment["findings"])

        synced = sync_weather_assessment(
            self.root,
            date_value="2026-04-20",
            environment_service=FakeEnvironmentService(),
        )
        self.assertEqual(synced["date"], "2026-04-20")
        insight = [record for record in index.list_records(self.paths.db_path) if record["source_id"] == "weather-intelligence"]
        self.assertTrue(insight)


if __name__ == "__main__":
    unittest.main()
