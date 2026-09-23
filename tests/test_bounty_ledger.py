"""Behavior tests for the read-only ledger checker (no mail/network/file writes)."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "skills/bounty-assistant/scripts/ledger_status.py"
SPEC = importlib.util.spec_from_file_location("ledger_status", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class LedgerStatusTests(unittest.TestCase):
    def ledger(self, **overrides):
        item = {
            "id": "contest-1", "title": "测试口号",
            "deadline": {"date": "2026-09-23", "time": None, "timezone": "Asia/Shanghai"},
            "workflow_status": "candidate", "evidence_level": "primary",
            "verified_at": "2026-09-12", "ai_policy": "unspecified", "submissions": [],
        }
        item.update(overrides)
        return {"schema_version": 1, "profile_file": "private-profile.json", "projects": [item]}

    def inspect(self, ledger, at):
        return MODULE.analyze_ledger(ledger, MODULE.parse_at(at))["projects"][0]

    def test_timezone_and_date_only_deadline(self):
        ledger = self.ledger()
        self.assertEqual(self.inspect(ledger, "2026-09-23T15:59:59Z")["time_status"], "deadline_day")
        self.assertEqual(self.inspect(ledger, "2026-09-23T16:00:00Z")["time_status"], "expired")
        self.assertEqual(MODULE.parse_at("2026-09-23").isoformat(), "2026-09-23T00:00:00+08:00")
        with self.assertRaises(MODULE.LedgerError):
            MODULE.parse_at("2026-09-23T10:00:00")
        # A future deadline plus stale primary evidence is never certified as valid.
        item = self.inspect(ledger, "2026-09-22")
        self.assertTrue(any("不代表活动当前有效" in text for text in item["notices"]))
        self.assertTrue(any("早于当前核查日" in text for text in item["notices"]))

    def test_24_hour_boundary_in_local_deadline_timezone(self):
        ledger = self.ledger(deadline={"date": "2026-09-23", "time": "24:00", "timezone": "Asia/Tokyo"})
        self.assertEqual(self.inspect(ledger, "2026-09-23T22:59:59+08:00")["time_status"], "not_due")
        item = self.inspect(ledger, "2026-09-23T23:00:00+08:00")
        self.assertEqual(item["time_status"], "expired")
        self.assertEqual(item["deadline_at"], "2026-09-24T00:00:00+09:00")

    def test_date_only_and_explicit_midnight_are_distinguished(self):
        date_only = self.ledger()
        explicit = self.ledger(deadline={"date": "2026-09-23", "time": "24:00", "timezone": "Asia/Shanghai"})
        for at in ("2026-09-23", "2026-09-23T23:59:59+08:00"):
            with self.subTest(at=at):
                inferred = self.inspect(date_only, at)
                precise = self.inspect(explicit, at)
                self.assertEqual(inferred["time_status"], "deadline_day")
                self.assertEqual(inferred["deadline_precision"], "date")
                self.assertIsNone(inferred["deadline_at"])
                self.assertEqual(inferred["calendar_boundary_at"], "2026-09-24T00:00:00+08:00")
                self.assertEqual(precise["time_status"], "not_due")
                self.assertEqual(precise["deadline_precision"], "time")
                self.assertEqual(precise["deadline_at"], "2026-09-24T00:00:00+08:00")
                self.assertIsNone(precise["calendar_boundary_at"])
        self.assertEqual(self.inspect(date_only, "2026-09-22")["time_status"], "not_due")
        self.assertEqual(self.inspect(date_only, "2026-09-24")["time_status"], "expired")
        self.assertEqual(self.inspect(explicit, "2026-09-24")["time_status"], "expired")

    def test_campaign_pause_is_explicit_in_machine_and_human_outputs(self):
        ledger = self.ledger()
        report = MODULE.analyze_ledger(ledger, MODULE.parse_at("2026-09-23"))
        self.assertIsNone(report["campaign_paused"])
        self.assertIn("暂停状态未知", MODULE.render_table(report))
        ledger["settings"] = {"campaign_paused": False}
        report = MODULE.analyze_ledger(ledger, MODULE.parse_at("2026-09-23"))
        self.assertIs(report["campaign_paused"], False)
        ledger["settings"] = {"campaign_paused": True}
        original = copy.deepcopy(ledger)
        report = MODULE.analyze_ledger(ledger, MODULE.parse_at("2026-09-23"))
        self.assertIs(report["campaign_paused"], True)
        self.assertIn("报名活动已暂停", MODULE.render_table(report))
        self.assertEqual(ledger, original)
        ledger["settings"]["campaign_paused"] = "false"
        with self.assertRaisesRegex(MODULE.LedgerError, "布尔"):
            MODULE.analyze_ledger(ledger, MODULE.parse_at("2026-09-23"))

    def test_expired_submission_keeps_history_and_cli_omits_personal_data(self):
        ledger = self.ledger(workflow_status="submitted", submissions=[{
            "provider": "gmail", "message_id": "provider-id",
            "sent_at": "2026-09-22T12:00:00+08:00", "status": "sent",
            "body": "PRIVATE_MAIL_BODY", "to": "private@example.com",
        }], author_phone="PRIVATE_PHONE")
        original = copy.deepcopy(ledger)
        item = self.inspect(ledger, "2026-09-25")
        self.assertEqual(item["workflow_status"], "submitted")
        self.assertEqual(item["time_status"], "expired")
        self.assertEqual(ledger, original)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "ledger.json"
            source = json.dumps(ledger)
            path.write_text(source)
            result = subprocess.run([sys.executable, str(SCRIPT), "--ledger", str(path), "--at", "2026-09-25", "--format", "json"], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(path.read_text(), source)
            self.assertEqual(json.loads(result.stdout)["projects"][0]["workflow_status"], "submitted")
            for private in ("PRIVATE_MAIL_BODY", "PRIVATE_PHONE", "private@example.com", "provider-id", "private-profile.json"):
                self.assertNotIn(private, result.stdout)

    def test_uncertain_send_requires_lookup_before_retry(self):
        for overrides in ({"workflow_status": "submission_uncertain"}, {"submissions": [{"status": "uncertain"}]}):
            with self.subTest(overrides=overrides):
                item = self.inspect(self.ledger(**overrides), "2026-09-23")
                self.assertTrue(any("先核查" in notice and "不要重发" in notice for notice in item["notices"]))

    def test_duplicate_message_id_and_project_id_rejected(self):
        ledger = self.ledger(submissions=[{"provider": "gmail", "message_id": "same-id"}])
        other = copy.deepcopy(ledger["projects"][0])
        other["id"] = "contest-2"
        ledger["projects"].append(other)
        with self.assertRaisesRegex(MODULE.LedgerError, "message_id"):
            self.inspect(ledger, "2026-09-23")
        other["submissions"][0]["provider"] = "another-mail-provider"
        self.inspect(ledger, "2026-09-23")  # Service-local IDs need not be globally unique.
        other["id"] = "contest-1"
        with self.assertRaisesRegex(MODULE.LedgerError, "重复项目 id"):
            self.inspect(ledger, "2026-09-23")


if __name__ == "__main__":
    unittest.main(verbosity=2)
