# Daily Intelligence 发布仓库当前状态

这是 Daily Intelligence 的公开静态发布仓库，当前分支为 `main`。日报由本机 Codex 完成完整来源、时效与内容验证后生成；独立发布器只对干净工作区中的已有本地提交执行远端刷新、安全祖先检查和普通推送。

本机现行任务为每日 07:00（Asia/Shanghai）的 `daily-intelligence` heartbeat；`com.wisdom.daily-news-publish` 按提交事件、登录/重新载入、每五分钟及原固定补查时点检查待推提交。2026-10-19 已核对自动化为 ACTIVE，发布器日志记录 10 月 18 日成功推送；此前“尚未切换、保持暂停”的迁移说明已经失效。

进入路径：`AGENTS.md` → `.project-profile.yaml` → 本文件。生成前后运行项目根目录的 `scripts/check_daily_gaps.py`；完整执行提示词位于运行项目的 `L3-handoff/automation-prompt.md`。研究需完成官方入口补查与原文核验，保留 AI 和商业/宏观各两条近期一手来源门槛，不能用周末常规统计未发布推断全球无新来源。生成者不运行 API 生成入口、不直接 fetch 或 push。

2026-10-20 用户授权全站界面重构：首页、日周月卡片与118期阅读壳统一，周月长文在可横滑的独立阅读层显示，摘要清晰表达沿用最新规则。界面唯一实现为 `automation/homepage_renderer.py`；规则见 `automation/HOMEPAGE.md`。每日新稿自动继承，发布机制保持原入口。
