# Plan, bundle and verification formats

[English overview](../README.md) · [中文说明](../README.zh-CN.md)

Version 1 uses UTF-8 JSON, rejects duplicate object keys and non-standard `NaN`/`Infinity`, and accepts an initial UTF-8 BOM. Unknown fields are rejected. Limits are deliberately finite; this format is intended for a small, explicitly selected task context.

## Plan / 输入清单

```json
{"version": 1, "files": [{"path": "src/cart.py", "priority": 20, "start_line": 4, "end_line": 6}]}
```

| Field | Meaning / 含义 |
| --- | --- |
| `version` | Integer `1` |
| `files` | List of 0–128 entries |
| `path` | Required relative `/`-separated path, at most 1024 characters |
| `priority` | Optional integer −1,000,000 to 1,000,000; defaults to 0 |
| `start_line` | Optional positive integer; defaults to 1 |
| `end_line` | Optional inclusive integer at least `start_line`, or `null` for the final physical line |

Line numbers cannot exceed 1,000,000,000. A nonempty UTF-8 source with an out-of-range selection stops the build. An empty source is excluded. LF is the physical line separator; a terminal LF does not create another source line. CRLF becomes LF and an initial UTF-8 BOM is removed only in selected content. Source hashes always cover the complete raw file bytes.

Paths are case-insensitively unique in a plan even on case-sensitive systems. Absolute paths, Windows drives/UNC, backslashes, colons, parent/dot/empty components, control characters, trailing spaces/dots and Windows device-name components are rejected. Observed links and reparse points are rejected, including existing ancestors. Filename restrictions are conservative portability rules and are not a security boundary against a concurrently changing filesystem.

## Selection / 选择

Entries are visited by descending priority, then original plan index. Each complete requested range is rendered as a Markdown heading and a fenced block. The fence is longer than any backtick run inside the fragment. The actual UTF-8 size of the complete block determines whether it fits in `--max-bytes`; a skipped entry does not prevent later smaller entries from fitting. There is no partial truncation or optimal packing claim.

Default maximum source size is 1 MiB; configurable from 1 byte to 4 MiB. Context budget is 0–16 MiB. At most 32 MiB of source bytes are read per build. Plan JSON is capped at 256 KiB. A new bundle directory contains exactly:

- `context.md`: selected Markdown blocks, possibly empty.
- `manifest.json`: metadata described below; excluded from the context byte budget.
- `report.html`: self-contained static review page; also excluded from that budget.

Existing output paths are refused. The write is not a transaction: an I/O failure can leave a partial newly created directory.

## Manifest / 输出明细

Top-level fields are `schema_version`, `tool_version`, `budget`, `limits`, `source_bytes_read`, `entries`, `context` and `report`. Artifact metadata contains fixed relative `path`, actual `bytes` and lowercase hexadecimal `sha256`. `budget` records `max_bytes`, `used_bytes` and `remaining_bytes`; `limits` records source-read bounds.

Each entry records original `plan_index`, path, priority, requested line range, `status`, `reason`, complete-source byte count/hash, selected line range, snippet hash and rendered block byte count. Hashes use SHA-256. Source fields can be `null` when the file was not read. Snippet/block metadata can also be present for a fragment excluded by budget: the source was read, but its context block was not selected.

| `reason` | Meaning / 含义 |
| --- | --- |
| `selected` | Complete fragment fits; `status` is `selected` |
| `budget` | Complete rendered block would exceed the context budget |
| `blocked_name` | Conservative filename rule; source was not opened or hashed |
| `too_large` | File exceeds the per-file read limit; not hashed |
| `read_limit` | Reading the file would exceed the total source-read limit; not hashed |
| `binary` | Source contains NUL bytes |
| `invalid_utf8` | Source is not valid UTF-8 |
| `empty` | No physical source lines |

All other reasons use `status: "excluded"`. Blocked names include `.env`/`.env.*`, common private-key and credential names, `.pem`/`.key` suffixes and `.git`/`.ssh`/`.aws`/`.azure` components. A normal source file containing sensitive text is not detected. Read `context.md` before sharing it.

## Verification / 核验

`context-budgetpack verify BUNDLE --root ROOT --format json` returns:

```json
{"ok": true, "source_files_checked": 4, "unhashed_entries": 1, "issues": []}
```

Verification checks known schema fields and ordering, context size/hash, HTML size/hash, every recorded source hash within the read limits, selected line metadata, reconstructed context and HTML agreement with manifest metadata. It does not prove that unhashed exclusions remain unchanged or that the selection is semantically useful.

Issue codes include `artifact_changed`, `artifact_unavailable`, `source_changed`, `source_unavailable`, `selection_metadata_changed`, `context_does_not_match_selection` and `report_does_not_match_manifest`. More than one issue may describe a changed artifact. A malformed manifest is an input error rather than a changed-source result. Verification accepts manifests from tool version `0.1.0` only; future changes require an explicit compatibility decision.

Exit status: **0** success/unchanged, **1** a verification discrepancy, **2** invalid input or file operation failure. CLI diagnostics go to standard error for exit 2. Missing source files during verification become discrepancies; a missing root or manifest is a file operation failure. The CLI never rewrites a bundle while verifying.

The manifest is not signed. A person who rewrites source metadata and generated artifacts can create a self-consistent bundle. This tool detects ordinary drift, not authenticity or malicious source instructions.
