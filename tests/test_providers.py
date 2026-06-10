import unittest

from openhealth import providers


class CatalogValidityTests(unittest.TestCase):
    def test_catalog_loads_and_is_valid(self):
        problems = providers.validate_catalog()
        self.assertEqual(problems, [], "catalog schema problems: %s" % problems)

    def test_catalog_has_version_and_updated(self):
        payload = providers.catalog()
        self.assertIsInstance(payload["version"], int)
        self.assertIn("updated", payload)
        self.assertIn("providers", payload)

    def test_all_required_fields_present(self):
        for entry in providers.load_providers():
            for field in providers.REQUIRED_FIELDS:
                self.assertIn(field, entry, "%s missing %s" % (entry.get("id"), field))

    def test_unique_ids(self):
        ids = [p["id"] for p in providers.load_providers()]
        self.assertEqual(len(ids), len(set(ids)), "duplicate provider ids")

    def test_urls_are_https(self):
        for entry in providers.load_providers():
            for field in ("dev_portal_url", "docs_url"):
                value = entry[field]
                if value is not None:
                    self.assertTrue(
                        value.startswith("https://"),
                        "%s.%s is not https: %r" % (entry["id"], field, value),
                    )

    def test_enums(self):
        for entry in providers.load_providers():
            self.assertIn(entry["category"], providers.CATEGORIES)
            self.assertIn(entry["auth"], providers.AUTH_KINDS)
            self.assertIn(entry["status"], providers.STATUSES)

    def test_supported_providers_have_key_steps_and_connector(self):
        supported = providers.by_status("supported")
        self.assertTrue(supported, "expected at least one supported provider")
        for entry in supported:
            self.assertGreaterEqual(
                len(entry["key_steps"]), 2,
                "%s: supported provider needs >=2 key_steps" % entry["id"],
            )
            self.assertTrue(entry["connector"], "%s: supported provider needs a connector path" % entry["id"])

    def test_every_provider_documents_steps_and_data(self):
        for entry in providers.load_providers():
            self.assertGreaterEqual(len(entry["key_steps"]), 2, entry["id"])
            self.assertTrue(entry["data_types"], entry["id"])
            self.assertTrue(entry["rate_limit_note"].strip(), entry["id"])


class CatalogCoverageTests(unittest.TestCase):
    def test_expected_core_providers_present(self):
        ids = {p["id"] for p in providers.load_providers()}
        for expected in (
            "whoop", "oura", "garmin", "fitbit", "polar", "withings",
            "dexcom", "awair", "airthings", "netatmo", "home_assistant",
            "apple_health",
        ):
            self.assertIn(expected, ids)

    def test_honest_export_only_providers(self):
        # Providers with no official open API must not pretend to have one.
        for pid in ("xiaomi_mi_fitness", "eufy", "freestyle_libre", "samsung_health"):
            entry = providers.get_provider(pid)
            self.assertIsNotNone(entry, pid)
            self.assertEqual(entry["status"], "export_only", pid)
            self.assertIsNone(entry["api_base"], pid)

    def test_all_categories_covered(self):
        cats = {p["category"] for p in providers.load_providers()}
        self.assertEqual(cats, set(providers.CATEGORIES))


class AccessorTests(unittest.TestCase):
    def test_get_provider_known_and_unknown(self):
        whoop = providers.get_provider("whoop")
        self.assertIsNotNone(whoop)
        self.assertEqual(whoop["label"], "WHOOP")
        self.assertIsNone(providers.get_provider("nope_no_such_thing"))

    def test_get_provider_normalizes_case_and_space(self):
        self.assertIsNotNone(providers.get_provider("  WHOOP "))

    def test_by_category_and_status(self):
        trackers = providers.by_category("tracker")
        self.assertTrue(all(p["category"] == "tracker" for p in trackers))
        self.assertTrue(trackers)
        planned = providers.by_status("planned")
        self.assertTrue(all(p["status"] == "planned" for p in planned))

    def test_summary_counts_add_up(self):
        info = providers.summary()
        self.assertEqual(info["total"], len(providers.load_providers()))
        self.assertEqual(sum(info["by_category"].values()), info["total"])
        self.assertEqual(sum(info["by_status"].values()), info["total"])
        self.assertIn("whoop", info["supported_ids"])

    def test_validate_catalog_flags_broken_payload(self):
        broken = {
            "version": "one",
            "providers": [
                {
                    "id": "Bad Id!",
                    "label": "",
                    "category": "spaceship",
                    "auth": "magic",
                    "status": "vaporware",
                    "api_base": "ftp://nope",
                    "dev_portal_url": "http://insecure.example",
                    "docs_url": None,
                    "key_steps": [],
                    "data_types": [],
                    "rate_limit_note": "",
                    "connector": 42,
                    "env_vars": "not-a-list",
                }
            ],
        }
        problems = providers.validate_catalog(broken)
        self.assertTrue(problems)
        joined = "\n".join(problems)
        for fragment in ("version", "category", "auth", "status", "dev_portal_url", "key_steps", "env_vars"):
            self.assertIn(fragment, joined)


if __name__ == "__main__":
    unittest.main()
