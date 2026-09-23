"""资料检查的行为测试；只使用合成资料。"""
import copy
import importlib.util
import json
from datetime import date
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "skills/bounty-assistant/scripts/profile_readiness.py"
SPEC = importlib.util.spec_from_file_location("profile_readiness", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ProfileReadinessTests(unittest.TestCase):
    def ledger(self, fields=None, any_of=None, completeness="known"):
        return {"schema_version": 1, "projects": [{
            "id": "p-1", "title": "合成比赛", "verified_at": "2026-09-12",
            "requirements": {"personal_data": {"completeness": completeness,
                "fields": fields or [], "any_of": any_of or [],
                "basis": "existing_record", "evidence_urls": []}},
        }]}

    def inspect(self, profile, ledger):
        return MODULE.analyze_profile(profile, ledger, date(2026, 9, 23))["projects"][0]

    def rule(self, key, phase="submission"):
        return {"key": key, "phase": phase, "required": True}

    def test_existing_alternative_avoids_collecting_other_tier_fields(self):
        ledger = self.ledger(any_of=[{"keys": ["hometown", "unit"], "phase": "submission", "required": True}])
        item = self.inspect({"unit": "SYNTHETIC_COMPANY"}, ledger)
        self.assertEqual(item["status"], "data_ready")
        self.assertEqual(item["missing_keys"], [])
        self.assertEqual(item["missing_groups"], [])
        self.assertEqual(item["selected_alternative_keys"], ["unit"])
        # 优先现成的低层级字段；均无时也只建议最低层级的一个字段。
        ledger["projects"][0]["requirements"]["personal_data"]["any_of"][0]["keys"] = ["postal_address", "unit"]
        item = self.inspect({"unit": "UNIT", "postal_address": "ADDRESS"}, ledger)
        self.assertEqual(item["selected_alternative_keys"], ["unit"])
        item = self.inspect({}, ledger)
        self.assertEqual(item["suggested_missing_keys"], ["unit"])
        self.assertEqual(item["missing_groups"], [["postal_address", "unit"]])

    def test_claim_fields_do_not_block_submission_or_request_financial_data(self):
        ledger = self.ledger(fields=[self.rule("name"), self.rule("bank_account", "claim"), self.rule("tax_information", "claim")])
        item = self.inspect({"name": "SYNTHETIC_NAME"}, ledger)
        self.assertEqual(item["status"], "data_ready")
        self.assertEqual(item["required_submission_tiers"], [1])
        self.assertEqual(item["phase_review_keys"], [])
        self.assertNotIn("bank_account", item["missing_keys"])
        ledger["projects"][0]["requirements"]["personal_data"]["fields"][1]["phase"] = "submission"
        item = self.inspect({"name": "SYNTHETIC_NAME"}, ledger)
        self.assertEqual(item["status"], "rules_incomplete")
        self.assertEqual(item["phase_review_keys"], ["bank_account"])
        self.assertNotIn("bank_account", item["missing_keys"])

    def test_partial_or_unknown_rules_cannot_claim_ready(self):
        for completeness in ("partial", "unknown"):
            with self.subTest(completeness=completeness):
                item = self.inspect({"name": "NAME"}, self.ledger(fields=[self.rule("name")], completeness=completeness))
                self.assertEqual(item["status"], "rules_incomplete")
                self.assertEqual(item["missing_keys"], [])
        ledger = self.ledger()
        del ledger["projects"][0]["requirements"]["personal_data"]
        self.assertEqual(self.inspect({}, ledger)["status"], "rules_incomplete")

    def test_unknown_required_key_requires_rule_review_even_if_profile_has_value(self):
        ledger = self.ledger(fields=[self.rule("unrecognized_credential")])
        item = self.inspect({"unrecognized_credential": "VALUE"}, ledger)
        self.assertEqual(item["status"], "rules_incomplete")
        self.assertEqual(item["unknown_keys"], ["unrecognized_credential"])
        ledger = self.ledger(any_of=[{"keys": ["unit", "unknown_alternative"], "phase": "submission", "required": True}])
        item = self.inspect({"unit": "UNIT"}, ledger)
        self.assertEqual(item["status"], "rules_incomplete")
        self.assertEqual(item["unknown_keys"], ["unknown_alternative"])

    def test_blank_or_boolean_values_are_not_personal_data(self):
        for value in (None, "", " \n\t", True, False, 123, {}, []):
            with self.subTest(value=value):
                item = self.inspect({"phone": value}, self.ledger(fields=[self.rule("phone")]))
                self.assertEqual(item["status"], "missing_data")
                self.assertEqual(item["missing_keys"], ["phone"])

    def test_permission_final_review_and_separate_checks_are_not_inferred_from_presence(self):
        ledger = self.ledger(fields=[self.rule("name")])
        item = self.inspect({"name": "NAME", "submission_policy": "require_final_review"}, ledger)
        self.assertIs(item["final_review_required"], True)
        self.assertIs(item["permission_review_required"], True)
        self.assertEqual(item["other_checks"]["rules_freshness"], "requires_recheck")
        self.assertEqual(item["other_checks"]["qualification"], "requires_separate_verification")
        self.assertEqual(item["other_checks"]["ai_policy"], "requires_separate_verification")
        self.assertIsNone(self.inspect({"name": "NAME", "submission_policy": "unrecognized"}, ledger)["final_review_required"])

    def test_cli_privacy_and_files_remain_unchanged_in_both_formats(self):
        profile = {"name": "PRIVATE_PERSON_SENTINEL", "phone": "PRIVATE_PHONE_SENTINEL",
                   "email": "private-email@example.invalid", "id_document": "/private/id-file-sentinel.pdf",
                   "authorization_note": "PRIVATE_NOTE_SENTINEL", "submission_policy": "require_final_review"}
        ledger = self.ledger(fields=[self.rule("name"), self.rule("email"), self.rule("phone")])
        ledger["projects"][0]["submissions"] = [{"body": "PRIVATE_MAIL_SENTINEL"}]
        original_profile, original_ledger = copy.deepcopy(profile), copy.deepcopy(ledger)
        MODULE.analyze_profile(profile, ledger)
        self.assertEqual(profile, original_profile)
        self.assertEqual(ledger, original_ledger)
        with tempfile.TemporaryDirectory() as folder:
            profile_path, ledger_path = Path(folder) / "profile.json", Path(folder) / "ledger.json"
            profile_source, ledger_source = json.dumps(profile), json.dumps(ledger)
            profile_path.write_text(profile_source)
            ledger_path.write_text(ledger_source)
            for output_format in ("json", "table"):
                result = subprocess.run([sys.executable, str(SCRIPT), "--profile", str(profile_path), "--ledger", str(ledger_path), "--format", output_format], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                for private in list(profile.values())[:-1] + ["PRIVATE_MAIL_SENTINEL"]:
                    self.assertNotIn(private, result.stdout + result.stderr)
                if output_format == "json":
                    self.assertEqual(json.loads(result.stdout)["projects"][0]["status"], "data_ready")
                else:
                    self.assertIn("不等于可投稿", result.stdout)
            self.assertEqual(profile_path.read_text(), profile_source)
            self.assertEqual(ledger_path.read_text(), ledger_source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
