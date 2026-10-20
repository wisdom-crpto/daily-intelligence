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


_READER_CSS = r"""
:root{color-scheme:light;--ink:#1d1d1f;--muted:#626268;--accent:#0066cc;--line:#e5e5e7;--paper:#fff}
*{box-sizing:border-box}html{scroll-padding-top:90px}body{margin:0;background:#fff;color:var(--ink);font:18px/1.9 -apple-system,BlinkMacSystemFont,"SF Pro Text","PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif;-webkit-font-smoothing:antialiased}
.reader-nav{position:sticky;top:0;z-index:10;background:#ffffffed;backdrop-filter:blur(20px);border-bottom:1px solid var(--line)}.reader-nav>div{max-width:1120px;margin:auto;min-height:64px;padding:10px 28px;display:flex;align-items:center;justify-content:space-between;gap:16px}.reader-brand{font-size:17px;font-weight:650;color:var(--ink);letter-spacing:-.025em;text-decoration:none}.reader-back{font-size:14px;color:var(--accent);min-height:44px;display:inline-flex;align-items:center;text-decoration:none}
main{width:calc(100% - 56px);max-width:880px;min-width:0;margin:0 auto;padding:64px 56px 80px;background:var(--paper);border-radius:0;box-shadow:none;overflow:visible}main h1,main h2,main h3,main h4{color:var(--ink);font-weight:650;letter-spacing:-.02em;line-height:1.4;word-break:normal;overflow-wrap:break-word;line-break:strict;text-wrap:pretty}main h1{font-size:clamp(32px,4vw,48px);line-height:1.16;margin:0 0 28px;letter-spacing:-.035em}main h2{font-size:28px;margin:64px 0 24px;padding:28px 0 0;border:0;border-top:1px solid var(--line)}main h3{font-size:22px;margin:36px 0 16px}main h4{font-size:19px;margin:28px 0 12px}main p{margin:20px 0}main strong{font-weight:650}main a{color:var(--accent);overflow-wrap:anywhere;word-break:normal;text-decoration:underline;text-decoration-color:#0066cc55;text-underline-offset:4px}main a:hover{text-decoration-color:currentColor}main p,main li,main blockquote{word-break:normal;overflow-wrap:break-word}main ul,main ol{padding-left:1.4em}main li{padding-left:.25em;margin:16px 0}main .action-items li{padding-block:8px}main blockquote{border:0;border-left:3px solid #d2d2d7;background:#f5f5f7;border-radius:0 12px 12px 0;color:var(--muted);padding:20px 24px;margin:28px 0;font-size:17px}main h1+blockquote{font-size:14px;line-height:1.8;margin:0 0 40px}main hr{border:0;border-top:1px solid var(--line);margin:40px 0}main code{font-size:.86em;background:#f5f5f7;padding:.15em .3em;border-radius:4px;white-space:pre-wrap;overflow-wrap:anywhere}main img{display:block;max-width:100%;height:auto;margin:28px auto;border-radius:16px}main .table-wrap{max-width:100%;overflow-x:auto;overscroll-behavior-x:contain;-webkit-overflow-scrolling:touch;margin:28px 0;border:1px solid var(--line);border-radius:12px;scrollbar-width:thin}main table{font-size:15px;line-height:1.65;border-collapse:collapse;width:100%}main th,main td{padding:14px 18px;border-bottom:1px solid var(--line);text-align:left;white-space:normal;min-width:120px}main th{background:#f5f5f7;color:var(--ink);font-weight:600}footer{max-width:880px;margin:0 auto;padding:28px;text-align:center;color:var(--muted);font-size:12px;border-top:1px solid var(--line)}a:focus-visible{outline:3px solid #0071e3;outline-offset:5px;border-radius:3px}
@media(max-width:700px){.reader-nav>div{padding:8px 20px;min-height:60px}.reader-brand{font-size:16px}.reader-back{font-size:13px}main{width:100%;padding:40px 24px 56px;margin:0;border-radius:0;overflow:visible}main h1{font-size:32px}main h2{font-size:25px;margin-top:48px}main h3{font-size:21px}main p,main li{font-size:17px;line-height:1.95}main blockquote{font-size:16px;padding:16px 18px}main h1+blockquote{font-size:13px}main th,main td{padding:12px;min-width:108px}footer{padding:24px}}
@media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}}@media print{.reader-nav,footer{display:none}main{width:100%;max-width:none;padding:0}body{font-size:11pt}main h2{break-after:avoid}main .table-wrap{overflow:visible}main a{color:inherit}}

.reader-hero{width:calc(100% - 56px);max-width:880px;margin:auto;padding:64px 56px 20px}.reader-hero>p{font-size:12px;letter-spacing:.12em;font-weight:600;color:var(--muted);margin:0 0 18px}.reader-hero h1{font-size:clamp(32px,4vw,46px);letter-spacing:-.025em;line-height:1.4;margin:0;text-wrap:balance;word-break:normal;line-break:strict}.reader-hero~main{padding-top:8px}.reader-hero~main h1{display:none}main>a[href="../../../../index.html"]{display:none}@media(max-width:700px){.reader-hero{width:100%;padding:40px 24px 20px}.reader-hero h1{font-size:30px;line-height:1.45}.reader-hero~main{padding-top:0}}
"""


def _style_reader_page(page: str) -> str:
    """Apply shared reader chrome without touching the archived article body."""
    page = re.sub(r'<!-- DI-READER-STYLE:BEGIN -->[\s\S]*?<!-- DI-READER-STYLE:END -->', '', page)
    page = re.sub(r'<!-- DI-READER-NAV:BEGIN -->[\s\S]*?<!-- DI-READER-NAV:END -->', '', page)
    page = re.sub(r'<!-- DI-READER-HERO:BEGIN -->[\s\S]*?<!-- DI-READER-HERO:END -->', '', page)
    style = '<!-- DI-READER-STYLE:BEGIN --><style>' + _READER_CSS + '</style><!-- DI-READER-STYLE:END -->'
    nav = '<!-- DI-READER-NAV:BEGIN --><nav class="reader-nav" aria-label="阅读导航"><div><a class="reader-brand" href="../../../index.html">Daily Intelligence</a><a class="reader-back" href="../../../index.html"><span aria-hidden="true">←</span> 返回首页</a></div></nav><!-- DI-READER-NAV:END -->'
    heading = re.search(r'<main\b[^>]*>[\s\S]*?<h1\b[^>]*>([\s\S]*?)</h1>', page)
    hero = ''
    if heading:
        title = html.unescape(re.sub(r'<[^>]+>', '', heading.group(1)))
        display = re.sub(r'^Daily\s+Intelligence\s*[|｜·:：—-]?\s*', '', title, flags=re.I).strip() or title
        hero = '<!-- DI-READER-HERO:BEGIN --><header class="reader-hero"><p>DAILY INTELLIGENCE</p><h1>' + html.escape(display) + '</h1></header><!-- DI-READER-HERO:END -->'
    if '</head>' not in page or not re.search(r'<body(?:\s[^>]*)?>', page):
        raise ValueError('Reader page is missing its document shell')
    page = page.replace('</head>', style + '</head>', 1)
    return re.sub(r'(<body(?:\s[^>]*)?>)', lambda m: m.group(1) + nav + hero, page, count=1)


def _report_html(markdown: str, title: str) -> str:
    output, paragraph, table = [], [], []
    in_list = None
    in_actions = False

    def flush() -> None:
        nonlocal paragraph, table, in_list
        if paragraph:
            output.append("<p>" + _inline(" ".join(paragraph)) + "</p>")
            paragraph = []
        if in_list:
            output.append(f"</{in_list}>")
            in_list = None
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
                if level <= 2:
                    in_actions = heading.group(2).lower().startswith('action items')
                output.append(f"<h{level}>" + _inline(heading.group(2)) + f"</h{level}>")
            elif line.startswith("> "):
                flush()
                output.append("<blockquote>" + _inline(line[2:]) + "</blockquote>")
            elif re.match(r"^(?:[-*]\s+|[0-9]+[.)]\s+)", line):
                item = re.match(r"^(?:([-*])|([0-9]+)[.)])\s+(.+)$", line)
                kind = 'ul' if item.group(1) else 'ol'
                if paragraph or (in_list and in_list != kind):
                    flush()
                if not in_list:
                    attrs = ' class="action-items"' if in_actions else ''
                    if kind == 'ol' and item.group(2) != '1':
                        attrs += f' start="{int(item.group(2))}"'
                    output.append(f'<{kind}{attrs}>')
                    in_list = kind
                output.append('<li>' + _inline(item.group(3)) + '</li>')
            elif in_list and line.startswith(('  ', '\t')):
                output[-1] = output[-1][:-5] + ' ' + _inline(line.strip()) + '</li>'
            elif line == "---":
                flush()
                output.append("<hr>")
            else:
                if in_list:
                    flush()
                paragraph.append(line)
    flush()
    return _style_reader_page(f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
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
</style></head><body><main>{''.join(output)}</main><footer>Daily Intelligence · AI 辅助整理与分析，请核对原始来源</footer></body></html>''')


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
    # Editorial words are preserved; only sentence punctuation is normalized.
    return html.escape(value.rstrip('。.').replace('。', '，'))


def _carousel_controls(section: str, total: int) -> str:
    label = {'daily': '日报', 'weekly': '周报', 'monthly': '月报'}[section]
    return f'<div class="carousel-controls" data-carousel="{section}"><span class="swipe-hint">左右滑动，发现更多</span><span class="carousel-position" aria-live="polite" aria-atomic="true">1 / {total}</span><button type="button" data-step="-1" aria-label="上一张{label}" aria-controls="{section}-cards" disabled>‹</button><button type="button" data-step="1" aria-label="下一张{label}" aria-controls="{section}-cards">›</button></div>'


def _summary_items(entry: dict, records_by_date: dict, daily=False) -> str:
    parts = []
    for item in entry['items']:
        refs = '' if daily else '<span class="point-sources">' + ' '.join(
            f'<a href="{html.escape(records_by_date[d]["relative_html"], quote=True)}" aria-label="阅读 {d} 日报，{html.escape(item["heading"], quote=True)}的来源">{d[5:].replace("-", ".")} 原文 ↗</a>'
            for d in item['source_dates']) + '</span>'
        parts.append(f'<li><h4>{html.escape(item["heading"])}</h4><p>{html.escape(item["body"])}</p>{refs}</li>')
    return '<ul class="editorial-points">' + ''.join(parts) + '</ul>'


def _period_reviews(records: list[dict], anchor: dt.date, monthly: bool, summaries=None) -> str:
    """Authored synthesis, with native details as a no-script fallback."""
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
        actual = len(entry['source_hashes'])
        expected = (end-start).days
        coverage = f'<p class="coverage-note"><strong>阅读说明</strong><br>{html.escape(entry["coverage_note"])}</p>' if entry.get('coverage_note') else ''
        brief = f'<p class="coverage-brief">已归档 {actual}/{expected} 期' + (' · 覆盖不全' if actual < expected else '') + (' · 附阅读说明' if coverage else '') + '</p>' if coverage or actual < expected else ''
        cards.append(f'<article class="editorial-card"><div class="eyebrow">{label}</div><h3>{_compact_title(entry["card_title"])}</h3><p class="card-deck">{html.escape(entry["card_deck"])}</p>{brief}<details class="insights"><summary><span class="closed-label">展开阅读</span><span class="open-label">收起重点</span><span class="toggle" aria-hidden="true">+</span></summary><div class="insight-body"><p class="editorial-lede">{html.escape(entry["overview"])}</p>{coverage}{_summary_items(entry, by_date)}<div class="watch"><strong>接下来值得留意</strong><p>{html.escape(entry["watch"])}</p></div></div></details></article>')
        end = start
    return ''.join(cards)


def _daily_card(item: dict, summaries=None) -> str:
    entry = (summaries or {}).get('daily', {}).get(item['date'])
    url = html.escape(item['relative_html'], quote=True)
    if entry is None:
        # Staging-only rendering; refresh_homepage rejects missing authored prose.
        return f'<article class="daily-card"><small>{item["date"]}</small><h3>{html.escape(item.get("thesis", ""))}</h3><a class="read-link" href="{url}">阅读全文 →</a></article>'
    return f'<article class="daily-card"><small>{item["date"][5:].replace("-", ".")}</small><h3>{_compact_title(entry["card_title"])}</h3><p class="card-deck">{html.escape(entry["card_deck"])}</p><a class="read-link" href="{url}" aria-label="阅读 {item["date"]} 日报">阅读日报 <span aria-hidden="true">›</span></a></article>'



_HOME_CSS = r"""
:root{color-scheme:light;--ink:#1d1d1f;--muted:#626268;--accent:#0066cc;--ground:#f5f5f7;--paper:#fff;--line:#dedee3;--font:-apple-system,BlinkMacSystemFont,"SF Pro Text","PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif}
*{box-sizing:border-box}html{scroll-behavior:smooth;scroll-padding-top:88px}body{margin:0;background:var(--ground);color:var(--ink);font:17px/1.65 var(--font);-webkit-font-smoothing:antialiased}a{color:var(--accent);text-decoration:none;overflow-wrap:anywhere}a:hover{text-decoration:underline;text-underline-offset:4px}button,input{font:inherit}button,summary,a{-webkit-tap-highlight-color:transparent}button{cursor:pointer}button:disabled{cursor:default}a:focus-visible,button:focus-visible,summary:focus-visible,input:focus-visible,[tabindex="0"]:focus-visible{outline:3px solid #0071e3;outline-offset:4px}h1,h2,h3,h4,p{margin:0}h1,h2,h3,h4{font-weight:650;line-height:1.35;letter-spacing:-.025em;word-break:normal;overflow-wrap:break-word;line-break:strict;text-wrap:pretty}h1,h2,h3{text-wrap:balance}button svg{pointer-events:none}[hidden]{display:none!important}.skip-link{position:fixed;top:8px;left:16px;z-index:100;padding:10px 16px;background:#fff;border-radius:8px;transform:translateY(-150%)}.skip-link:focus{transform:none}
.site-nav{position:sticky;top:0;z-index:10;background:#ffffffeb;backdrop-filter:blur(20px);border-bottom:1px solid #00000008}.nav-inner{max-width:1200px;padding:8px 32px;min-height:64px;margin:auto;display:flex;align-items:center;justify-content:space-between;gap:20px}.brand{font-size:17px;font-weight:650;letter-spacing:-.035em;color:var(--ink);white-space:nowrap}.brand:hover{text-decoration:none}.nav-links{display:flex;gap:28px;font-size:13px}.nav-links a{display:flex;align-items:center;min-height:44px;color:var(--ink)}
.hero{background:var(--paper);padding:80px 28px 88px;text-align:center}.eyebrow{font-size:13px;line-height:1.5;font-weight:600;letter-spacing:.02em;color:var(--muted)}.hero .eyebrow{font-size:14px;color:var(--accent)}.hero h1{max-width:15em;margin:22px auto 24px;font-size:clamp(36px,4.8vw,64px);letter-spacing:-.04em;line-height:1.18}.title-word{display:inline-block;max-width:100%}.hero-deck{font-size:21px;line-height:1.65;color:var(--muted);max-width:30em;margin:0 auto 30px}.primary-cta{display:inline-flex;align-items:center;gap:18px;min-height:48px;padding:11px 26px;border-radius:999px;background:#0071e3;color:#fff;font-size:17px}.primary-cta:hover{background:#0077ed;text-decoration:none}.issue-date{font-size:12px;color:var(--muted);margin-top:18px}.content{max-width:1200px;margin:auto;padding:0 32px 40px}.section-head{display:flex;align-items:end;justify-content:space-between;gap:24px;padding:72px 0 26px}.section-head h2{font-size:34px;line-height:1.2}.section-head p{font-size:16px;color:var(--muted);margin-top:10px}.section-kicker{font-size:12px;letter-spacing:.1em;color:var(--muted);margin-bottom:10px}
.daily-grid,.editorial-grid{display:flex;align-items:stretch;gap:20px;overflow-x:auto;scroll-snap-type:x mandatory;scroll-padding-inline:4px;overscroll-behavior-x:contain;scrollbar-width:thin;scrollbar-color:#c8c8ce transparent;padding:4px 4px 18px;margin-inline:-4px;-webkit-overflow-scrolling:touch}.daily-card,.editorial-card{flex:0 0 calc((100% - 54px)/3);min-width:0;min-height:320px;display:flex;flex-direction:column;align-self:stretch;scroll-snap-align:start;background:#fff;border:1px solid #00000005;border-radius:24px;padding:30px;overflow-wrap:break-word;box-shadow:0 2px 6px #00000003}.daily-card small,.editorial-card>.eyebrow{font-size:13px;line-height:1.5;color:var(--muted);font-weight:600}.daily-card h3,.editorial-card h3{font-size:26px;line-height:1.4;margin:16px 0 12px;letter-spacing:-.025em}.card-deck{font-size:16px;line-height:1.75;color:var(--muted)}.read-link{font-size:15px;min-height:44px;display:inline-flex;align-items:center;gap:10px}.daily-card .read-link{margin-top:auto;padding-top:22px}.coverage-brief{font-size:12px;color:var(--muted);margin-top:16px;line-height:1.65}.insights{margin-top:auto;padding-top:24px}.insights summary{display:flex;align-items:center;justify-content:space-between;gap:16px;list-style:none;cursor:pointer;color:var(--accent);font-size:15px;min-height:44px}.insights summary::-webkit-details-marker{display:none}.toggle{display:grid;place-items:center;flex-shrink:0;width:30px;height:30px;border-radius:50%;background:#f0f0f3;color:#424245;font-size:22px;font-weight:400}.open-label{display:none}.insights[open] .closed-label{display:none}.insights[open] .open-label{display:inline}.insights[open] .toggle{transform:rotate(45deg)}.insight-body{padding-top:24px}.editorial-lede{font-size:19px;line-height:1.85;color:var(--ink)}.coverage-note{font-size:14px;line-height:1.8;color:var(--muted);padding:18px 20px;background:var(--ground);border-radius:12px;margin-top:24px}.editorial-points{list-style:none;padding:0;margin:30px 0}.editorial-points li{padding:28px 0;border-top:1px solid var(--line)}.editorial-points h4{font-size:22px;line-height:1.5;margin-bottom:12px}.editorial-points p,.watch p{font-size:17px;line-height:1.9;color:#424245}.point-sources{display:flex;flex-wrap:wrap;gap:8px;margin-top:18px}.point-sources a{font-size:12px;min-height:36px;padding:6px 12px;border-radius:999px;background:#f5f5f7;display:inline-flex;align-items:center}.watch{border-top:1px solid var(--line);padding-top:26px}.watch strong{font-size:18px;font-weight:600}.watch p{margin-top:12px}.carousel-controls{display:none;align-items:center;justify-content:flex-end;gap:10px;margin-top:4px;min-height:48px}.carousel-controls.ready{display:flex}.swipe-hint{font-size:12px;color:var(--muted);margin-right:auto}.carousel-position{font-size:13px;color:var(--muted);font-variant-numeric:tabular-nums;margin-right:8px}.carousel-controls button,.review-toolbar button{border:0;border-radius:50%;width:44px;height:44px;flex-shrink:0;display:grid;place-items:center;background:#e8e8ed;color:#333336;font-size:26px;line-height:1}.carousel-controls button:disabled,.review-toolbar button:disabled{opacity:.35}.carousel-controls button:not(:disabled):hover,.review-toolbar button:not(:disabled):hover{background:#dcdce1}
.review-dialog{width:min(1000px,calc(100% - 48px));max-width:none;height:calc(100dvh - 48px);max-height:none;margin:auto;padding:0;border:0;border-radius:26px;color:var(--ink);background:#fff;box-shadow:0 24px 100px #0003;overflow:hidden}.review-dialog::backdrop{background:#0006;backdrop-filter:blur(5px)}body.review-open{overflow:hidden}.review-toolbar{height:76px;display:flex;align-items:center;gap:10px;padding:12px 24px;border-bottom:1px solid var(--line);background:#fff}.review-toolbar h2{font-size:17px;margin-right:auto;letter-spacing:0}.review-position{font-size:13px;color:var(--muted);font-variant-numeric:tabular-nums;margin-right:6px}.review-toolbar .review-close{margin-left:12px}.review-track{height:calc(100% - 76px);display:flex;overflow-x:auto;overflow-y:hidden;scroll-snap-type:x mandatory;overscroll-behavior-x:contain;scrollbar-width:none;-webkit-overflow-scrolling:touch}.review-track::-webkit-scrollbar{display:none}.review-page{flex:0 0 100%;min-width:0;height:100%;overflow-y:auto;overscroll-behavior-y:contain;scroll-snap-align:start;scroll-snap-stop:always;padding:44px 60px 60px;scrollbar-width:thin}.review-prose{max-width:720px;margin:auto}.review-page h3{font-size:36px;line-height:1.3;margin:14px 0 18px}.review-page .card-deck{font-size:19px;line-height:1.7}.review-page .insight-body{padding-top:32px}.review-page .review-end{margin-top:36px;border-top:1px solid var(--line);padding-top:24px;color:var(--muted);font-size:13px}.review-page:focus-visible{outline-offset:-5px}
.archive{border-top:1px solid var(--line);margin-top:72px;padding-top:32px}.archive>summary{font-size:28px;font-weight:650;letter-spacing:-.025em;cursor:pointer;list-style:none;display:flex;justify-content:space-between;gap:24px;align-items:center;min-height:52px}.archive>summary::-webkit-details-marker{display:none}.archive>summary::after{content:'+';font-weight:400;color:var(--muted)}.archive[open]>summary::after{content:'−'}.archive-intro{color:var(--muted);font-size:16px;margin-top:16px}.month-nav{display:flex;gap:10px;flex-wrap:wrap;margin:24px 0;font-size:13px}.month-nav a{border:1px solid var(--line);padding:8px 14px;min-height:40px;border-radius:999px;color:var(--ink)}.search-wrap{margin:28px 0 12px}.search-wrap label{display:block;font-size:14px;color:var(--muted);margin-bottom:8px}input[type=search]{width:100%;padding:16px 18px;border:1px solid #b9b9c0;border-radius:14px;background:#fff;font-size:17px;color:var(--ink)}.search-status{min-height:28px;color:var(--muted);font-size:13px;margin-bottom:20px}.month-group{margin:36px 0}.month-group>h3{font-size:24px;margin-bottom:8px}.issue-card{display:grid;grid-template-columns:60px 1fr;gap:28px;padding:24px 0;border-bottom:1px solid var(--line)}.date-box{color:var(--muted);display:flex;flex-direction:column;align-items:center}.date-box span{font-size:28px;font-weight:600}.date-box small{font-size:11px}.issue-body{min-width:0}.issue-meta{font-size:12px;color:var(--muted)}.issue-body h2{font-size:21px;line-height:1.5;margin:8px 0}.issue-body h2 a{color:var(--ink);display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}.issue-body p{font-size:15px;line-height:1.8;color:var(--muted);margin:8px 0 12px}.footer{display:flex;justify-content:space-between;gap:24px;border-top:1px solid var(--line);margin-top:56px;padding:24px 0;font-size:12px;color:var(--muted)}
@media(max-width:1000px){.daily-card,.editorial-card{flex-basis:calc((100% - 34px)/2)}}
@media(max-width:600px){html{scroll-padding-top:108px}.nav-inner{padding:8px 20px;flex-wrap:wrap;gap:0;min-height:88px}.brand{font-size:16px}.nav-links{gap:24px;width:100%;font-size:12px}.nav-links a{min-height:34px}.hero{padding:48px 24px 56px}.hero h1{font-size:36px;line-height:1.3;margin:18px auto 20px}.hero-deck{font-size:18px;margin-bottom:26px}.content{padding:0 20px 24px}.section-head{padding:48px 0 22px;display:block}.section-head h2{font-size:28px}.section-head p{font-size:15px}.daily-grid,.editorial-grid{gap:14px;margin-inline:-20px;padding:4px 20px 16px;scroll-padding-inline:20px}.daily-card,.editorial-card{flex-basis:calc(100% - 24px);min-height:310px;padding:26px;border-radius:22px}.daily-card h3,.editorial-card h3{font-size:25px}.card-deck{font-size:16px}.swipe-hint{max-width:12em}.review-dialog{width:100%;height:100dvh;border-radius:0}.review-toolbar{height:68px;padding:10px 16px;gap:6px}.review-toolbar h2{font-size:15px}.review-position{font-size:12px;margin-right:4px}.review-toolbar .review-close{margin-left:4px}.review-track{height:calc(100% - 68px)}.review-page{padding:32px 24px 44px}.review-page h3{font-size:29px}.review-page .card-deck{font-size:17px}.editorial-lede{font-size:18px}.editorial-points h4{font-size:21px}.editorial-points p,.watch p{font-size:17px}.coverage-note{font-size:13px;padding:16px}.archive{margin-top:48px}.archive>summary{font-size:25px}.issue-card{grid-template-columns:1fr;gap:0}.date-box{display:none}.footer{display:block}.footer a{display:inline-block;margin-top:14px}}
@media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}*,*::before,*::after{animation:none!important;transition:none!important}}
"""

_HOME_JS = r"""
const reducedMotion=matchMedia('(prefers-reduced-motion:reduce)');
const motion=()=>reducedMotion.matches?'auto':'smooth';
// Keep Chinese word groups and English words intact at line boundaries.
// The unsegmented label remains the heading's accessible name.
if(typeof Intl.Segmenter==='function'){
 const words=new Intl.Segmenter('zh',{granularity:'word'});
 document.querySelectorAll('.hero h1,.daily-card h3,.editorial-card h3').forEach(heading=>{
  const text=heading.textContent,visual=document.createElement('span');
  visual.setAttribute('aria-hidden','true');heading.setAttribute('aria-label',text);
  for(const part of words.segment(text)){
   const word=document.createElement('span');word.className='title-word';word.textContent=part.segment;visual.append(word);
  }
  heading.replaceChildren(visual);
 });
}

// No geometry writes during scrolling. Native overflow is the no-JavaScript fallback.
function nearest(track,slides){
 const start=track.getBoundingClientRect().left+parseFloat(getComputedStyle(track).paddingLeft||0);
 return slides.reduce((best,slide,i)=>Math.abs(slide.getBoundingClientRect().left-start)<Math.abs(slides[best].getBoundingClientRect().left-start)?i:best,0);
}
function scrollToSlide(track,slides,index,behavior=motion()){
 index=Math.max(0,Math.min(slides.length-1,index));
 track.scrollTo({left:slides[index].offsetLeft-slides[0].offsetLeft,behavior});
}
document.querySelectorAll('.carousel-controls').forEach(controls=>{
 const track=document.getElementById(controls.dataset.carousel+'-cards'),slides=[...track.children];
 if(!slides.length)return;
 const previous=controls.querySelector('[data-step="-1"]'),next=controls.querySelector('[data-step="1"]');
 let current=0,timer;
 function update(){
  current=nearest(track,slides);
  const box=track.getBoundingClientRect();
  const visible=slides.map((slide,i)=>({box:slide.getBoundingClientRect(),i})).filter(x=>Math.min(x.box.right,box.right)-Math.max(x.box.left,box.left)>x.box.width*.7);
  const last=visible.length?visible[visible.length-1].i:current;
  previous.disabled=track.scrollLeft<2;next.disabled=track.scrollLeft>=track.scrollWidth-track.clientWidth-2;
  controls.querySelector('.carousel-position').textContent=(current+1)+(last>current?'–'+(last+1):'')+' / '+slides.length;
 }
 function schedule(){clearTimeout(timer);timer=setTimeout(update,120);}
 function go(i){current=Math.max(0,Math.min(slides.length-1,i));scrollToSlide(track,slides,current);schedule();}
 previous.addEventListener('click',()=>go(current-1));next.addEventListener('click',()=>go(current+1));
 track.addEventListener('scroll',schedule,{passive:true});
 track.addEventListener('keydown',event=>{
  if(event.target!==track)return;
  const keys={ArrowLeft:current-1,ArrowRight:current+1,Home:0,End:slides.length-1};
  if(event.key in keys){event.preventDefault();go(keys[event.key]);}
 });
 // Focus within an already visible card must not move the carousel.
 track.addEventListener('focusin',event=>{
  const i=slides.findIndex(slide=>slide.contains(event.target));if(i<0)return;
  const a=slides[i].getBoundingClientRect(),b=track.getBoundingClientRect();
  if(a.right<=b.left||a.left>=b.right)go(i);
 });
 window.addEventListener('resize',schedule);controls.classList.add('ready');update();
});
// Long reviews have their own reading surface. Its horizontal and vertical
// scroll containers are independent; no touch handler cancels native gestures.
const review=document.getElementById('review-dialog');
if(typeof review.showModal==='function'){
 const track=review.querySelector('.review-track'),previous=review.querySelector('[data-review-step="-1"]'),next=review.querySelector('[data-review-step="1"]');
 const close=review.querySelector('.review-close'),position=review.querySelector('.review-position');
 let pages=[],sourceCards=[],origin=null,current=0,timer;
 function update(){
  if(!pages.length)return;
  current=nearest(track,pages);
  previous.disabled=current===0;next.disabled=current===pages.length-1;
  position.textContent=(current+1)+' / '+pages.length;
  // Keep keyboard navigation and screen readers in the visible review only.
  pages.forEach((page,i)=>{page.inert=i!==current;page.setAttribute('aria-hidden',String(i!==current));});
 }
 function schedule(){clearTimeout(timer);timer=setTimeout(update,140);}
 function go(index){current=Math.max(0,Math.min(pages.length-1,index));scrollToSlide(track,pages,current);schedule();}
 document.querySelectorAll('.editorial-grid').forEach(sourceTrack=>{
  const cards=[...sourceTrack.children];
  cards.forEach((card,index)=>{
   card.querySelector('.insights>summary').addEventListener('click',event=>{
    event.preventDefault();origin=event.currentTarget;sourceCards=cards;current=index;
    const isWeek=sourceTrack.id==='weekly-cards';
    review.querySelector('#review-label').textContent=isWeek?'每周回顾':'每月回顾';
    track.replaceChildren();
    pages=cards.map((source,i)=>{
     const page=document.createElement('article');page.className='review-page';page.tabIndex=0;
     page.setAttribute('aria-label',source.querySelector('.eyebrow').textContent+'，'+source.querySelector('h3').textContent);
     const prose=document.createElement('div');prose.className='review-prose';
     ['.eyebrow','h3','.card-deck','.insight-body'].forEach(selector=>prose.append(source.querySelector(selector).cloneNode(true)));
     const end=document.createElement('p');end.className='review-end';end.textContent='左右滑动切换，向下滚动继续阅读';prose.append(end);
     page.append(prose);track.append(page);return page;
    });
    document.body.classList.add('review-open');review.showModal();
    scrollToSlide(track,pages,index,'auto');update();close.focus({preventScroll:true});
   });
  });
 });
 previous.addEventListener('click',()=>go(current-1));next.addEventListener('click',()=>go(current+1));
 function closeReview(){update();review.close();}
 close.addEventListener('click',closeReview);
 review.addEventListener('cancel',update);
 review.addEventListener('click',event=>{if(event.target===review)closeReview();});
 review.addEventListener('close',()=>{
  clearTimeout(timer);document.body.classList.remove('review-open');
  // Returning from another review restores focus to that review's card.
  const target=sourceCards[current]?.querySelector('summary')||origin;
  if(target){const parent=sourceCards[current]?.parentElement;if(parent)scrollToSlide(parent,sourceCards,current,'auto');target.focus({preventScroll:true});}
 });
 review.addEventListener('keydown',event=>{
  if(event.key==='ArrowLeft'||event.key==='ArrowRight'){
   event.preventDefault();go(current+(event.key==='ArrowRight'?1:-1));
  }
 });
 track.addEventListener('scroll',schedule,{passive:true});
 window.addEventListener('resize',()=>{if(review.open)scrollToSlide(track,pages,current,'auto');});
}
document.querySelector('.nav-links a[href="#archive"]').addEventListener('click',()=>{document.getElementById('archive').open=true;});
// Search requests share one fetch; only the latest typed query paints results.
const cards=[...document.querySelectorAll('.issue-card')],search=document.getElementById('q'),status=document.getElementById('search-status');
let searchPromise=null,queryVersion=0;
search.addEventListener('input',async()=>{
 const version=++queryVersion,query=search.value.trim().toLowerCase();
 if(!searchPromise)searchPromise=fetch('search-index.json').then(response=>{if(!response.ok)throw Error('search');return response.json();}).catch(()=>null);
 const records=await searchPromise;if(version!==queryVersion)return;
 const searchable=new Map((records||[]).map(item=>[item.date,JSON.stringify(item).toLowerCase()]));
 cards.forEach(card=>{card.hidden=!!query&&!(searchable.get(card.dataset.date)||card.textContent.toLowerCase()).includes(query);});
 document.querySelectorAll('.month-group').forEach(group=>{group.hidden=![...group.querySelectorAll('.issue-card')].some(card=>!card.hidden);});
 const count=cards.filter(card=>!card.hidden).length;
 status.textContent=query?(count?'找到 '+count+' 期日报':'没有找到相关日报，试试其他词或日期'):'显示全部归档';
 if(records===null)status.textContent+='；全文搜索暂不可用，当前按标题和摘要查找';
});
"""


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
            archive_title = (summaries or {}).get("daily", {}).get(date, {}).get("card_title") or item.get("thesis") or "Daily Intelligence"
            url = html.escape(item["relative_html"], quote=True)
            summary = re.sub(r"\s+", " ", item.get("summary", "")).strip()
            if len(summary) > 280:
                summary = summary[:280] + "…"
            cards.append(f'''<article class="issue-card" data-date="{date}"><a class="date-box" href="{url}"><span>{date[8:]}</span><small>{('周一','周二','周三','周四','周五','周六','周日')[dt.date.fromisoformat(date).weekday()]}</small></a><div class="issue-body"><div class="issue-meta">{date} · Daily Intelligence</div><h2><a href="{url}">{_compact_title(archive_title)}</a></h2><p>{html.escape(summary)}</p><a class="read-link" href="{url}">阅读全文 →</a></div></article>''')
        sections.append(f'<section class="month-group" id="{month}"><h3>{month}</h3>{"".join(cards)}</section>')
    latest = records[0]
    latest_url = html.escape(latest["relative_html"], quote=True)
    latest_entry = (summaries or {}).get('daily', {}).get(latest['date'], {})
    latest_title = _compact_title(latest_entry.get('card_title') or latest.get('thesis') or '读懂今天')
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
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="description" content="读懂 AI、科技、商业与宏观的重要变化。每日完整报道，每周与每月回顾。"><title>Daily Intelligence · 读懂重要变化</title><style>{_HOME_CSS}</style></head><body>
<a class="skip-link" href="#daily">跳到新闻</a><nav class="site-nav" aria-label="主要导航"><div class="nav-inner"><a class="brand" href="#top">Daily Intelligence</a><div class="nav-links"><a href="#daily">每日</a><a href="#weekly">每周</a><a href="#monthly">每月</a><a href="#archive">归档</a></div></div></nav><main id="top">
<header class="hero"><div class="eyebrow">{latest['date'].replace('-', '.')} · 今日导读</div><h1>{latest_title}</h1><p class="hero-deck">{latest_deck}</p><a class="primary-cta" href="{latest_url}">阅读本期 <span aria-hidden="true">↗</span></a><p class="issue-date">AI · 科技 · 商业 · 宏观</p></header><div class="content">
<section id="daily"><div class="section-head"><div><div class="section-kicker">DAILY</div><h2>每天，读懂新变化</h2><p>最近 7 天，值得了解的事实与影响</p></div></div><div class="daily-grid" id="daily-cards" role="region" aria-label="最近七天日报" tabindex="0">{week_cards}</div>{_carousel_controls('daily',len([r for r in records if r['date']>=daily_start]))}</section>
<section id="weekly"><div class="section-head"><div><div class="section-kicker">WEEKLY</div><h2>每周，把变化连起来</h2><p>最近四个完整自然周，哪些判断得到支持</p></div></div><div class="editorial-grid" id="weekly-cards" role="region" aria-label="最近四周总结" tabindex="0">{weekly_reviews}</div>{_carousel_controls('weekly',4)}</section>
<section id="monthly"><div class="section-head"><div><div class="section-kicker">MONTHLY</div><h2>每月，看清来龙去脉</h2><p>最近三个完整自然月，区分长期变化与单次事件</p></div></div><div class="editorial-grid monthly-grid" id="monthly-cards" role="region" aria-label="最近三个月总结" tabindex="0">{monthly_reviews}</div>{_carousel_controls('monthly',3)}</section>
<details id="archive" class="archive"><summary>探索全部归档</summary><p class="archive-intro">按月份回看，也可以搜索你关心的主题</p><nav class="month-nav" aria-label="归档月份">{month_links}</nav><div class="search-wrap"><label for="q">搜索归档</label><input id="q" type="search" placeholder="日期、公司或主题" autocomplete="off"></div><p class="search-status" id="search-status" role="status" aria-live="polite">输入关键词，查找相关日报</p><section id="results">{''.join(sections)}</section></details>
<footer class="footer"><p>Daily Intelligence · 把重要的事，讲清楚</p><a href="#top">回到顶部 ↑</a></footer></div></main>
<dialog class="review-dialog" id="review-dialog" aria-labelledby="review-label"><div class="review-toolbar"><h2 id="review-label">回顾</h2><span class="review-position" aria-live="polite" aria-atomic="true"></span><button type="button" data-review-step="-1" aria-label="上一篇回顾">‹</button><button type="button" data-review-step="1" aria-label="下一篇回顾">›</button><button class="review-close" type="button" aria-label="关闭回顾" autofocus>×</button></div><div class="review-track" aria-label="回顾全文"></div></dialog><script>{_HOME_JS}</script></body></html>'''



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
