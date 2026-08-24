# AI Agent 论文搜索、下载与 Zotero Agentibility 适配研究备忘录

> 访问日期：2026-08-23（来源页面均为本次核查时访问；外部项目能力应以锁定版本复核）。

## 结论先行

需要区分**当前发布能力**与已接受的**目标控制面**：当前
`zotero-agentibility` 已实现本地 Zotero 的读取、语义检索、来源核验、
本地 PDF/EPUB `add file`、`resolve`，以及“已审阅 Markdown”的显式导入/采纳；
当前 `za-cli` 还没有 identifier/URL/RIS/BibTeX ingest、PDF 下载或通用 duplicate/merge 命令。
已接受的下一步不是另造一个下载器，而是把 Zotero 原生能力放进 broad
native-first fixed-operation CLI；命令是否发布仍以 Click command tree 为准。

PDF discovery、PDF download、校园认证、cookies，以及“是否下载”这一决策
不属于 core。它们由 Human 或 browser Skill 完成；core 只接收用户选定的
local file，或已经存在于 Zotero 的 item/attachment。这样既保留浏览器和机构
许可的真实边界，也不把登录态、版权判断或抓取策略变成 bridge 的隐含权限。

core 可以联网，但范围更窄：已知 identifier、URL 或结构化 metadata import
可以调用 Zotero 的 native translator 路径获取**元数据**，并且必须使用
`saveAttachments=false`。这类联网不负责发现或下载 PDF，也不接收论文全文。
需要字节时，Human/browser Skill 先把文件放到本地，之后 core 的 `add file`
负责复制到 Zotero storage、保留源文件、默认 native recognize，或
在显式 `--parent` 时跳过 recognize。

## 1. 当前仓库与目标控制面

依据 [README.md](../../README.md)、[docs/cli.md](../cli.md)、
[docs/ingest.md](../ingest.md)、[`skills/research-with-zotero/SKILL.md`](../../skills/research-with-zotero/SKILL.md)
与 [`skills/research-with-zotero/references/mutations.md`](../../skills/research-with-zotero/references/mutations.md)：

- **当前已实现：** `lookup`、`source`、`read`、`find`、`search`、Collection
  浏览 Session、索引维护；本地 `add file`；`resolve ATTACHMENT_KEY`；`fulltext audit/adopt/import/migrate`。
- **当前 PDF 边界：** `add file` 接受 Human/browser Skill 已选择的本地 PDF/EPUB，
  由 Zotero 复制并默认识别；`resolve` 处理已经在 Zotero 中的孤立文档。二者都不下载
  PDF。`fulltext import` 接受审阅过的本地 `.md`，原样复制为 `fulltext.md`。
- **已接受的扩展：** item/attachment/Collection/tag/note/duplicate/
  saved-search/add/import/export/sync 等资源组都通过固定、校验过的 native
  operation 进入 Zotero；read-only SQLite 只能加速读取，live Zotero 才是写权威。
- **身份与重复：** 精确 Item Key、规范化 Strong Identifier 或相同源文件
  SHA-256 才能复用；相似标题、作者、年份只产生 fuzzy candidate。相同 Strong
  Identifier 但不同 Source 必须 rollback 新导入并报告 conflict；fuzzy candidate
  可以在策略允许时 add 并 warning，但绝不 auto merge。合并必须由 caller 选择
  keeper 并显式确认。
- **安全边界：** 不写 `zotero.sqlite`，不执行任意 Zotero JavaScript，不写
  group library，不永久删除；PDF acquisition 和 browser cookies 也不进入 core。

因此，“当前版本是否支持 PDF 导入、去重/合并”的直接回答是：**支持用户选择的
本地 PDF/EPUB 入库和精确复用；不负责 PDF 下载，也还没有通用 duplicate merge
命令。** 已存在 PDF 的识别与 Markdown Full Text 导入/采纳继续可用。目标控制面的可执行矩阵见
[docs/capabilities.md](../capabilities.md)。

## 2. 可借用的外部工具

### 2.1 `cli-anything-zotero`

官方 README/命令文档列出：

- `add doi DOI --fetch-pdf`、`add arxiv ID`、`add file PATH`、`add bibtex FILE`；
  底层还有 DOI、RIS/BibTeX/JSON 导入。
- `item attach ITEM_KEY FILE`、`item find-pdf ITEM_KEY`、`item fetch-pdf ITEM_KEY
  --sources zotero,unpaywall,arxiv`，以及按 Collection 批量找 PDF。
- 搜索/导出 BibTeX、RIS、CSL-JSON 等；还包括 metadata、tag、note、sync、
  duplicate/merge 相关的广泛写操作。
- 依赖 Zotero Desktop 与 JS Bridge；README 还暴露 `zotero-cli js "..."` 任意
  JavaScript 执行能力。

它说明了 broad capability surface 的用户价值，但不是本项目的后端：特权 JS
Bridge、PDF fetch 和自动写路径违反本项目的固定操作、人工确认、审计与
My Library 约束。它只作为能力和风险的参考；本项目的目标实现必须把每个写意图
映射成自己的 schema-validated native operation，不能把任意 JS 带进来。

许可证：Apache-2.0。风险：Bridge 是本机特权面；任何把模型输入直接拼进
`zotero-cli js` 的方案都等价于给 Agent 数据库写权限。PDF 自动抓取还可能
触及出版商 robots、访问条款和版权。

来源：
- https://github.com/PiaoyangGuohai1/cli-anything-zotero
- https://github.com/PiaoyangGuohai1/cli-anything-zotero/blob/main/docs/COMMANDS.md
- https://github.com/PiaoyangGuohai1/cli-anything-zotero/blob/main/cli_anything/zotero/core/pdf_fetch.py
- https://github.com/PiaoyangGuohai1/cli-anything-zotero/blob/main/LICENSE

### 2.2 `zotero-cli-ai`（命令 `zot`）

官方 README 描述的是“SQLite 读取 + Zotero Web API 写入”：本地 SQLite 读取
无需 API key、离线且快；写入使用 Web API；支持 PDF 全文提取缓存、按库/Collection
的排序检索、JSON envelope、`--dry-run`、幂等键和 MCP server。示例包括
`zot add --doi`、`zot search`、`zot read`、`zot export`。

它适合做只读检索或独立 Web API 工作流，但不应接入当前项目：直接读 SQLite
和 Web API 写入绕开了 Agentibility 的 Extension bridge、My Library 限制、
写锁、审计和“不能直接写数据库”的契约；Web API 还需要用户管理 API key。
其开源许可证为 AGPL-3.0-or-later，另有商业许可证；若集成代码或服务，需先
解决许可证义务。

来源：
- https://github.com/Agents365-ai/zotero-cli-ai
- https://agents365-ai.github.io/zotero-cli-ai/guide/pdf/
- https://github.com/Agents365-ai/zotero-cli-ai/blob/main/LICENSE
- https://github.com/Agents365-ai/zotero-cli-ai/blob/main/LICENSE-COMMERCIAL

### 2.3 `save_to_zotero`

官方 README 支持本地 PDF 和网页 URL。网页路径用 Playwright 渲染页面、展开
动态内容并生成 PDF，再通过 Zotero API/Connector API 入库；也有 metadata、
Collection、tag 支持。`ZOTERO_BROWSER_USER_DATA_DIR` 可以复用 Chromium
cookies/login session，作者同时警告不要并发使用该 browser profile。

这正说明它应属于 Human/browser Skill，而不是 core：cookies 不是授权绕过，
没有有效会话、机构许可或可下载响应时，工具不能合法取得付费 PDF。复用真实
登录态还会把 bearer-like cookies 暴露给自动化进程；反检测抓取也不应默认为
Agent 行为。许可证：AGPLv3。

来源：https://github.com/thiswillbeyourgithub/save_to_zotero（含本地 PDF、Connector、
browser profile、许可证说明）。

## 3. Connector、校园代理与 PDF 获取边界

Zotero Connector 能在浏览器中保存带元数据的网页/数据库条目，也会提示导入
RIS、BibTeX/Refer 文件；它能检测机构代理，并在用户已通过代理访问站点后把
匹配 URL 重定向到代理域名。

这解决的是**浏览器访问链路**，不是给无头 HTTP client、Unpaywall 或 Agent
授予订阅权限。Connector 不应把 cookies 导出给其他工具；Safari 也不支持
Zotero 的代理重定向功能（官方偏好设置有说明）。最稳妥的付费出版商流程是：
用户在浏览器完成校园 SSO/代理登录，确认机构许可允许保存，再由 Connector
或 Zotero UI 保存；Agent/core 只接收用户选定的本地文件。

因此下列事项明确归 Human/browser Skill：

| 事项 | core 行为 |
| --- | --- |
| PDF discovery（DOI、标题、OA location 的搜索） | 不提供下载器；可接收用户选定的结果或 metadata-only URL。 |
| PDF download 与是否下载的决定 | 不自动执行；Human/browser Skill 根据许可、版权和用户意图取得 local file。 |
| 校园 SSO、代理、cookies、paywall | 不读取、不保存、不转发；浏览器维护认证边界。 |
| PDF-to-Markdown/OCR | 外部用户选定工具；core 只接收审阅后的本地 Markdown Full Text。 |

## 4. OA 元数据与 metadata-only 网络路径

Unpaywall、OpenAlex、Semantic Scholar 可用于 Human/browser Skill 的发现工作：

- **Unpaywall：** DOI REST API 返回 OA 状态、`best_oa_location`、版本、许可证
  和可用位置；它是发现服务，不保证每个 URL 长期可用或满足目标用途。
- **OpenAlex：** Work API 的 `open_access`、`best_oa_location` 和 `locations`
  提供 OA 状态、来源和 PDF/landing-page 信息；不是版权许可判定器。
- **Semantic Scholar：** Academic Graph API 的 `openAccessPdf`、`isOpenAccess`
  可用于发现公开 PDF；字段缺失不代表论文一定付费。

这些服务不能把 PDF 下载、再分发或机构权限授予 core。core 可以接受已知
identifier/URL/结构化 metadata import，并在未来的 `add identifier`、`add url`
或 `import` fixed operation 中调用 Zotero translator 获取元数据；这类请求
必须是 metadata-only、明确报告外部服务，并使用 `saveAttachments=false`。
它们不能携带或返回论文全文，也不能偷偷下载附件。

## 5. Core 适配 checkpoint

1. **获取由外部负责。** Human 或 browser Skill 处理发现、下载、校园认证、
   cookies 和“是否下载”，把用户选择的文件放在本地，或指出已有 Zotero item。
2. **本地文件进入 native intake。** 计划中的 `add file` 用
   `Zotero.Attachments.importFromFile` 复制进 Zotero storage，保留源文件；默认
   native recognize，`--parent` 明确跳过 recognize；精确 hash/Strong Identifier
   才复用；同强标识不同 Source rollback+conflict；fuzzy candidate add+warn；
   指定 Collection Key 时补 Membership，否则保持 Unfiled；选定 Source PDF 标 `za-cli:pdf`；第一阶段只做
   My Library。
3. **元数据路径保持无附件。** identifier、URL、RIS/BibTeX/CSL-JSON metadata
   import 可以联网，但 native translator 使用 `saveAttachments=false`；任何
   PDF 字节仍由外部获取并以 local file 进入步骤 2。
4. **写权威保持在 Zotero。** read-only SQLite 只生成候选或索引提示；Extension
   通过固定 schema、live reload、写锁、事务、审计和可恢复 Trash 执行 mutation。
5. **重复处理显式化。** 精确身份可复用；fuzzy 只警告；duplicate merge 先
   preview，由 caller 选择 keeper 并确认，不自动合并。

这条路线把项目定位为 broad native-first fixed-operation control surface，
同时保留清楚的 acquisition、认证和数据权威边界。命令和里程碑详见 [docs/capabilities.md](../capabilities.md)、[docs/cli.md](../cli.md)、
[docs/bridge.md](../bridge.md) 与 [docs/ingest.md](../ingest.md)。

## 6. Zotero native recognition 适配参考

`docs/research/zotero-metadata-recognition.md` 记录了 PDF/EPUB 原生 recognition、
`Zotero.Utilities.extractIdentifiers()` 和 `Zotero.Translate.Search` 的来源与
风险。要点是：不要把 Markdown 伪装成 PDF 送入私有 recognizer；保留原始 local
PDF/EPUB 让 Zotero 自己识别，之后再把 reviewed Markdown 作为 Full Text child
attachment。identifier fallback 只接受一个可验证的 Strong Identifier，不用
标题相似度偷偷选 parent。
