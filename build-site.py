#!/usr/bin/env python3
"""
Builds the ByteByteGo x Wait But Why System Design Blog (docs/index.html)
from chapters/*.md and diagrams/*.excalidraw.
Features:
- Full Excalidraw + System Design Library SVG renderer (rectangle, ellipse, diamond, line, freedraw, arrow, text)
- Pure chapter-based narrative blog (zero study-plan, progress, or question-bank tabs exposed)
- Select-text / Tap-paragraph floating pill: [💬 Ask Question | ▶ Listen from here]
- PR-diff style inline question & reply threads backed by GitHub Issues (label: line-question)
- Per-chapter citations ([1], [2]) + "+ Add Source" modal
- Sticky Web Speech API audio narrator
"""
import html
import json
import math
import pathlib
import re
import subprocess

ROOT = pathlib.Path(__file__).resolve().parent
DOCS_DIR = ROOT / "docs"
DIAG_DIR = ROOT / "diagrams"
CHAP_DIR = ROOT / "chapters"
REPO_SLUG = "Rrishik/sd-interview-prep"


def excalidraw_to_svg(ex_path: pathlib.Path) -> str:
    data = json.loads(ex_path.read_text(encoding="utf-8"))
    elements = [e for e in data.get("elements", []) if not e.get("isDeleted")]
    if not elements:
        return ""

    min_x, min_y = float("inf"), float("inf")
    max_x, max_y = float("-inf"), float("-inf")
    for e in elements:
        x, y = float(e.get("x", 0)), float(e.get("y", 0))
        w, h = float(e.get("width", 0)), float(e.get("height", 0))
        if e.get("type") in ("arrow", "line", "freedraw", "draw") and e.get("points"):
            for pt in e["points"]:
                px, py = x + float(pt[0]), y + float(pt[1])
                min_x, min_y = min(min_x, px), min(min_y, py)
                max_x, max_y = max(max_x, px), max(max_y, py)
        else:
            min_x, min_y = min(min_x, x), min(min_y, y)
            max_x, max_y = max(max_x, x + w), max(max_y, y + h)

    pad = 24
    vb_x = int(math.floor(min_x - pad))
    vb_y = int(math.floor(min_y - pad))
    vb_w = int(math.ceil((max_x - min_x) + pad * 2))
    vb_h = int(math.ceil((max_y - min_y) + pad * 2))

    svg = [
        f'<svg class="ex-svg" viewBox="{vb_x} {vb_y} {vb_w} {vb_h}" width="100%" xmlns="http://www.w3.org/2000/svg">',
        '<defs>',
        '<marker id="ex-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6.5" markerHeight="6.5" orient="auto-start-reverse">',
        '<path d="M 0 1.5 L 8 5 L 0 8.5 z" fill="#475569"/>',
        '</marker>',
        '</defs>',
        f'<rect x="{vb_x}" y="{vb_y}" width="{vb_w}" height="{vb_h}" rx="12" fill="#ffffff"/>',
    ]

    for e in elements:
        etype = e.get("type")
        x, y = float(e.get("x", 0)), float(e.get("y", 0))
        w, h = float(e.get("width", 0)), float(e.get("height", 0))
        stroke = e.get("strokeColor", "#334155")
        bg = e.get("backgroundColor", "transparent")
        fill = "none" if bg in ("transparent", "", None) else bg
        sw = e.get("strokeWidth", 1.5)
        dash = ' stroke-dasharray="6 4"' if e.get("strokeStyle") == "dashed" else (
            ' stroke-dasharray="2 3"' if e.get("strokeStyle") == "dotted" else ""
        )

        if etype == "rectangle":
            rx = 8 if e.get("roundness") else 0
            svg.append(
                f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{rx}" '
                f'fill="{fill}" stroke="{stroke}" stroke-width="{sw}"{dash}/>'
            )
        elif etype == "ellipse":
            cx, cy = x + w / 2.0, y + h / 2.0
            rx, ry = max(w / 2.0, 0.5), max(h / 2.0, 0.5)
            svg.append(
                f'<ellipse cx="{cx:.1f}" cy="{cy:.1f}" rx="{rx:.1f}" ry="{ry:.1f}" '
                f'fill="{fill}" stroke="{stroke}" stroke-width="{sw}"{dash}/>'
            )
        elif etype == "diamond":
            pts = f"{x + w/2:.1f},{y:.1f} {x + w:.1f},{y + h/2:.1f} {x + w/2:.1f},{y + h:.1f} {x:.1f},{y + h/2:.1f}"
            svg.append(
                f'<polygon points="{pts}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}" stroke-linejoin="round"{dash}/>'
            )
        elif etype in ("arrow", "line", "freedraw", "draw"):
            pts = e.get("points") or [[0, 0], [w, h]]
            if len(pts) >= 2:
                pt_str = " ".join(f"{x + float(p[0]):.1f},{y + float(p[1]):.1f}" for p in pts)
                marker = ' marker-end="url(#ex-arrow)"' if (etype == "arrow" or e.get("endArrowhead") == "arrow") else ""
                poly_fill = fill if (etype == "line" and len(pts) > 2 and pts[0] == pts[-1]) else "none"
                svg.append(
                    f'<polyline points="{pt_str}" fill="{poly_fill}" stroke="{stroke}" '
                    f'stroke-width="{sw}" stroke-linecap="round" stroke-linejoin="round"{dash}{marker}/>'
                )
        elif etype == "text":
            txt = e.get("text", "")
            if not txt.strip():
                continue
            lines = txt.split("\n")
            fsize = float(e.get("fontSize", 14))
            ffam = e.get("fontFamily", 2)
            font_css = (
                "'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"
                if ffam == 3
                else "'Noto Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
            )
            align = e.get("textAlign", "left")
            if align == "center":
                tx = x + w / 2.0
                anchor = "middle"
            elif align == "right":
                tx = x + w
                anchor = "end"
            else:
                tx = x
                anchor = "start"

            line_h = fsize * 1.32
            start_y = y + fsize * 0.95
            font_weight = "700" if fsize >= 15 else "400"
            tspans = []
            for idx, line in enumerate(lines):
                ly = start_y + idx * line_h
                esc = html.escape(line) if line.strip() else "&#160;"
                weight = "700" if (idx == 0 and len(lines) > 1 and not line.startswith("•")) else font_weight
                tspans.append(f'<tspan x="{tx:.1f}" y="{ly:.1f}" font-weight="{weight}">{esc}</tspan>')
            svg.append(
                f'<text font-family="{font_css}" font-size="{fsize:.1f}" fill="{stroke}" text-anchor="{anchor}">'
                + "".join(tspans)
                + "</text>"
            )

    svg.append("</svg>")
    return "\n".join(svg)


def inline_md(text: str, ch_slug: str) -> str:
    text = html.escape(text)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", text)
    text = re.sub(
        r"\[([^\]]+)\]\((https?://[^)]+)\)",
        r'<a href="\2" target="_blank" rel="noopener">\1</a>',
        text,
    )
    def cite_repl(m):
        inner = m.group(1)
        return f'<a href="#{ch_slug}-refs" class="cite-ref" title="Jump to chapter references">[{inner}]</a>'

    text = re.sub(r"\[(\d+(?:,\s*\d+)*)\](?!\()", cite_repl, text)
    return text


def md_to_chapter_html(md_text: str, ch_slug: str, svg_map: dict) -> str:
    lines = md_text.splitlines()
    out = []
    in_ul = False
    in_ol = False
    in_code = False
    in_table = False
    code_buf = []
    block_idx = 0

    def next_anchor():
        nonlocal block_idx
        block_idx += 1
        return f"{ch_slug}-b{block_idx:02d}"

    def close_lists():
        nonlocal in_ul, in_ol, in_table
        if in_ul:
            out.append("</ul>")
            in_ul = False
        if in_ol:
            out.append("</ol>")
            in_ol = False
        if in_table:
            out.append("</tbody></table></div>")
            in_table = False

    for raw in lines:
        line = raw.rstrip()

        if line.strip().startswith(("<details>", "</details>", "<summary>", "<p><strong>Answer:")):
            close_lists()
            if line.strip().startswith("<summary>"):
                anc = next_anchor()
                out.append(line.replace("<summary>", f'<summary class="annotatable speakable" data-anchor="{anc}">', 1))
            else:
                out.append(line)
            continue

        dm = re.match(r"^\{\{diagram:([^}]+)\}\}$", line.strip())
        if dm:
            close_lists()
            dname = dm.group(1).strip()
            dsvg = svg_map.get(dname, "")
            if dsvg:
                anc = next_anchor()
                out.append(
                    f'<figure class="inline-diag annotatable" data-anchor="{anc}">'
                    f'<div class="diag-scroll">{dsvg}</div>'
                    f'<figcaption class="diag-cap"><span>Architecture Diagram · {html.escape(dname.replace(".excalidraw", ""))}</span>'
                    f'<span class="diag-hint">Tap any line to ask a question · Pinch/scroll to zoom</span></figcaption>'
                    f'</figure>'
                )
            continue

        if line.startswith("```"):
            close_lists()
            if not in_code:
                in_code = True
                code_buf = []
            else:
                in_code = False
                anc = next_anchor()
                out.append(f'<pre class="code-block annotatable" data-anchor="{anc}"><code>{html.escape(chr(10).join(code_buf))}</code></pre>')
            continue

        if in_code:
            code_buf.append(raw)
            continue

        if not line.strip():
            close_lists()
            continue

        if line.strip() == "---":
            close_lists()
            out.append('<hr class="wbw-divider"/>')
            continue

        if line.strip().startswith("|") and line.strip().endswith("|"):
            cells = [c.strip() for c in line.strip()[1:-1].split("|")]
            if all(re.match(r"^[-:]+$", c.replace(" ", "")) for c in cells if c):
                continue
            if not in_table:
                close_lists()
                in_table = True
                out.append('<div class="table-wrap"><table><thead><tr>')
                for c in cells:
                    out.append(f"<th>{inline_md(c, ch_slug)}</th>")
                out.append("</tr></thead><tbody>")
            else:
                anc = next_anchor()
                out.append(f'<tr class="annotatable speakable" data-anchor="{anc}">')
                for c in cells:
                    out.append(f"<td>{inline_md(c, ch_slug)}</td>")
                out.append("</tr>")
            continue
        else:
            if in_table:
                close_lists()

        hm = re.match(r"^(#{1,4})\s+(.*)$", line)
        if hm:
            close_lists()
            lvl = len(hm.group(1))
            raw_h = hm.group(2)
            htxt = inline_md(raw_h, ch_slug)
            extra_id = f' id="{ch_slug}-refs"' if "Sources & References" in raw_h else ""
            if lvl == 1:
                out.append(f'<h1 class="ch-title speakable">{htxt}</h1>')
            else:
                anc = next_anchor()
                out.append(f'<h{lvl}{extra_id} class="annotatable speakable" data-anchor="{anc}">{htxt}</h{lvl}>')
            continue

        bm = re.match(r"^\s*[-*]\s+(.*)$", line)
        if bm:
            if in_ol:
                out.append("</ol>")
                in_ol = False
            if not in_ul:
                out.append("<ul>")
                in_ul = True
            anc = next_anchor()
            out.append(f'<li class="annotatable speakable" data-anchor="{anc}">{inline_md(bm.group(1), ch_slug)}</li>')
            continue

        om = re.match(r"^\s*\d+\.\s+(.*)$", line)
        if om:
            if in_ul:
                out.append("</ul>")
                in_ul = False
            if not in_ol:
                out.append("<ol>")
                in_ol = True
            anc = next_anchor()
            out.append(f'<li class="annotatable speakable" data-anchor="{anc}">{inline_md(om.group(1), ch_slug)}</li>')
            continue

        close_lists()
        if line.strip().startswith("*") and line.strip().endswith("*") and "min read" in line:
            meta_txt = line.strip()[1:-1]
            out.append(f'<div class="ch-kicker">{html.escape(meta_txt)}</div>')
            continue

        anc = next_anchor()
        out.append(f'<p class="annotatable speakable" data-anchor="{anc}">{inline_md(line, ch_slug)}</p>')

    close_lists()
    return "\n".join(out)


def fetch_baked_threads() -> list:
    try:
        res = subprocess.run(
            [
                "gh",
                "issue",
                "list",
                "--repo",
                REPO_SLUG,
                "--label",
                "line-question",
                "--state",
                "all",
                "--limit",
                "100",
                "--json",
                "number,title,body,state,createdAt,url,comments",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            encoding="utf-8",
        )
        if res.returncode == 0 and res.stdout.strip():
            return json.loads(res.stdout)
    except Exception:
        pass
    return []


def build():
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    svg_map = {}
    for ex_file in sorted(DIAG_DIR.glob("*.excalidraw")):
        svg_map[ex_file.name] = excalidraw_to_svg(ex_file)

    chapter_meta = [
        ("ch01", "ch01-envelope-math.md", "Part I · Core Building Blocks", "1. Back-of-the-Envelope Math", "60-second QPS, storage, RAM & LLM token math"),
        ("ch02", "ch02-kafka-streams.md", "Part I · Core Building Blocks", "2. Kafka & Partition Streams", "Topics, partitions, offsets, ordering & hot keys"),
        ("ch03", "ch03-redis-swiss-army-knife.md", "Part I · Core Building Blocks", "3. Redis & In-Memory Primitives", "String NX, List, ZSET timers, Hash & AOF"),
        ("ch04", "ch04-database-keys-sharding.md", "Part I · Core Building Blocks", "4. Database Keys & Sharding", "Partition vs Sort key, B-Tree vs LSM, Consistent Hashing"),
        ("ch05", "ch05-notification-system-ai-digest.md", "Part II · System Design Stories", "5. Global Notification + AI Digest", "30k QPS fan-out, dedup, retries & 15m LLM digest"),
        ("ch06", "ch06-url-shortener-and-id-gen.md", "Part II · System Design Stories", "6. URL Shortener & Snowflake IDs", "Base62 math, 64-bit Snowflake & 301 vs 302 caching"),
        ("ch07", "ch07-rate-limiter.md", "Part II · System Design Stories", "7. Distributed Rate Limiter", "Token bucket, Redis Lua atomicity & LLM TPM caps"),
        ("ch08", "ch08-news-feed-fanout.md", "Part II · System Design Stories", "8. News Feed & Celebrity Fan-Out", "Hybrid push/pull timelines & two-tier hydration"),
        ("ch09", "ch09-realtime-chat.md", "Part II · System Design Stories", "9. Real-Time Chat & Presence", "Stateful WebSockets, Redis routing & presence storms"),
        ("ch10", "ch10-ticketing-and-geospatial.md", "Part II · System Design Stories", "10. Flash Sales & Uber Geospatial", "2-phase Redis seat holds, Geohash, Quadtrees & H3"),
        ("ch11", "ch11-rag-and-llm-systems.md", "Part III · AI Engineering Systems", "11. Production RAG & ACL Security", "Hybrid BM25+Vector RRF, cross-encoder & ACL pre-filter"),
        ("ch12", "ch12-agents-guardrails-evals.md", "Part III · AI Engineering Systems", "12. AI Agents, Guardrails & Evals", "Bounded ReAct loops, tool privilege gates & async judge"),
        ("ch13", "ch13-agent-loops-orchestration.md", "Part IV · Autonomous Agent Systems", "13. Agent Loop Architectures", "ReAct, Plan-and-Execute DAGs, two-pass flows & handoffs"),
        ("ch14", "ch14-agent-memory-and-caching.md", "Part IV · Autonomous Agent Systems", "14. Agent Memory & KV Caching", "Working, episodic & semantic memory + prefix KV cache"),
        ("ch15", "ch15-rag-recall-and-vector-math.md", "Part IV · Autonomous Agent Systems", "15. Retrieval Math & Vector Indexes", "Recall@K, MRR, nDCG@K, HNSW vs IVF & pgvector vs Milvus"),
        ("ch16", "ch16-mcp-tools-and-safety.md", "Part IV · Autonomous Agent Systems", "16. MCP, Tool Contracts & Safety", "Model Context Protocol, idempotency, sandboxing & CaMeL"),
        ("ch17", "ch17-agent-observability-and-evals.md", "Part IV · Autonomous Agent Systems", "17. Agent Observability & Replay", "OpenTelemetry GenAI spans, cassette replay & canary gates"),
        ("ch18", "ch18-reactive-backend-and-concurrency.md", "Part IV · Autonomous Agent Systems", "18. Reactive Backends & Concurrency", "Spring WebFlux SSE, LongAdder vs CAS & keyset pagination"),
    ]

    chapters_data = []
    for idx, (slug, fname, part, short_title, subtitle) in enumerate(chapter_meta):
        fpath = CHAP_DIR / fname
        md_txt = fpath.read_text(encoding="utf-8") if fpath.exists() else f"# {short_title}"
        ch_html = md_to_chapter_html(md_txt, slug, svg_map)
        chapters_data.append({
            "idx": idx,
            "slug": slug,
            "part": part,
            "title": short_title,
            "subtitle": subtitle,
            "html": ch_html,
        })

    sidebar_parts = {}
    for ch in chapters_data:
        sidebar_parts.setdefault(ch["part"], []).append(ch)

    sidebar_html = []
    for part_name, ch_list in sidebar_parts.items():
        sidebar_html.append(f'<div class="nav-part">{html.escape(part_name)}</div>')
        for ch in ch_list:
            active_cls = " active" if ch["idx"] == 0 else ""
            sidebar_html.append(
                f'<button class="nav-ch{active_cls}" id="nav-{ch["slug"]}" onclick="openChapter(\'{ch["slug"]}\')">'
                f'<span class="nav-ch-title">{html.escape(ch["title"])}</span>'
                f'<span class="nav-ch-sub">{html.escape(ch["subtitle"])}</span>'
                f'</button>'
            )

    articles_html = []
    for i, ch in enumerate(chapters_data):
        active_cls = " active" if i == 0 else ""
        if i > 0:
            p = chapters_data[i - 1]
            prev_btn = (
                f'<button class="ch-pager-btn prev" onclick="openChapter(\'{p["slug"]}\')">'
                f'<span class="pager-dir">← Previous Chapter</span>'
                f'<span class="pager-title">{html.escape(p["title"])}</span></button>'
            )
        else:
            prev_btn = '<div></div>'
        if i < len(chapters_data) - 1:
            n = chapters_data[i + 1]
            next_btn = (
                f'<button class="ch-pager-btn next" onclick="openChapter(\'{n["slug"]}\')">'
                f'<span class="pager-dir">Next Chapter →</span>'
                f'<span class="pager-title">{html.escape(n["title"])}</span></button>'
            )
        else:
            next_btn = '<div></div>'

        articles_html.append(
            f'<article id="chap-{ch["slug"]}" class="chapter-article{active_cls}" data-ch="{ch["slug"]}">'
            f'{ch["html"]}'
            f'<nav class="ch-pager">{prev_btn}{next_btn}</nav>'
            f'</article>'
        )

    baked_issues_json = json.dumps(fetch_baked_threads())

    page_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=5"/>
<meta name="theme-color" content="#ffffff"/>
<meta name="apple-mobile-web-app-capable" content="yes"/>
<title>System Design — Visual Field Guide</title>
<link rel="manifest" href="manifest.json"/>
<link rel="preconnect" href="https://fonts.googleapis.com"/>
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin/>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500&family=Lora:ital,wght@0,400;0,600;1,400&family=Noto+Sans:ital,wght@0,400;0,600;0,700;1,400&family=PT+Sans+Narrow:wght@700&display=swap" rel="stylesheet"/>
<style>
:root {{
  --bg: #ffffff;
  --bg-Warm: #faf9f5;
  --surface: #ffffff;
  --text: #222222;
  --text-muted: #64748b;
  --border: #e5e7eb;
  --accent: #d9534f;
  --blue: #1d4ed8;
  --blue-soft: #eff6ff;
  --amber-soft: #fef3c7;
  --green: #047857;
  --font-body: 'Noto Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  --font-Display: 'PT Sans Narrow', 'Noto Sans', sans-serif;
  --font-serif: 'Lora', Georgia, serif;
  --font-mono: 'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, monospace;
}}
[data-theme="dark"] {{
  --bg: #0f172a;
  --bg-Warm: #111827;
  --surface: #1e293b;
  --text: #e2e8f0;
  --text-muted: #94a3b8;
  --border: #334155;
  --blue: #60a5fa;
  --blue-soft: #1e3a8a;
  --amber-soft: #451a03;
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font-family: var(--font-body);
  font-size: 17px;
  line-height: 1.78;
  -webkit-font-smoothing: antialiased;
  padding-bottom: 96px;
}}
.masthead {{
  position: sticky;
  top: 0;
  z-index: 50;
  background: rgba(255, 255, 255, 0.95);
  backdrop-filter: blur(10px);
  border-bottom: 1px solid var(--border);
  height: 56px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 18px;
}}
[data-theme="dark"] .masthead {{
  background: rgba(15, 23, 42, 0.95);
}}
.mast-left {{
  display: flex;
  align-items: center;
  gap: 12px;
}}
.menu-btn {{
  background: transparent;
  border: 1px solid var(--border);
  color: var(--text);
  border-radius: 7px;
  padding: 5px 10px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
}}
.brand {{
  display: flex;
  align-items: baseline;
  gap: 10px;
}}
.brand-title {{
  font-family: var(--font-Display);
  font-size: 21px;
  font-weight: 700;
  letter-spacing: 0.02em;
  text-transform: uppercase;
}}
.brand-sub {{
  font-size: 12px;
  color: var(--text-muted);
  display: none;
}}
@media (min-width: 700px) {{
  .brand-sub {{ display: inline; }}
}}
.mast-actions {{
  display: flex;
  align-items: center;
  gap: 8px;
}}
.top-btn {{
  background: var(--surface);
  color: var(--text);
  border: 1px solid var(--border);
  border-radius: 7px;
  padding: 5px 10px;
  font-size: 12.5px;
  font-weight: 600;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 5px;
}}
.top-btn:hover {{
  border-color: var(--blue);
}}
.top-btn.primary {{
  background: var(--blue);
  color: #ffffff;
  border-color: var(--blue);
}}
.layout {{
  display: flex;
  max-width: 1240px;
  margin: 0 auto;
}}
.sidebar {{
  width: 290px;
  flex-shrink: 0;
  border-right: 1px solid var(--border);
  padding: 20px 14px 100px;
  height: calc(100vh - 56px);
  position: sticky;
  top: 56px;
  overflow-y: auto;
  background: var(--bg-Warm);
}}
@media (max-width: 960px) {{
  .sidebar {{
    position: fixed;
    left: 0;
    top: 56px;
    z-index: 60;
    transform: translateX(-105%);
    transition: transform 0.22s ease;
    box-shadow: 8px 0 24px rgba(0,0,0,0.12);
  }}
  .sidebar.open {{
    transform: translateX(0);
  }}
}}
.nav-part {{
  font-family: var(--font-Display);
  font-size: 13px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--text-muted);
  margin: 18px 8px 6px;
}}
.nav-part:first-child {{ margin-top: 2px; }}
.nav-ch {{
  display: block;
  width: 100%;
  text-align: left;
  background: transparent;
  border: none;
  border-radius: 8px;
  padding: 8px 10px;
  margin-bottom: 3px;
  cursor: pointer;
  color: var(--text);
  transition: background 0.12s;
}}
.nav-ch:hover {{
  background: rgba(29, 78, 216, 0.06);
}}
.nav-ch.active {{
  background: var(--blue-soft);
  border-left: 3px solid var(--blue);
}}
.nav-ch-title {{
  display: block;
  font-size: 13.5px;
  font-weight: 700;
  line-height: 1.3;
}}
.nav-ch-sub {{
  display: block;
  font-size: 11.5px;
  color: var(--text-muted);
  margin-top: 2px;
  line-height: 1.25;
}}
.reader-col {{
  flex: 1;
  min-width: 0;
  max-width: 740px;
  margin: 0 auto;
  padding: 36px 24px 90px;
}}
.chapter-article {{ display: none; }}
.chapter-article.active {{ display: block; }}
.ch-kicker {{
  font-family: var(--font-Display);
  font-size: 14px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--accent);
  margin-bottom: 18px;
}}
.ch-title {{
  font-family: var(--font-body);
  font-size: 32px;
  font-weight: 700;
  line-height: 1.22;
  letter-spacing: -0.02em;
  margin: 0 0 8px;
}}
h2, h3 {{
  font-family: var(--font-body);
  font-weight: 700;
  line-height: 1.3;
  margin-top: 34px;
  margin-bottom: 12px;
}}
h3 {{ font-size: 21px; }}
p {{ margin: 0 0 18px; }}
ul, ol {{ margin: 0 0 20px; padding-left: 24px; }}
li {{ margin-bottom: 9px; }}
.wbw-divider {{
  border: none;
  border-top: 1px solid var(--border);
  margin: 34px auto;
  width: 60%;
}}
code {{
  font-family: var(--font-mono);
  font-size: 0.87em;
  background: var(--bg-Warm);
  border: 1px solid var(--border);
  padding: 1px 6px;
  border-radius: 5px;
}}
.code-block {{
  background: #0f172a;
  color: #f8fafc;
  padding: 14px 16px;
  border-radius: 10px;
  overflow-x: auto;
  font-size: 13.5px;
  line-height: 1.5;
}}
.code-block code {{
  background: none;
  border: none;
  color: inherit;
  padding: 0;
}}
.cite-ref {{
  font-size: 12px;
  font-weight: 700;
  color: var(--blue);
  text-decoration: none;
  padding: 0 2px;
}}
.cite-ref:hover {{ text-decoration: underline; }}
.table-wrap {{
  overflow-x: auto;
  margin: 20px 0 24px;
  border: 1px solid var(--border);
  border-radius: 10px;
}}
table {{
  width: 100%;
  border-collapse: collapse;
  font-size: 14.5px;
  line-height: 1.5;
}}
th, td {{
  text-align: left;
  padding: 10px 12px;
  border-bottom: 1px solid var(--border);
  vertical-align: top;
}}
th {{
  background: var(--bg-Warm);
  font-weight: 700;
  font-size: 13px;
}}
.inline-diag {{
  margin: 26px -12px;
  background: #ffffff;
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 12px;
  box-shadow: 0 2px 10px rgba(15, 23, 42, 0.04);
}}
.diag-scroll {{
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
}}
.ex-svg {{
  display: block;
  min-width: 640px;
  max-width: 100%;
  height: auto;
}}
.diag-cap {{
  display: flex;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8px;
  font-size: 12px;
  color: var(--text-muted);
  padding-top: 8px;
  border-top: 1px dashed var(--border);
  margin-top: 8px;
}}
details {{
  background: var(--bg-Warm);
  border: 1px solid var(--border);
  border-radius: 9px;
  padding: 11px 15px;
  margin-bottom: 10px;
  font-size: 15.5px;
}}
summary {{
  cursor: pointer;
  user-select: none;
}}
details p {{
  margin: 10px 0 2px;
  padding-top: 10px;
  border-top: 1px dashed var(--border);
}}
.ch-pager {{
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
  margin-top: 48px;
  padding-top: 24px;
  border-top: 2px solid var(--border);
}}
.ch-pager-btn {{
  background: var(--bg-Warm);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 12px 16px;
  cursor: pointer;
  text-align: left;
  color: var(--text);
}}
.ch-pager-btn.next {{ text-align: right; }}
.ch-pager-btn:hover {{ border-color: var(--blue); }}
.pager-dir {{
  display: block;
  font-size: 12px;
  color: var(--text-muted);
  font-weight: 600;
}}
.pager-title {{
  display: block;
  font-size: 14.5px;
  font-weight: 700;
  margin-top: 3px;
}}
.annotatable {{
  position: relative;
  border-radius: 6px;
  transition: background 0.15s;
}}
.annotatable.active-target {{
  background: rgba(29, 78, 216, 0.06);
}}
.annotatable.speaking {{
  background: var(--amber-soft);
  box-shadow: -4px 0 0 #d97706;
}}
.thread-pill {{
  display: inline-flex;
  align-items: center;
  gap: 4px;
  margin-left: 8px;
  padding: 1px 8px;
  font-size: 12px;
  font-weight: 700;
  color: var(--blue);
  background: var(--blue-soft);
  border: 1px solid rgba(29, 78, 216, 0.25);
  border-radius: 999px;
  cursor: pointer;
  vertical-align: middle;
}}
.thread-pill:hover {{
  background: var(--blue);
  color: #ffffff;
}}
.action-popover {{
  position: absolute;
  z-index: 80;
  display: none;
  align-items: center;
  gap: 4px;
  background: #0f172a;
  color: #ffffff;
  padding: 5px 7px;
  border-radius: 999px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.22);
  font-size: 12.5px;
  font-weight: 600;
  white-space: nowrap;
}}
.action-popover button {{
  background: transparent;
  border: none;
  color: #ffffff;
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 12.5px;
  font-weight: 600;
  cursor: pointer;
}}
.action-popover button:hover {{
  background: rgba(255, 255, 255, 0.16);
}}
.action-sep {{
  color: #475569;
  font-size: 12px;
}}
.inline-thread-box {{
  margin: 8px 0 20px;
  border: 1px solid rgba(29, 78, 216, 0.3);
  border-left: 4px solid var(--blue);
  border-radius: 10px;
  background: var(--bg-Warm);
  padding: 14px 16px;
  font-size: 14.5px;
}}
.thread-quote {{
  font-family: var(--font-serif);
  font-style: italic;
  font-size: 13.5px;
  color: var(--text-muted);
  border-left: 3px solid #94a3b8;
  padding-left: 10px;
  margin-bottom: 10px;
}}
.thread-msg {{
  padding: 9px 0;
  border-bottom: 1px dashed var(--border);
}}
.thread-msg:last-of-type {{ border-bottom: none; }}
.thread-meta {{
  font-size: 12px;
  font-weight: 700;
  color: var(--text-muted);
  margin-bottom: 3px;
  display: flex;
  justify-content: space-between;
}}
.thread-author-bot {{
  color: var(--green);
}}
.thread-input {{
  width: 100%;
  padding: 9px 11px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface);
  color: var(--text);
  font-family: inherit;
  font-size: 14px;
  margin-top: 8px;
}}
.thread-actions {{
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  margin-top: 8px;
  flex-wrap: wrap;
}}
.thread-hint {{
  font-size: 11.5px;
  color: var(--text-muted);
}}
.modal-backdrop {{
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.55);
  z-index: 90;
  display: none;
  align-items: center;
  justify-content: center;
  padding: 16px;
}}
.modal-backdrop.open {{ display: flex; }}
.modal-card {{
  background: var(--surface);
  color: var(--text);
  border: 1px solid var(--border);
  border-radius: 14px;
  max-width: 480px;
  width: 100%;
  padding: 20px;
  box-shadow: 0 16px 40px rgba(0,0,0,0.25);
}}
.modal-card h3 {{ margin-top: 0; }}
.form-row {{ margin-bottom: 12px; }}
.form-row label {{
  display: block;
  font-size: 12.5px;
  font-weight: 700;
  color: var(--text-muted);
  margin-bottom: 4px;
}}
.form-row input, .form-row textarea {{
  width: 100%;
  padding: 9px 11px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--bg);
  color: var(--text);
  font-family: inherit;
  font-size: 14px;
}}
.audio-bar {{
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  z-index: 70;
  background: var(--surface);
  border-top: 1px solid var(--border);
  padding: 9px 16px;
  box-shadow: 0 -4px 16px rgba(0, 0, 0, 0.06);
}}
.audio-inner {{
  max-width: 820px;
  margin: 0 auto;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}}
.audio-status {{
  font-size: 12.5px;
  color: var(--text-muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  flex: 1;
}}
.audio-controls {{
  display: flex;
  align-items: center;
  gap: 6px;
}}
.a-btn {{
  background: var(--bg-Warm);
  color: var(--text);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 6px 11px;
  font-size: 13px;
  font-weight: 700;
  cursor: pointer;
}}
.a-btn.play {{
  background: var(--blue);
  color: #ffffff;
  border-color: var(--blue);
}}
</style>
</head>
<body>

<header class="masthead">
  <div class="mast-left">
    <button class="menu-btn" onclick="toggleSidebar()">☰ Chapters</button>
    <div class="brand">
      <span class="brand-title">System Design Field Guide</span>
      <span class="brand-sub">First-Principles Stories & Visual Architectures</span>
    </div>
  </div>
  <div class="mast-actions">
    <button class="top-btn" id="toggle-threads-btn" onclick="toggleAllThreads()" title="Expand or collapse all inline Q&A threads">💬 Threads (<span id="thread-total-count">0</span>)</button>
    <button class="top-btn" onclick="openSourceModal()">+ Add Source</button>
    <button class="top-btn" onclick="openTokenModal()" id="gh-token-btn" title="Connect GitHub token for 1-click inline question posting">🔑 GitHub</button>
    <button class="top-btn" onclick="toggleTheme()" title="Toggle light/dark mode">◐</button>
  </div>
</header>

<div class="layout">
  <aside class="sidebar" id="sidebar">
    {"".join(sidebar_html)}
  </aside>

  <main class="reader-col" id="reader-col">
    {"".join(articles_html)}
  </main>
</div>

<div class="action-popover" id="action-popover">
  <button onclick="openQuestionComposerFromPopover()">💬 Ask Question</button>
  <span class="action-sep">|</span>
  <button onclick="listenFromPopover()">▶ Listen</button>
</div>

<div class="modal-backdrop" id="source-modal">
  <div class="modal-card">
    <h3>+ Save a Reference or Source</h3>
    <p style="font-size:13.5px;color:var(--text-muted);margin-top:0;">Drop any article, paper, or engineering blog link here. On the next refresh, it will be folded into the relevant chapter citations.</p>
    <div class="form-row">
      <label>Title or Topic</label>
      <input id="src-title" type="text" placeholder="e.g., Netflix Zuul Push Architecture"/>
    </div>
    <div class="form-row">
      <label>URL</label>
      <input id="src-url" type="url" placeholder="https://..."/>
    </div>
    <div class="form-row">
      <label>Notes / What to extract (optional)</label>
      <textarea id="src-notes" rows="3" placeholder="Key takeaway or question to fold into the chapter..."></textarea>
    </div>
    <div class="thread-actions">
      <button class="top-btn" onclick="closeModals()">Cancel</button>
      <button class="top-btn primary" onclick="submitNewSource()">Save Source to GitHub</button>
    </div>
  </div>
</div>

<div class="modal-backdrop" id="token-modal">
  <div class="modal-card">
    <h3>🔑 Connect GitHub for Instant Inline Threads</h3>
    <p style="font-size:13.5px;color:var(--text-muted);margin-top:0;">Optional: Paste a GitHub Personal Access Token (with <code>public_repo</code> or <code>Issues: Read & Write</code> scope on <code>{REPO_SLUG}</code>). Stored <strong>only in this browser's localStorage</strong> so your inline questions and replies post directly without opening a new tab.</p>
    <div class="form-row">
      <label>GitHub Token (starts with <code>ghp_</code> or <code>github_pat_</code>)</label>
      <input id="gh-token-input" type="password" placeholder="github_pat_..."/>
    </div>
    <div class="thread-actions">
      <button class="top-btn" onclick="clearGhToken()">Clear</button>
      <div style="display:flex;gap:8px;">
        <button class="top-btn" onclick="closeModals()">Cancel</button>
        <button class="top-btn primary" onclick="saveGhToken()">Save Token</button>
      </div>
    </div>
  </div>
</div>

<div class="audio-bar">
  <div class="audio-inner">
    <div class="audio-status" id="audio-status">🎧 Select any text or tap a paragraph to Ask a Question or Listen</div>
    <div class="audio-controls">
      <button class="a-btn" onclick="stepAudio(-1)" title="Previous paragraph">⏮</button>
      <button class="a-btn play" id="play-btn" onclick="toggleAudio()">▶ Listen</button>
      <button class="a-btn" onclick="stepAudio(1)" title="Next paragraph">⏭</button>
      <button class="a-btn" id="speed-btn" onclick="cycleSpeed()">1.0×</button>
    </div>
  </div>
</div>

<script>
const REPO = "{REPO_SLUG}";
const BAKED_ISSUES = {baked_issues_json};
const threadsByAnchor = {{}};
let allThreadsExpanded = false;
let activeAnchorEl = null;
let activeSelectedQuote = "";

function openChapter(slug) {{
  stopAudio();
  hidePopover();
  document.querySelectorAll('.chapter-article').forEach(a => a.classList.remove('active'));
  document.querySelectorAll('.nav-ch').forEach(b => b.classList.remove('active'));
  const art = document.getElementById('chap-' + slug);
  const btn = document.getElementById('nav-' + slug);
  if (art) art.classList.add('active');
  if (btn) btn.classList.add('active');
  document.getElementById('sidebar').classList.remove('open');
  window.scrollTo({{ top: 0, behavior: 'smooth' }});
  history.replaceState(null, '', '#' + slug);
}}

function toggleSidebar() {{
  document.getElementById('sidebar').classList.toggle('open');
}}

function toggleTheme() {{
  const cur = document.documentElement.getAttribute('data-theme');
  const next = cur === 'dark' ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', next);
  localStorage.setItem('sd_blog_theme', next);
}}
if (localStorage.getItem('sd_blog_theme') === 'dark') {{
  document.documentElement.setAttribute('data-theme', 'dark');
}}

const popover = document.getElementById('action-popover');

function showPopoverForElement(el, quoteText) {{
  if (activeAnchorEl && activeAnchorEl !== el) {{
    activeAnchorEl.classList.remove('active-target');
  }}
  activeAnchorEl = el;
  activeSelectedQuote = (quoteText || el.innerText || "").trim().slice(0, 220);
  el.classList.add('active-target');

  const rect = el.getBoundingClientRect();
  popover.style.display = 'inline-flex';
  const topY = window.scrollY + rect.top - 42;
  const leftX = Math.max(16, Math.min(window.innerWidth - 240, rect.left + 16));
  popover.style.top = (topY > 60 ? topY : window.scrollY + rect.bottom + 6) + 'px';
  popover.style.left = leftX + 'px';
}}

function hidePopover() {{
  popover.style.display = 'none';
  if (activeAnchorEl) {{
    activeAnchorEl.classList.remove('active-target');
  }}
}}

document.addEventListener('mouseup', (e) => {{
  if (popover.contains(e.target) || e.target.closest('.inline-thread-box') || e.target.closest('.thread-pill')) return;
  const sel = window.getSelection();
  const selText = sel ? sel.toString().trim() : '';
  if (selText.length > 2) {{
    const anchorEl = (sel.anchorNode.nodeType === 1 ? sel.anchorNode : sel.anchorNode.parentElement).closest('.annotatable');
    if (anchorEl) {{
      showPopoverForElement(anchorEl, selText);
      return;
    }}
  }}
}});

document.querySelector('.reader-col').addEventListener('click', (e) => {{
  if (e.target.closest('a') || e.target.closest('button') || e.target.closest('.inline-thread-box') || e.target.closest('.thread-pill') || e.target.closest('summary')) {{
    return;
  }}
  const sel = window.getSelection();
  if (sel && sel.toString().trim().length > 2) return;
  const blk = e.target.closest('.annotatable');
  if (blk) {{
    showPopoverForElement(blk, blk.innerText.split('.')[0]);
  }} else {{
    hidePopover();
  }}
}});

function parseIssueToThread(issue) {{
  const body = issue.body || "";
  const mAnchor = body.match(/<!--\\s*anchor:([a-z0-9-]+)\\s*-->/i) || (issue.title || "").match(/\\[([a-z0-9]+-b\\d+)\\]/i);
  if (!mAnchor) return null;
  const anchor = mAnchor[1];

  let quote = "";
  const mQuote = body.match(/>\\s*Quoted:\\s*"([^"]+)"/i);
  if (mQuote) quote = mQuote[1];

  let question = body
    .replace(/<!--[\\s\\S]*?-->/g, '')
    .replace(/>\\s*Quoted:.*$/gm, '')
    .replace(/\\*\\*Chapter Anchor:\\*\\*.*$/gm, '')
    .trim();
  if (!question) question = issue.title;

  return {{
    number: issue.number,
    anchor,
    quote,
    question,
    url: issue.html_url || issue.url || `https://github.com/${{REPO}}/issues/${{issue.number}}`,
    state: issue.state || 'open',
    createdAt: issue.created_at || issue.createdAt || '',
    comments: (issue.comments_list || issue.comments || [])
  }};
}}

function registerThread(t) {{
  if (!t || !t.anchor) return;
  if (!threadsByAnchor[t.anchor]) threadsByAnchor[t.anchor] = [];
  const existingIdx = threadsByAnchor[t.anchor].findIndex(x => (t.number && x.number === t.number) || x.question === t.question);
  if (existingIdx >= 0) {{
    threadsByAnchor[t.anchor][existingIdx] = t;
  }} else {{
    threadsByAnchor[t.anchor].push(t);
  }}
}}

async function loadAllThreads() {{
  (BAKED_ISSUES || []).forEach(iss => {{
    const t = parseIssueToThread(iss);
    if (t) registerThread(t);
  }});

  try {{
    const localList = JSON.parse(localStorage.getItem('sd_local_threads') || '[]');
    localList.forEach(t => registerThread(t));
  }} catch (e) {{}}

  renderThreadBadges();

  try {{
    const headers = {{ 'Accept': 'application/vnd.github+json' }};
    const tok = localStorage.getItem('sd_gh_token');
    if (tok) headers['Authorization'] = `Bearer ${{tok}}`;
    const res = await fetch(`https://api.github.com/repos/${{REPO}}/issues?labels=line-question&state=all&per_page=100`, {{ headers }});
    if (!res.ok) return;
    const issues = await res.json();
    for (const iss of issues) {{
      if (iss.comments > 0) {{
        try {{
          const cres = await fetch(iss.comments_url, {{ headers }});
          if (cres.ok) iss.comments_list = await cres.json();
        }} catch (e) {{}}
      }}
      const t = parseIssueToThread(iss);
      if (t) registerThread(t);
    }}
    renderThreadBadges();
  }} catch (e) {{}}
}}

function renderThreadBadges() {{
  document.querySelectorAll('.thread-pill').forEach(p => p.remove());
  let total = 0;
  Object.keys(threadsByAnchor).forEach(anchor => {{
    const list = threadsByAnchor[anchor];
    if (!list || !list.length) return;
    total += list.length;
    const el = document.querySelector(`[data-anchor="${{anchor}}"]`);
    if (!el) return;
    const pill = document.createElement('button');
    pill.className = 'thread-pill';
    pill.innerHTML = `💬 ${{list.length}}`;
    pill.title = 'Click to view or reply to inline question thread';
    pill.onclick = (ev) => {{
      ev.stopPropagation();
      toggleInlineThreadDrawer(el, anchor);
    }};
    el.appendChild(pill);
    if (allThreadsExpanded) {{
      toggleInlineThreadDrawer(el, anchor, true);
    }}
  }});
  document.getElementById('thread-total-count').textContent = total;
}}

function toggleAllThreads() {{
  allThreadsExpanded = !allThreadsExpanded;
  if (!allThreadsExpanded) {{
    document.querySelectorAll('.inline-thread-box').forEach(b => b.remove());
  }} else {{
    Object.keys(threadsByAnchor).forEach(anchor => {{
      const el = document.querySelector(`[data-anchor="${{anchor}}"]`);
      if (el) toggleInlineThreadDrawer(el, anchor, true);
    }});
  }}
}}

function openQuestionComposerFromPopover() {{
  if (!activeAnchorEl) return;
  const anchor = activeAnchorEl.getAttribute('data-anchor');
  const quote = activeSelectedQuote;
  hidePopover();
  toggleInlineThreadDrawer(activeAnchorEl, anchor, true, quote);
}}

function toggleInlineThreadDrawer(el, anchor, forceOpen = false, newQuote = "") {{
  const existing = document.getElementById('drawer-' + anchor);
  if (existing && !forceOpen) {{
    existing.remove();
    return;
  }}
  if (existing) existing.remove();

  const box = document.createElement('div');
  box.className = 'inline-thread-box';
  box.id = 'drawer-' + anchor;

  const list = threadsByAnchor[anchor] || [];
  let htmlParts = [];

  list.forEach((t) => {{
    if (t.quote) {{
      htmlParts.push(`<div class="thread-quote">"${{escapeHtml(t.quote)}}"</div>`);
    }}
    htmlParts.push(
      `<div class="thread-msg">` +
      `<div class="thread-meta"><span>You asked · <a href="${{t.url}}" target="_blank" rel="noopener">${{t.number ? '#' + t.number : 'Pending'}}</a></span><span>${{t.state === 'closed' ? '✓ Answered' : 'Open'}}</span></div>` +
      `<div>${{escapeHtml(t.question)}}</div>` +
      `</div>`
    );
    (t.comments || []).forEach(c => {{
      const body = c.body || "";
      htmlParts.push(
        `<div class="thread-msg">` +
        `<div class="thread-meta"><span class="thread-author-bot">↳ Answer / Follow-up</span></div>` +
        `<div style="white-space:pre-wrap;">${{escapeHtml(body)}}</div>` +
        `</div>`
      );
    }});
    if (t.number) {{
      htmlParts.push(
        `<div style="margin-top:8px;">` +
        `<input class="thread-input" id="reply-in-${{t.number}}" placeholder="Write a follow-up reply on #${{t.number}}..."/>` +
        `<div class="thread-actions">` +
        `<span class="thread-hint">Synced with GitHub Issue #${{t.number}}</span>` +
        `<button class="top-btn primary" onclick="submitThreadReply(${{t.number}}, '${{anchor}}')">Reply</button>` +
        `</div></div>`
      );
    }}
  }});

  const quoteToUse = newQuote || (el.innerText || "").trim().slice(0, 180);
  htmlParts.push(
    `<div style="margin-top:${{list.length ? '14px;padding-top:12px;border-top:1px solid var(--border)' : '0'}}">` +
    `<div class="thread-quote" id="quote-${{anchor}}">Quoted: "${{escapeHtml(quoteToUse)}}"</div>` +
    `<textarea class="thread-input" id="ask-in-${{anchor}}" rows="2" placeholder="Ask a question about this line (converted into a GitHub Issue & answered inline)..."></textarea>` +
    `<div class="thread-actions">` +
    `<span class="thread-hint">Anchor: <code>${{anchor}}</code></span>` +
    `<div style="display:flex;gap:6px;">` +
    `<button class="top-btn" onclick="document.getElementById('drawer-${{anchor}}').remove()">Close</button>` +
    `<button class="top-btn primary" onclick="submitInlineQuestion('${{anchor}}')">Post Question</button>` +
    `</div></div></div>`
  );

  box.innerHTML = htmlParts.join('');
  el.insertAdjacentElement('afterend', box);
  const ta = document.getElementById('ask-in-' + anchor);
  if (ta && (!list.length || newQuote)) ta.focus();
}}

async function submitInlineQuestion(anchor) {{
  const ta = document.getElementById('ask-in-' + anchor);
  const qText = (ta ? ta.value : '').trim();
  if (!qText) return;
  const quoteEl = document.getElementById('quote-' + anchor);
  const quote = quoteEl ? quoteEl.textContent.replace(/^Quoted:\\s*"|"$/g, '') : '';

  const issueTitle = `[${{anchor}}] ${{qText.slice(0, 72)}}`;
  const issueBody = `<!-- anchor:${{anchor}} -->\\n> Quoted: "${{quote}}"\\n\\n${{qText}}`;
  const tok = localStorage.getItem('sd_gh_token');

  if (tok) {{
    try {{
      const res = await fetch(`https://api.github.com/repos/${{REPO}}/issues`, {{
        method: 'POST',
        headers: {{
          'Accept': 'application/vnd.github+json',
          'Authorization': `Bearer ${{tok}}`,
          'Content-Type': 'application/json'
        }},
        body: JSON.stringify({{
          title: issueTitle,
          body: issueBody,
          labels: ['line-question']
        }})
      }});
      if (res.ok) {{
        const created = await res.json();
        const t = parseIssueToThread(created);
        if (t) registerThread(t);
        renderThreadBadges();
        const el = document.querySelector(`[data-anchor="${{anchor}}"]`);
        if (el) toggleInlineThreadDrawer(el, anchor, true);
        return;
      }}
    }} catch (e) {{}}
  }}

  const localThread = {{
    number: null,
    anchor,
    quote,
    question: qText,
    url: `https://github.com/${{REPO}}/issues`,
    state: 'open',
    createdAt: new Date().toISOString(),
    comments: []
  }};
  registerThread(localThread);
  const saved = JSON.parse(localStorage.getItem('sd_local_threads') || '[]');
  saved.push(localThread);
  localStorage.setItem('sd_local_threads', JSON.stringify(saved));
  renderThreadBadges();

  const ghUrl = `https://github.com/${{REPO}}/issues/new?labels=line-question&title=${{encodeURIComponent(issueTitle)}}&body=${{encodeURIComponent(issueBody)}}`;
  window.open(ghUrl, '_blank');
  const el = document.querySelector(`[data-anchor="${{anchor}}"]`);
  if (el) toggleInlineThreadDrawer(el, anchor, true);
}}

async function submitThreadReply(issueNumber, anchor) {{
  const inp = document.getElementById('reply-in-' + issueNumber);
  const rText = (inp ? inp.value : '').trim();
  if (!rText) return;
  const tok = localStorage.getItem('sd_gh_token');
  if (tok) {{
    try {{
      const res = await fetch(`https://api.github.com/repos/${{REPO}}/issues/${{issueNumber}}/comments`, {{
        method: 'POST',
        headers: {{
          'Accept': 'application/vnd.github+json',
          'Authorization': `Bearer ${{tok}}`,
          'Content-Type': 'application/json'
        }},
        body: JSON.stringify({{ body: rText }})
      }});
      if (res.ok) {{
        const c = await res.json();
        const list = threadsByAnchor[anchor] || [];
        const target = list.find(x => x.number === issueNumber);
        if (target) {{
          target.comments = target.comments || [];
          target.comments.push(c);
        }}
        const el = document.querySelector(`[data-anchor="${{anchor}}"]`);
        if (el) toggleInlineThreadDrawer(el, anchor, true);
        return;
      }}
    }} catch (e) {{}}
  }}
  window.open(`https://github.com/${{REPO}}/issues/${{issueNumber}}`, '_blank');
}}

function escapeHtml(s) {{
  return (s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}}

function openSourceModal() {{
  document.getElementById('source-modal').classList.add('open');
}}
function openTokenModal() {{
  document.getElementById('gh-token-input').value = localStorage.getItem('sd_gh_token') || '';
  document.getElementById('token-modal').classList.add('open');
}}
function closeModals() {{
  document.querySelectorAll('.modal-backdrop').forEach(m => m.classList.remove('open'));
}}
function saveGhToken() {{
  const v = document.getElementById('gh-token-input').value.trim();
  if (v) {{
    localStorage.setItem('sd_gh_token', v);
    document.getElementById('gh-token-btn').textContent = '🔑 Connected';
  }}
  closeModals();
  loadAllThreads();
}}
function clearGhToken() {{
  localStorage.removeItem('sd_gh_token');
  document.getElementById('gh-token-input').value = '';
  document.getElementById('gh-token-btn').textContent = '🔑 GitHub';
  closeModals();
}}
if (localStorage.getItem('sd_gh_token')) {{
  document.getElementById('gh-token-btn').textContent = '🔑 Connected';
}}

async function submitNewSource() {{
  const title = document.getElementById('src-title').value.trim() || 'New System Design Reference';
  const url = document.getElementById('src-url').value.trim();
  const notes = document.getElementById('src-notes').value.trim();
  const body = `**URL:** ${{url}}\\n\\n**Notes:**\\n${{notes}}`;
  const tok = localStorage.getItem('sd_gh_token');
  if (tok) {{
    try {{
      const res = await fetch(`https://api.github.com/repos/${{REPO}}/issues`, {{
        method: 'POST',
        headers: {{
          'Accept': 'application/vnd.github+json',
          'Authorization': `Bearer ${{tok}}`,
          'Content-Type': 'application/json'
        }},
        body: JSON.stringify({{ title: `[Source] ${{title}}`, body, labels: ['inbox'] }})
      }});
      if (res.ok) {{
        closeModals();
        alert('Source saved to GitHub Issues (label: inbox)!');
        return;
      }}
    }} catch (e) {{}}
  }}
  const ghUrl = `https://github.com/${{REPO}}/issues/new?labels=inbox&title=${{encodeURIComponent('[Source] ' + title)}}&body=${{encodeURIComponent(body)}}`;
  window.open(ghUrl, '_blank');
  closeModals();
}}

let synth = window.speechSynthesis;
let isPlaying = false;
let currentIdx = 0;
let speeds = [1.0, 1.25, 1.5, 1.75, 2.0];
let speedIdx = 0;
let nodes = [];

function getActiveSpeakableNodes() {{
  const activeArt = document.querySelector('.chapter-article.active');
  if (!activeArt) return [];
  return Array.from(activeArt.querySelectorAll('.speakable'));
}}

function clearHighlight() {{
  document.querySelectorAll('.speakable.speaking').forEach(el => el.classList.remove('speaking'));
}}

function speakIndex(idx) {{
  if (!synth) return;
  synth.cancel();
  nodes = getActiveSpeakableNodes();
  if (!nodes.length) return;
  if (idx < 0) idx = 0;
  if (idx >= nodes.length) {{
    stopAudio();
    return;
  }}
  currentIdx = idx;
  clearHighlight();
  const el = nodes[currentIdx];
  el.classList.add('speaking');
  el.scrollIntoView({{ behavior: 'smooth', block: 'center' }});

  const text = el.innerText.replace(/💬\\s*\\d+/g, '').trim();
  if (!text) {{
    speakIndex(currentIdx + 1);
    return;
  }}

  const utter = new SpeechSynthesisUtterance(text);
  utter.rate = speeds[speedIdx];
  utter.onend = () => {{
    if (isPlaying) speakIndex(currentIdx + 1);
  }};
  document.getElementById('audio-status').textContent =
    `🔊 (${{currentIdx + 1}}/${{nodes.length}}) ` + text.slice(0, 68);
  document.getElementById('play-btn').textContent = '⏸ Pause';
  isPlaying = true;
  synth.speak(utter);
}}

function toggleAudio() {{
  if (!synth) return;
  if (isPlaying) {{
    synth.cancel();
    isPlaying = false;
    document.getElementById('play-btn').textContent = '▶ Listen';
  }} else {{
    speakIndex(currentIdx);
  }}
}}

function stopAudio() {{
  if (synth) synth.cancel();
  isPlaying = false;
  currentIdx = 0;
  clearHighlight();
  document.getElementById('play-btn').textContent = '▶ Listen';
}}

function stepAudio(delta) {{
  nodes = getActiveSpeakableNodes();
  if (!nodes.length) return;
  speakIndex(Math.max(0, Math.min(nodes.length - 1, currentIdx + delta)));
}}

function cycleSpeed() {{
  speedIdx = (speedIdx + 1) % speeds.length;
  document.getElementById('speed-btn').textContent = speeds[speedIdx].toFixed(2).replace(/\\.00$/, '.0') + '×';
  if (isPlaying) speakIndex(currentIdx);
}}

function listenFromPopover() {{
  if (!activeAnchorEl) return;
  nodes = getActiveSpeakableNodes();
  const idx = nodes.indexOf(activeAnchorEl);
  hidePopover();
  if (idx !== -1) speakIndex(idx);
}}

window.addEventListener('DOMContentLoaded', () => {{
  const h = (location.hash || '').replace('#', '');
  if (h && document.getElementById('chap-' + h)) {{
    openChapter(h);
  }}
  loadAllThreads();
}});
</script>
</body>
</html>
"""
    (DOCS_DIR / "index.html").write_text(page_html, encoding="utf-8")
    (DOCS_DIR / ".nojekyll").write_text("", encoding="utf-8")
    print(f"Built {DOCS_DIR / 'index.html'} ({len(page_html) // 1024} KB) with {len(chapters_data)} chapters and System Design Library SVGs.")


if __name__ == "__main__":
    build()
