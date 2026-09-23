# 首页自动更新

`homepage-summaries.json` 是首页综合摘要的权威内容；`homepage_renderer.py` 负责排版，`editorial_summaries.py` 校验来源覆盖与内容是否过期。脚本只读本地归档，不联网或调用 API，不自动编写或拼接总结。

每次日报或历史补编完成后、创建本地提交前，先由 Codex 阅读内容并更新 `homepage-summaries.json`：新日报需要短标题、导读和三条重点；周月总结综合对应期间全部已有日报，写核心判断、三至五条事件分析和后续观察。保留事实、推断及计划的差别，典故来自已核实原文，不强行添加。周期未变化且来源未变化时复用已有合格总结。

每条重点用 `source_dates` 关联原文；日卡及周期卡的 `source_hashes` 必须覆盖该日或该周期的全部归档 Markdown（SHA-256）。指纹只检测改动，不证明稿件质量：新增补稿或源文修订后必须重新阅读相关内容、调整分析，再更新指纹。顶层 `generated_at` 使用真实编写时间和时区。缺失日报必须明确说明 `coverage_note`。

随后用项目 Python 3.11+ 执行：

```
python3 -B automation/refresh_homepage.py --write
python3 -B automation/refresh_homepage.py --check
```

摘要文件、首页与该次日报及直接相关索引一同提交。展示以最大报道日期为锚点：最近 7 个日历日、此前 4 个完整自然周、此前 3 个完整自然月。补历史稿不改变锚点。周月卡片不显示日期范围，内部仍保留 start/end；按由近到远标示上周、上月及往期。无数据的日期不伪造，覆盖不足明确标示。不能用关键词频次、抽样拼接或模板段落替代综合判断。

代码改版独立提交。本机 `scripts/server/artifacts.py` 保持与仓库渲染器同步；`build_bundle` 中的临时首页仍必须经过上述正式刷新才能提交。不得直接发布未经摘要校验的暂存首页。

独立发布器在刷新远端、安全祖先检查和实际推送之间执行只读校验；不一致时停止，不在发布阶段修改文件或创建提交。通过 `PUBLISH_PYTHON_BIN` 指定项目 Python。无待推提交的周期检查不生成或改写内容。

运行回归测试：`python3 -B -m unittest discover -s automation -p test_refresh_homepage.py`。
