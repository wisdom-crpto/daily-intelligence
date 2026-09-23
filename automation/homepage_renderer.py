"""Private, deterministic Daily Intelligence validation and static rendering.

No network, API SDK, shell execution, or imports from the publication checkout.
The small Markdown renderer and archive card layout are audited adaptations of
automation/generate.py:347-496 and dios.py:622-712. Source flags are model claims;
these structural gates do not prove factual accuracy or publication approval.
"""

from __future__ import annotations

import datetime as dt
import html
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import textwrap
import unicodedata
from urllib.parse import unquote, urlsplit


SECTIONS = (
    "Today's Thesis", "Executive Summary", "AI Daily", "Business Daily",
    "Macro Observation", "Signal Dashboard", "Deep Insight", "Tomorrow Watch",
    "One Chart", "Quote of the Day", "Action Items",
)
PAYLOAD_KEYS = {"ready", "reason", "markdown", "data_json", "chart_json"}
DATA_KEYS = {
    "schema_version", "date", "generated_at", "model", "mode", "thesis",
    "summary", "relative_html", "topics", "quote", "markets", "sources",
    "search_text",
}
SOURCE_KEYS = {"title", "summary", "url", "published", "source", "primary"}
LOCAL_IMAGES = {"assets/chart.svg", "assets/cover.svg"}
DATE_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}\Z")
IMAGE_RE = re.compile(r"!\[([^\]\n]*)\]\(([^)\n]+)\)")
LINK_RE = re.compile(r"(?<!!)\[([^\]\n]+)\]\(([^)\n]+)\)")
SECRET_RE = re.compile(
    r"\b(?:sk-(?!hynix-)[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9]{20,}|"
    r"github_pat_[A-Za-z0-9_]{20,}|AKIA[A-Z0-9]{16})\b|"
    r"-----BEGIN (?:[A-Z ]+)?PRIVATE KEY-----|"
    r"\bBearer\s+[A-Za-z0-9._~+/-]{16,}|"
    r"(?:api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret)"
    r"[\s\"']*[:=][\s\"']*[^\s\"',}]{8,}", re.I,
)
RAW_HTML_RE = re.compile(r"<\s*(?:/?[A-Za-z][^>]*|![^>]*)>")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _text(value: object, field: str, minimum: int = 1, maximum: int = 10000) -> str:
    _require(isinstance(value, str), f"{field}: expected text")
    _require(minimum <= len(value.strip()) <= maximum, f"{field}: invalid length")
    _require(not re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff]", value),
             f"{field}: invalid control character")
    return value


def _content_safety(value: str, field: str) -> None:
    _require(not SECRET_RE.search(value), f"{field}: credential-like content forbidden")
    _require(not RAW_HTML_RE.search(value), f"{field}: raw HTML/SVG forbidden")
    _require(not re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff]", value),
             f"{field}: invalid control character")


def _date(value: object) -> str:
    _require(isinstance(value, str) and DATE_RE.fullmatch(value) is not None,
             "date: expected YYYY-MM-DD")
    try:
        dt.date.fromisoformat(value)
    except ValueError:
        raise ValueError("date: invalid calendar date") from None
    return value


def _relative(report_date: str) -> str:
    return f"{report_date[:4]}/{report_date[5:7]}/{report_date}"


def _no_duplicates(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        _require(key not in result, "JSON: duplicate object key")
        result[key] = value
    return result


def _invalid_constant(_: str) -> None:
    raise ValueError("JSON: non-finite number")


def _object(raw: str, field: str) -> dict:
    try:
        value = json.loads(raw, object_pairs_hook=_no_duplicates,
                           parse_constant=_invalid_constant)
    except (json.JSONDecodeError, RecursionError):
        raise ValueError(f"{field}: invalid JSON") from None
    _require(isinstance(value, dict), f"{field}: expected object")
    return value


def _url(value: object, field: str) -> str:
    value = _text(value, field, maximum=4000)
    _require(not re.search(r"[\s<>\"'\\\x00-\x1f]", value), f"{field}: unsafe URL")
    try:
        parts = urlsplit(value)
        host = parts.hostname or ""
        port = parts.port
    except ValueError:
        raise ValueError(f"{field}: invalid URL") from None
    _require(parts.scheme in {"http", "https"} and bool(host) and "." in host
             and not parts.username and not parts.password and port in {None, 80, 443},
             f"{field}: expected public HTTP(S) URL")
    _require(not host.lower().endswith((".local", ".localhost", ".internal")),
             f"{field}: private URL forbidden")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    _require(address is None or address.is_global, f"{field}: private URL forbidden")
    _require(not re.search(r"(?:token|api.?key|secret|signature|password)=", unquote(parts.query), re.I),
             f"{field}: credential query forbidden")
    _require(not SECRET_RE.search(unquote(value)), f"{field}: credential-like URL")
    return value


def _normalized(value: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKC", value).casefold()
                   if c.isalnum())


def _chinese(value: str) -> int:
    # URL characters cannot satisfy prose-length gates.
    value = re.sub(r"https?://[^\s)]+", "", value)
    return len(re.findall(r"[\u3400-\u9fff]", value))


def _safe_root(path: Path, must_exist: bool = True) -> Path:
    path = Path(path).absolute()
    _require(".." not in path.parts, "path: parent traversal forbidden")
    _require(not path.is_symlink(), "path: symlink root forbidden")
    # macOS standard temporary-directory aliases are the only parent exceptions.
    for parent in path.parents:
        _require(not parent.is_symlink() or parent in {Path("/tmp"), Path("/var")},
                 "path: symlink ancestor forbidden")
    path = path.resolve(strict=False)
    if must_exist:
        _require(path.is_dir(), "path: archive directory missing")
    return path


def _no_symlinks(root: Path, path: Path) -> None:
    _require(path.is_relative_to(root), "path: outside root")
    for item in (path, *path.parents):
        if item == root:
            break
        _require(not item.is_symlink(), "path: symlink forbidden")


def _archive_records(root: Path) -> tuple[list[dict], list[str]]:
    """Read historical schema variants without retroactive content requirements."""
    root = _safe_root(root)
    records, quote_haystacks = [], []
    seen, data_paths = set(), set()
    for year in sorted(root.iterdir()):
        if not re.fullmatch(r"[0-9]{4}", year.name):
            continue
        _no_symlinks(root, year)
        _require(year.is_dir(), "archive: invalid year directory")
        for month in sorted(year.iterdir()):
            if month.name.startswith("."):
                continue
            _no_symlinks(root, month)
            _require(month.is_dir() and re.fullmatch(r"(?:0[1-9]|1[0-2])", month.name)
                     is not None, "archive: invalid month directory")
            for issue in sorted(month.iterdir()):
                if issue.name.startswith("."):
                    continue
                _no_symlinks(root, issue)
                issue_date = _date(issue.name)
                _require(issue.is_dir() and issue_date[:4] == year.name
                         and issue_date[5:7] == month.name, "archive: invalid issue path")
                for parent, directories, files in os.walk(issue, followlinks=False):
                    for name in directories + files:
                        _no_symlinks(root, Path(parent) / name)
                for name in ("data.json", "Daily Intelligence.md", "Daily Intelligence.html"):
                    _require((issue / name).is_file(), "archive: incomplete existing issue")
                try:
                    raw = (issue / "data.json").read_text(encoding="utf-8")
                    markdown = (issue / "Daily Intelligence.md").read_text(encoding="utf-8")
                except (OSError, UnicodeError):
                    raise ValueError("archive: unreadable existing issue") from None
                record = _object(raw, "archive record")
                _require(record.get("date") == issue_date and issue_date not in seen,
                         "archive: mismatched or duplicate date")
                canonical = _relative(issue_date) + "/Daily Intelligence.html"
                relative_html = record.get("relative_html")
                _require(isinstance(relative_html, str)
                         and unquote(relative_html) == canonical,
                         "archive: invalid relative_html")
                for key in ("thesis", "summary"):
                    _require(isinstance(record.get(key, ""), str),
                             "archive: invalid card metadata")
                quote = record.get("quote")
                _require(quote is None or isinstance(quote, dict), "archive: invalid quote")
                seen.add(issue_date)
                data_paths.add(issue / "data.json")
                records.append(record)
                quote_haystacks.extend((_normalized(raw), _normalized(markdown)))
    _require(all(path in data_paths for path in root.glob("*/*/*/data.json")),
             "archive: unrecognized record path")
    return sorted(records, key=lambda item: item["date"], reverse=True), quote_haystacks


def _sections(markdown: str) -> dict[str, str]:
    headings = list(re.finditer(r"^##\s+(.+)$", markdown, re.M))
    found, order = {}, []
    for index, heading in enumerate(headings):
        label = _normalized(heading.group(1))
        matches = [name for name in SECTIONS if _normalized(name) in label]
        _require(len(matches) <= 1, "markdown: ambiguous section")
        if matches:
            name = matches[0]
            _require(name not in found, "markdown: duplicate section")
            end = headings[index + 1].start() if index + 1 < len(headings) else len(markdown)
            found[name] = markdown[heading.end():end].strip()
            order.append(name)
    _require(tuple(order) == SECTIONS, "markdown: missing or unordered formal sections")
    for name, body in found.items():
        _require(_chinese(body) >= (10 if name == "Quote of the Day" else 20),
                 "markdown: empty or undersized section")
    _require(_chinese("\n".join(found.values())) >= 2500,
             "markdown: formal report needs at least 2500 Chinese characters")
    _require(_chinese(found["Deep Insight"]) >= 600,
             "markdown: Deep Insight needs at least 600 Chinese characters")
    return found


def _chart(raw: str, markdown: str) -> dict:
    chart = _object(raw, "chart_json")
    _require(set(chart) == {"title", "unit", "source_url", "series"},
             "chart: invalid fields")
    _text(chart["title"], "chart.title", maximum=90)
    _text(chart["unit"], "chart.unit", maximum=40)
    source = _url(chart["source_url"], "chart.source_url")
    _require(source in markdown, "chart: source must appear in report")
    series = chart["series"]
    _require(isinstance(series, list) and 1 <= len(series) <= 12,
             "chart: expected 1-12 observations")
    labels = set()
    for point in series:
        _require(isinstance(point, dict) and set(point) == {"label", "value", "status"},
                 "chart: invalid observation fields; use one top-level unit")
        label = _text(point["label"], "chart.label", maximum=65)
        _require(label not in labels, "chart: duplicate label")
        labels.add(label)
        value = point["value"]
        _require(type(value) in {int, float} and math.isfinite(value) and abs(value) <= 1e15,
                 "chart: numeric value required; unknown is not zero")
        _require(isinstance(point["status"], str)
                 and point["status"] in {"actual", "forecast", "estimate", "reported"},
                 "chart: unsupported observation status")
    return chart


def validate_payload(payload: dict, report_date: str, archive_root: Path) -> dict:
    """Return {data, chart, sections, records}; raise ValueError without content echo."""
    report_date = _date(report_date)
    _require(isinstance(payload, dict) and set(payload) == PAYLOAD_KEYS,
             "payload: exact fields required")
    _require(type(payload["ready"]) is bool and isinstance(payload["reason"], str),
             "payload: invalid ready/reason")
    _require(payload["ready"], "payload: model did not produce a ready report")
    markdown = _text(payload["markdown"], "markdown", maximum=150000)
    data_raw = _text(payload["data_json"], "data_json", maximum=300000)
    chart_raw = _text(payload["chart_json"], "chart_json", maximum=30000)
    combined = "\n".join((markdown, data_raw, chart_raw, payload["reason"]))
    _content_safety(combined, "payload")
    images = list(IMAGE_RE.finditer(markdown))
    _require(len(images) == markdown.count("!["), "markdown: unsupported image syntax")
    _require(all(match.group(2) in LOCAL_IMAGES for match in images),
             "markdown: only deterministic local image assets allowed")
    _require(any(match.group(2) == "assets/chart.svg" for match in images),
             "markdown: chart asset reference required")
    for match in LINK_RE.finditer(markdown):
        _url(match.group(2), "markdown.link")
    _require(report_date in markdown[:500], "markdown: report date missing from header")
    sections = _sections(markdown)
    data = _object(data_raw, "data_json")
    _content_safety(str(data), "data")
    _require(set(data) == DATA_KEYS, "data: exact schema fields required")
    _require(type(data["schema_version"]) is int and data["schema_version"] == 1,
             "data: unsupported schema")
    _require(data["date"] == report_date and data["mode"] == "model",
             "data: wrong date or non-model mode")
    for field in ("generated_at", "model", "thesis", "summary"):
        _text(data[field], f"data.{field}")
    _text(data["search_text"], "data.search_text", maximum=150000)
    _require(data["model"] in {"gpt-5.6-sol", "gpt-6-astra", "Codex (GPT-6)"}, "data: unexpected model")
    try:
        generated = dt.datetime.fromisoformat(data["generated_at"])
    except ValueError:
        raise ValueError("data: invalid generated_at") from None
    _require(generated.tzinfo is not None, "data: generated_at must include timezone")
    _require(generated.astimezone(dt.timezone(dt.timedelta(hours=8))).date().isoformat()
             >= report_date, "data: generation cannot predate report")
    _require(generated <= dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=10),
             "data: generation timestamp is in the future")
    _require(_chinese(data["thesis"]) >= 20 and _chinese(data["summary"]) >= 30,
             "data: undersized Chinese metadata")
    canonical_html = _relative(report_date) + "/Daily%20Intelligence.html"
    _require(data["relative_html"] == canonical_html, "data: invalid relative_html")
    _require(isinstance(data["topics"], list) and 1 <= len(data["topics"]) <= 40,
             "data: topics required")
    for topic in data["topics"]:
        _text(topic, "data.topic", maximum=100)
    _require(isinstance(data["markets"], list), "data: markets must be a list")
    for market in data["markets"]:
        _require(isinstance(market, dict), "data: invalid market entry")
        _text(market.get("name"), "market.name")
        _text(market.get("status"), "market.status")
        value = market.get("value")
        _require(value is None or value == "N/A" or
                 (type(value) in {int, float} and math.isfinite(value)),
                 "market: invalid or non-finite value")
        if type(value) in {int, float}:
            _text(market.get("unit"), "market.unit")
            _url(market.get("source_url"), "market.source_url")
            _require(market["source_url"] in markdown, "market: source missing from report")
            _require(not re.search(r"unknown|unavailable|missing|N/A|待核实|未观测|缺失",
                                   market["status"], re.I),
                     "market: unavailable observation cannot have a numeric value")
    sources = data["sources"]
    _require(isinstance(sources, dict) and set(sources) == {"ai", "business_macro"},
             "data: required source categories missing")
    for category in ("ai", "business_macro"):
        _require(isinstance(sources[category], list) and 1 <= len(sources[category]) <= 50,
                 "data: source category must be nonempty")
        for source in sources[category]:
            _require(isinstance(source, dict) and set(source) == SOURCE_KEYS,
                     "source: invalid fields")
            for key in ("title", "summary", "source"):
                _text(source[key], f"source.{key}")
            if source["published"] is None:
                _require(re.search(r"unknown|unavailable|undated|not disclosed|未知|未披露|未标注|不详|无法核实",
                                   source["summary"], re.I) is not None,
                         "source: unknown publication date requires limitation in summary")
            else:
                _require(_date(source["published"]) <= report_date,
                         "source: publication is after report date")
            url = _url(source["url"], "source.url")
            _require(source["primary"] is True, "source: explicit primary-source claim required")
            _require(url in markdown, "source: URL missing from report")
            _require(urlsplit(url).hostname not in {"news.google.com", "news.yahoo.com"},
                     "source: discovery aggregator is not primary evidence")
    quote = data["quote"]
    _require(isinstance(quote, dict)
             and set(quote) == {"english", "speaker", "chinese", "source_url"},
             "quote: exact fields required")
    for field in ("english", "speaker", "chinese"):
        _text(quote[field], f"quote.{field}", maximum=1500)
        _require(_normalized(quote[field]) in _normalized(sections["Quote of the Day"]),
                 "quote: metadata and report disagree")
    quote_key = _normalized(quote["english"])
    _require(len(quote_key) >= 12, "quote: English text too short")
    _require(_url(quote["source_url"], "quote.source_url") in markdown,
             "quote: provenance URL missing from report")
    chart = _chart(chart_raw, markdown)
    _content_safety(str(chart), "chart")
    for point in chart["series"]:
        _require(any(type(market.get("value")) in {int, float}
                     and market["value"] == point["value"]
                     and market.get("unit") == chart["unit"]
                     and market.get("source_url") == chart["source_url"]
                     for market in data["markets"]),
                 "chart: value/unit/source must match a data.markets entry")
    records, historical_text = _archive_records(archive_root)
    _require(not SECRET_RE.search(json.dumps(records, ensure_ascii=False)),
             "archive: credential-like content cannot enter rebuilt index")
    _require(not any(record["date"] == report_date for record in records),
             "archive: dated issue already exists")
    _require(not (Path(archive_root) / _relative(report_date)).exists(),
             "archive: dated path already exists")
    _require(not any(quote_key in text for text in historical_text),
             "quote: already present in historical archive")
    return {"data": data, "chart": chart, "sections": sections, "records": records}


def _inline(text: str) -> str:
    def escaped_markup(value: str) -> str:
        escaped = html.escape(value)
        escaped = re.sub(r"\*\*([^*<>]+)\*\*", r"<strong>\1</strong>", escaped)
        return re.sub(r"`([^`<>]+)`", r"<code>\1</code>", escaped)

    tokens = [("image", match) for match in IMAGE_RE.finditer(text)]
    tokens += [("link", match) for match in LINK_RE.finditer(text)]
    parts, cursor = [], 0
    for kind, match in sorted(tokens, key=lambda item: item[1].start()):
        if match.start() < cursor:
            continue
        parts.append(escaped_markup(text[cursor:match.start()]))
        label, url = (html.escape(value, quote=True) for value in match.groups())
        if kind == "image":
            parts.append(f'<img src="{url}" alt="{label}" loading="lazy">')
        else:
            parts.append(f'<a href="{url}" target="_blank" rel="noopener noreferrer">{label}</a>')
        cursor = match.end()
    parts.append(escaped_markup(text[cursor:]))
    return "".join(parts)


def _report_html(markdown: str, title: str) -> str:
    output, paragraph, table = [], [], []
    in_list = False

    def flush() -> None:
        nonlocal paragraph, table, in_list
        if paragraph:
            output.append("<p>" + _inline(" ".join(paragraph)) + "</p>")
            paragraph = []
        if in_list:
            output.append("</ul>")
            in_list = False
        if table:
            output.append('<div class="table-wrap"><table><thead><tr>')
            output.extend("<th>" + _inline(cell) + "</th>" for cell in table[0])
            output.append("</tr></thead><tbody>")
            for row in table[1:]:
                output.append("<tr>" + "".join("<td>" + _inline(cell) + "</td>" for cell in row) + "</tr>")
            output.append("</tbody></table></div>")
            table = []

    for line in markdown.splitlines():
        line = line.rstrip()
        if not line:
            flush()
        elif line.startswith("|") and line.endswith("|"):
            if paragraph or in_list:
                flush()
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if not all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
                table.append(cells)
        else:
            if table:
                flush()
            heading = re.match(r"^(#{1,4})\s+(.+)$", line)
            if heading:
                flush()
                level = len(heading.group(1))
                output.append(f"<h{level}>" + _inline(heading.group(2)) + f"</h{level}>")
            elif line.startswith("> "):
                flush()
                output.append("<blockquote>" + _inline(line[2:]) + "</blockquote>")
            elif re.match(r"^[-*]\s+", line):
                if paragraph:
                    flush()
                if not in_list:
                    output.append("<ul>")
                    in_list = True
                output.append("<li>" + _inline(line[2:]) + "</li>")
            elif line == "---":
                flush()
                output.append("<hr>")
            else:
                if in_list:
                    flush()
                paragraph.append(line)
    flush()
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<title>{html.escape(title)}</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:#f4f7fb;color:#17202a;font:17px/1.75 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}}
main{{max-width:860px;margin:32px auto;padding:48px 64px;background:#fff;border-radius:18px;box-shadow:0 12px 40px #10282814}}
h1{{font-size:2.2rem;line-height:1.25}}h2{{margin-top:2.2rem;border-bottom:1px solid #e4e7ec}}h3{{margin-top:1.6rem}}
a{{color:#155eef;text-decoration:none;overflow-wrap:anywhere;word-break:break-all}}a:hover{{text-decoration:underline}}
p,li,blockquote{{overflow-wrap:anywhere;word-break:break-word}}blockquote{{margin:1rem 0;padding:.8rem 1rem;color:#667085;background:#f8fafc;border-left:4px solid #84adff}}
code{{background:#eef2f6;padding:.12rem .35rem;border-radius:4px;white-space:pre-wrap}}li{{margin:.45rem 0}}
img{{display:block;max-width:100%;height:auto;margin:1.25rem auto;border-radius:12px}}
.table-wrap{{max-width:100%;overflow-x:auto;margin:1.2rem 0}}table{{width:100%;border-collapse:collapse;font-size:.94rem}}th,td{{padding:.7rem .75rem;border-bottom:1px solid #e4e7ec;text-align:left;white-space:nowrap}}th{{background:#f8fafc}}
footer{{text-align:center;color:#667085;font-size:.85rem;margin:24px}}@media(max-width:700px){{main{{width:100%;min-width:0;margin:0;padding:28px 20px;border-radius:0;overflow:hidden}}h1{{font-size:1.8rem}}}}
</style></head><body><main>{''.join(output)}</main><footer>Daily Intelligence · AI 辅助整理与分析，请核对原始来源</footer></body></html>'''


def _chart_svg(chart: dict) -> str:
    series = chart["series"]
    title_lines = textwrap.wrap(chart["title"], width=36)
    header = 68 + 27 * len(title_lines)
    height = header + 40 + 90 * len(series)
    low = min(0, min(point["value"] for point in series))
    high = max(0, max(point["value"] for point in series))
    span = high - low or 1
    position = lambda value: 285 + 370 * (value - low) / span
    zero = position(0)
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 {height}" role="img">',
             f'<title>{html.escape(chart["title"])}</title>',
             '<rect width="100%" height="100%" fill="#0b1424" rx="18"/>']
    for index, line in enumerate(title_lines):
        parts.append(f'<text x="28" y="{36 + 27 * index}" fill="#ffffff" font-size="22">{html.escape(line)}</text>')
    parts.extend((f'<text x="28" y="{header - 25}" fill="#a9b7c9" font-size="14">单位：{html.escape(chart["unit"])}</text>',
                  f'<line x1="{zero:.2f}" x2="{zero:.2f}" y1="{header}" y2="{height - 45}" stroke="#667085"/>'))
    colors = {"actual": "#67d4ff", "forecast": "#d8b4fe", "estimate": "#fcd34d", "reported": "#86efac"}
    for index, point in enumerate(series):
        y = header + 24 + index * 90
        endpoint = position(point["value"])
        for line_index, line in enumerate(textwrap.wrap(point["label"], width=18)):
            parts.append(f'<text x="28" y="{y - 12 + line_index * 16}" fill="#e5edf8" font-size="14">{html.escape(line)}</text>')
        parts.extend((
            f'<rect x="{min(zero, endpoint):.2f}" y="{y - 16}" width="{abs(endpoint - zero):.2f}" height="26" fill="{colors[point["status"]]}"/>',
            f'<text x="675" y="{y + 4}" fill="#e5edf8" font-size="14">{point["value"]:g} [{point["status"]}]</text>',
        ))
    parts.append('<text x="28" y="' + str(height - 18) + '" fill="#a9b7c9" font-size="12">actual 实际 · reported 来源披露 · estimate 估计 · forecast 预测；来源见正文</text></svg>')
    return "".join(parts)


def _cover_svg(report_date: str) -> str:
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 630" role="img"><title>Daily Intelligence {report_date}</title><rect width="1200" height="630" fill="#08111f"/><path d="M0 480L1200 180V630H0Z" fill="#13243d"/><text x="80" y="190" fill="#67d4ff" font-size="28" letter-spacing="5">DAILY INTELLIGENCE</text><text x="80" y="330" fill="#ffffff" font-size="86">{report_date}</text><text x="80" y="420" fill="#a9b7c9" font-size="32">AI · Business · Macro</text></svg>'''


def _compact_title(value: str) -> str:
    # Keep short editorial clauses together where the card width allows it.
    return ''.join(f'<span>{html.escape(part)}</span>' for part in re.findall(r'[^。！？]+[。！？]?', value))


def _summary_items(entry: dict, records_by_date: dict, daily=False) -> str:
    parts = []
    for item in entry['items']:
        refs = '' if daily else '<span class="point-sources">' + ' '.join(
            f'<a href="{html.escape(records_by_date[d]["relative_html"], quote=True)}" aria-label="阅读这条重点的来源 {n}">原文{n}</a>'
            for n, d in enumerate(item['source_dates'], 1)) + '</span>'
        parts.append(f'<li><h4>{html.escape(item["heading"])}</h4><p>{html.escape(item["body"])}</p>{refs}</li>')
    return '<ul class="editorial-points">' + ''.join(parts) + '</ul>'


def _period_reviews(records: list[dict], anchor: dt.date, monthly: bool, summaries=None) -> str:
    """Render authored synthesis. Production refresh requires validated summaries."""
    if summaries is None:
        return ''
    end = anchor.replace(day=1) if monthly else anchor - dt.timedelta(days=anchor.weekday())
    by_start = {e['start']: e for e in summaries['monthly' if monthly else 'weekly']}
    by_date = {r['date']: r for r in records}
    labels = ['上月', '再前一个月', '更早一个月'] if monthly else ['上周', '再前一周', '更早两周', '更早三周']
    cards = []
    for index, label in enumerate(labels):
        start = (end - dt.timedelta(days=1)).replace(day=1) if monthly else end - dt.timedelta(days=7)
        entry = by_start[start.isoformat()]
        coverage = f'<p class="coverage-note">{html.escape(entry["coverage_note"])}</p>' if entry.get('coverage_note') else ''
        cards.append(f'<article class="editorial-card"><div class="eyebrow">{label}</div><h3>{_compact_title(entry["card_title"])}</h3><p class="card-deck">{html.escape(entry["card_deck"])}</p>{coverage}<details class="insights"><summary><span class="closed-label">展开重点</span><span class="open-label">收起重点</span><span class="toggle" aria-hidden="true">+</span></summary><div class="insight-body"><p class="editorial-lede">{html.escape(entry["overview"])}</p>{_summary_items(entry, by_date)}<div class="watch"><strong>接下来值得留意</strong><p>{html.escape(entry["watch"])}</p></div></div></details></article>')
        end = start
    return ''.join(cards)


def _daily_card(item: dict, summaries=None) -> str:
    entry = (summaries or {}).get('daily', {}).get(item['date'])
    url = html.escape(item['relative_html'], quote=True)
    if entry is None:
        # Staging-only rendering; refresh_homepage rejects missing authored prose.
        return f'<article class="daily-card"><small>{item["date"]}</small><h3>{html.escape(item.get("thesis", ""))}</h3><a class="read-link" href="{url}">阅读全文 →</a></article>'
    return f'<article class="daily-card"><small>{item["date"][5:].replace("-", ".")}</small><h3>{_compact_title(entry["card_title"])}</h3><p class="card-deck">{html.escape(entry["card_deck"])}</p><a class="read-link" href="{url}" aria-label="阅读 {item["date"]} 日报">阅读日报 <span aria-hidden="true">›</span></a></article>'



def _index_html(records: list[dict], summaries=None) -> str:
    records = sorted(records, key=lambda item: item['date'], reverse=True)
    groups = {}
    for record in records:
        groups.setdefault(record["date"][:7], []).append(record)
    sections = []
    for month, issues in groups.items():
        cards = []
        for item in issues:
            date = item["date"]
            url = html.escape(item["relative_html"], quote=True)
            summary = re.sub(r"\s+", " ", item.get("summary", "")).strip()
            if len(summary) > 280:
                summary = summary[:280] + "…"
            cards.append(f'''<article class="issue-card" data-date="{date}"><a class="date-box" href="{url}"><span>{date[8:]}</span><small>{dt.date.fromisoformat(date).strftime('%A')}</small></a><div class="issue-body"><div class="issue-meta">{date} · Daily Intelligence</div><h2><a href="{url}">{html.escape(item.get("thesis") or "Daily Intelligence")}</a></h2><p>{html.escape(summary)}</p><a class="read-link" href="{url}">阅读全文 →</a></div></article>''')
        sections.append(f'<section class="month-group" id="{month}"><h3>{month}</h3>{"".join(cards)}</section>')
    latest = records[0]
    latest_url = html.escape(latest["relative_html"], quote=True)
    latest_entry = (summaries or {}).get('daily', {}).get(latest['date'], {})
    latest_title = html.escape(latest_entry.get('card_title') or latest.get('thesis') or '读懂今天。').replace('。', '。<br>')
    latest_deck = html.escape(latest_entry.get('card_deck') or latest.get('summary', ''))
    anchor = dt.date.fromisoformat(latest['date'])
    daily_start = (anchor - dt.timedelta(days=6)).isoformat()
    weekly_reviews = _period_reviews(records, anchor, False, summaries)
    monthly_reviews = _period_reviews(records, anchor, True, summaries)
    week_cards = "".join(
        _daily_card(item, summaries)
        for item in records if item['date'] >= daily_start)
    month_links = "".join(f'<a href="#{month}">{month} · {len(issues)} 期</a>'
                          for month, issues in groups.items())
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Daily Intelligence</title><style>
:root{{--ink:#1d1d1f;--muted:#626267;--paper:#fff;--ground:#f5f5f7;--accent:#0066cc;--line:#dedee3}}*{{box-sizing:border-box}}html{{scroll-behavior:smooth;scroll-padding-top:84px}}body{{margin:0;background:var(--ground);color:var(--ink);font:17px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC",sans-serif;-webkit-font-smoothing:antialiased}}a{{color:var(--accent);text-decoration:none;overflow-wrap:anywhere}}a:hover{{text-decoration:underline}}a:focus-visible,summary:focus-visible,input:focus-visible{{outline:3px solid #0071e3;outline-offset:5px}}p{{margin:0}}h1,h2,h3,h4{{margin:0;font-weight:650;letter-spacing:-.035em}}nav.site-nav{{position:sticky;top:0;z-index:10;background:#ffffffed;backdrop-filter:blur(18px);border-bottom:1px solid #00000008}}.nav-inner{{max-width:1120px;margin:auto;padding:15px 24px;display:flex;align-items:center;justify-content:space-between;gap:20px}}.brand{{font-size:17px;font-weight:650;color:var(--ink);letter-spacing:-.04em}}.nav-links{{display:flex;gap:26px;font-size:12px}}.nav-links a{{color:#424245}}.hero{{text-align:center;background:radial-gradient(ellipse at 50% 100%,#eaf2ff 0,transparent 65%),#fff;padding:76px 24px 82px}}.eyebrow{{font-size:13px;font-weight:600;color:var(--muted);letter-spacing:.03em}}.hero .eyebrow{{color:var(--accent);font-size:15px}}.hero h1{{font-size:clamp(38px,5.3vw,66px);line-height:1.18;margin:20px auto 24px;max-width:960px}}.hero h1 br:last-child{{display:none}}.hero-deck{{font-size:21px;line-height:1.6;color:#515157;max-width:620px;margin:0 auto 30px}}.primary-cta{{display:inline-flex;align-items:center;gap:16px;min-height:48px;padding:12px 27px;border-radius:999px;background:#0071e3;color:white;font-size:17px}}.primary-cta:hover{{background:#0077ed;text-decoration:none}}.issue-date{{font-size:12px;color:var(--muted);margin-top:16px}}.content{{max-width:1120px;margin:auto;padding:0 24px 60px}}.section-head{{display:flex;align-items:baseline;justify-content:space-between;gap:18px;margin:72px 0 26px}}.section-head h2{{font-size:36px;line-height:1.2}}.section-head p{{font-size:17px;color:var(--muted)}}.daily-grid,.editorial-grid{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:20px;align-items:start}}.editorial-grid{{grid-template-columns:repeat(2,minmax(0,1fr))}}.monthly-grid{{grid-template-columns:repeat(3,minmax(0,1fr))}}.daily-card,.editorial-card{{min-width:0;border-radius:24px;background:var(--paper);padding:32px;overflow-wrap:anywhere}}.daily-card{{display:flex;flex-direction:column;min-height:275px;align-self:stretch}}.daily-card small{{font-size:12px;color:var(--muted)}}.daily-card h3,.editorial-card h3{{font-size:25px;line-height:1.35;margin:12px 0}}.editorial-card{{padding:38px}}.editorial-card h3{{font-size:30px;max-width:16em}}.monthly-grid .editorial-card{{padding:30px}}.monthly-grid h3{{font-size:26px}}.daily-card h3 span,.editorial-card h3 span{{display:inline-block;max-width:100%}}.card-deck{{color:var(--muted);font-size:15px;line-height:1.75}}.read-link{{font-size:14px;color:var(--accent)}}.daily-card .read-link{{margin-top:auto;padding-top:24px}}.read-link span{{font-size:21px;margin-left:5px;line-height:0}}.insights{{margin-top:24px}}.insights summary{{display:flex;align-items:center;gap:12px;list-style:none;color:var(--accent);font-size:14px;cursor:pointer;width:fit-content;min-height:32px}}.insights summary::-webkit-details-marker{{display:none}}.toggle{{display:grid;place-items:center;width:24px;height:24px;border-radius:50%;background:#f0f5fc;color:var(--accent);font-size:20px;line-height:1}}.open-label{{display:none}}.insights[open] .closed-label{{display:none}}.insights[open] .open-label{{display:inline}}.insights[open] .toggle{{transform:rotate(45deg)}}.insight-body{{padding-top:22px}}.editorial-lede{{color:var(--muted);font-size:15px;line-height:1.8}}.editorial-points{{list-style:none;padding:0;margin:22px 0}}.editorial-points li{{border-top:1px solid var(--line);padding:18px 0}}.editorial-points h4{{font-size:16px;letter-spacing:0;line-height:1.6;margin-bottom:8px}}.editorial-points p,.watch p{{font-size:14px;color:var(--muted);line-height:1.85}}.point-sources{{display:flex;gap:12px;flex-wrap:wrap;margin-top:8px;font-size:12px}}.watch{{border-top:1px solid var(--line);padding-top:20px}}.watch strong{{font-size:13px}}.watch p{{margin-top:8px}}.coverage-note{{font-size:12px;color:var(--muted);margin-top:12px}}.archive{{border-top:1px solid var(--line);margin-top:72px;padding-top:24px}}.archive>summary{{font-size:17px;cursor:pointer;width:fit-content;color:var(--accent)}}.month-nav{{display:flex;gap:16px;flex-wrap:wrap;margin:30px 0 20px;font-size:14px}}.search-wrap{{margin-bottom:30px}}input{{width:100%;padding:16px 18px;border:1px solid #b9b9c0;border-radius:12px;background:#fff;font:inherit}}.month-group{{margin:28px 0}}.month-group>h3{{font-size:24px}}.issue-card{{display:grid;grid-template-columns:64px 1fr;gap:24px;padding:24px 0;border-bottom:1px solid var(--line)}}.date-box{{color:var(--muted);display:flex;flex-direction:column;align-items:center}}.date-box span{{font-size:28px}}.date-box small{{font-size:10px}}.issue-body{{min-width:0}}.issue-meta{{font-size:12px;color:var(--muted)}}.issue-body h2{{font-size:20px;letter-spacing:0;line-height:1.5;margin:8px 0}}.issue-body h2 a{{color:var(--ink)}}.issue-body p{{font-size:14px;color:var(--muted);margin:8px 0 12px}}.footer{{border-top:1px solid var(--line);margin-top:44px;padding-top:20px;font-size:12px;color:var(--muted)}}[hidden]{{display:none!important}}@media(max-width:900px){{.daily-grid,.monthly-grid{{grid-template-columns:repeat(2,minmax(0,1fr))}}.editorial-card{{padding:28px}}}}@media(max-width:600px){{.nav-inner{{padding:13px 20px;flex-wrap:wrap;gap:10px}}.brand{{font-size:16px}}.nav-links{{gap:20px}}.hero{{padding:52px 24px 54px}}.hero h1{{font-size:38px;margin:18px auto 20px}}.hero-deck{{font-size:18px;max-width:340px;margin-bottom:26px}}.content{{padding:0 20px 36px}}.section-head{{display:block;margin:48px 0 20px}}.section-head h2{{font-size:30px}}.section-head p{{font-size:15px;margin-top:8px}}.daily-grid,.editorial-grid,.monthly-grid{{grid-template-columns:1fr;gap:14px}}.daily-card,.editorial-card,.monthly-grid .editorial-card{{padding:28px;border-radius:22px}}.daily-card{{min-height:0}}.daily-card h3,.editorial-card h3,.monthly-grid h3{{font-size:25px}}.card-deck{{font-size:15px}}.daily-card .read-link{{padding-top:18px}}.archive{{margin-top:48px}}.issue-card{{grid-template-columns:1fr;gap:8px}}.date-box{{display:none}}}}@media(prefers-reduced-motion:reduce){{html{{scroll-behavior:auto}}}}
</style></head><body><nav class="site-nav" aria-label="主要导航"><div class="nav-inner"><a class="brand" href="#top">Daily Intelligence</a><div class="nav-links"><a href="#daily">最近 7 天</a><a href="#weekly">每周</a><a href="#monthly">每月</a></div></div></nav><main id="top"><header class="hero"><div class="eyebrow">读懂今天，先从这里。</div><h1>{latest_title}</h1><p class="hero-deck">{latest_deck}</p><a class="primary-cta" href="{latest_url}">阅读本期 <span aria-hidden="true">↗</span></a><p class="issue-date">{latest['date']} · Daily Intelligence</p></header><div class="content"><section id="daily"><div class="section-head"><h2>最近 7 天。</h2><p>每天，留下值得读的。</p></div><div class="daily-grid">{week_cards}</div></section><section id="weekly"><div class="section-head"><h2>每周，连起来看。</h2><p>最近四周的重要变化。</p></div><div class="editorial-grid">{weekly_reviews}</div></section><section id="monthly"><div class="section-head"><h2>每月，看得更远。</h2><p>最近三个月的关键脉络。</p></div><div class="editorial-grid monthly-grid">{monthly_reviews}</div></section><details id="archive" class="archive"><summary>探索全部归档</summary><nav class="month-nav" aria-label="归档月份">{month_links}</nav><div class="search-wrap"><input id="q" type="search" placeholder="搜索日期、公司或主题" aria-label="搜索归档"></div><section id="results">{''.join(sections)}</section></details><footer class="footer">Daily Intelligence · AI、科技、商业与宏观。</footer></div></main><script>
// Fixed local code only. JSON is data; no generated HTML, eval, or dynamic links.
const cards=[...document.querySelectorAll('.issue-card')];
let records=null;
document.getElementById('q').addEventListener('input',async event=>{{
 const query=event.target.value.trim().toLowerCase();
 if(!records){{try{{const response=await fetch('search-index.json');if(response.ok)records=await response.json();}}catch(error){{records=[];}}}}
 const searchable=new Map((records||[]).map(item=>[item.date,JSON.stringify(item).toLowerCase()]));
 cards.forEach(card=>{{card.hidden=!!query&&!(searchable.get(card.dataset.date)||card.textContent.toLowerCase()).includes(query);}});
 document.querySelectorAll('.month-group').forEach(group=>{{group.hidden=![...group.querySelectorAll('.issue-card')].some(card=>!card.hidden);}});
}});
</script></body></html>'''


def build_bundle(payload: dict, report_date: str, archive_root: Path,
                 output_dir: Path) -> list[str]:
    """Write eight NEW files in separate staging; never mutate archive_root.

    The returned POSIX relative paths are the complete publication allowlist.
    Existing historical issue files are referenced, not copied into the bundle.
    """
    parsed = validate_payload(payload, report_date, archive_root)
    archive = _safe_root(archive_root)
    output = _safe_root(output_dir, must_exist=False)
    _require(not output.is_relative_to(archive) and not archive.is_relative_to(output),
             "path: staging and archive must be disjoint")
    records = sorted(parsed["records"] + [parsed["data"]],
                     key=lambda record: record["date"], reverse=True)
    relative = _relative(report_date)
    latest_url = html.escape(records[0]["relative_html"], quote=True)
    files = {
        f"{relative}/Daily Intelligence.md": payload["markdown"].rstrip() + "\n",
        f"{relative}/Daily Intelligence.html": _report_html(payload["markdown"], f"Daily Intelligence {report_date}"),
        f"{relative}/data.json": json.dumps(parsed["data"], ensure_ascii=False, indent=2) + "\n",
        f"{relative}/assets/chart.svg": _chart_svg(parsed["chart"]),
        f"{relative}/assets/cover.svg": _cover_svg(report_date),
        "search-index.json": json.dumps(records, ensure_ascii=False, indent=2) + "\n",
        "index.html": _index_html(records),
        "latest.html": f'<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="0; url={latest_url}"><title>Latest Daily Intelligence</title></head><body><a href="{latest_url}">打开最新一期</a></body></html>',
    }
    for relative_path in files:
        destination = output / relative_path
        _no_symlinks(output, destination)
        _require(not destination.exists(), "bundle: existing output file forbidden")
    output.mkdir(parents=True, exist_ok=True)
    for relative_path, content in files.items():
        destination = output / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        _no_symlinks(output, destination)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(destination, flags, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
    return list(files)
