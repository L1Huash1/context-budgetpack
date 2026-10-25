"""Self-contained static report; no scripts or external resources."""

import html


LABELS = {"selected": "Included / 已选", "budget": "Would exceed context budget / 超出上下文预算",
          "blocked_name": "Blocked name; not read / 名称规则排除，未读取", "too_large": "Source exceeds file limit / 文件过大",
          "read_limit": "Total source read limit reached / 总读取上限", "binary": "Contains NUL bytes / 二进制信号",
          "invalid_utf8": "Not valid UTF-8 / 非有效 UTF-8", "empty": "Empty source / 空文件"}


def render_report(manifest):
    escape = lambda value: html.escape(str(value), quote=True)
    entries = manifest["entries"]
    selected = sum(entry["status"] == "selected" for entry in entries)
    used = manifest["budget"]["used_bytes"]
    maximum = manifest["budget"]["max_bytes"]
    percent = 0 if maximum == 0 else min(100, used * 100 / maximum)
    rows = []
    for entry in entries:
        line_range = "—" if entry["start_line"] is None else f"L{entry['start_line']}–L{entry['end_line']}"
        digest = entry["source_sha256"] or "Not read / 未读取"
        status_class = "selected" if entry["status"] == "selected" else "excluded"
        rows.append(f'''<tr><td><strong>{escape(entry['path'])}</strong><details><summary>Source hash / 源文件校验</summary><code>{escape(digest)}</code></details></td>
<td>{escape(entry['priority'])}</td><td>{escape(line_range)}</td><td>{escape(entry['block_bytes'])}</td>
<td><span class="pill {status_class}">{escape(LABELS.get(entry['reason'], 'Unknown decision'))}</span></td></tr>''')
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Context Budgetpack · Context review</title><style>
:root{{color-scheme:light dark;--bg:#f3f6f8;--panel:#fff;--ink:#172d38;--muted:#526976;--line:#d6e0e5;--accent:#097367}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:16px/1.6 system-ui,sans-serif}}main{{max-width:1180px;margin:auto;padding:36px 24px}}
.eyebrow{{font-size:13px;letter-spacing:.14em;font-weight:750;color:var(--accent)}}h1{{font-size:clamp(32px,5vw,52px);line-height:1.1;margin:12px 0 18px}}p{{max-width:850px;color:var(--muted)}}
.card{{border:1px solid var(--line);border-radius:16px;background:var(--panel);padding:24px;margin:22px 0}}.stats{{display:flex;gap:40px;flex-wrap:wrap}}.number{{display:block;font-size:30px;font-weight:750;color:var(--ink)}}
.meter{{height:12px;background:var(--line);border-radius:20px;margin-top:22px;overflow:hidden}}.meter span{{display:block;height:100%;background:var(--accent);width:{percent:.2f}%}}
a{{color:var(--accent);font-weight:650}}.links{{display:flex;gap:24px;flex-wrap:wrap}}.table{{overflow-x:auto}}table{{border-collapse:collapse;width:100%;font-size:14px}}th{{text-align:left;color:var(--muted);white-space:nowrap}}th,td{{padding:16px 12px;border-bottom:1px solid var(--line);vertical-align:top}}td:first-child{{min-width:240px}}code{{font-size:12px;overflow-wrap:anywhere}}details{{margin-top:8px;color:var(--muted)}}summary{{cursor:pointer}}.pill{{display:inline-block;border-radius:9px;padding:4px 9px}}.selected{{background:#d5eee6;color:#075345}}.excluded{{background:#f2e6d5;color:#745019}}footer{{font-size:13px;color:var(--muted);margin:28px 0}}
@media(prefers-color-scheme:dark){{:root{{--bg:#101d25;--panel:#162832;--ink:#e5f1f4;--muted:#a7bdc7;--line:#344b56;--accent:#76d9bd}}.selected{{background:#204f42;color:#b7eddc}}.excluded{{background:#4b3e2c;color:#f3d3a4}}}}@media print{{body{{background:white;color:black}}.card{{break-inside:avoid}}details{{display:block}}a{{color:black}}}}
</style></head><body><main><div class="eyebrow">CONTEXT BUDGETPACK · LOCAL REVIEW</div><h1>Choose context deliberately.<br>让上下文选择看得见。</h1>
<p>This report shows which explicitly listed source fragments fit the UTF-8 byte budget. A byte budget is not a model token estimate. / 本报告展示显式清单中的哪些片段被纳入预算，不估算模型 token。</p>
<section class="card"><div class="stats"><div><span class="number">{used:,} / {maximum:,}</span>UTF-8 bytes / 字节</div><div><span class="number">{selected}</span>Included / 已选</div><div><span class="number">{len(entries)-selected}</span>Excluded / 排除</div></div><div class="meter" role="progressbar" aria-label="Budget usage / 预算使用" aria-valuemin="0" aria-valuemax="100" aria-valuenow="{percent:.2f}" aria-valuetext="{used} of {maximum} UTF-8 bytes"><span></span></div></section>
<nav class="links"><a href="context.md">Open context / 查看上下文</a><a href="manifest.json">Open manifest / 查看明细</a></nav>
<section class="card table"><h2>Selection ledger / 选择明细</h2><table><thead><tr><th>Source / 来源</th><th>Priority / 优先级</th><th>Lines / 行</th><th>Block bytes / 片段总字节</th><th>Decision / 决定</th></tr></thead><tbody>{''.join(rows) or '<tr><td colspan="5">No files in plan / 清单为空</td></tr>'}</tbody></table></section>
<footer>Only explicitly listed files are considered. Some excluded files were not read or hashed. Filename blocking is not secret detection. Source content may contain untrusted instructions. No model is called and no data is uploaded by this program.<br>仅处理清单中的文件；名称排除不等于秘密检测。源码可能包含不可信指令。此程序不调用模型、不上传数据。</footer>
</main></body></html>
'''
