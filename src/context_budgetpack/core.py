"""Build and verify explicit, bounded, local context bundles."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Any


MAX_ENTRIES = 128
MAX_PLAN_BYTES = 256 * 1024
MAX_MANIFEST_BYTES = 2 * 1024 * 1024
MAX_CONTEXT_BYTES = 16 * 1024 * 1024
MAX_FILE_BYTES = 4 * 1024 * 1024
DEFAULT_FILE_BYTES = 1024 * 1024
MAX_SOURCE_READ_BYTES = 32 * 1024 * 1024
MAX_REPORT_BYTES = 2 * 1024 * 1024
REASONS = {"selected", "budget", "blocked_name", "too_large", "read_limit", "binary", "invalid_utf8", "empty"}
ENTRY_KEYS = {"plan_index", "path", "priority", "requested_start_line", "requested_end_line", "status",
              "reason", "source_bytes", "source_sha256", "start_line", "end_line", "snippet_sha256", "block_bytes"}


class BundleError(ValueError):
    """Invalid input or an unsafe/unreadable local path."""


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise BundleError(f"Duplicate JSON key: {key!r}")
        result[key] = value
    return result


def _constant(value):
    raise BundleError(f"Non-standard JSON value: {value}")


def _json_file(path: Path, limit: int) -> Any:
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise BundleError(f"JSON document exceeds {limit} bytes")
    try:
        return json.loads(data.decode("utf-8-sig"), object_pairs_hook=_object, parse_constant=_constant)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise BundleError(f"Invalid JSON document: {error}") from error


def load_plan(path: str | os.PathLike[str]) -> dict:
    return _json_file(Path(path), MAX_PLAN_BYTES)


def _integer(value: Any, label: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise BundleError(f"{label}: expected an integer from {minimum} to {maximum}")
    return value


def _relative_path(value: Any) -> str:
    if not isinstance(value, str) or not value or len(value) > 1024:
        raise BundleError("path: expected a nonempty relative path up to 1024 characters")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise BundleError("path: control characters are not allowed")
    if value.startswith(("/", "\\")) or "\\" in value or ":" in value:
        raise BundleError("path: use slash-separated relative paths, not absolute/drive/UNC paths")
    if any(part in {"", ".", ".."} for part in value.split("/")):
        raise BundleError("path: empty, dot and parent components are not allowed")
    for part in value.split("/"):
        if part.endswith((" ", ".")):
            raise BundleError("path: components ending in a space or dot are not allowed")
        if re.fullmatch(r"(?i)(con|prn|aux|nul|com[1-9¹²³]|lpt[1-9¹²³])", part.split(".", 1)[0]):
            raise BundleError("path: Windows device names are not allowed")
    return value


def _linked(info) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)


def _local_path(path: Path, *, allow_missing: bool = False) -> Path:
    """Reject observed links/reparse points, including existing ancestors."""
    absolute = Path(os.path.abspath(path))
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        try:
            info = current.lstat()
        except FileNotFoundError:
            if allow_missing:
                continue
            raise
        if _linked(info):
            raise BundleError(f"Linked or reparse path is not allowed: {str(current)!r}")
    return absolute


def _root(path: str | os.PathLike[str]) -> Path:
    result = _local_path(Path(path))
    if not result.is_dir():
        raise BundleError("root: expected a directory")
    return result


def _source(root: Path, relative: str):
    path = _local_path(root.joinpath(*relative.split("/")))
    if not path.is_relative_to(root):
        raise BundleError("Source path escaped its root")
    info = path.stat()
    if not stat.S_ISREG(info.st_mode):
        raise BundleError(f"Source is not a regular file: {relative!r}")
    return path, info


def _blocked(relative: str) -> bool:
    parts = [part.casefold() for part in relative.split("/")]
    name = parts[-1]
    return (any(part in {".git", ".ssh", ".aws", ".azure"} for part in parts)
            or name == ".env" or name.startswith(".env.")
            or name in {"id_rsa", "id_dsa", "id_ecdsa", "id_ed25519", "credentials", "credentials.json", "secrets.json"}
            or name.endswith((".pem", ".key")))


def _plan(value: Any) -> list[dict]:
    if not isinstance(value, dict) or set(value) != {"version", "files"} or type(value["version"]) is not int or value["version"] != 1:
        raise BundleError("Plan must contain version: 1 and files only")
    files = value["files"]
    if not isinstance(files, list) or len(files) > MAX_ENTRIES:
        raise BundleError(f"files: expected a list with at most {MAX_ENTRIES} entries")
    entries = []
    seen = set()
    for index, item in enumerate(files):
        if not isinstance(item, dict) or "path" not in item or set(item) - {"path", "priority", "start_line", "end_line"}:
            raise BundleError(f"files[{index}]: unknown fields or missing path")
        relative = _relative_path(item["path"])
        if relative.casefold() in seen:
            raise BundleError(f"Duplicate path (case-insensitive): {relative!r}")
        seen.add(relative.casefold())
        priority = _integer(item.get("priority", 0), "priority", -1000000, 1000000)
        start = _integer(item.get("start_line", 1), "start_line", 1, 1000000000)
        end = item.get("end_line")
        if end is not None:
            end = _integer(end, "end_line", start, 1000000000)
        entries.append({"plan_index": index, "path": relative, "priority": priority,
                        "requested_start_line": start, "requested_end_line": end})
    return sorted(entries, key=lambda entry: (-entry["priority"], entry["plan_index"]))


def _read(path: Path, before, limit: int) -> bytes:
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    after = path.stat()
    signature = lambda info: (info.st_size, info.st_mtime_ns, info.st_ino)
    if len(data) > limit or signature(before) != signature(after) or len(data) != before.st_size:
        raise BundleError("A source changed or grew during reading; try again after it stops changing")
    return data


def _snippet(data: bytes, start: int, end: int | None):
    text = data.decode("utf-8-sig").replace("\r\n", "\n")
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    if not lines:
        return "", None, None
    actual_end = len(lines) if end is None else end
    if start > len(lines) or actual_end > len(lines):
        raise BundleError(f"Requested line range {start}-{actual_end} exceeds {len(lines)} physical lines")
    return "\n".join(lines[start - 1:actual_end]) + "\n", start, actual_end


def _block(path: str, start: int, end: int, snippet: str) -> str:
    heading = re.sub(r"([\\`*_\[\]{}()#+.!|<>~\-])", r"\\\1", path)
    fence = "`" * max(3, max((len(match.group()) + 1 for match in re.finditer(r"`+", snippet)), default=0))
    return f"## {heading}:L{start}-L{end}\n\n{fence}\n{snippet}{fence}\n\n"


def build_bundle(plan: dict, root: str | os.PathLike[str], *, max_bytes: int = 8192,
                 max_file_bytes: int = DEFAULT_FILE_BYTES) -> tuple[str, dict]:
    """Return context and metadata; no output files are written by this function."""
    max_bytes = _integer(max_bytes, "max_bytes", 0, MAX_CONTEXT_BYTES)
    max_file_bytes = _integer(max_file_bytes, "max_file_bytes", 1, MAX_FILE_BYTES)
    entries = _plan(plan)
    source_root = _root(root)
    context = []
    used = read_bytes = 0
    for entry in entries:
        entry.update(status="excluded", reason="blocked_name", source_bytes=None, source_sha256=None,
                     start_line=None, end_line=None, snippet_sha256=None, block_bytes=0)
        if _blocked(entry["path"]):
            continue  # Do not open or hash denied names.
        path, info = _source(source_root, entry["path"])
        entry["source_bytes"] = info.st_size
        if info.st_size > max_file_bytes:
            entry["reason"] = "too_large"
            continue
        if read_bytes + info.st_size > MAX_SOURCE_READ_BYTES:
            entry["reason"] = "read_limit"
            continue
        data = _read(path, info, max_file_bytes)
        read_bytes += len(data)
        entry["source_sha256"] = _hash(data)
        if b"\0" in data:
            entry["reason"] = "binary"
            continue
        try:
            snippet, start, end = _snippet(data, entry["requested_start_line"], entry["requested_end_line"])
        except UnicodeError:
            entry["reason"] = "invalid_utf8"
            continue
        if start is None:
            entry["reason"] = "empty"
            continue
        entry.update(start_line=start, end_line=end, snippet_sha256=_hash(snippet.encode("utf-8")))
        block = _block(entry["path"], start, end, snippet)
        size = len(block.encode("utf-8"))
        entry["block_bytes"] = size
        if used + size > max_bytes:
            entry["reason"] = "budget"
            continue
        entry.update(status="selected", reason="selected")
        context.append(block)
        used += size
    rendered = "".join(context)
    manifest = {"schema_version": 1, "tool_version": "0.1.0",
                "budget": {"max_bytes": max_bytes, "used_bytes": used, "remaining_bytes": max_bytes - used},
                "limits": {"max_entries": MAX_ENTRIES, "max_file_bytes": max_file_bytes,
                           "max_total_read_bytes": MAX_SOURCE_READ_BYTES},
                "source_bytes_read": read_bytes, "entries": entries,
                "context": {"path": "context.md", "bytes": used, "sha256": _hash(rendered.encode("utf-8"))}}
    from .report import render_report
    report = render_report(manifest)
    manifest["report"] = {"path": "report.html", "bytes": len(report.encode("utf-8")), "sha256": _hash(report.encode("utf-8"))}
    return rendered, manifest


def write_bundle(context: str, manifest: dict, output: str | os.PathLike[str]) -> Path:
    """Exclusively create a new bundle directory; never replace existing paths."""
    from .report import render_report
    report = render_report(manifest)
    if _hash(context.encode("utf-8")) != manifest["context"]["sha256"] or _hash(report.encode("utf-8")) != manifest["report"]["sha256"]:
        raise BundleError("Bundle data changed before writing")
    target = _local_path(Path(output), allow_missing=True)
    target.mkdir(parents=True, exist_ok=False)
    for name, text in (("context.md", context), ("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"), ("report.html", report)):
        with (target / name).open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
    return target


def _sha(value: Any, label: str, *, optional: bool = False):
    if optional and value is None:
        return
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise BundleError(f"{label}: expected a SHA-256 hex string")


def _validate_manifest(value: Any) -> dict:
    expected = {"schema_version", "tool_version", "budget", "limits", "source_bytes_read", "entries", "context", "report"}
    if not isinstance(value, dict) or set(value) != expected or type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise BundleError("Unsupported or malformed manifest")
    if value["tool_version"] != "0.1.0":
        raise BundleError("Unsupported tool version in manifest")
    budget = value["budget"]
    if not isinstance(budget, dict) or set(budget) != {"max_bytes", "used_bytes", "remaining_bytes"}:
        raise BundleError("Malformed budget metadata")
    maximum = _integer(budget["max_bytes"], "budget.max_bytes", 0, MAX_CONTEXT_BYTES)
    used = _integer(budget["used_bytes"], "budget.used_bytes", 0, maximum)
    _integer(budget["remaining_bytes"], "budget.remaining_bytes", 0, maximum)
    if budget["remaining_bytes"] != maximum - used:
        raise BundleError("Inconsistent remaining budget")
    limits = value["limits"]
    if not isinstance(limits, dict) or set(limits) != {"max_entries", "max_file_bytes", "max_total_read_bytes"}:
        raise BundleError("Malformed read limits")
    _integer(limits["max_entries"], "limits.max_entries", MAX_ENTRIES, MAX_ENTRIES)
    _integer(limits["max_total_read_bytes"], "limits.max_total_read_bytes", MAX_SOURCE_READ_BYTES, MAX_SOURCE_READ_BYTES)
    if limits["max_entries"] != MAX_ENTRIES or limits["max_total_read_bytes"] != MAX_SOURCE_READ_BYTES:
        raise BundleError("Unsupported read limits")
    _integer(limits["max_file_bytes"], "limits.max_file_bytes", 1, MAX_FILE_BYTES)
    _integer(value["source_bytes_read"], "source_bytes_read", 0, MAX_SOURCE_READ_BYTES)
    entries = value["entries"]
    if not isinstance(entries, list) or len(entries) > MAX_ENTRIES:
        raise BundleError("Malformed manifest entries")
    seen = set()
    indices = set()
    selected_bytes = 0
    hashed_bytes = 0
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != ENTRY_KEYS:
            raise BundleError("Malformed manifest entry")
        relative = _relative_path(entry["path"])
        if relative.casefold() in seen:
            raise BundleError("Duplicate manifest path")
        seen.add(relative.casefold())
        index = _integer(entry["plan_index"], "plan_index", 0, MAX_ENTRIES - 1)
        if index in indices:
            raise BundleError("Duplicate plan index")
        indices.add(index)
        _integer(entry["priority"], "priority", -1000000, 1000000)
        _integer(entry["requested_start_line"], "requested_start_line", 1, 1000000000)
        if entry["requested_end_line"] is not None:
            _integer(entry["requested_end_line"], "requested_end_line", entry["requested_start_line"], 1000000000)
        if (not isinstance(entry["status"], str) or not isinstance(entry["reason"], str)
                or entry["status"] not in {"selected", "excluded"} or entry["reason"] not in REASONS):
            raise BundleError("Unknown entry status or reason")
        if (entry["status"] == "selected") != (entry["reason"] == "selected"):
            raise BundleError("Inconsistent entry status")
        if entry["source_bytes"] is not None:
            _integer(entry["source_bytes"], "source_bytes", 0, 2**63 - 1)
        _sha(entry["source_sha256"], "source_sha256", optional=True)
        _sha(entry["snippet_sha256"], "snippet_sha256", optional=True)
        if entry["source_sha256"] is not None:
            if entry["source_bytes"] is None or entry["source_bytes"] > limits["max_file_bytes"]:
                raise BundleError("Hashed entry lacks a valid source byte count")
            hashed_bytes += entry["source_bytes"]
        block_bytes = _integer(entry["block_bytes"], "block_bytes", 0, MAX_CONTEXT_BYTES + MAX_FILE_BYTES)
        if entry["start_line"] is not None or entry["end_line"] is not None:
            _integer(entry["start_line"], "start_line", 1, 1000000000)
            _integer(entry["end_line"], "end_line", entry["start_line"], 1000000000)
        if entry["status"] == "selected":
            if entry["source_sha256"] is None or entry["snippet_sha256"] is None or entry["start_line"] is None or _blocked(relative):
                raise BundleError("Selected entry lacks source metadata or uses a blocked name")
            if entry["source_bytes"] is None or entry["source_bytes"] > limits["max_file_bytes"]:
                raise BundleError("Selected entry exceeds its source limit")
            selected_bytes += block_bytes
    if selected_bytes != used or entries != sorted(entries, key=lambda entry: (-entry["priority"], entry["plan_index"])):
        raise BundleError("Inconsistent selected bytes or entry ordering")
    if hashed_bytes != value["source_bytes_read"]:
        raise BundleError("Inconsistent source bytes read")
    for key, name, cap in (("context", "context.md", MAX_CONTEXT_BYTES), ("report", "report.html", MAX_REPORT_BYTES)):
        artifact = value[key]
        if not isinstance(artifact, dict) or set(artifact) != {"path", "bytes", "sha256"} or artifact["path"] != name:
            raise BundleError("Malformed artifact metadata")
        _integer(artifact["bytes"], key + ".bytes", 0, cap)
        _sha(artifact["sha256"], key + ".sha256")
    if value["context"]["bytes"] != used:
        raise BundleError("Context size differs from budget usage")
    return value


def verify_bundle(bundle: str | os.PathLike[str], root: str | os.PathLike[str]) -> dict:
    """Check source hashes and generated artifacts without rewriting anything."""
    directory = _root(bundle)
    source_root = _root(root)
    manifest_path = _local_path(directory / "manifest.json")
    manifest = _validate_manifest(_json_file(manifest_path, MAX_MANIFEST_BYTES))
    issues = []
    actual_context = None
    actual_report = None
    for key, cap in (("context", MAX_CONTEXT_BYTES), ("report", MAX_REPORT_BYTES)):
        metadata = manifest[key]
        try:
            path = _local_path(directory / metadata["path"])
            if not path.is_file():
                raise BundleError("Artifact is not a regular file")
            with path.open("rb") as stream:
                data = stream.read(cap + 1)
            if len(data) != metadata["bytes"] or _hash(data) != metadata["sha256"]:
                issues.append({"path": metadata["path"], "code": "artifact_changed"})
            if key == "context":
                actual_context = data
            else:
                actual_report = data
        except (OSError, BundleError):
            issues.append({"path": metadata["path"], "code": "artifact_unavailable"})
    blocks = []
    checked = read_bytes = 0
    for entry in manifest["entries"]:
        if entry["source_sha256"] is None:
            continue
        relative = entry["path"]
        if _blocked(relative):
            raise BundleError("Manifest asks to verify a blocked filename")
        try:
            path, info = _source(source_root, relative)
            if info.st_size > manifest["limits"]["max_file_bytes"] or read_bytes + info.st_size > MAX_SOURCE_READ_BYTES:
                raise BundleError("Source exceeds verification read limits")
            data = _read(path, info, manifest["limits"]["max_file_bytes"])
            read_bytes += len(data)
            checked += 1
            if len(data) != entry["source_bytes"] or _hash(data) != entry["source_sha256"]:
                issues.append({"path": relative, "code": "source_changed"})
                continue
            if entry["status"] == "selected":
                snippet, start, end = _snippet(data, entry["requested_start_line"], entry["requested_end_line"])
                block = _block(relative, start, end, snippet)
                if (start != entry["start_line"] or end != entry["end_line"]
                        or _hash(snippet.encode("utf-8")) != entry["snippet_sha256"]
                        or len(block.encode("utf-8")) != entry["block_bytes"]):
                    issues.append({"path": relative, "code": "selection_metadata_changed"})
                blocks.append(block)
        except (OSError, BundleError, UnicodeError, TypeError):
            issues.append({"path": relative, "code": "source_unavailable"})
    if not issues and actual_context != "".join(blocks).encode("utf-8"):
        issues.append({"path": "context.md", "code": "context_does_not_match_selection"})
    from .report import render_report
    if actual_report is not None and actual_report != render_report(manifest).encode("utf-8"):
        issues.append({"path": "report.html", "code": "report_does_not_match_manifest"})
    return {"ok": not issues, "source_files_checked": checked,
            "unhashed_entries": sum(entry["source_sha256"] is None for entry in manifest["entries"]), "issues": issues}
