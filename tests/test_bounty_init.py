"""空状态初始化：兼容、隐私、重复调用与中途竞态的行为测试。"""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "skills/bounty-assistant/scripts"
SCRIPT = SCRIPT_DIR / "init_state.py"
SPEC = importlib.util.spec_from_file_location("init_state", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class BountyInitTests(unittest.TestCase):
    def test_first_initialization_is_compatible_with_both_read_only_scripts(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "new-user"
            result = subprocess.run([sys.executable, str(SCRIPT), "--state-dir", str(target)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(str(target), result.stdout)
            self.assertIn("未启用自动提醒", result.stdout)
            self.assertEqual({path.name for path in target.iterdir()}, {"profile.json", "ledger.json"})
            for name in ("ledger_status.py", "profile_readiness.py"):
                command = [sys.executable, str(SCRIPT_DIR / name), "--ledger", str(target / "ledger.json"), "--format", "json"]
                if name == "profile_readiness.py":
                    command.extend(["--profile", str(target / "profile.json")])
                check = subprocess.run(command, capture_output=True, text=True)
                self.assertEqual(check.returncode, 0, check.stderr)
                self.assertEqual(json.loads(check.stdout)["projects"], [])

    def test_repeated_initialization_never_overwrites_existing_state(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder)
            MODULE.initialize_state(target)
            before = {path.name: path.read_bytes() for path in target.iterdir()}
            with self.assertRaisesRegex(MODULE.InitializationError, "已有"):
                MODULE.initialize_state(target)
            self.assertEqual({path.name: path.read_bytes() for path in target.iterdir()}, before)

    def test_single_existing_target_preserves_everything_without_creating_other_file(self):
        for filename in ("profile.json", "ledger.json"):
            with self.subTest(filename=filename), tempfile.TemporaryDirectory() as folder:
                target = Path(folder)
                (target / filename).write_bytes(b"USER_EXISTING_CONTENT\x00")
                (target / "notes.txt").write_bytes(b"UNRELATED_KEEP")
                before = {path.name: path.read_bytes() for path in target.iterdir()}
                with self.assertRaises(MODULE.InitializationError):
                    MODULE.initialize_state(target)
                self.assertEqual({path.name: path.read_bytes() for path in target.iterdir()}, before)

    def test_new_state_contains_no_personal_information_or_history(self):
        with tempfile.TemporaryDirectory() as folder:
            target = MODULE.initialize_state(Path(folder) / "fresh")
            profile = json.loads((target / "profile.json").read_text())
            ledger = json.loads((target / "ledger.json").read_text())
            self.assertEqual(profile, {"schema_version": 1, "submission_policy": "require_final_review", "information_preferences": {"collection_mode": "progressive"}})
            self.assertEqual(ledger, {"schema_version": 1, "profile_file": "profile.json", "settings": {
                "campaign_paused": False, "follow_up": {"enabled": False, "automation_id": None,
                "activation_status": "not_activated", "policy": "on_demand_until_activated"}}, "projects": []})
            self.assertFalse((target / "config.local.json").exists())

    def test_file_appearing_midway_is_not_overwritten_or_removed(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder)
            real_open = os.open

            def competing_open(path, flags, mode=0o777):
                if Path(path).name == "ledger.json":
                    (target / "ledger.json").write_bytes(b"OTHER_WRITER_LEDGER")
                return real_open(path, flags, mode)

            with patch.object(MODULE.os, "open", side_effect=competing_open):
                with self.assertRaises(MODULE.InitializationError):
                    MODULE.initialize_state(target)
            self.assertFalse((target / "profile.json").exists())
            self.assertEqual((target / "ledger.json").read_bytes(), b"OTHER_WRITER_LEDGER")

    def test_cleanup_does_not_delete_a_file_replaced_by_another_writer(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder)
            real_open = os.open

            def failing_open(path, flags, mode=0o777):
                if Path(path).name == "ledger.json":
                    replacement = target / "replacement.tmp"
                    replacement.write_bytes(b"USER_REPLACEMENT_PROFILE")
                    replacement.replace(target / "profile.json")
                    raise OSError("simulated second file failure")
                return real_open(path, flags, mode)

            with patch.object(MODULE.os, "open", side_effect=failing_open):
                with self.assertRaises(MODULE.InitializationError):
                    MODULE.initialize_state(target)
            self.assertEqual((target / "profile.json").read_bytes(), b"USER_REPLACEMENT_PROFILE")
            self.assertFalse((target / "ledger.json").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
