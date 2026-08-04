#!/usr/bin/env python3
"""Generate two daily news briefings as Markdown and readable HTML."""

from __future__ import annotations

import argparse
import datetime as dt
import email.utils
import html
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, Iterable, List


ROOT = Path(__file__).resolve().parent
USER_AGENT = "DailyNewsObserver/1.0 (+local personal news digest)"


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def fetch_bytes(url: str, timeout: int = 20) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/atom+xml, text/xml"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def text_of(element: ET.Element | None) -> str:
    if element is None:
        return ""
    return " ".join("".join(element.itertext()).split())


def strip_html(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", value or "")
    return html.unescape(" ".join(value.split()))


def parse_date(value: str) -> dt.datetime | None:
    if not value:
        return None
    try:
        parsed = email.utils.parsedate_to_datetime(value)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)
    except (TypeError, ValueError):
        pass
    try:
        normalized = value.replace("Z", "+00:00")
        parsed = dt.datetime.fromisoformat(normalized)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)
    except ValueError:
        return None


def parse_feed(data: bytes, feed_name: str) -> List[Dict[str, str]]:
    root = ET.fromstring(data)
    items: List[Dict[str, str]] = []

    if root.tag.endswith("feed"):  # Atom
        entries = [node for node in root.iter() if node.tag.endswith("entry")]
        for entry in entries:
            title = text_of(next((n for n in entry if n.tag.endswith("title")), None))
            summary = text_of(
                next((n for n in entry if n.tag.endswith(("summary", "content"))), None)
            )
            link_node = next(
                (n for n in entry if n.tag.endswith("link") and n.attrib.get("href")), None
            )
            date_value = text_of(
                next((n for n in entry if n.tag.endswith(("published", "updated"))), None)
            )
            items.append(
                {
                    "title": title,
                    "summary": strip_html(summary),
                    "url": link_node.attrib.get("href", "") if link_node is not None else "",
                    "published": date_value,
                    "source": feed_name,
                }
            )
    else:  # RSS
        entries = [node for node in root.iter() if node.tag.endswith("item")]
        for entry in entries:
            values: Dict[str, str] = {}
            for child in entry:
                key = child.tag.split("}")[-1]
                if key in {"title", "link", "description", "pubDate", "date"}:
                    values[key] = text_of(child)
            items.append(
                {
                    "title": values.get("title", ""),
                    "summary": strip_html(values.get("description", "")),
                    "url": values.get("link", ""),
                    "published": values.get("pubDate", values.get("date", "")),
                    "source": feed_name,
                }
            )
    return [item for item in items if item["title"] and item["url"]]


def collect_sources(feeds: Iterable[Dict[str, str]], hours: int, limit: int) -> List[Dict[str, str]]:
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours)
    collected: List[Dict[str, str]] = []
    for feed in feeds:
        try:
            collected.extend(parse_feed(fetch_bytes(feed["url"]), feed["name"]))
        except (urllib.error.URLError, TimeoutError, ET.ParseError, KeyError) as exc:
            print(f"警告：无法读取 {feed.get('name', feed.get('url', 'feed'))}: {exc}", file=sys.stderr)

    unique: Dict[str, Dict[str, str]] = {}
    for item in collected:
        key = re.sub(r"\W+", "", item["title"].lower())
        published = parse_date(item["published"])
        if published and published < cutoff:
            continue
        if key and key not in unique:
            item["_date"] = published.isoformat() if published else ""
            unique[key] = item

    return sorted(unique.values(), key=lambda x: x["_date"], reverse=True)[:limit]


def source_bundle(items: List[Dict[str, str]]) -> str:
    chunks = []
    for index, item in enumerate(items, 1):
        chunks.append(
            f"[S{index}] {item['title']}\n"
            f"来源: {item['source']}\n"
            f"时间: {item['published'] or '未提供'}\n"
            f"链接: {item['url']}\n"
            f"摘要: {item['summary'][:700] or '无摘要'}"
        )
    return "\n\n".join(chunks)


def call_openai(prompt: str, model: str) -> str:
    api_key = os.environ.get("OPENAI_API_KEY", "")
    base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    timeout = int(os.environ.get("OPENAI_TIMEOUT_SECONDS", "180"))
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY 未配置")

    instructions = (
        "你是严谨的中文新闻研究员。只能使用用户提供的材料，不得补充未被材料支持的事实。"
        "区分事实、推断和待验证信号。输出纯 Markdown，不要使用代码围栏。"
    )
    payload = json.dumps(
        {
            "model": model,
            "instructions": instructions,
            "input": prompt,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url}/responses",
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        if exc.code != 404:
            raise RuntimeError(f"OpenAI API 返回 HTTP {exc.code}: {detail[:500]}") from exc
        return call_chat_completions(base_url, api_key, model, instructions, prompt, timeout)

    if body.get("output_text"):
        return body["output_text"].strip()
    texts = []
    for output in body.get("output", []):
        for content in output.get("content", []):
            if content.get("type") == "output_text" and content.get("text"):
                texts.append(content["text"])
    if not texts:
        raise RuntimeError("OpenAI API 响应中没有文本输出")
    return "\n".join(texts).strip()


def call_chat_completions(
    base_url: str,
    api_key: str,
    model: str,
    instructions: str,
    prompt: str,
    timeout: int,
) -> str:
    """Compatibility fallback for gateways/models without the Responses API."""
    payload = json.dumps(
        {
            "model": model,
            "messages": [
                {"role": "system", "content": instructions},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Chat Completions API 返回 HTTP {exc.code}: {detail[:500]}") from exc
    try:
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("Chat Completions API 响应中没有文本输出") from exc
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        return "\n".join(
            item.get("text", "") for item in content if isinstance(item, dict) and item.get("text")
        ).strip()
    raise RuntimeError("Chat Completions API 返回了不支持的文本格式")


def common_prompt(date: str, items: List[Dict[str, str]]) -> str:
    return (
        f"报告日期：{date}\n"
        "引用规则：每个关键事实后标注来源编号，例如 [S1]；不得虚构来源；文末列出来源链接。\n"
        "如果来源不足或互相冲突，明确写出限制。避免投资建议和确定性预测。\n\n"
        f"材料：\n{source_bundle(items)}"
    )


def ai_prompt(date: str, items: List[Dict[str, str]]) -> str:
    return (
        "请生成《全球 AI 动态日报》，约 1000—1500 字，结构如下：\n"
        "# 全球 AI 动态日报\n"
        "> 日期、30 秒摘要\n"
        "## 今日最重要的 3—5 个变化\n"
        "每项说明：发生了什么、为什么重要、对产品/企业/个人的影响。\n"
        "## 趋势雷达\n"
        "覆盖模型与产品、算力与芯片、资本与商业化、监管与安全；没有可靠材料的类别可省略。\n"
        "## 接下来值得观察\n"
        "列出 3 个可验证信号。\n"
        "## 信息边界\n"
        "## 来源\n"
        "来源使用 Markdown 链接列表。\n\n"
        + common_prompt(date, items)
    )


def industry_prompt(date: str, items: List[Dict[str, str]]) -> str:
    return (
        "请生成《行业与宏观每日观察》。采用原则驱动的宏观分析框架：从事实出发，解释"
        "因果链、反馈循环、二阶影响和可证伪信号。不要模仿或声称使用任何在世作者的独特文风。\n"
        "约 1200—1800 字，结构如下：\n"
        "# 行业与宏观每日观察\n"
        "> 日期、一句话总判断\n"
        "## 今天发生了什么\n"
        "按受影响最大的行业组织 4—6 项。\n"
        "## 机器如何运转\n"
        "解释增长、通胀、利率/流动性、政策、技术与地缘因素之间的因果链。\n"
        "## 一阶与二阶影响\n"
        "明确区分直接影响和后续传导。\n"
        "## 受益、承压与分歧\n"
        "只做情景分析，不给具体证券买卖建议。\n"
        "## 未来 7—30 天观察清单\n"
        "列出 5 个可验证指标或事件。\n"
        "## 反方观点与信息边界\n"
        "## 来源\n"
        "来源使用 Markdown 链接列表。\n\n"
        + common_prompt(date, items)
    )


def fallback_report(title: str, date: str, items: List[Dict[str, str]], observation: bool) -> str:
    lines = [
        f"# {title}",
        "",
        f"> 日期：{date}  ",
        "> 当前为基础版：未配置模型 API，以下内容按来源发布时间整理，未进行深度综合。",
        "",
        "## 今日要点",
        "",
    ]
    if not items:
        lines.extend(["未抓取到可用新闻。请检查网络或在 `config.json` 中调整信息源。", ""])
    for index, item in enumerate(items[:8], 1):
        summary = item["summary"][:240] or "来源未提供摘要。"
        lines.extend(
            [
                f"### {index}. {item['title']}",
                "",
                f"{summary}",
                "",
                f"- 来源：[{item['source']}]({item['url']})",
                f"- 时间：{item['published'] or '未提供'}",
                "",
            ]
        )
    if observation:
        lines.extend(
            [
                "## 观察框架",
                "",
                "- 一阶影响：关注事件直接改变了哪些成本、需求、供给或规则。",
                "- 二阶影响：关注企业、消费者、资本和政策制定者随后如何调整行为。",
                "- 验证信号：后续价格、订单、库存、就业、融资与监管数据是否支持当前叙事。",
                "",
            ]
        )
    lines.extend(["## 来源", ""])
    for index, item in enumerate(items, 1):
        lines.append(f"- [S{index}：{item['title']}]({item['url']}) — {item['source']}")
    lines.append("")
    return "\n".join(lines)


INLINE_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)]+)\)")
INLINE_IMAGE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")


def inline_markup(text: str) -> str:
    parts: List[str] = []
    cursor = 0
    tokens = []
    tokens.extend(("image", match) for match in INLINE_IMAGE.finditer(text))
    tokens.extend(("link", match) for match in INLINE_LINK.finditer(text) if match.start() == 0 or text[match.start() - 1] != "!")
    tokens.sort(key=lambda item: item[1].start())
    for token_type, match in tokens:
        if match.start() < cursor:
            continue
        parts.append(html.escape(text[cursor : match.start()], quote=True))
        label = html.escape(match.group(1), quote=True)
        url = html.escape(match.group(2), quote=True)
        if token_type == "image":
            parts.append(f'<img src="{url}" alt="{label}" loading="lazy">')
        else:
            parts.append(f'<a href="{url}" target="_blank" rel="noopener">{label}</a>')
        cursor = match.end()
    parts.append(html.escape(text[cursor:], quote=True))
    marked = "".join(parts)
    marked = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", marked)
    marked = re.sub(r"`([^`]+)`", r"<code>\1</code>", marked)
    return marked


def markdown_to_html(markdown: str, page_title: str) -> str:
    output: List[str] = []
    in_list = False
    paragraph: List[str] = []
    table_rows: List[List[str]] = []

    def flush_paragraph() -> None:
        nonlocal paragraph
        if paragraph:
            output.append(f"<p>{inline_markup(' '.join(paragraph))}</p>")
            paragraph = []

    def close_list() -> None:
        nonlocal in_list
        if in_list:
            output.append("</ul>")
            in_list = False

    def flush_table() -> None:
        nonlocal table_rows
        if not table_rows:
            return
        header, *body = table_rows
        output.append("<div class=\"table-wrap\"><table><thead><tr>")
        output.extend(f"<th>{inline_markup(cell)}</th>" for cell in header)
        output.append("</tr></thead><tbody>")
        for row in body:
            output.append("<tr>")
            output.extend(f"<td>{inline_markup(cell)}</td>" for cell in row)
            output.append("</tr>")
        output.append("</tbody></table></div>")
        table_rows = []

    for raw in markdown.splitlines():
        line = raw.rstrip()
        if not line:
            flush_paragraph()
            close_list()
            flush_table()
            continue
        if line.startswith("|") and line.endswith("|"):
            flush_paragraph()
            close_list()
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
                continue
            table_rows.append(cells)
            continue
        flush_table()
        heading = re.match(r"^(#{1,4})\s+(.+)$", line)
        if heading:
            flush_paragraph()
            close_list()
            level = len(heading.group(1))
            output.append(f"<h{level}>{inline_markup(heading.group(2))}</h{level}>")
        elif line.startswith("> "):
            flush_paragraph()
            close_list()
            output.append(f"<blockquote>{inline_markup(line[2:].rstrip('  '))}</blockquote>")
        elif re.match(r"^[-*]\s+", line):
            flush_paragraph()
            if not in_list:
                output.append("<ul>")
                in_list = True
            list_text = re.sub(r"^[-*]\s+", "", line)
            output.append(f"<li>{inline_markup(list_text)}</li>")
        elif re.match(r"^\d+\.\s+", line):
            flush_paragraph()
            close_list()
            output.append(f"<p class=\"numbered\">{inline_markup(line)}</p>")
        elif line.strip() == "---":
            flush_paragraph()
            close_list()
            output.append("<hr>")
        else:
            paragraph.append(line.rstrip("  "))
    flush_paragraph()
    close_list()
    flush_table()

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(page_title)}</title>
  <style>
    :root {{ color-scheme: light; --ink:#17202a; --muted:#667085; --accent:#155eef; --paper:#fff; --bg:#f4f7fb; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; background:var(--bg); color:var(--ink); font:17px/1.75 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif; }}
    main {{ max-width:860px; margin:32px auto; padding:48px 64px; background:var(--paper); border-radius:18px; box-shadow:0 12px 40px rgba(16,24,40,.08); }}
    h1 {{ font-size:2.2rem; line-height:1.25; margin:0 0 1rem; }}
    h2 {{ margin-top:2.2rem; padding-bottom:.35rem; border-bottom:1px solid #e4e7ec; }}
    h3 {{ margin-top:1.6rem; }}
    a {{ color:var(--accent); text-decoration:none; }} a:hover {{ text-decoration:underline; }}
    blockquote {{ margin:1rem 0; padding:.8rem 1rem; color:var(--muted); background:#f8fafc; border-left:4px solid #84adff; }}
    code {{ background:#eef2f6; padding:.12rem .35rem; border-radius:4px; }}
    li {{ margin:.45rem 0; }} .numbered {{ padding-left:.25rem; }}
    img {{ display:block; max-width:100%; height:auto; margin:1.25rem auto; border-radius:12px; }}
    .table-wrap {{ overflow-x:auto; margin:1.2rem 0; }} table {{ width:100%; border-collapse:collapse; font-size:.94rem; }}
    th,td {{ padding:.7rem .75rem; border-bottom:1px solid #e4e7ec; text-align:left; white-space:nowrap; }}
    th {{ background:#f8fafc; }}
    footer {{ max-width:860px; margin:0 auto 32px; color:var(--muted); text-align:center; font-size:.85rem; }}
    @media (max-width:700px) {{ main {{ margin:0; padding:28px 20px; border-radius:0; }} }}
  </style>
</head>
<body>
  <main>
    {''.join(output)}
  </main>
  <footer>由本地 Daily News Observer 自动生成 · 请核对原始来源</footer>
</body>
</html>
"""


def combined_index(date: str, pages: List[Dict[str, str]]) -> str:
    cards = "".join(
        f'<a class="card" href="{page["file"]}"><span>{page["eyebrow"]}</span>'
        f'<h2>{page["title"]}</h2><p>{page["description"]}</p><b>阅读全文 →</b></a>'
        for page in pages
    )
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{date} 每日新闻观察</title>
<style>
body{{margin:0;min-height:100vh;background:#0b1220;color:#f8fafc;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC",sans-serif}}
main{{max-width:1050px;margin:auto;padding:9vh 28px}}header{{max-width:700px;margin-bottom:50px}}
.date,.card span{{color:#7dd3fc;font-size:.85rem;letter-spacing:.12em;text-transform:uppercase}}
h1{{font-size:clamp(2.5rem,7vw,5.5rem);line-height:1.02;margin:.35em 0}}header p{{color:#a8b3c7;font-size:1.15rem;line-height:1.7}}
.grid{{display:grid;grid-template-columns:repeat(2,1fr);gap:24px}}.card{{display:block;padding:32px;border:1px solid #26344d;border-radius:18px;background:#111b2e;color:inherit;text-decoration:none;transition:.2s}}
.card:hover{{transform:translateY(-4px);border-color:#38bdf8}}.card h2{{font-size:1.65rem}}.card p{{color:#a8b3c7;line-height:1.7;min-height:5.1em}}.card b{{color:#7dd3fc}}
@media(max-width:720px){{.grid{{grid-template-columns:1fr}}main{{padding-top:50px}}}}
</style></head><body><main><header><div class="date">{date}</div><h1>每日新闻观察</h1>
<p>全球 AI 动态与跨行业宏观信号。所有判断均应回到原始来源验证。</p></header><section class="grid">{cards}</section></main></body></html>"""


def main() -> int:
    parser = argparse.ArgumentParser(description="生成每日 AI 与行业新闻观察")
    parser.add_argument("--date", help="报告日期，格式 YYYY-MM-DD，默认今天")
    parser.add_argument("--config", default=str(ROOT / "config.json"), help="配置文件路径")
    parser.add_argument("--fallback-only", action="store_true", help="不调用模型，仅生成基础版")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    report_date = args.date or dt.date.today().isoformat()
    output_dir = ROOT / config.get("output_dir", "output") / report_date
    output_dir.mkdir(parents=True, exist_ok=True)

    hours = int(config.get("lookback_hours", 48))
    limit = int(config.get("max_items_per_report", 18))
    ai_items = collect_sources(config["feeds"]["ai"], hours, limit)
    industry_items = collect_sources(config["feeds"]["industry"], hours, limit)
    model = os.environ.get("OPENAI_MODEL", config.get("model", "gpt-5.4-mini"))

    use_model = bool(os.environ.get("OPENAI_API_KEY")) and not args.fallback_only
    if use_model:
        ai_markdown = call_openai(ai_prompt(report_date, ai_items), model)
        industry_markdown = call_openai(industry_prompt(report_date, industry_items), model)
    else:
        ai_markdown = fallback_report("全球 AI 动态日报", report_date, ai_items, False)
        industry_markdown = fallback_report("行业与宏观每日观察", report_date, industry_items, True)

    files = [
        ("ai-news", "全球 AI 动态日报", ai_markdown),
        ("industry-observation", "行业与宏观每日观察", industry_markdown),
    ]
    for stem, title, markdown in files:
        (output_dir / f"{stem}.md").write_text(markdown.strip() + "\n", encoding="utf-8")
        (output_dir / f"{stem}.html").write_text(
            markdown_to_html(markdown, f"{report_date} {title}"), encoding="utf-8"
        )

    (output_dir / "index.html").write_text(
        combined_index(
            report_date,
            [
                {
                    "file": "ai-news.html",
                    "eyebrow": "AI TRACKER",
                    "title": "全球 AI 动态日报",
                    "description": "模型、产品、算力、商业化、监管与安全的关键变化。",
                },
                {
                    "file": "industry-observation.html",
                    "eyebrow": "MACRO & INDUSTRIES",
                    "title": "行业与宏观每日观察",
                    "description": "用因果链、反馈循环和二阶影响理解跨行业动态。",
                },
            ],
        ),
        encoding="utf-8",
    )
    (ROOT / config.get("output_dir", "output") / "latest.html").write_text(
        f'<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="0; url={report_date}/index.html">',
        encoding="utf-8",
    )

    print(f"完成：{output_dir}")
    print(f"AI 来源 {len(ai_items)} 条；行业来源 {len(industry_items)} 条；模式：{'模型综合' if use_model else '基础版'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
