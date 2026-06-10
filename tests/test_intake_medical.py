import json
import os
import tempfile
import unittest
from pathlib import Path

from openhealth import index, intake_medical


def _make_doc(tmp: Path, name: str = "discharge.pdf", content: bytes = b"%PDF-1.4 fake discharge") -> Path:
    path = tmp / name
    path.write_bytes(content)
    return path


class IngestMedicalDocTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_ingest_archives_copy_manifest_and_sidecar(self):
        src = _make_doc(self.root)
        entry = intake_medical.ingest_medical_doc(
            self.root, src, "discharge", note="cardiology discharge", date="2026-05-20", doctor="Dr. A"
        )
        self.assertFalse(entry["duplicate"])
        self.assertEqual(entry["type"], "discharge")
        self.assertEqual(entry["date"], "2026-05-20")
        self.assertEqual(entry["doctor"], "Dr. A")
        self.assertFalse(entry["parsed"])  # intake never parses content

        archived = Path(entry["archived_path"])
        self.assertTrue(archived.exists())
        self.assertTrue(str(archived).startswith(str(self.root / "data" / "sources" / "medical")))
        # Naming convention: <date>-<type>-<slug>-<checksum8><ext>
        self.assertTrue(archived.name.startswith("2026-05-20-discharge-discharge-"))
        self.assertTrue(archived.name.endswith(".pdf"))
        self.assertEqual(archived.read_bytes(), src.read_bytes())

        sidecar = archived.with_name(archived.name + ".sidecar.json")
        self.assertTrue(sidecar.exists())
        payload = json.loads(sidecar.read_text(encoding="utf-8"))
        self.assertEqual(payload["checksum"], entry["checksum"])
        self.assertEqual(payload["provenance"]["source_id"], "medical-intake")
        self.assertFalse(payload["privacy"]["shareable"])

        manifest = intake_medical.load_manifest(self.root)
        self.assertEqual(len(manifest["documents"]), 1)
        self.assertEqual(manifest["documents"][0]["id"], entry["id"])

    def test_archived_copy_is_read_only(self):
        src = _make_doc(self.root)
        entry = intake_medical.ingest_medical_doc(self.root, src, "exam")
        archived = Path(entry["archived_path"])
        self.assertFalse(os.access(str(archived), os.W_OK))
        with self.assertRaises(PermissionError):
            archived.write_bytes(b"tampered")
        # Raw stays immutable.
        self.assertEqual(archived.read_bytes(), src.read_bytes())

    def test_reingest_same_content_is_deduped(self):
        src = _make_doc(self.root)
        first = intake_medical.ingest_medical_doc(self.root, src, "discharge")
        again = intake_medical.ingest_medical_doc(self.root, src, "discharge")
        self.assertTrue(again["duplicate"])
        self.assertEqual(again["id"], first["id"])
        self.assertEqual(len(intake_medical.load_manifest(self.root)["documents"]), 1)

    def test_rejects_unknown_type_missing_file_and_bad_date(self):
        src = _make_doc(self.root)
        with self.assertRaises(ValueError):
            intake_medical.ingest_medical_doc(self.root, src, "diagnosis")
        with self.assertRaises(ValueError):
            intake_medical.ingest_medical_doc(self.root, self.root / "missing.pdf", "exam")
        with self.assertRaises(ValueError):
            intake_medical.ingest_medical_doc(self.root, src, "exam", date="not-a-date")

    def test_list_medical_filters_by_type_and_doctor(self):
        intake_medical.ingest_medical_doc(self.root, _make_doc(self.root, "a.pdf", b"a"), "discharge", doctor="Dr. A")
        intake_medical.ingest_medical_doc(
            self.root, _make_doc(self.root, "b.txt", b"b"), "recommendation", doctor="Dr. B"
        )
        intake_medical.ingest_medical_doc(self.root, _make_doc(self.root, "c.jpg", b"c"), "exam", doctor="Dr. A")

        self.assertEqual(len(intake_medical.list_medical(self.root)), 3)
        self.assertEqual(len(intake_medical.list_medical(self.root, doc_type="exam")), 1)
        self.assertEqual(len(intake_medical.list_medical(self.root, doctor="dr. a")), 2)
        only = intake_medical.list_medical(self.root, doc_type="recommendation", doctor="Dr. B")
        self.assertEqual(len(only), 1)
        self.assertTrue(only[0]["archived_path"].endswith(".txt"))
        with self.assertRaises(ValueError):
            intake_medical.list_medical(self.root, doc_type="bogus")


class DoctorNoteTests(unittest.TestCase):
    def test_doctor_note_record_shape(self):
        rec = intake_medical.doctor_note(
            "Recheck ferritin in 3 months.", "2026-06-01", doctor="Dr. A", tags=["ferritin"]
        )
        self.assertEqual(rec["record_type"], "ContextNote")
        self.assertEqual(rec["note_kind"], "doctor_recommendation")
        self.assertEqual(rec["date"], "2026-06-01")
        self.assertEqual(rec["metadata"]["doctor"], "Dr. A")
        self.assertEqual(rec["metadata"]["verbatim"], "Recheck ferritin in 3 months.")
        self.assertIn("ferritin", rec["tags"])
        self.assertIn("doctor", rec["tags"])
        # Verbatim text is preserved, not rephrased.
        self.assertEqual(rec["summary"], "Recheck ferritin in 3 months.")

    def test_doctor_note_validates_inputs(self):
        with self.assertRaises(ValueError):
            intake_medical.doctor_note("   ", "2026-06-01")
        with self.assertRaises(ValueError):
            intake_medical.doctor_note("text", "june 1st")

    def test_same_text_same_date_is_stable_id(self):
        a = intake_medical.doctor_note("Drink more water.", "2026-06-01")
        b = intake_medical.doctor_note("Drink more water.", "2026-06-01")
        c = intake_medical.doctor_note("Drink more water!", "2026-06-01")
        self.assertEqual(a["id"], b["id"])
        self.assertNotEqual(a["id"], c["id"])

    def test_persist_record_writes_to_index(self):
        rec = intake_medical.doctor_note("Recheck ferritin in 3 months.", "2026-06-01", doctor="Dr. A")
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "oh.sqlite3"
            index.init_db(db)
            intake_medical.persist_record(rec, db)
            notes = index.list_records(db, "ContextNote")
            self.assertEqual(len(notes), 1)
            self.assertEqual(notes[0]["id"], rec["id"])


if __name__ == "__main__":
    unittest.main()
