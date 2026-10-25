import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from context_budgetpack import BundleError, build_bundle, verify_bundle, write_bundle
from context_budgetpack import core
from context_budgetpack.report import render_report


class BundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "sources"
        self.root.mkdir()

    def source(self, name="code.py", text="first\nsecond\nthird\n"):
        target = self.root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(text.encode("utf-8") if isinstance(text, str) else text)
        return target

    def plan(self, *items):
        return {"version": 1, "files": [dict(path=item) if isinstance(item, str) else item for item in items]}

    def bundle(self, plan=None, **options):
        if plan is None:
            self.source()
            plan = self.plan("code.py")
        context, manifest = build_bundle(plan, self.root, **options)
        output = self.base / "bundle"
        write_bundle(context, manifest, output)
        return output, context, manifest

    def update_manifest(self, output, mutate):
        path = output / "manifest.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        mutate(value)
        path.write_text(json.dumps(value), encoding="utf-8")

    def test_round_trip_checks_artifacts_and_source(self):
        output, context, manifest = self.bundle()
        self.assertIn("first\nsecond\nthird", context)
        self.assertEqual(manifest["budget"]["used_bytes"], len(context.encode("utf-8")))
        self.assertEqual(verify_bundle(output, self.root), {
            "ok": True, "source_files_checked": 1, "unhashed_entries": 0, "issues": []})

    def test_exact_budget_includes_markdown_overhead(self):
        self.source(text="汉字\n")
        plan = self.plan("code.py")
        rendered, initial = build_bundle(plan, self.root)
        exact = len(rendered.encode("utf-8"))
        self.assertGreater(exact, len("汉字\n".encode("utf-8")))
        self.assertEqual(build_bundle(plan, self.root, max_bytes=exact)[0], rendered)
        smaller, manifest = build_bundle(plan, self.root, max_bytes=exact - 1)
        self.assertEqual(smaller, "")
        self.assertEqual(manifest["entries"][0]["reason"], "budget")

    def test_zero_budget_still_reports_read_sources(self):
        output, context, manifest = self.bundle(max_bytes=0)
        self.assertEqual(context, "")
        self.assertEqual(manifest["budget"], {"max_bytes": 0, "used_bytes": 0, "remaining_bytes": 0})
        self.assertEqual(manifest["entries"][0]["reason"], "budget")
        self.assertTrue(verify_bundle(output, self.root)["ok"])

    def test_empty_plan_has_valid_empty_artifacts(self):
        output, context, manifest = self.bundle(self.plan())
        self.assertEqual(context, "")
        self.assertEqual(manifest["entries"], [])
        self.assertTrue(verify_bundle(output, self.root)["ok"])

    def test_priority_is_descending_and_ties_keep_plan_order(self):
        for name in ("low.txt", "a.txt", "b.txt"):
            self.source(name, name)
        context, manifest = build_bundle(self.plan(
            {"path": "low.txt", "priority": -1}, {"path": "a.txt", "priority": 10},
            {"path": "b.txt", "priority": 10}), self.root)
        self.assertEqual([entry["path"] for entry in manifest["entries"]], ["a.txt", "b.txt", "low.txt"])
        self.assertLess(context.index("a\\.txt"), context.index("b\\.txt"))

    def test_oversized_fragment_does_not_starve_later_smaller_one(self):
        self.source("large.txt", "x" * 1000)
        self.source("small.txt", "ok")
        context, manifest = build_bundle(self.plan("large.txt", "small.txt"), self.root, max_bytes=100)
        self.assertEqual([entry["reason"] for entry in manifest["entries"]], ["budget", "selected"])
        self.assertIn("ok", context)
        self.assertNotIn("x" * 50, context)

    def test_line_range_is_inclusive_without_silent_truncation(self):
        self.source()
        context, manifest = build_bundle(self.plan({"path": "code.py", "start_line": 2, "end_line": 2}), self.root)
        self.assertIn("second\n", context)
        self.assertNotIn("first", context)
        self.assertNotIn("third", context)
        self.assertEqual((manifest["entries"][0]["start_line"], manifest["entries"][0]["end_line"]), (2, 2))

    def test_out_of_range_fails_build(self):
        self.source(text="one\n")
        for item in ({"path": "code.py", "start_line": 2}, {"path": "code.py", "end_line": 2}):
            with self.subTest(item=item), self.assertRaises(BundleError):
                build_bundle(self.plan(item), self.root)

    def test_final_newline_is_not_an_extra_physical_line(self):
        self.source(text="one\n")
        _, manifest = build_bundle(self.plan("code.py"), self.root)
        self.assertEqual(manifest["entries"][0]["end_line"], 1)

    def test_blank_line_is_not_an_empty_file(self):
        self.source(text="\n")
        context, manifest = build_bundle(self.plan("code.py"), self.root)
        self.assertEqual(manifest["entries"][0]["reason"], "selected")
        self.assertIn("```\n\n```", context)

    def test_bom_crlf_normalize_context_but_hash_raw_bytes(self):
        raw = b"\xef\xbb\xbfalpha\r\nbeta\r\n"
        self.source(text=raw)
        context, manifest = build_bundle(self.plan("code.py"), self.root)
        self.assertIn("alpha\nbeta\n", context)
        self.assertNotIn("\r", context)
        self.assertNotIn("\ufeff", context)
        self.assertEqual(manifest["entries"][0]["source_sha256"], hashlib.sha256(raw).hexdigest())

    def test_lone_carriage_return_does_not_create_line(self):
        self.source(text="one\rtwo\n")
        _, manifest = build_bundle(self.plan("code.py"), self.root)
        self.assertEqual(manifest["entries"][0]["end_line"], 1)

    def test_fence_is_longer_than_source_backtick_runs(self):
        self.source(text="```\ntext\n`````\n")
        context, _ = build_bundle(self.plan("code.py"), self.root)
        self.assertEqual(context.count("``````"), 2)

    def test_empty_binary_and_invalid_utf8_have_distinct_reasons(self):
        self.source("empty", b"")
        self.source("binary", b"valid\0bytes")
        self.source("invalid", b"\xff")
        _, manifest = build_bundle(self.plan("empty", "binary", "invalid"), self.root)
        self.assertEqual([entry["reason"] for entry in manifest["entries"]], ["empty", "binary", "invalid_utf8"])
        self.assertTrue(all(entry["source_sha256"] for entry in manifest["entries"]))

    def test_blocked_names_are_not_opened_even_if_missing(self):
        names = [".env", ".ENV.prod", ".git/config", "x/.ssh/config", ".aws/credentials", ".azure/token", "id_rsa", "ID_ED25519", "key.pem", "key.KEY", "credentials.json", "secrets.json"]
        with patch.object(core, "_source", side_effect=AssertionError("blocked source was accessed")):
            context, manifest = build_bundle(self.plan(*names), self.root)
        self.assertEqual(context, "")
        self.assertTrue(all(entry["reason"] == "blocked_name" and entry["source_sha256"] is None for entry in manifest["entries"]))

    def test_filename_policy_does_not_claim_content_secret_detection(self):
        self.source("ordinary.txt", "SYNTHETIC_TEST_SECRET=sample-value\n")
        context, manifest = build_bundle(self.plan("ordinary.txt"), self.root)
        self.assertIn("SYNTHETIC_TEST_SECRET", context)
        self.assertEqual(manifest["entries"][0]["reason"], "selected")

    def test_file_limit_excludes_without_reading_or_hashing(self):
        self.source(text="12345")
        with patch.object(core, "_read", side_effect=AssertionError("oversized source was read")):
            _, manifest = build_bundle(self.plan("code.py"), self.root, max_file_bytes=4)
        self.assertEqual(manifest["entries"][0]["reason"], "too_large")
        self.assertIsNone(manifest["entries"][0]["source_sha256"])
        self.assertEqual(manifest["source_bytes_read"], 0)

    def test_total_read_limit_preserves_remaining_smaller_sources(self):
        self.source("a", "1234")
        self.source("b", "5678")
        self.source("c", "x")
        with patch.object(core, "MAX_SOURCE_READ_BYTES", 5):
            _, manifest = build_bundle(self.plan("a", "b", "c"), self.root)
        self.assertEqual([entry["reason"] for entry in manifest["entries"]], ["selected", "read_limit", "selected"])
        self.assertEqual(manifest["source_bytes_read"], 5)

    def test_missing_source_stops_build(self):
        with self.assertRaises(FileNotFoundError):
            build_bundle(self.plan("missing.py"), self.root)

    def test_directory_source_stops_build(self):
        (self.root / "directory").mkdir()
        with self.assertRaises(BundleError):
            build_bundle(self.plan("directory"), self.root)

    def test_source_mutated_during_read_is_rejected(self):
        source = self.source()
        initial = source.stat()
        source.write_text("changed", encoding="utf-8")
        with self.assertRaises(BundleError):
            core._read(source, initial, 1024)

    def test_input_is_not_modified(self):
        self.source()
        plan = self.plan("code.py")
        before = copy.deepcopy(plan)
        build_bundle(plan, self.root)
        self.assertEqual(plan, before)
        self.assertEqual((self.root / "code.py").read_bytes(), b"first\nsecond\nthird\n")

    def test_invalid_paths_are_rejected_on_all_platforms(self):
        paths = ["../outside", "dir/../outside", "./a", "a//b", "a/", "/a", "C:/a", "C:a", "\\\\server\\share", "a\\b", "a:b", "a\nb", "a\x00b", "a\x7fb", "a.", "a ", ".. /outside", ".env ", "id_rsa.", "NUL", "CON.txt", "a/AUX.json", "COM1.txt", "lpt9", "com¹.log"]
        for path in paths:
            with self.subTest(path=repr(path)), self.assertRaises(BundleError):
                build_bundle(self.plan(path), self.root)

    def test_windows_alias_paths_cannot_select_blocked_or_outside_data(self):
        outside = self.base / "outside.txt"
        outside.write_text("synthetic outside data", encoding="utf-8")
        self.source(".env", "synthetic blocked data")
        for path in ("../outside.txt", ".. /outside.txt", ".env ", ".env."):
            with self.subTest(path=path), self.assertRaises(BundleError):
                build_bundle(self.plan(path), self.root)

    def test_casefold_duplicates_are_rejected(self):
        with self.assertRaises(BundleError):
            build_bundle(self.plan("a.py", "A.py"), self.root)

    def test_invalid_plan_fields_and_types(self):
        cases = [None, [], {}, {"version": True, "files": []}, {"version": 1.0, "files": []}, {"version": 2, "files": []}, {"version": 1, "files": [], "extra": 1}, {"version": 1, "files": {}}, self.plan({"path": "a", "extra": 1}), self.plan({"path": "a", "priority": True}), self.plan({"path": "a", "priority": 1.5}), self.plan({"path": "a", "start_line": 0}), self.plan({"path": "a", "end_line": 0}), self.plan({"path": "a", "start_line": 3, "end_line": 2}), self.plan({"path": "a", "priority": 1000001})]
        for plan in cases:
            with self.subTest(plan=plan), self.assertRaises(BundleError):
                build_bundle(plan, self.root)

    def test_entry_limit(self):
        with self.assertRaises(BundleError):
            build_bundle(self.plan(*(str(index) for index in range(129))), self.root)

    def test_invalid_budget_and_file_bounds(self):
        for options in ({"max_bytes": -1}, {"max_bytes": True}, {"max_bytes": 1.0}, {"max_bytes": 16777217}, {"max_file_bytes": 0}, {"max_file_bytes": 4194305}, {"max_file_bytes": False}):
            with self.subTest(options=options), self.assertRaises(BundleError):
                build_bundle(self.plan(), self.root, **options)

    def test_json_plan_duplicate_keys_nonfinite_and_oversize_rejected(self):
        path = self.base / "plan.json"
        for raw in (b'{"version":1,"version":1,"files":[]}', b'{"version":NaN,"files":[]}', b"\xff", b"x" * (core.MAX_PLAN_BYTES + 1)):
            path.write_bytes(raw)
            with self.subTest(prefix=raw[:30]), self.assertRaises(BundleError):
                core.load_plan(path)

    def test_json_plan_bom_is_accepted(self):
        path = self.base / "plan.json"
        path.write_bytes(b'\xef\xbb\xbf{"version":1,"files":[]}')
        self.assertEqual(core.load_plan(path), self.plan())

    def test_existing_output_directory_or_file_is_preserved(self):
        self.source()
        context, manifest = build_bundle(self.plan("code.py"), self.root)
        for is_directory in (True, False):
            output = self.base / ("existing-dir" if is_directory else "existing-file")
            if is_directory:
                output.mkdir()
                keep = output / "keep.txt"
                keep.write_text("keep", encoding="utf-8")
            else:
                keep = output
                keep.write_text("keep", encoding="utf-8")
            with self.subTest(directory=is_directory), self.assertRaises(FileExistsError):
                write_bundle(context, manifest, output)
            self.assertEqual(keep.read_text(encoding="utf-8"), "keep")

    def test_changed_context_is_refused_before_output_creation(self):
        self.source()
        context, manifest = build_bundle(self.plan("code.py"), self.root)
        output = self.base / "never-created"
        with self.assertRaises(BundleError):
            write_bundle(context + "changed", manifest, output)
        self.assertFalse(output.exists())

    def test_nested_new_output_is_created(self):
        context, manifest = build_bundle(self.plan(), self.root)
        target = self.base / "a" / "b" / "bundle"
        self.assertEqual(write_bundle(context, manifest, target), target)
        self.assertEqual({path.name for path in target.iterdir()}, {"context.md", "manifest.json", "report.html"})

    def test_source_change_even_outside_selected_lines_is_detected(self):
        self.source()
        output, _, _ = self.bundle(self.plan({"path": "code.py", "start_line": 1, "end_line": 1}))
        self.source(text="first\nnew second\nthird\n")
        report = verify_bundle(output, self.root)
        self.assertFalse(report["ok"])
        self.assertIn({"path": "code.py", "code": "source_changed"}, report["issues"])

    def test_line_endings_change_detected_even_if_context_would_match(self):
        self.source(text=b"one\r\n")
        output, _, _ = self.bundle(self.plan("code.py"))
        self.source(text=b"one\n")
        self.assertEqual(verify_bundle(output, self.root)["issues"][0]["code"], "source_changed")

    def test_hashed_excluded_sources_are_verified(self):
        output, _, _ = self.bundle(max_bytes=0)
        self.source(text="changed\n")
        self.assertFalse(verify_bundle(output, self.root)["ok"])

    def test_unhashed_blocked_entry_is_reported_without_reading(self):
        output, _, _ = self.bundle(self.plan(".env"))
        report = verify_bundle(output, self.root)
        self.assertTrue(report["ok"])
        self.assertEqual(report["unhashed_entries"], 1)
        self.assertEqual(report["source_files_checked"], 0)

    def test_removed_source_is_verification_discrepancy(self):
        output, _, _ = self.bundle()
        (self.root / "code.py").unlink()
        self.assertIn({"path": "code.py", "code": "source_unavailable"}, verify_bundle(output, self.root)["issues"])

    def test_artifact_edits_are_detected_without_rewriting(self):
        output, _, _ = self.bundle()
        for name in ("context.md", "report.html"):
            path = output / name
            before = path.read_bytes()
            path.write_bytes(before + b"changed")
            report = verify_bundle(output, self.root)
            self.assertIn({"path": name, "code": "artifact_changed"}, report["issues"])
            self.assertEqual(path.read_bytes(), before + b"changed")
            path.write_bytes(before)

    def test_removed_artifact_is_verification_discrepancy(self):
        output, _, _ = self.bundle()
        (output / "context.md").unlink()
        self.assertIn({"path": "context.md", "code": "artifact_unavailable"}, verify_bundle(output, self.root)["issues"])

    def test_manifest_priority_edit_invalidates_stale_html(self):
        output, _, _ = self.bundle()
        self.update_manifest(output, lambda value: value["entries"][0].update(priority=100))
        self.assertIn({"path": "report.html", "code": "report_does_not_match_manifest"}, verify_bundle(output, self.root)["issues"])

    def test_manifest_source_line_metadata_edit_is_detected(self):
        output, _, _ = self.bundle()
        self.update_manifest(output, lambda value: value["entries"][0].update(end_line=2))
        self.assertIn({"path": "code.py", "code": "selection_metadata_changed"}, verify_bundle(output, self.root)["issues"])

    def test_manifest_selected_byte_total_must_match_budget(self):
        output, _, _ = self.bundle()
        self.update_manifest(output, lambda value: value["entries"][0].update(block_bytes=1))
        with self.assertRaises(BundleError):
            verify_bundle(output, self.root)

    def test_manifest_read_byte_total_must_match_hashed_sources(self):
        output, _, _ = self.bundle()
        self.update_manifest(output, lambda value: value.update(source_bytes_read=0))
        with self.assertRaises(BundleError):
            verify_bundle(output, self.root)

    def test_malformed_manifest_nested_types_raise_bundle_error(self):
        output, _, manifest = self.bundle()
        cases = [lambda value: value["entries"][0].update(status=[]),
                 lambda value: value["entries"][0].update(reason={}),
                 lambda value: value["limits"].update(max_entries=128.0),
                 lambda value: value["limits"].update(max_total_read_bytes=float(core.MAX_SOURCE_READ_BYTES)),
                 lambda value: value["entries"][0].update(source_bytes=None)]
        for mutate in cases:
            value = copy.deepcopy(manifest)
            mutate(value)
            (output / "manifest.json").write_text(json.dumps(value), encoding="utf-8")
            with self.subTest(value=value), self.assertRaises(BundleError):
                verify_bundle(output, self.root)

    def test_manifest_artifact_paths_cannot_escape_bundle(self):
        output, _, _ = self.bundle()
        self.update_manifest(output, lambda value: value["context"].update(path="../outside.md"))
        with self.assertRaises(BundleError):
            verify_bundle(output, self.root)

    def test_manifest_unknown_fields_and_wrong_version_rejected(self):
        output, _, manifest = self.bundle()
        for mutate in (lambda value: value.update(extra=1), lambda value: value.update(schema_version=True), lambda value: value.update(schema_version=1.0), lambda value: value.update(tool_version="future")):
            value = copy.deepcopy(manifest)
            mutate(value)
            (output / "manifest.json").write_text(json.dumps(value), encoding="utf-8")
            with self.subTest(value=value), self.assertRaises(BundleError):
                verify_bundle(output, self.root)

    def test_report_escapes_source_metadata(self):
        self.source("normal.txt", "content")
        _, manifest = build_bundle(self.plan("normal.txt"), self.root)
        manifest["entries"][0]["path"] = '<img src=x onerror="alert(1)">'
        report = render_report(manifest)
        self.assertIn("&lt;img", report)
        self.assertNotIn("<img", report)
        self.assertNotIn("<script", report.lower())
        self.assertNotIn('src="http', report.lower())

    def test_report_contains_visible_accessible_budget_fill(self):
        self.source()
        _, manifest = build_bundle(self.plan("code.py"), self.root)
        report = render_report(manifest)
        self.assertIn('role="progressbar"', report)
        self.assertIn('aria-valuemax="100"', report)
        self.assertIn('<span></span></div></section>', report)
        self.assertIn(f'aria-valuetext="{manifest["budget"]["used_bytes"]} of 8192 UTF-8 bytes"', report)

    def test_zero_budget_progress_is_finite(self):
        _, manifest = build_bundle(self.plan(), self.root, max_bytes=0)
        report = render_report(manifest)
        self.assertIn('aria-valuenow="0.00"', report)
        self.assertIn('aria-valuetext="0 of 0 UTF-8 bytes"', report)

    def make_link(self, link, target, directory=False):
        try:
            link.symlink_to(target, target_is_directory=directory)
        except (OSError, NotImplementedError) as error:
            self.skipTest(f"Symbolic-link privilege unavailable: {error}")

    def test_source_symlink_is_rejected(self):
        target = self.source("target.py")
        self.make_link(self.root / "link.py", target)
        with self.assertRaises(BundleError):
            build_bundle(self.plan("link.py"), self.root)

    def test_linked_root_ancestor_is_rejected(self):
        target = self.source()
        alias = self.base / "alias"
        self.make_link(alias, self.root, directory=True)
        with self.assertRaises(BundleError):
            build_bundle(self.plan(target.name), alias)

    def test_output_symlink_is_rejected(self):
        target = self.base / "actual-output"
        target.mkdir()
        alias = self.base / "output-alias"
        self.make_link(alias, target, directory=True)
        context, manifest = build_bundle(self.plan(), self.root)
        with self.assertRaises(BundleError):
            write_bundle(context, manifest, alias)
        self.assertEqual(list(target.iterdir()), [])

    def test_artifact_symlink_is_detected_without_reading_target(self):
        output, _, _ = self.bundle()
        path = output / "context.md"
        target = self.base / "outside-artifact"
        target.write_text("synthetic", encoding="utf-8")
        path.unlink()
        self.make_link(path, target)
        self.assertIn({"path": "context.md", "code": "artifact_unavailable"}, verify_bundle(output, self.root)["issues"])


if __name__ == "__main__":
    unittest.main()
