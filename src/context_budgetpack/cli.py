"""Command line entry points for local context bundles."""

import argparse
import json
from pathlib import Path
import sys

from . import __version__
from .core import BundleError, DEFAULT_FILE_BYTES, build_bundle, load_plan, verify_bundle, write_bundle


def main(argv=None):
    parser = argparse.ArgumentParser(description="Pack explicitly selected local sources into an exact UTF-8 byte budget.")
    parser.add_argument("--version", action="version", version=f"context-budgetpack {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)
    pack = commands.add_parser("pack", help="create a new context bundle")
    pack.add_argument("plan", type=Path)
    pack.add_argument("--root", type=Path, required=True)
    pack.add_argument("--max-bytes", type=int, default=8192)
    pack.add_argument("--max-file-bytes", type=int, default=DEFAULT_FILE_BYTES)
    pack.add_argument("--output", type=Path, required=True)
    verify = commands.add_parser("verify", help="check a bundle's sources and artifact hashes")
    verify.add_argument("bundle", type=Path)
    verify.add_argument("--root", type=Path, required=True)
    verify.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args(argv)
    try:
        if args.command == "pack":
            context, manifest = build_bundle(load_plan(args.plan), args.root, max_bytes=args.max_bytes,
                                             max_file_bytes=args.max_file_bytes)
            output = write_bundle(context, manifest, args.output)
            selected = sum(entry["status"] == "selected" for entry in manifest["entries"])
            print(f"Packed {selected}/{len(manifest['entries'])} files: {manifest['budget']['used_bytes']} UTF-8 bytes.")
            print(f"Review report: {str(output / 'report.html')!r}")
            return 0
        report = verify_bundle(args.bundle, args.root)
        if args.format == "json":
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print(f"Verification {'passed' if report['ok'] else 'found changes'}: {report['source_files_checked']} sources checked; {report['unhashed_entries']} entries had no source hash.")
            for issue in report["issues"]:
                print(f"- {issue['code']}: {issue['path']}")
        return 0 if report["ok"] else 1
    except (BundleError, OSError, UnicodeError, RecursionError, TypeError, OverflowError) as error:
        print(f"context-budgetpack: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
