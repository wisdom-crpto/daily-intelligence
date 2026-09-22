<!-- PROJECTS-CONTRACT:BEGIN -->
## Inherited workspace contract

This project inherits the current contract from `/Users/ykc/Documents/project/PROJECT-CONTRACT.md`.

Before any write, run:

`/Users/ykc/Documents/project/.project-governance/tools/sync-project-contract.sh --project <this-project>`

Then read the local project rules. Local rules may strengthen or specialize the parent contract, but may not silently weaken raw immutability, unique current pointers, explicit L2 decisions, L1 communication routing, or controlled L3 handoff.
<!-- PROJECTS-CONTRACT:END -->

# Daily Intelligence 发布仓库规则

本仓库是公开静态日报的发布面。权威日报内容位于按日期划分的 `YYYY/MM/YYYY-MM-DD/` 目录；`index.html`、`latest.html` 和 `search-index.json` 是直接关联的入口与索引。

每次写入前，先运行父工作区的 contract sync，然后阅读 `CURRENT.md`、本文件和 `.project-profile.yaml`。只允许 Codex 基于已完成的完整稿更新日报及其直接索引。不得运行 `automation/dios.py`、`automation/generate.py` 或 GitHub Actions 的 API 生成入口；发布只由独立的本地发布器处理。

每个报道日期单独验证、单独创建本地提交；日报提交不得混入自动化、治理或其他日期的修改。历史补稿不得让首页、`latest.html` 或搜索索引回退到较早日期。发现工作区脏、分叉、目录残缺或索引错误时，停止写入并报告。
