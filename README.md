# context-budgetpack

**Pack explicitly chosen source fragments into an exact UTF-8 byte budget, with a readable selection ledger and source hashes.**

[中文说明](README.zh-CN.md) · [Plan and manifest format](docs/format.md)

A small local context preparation tool for agent developers. Python 3.10+, zero runtime dependencies, no model calls and no uploads. It considers only paths in your plan; it does not discover project files or infer semantic relevance.

## Try the synthetic example

```sh
git clone https://github.com/L1Huash1/context-budgetpack.git
cd context-budgetpack
python -m venv .venv
```

**Windows PowerShell** — use the environment's programs directly; activation and script-policy changes are unnecessary:

```powershell
.venv\Scripts\python.exe -m pip install .
.venv\Scripts\context-budgetpack.exe pack examples/plan.json --root examples/workspace --max-bytes 1000 --output demo-bundle
.venv\Scripts\context-budgetpack.exe verify demo-bundle --root examples/workspace
```

**macOS / Linux**:

```sh
.venv/bin/python -m pip install .
.venv/bin/context-budgetpack pack examples/plan.json --root examples/workspace --max-bytes 1000 --output demo-bundle
.venv/bin/context-budgetpack verify demo-bundle --root examples/workspace
```

As an alternative module entry point, replace `.venv\Scripts\context-budgetpack.exe` with `.venv\Scripts\python.exe -m context_budgetpack` on Windows, or `.venv/bin/context-budgetpack` with `.venv/bin/python -m context_budgetpack` on macOS/Linux, keeping the same arguments. For example, `.venv\Scripts\python.exe -m context_budgetpack --help` shows usage without depending on the command being on `PATH`. Installation may download the `setuptools` build tool; packing and verification run locally.

Open `demo-bundle/report.html` in a browser to review selected and excluded fragments. `context.md` contains the selected material; `manifest.json` records source hashes, line ranges and decisions. Choose a new output directory when repeating the example: existing output paths are refused.

You can also download the synthetic demo bundle from **Artifacts** on a successful [GitHub Actions run](https://github.com/L1Huash1/context-budgetpack/actions); demo artifacts are retained for 7 days. Unzip the bundle and open `report.html` locally.

The example intentionally lists `.env` as a blocked-name demonstration; no `.env` file or real secret is included. The background notes are excluded when they do not fit. These are synthetic source files, not an evaluation of model quality.

## An explicit plan

```json
{
  "version": 1,
  "files": [
    {"path": "README.md", "priority": 100},
    {"path": "src/cart.py", "priority": 90, "start_line": 1, "end_line": 10}
  ]
}
```

Paths use `/` and stay within the selected root. Line numbers are 1-based and inclusive. Priority is higher-first, with original plan order breaking ties. Each complete requested fragment is included if it fits; oversized fragments are skipped rather than truncated. A later smaller fragment can still fit. This is stable greedy selection, not an optimizer.

The hard budget applies to **the actual UTF-8 bytes of `context.md`**, including Markdown headings, source references and fences. Manifest and HTML bytes are **not** included in that context budget. A zero-byte budget produces empty context and an explanatory report. Bytes are not tokens: no model-specific token estimate is made.

LF defines physical lines; CRLF is normalized to LF in context fragments. The complete original file is hashed from raw bytes, so line-ending changes still fail source verification. An initial UTF-8 BOM is removed from the selected text. Invalid UTF-8, NUL-containing files and empty files receive explicit exclusion reasons.

## Verify later

Windows PowerShell:

```powershell
.venv\Scripts\python.exe -m context_budgetpack verify demo-bundle --root examples/workspace --format json
```

macOS / Linux:

```sh
.venv/bin/python -m context_budgetpack verify demo-bundle --root examples/workspace --format json
```

Verification checks the recorded source hashes, context and HTML artifact bytes, and the selected context reconstructed from unchanged sources. A changed source or artifact returns **1**; malformed input or file errors return **2**. The manifest is local metadata, not a signed trust anchor. Simultaneously editing metadata and artifacts can create a self-consistent bundle; this is not tamper-proof storage.

Some excluded files are never read or hashed. Verification reports how many entries had no source hash rather than claiming those files are unchanged.

## Limits and handling rules

- Maximum 128 plan entries; one case-insensitively unique path per entry. Default source-file limit is 1 MiB (`--max-file-bytes`, at most 4 MiB), with at most 32 MiB of source bytes read per build. Context budgets are capped at 16 MiB.
- Absolute paths, Windows drives/UNC paths, `..`, backslashes, control characters, trailing spaces/dots and Windows device-name components are rejected on every platform. Observed symbolic links and Windows reparse points, including ancestors, are refused. This is not hardened against a concurrently hostile filesystem or special network mounts.
- `.env`/`.env.*`, common private-key names/suffixes, and `.git`/`.ssh`/`.aws`/`.azure` components are blocked before reading. This is a conservative name rule, **not secret detection**. Secrets in ordinary files can still be included. Review the actual context before sharing.
- Files that are missing, unreadable, not regular files or have an out-of-bounds requested line range stop the build with exit 2. No input is overwritten. A write failure can leave a partial newly created output directory.
- Source content is untrusted material. This program does not remove prompt injections, judge relevance or authorize agent actions. The report is self-contained static HTML and displays metadata rather than embedding all source contents.

## Development

```sh
python -m pip install -e .
python -m unittest discover -s tests -v
```

## Related work

[Repomix](https://github.com/yamadashy/repomix) already supports file lists and token-budget workflows. This small project explores a narrower combination: explicit priority and line ranges, an exact UTF-8 byte cap, exclusion reasons and source-hash verification. It does not claim to replace or outperform a mature repository-packing tool.

MIT licensed. Early release; initial development used AI coding assistance. Distributed through GitHub source releases; no PyPI publication is assumed.
