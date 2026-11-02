#!/usr/bin/env python3
"""
Builds the minimal mobile-first web app (docs/index.html) from the Markdown
study guides and .excalidraw diagrams in d:/test/PersonalDocuments/sd-interview-prep.
Includes:
- Crisp inline SVG rendering of Minimal Architect .excalidraw diagrams
- Built-in Web Speech API audio player (Play/Pause, Prev/Next, Speed, tap-to-read)
- 1-tap GitHub Issue bookmark inbox for saving sources from phone or PC
"""
import html
import json
import math
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent
DOCS_DIR = ROOT / "docs"
DIAG_DIR = ROOT / "diagrams"
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
        if e.get("type") in ("arrow", "line") and e.get("points"):
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
        fill = "none" if bg == "transparent" else bg
        sw = e.get("strokeWidth", 1.5)
        dash = ' stroke-dasharray="6 4"' if e.get("strokeStyle") == "dashed" else ""

        if etype == "rectangle":
            rx = 10 if e.get("roundness") else 0
            svg.append(
                f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{rx}" '
                f'fill="{fill}" stroke="{stroke}" stroke-width="{sw}"{dash}/>'
            )
        elif etype in ("arrow", "line"):
            pts = e.get("points") or [[0, 0], [w, h]]
            pt_str = " ".join(f"{x + float(p[0]):.1f},{y + float(p[1]):.1f}" for p in pts)
            marker = ' marker-end="url(#ex-arrow)"' if etype == "arrow" else ""
            svg.append(
                f'<polyline points="{pt_str}" fill="none" stroke="{stroke}" '
                f'stroke-width="{sw}" stroke-linecap="round" stroke-linejoin="round"{dash}{marker}/>'
            )
        elif etype == "text":
            txt = e.get("text", "")
            lines = txt.split("\n")
            fsize = float(e.get("fontSize", 14))
            ffam = e.get("fontFamily", 2)
            font_css = (
                "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"
                if ffam == 3
                else "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
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

            line_h = fsize * 1.35
            start_y = y + fsize
            font_weight = "600" if fsize >= 15 else "400"
            tspans = []
            for idx, line in enumerate(lines):
                ly = start_y + idx * line_h
                esc = html.escape(line) if line.strip() else "&#160;"
                weight = "600" if (idx == 0 and len(lines) > 1 and not line.startswith("•")) else font_weight
                tspans.append(f'<tspan x="{tx:.1f}" y="{ly:.1f}" font-weight="{weight}">{esc}</tspan>')
            svg.append(
                f'<text font-family="{font_css}" font-size="{fsize:.1f}" fill="{stroke}" text-anchor="{anchor}">'
                + "".join(tspans)
                + "</text>"
            )

    svg.append("</svg>")
    return "\n".join(svg)


def inline_md(text: str, svg_map: dict) -> str:
    # Escape HTML first
    text = html.escape(text)
    # Code spans
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    # Bold & italic
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", text)
    # Links to .excalidraw -> jump button
    def replace_link(m):
        label, url = m.group(1), m.group(2)
        for diag_name in svg_map:
            if diag_name in url:
                return f'<a href="#diag-{diag_name}" class="diag-chip" onclick="switchTab(\'diagrams\', \'diag-{diag_name}\'); return false;">📐 {label}</a>'
        if url.startswith("http"):
            return f'<a href="{url}" target="_blank" rel="noopener">{label}</a>'
        return f'<span class="file-ref">{label}</span>'

    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", replace_link, text)
    return text


def md_to_html(md_text: str, svg_map: dict, embed_diagrams: bool = False) -> str:
    lines = md_text.splitlines()
    out = []
    in_ul = False
    in_ol = False
    in_code = False
    in_table = False
    code_buf = []
    embedded_seen = set()

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
        if line.startswith("```"):
            close_lists()
            if not in_code:
                in_code = True
                code_buf = []
            else:
                in_code = False
                out.append(f'<pre class="code-block"><code>{html.escape(chr(10).join(code_buf))}</code></pre>')
            continue

        if in_code:
            code_buf.append(raw)
            continue

        if not line.strip():
            close_lists()
            continue

        if line.strip() == "---":
            close_lists()
            out.append("<hr/>")
            continue

        # Table rows
        if line.strip().startswith("|") and line.strip().endswith("|"):
            cells = [c.strip() for c in line.strip()[1:-1].split("|")]
            if all(re.match(r"^[-:]+$", c.replace(" ", "")) for c in cells if c):
                continue
            if not in_table:
                close_lists()
                in_table = True
                out.append('<div class="table-wrap"><table><thead><tr>')
                for c in cells:
                    out.append(f"<th>{inline_md(c, svg_map)}</th>")
                out.append("</tr></thead><tbody>")
            else:
                out.append("<tr>")
                for c in cells:
                    out.append(f'<td class="speakable">{inline_md(c, svg_map)}</td>')
                out.append("</tr>")
            continue
        else:
            if in_table:
                close_lists()

        # Headings
        hm = re.match(r"^(#{1,4})\s+(.*)$", line)
        if hm:
            close_lists()
            lvl = len(hm.group(1))
            htxt = inline_md(hm.group(2), svg_map)
            out.append(f'<h{lvl} class="speakable">{htxt}</h{lvl}>')
            continue

        # Bullet list
        bm = re.match(r"^\s*[-*]\s+(.*)$", line)
        if bm:
            if in_ol:
                out.append("</ol>")
                in_ol = False
            if not in_ul:
                out.append("<ul>")
                in_ul = True
            item_html = inline_md(bm.group(1), svg_map)
            out.append(f'<li class="speakable">{item_html}</li>')
            if embed_diagrams:
                for dname, dsvg in svg_map.items():
                    if dname in raw and dname not in embedded_seen:
                        embedded_seen.add(dname)
                        out.append(f'<div class="inline-diag">{dsvg}<div class="diag-cap">{dname} (pinch or scroll to zoom)</div></div>')
            continue

        # Numbered list
        om = re.match(r"^\s*\d+\.\s+(.*)$", line)
        if om:
            if in_ul:
                out.append("</ul>")
                in_ul = False
            if not in_ol:
                out.append("<ol>")
                in_ol = True
            out.append(f'<li class="speakable">{inline_md(om.group(1), svg_map)}</li>')
            continue

        close_lists()
        p_html = inline_md(line, svg_map)
        out.append(f'<p class="speakable">{p_html}</p>')
        if embed_diagrams:
            for dname, dsvg in svg_map.items():
                if dname in raw and dname not in embedded_seen:
                    embedded_seen.add(dname)
                    out.append(f'<div class="inline-diag">{dsvg}<div class="diag-cap">{dname}</div></div>')

    close_lists()
    return "\n".join(out)


def main():
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    svg_map = {}
    for ex_file in sorted(DIAG_DIR.glob("*.excalidraw")):
        svg_map[ex_file.name] = excalidraw_to_svg(ex_file)

    guide_html = md_to_html((ROOT / "01-week1-learning-guide.md").read_text(encoding="utf-8"), svg_map, embed_diagrams=True)
    plan_html = md_to_html((ROOT / "00-plan.md").read_text(encoding="utf-8"), svg_map, embed_diagrams=False)
    bank_html = md_to_html((ROOT / "question-bank.md").read_text(encoding="utf-8"), svg_map, embed_diagrams=False)
    prog_html = md_to_html((ROOT / "progress.md").read_text(encoding="utf-8"), svg_map, embed_diagrams=False)
    sources_html = md_to_html((ROOT / "sources.md").read_text(encoding="utf-8"), svg_map, embed_diagrams=False)

    diag_cards = []
    diag_titles = {
        "01-kafka-and-redis.excalidraw": "Week 1: Kafka Partitions vs DB Locks & Redis 4 Data Structures",
        "mock0-notification-system.excalidraw": "Mock 0 Reference: Global Notification Service + AI Smart Digest",
        "00-timeline.excalidraw": "4-Week System Design & AI Study Plan",
    }
    for dname, dsvg in svg_map.items():
        title = diag_titles.get(dname, dname)
        diag_cards.append(
            f'<div class="card diag-card" id="diag-{dname}">'
            f'<div class="diag-header"><h3>{html.escape(title)}</h3><span class="badge">{dname}</span></div>'
            f'<div class="svg-scroll">{dsvg}</div>'
            f'</div>'
        )
    diagrams_section_html = "\n".join(diag_cards)

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=5.0" />
  <meta name="theme-color" content="#0f172a" />
  <meta name="apple-mobile-web-app-capable" content="yes" />
  <title>SD + AI Interview Prep</title>
  <link rel="manifest" href="manifest.json" />
  <style>
    :root {{
      --bg: #f8fafc;
      --surface: #ffffff;
      --text: #0f172a;
      --muted: #475569;
      --border: #e2e8f0;
      --accent: #2563eb;
      --accent-soft: #eff6ff;
      --highlight: #fef08a;
      --code-bg: #f1f5f9;
    }}
    [data-theme="dark"] {{
      --bg: #0b0f19;
      --surface: #111827;
      --text: #f1f5f9;
      --muted: #94a3b8;
      --border: #1e293b;
      --accent: #60a5fa;
      --accent-soft: #1e293b;
      --highlight: #422006;
      --code-bg: #1e293b;
    }}
    * {{ box-sizing: border-box; -webkit-tap-highlight-color: transparent; }}
    body {{
      margin: 0;
      font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.65;
      font-size: 16px;
      padding-bottom: 120px;
    }}
    header {{
      position: sticky;
      top: 0;
      z-index: 30;
      background: var(--surface);
      border-bottom: 1px solid var(--border);
      padding: 10px 16px;
    }}
    .top-row {{
      max-width: 860px;
      margin: 0 auto;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
    }}
    .brand {{
      font-weight: 700;
      font-size: 16px;
      letter-spacing: -0.02em;
      display: flex;
      align-items: center;
      gap: 8px;
    }}
    .top-actions {{
      display: flex;
      gap: 8px;
      align-items: center;
    }}
    .btn {{
      border: 1px solid var(--border);
      background: var(--surface);
      color: var(--text);
      padding: 6px 11px;
      border-radius: 8px;
      font-size: 13px;
      font-weight: 500;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 5px;
      text-decoration: none;
    }}
    .btn-primary {{
      background: var(--accent);
      color: #ffffff;
      border-color: var(--accent);
    }}
    .tabs {{
      max-width: 860px;
      margin: 8px auto 0;
      display: flex;
      gap: 6px;
      overflow-x: auto;
      padding-bottom: 2px;
      scrollbar-width: none;
    }}
    .tabs::-webkit-scrollbar {{ display: none; }}
    .tab {{
      border: 1px solid transparent;
      background: transparent;
      color: var(--muted);
      padding: 6px 12px;
      border-radius: 999px;
      font-size: 13.5px;
      font-weight: 500;
      white-space: nowrap;
      cursor: pointer;
    }}
    .tab.active {{
      background: var(--accent-soft);
      color: var(--accent);
      border-color: var(--border);
      font-weight: 600;
    }}
    main {{
      max-width: 860px;
      margin: 16px auto;
      padding: 0 14px;
    }}
    .pane {{ display: none; }}
    .pane.active {{ display: block; }}
    .card {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 18px;
      margin-bottom: 16px;
    }}
    h1 {{ font-size: 22px; margin: 0 0 12px; letter-spacing: -0.02em; }}
    h2 {{ font-size: 18px; margin: 26px 0 10px; padding-top: 12px; border-top: 1px solid var(--border); letter-spacing: -0.01em; }}
    h3 {{ font-size: 15.5px; margin: 18px 0 6px; }}
    p, li {{ font-size: 15.5px; color: var(--text); }}
    ul, ol {{ padding-left: 20px; margin: 8px 0; }}
    li {{ margin-bottom: 6px; }}
    code {{
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 13.5px;
      background: var(--code-bg);
      padding: 2px 6px;
      border-radius: 5px;
    }}
    .code-block {{
      background: var(--code-bg);
      padding: 12px 14px;
      border-radius: 10px;
      overflow-x: auto;
      font-size: 13px;
      line-height: 1.5;
    }}
    .code-block code {{ background: none; padding: 0; }}
    .table-wrap {{ overflow-x: auto; margin: 12px 0; border: 1px solid var(--border); border-radius: 10px; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
    th, td {{ text-align: left; padding: 9px 12px; border-bottom: 1px solid var(--border); vertical-align: top; }}
    th {{ background: var(--code-bg); font-weight: 600; }}
    .inline-diag, .svg-scroll {{
      margin: 14px 0;
      border: 1px solid var(--border);
      border-radius: 12px;
      overflow-x: auto;
      background: #ffffff;
      padding: 8px;
    }}
    .ex-svg {{
      display: block;
      min-width: 680px;
      height: auto;
    }}
    .diag-cap {{
      font-size: 12px;
      color: #64748b;
      text-align: center;
      padding-top: 4px;
    }}
    .diag-chip {{
      display: inline-flex;
      align-items: center;
      gap: 4px;
      background: var(--accent-soft);
      color: var(--accent);
      padding: 2px 8px;
      border-radius: 6px;
      text-decoration: none;
      font-size: 13.5px;
      font-weight: 500;
    }}
    .speakable {{
      cursor: pointer;
      border-radius: 6px;
      transition: background 0.15s ease;
    }}
    .speakable.speaking {{
      background: var(--highlight);
      padding-left: 6px;
      padding-right: 6px;
    }}
    .hint-banner {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      font-size: 13px;
      color: var(--muted);
      background: var(--accent-soft);
      border: 1px solid var(--border);
      padding: 8px 12px;
      border-radius: 10px;
      margin-bottom: 14px;
    }}
    /* Sticky Audio Bar */
    .audio-bar {{
      position: fixed;
      bottom: 0;
      left: 0;
      right: 0;
      z-index: 40;
      background: var(--surface);
      border-top: 1px solid var(--border);
      padding: 10px 14px calc(10px + env(safe-area-inset-bottom));
      box-shadow: 0 -4px 16px rgba(0, 0, 0, 0.06);
    }}
    .audio-inner {{
      max-width: 860px;
      margin: 0 auto;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      flex-wrap: wrap;
    }}
    .audio-controls {{
      display: flex;
      align-items: center;
      gap: 6px;
    }}
    .audio-status {{
      font-size: 12.5px;
      color: var(--muted);
      flex: 1;
      min-width: 120px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }}
    select.voice-select {{
      max-width: 140px;
      font-size: 12px;
      padding: 5px 6px;
      border-radius: 6px;
      border: 1px solid var(--border);
      background: var(--surface);
      color: var(--text);
    }}
    /* Modal for Quick Bookmark */
    .modal-backdrop {{
      display: none;
      position: fixed;
      inset: 0;
      background: rgba(15, 23, 42, 0.55);
      z-index: 50;
      align-items: center;
      justify-content: center;
      padding: 16px;
    }}
    .modal-backdrop.open {{ display: flex; }}
    .modal {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 14px;
      max-width: 480px;
      width: 100%;
      padding: 18px;
    }}
    .modal input, .modal textarea {{
      width: 100%;
      padding: 9px 11px;
      margin: 6px 0 12px;
      border: 1px solid var(--border);
      border-radius: 8px;
      background: var(--bg);
      color: var(--text);
      font-family: inherit;
      font-size: 14px;
    }}
    .diag-header {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 8px;
      margin-bottom: 8px;
    }}
    .badge {{
      font-size: 12px;
      color: var(--muted);
      background: var(--code-bg);
      padding: 2px 8px;
      border-radius: 999px;
    }}
  </style>
</head>
<body>
  <header>
    <div class="top-row">
      <div class="brand">⚡ SD + AI Prep</div>
      <div class="top-actions">
        <button class="btn btn-primary" onclick="openBookmarkModal()">+ Save Source</button>
        <button class="btn" onclick="toggleTheme()" id="themeBtn" title="Toggle Dark/Light Mode">◐</button>
      </div>
    </div>
    <nav class="tabs">
      <button class="tab active" data-tab="guide" onclick="switchTab('guide')">📘 Week 1 Guide</button>
      <button class="tab" data-tab="diagrams" onclick="switchTab('diagrams')">📐 Diagrams (3)</button>
      <button class="tab" data-tab="plan" onclick="switchTab('plan')">🗓️ 4-Week Plan</button>
      <button class="tab" data-tab="bank" onclick="switchTab('bank')">🎯 Question Bank</button>
      <button class="tab" data-tab="progress" onclick="switchTab('progress')">📊 Progress & Quiz</button>
      <button class="tab" data-tab="sources" onclick="switchTab('sources')">🔗 Sources</button>
    </nav>
  </header>

  <main>
    <div class="hint-banner">
      <span>🎧 <strong>Audio Mode:</strong> Tap <strong>▶ Play</strong> below or tap any paragraph to start listening from that line.</span>
    </div>

    <section id="pane-guide" class="pane active">
      <div class="card">{guide_html}</div>
    </section>

    <section id="pane-diagrams" class="pane">
      {diagrams_section_html}
    </section>

    <section id="pane-plan" class="pane">
      <div class="card">{plan_html}</div>
    </section>

    <section id="pane-bank" class="pane">
      <div class="card">{bank_html}</div>
    </section>

    <section id="pane-progress" class="pane">
      <div class="card">{prog_html}</div>
    </section>

    <section id="pane-sources" class="pane">
      <div class="card">{sources_html}</div>
    </section>
  </main>

  <div class="audio-bar">
    <div class="audio-inner">
      <div class="audio-controls">
        <button class="btn" onclick="prevLine()" title="Previous paragraph">⏮</button>
        <button class="btn btn-primary" id="playBtn" onclick="togglePlay()">▶ Listen</button>
        <button class="btn" onclick="nextLine()" title="Next paragraph">⏭</button>
        <button class="btn" id="speedBtn" onclick="cycleSpeed()">1x</button>
      </div>
      <div class="audio-status" id="audioStatus">Tap Play or any paragraph to listen</div>
      <select class="voice-select" id="voiceSelect" onchange="onVoiceChange()"></select>
    </div>
  </div>

  <div class="modal-backdrop" id="bmModal" onclick="if(event.target===this)closeBookmarkModal()">
    <div class="modal">
      <h3 style="margin-top:0">📌 Save Interview Source / Note</h3>
      <p style="font-size:13px;color:var(--muted);margin-top:4px">
        Submits a tagged GitHub Issue to <code>{REPO_SLUG}</code>. Our weekly refresh script automatically ingests open issues into your prep materials.
      </p>
      <label style="font-size:13px;font-weight:600">Title or Company / Question</label>
      <input id="bmTitle" placeholder="e.g. Meta E5 SD: Distributed Rate Limiter + Token Bucket" />
      <label style="font-size:13px;font-weight:600">URL or Raw Notes</label>
      <textarea id="bmBody" rows="4" placeholder="Paste link, Blind/LeetCode snippet, or key takeaway..."></textarea>
      <div style="display:flex;justify-content:flex-end;gap:8px">
        <button class="btn" onclick="closeBookmarkModal()">Cancel</button>
        <button class="btn btn-primary" onclick="submitBookmarkIssue()">Open in GitHub ↗</button>
      </div>
    </div>
  </div>

  <script>
    // Theme toggle
    const savedTheme = localStorage.getItem('sd_theme') || (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
    document.documentElement.setAttribute('data-theme', savedTheme);
    function toggleTheme() {{
      const next = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
      document.documentElement.setAttribute('data-theme', next);
      localStorage.setItem('sd_theme', next);
    }}

    // Tabs
    function switchTab(tabId, scrollTargetId) {{
      stopSpeech();
      document.querySelectorAll('.tab').forEach(b => b.classList.toggle('active', b.dataset.tab === tabId));
      document.querySelectorAll('.pane').forEach(p => p.classList.toggle('active', p.id === 'pane-' + tabId));
      if (scrollTargetId) {{
        setTimeout(() => {{
          const el = document.getElementById(scrollTargetId);
          if (el) el.scrollIntoView({{ behavior: 'smooth', block: 'start' }});
        }}, 60);
      }} else {{
        window.scrollTo({{ top: 0, behavior: 'smooth' }});
      }}
    }}

    // Web Speech API Audio Player
    const synth = window.speechSynthesis;
    let voices = [];
    let selectedVoice = null;
    let speeds = [1.0, 1.25, 1.5, 1.75, 2.0];
    let speedIdx = 0;
    let isPlaying = false;
    let currentIdx = 0;

    function getActiveSpeakables() {{
      const activePane = document.querySelector('.pane.active');
      return activePane ? Array.from(activePane.querySelectorAll('.speakable')) : [];
    }}

    function loadVoices() {{
      if (!synth) return;
      voices = synth.getVoices().filter(v => v.lang && v.lang.toLowerCase().startsWith('en'));
      if (!voices.length) voices = synth.getVoices();
      const sel = document.getElementById('voiceSelect');
      sel.innerHTML = '';
      // Prefer Natural / Online / Samantha / Google US English voices
      voices.sort((a, b) => {{
        const score = v => (v.name.includes('Natural') || v.name.includes('Online') || v.name.includes('Samantha') || v.name.includes('Google')) ? 0 : 1;
        return score(a) - score(b);
      }});
      voices.forEach((v, idx) => {{
        const opt = document.createElement('option');
        opt.value = idx;
        opt.textContent = v.name.replace(/Microsoft |Online \\(Natural\\) - /g, '');
        sel.appendChild(opt);
      }});
      selectedVoice = voices[0] || null;
    }}
    if (synth) {{
      loadVoices();
      if (synth.onvoiceschanged !== undefined) synth.onvoiceschanged = loadVoices;
    }}

    function onVoiceChange() {{
      const sel = document.getElementById('voiceSelect');
      selectedVoice = voices[Number(sel.value)] || null;
      if (isPlaying) speakAt(currentIdx);
    }}

    function clearHighlights() {{
      document.querySelectorAll('.speakable.speaking').forEach(el => el.classList.remove('speaking'));
    }}

    function speakAt(idx) {{
      if (!synth) return;
      const items = getActiveSpeakables();
      if (!items.length) return;
      if (idx < 0) idx = 0;
      if (idx >= items.length) {{
        stopSpeech();
        return;
      }}
      currentIdx = idx;
      synth.cancel();
      clearHighlights();

      const el = items[currentIdx];
      el.classList.add('speaking');
      el.scrollIntoView({{ behavior: 'smooth', block: 'center' }});

      const cleanText = el.innerText.replace(/📐/g, '').trim();
      document.getElementById('audioStatus').textContent = `[${{currentIdx + 1}}/${{items.length}}] ` + cleanText.slice(0, 65);

      const utter = new SpeechSynthesisUtterance(cleanText);
      if (selectedVoice) utter.voice = selectedVoice;
      utter.rate = speeds[speedIdx];
      utter.onend = () => {{
        if (isPlaying) speakAt(currentIdx + 1);
      }};
      utter.onerror = () => {{
        if (isPlaying) speakAt(currentIdx + 1);
      }};
      isPlaying = true;
      document.getElementById('playBtn').textContent = '⏸ Pause';
      synth.speak(utter);
    }}

    function togglePlay() {{
      if (!synth) {{
        alert('Web Speech API is not supported in this browser.');
        return;
      }}
      if (isPlaying) {{
        stopSpeech();
      }} else {{
        speakAt(currentIdx);
      }}
    }}

    function stopSpeech() {{
      isPlaying = false;
      if (synth) synth.cancel();
      clearHighlights();
      document.getElementById('playBtn').textContent = '▶ Listen';
    }}

    function prevLine() {{
      speakAt(Math.max(0, currentIdx - 1));
    }}

    function nextLine() {{
      speakAt(currentIdx + 1);
    }}

    function cycleSpeed() {{
      speedIdx = (speedIdx + 1) % speeds.length;
      document.getElementById('speedBtn').textContent = speeds[speedIdx] + 'x';
      if (isPlaying) speakAt(currentIdx);
    }}

    // Tap any paragraph to start reading from there
    document.addEventListener('click', e => {{
      const sp = e.target.closest('.speakable');
      if (!sp || e.target.closest('a')) return;
      const items = getActiveSpeakables();
      const idx = items.indexOf(sp);
      if (idx !== -1 && isPlaying) {{
        speakAt(idx);
      }} else if (idx !== -1) {{
        currentIdx = idx;
        clearHighlights();
        sp.classList.add('speaking');
        document.getElementById('audioStatus').textContent = `Ready at [${{idx + 1}}/${{items.length}}] — tap ▶ Listen`;
      }}
    }});

    // Bookmark modal -> GitHub Issue
    function openBookmarkModal() {{
      document.getElementById('bmModal').classList.add('open');
      document.getElementById('bmTitle').focus();
    }}
    function closeBookmarkModal() {{
      document.getElementById('bmModal').classList.remove('open');
    }}
    function submitBookmarkIssue() {{
      const title = document.getElementById('bmTitle').value.trim() || 'New Interview Source / Note';
      const body = document.getElementById('bmBody').value.trim();
      const url = `https://github.com/{REPO_SLUG}/issues/new?labels=inbox&title=${{encodeURIComponent('[Inbox] ' + title)}}&body=${{encodeURIComponent(body)}}`;
      window.open(url, '_blank');
      closeBookmarkModal();
    }}
  </script>
</body>
</html>
"""
    (DOCS_DIR / "index.html").write_text(page, encoding="utf-8")
    (DOCS_DIR / ".nojekyll").write_text("", encoding="utf-8")

    manifest = {
        "name": "SD + AI Interview Prep",
        "short_name": "SD Prep",
        "start_url": "./index.html",
        "display": "standalone",
        "background_color": "#0f172a",
        "theme_color": "#0f172a",
    }
    (DOCS_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Generated {DOCS_DIR / 'index.html'} ({len(page):,} bytes) with {len(svg_map)} embedded SVG diagrams.")


if __name__ == "__main__":
    main()
