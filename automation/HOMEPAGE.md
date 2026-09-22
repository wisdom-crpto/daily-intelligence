# 首页自动更新

`homepage_renderer.py` 是已发布首页的权威渲染逻辑。仅使用归档日报，不联网或调用 API。

每次日报或历史补编完成后、创建本地提交前，用项目 Python 3.11+ 执行：

```
python3 -B automation/refresh_homepage.py --write
python3 -B automation/refresh_homepage.py --check
```

首页与该次日报及直接相关索引一同提交。展示以最大报道日期为锚点：最近 7 个日历日、此前 4 个完整自然周、此前 3 个完整自然月。补历史稿不改变锚点。无数据的日期不伪造，覆盖不足明确标示。周期回顾为主题和日报摘要摘选，不冒充独立研究报告。

独立发布器在刷新远端、安全祖先检查和实际推送之间执行只读校验；不一致时停止，不在发布阶段修改文件或创建提交。通过 `PUBLISH_PYTHON_BIN` 指定项目 Python。无待推提交的周期检查不生成或改写内容。

运行回归测试：`python3 -B -m unittest discover -s automation -p test_refresh_homepage.py`。
