"""Publish markdown documents into Notion, keeping their structure.

Notion's API takes blocks, not markdown, so a document has to be parsed and
rebuilt. Pasting the raw text into a page instead would work and would throw
away every heading, table and code fence, which for a specification is most of
what makes it readable.

WHAT IT KEEPS

  Headings, to three levels, so the page gets a working table of contents.
  Bold, italic, inline code and links, parsed out of the text rather than left
    as asterisks and backticks on the page.
  Fenced code blocks, which is where the ASCII figures live. They stay
    monospaced, which is the only reason they are legible.
  Tables, as real Notion tables with a header row, not as pipes in a paragraph.
  Bulleted and numbered lists, dividers, and block quotes.

THE LIMITS IT WORKS AROUND

  A request may carry 100 blocks, so a long document is appended in batches
    after the page is created.
  One rich-text run may hold 2,000 characters, so long paragraphs and long code
    blocks are split into several runs rather than being truncated by the API.
  A table's rows must all be supplied when the table block is created; they
    cannot be appended afterwards.

THE TOKEN IS NOT IN THIS FILE

It is read from NOTION_TOKEN. A key written into a repository is a key that has
been published, whatever the repository's setting says today.

    export NOTION_TOKEN=...
    python tools/notion_publish.py --parent <page-id> FILE.md [FILE.md ...]
    python tools/notion_publish.py --list        # what the integration can see
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

API = "https://api.notion.com/v1"
VERSION = "2022-06-28"
MAX_BLOCKS = 100          # per request
MAX_RUN = 1900            # characters per rich-text run, under Notion's 2000


def call(method: str, path: str, body: dict | None = None) -> dict:
    token = os.environ.get("NOTION_TOKEN", "").strip()
    if not token:
        raise SystemExit("NOTION_TOKEN is not set.")
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"{API}{path}", data=data, method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Notion-Version": VERSION,
            "Content-Type": "application/json",
        })
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")
        raise SystemExit(f"Notion said {e.code}: {detail[:400]}")


# --------------------------------------------------------------- inline text

INLINE = re.compile(
    r'(\*\*[^*]+?\*\*)'          # bold
    r'|(\*[^*\n]+?\*)'           # italic
    r'|(`[^`]+?`)'               # code
    r'|(\[[^\]]+?\]\([^)]+?\))'  # link
)


def runs(text: str) -> list[dict]:
    """Markdown inline formatting as Notion rich-text runs."""
    text = (text.replace("&nbsp;", " ").replace("&mdash;", "—")
                .replace("&rsquo;", "’").replace("&ldquo;", "“")
                .replace("&rdquo;", "”").replace("&sect;", "§"))
    out: list[dict] = []
    pos = 0

    def plain(s: str, **ann):
        # Long text is split rather than truncated: the API refuses a run over
        # 2,000 characters, and a specification has paragraphs that reach it.
        for i in range(0, len(s), MAX_RUN):
            chunk = s[i:i + MAX_RUN]
            if chunk:
                out.append({"type": "text", "text": {"content": chunk},
                            "annotations": dict(ann)} if ann else
                           {"type": "text", "text": {"content": chunk}})

    for m in INLINE.finditer(text):
        if m.start() > pos:
            plain(text[pos:m.start()])
        bold, ital, code, link = m.groups()
        if bold:
            plain(bold[2:-2], bold=True)
        elif ital:
            plain(ital[1:-1], italic=True)
        elif code:
            plain(code[1:-1], code=True)
        elif link:
            label, url = re.match(r'\[([^\]]+)\]\(([^)]+)\)', link).groups()
            out.append({"type": "text",
                        "text": {"content": label[:MAX_RUN], "link": {"url": url}}})
        pos = m.end()
    if pos < len(text):
        plain(text[pos:])
    return out or [{"type": "text", "text": {"content": ""}}]


def block(kind: str, text: str, **extra) -> dict:
    return {"object": "block", "type": kind,
            kind: {"rich_text": runs(text), **extra}}


# ------------------------------------------------------------------ parsing

FENCE = re.compile(r'^\s*```(\w*)\s*$')
HEADING = re.compile(r'^(#{1,6})\s+(.*)$')
BULLET = re.compile(r'^\s*[-*+]\s+(.*)$')
NUMBERED = re.compile(r'^\s*\d+[.)]\s+(.*)$')
QUOTE = re.compile(r'^\s*>\s?(.*)$')
RULE = re.compile(r'^\s*(-{3,}|\*{3,}|_{3,})\s*$')
TABLE_SEP = re.compile(r'^\s*\|?[\s:|-]+\|[\s:|-]*$')


def cells(line: str) -> list[str]:
    row = line.strip()
    if row.startswith("|"):
        row = row[1:]
    if row.endswith("|"):
        row = row[:-1]
    return [c.strip() for c in row.split("|")]


def table_block(rows: list[list[str]]) -> dict:
    width = max(len(r) for r in rows)
    return {
        "object": "block", "type": "table",
        "table": {
            "table_width": width,
            "has_column_header": True,
            "has_row_header": False,
            # Rows must be supplied here. Notion will not accept them appended
            # to an existing table block.
            "children": [
                {"object": "block", "type": "table_row",
                 "table_row": {"cells": [runs(c) for c in
                                         (r + [""] * (width - len(r)))]}}
                for r in rows
            ],
        },
    }


def to_blocks(md: str) -> list[dict]:
    lines = md.split("\n")
    blocks: list[dict] = []
    i = 0
    while i < len(lines):
        line = lines[i]

        m = FENCE.match(line)
        if m:
            lang = (m.group(1) or "plain text").lower()
            body: list[str] = []
            i += 1
            while i < len(lines) and not FENCE.match(lines[i]):
                body.append(lines[i])
                i += 1
            i += 1
            code = "\n".join(body)
            # Notion's own language list is short; anything unknown is refused,
            # and a figure drawn in box characters is not a language anyway.
            known = {"python", "javascript", "typescript", "json", "bash",
                     "shell", "sql", "html", "css", "yaml", "markdown"}
            blocks.append({
                "object": "block", "type": "code",
                "code": {
                    "language": lang if lang in known else "plain text",
                    "rich_text": [{"type": "text", "text": {"content": code[j:j + MAX_RUN]}}
                                  for j in range(0, max(len(code), 1), MAX_RUN)],
                }})
            continue

        if RULE.match(line):
            blocks.append({"object": "block", "type": "divider", "divider": {}})
            i += 1
            continue

        m = HEADING.match(line)
        if m:
            level = min(len(m.group(1)), 3)
            blocks.append(block(f"heading_{level}", m.group(2).strip()))
            i += 1
            continue

        # A table: a row of pipes followed by a separator row.
        if (line.count("|") >= 2 and i + 1 < len(lines)
                and TABLE_SEP.match(lines[i + 1])):
            rows = [cells(line)]
            i += 2
            while i < len(lines) and lines[i].count("|") >= 2:
                rows.append(cells(lines[i]))
                i += 1
            blocks.append(table_block(rows))
            continue

        m = QUOTE.match(line)
        if m:
            body = [m.group(1)]
            i += 1
            while i < len(lines) and QUOTE.match(lines[i]):
                body.append(QUOTE.match(lines[i]).group(1))
                i += 1
            blocks.append(block("quote", " ".join(body).strip()))
            continue

        m = BULLET.match(line)
        if m:
            blocks.append(block("bulleted_list_item", m.group(1).strip()))
            i += 1
            continue

        m = NUMBERED.match(line)
        if m:
            blocks.append(block("numbered_list_item", m.group(1).strip()))
            i += 1
            continue

        if not line.strip():
            i += 1
            continue

        # A paragraph runs until a blank line or the start of another block.
        para = [line.strip()]
        i += 1
        while i < len(lines) and lines[i].strip() and not (
                FENCE.match(lines[i]) or HEADING.match(lines[i])
                or BULLET.match(lines[i]) or NUMBERED.match(lines[i])
                or RULE.match(lines[i]) or QUOTE.match(lines[i])
                or lines[i].count("|") >= 2):
            para.append(lines[i].strip())
            i += 1
        blocks.append(block("paragraph", " ".join(para)))
    return blocks


# ----------------------------------------------------------------- publishing

def title_of(md: str, fallback: str) -> str:
    for line in md.split("\n"):
        m = HEADING.match(line)
        if m:
            return re.sub(r'[*`]', "", m.group(2)).strip()
    return fallback


def publish(path: Path, parent: str) -> str:
    md = path.read_text(encoding="utf-8")
    blocks = to_blocks(md)
    title = title_of(md, path.stem)

    page = call("POST", "/pages", {
        "parent": {"type": "page_id", "page_id": parent},
        "properties": {"title": {"title": [{"text": {"content": title[:200]}}]}},
        "children": blocks[:MAX_BLOCKS],
    })
    page_id = page["id"]

    # The rest in batches. A document of any size exceeds one request.
    rest = blocks[MAX_BLOCKS:]
    while rest:
        call("PATCH", f"/blocks/{page_id}/children",
             {"children": rest[:MAX_BLOCKS]})
        rest = rest[MAX_BLOCKS:]

    print(f"  {title}\n    {len(blocks)} blocks -> {page.get('url', page_id)}")
    return page_id


def main() -> int:
    args = sys.argv[1:]
    if "--list" in args:
        found = call("POST", "/search", {"page_size": 50})
        results = found.get("results", [])
        if not results:
            print("  The integration can see nothing yet.\n"
                  "  In Notion open the page you want these under, then\n"
                  "  ··· -> Connections -> Claude.")
            return 1
        for r in results:
            props = r.get("properties", {})
            name = ""
            for v in props.values():
                if v.get("type") == "title" and v["title"]:
                    name = v["title"][0]["plain_text"]
            print(f"  {r['object']:<9} {r['id']}  {name or r.get('url','')}")
        return 0

    if "--parent" not in args:
        raise SystemExit(__doc__)
    parent = args[args.index("--parent") + 1].replace("-", "")
    files = [Path(a) for a in args
             if a.endswith(".md") and Path(a).exists()]
    if not files:
        raise SystemExit("No markdown files given.")

    print(f"publishing {len(files)} document(s):")
    for f in files:
        publish(f, parent)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
