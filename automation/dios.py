#!/usr/bin/env python3
"""Daily Intelligence OS: generate and archive one high-density daily briefing."""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import math
import os
import random
import re
import struct
import urllib.error
import urllib.parse
import urllib.request
import zlib
from pathlib import Path
from typing import Dict, List

import generate as core


ROOT = Path(__file__).resolve().parent
QUOTES = [
    (
        "Price is what you pay. Value is what you get.",
        "Warren Buffett",
        "价格是你付出的东西，价值是你真正得到的东西。",
    ),
    (
        "The big money is not in the buying and selling, but in the waiting.",
        "Charlie Munger",
        "真正的大钱往往不来自频繁买卖，而来自有判断后的耐心等待。",
    ),
    (
        "Risk means more things can happen than will happen.",
        "Elroy Dimson",
        "风险的核心不是预测一个结果，而是承认可能结果的范围远大于最终发生的那个结果。",
    ),
    (
        "The future is already here — it is just not evenly distributed.",
        "William Gibson",
        "未来其实已经出现，只是分布在少数地区、公司和人群中，还没有扩散到所有地方。",
    ),
    (
        "It is better to be roughly right than precisely wrong.",
        "John Maynard Keynes",
        "在复杂系统里，方向上大致正确，通常比数字上精确但逻辑错误更重要。",
    ),
    (
        "The essence of strategy is choosing what not to do.",
        "Michael Porter",
        "战略的本质不是做更多事，而是清楚地决定哪些事不做。",
    ),
    (
        "In the short run, the market is a voting machine but in the long run, it is a weighing machine.",
        "Benjamin Graham",
        "短期市场反映情绪和投票，长期市场会回到基本面和真实重量。",
    ),
    (
        "What gets measured gets managed.",
        "Peter Drucker",
        "被持续衡量的东西，才会真正进入管理和资源配置。",
    ),
    (
        "The most important thing is not to be smarter than others, but to be more disciplined than others.",
        "Howard Marks",
        "重要的不是永远比别人聪明，而是在不确定性面前比别人更守纪律。",
    ),
    (
        "The nature of technology is that it creates previously impossible ways to economize on scarce resources.",
        "Marc Andreessen",
        "技术的本质，是让人类用过去不可能的方式节约稀缺资源。",
    ),
    (
        "If something cannot go on forever, it will stop.",
        "Herbert Stein",
        "不能永远持续的东西，最终一定会停止；问题只在时间和路径。",
    ),
    (
        "You can’t predict, but you can prepare.",
        "Howard Marks",
        "你无法精确预测未来，但可以为多种未来提前准备。",
    ),
    (
        "The greatest danger in times of turbulence is not the turbulence; it is to act with yesterday’s logic.",
        "Peter Drucker",
        "动荡时期最大的危险不是动荡本身，而是继续用昨天的逻辑行动。",
    ),
    (
        "Compound interest is the eighth wonder of the world.",
        "Attributed to Albert Einstein",
        "复利的力量来自时间、持续性和不被中断的积累。",
    ),
    (
        "Plans are worthless, but planning is everything.",
        "Dwight D. Eisenhower",
        "计划本身常会失效，但规划过程能让你理解约束、选项和应对路径。",
    ),
    (
        "The biggest risk is not taking any risk.",
        "Mark Zuckerberg",
        "在快速变化的系统里，完全不承担风险本身也可能是最大的风险。",
    ),
    (
        "All models are wrong, but some are useful.",
        "George Box",
        "所有模型都会简化现实，但有些模型能帮助你抓住真正重要的机制。",
    ),
    (
        "Prediction is very difficult, especially if it’s about the future.",
        "Attributed to Niels Bohr",
        "预测未来很难，所以更重要的是识别关键变量和更新机制。",
    ),
    (
        "Skate to where the puck is going, not where it has been.",
        "Wayne Gretzky",
        "判断趋势时，要看系统下一步可能去哪里，而不是只看它过去在哪里。",
    ),
    (
        "The world is full of obvious things which nobody by any chance ever observes.",
        "Arthur Conan Doyle",
        "世界充满显而易见却无人真正观察的信号，洞察常来自重新看见这些信号。",
    ),
    (
        "The first principle is that you must not fool yourself — and you are the easiest person to fool.",
        "Richard Feynman",
        "第一原则是不要欺骗自己，而自己恰恰是最容易被欺骗的人。",
    ),
    (
        "Without data, you're just another person with an opinion.",
        "W. Edwards Deming",
        "没有数据支撑，观点就很难与普通意见区分开。",
    ),
    (
        "The purpose of computing is insight, not numbers.",
        "Richard Hamming",
        "计算的目的不是堆积数字，而是获得洞察。",
    ),
    (
        "Nothing is particularly hard if you divide it into small jobs.",
        "Henry Ford",
        "把复杂问题拆成足够小的任务后，困难往往会显著下降。",
    ),
    (
        "There is nothing so useless as doing efficiently that which should not be done at all.",
        "Peter Drucker",
        "最高效地完成一件本不该做的事，仍然没有价值。",
    ),
    (
        "An investment in knowledge pays the best interest.",
        "Benjamin Franklin",
        "对知识的投资，往往能带来最持久的回报。",
    ),
    (
        "The measure of intelligence is the ability to change.",
        "Attributed to Albert Einstein",
        "衡量智慧的重要标准，是能否根据新证据改变判断。",
    ),
    (
        "Simplicity is prerequisite for reliability.",
        "Edsger W. Dijkstra",
        "简洁不是装饰，而是可靠性的前提。",
    ),
    (
        "You cannot improve what you do not measure.",
        "Lord Kelvin",
        "没有持续衡量，就很难知道改善是否真实发生。",
    ),
    (
        "Facts are stubborn things.",
        "John Adams",
        "事实很顽固，最终会迫使叙事接受检验。",
    ),
]


def fetch_market(name: str, symbol: str) -> Dict[str, object]:
    encoded = urllib.parse.quote(symbol, safe="")
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded}?range=10d&interval=1d"
    request = urllib.request.Request(url, headers={"User-Agent": core.USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read())
        result = payload["chart"]["result"][0]
        quote = result["indicators"]["quote"][0]
        closes = [float(x) for x in quote["close"] if x is not None]
        if len(closes) < 2:
            raise ValueError("有效收盘价不足")
        current, previous = closes[-1], closes[-2]
        change = (current / previous - 1) * 100
        return {
            "name": name,
            "symbol": symbol,
            "value": round(current, 4),
            "change_pct": round(change, 2),
            "direction": "↑" if change > 0.05 else "↓" if change < -0.05 else "→",
            "status": "ok",
            "source_url": f"https://finance.yahoo.com/quote/{encoded}",
        }
    except (urllib.error.URLError, KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return {
            "name": name,
            "symbol": symbol,
            "value": None,
            "change_pct": None,
            "direction": "—",
            "status": f"unavailable: {exc}",
            "source_url": f"https://finance.yahoo.com/quote/{encoded}",
        }


def market_interpretation(item: Dict[str, object]) -> str:
    name, change = item["name"], item["change_pct"]
    if change is None:
        return "待更新"
    magnitude = abs(float(change))
    if name == "VIX":
        return "避险升温" if change > 1 else "风险偏好改善" if change < -1 else "市场稳定"
    if name == "美元指数":
        return "金融条件偏紧" if change > 0.15 else "外部压力缓解" if change < -0.15 else "中性"
    if name == "十年美债收益率":
        return "成长估值承压" if change > 0.25 else "利好久期资产" if change < -0.25 else "中性"
    if name == "黄金":
        return "避险/通胀对冲增强" if change > 0.3 else "避险需求回落" if change < -0.3 else "中性"
    if name == "原油":
        return "通胀压力上升" if change > 0.5 else "通胀压力缓解" if change < -0.5 else "供需平衡"
    if name in {"Nasdaq", "BTC", "NVIDIA"}:
        return "风险偏好改善" if change > 0.3 else "风险偏好降温" if change < -0.3 else "中性"
    return "波动显著" if magnitude > 1 else "中性"


def market_markdown(markets: List[Dict[str, object]]) -> str:
    lines = ["| 指标 | 最新值 | 今日 | 信号 |", "|---|---:|:---:|---|"]
    for item in markets:
        value = "N/A" if item["value"] is None else f"{item['value']:,.2f}"
        change = "N/A" if item["change_pct"] is None else f"{item['change_pct']:+.2f}%"
        lines.append(
            f"| [{item['name']}]({item['source_url']}) | {value} | {item['direction']} {change} | {market_interpretation(item)} |"
        )
    return "\n".join(lines)


def choose_quote(report_date: dt.date, archive_root: Path, lookback_days: int = 10) -> tuple:
    """Choose a deterministic quote without repeating until the pool is exhausted."""
    last_used: Dict[tuple, dt.date] = {}

    def remember_from_markdown(markdown_path: Path) -> None:
        try:
            text = markdown_path.read_text(encoding="utf-8")
        except OSError:
            return
        section = re.search(r"##\s+⑨\s+Quote of the Day[^\n]*\n(.*?)(?=\n##\s|\Z)", text, flags=re.S)
        if not section:
            return
        quote_match = re.search(r">+\s*[“\"](.+?)[”\"]", section.group(1))
        speaker_match = re.search(r">\s*—\s*(.+)", section.group(1))
        if quote_match and speaker_match:
            key = (quote_match.group(1).strip(), speaker_match.group(1).strip())
            try:
                issue_date = dt.date.fromisoformat(markdown_path.parent.name)
            except ValueError:
                return
            if issue_date < report_date:
                last_used[key] = max(issue_date, last_used.get(key, dt.date.min))

    history_roots = {archive_root.resolve()}
    local_release = ROOT / "pages-repo"
    if local_release.is_dir():
        history_roots.add(local_release.resolve())
    if ROOT.name == "automation":
        history_roots.add(ROOT.parent.resolve())

    day_dirs = set()
    for history_root in history_roots:
        day_dirs.update(path.parent for path in history_root.glob("*/*/*/data.json"))
        day_dirs.update(path.parent for path in history_root.glob("*/*/*/Daily Intelligence.md"))

    for day_dir in sorted(day_dirs):
        try:
            issue_date = dt.date.fromisoformat(day_dir.name)
        except ValueError:
            continue
        if issue_date >= report_date:
            continue
        data_path = day_dir / "data.json"
        try:
            data = json.loads(data_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            remember_from_markdown(day_dir / "Daily Intelligence.md")
            continue
        quote = data.get("quote") or {}
        english = quote.get("english")
        speaker = quote.get("speaker")
        if english and speaker:
            key = (english.strip(), speaker.strip())
            last_used[key] = max(issue_date, last_used.get(key, dt.date.min))
        else:
            remember_from_markdown(day_dir / "Daily Intelligence.md")

    candidates = [q for q in QUOTES if (q[0], q[1]) not in last_used]
    if not candidates:
        oldest = min(last_used.get((q[0], q[1]), dt.date.min) for q in QUOTES)
        candidates = [q for q in QUOTES if last_used.get((q[0], q[1]), dt.date.min) == oldest]
    return random.Random(report_date.toordinal()).choice(candidates)


def quote_markdown(quote: tuple) -> str:
    english, speaker, chinese = quote
    return (
        "## ⑨ Quote of the Day\n\n"
        f'> “{english}”  \n'
        f"> — {speaker}\n\n"
        f"**中文理解**：{chinese}\n\n"
        "**Why it matters today**：这句话不是装饰，而是今天观察 AI、商业和宏观变化时的一个思考框架：先看机制，再看价格；先看约束，再看叙事。"
    )


def ensure_quote_section(markdown: str, quote: tuple) -> str:
    canonical = quote_markdown(quote).strip()
    pattern = r"##\s+⑨\s+Quote of the Day[^\n]*\n.*?(?=\n##\s+⑩|\Z)"
    if re.search(pattern, markdown, flags=re.S):
        return re.sub(pattern, canonical, markdown, flags=re.S)
    return markdown.rstrip() + "\n\n" + canonical + "\n"


def make_chart_svg(markets: List[Dict[str, object]], path: Path, date: str) -> None:
    available = [item for item in markets if item["change_pct"] is not None][:8]
    width, height = 980, 130 + len(available) * 62
    max_change = max([abs(float(item["change_pct"])) for item in available] + [1.0])
    rows = []
    zero_x, scale = 490, 360 / max_change
    for index, item in enumerate(available):
        y = 105 + index * 62
        change = float(item["change_pct"])
        bar_width = min(abs(change) * scale, 360)
        x = zero_x if change >= 0 else zero_x - bar_width
        color = "#16a34a" if change >= 0 else "#dc2626"
        rows.append(
            f'<text x="30" y="{y + 7}" class="label">{html.escape(str(item["name"]))}</text>'
            f'<rect x="{x:.1f}" y="{y - 16}" width="{bar_width:.1f}" height="28" rx="6" fill="{color}"/>'
            f'<text x="{850 if change >= 0 else 130}" y="{y + 7}" class="value">{change:+.2f}%</text>'
        )
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
<rect width="100%" height="100%" rx="24" fill="#0b1220"/>
<style>.title{{font:700 25px -apple-system,BlinkMacSystemFont,sans-serif;fill:#f8fafc}}.sub{{font:14px sans-serif;fill:#94a3b8}}.label{{font:16px sans-serif;fill:#e2e8f0}}.value{{font:600 15px monospace;fill:#cbd5e1}}.axis{{stroke:#475569;stroke-width:1}}</style>
<text x="30" y="42" class="title">One Chart · Daily Market Pulse</text>
<text x="30" y="68" class="sub">{date} · 最近交易日涨跌幅，方向信号不构成投资建议</text>
<line x1="{zero_x}" y1="86" x2="{zero_x}" y2="{height - 24}" class="axis"/>
{''.join(rows)}
</svg>"""
    path.write_text(svg, encoding="utf-8")


def png_chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def make_cover_png(path: Path, date: str, width: int = 1200, height: int = 630) -> None:
    """Create a dependency-free branded gradient PNG."""
    rows = bytearray()
    seed = int(date.replace("-", ""))
    for y in range(height):
        rows.append(0)
        for x in range(width):
            wave = int(18 * math.sin((x + seed % 97) / 90) * math.cos((y + seed % 53) / 70))
            r = max(7, min(255, 11 + int(22 * y / height) + wave // 4))
            g = max(15, min(255, 24 + int(45 * x / width) + wave // 2))
            b = max(35, min(255, 58 + int(100 * (1 - y / height)) + wave))
            rows.extend((r, g, b))
    signature = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    path.write_bytes(signature + png_chunk(b"IHDR", ihdr) + png_chunk(b"IDAT", zlib.compress(bytes(rows), 7)) + png_chunk(b"IEND", b""))


def dios_prompt(
    date_label: str,
    ai_items: List[Dict[str, str]],
    industry_items: List[Dict[str, str]],
    markets: List[Dict[str, object]],
    quote: tuple,
) -> str:
    market_data = market_markdown(markets)
    quote_block = quote_markdown(quote)
    return f"""生成一份 8—10 分钟可读完的《Daily Intelligence》。目标是解释趋势和机制，不是堆叠新闻。

严格使用以下结构与标题：
# Daily Intelligence
> {date_label}

## Today’s Thesis｜今日一句话
一句有判断、可被后续事实验证的核心论点。

## ① Executive Summary｜30 秒
恰好三条，分别回答今天最重要的 AI、商业、宏观变化。

## ② AI Daily
选择最多 3 个真正重要的变化。每项固定包含三级标题：What Happened、Why It Matters、Second-order Effect。
至少用一个纯文本箭头因果链，例如 A → B → C。

## ③ Business Daily
从科技、金融、能源、医疗、制造、消费、自动驾驶中，只选择今天最值得关注的 2—4 个行业。

## ④ Macro Observation｜机制分析
依次回答：世界正在发生什么？为什么发生？资本如何流动？接下来关注什么？
强调机制、反馈循环与可能的反身性；区分事实和推断。

## ⑤ Signal Dashboard
原样放入下面的市场表格，不修改数值：
{market_data}

## ⑥ Deep Insight
只写一个主题，必须达到 700—1000 个汉字（不含标题）。必须提出非共识或容易被忽略的视角，并给出反方观点与证伪条件。

## ⑦ Tomorrow Watch
固定 5 条，每条都是未来 1—7 天可验证的事件或数据。

## ⑧ One Chart
插入：![Daily Market Pulse](assets/chart.svg)
再用 2—3 句话解释图表，但不要把相关性写成因果。

## ⑨ Quote of the Day
使用下面的双语格式，不要改写英文原句，不要只保留中文：
{quote_block}

## ⑩ Action Items｜今天值得思考什么
固定 5 条，以“关注/验证/比较/追踪/思考”等动词开头，不给证券买卖建议。

## 信息边界
说明来源覆盖、时效、市场数据最近交易日等限制。

## Sources
按 AI、商业/宏观分组列出实际使用过的来源链接。正文关键事实必须标 [A1] 或 [B1] 等来源编号。

规则：
- 不得补充材料外的新闻事实；未知就写未知。
- 新闻来源可能是二手聚合，重要判断需提醒读者回到原文验证。
- 不模仿任何具体作者的独特文风，不声称代表任何机构。
- 不提供个性化投资建议。

AI SOURCES:
{numbered_sources(ai_items, "A")}

BUSINESS AND MACRO SOURCES:
{numbered_sources(industry_items, "B")}
"""


def numbered_sources(items: List[Dict[str, str]], prefix: str) -> str:
    chunks = []
    for index, item in enumerate(items, 1):
        chunks.append(
            f"[{prefix}{index}] {item['title']}\n来源: {item['source']}\n时间: {item['published'] or '未提供'}\n"
            f"链接: {item['url']}\n摘要: {item['summary'][:650] or '无摘要'}"
        )
    return "\n\n".join(chunks) or "没有抓取到可用来源。"


def fallback_dios(
    date_label: str,
    ai_items: List[Dict[str, str]],
    industry_items: List[Dict[str, str]],
    markets: List[Dict[str, object]],
    quote: tuple,
) -> str:
    ai_headlines = ai_items[:3]
    business = industry_items[:4]
    lines = [
        "# Daily Intelligence",
        "",
        f"> {date_label}",
        "",
        "## Today’s Thesis｜今日一句话",
        "",
        "当前为基础版：信息已归档，但深度机制分析需要配置模型 API 后生成。",
        "",
        "## ① Executive Summary｜30 秒",
        "",
        f"- AI：{ai_headlines[0]['title'] if ai_headlines else '暂无可靠更新'}",
        f"- 商业：{business[0]['title'] if business else '暂无可靠更新'}",
        "- 宏观：先观察市场价格与后续数据是否支持当前叙事，避免从单日波动推导长期趋势。",
        "",
        "## ② AI Daily",
        "",
    ]
    for index, item in enumerate(ai_headlines, 1):
        lines.extend(
            [
                f"### {index}. {item['title']} [A{index}]",
                "",
                "#### What Happened",
                "",
                item["summary"][:350] or "来源未提供摘要。",
                "",
                "#### Why It Matters",
                "",
                "需要结合原始报道与后续产品、收入或采用数据验证其重要性。",
                "",
                "#### Second-order Effect",
                "",
                "事件 → 参与者调整资源配置 → 行业竞争与采用速度可能变化。",
                "",
            ]
        )
    lines.extend(["## ③ Business Daily", ""])
    for index, item in enumerate(business, 1):
        lines.extend([f"### {item['title']} [B{index}]", "", item["summary"][:350] or "来源未提供摘要。", ""])
    lines.extend(
        [
            "## ④ Macro Observation｜机制分析",
            "",
            "基础版不对新闻之间建立未经验证的因果关系。建议依次检查：增长与需求 → 通胀与成本 → 利率与流动性 → 资本流向 → 企业投资。",
            "",
            "## ⑤ Signal Dashboard",
            "",
            market_markdown(markets),
            "",
            "## ⑥ Deep Insight",
            "",
            "深度分析待模型综合。核心原则是：新闻的长期价值不在事件本身，而在它是否改变了约束条件、激励机制和资源配置方向。",
            "",
            "## ⑦ Tomorrow Watch",
            "",
            "- 验证 AI 产品发布是否转化为真实采用。",
            "- 关注主要央行与监管机构的新表态。",
            "- 追踪芯片、数据中心和能源供应链信号。",
            "- 比较市场价格变化与基本面信息是否一致。",
            "- 观察今日核心叙事是否出现反证。",
            "",
            "## ⑧ One Chart",
            "",
            "![Daily Market Pulse](assets/chart.svg)",
            "",
            "图表展示最近交易日价格变化，仅用于发现值得进一步研究的异常，不代表因果关系。",
            "",
            "## ⑨ Quote of the Day",
            "",
            quote_markdown(quote).replace("## ⑨ Quote of the Day\n\n", ""),
            "",
            "## ⑩ Action Items｜今天值得思考什么",
            "",
            "- 关注 AI 能力提升是否变成客户付费。",
            "- 验证资本开支与收入增长是否匹配。",
            "- 比较行业叙事与实际订单、库存和招聘。",
            "- 追踪美元、利率与风险资产之间的联动。",
            "- 思考什么事实会推翻今天的核心判断。",
            "",
            "## 信息边界",
            "",
            "本期为无模型基础版；聚合新闻可能存在延迟或二手转述，市场数据为最近可得交易日。",
            "",
            "## Sources",
            "",
            "### AI",
            "",
        ]
    )
    lines.extend([f"- [A{i}：{x['title']}]({x['url']})" for i, x in enumerate(ai_items, 1)])
    lines.extend(["", "### 商业与宏观", ""])
    lines.extend([f"- [B{i}：{x['title']}]({x['url']})" for i, x in enumerate(industry_items, 1)])
    return "\n".join(lines) + "\n"


def extract_section(markdown: str, heading: str) -> str:
    heading_pattern = re.escape(heading).replace("Today’s", r"Today(?:’|')s")
    pattern = rf"##\s+{heading_pattern}[^\n]*\n+(.*?)(?=\n##\s|\Z)"
    match = re.search(pattern, markdown, flags=re.S)
    if not match:
        return ""
    return re.sub(r"\s+", " ", match.group(1)).strip()[:500]


def ensure_source_links(
    markdown: str, ai_items: List[Dict[str, str]], industry_items: List[Dict[str, str]]
) -> str:
    """Replace model-written source prose with canonical clickable source links."""
    used_ai = {int(x) for x in re.findall(r"\[A(\d+)\]", markdown)}
    used_business = {int(x) for x in re.findall(r"\[B(\d+)\]", markdown)}
    source_lines = ["## Sources", "", "### AI", ""]
    for index, item in enumerate(ai_items, 1):
        if index in used_ai:
            source_lines.append(f"- [A{index}：{item['title']}]({item['url']}) — {item['source']}")
    if not used_ai:
        source_lines.append("- 本期正文未引用 AI 来源。")
    source_lines.extend(["", "### Business & Macro", ""])
    for index, item in enumerate(industry_items, 1):
        if index in used_business:
            source_lines.append(f"- [B{index}：{item['title']}]({item['url']}) — {item['source']}")
    if not used_business:
        source_lines.append("- 本期正文未引用商业或宏观来源。")
    canonical = "\n".join(source_lines).strip() + "\n"
    if re.search(r"\n## Sources\b", markdown):
        return re.sub(r"\n## Sources\b.*\Z", "\n\n" + canonical, markdown, flags=re.S)
    return markdown.rstrip() + "\n\n" + canonical


def enforce_model_report(
    markdown: str,
    model: str,
    ai_items: List[Dict[str, str]],
    industry_items: List[Dict[str, str]],
    quote: tuple,
) -> str:
    markdown = markdown.replace("## Today's Thesis", "## Today’s Thesis")
    deep_match = re.search(r"(## ⑥ Deep Insight[^\n]*\n)(.*?)(?=\n## )", markdown, flags=re.S)
    if deep_match:
        deep_chars = len(re.sub(r"[\s#*_`>\[\]()]|https?://\S+", "", deep_match.group(2)))
        if deep_chars < 600:
            expanded = core.call_openai(
                "请扩写下面的 Deep Insight，使正文达到 700—900 个汉字。保留原主题和已有来源编号，"
                "不要新增事实或来源；必须包含：核心机制、至少两层二阶影响、反方观点、证伪条件。"
                "只输出正文，不输出标题或代码围栏。\n\n原文：\n" + deep_match.group(2),
                model,
            )
            markdown = markdown[: deep_match.start(2)] + expanded.strip() + "\n" + markdown[deep_match.end(2) :]
    markdown = ensure_quote_section(markdown, quote)
    return ensure_source_links(markdown, ai_items, industry_items)


def rebuild_library(root: Path) -> None:
    records = []
    for data_path in sorted(root.glob("*/*/*/data.json"), reverse=True):
        try:
            records.append(json.loads(data_path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    (root / "search-index.json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    weekdays = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

    def weekday_for(date_text: str) -> str:
        try:
            return weekdays[dt.date.fromisoformat(date_text).weekday()]
        except ValueError:
            return ""

    def short_summary(text: str) -> str:
        cleaned = re.sub(r"\s+", " ", text or "").strip()
        return cleaned[:280] + ("…" if len(cleaned) > 280 else "")

    grouped: Dict[str, List[Dict[str, object]]] = {}
    for item in records:
        month = str(item.get("date", ""))[:7] or "Unknown"
        grouped.setdefault(month, []).append(item)

    month_sections = []
    for month, items in grouped.items():
        cards = "".join(
            f"""<article class="issue-card">
  <a class="date-box" href="{html.escape(item.get("relative_html", "#"))}">
    <span>{html.escape(str(item.get("date", ""))[8:10])}</span>
    <small>{html.escape(weekday_for(str(item.get("date", ""))))}</small>
  </a>
  <div class="issue-body">
    <div class="issue-meta">{html.escape(str(item.get("date", "")))} · Daily Intelligence</div>
    <h2><a href="{html.escape(item.get("relative_html", "#"))}">{html.escape(item.get("thesis") or "Daily Intelligence")}</a></h2>
    <p>{html.escape(short_summary(item.get("summary", "")))}</p>
    <a class="read-link" href="{html.escape(item.get("relative_html", "#"))}">阅读全文 →</a>
  </div>
</article>"""
            for item in items
        )
        month_sections.append(f'<section class="month-group"><h3>{html.escape(month)}</h3>{cards}</section>')
    archive_html = "\n".join(month_sections) or '<p class="empty">还没有生成任何 Daily Intelligence。</p>'
    latest = records[0] if records else {}
    oldest_date = records[-1].get("date") if records else "—"
    newest_date = records[0].get("date") if records else "—"
    latest_url = html.escape(latest.get("relative_html", "#"))
    page = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Daily Intelligence OS</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:radial-gradient(circle at top left,#13243d 0,#08111f 42%,#050912 100%);color:#e5edf8;font:16px/1.65 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC",sans-serif}}
main{{max-width:1100px;margin:auto;padding:64px 24px 90px}}.eyebrow{{color:#67d4ff;font-size:.78rem;font-weight:700;letter-spacing:.18em;text-transform:uppercase}}h1{{font-size:clamp(2.7rem,7vw,5.6rem);line-height:.95;margin:.18em 0 .25em}}.sub{{color:#a9b7c9;max-width:720px;font-size:1.05rem}}
.topbar{{display:flex;gap:14px;flex-wrap:wrap;margin:32px 0}}.stat,.latest{{border:1px solid #223a5c;background:rgba(13,28,48,.78);border-radius:18px;padding:16px 18px;min-width:160px;box-shadow:0 18px 60px rgba(0,0,0,.18)}}.stat strong{{display:block;font-size:1.35rem;color:#fff}}.stat span,.latest span{{color:#91a4bd;font-size:.9rem}}.latest{{flex:1;min-width:260px}}.latest a{{display:block;color:#fff;text-decoration:none;font-size:1.05rem;font-weight:700;margin-top:4px}}.latest a:hover{{color:#67d4ff}}
.search-wrap{{position:sticky;top:0;z-index:5;padding:16px 0;background:linear-gradient(180deg,rgba(8,17,31,.96),rgba(8,17,31,.78))}}input{{width:100%;padding:17px 20px;border-radius:14px;border:1px solid #29405f;background:#101e31;color:white;font-size:17px;outline:none}}input:focus{{border-color:#67d4ff;box-shadow:0 0 0 4px rgba(103,212,255,.12)}}
.month-group{{margin-top:34px}}h3{{margin:0 0 14px;color:#67d4ff;font-size:1rem;letter-spacing:.08em}}.issue-card{{display:grid;grid-template-columns:92px 1fr;gap:22px;padding:26px 0;border-top:1px solid #22334b}}.date-box{{height:92px;border:1px solid #29405f;border-radius:18px;background:linear-gradient(180deg,#152742,#0e1b2e);display:flex;flex-direction:column;align-items:center;justify-content:center;text-decoration:none;color:#fff}}.date-box span{{font-size:2.15rem;font-weight:800;line-height:1}}.date-box small{{margin-top:6px;color:#91a4bd}}.issue-meta{{color:#91a4bd;font-size:.92rem}}h2{{font-size:clamp(1.25rem,3vw,1.75rem);line-height:1.28;margin:.25rem 0 .5rem}}a{{color:#f4f8ff;text-decoration:none}}a:hover{{color:#67d4ff}}p{{color:#a9b7c9;margin:.4rem 0 1rem}}.read-link{{color:#67d4ff;font-weight:700}}.empty,.no-results{{color:#91a4bd;border-top:1px solid #22334b;padding:26px 0}}mark{{background:rgba(103,212,255,.16);color:#dff7ff;border-radius:4px;padding:0 2px}}
@media(max-width:650px){{main{{padding:42px 18px 70px}}.issue-card{{grid-template-columns:1fr;gap:12px}}.date-box{{width:92px}}.search-wrap{{position:static}}}}
</style></head><body><main><div class="eyebrow">Personal Knowledge Base</div><h1>Daily Intelligence OS</h1>
<p class="sub">AI、科技、商业与宏观的每日情报归档。这里是总入口：按日期浏览今天及以前的所有 Daily Intelligence，也可以搜索公司、行业、趋势或观点。</p>
<div class="topbar">
  <div class="stat"><strong>{len(records)}</strong><span>total issues</span></div>
  <div class="stat"><strong>{html.escape(str(newest_date))}</strong><span>latest date</span></div>
  <div class="stat"><strong>{html.escape(str(oldest_date))}</strong><span>archive starts</span></div>
  <div class="latest"><span>Latest Intelligence</span><a href="{latest_url}">{html.escape(latest.get("thesis") or "打开最新一期")}</a></div>
</div>
<div class="search-wrap"><input id="q" type="search" placeholder="搜索日期 / AI Agent / 能源 / 美元 / NVIDIA / 医疗…" autofocus></div>
<section id="results">{archive_html}</section></main><script>
const initial=document.getElementById('results').innerHTML;
const qInput=document.getElementById('q');
function esc(s){{return String(s||'').replace(/[&<>"']/g,m=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[m]));}}
function weekday(date){{try{{return new Date(date+'T00:00:00').toLocaleDateString('en-US',{{weekday:'long'}})}}catch(e){{return ''}}}}
function summary(text){{text=String(text||'').replace(/\\s+/g,' ').trim();return text.length>280?text.slice(0,280)+'…':text;}}
function card(x){{
 const day=String(x.date||'').slice(8,10);
 return `<article class="issue-card">
  <a class="date-box" href="${{esc(x.relative_html||'#')}}"><span>${{esc(day)}}</span><small>${{esc(weekday(x.date))}}</small></a>
  <div class="issue-body"><div class="issue-meta">${{esc(x.date)}} · Daily Intelligence</div>
  <h2><a href="${{esc(x.relative_html||'#')}}">${{esc(x.thesis||'Daily Intelligence')}}</a></h2>
  <p>${{esc(summary(x.summary))}}</p><a class="read-link" href="${{esc(x.relative_html||'#')}}">阅读全文 →</a></div>
 </article>`;
}}
qInput.addEventListener('input',async e=>{{
 const q=e.target.value.trim().toLowerCase();
 if(!q){{document.getElementById('results').innerHTML=initial;return}}
 const data=await fetch('search-index.json').then(r=>r.json());
 const hits=data.filter(x=>JSON.stringify(x).toLowerCase().includes(q)).slice(0,80);
 document.getElementById('results').innerHTML=hits.length?`<section class="month-group"><h3>Search Results · ${{hits.length}}</h3>${{hits.map(card).join('')}}</section>`:'<p class="no-results">没有匹配结果。</p>';
}});
</script></body></html>"""
    (root / "index.html").write_text(page, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Daily Intelligence OS")
    parser.add_argument("--date", help="归档日期 YYYY-MM-DD，默认今天")
    parser.add_argument(
        "--archive-root",
        type=Path,
        help="归档根目录；GitHub Actions 使用仓库根目录",
    )
    args = parser.parse_args()
    core.load_dotenv(ROOT / ".env")
    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    report_date = dt.date.fromisoformat(args.date) if args.date else dt.date.today()
    date_text = f"{report_date.isoformat()}｜{report_date.strftime('%A')}"
    archive_root = (
        args.archive_root.resolve()
        if args.archive_root
        else ROOT / config.get("dios_output_dir", "Daily-Intelligence")
    )
    day_dir = archive_root / f"{report_date:%Y}" / f"{report_date:%m}" / report_date.isoformat()
    assets_dir = day_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)

    hours = int(config.get("lookback_hours", 48))
    limit = int(config.get("max_items_per_report", 24))
    ai_items = core.collect_sources(config["feeds"]["ai"], hours, limit)
    industry_items = core.collect_sources(config["feeds"]["industry"], hours, limit)
    markets = [fetch_market(name, symbol) for name, symbol in config["market_symbols"].items()]
    for item in markets:
        item["interpretation"] = market_interpretation(item)

    quote = choose_quote(report_date, archive_root)
    model = os.environ.get("OPENAI_MODEL", config.get("model", "gpt-5.6-sol"))
    markdown = core.call_openai(dios_prompt(date_text, ai_items, industry_items, markets, quote), model)
    markdown = enforce_model_report(markdown, model, ai_items, industry_items, quote)

    make_chart_svg(markets, assets_dir / "chart.svg", report_date.isoformat())
    make_cover_png(assets_dir / "cover.png", report_date.isoformat())
    md_path = day_dir / "Daily Intelligence.md"
    html_path = day_dir / "Daily Intelligence.html"
    md_path.write_text(markdown.strip() + "\n", encoding="utf-8")
    html_path.write_text(core.markdown_to_html(markdown, f"{report_date} Daily Intelligence"), encoding="utf-8")

    thesis = extract_section(markdown, "Today’s Thesis")
    summary = extract_section(markdown, "① Executive Summary")
    record = {
        "schema_version": 1,
        "date": report_date.isoformat(),
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "model": model,
        "mode": "model",
        "thesis": thesis,
        "summary": summary,
        "relative_html": f"{report_date:%Y}/{report_date:%m}/{report_date.isoformat()}/Daily%20Intelligence.html",
        "markets": markets,
        "topics": ["AI", "technology", "business", "macro"],
        "quote": {"english": quote[0], "speaker": quote[1], "chinese": quote[2]},
        "sources": {"ai": ai_items, "business_macro": industry_items},
        "search_text": re.sub(r"[#>*_`|!-]", " ", markdown),
    }
    (day_dir / "data.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    rebuild_library(archive_root)
    (archive_root / "latest.html").write_text(
        f'<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="0; url={record["relative_html"]}">',
        encoding="utf-8",
    )
    print(f"完成：{day_dir}")
    print(f"AI 来源 {len(ai_items)}；商业/宏观来源 {len(industry_items)}；市场指标 {len(markets)}；模式：{record['mode']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
