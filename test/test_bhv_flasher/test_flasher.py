import importlib.util
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("bhv_flasher", ROOT / "bin" / "bhv-flasher.py")
flasher = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = flasher
SPEC.loader.exec_module(flasher)


class BhvFlasherTests(unittest.TestCase):
    def test_flash_defaults_to_attendee_without_artifact_arguments(self):
        args = flasher.create_parser().parse_args(["flash", "--asset", "001"])
        flasher.normalize_args(args)
        self.assertFalse(args.admin_build)
        self.assertEqual(args.build_type, "attendee")
        self.assertFalse(hasattr(args, "firmware"))
        self.assertFalse(hasattr(args, "expected_info_fingerprint"))

    def test_admin_flag_selects_admin_build(self):
        args = flasher.create_parser().parse_args(["flash", "--asset", "ADMIN-001", "--admin"])
        flasher.normalize_args(args)
        self.assertTrue(args.admin_build)
        self.assertEqual(args.build_type, "admin")

    def test_configured_info_fingerprint_matches_release_value(self):
        self.assertEqual(
            flasher.configured_info_fingerprint(),
            "e928151ff0d445b6f5a7c1ba2d54d333f8e50a913e3204f653a475d0fd98e775",
        )

    def test_badge_names_from_numeric_asset(self):
        self.assertEqual(flasher.badge_names("7"), ("BHV Badge 007", "B007"))
        self.assertEqual(flasher.badge_names("BHV-123"), ("BHV Badge 123", "B123"))

    def test_admin_badge_names_use_admin_identity(self):
        self.assertEqual(
            flasher.badge_names("ADMIN-7", admin_build=True),
            ("BHV Admin 007", "A007"),
        )

    def test_duplicate_asset_pass_is_rejected(self):
        events = [{"asset": "001", "mac": "aa:bb:cc:dd:ee:ff", "status": "PASS"}]
        with self.assertRaises(flasher.FlasherError):
            flasher.enforce_duplicate_policy(
                events,
                asset="001",
                mac="aa:bb:cc:dd:ee:ff",
                allow_reflash=False,
            )

    def test_duplicate_mac_under_new_asset_is_rejected_even_for_rework(self):
        events = [{"asset": "001", "mac": "aa:bb:cc:dd:ee:ff", "status": "PASS"}]
        with self.assertRaises(flasher.FlasherError):
            flasher.enforce_duplicate_policy(
                events,
                asset="002",
                mac="aa:bb:cc:dd:ee:ff",
                allow_reflash=True,
            )

    def test_previously_flashed_mac_is_rejected_before_erase(self):
        artifacts = flasher.FirmwareArtifacts(
            factory=Path("/tmp/factory.bin"),
            filesystem=Path("/tmp/filesystem.bin"),
            metadata=Path("/tmp/metadata.json"),
            filesystem_offset="0xc90000",
            mcu="esp32s3",
            platformio_target="heltec-v4",
            version="test",
            factory_sha256="a" * 64,
            filesystem_sha256="b" * 64,
        )
        args = SimpleNamespace(
            port="/dev/cu.test",
            dry_run=True,
            station="test",
            operator="test",
            build_type="attendee",
            admin_build=False,
            allow_reflash=False,
            baud=921600,
            skip_provision=True,
            boot_wait=0,
            expected_channel=list(flasher.DEFAULT_CHANNELS),
            api_timeout=1,
            records_dir=Path("/tmp/unused-records"),
        )
        prior = [{"asset": "001", "mac": "aa:bb:cc:dd:ee:ff", "status": "PASS"}]
        with (
            mock.patch.object(flasher, "resolve_artifacts", return_value=artifacts),
            mock.patch.object(
                flasher,
                "probe_chip",
                return_value=("aa:bb:cc:dd:ee:ff", "ESP32-S3"),
            ),
            mock.patch.object(flasher, "read_events", return_value=prior),
            mock.patch.object(flasher, "flash_artifacts") as flash_artifacts,
        ):
            self.assertFalse(flasher.flash_one(args, "002"))
            flash_artifacts.assert_not_called()

    def test_failed_attempt_increments_retry_number(self):
        events = [{"asset": "001", "mac": "aa:bb:cc:dd:ee:ff", "status": "FAIL"}]
        self.assertEqual(
            flasher.enforce_duplicate_policy(
                events,
                asset="001",
                mac="aa:bb:cc:dd:ee:ff",
                allow_reflash=False,
            ),
            2,
        )

    def test_next_available_attendee_asset_uses_first_gap(self):
        events = [
            {"asset": "001", "status": "PASS"},
            {"asset": "002", "status": "FAIL"},
            {"asset": "003", "status": "PASS"},
            {"asset": "ADMIN-001", "status": "PASS"},
        ]
        self.assertEqual(flasher.next_available_asset(events, admin_build=False), "002")

    def test_parallel_asset_reservation_returns_unique_ids(self):
        events = [{"asset": "001", "status": "PASS"}]
        self.assertEqual(
            flasher.next_available_assets(
                events,
                admin_build=False,
                count=3,
                reserved={"003"},
            ),
            ["002", "004", "005"],
        )

    def test_next_available_admin_asset_uses_admin_sequence(self):
        events = [
            {"asset": "001", "status": "PASS"},
            {"asset": "ADMIN-001", "status": "PASS"},
        ]
        self.assertEqual(flasher.next_available_asset(events, admin_build=True), "ADMIN-002")

    def test_removed_assignment_is_available_again(self):
        events = [
            {"asset": "ADMIN-001", "mac": "aa:bb:cc:dd:ee:ff", "status": "PASS"},
            {"asset": "ADMIN-001", "mac": "aa:bb:cc:dd:ee:ff", "status": "REMOVED"},
        ]
        self.assertEqual(flasher.next_available_asset(events, admin_build=True), "ADMIN-001")
        self.assertEqual(flasher.next_available_asset(events, admin_build=False), "001")

    def test_removed_mac_can_be_reassigned(self):
        events = [
            {"asset": "ADMIN-004", "mac": "aa:bb:cc:dd:ee:ff", "status": "PASS"},
            {"asset": "ADMIN-004", "mac": "aa:bb:cc:dd:ee:ff", "status": "REMOVED"},
        ]
        self.assertEqual(
            flasher.enforce_duplicate_policy(
                events,
                asset="002",
                mac="aa:bb:cc:dd:ee:ff",
                allow_reflash=False,
            ),
            1,
        )

    def test_station_has_no_asset_argument(self):
        args = flasher.create_parser().parse_args(["station"])
        self.assertFalse(hasattr(args, "asset"))

    def test_secret_build_defines_are_redacted(self):
        line = "-DUSERPREFS_CHANNEL_1_PSK={ 0xaa, 0xbb }\n"
        redacted = flasher.SECRET_DEFINE_RE.sub(r"\1<redacted>", line)
        self.assertEqual(redacted, "-DUSERPREFS_CHANNEL_1_PSK=<redacted>\n")

    def test_append_event_writes_both_audit_formats(self):
        with tempfile.TemporaryDirectory() as directory:
            records = Path(directory)
            event = {
                "timestamp": "2026-07-23T00:00:00+00:00",
                "date_flashed": "2026-07-23T00:00:00+00:00",
                "asset": "001",
                "attempt": 1,
                "status": "PASS",
                "mac": "aa:bb:cc:dd:ee:ff",
                "badge_name": "BHV Badge 001",
                "build_type": "attendee",
                "admin_build": False,
            }
            flasher.append_event(records, event)
            json_event = json.loads((records / "events.jsonl").read_text().strip())
            self.assertEqual(json_event["asset"], "001")
            self.assertIn("asset,attempt,status", (records / "manifest.csv").read_text())
            inventory = json.loads((records / "inventory.json").read_text())
            self.assertEqual(inventory["badges"]["aa:bb:cc:dd:ee:ff"]["badge_name"], "BHV Badge 001")
            self.assertFalse(inventory["badges"]["aa:bb:cc:dd:ee:ff"]["admin_build"])

    def test_successful_reflash_updates_inventory_by_mac(self):
        with tempfile.TemporaryDirectory() as directory:
            records = Path(directory)
            base_event = {
                "timestamp": "2026-07-23T00:00:00+00:00",
                "date_flashed": "2026-07-23T00:00:00+00:00",
                "asset": "001",
                "attempt": 1,
                "status": "PASS",
                "mac": "aa:bb:cc:dd:ee:ff",
                "badge_name": "BHV Badge 001",
                "firmware_version": "old",
                "build_type": "attendee",
                "admin_build": False,
            }
            flasher.append_event(records, base_event)
            updated_event = {
                **base_event,
                "timestamp": "2026-08-01T00:00:00+00:00",
                "date_flashed": "2026-08-01T00:00:00+00:00",
                "attempt": 2,
                "firmware_version": "new",
                "build_type": "admin",
                "admin_build": True,
            }
            flasher.append_event(records, updated_event)

            inventory = json.loads((records / "inventory.json").read_text())
            badge = inventory["badges"]["aa:bb:cc:dd:ee:ff"]
            self.assertEqual(badge["firmware_version"], "new")
            self.assertEqual(badge["date_flashed"], "2026-08-01T00:00:00+00:00")
            self.assertTrue(badge["admin_build"])
            self.assertEqual(len((records / "events.jsonl").read_text().splitlines()), 2)

    def test_parallel_event_writes_preserve_all_inventory_records(self):
        with tempfile.TemporaryDirectory() as directory:
            records = Path(directory)

            def write(number):
                flasher.append_event(
                    records,
                    {
                        "timestamp": f"2026-07-29T00:00:0{number}+00:00",
                        "date_flashed": f"2026-07-29T00:00:0{number}+00:00",
                        "asset": f"{number:03d}",
                        "attempt": 1,
                        "status": "PASS",
                        "mac": f"aa:bb:cc:dd:ee:{number:02x}",
                        "badge_name": f"BHV Badge {number:03d}",
                        "build_type": "attendee",
                        "admin_build": False,
                    },
                )

            threads = [threading.Thread(target=write, args=(number,)) for number in range(1, 5)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            self.assertEqual(len((records / "events.jsonl").read_text().splitlines()), 4)
            inventory = json.loads((records / "inventory.json").read_text())
            self.assertEqual(len(inventory["badges"]), 4)


if __name__ == "__main__":
    unittest.main()
