import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class CliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "root"
        self.root.mkdir()
        (self.root / "source.py").write_text("print('synthetic')\n", encoding="utf-8")
        self.plan = self.base / "plan.json"
        self.plan.write_text(json.dumps({"version": 1, "files": [{"path": "source.py"}]}), encoding="utf-8")
        self.output = self.base / "bundle"

    def run_cli(self, *args):
        environment = dict(os.environ, PYTHONIOENCODING="utf-8")
        return subprocess.run([sys.executable, "-m", "context_budgetpack", *map(str, args)], capture_output=True, text=True, encoding="utf-8", env=environment, timeout=20)

    def pack(self, *extra):
        return self.run_cli("pack", self.plan, "--root", self.root, "--output", self.output, *extra)

    def test_pack_and_json_verify_success(self):
        packed = self.pack()
        self.assertEqual(packed.returncode, 0, packed.stderr)
        self.assertIn("Packed 1/1", packed.stdout)
        verified = self.run_cli("verify", self.output, "--root", self.root, "--format", "json")
        self.assertEqual(verified.returncode, 0, verified.stderr)
        self.assertTrue(json.loads(verified.stdout)["ok"])

    def test_verify_changed_source_returns_one(self):
        self.assertEqual(self.pack().returncode, 0)
        (self.root / "source.py").write_text("changed\n", encoding="utf-8")
        result = self.run_cli("verify", self.output, "--root", self.root)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("source_changed", result.stdout)

    def test_existing_output_returns_two_and_keeps_files(self):
        self.assertEqual(self.pack().returncode, 0)
        before = (self.output / "context.md").read_bytes()
        repeated = self.pack()
        self.assertEqual(repeated.returncode, 2)
        self.assertIn("context-budgetpack:", repeated.stderr)
        self.assertEqual((self.output / "context.md").read_bytes(), before)

    def test_invalid_json_returns_two_without_traceback(self):
        self.plan.write_text('{"version":', encoding="utf-8")
        result = self.pack()
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("Traceback", result.stderr)
        self.assertFalse(self.output.exists())

    def test_missing_plan_returns_two(self):
        self.plan.unlink()
        self.assertEqual(self.pack().returncode, 2)

    def test_missing_source_returns_two(self):
        (self.root / "source.py").unlink()
        result = self.pack()
        self.assertEqual(result.returncode, 2)
        self.assertFalse(self.output.exists())

    def test_invalid_numeric_budget_returns_two(self):
        for value in ("-1", "1.5", "true", "16777217"):
            with self.subTest(value=value):
                result = self.pack("--max-bytes", value)
                self.assertEqual(result.returncode, 2)
                self.assertNotIn("Traceback", result.stderr)

    def test_zero_budget_succeeds_with_empty_context(self):
        result = self.pack("--max-bytes", "0")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.output / "context.md").read_bytes(), b"")

    def test_missing_manifest_returns_two(self):
        self.assertEqual(self.pack().returncode, 0)
        (self.output / "manifest.json").unlink()
        result = self.run_cli("verify", self.output, "--root", self.root)
        self.assertEqual(result.returncode, 2)

    def test_invalid_manifest_returns_two(self):
        self.assertEqual(self.pack().returncode, 0)
        (self.output / "manifest.json").write_text("[]", encoding="utf-8")
        result = self.run_cli("verify", self.output, "--root", self.root)
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("Traceback", result.stderr)

    def test_version_and_help_are_available(self):
        version = self.run_cli("--version")
        self.assertEqual(version.returncode, 0)
        self.assertEqual(version.stdout.strip(), "context-budgetpack 0.1.0")
        self.assertEqual(self.run_cli("--help").returncode, 0)

    def test_required_arguments_return_two(self):
        self.assertEqual(self.run_cli().returncode, 2)
        self.assertEqual(self.run_cli("pack", self.plan).returncode, 2)


if __name__ == "__main__":
    unittest.main()
