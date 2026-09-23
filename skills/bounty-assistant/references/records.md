# 数据记录与兼容已有 LIST

个人数据与技能指令分开。数据目录包含 `profile.json`（身份/偏好）、`ledger.json`（结构化事实）、作品及邮件归档；用户可继续使用已有 Markdown LIST。`config.local.json` 只存个人数据目录的位置，不存密码、令牌或身份资料。

## 首次使用

先按用户给定路径、技能本地配置、当前项目 `outputs/bounty-data` 和已有LIST寻找记录；找到旧记录则读取/迁移，不创建空记录覆盖。确无旧记录且需要持久保存本次工作时，默认使用当前工作目录的 `outputs/bounty-data`，告知实际位置；也可用用户指定的目录。

```bash
python3 <本技能目录>/scripts/init_state.py --state-dir <个人数据目录>
```

脚本需要 Python 3.9+；日期脚本还需要可用的 IANA 时区数据库。初始化只创建空的 `profile.json`、`ledger.json`，默认最终投稿确认、按需资料收集及未启用跟进，不写个人信息、不创建自动化。只要任一目标文件已存在就拒绝覆盖；半完整旧目录先检查缺项再按事实修复，不用删除重建来通过初始化。

跨任务使用同一目录时，可在技能目录本地保存 `config.local.json`，字段为 `schema_version: 1` 和 `state_directory: <真实绝对路径>`。仅在已具备目录写权限时写入，已有配置先读取；没有写权限时使用明确的数据路径或当前项目默认目录即可。公共发布排除此本地配置、整个个人数据目录和邮件附件。

profile 的最小结构由初始化器提供；按用户实际输入逐步加 name、phone、email、unit 等字段。保持 `submission_policy: require_final_review`，除非用户明确改变确认要求。初始化的新空台账与旧台账迁移区别处理：旧记录没有暂停字段时状态是未知，应核对历史，不当成用户已恢复。

## 台账结构

JSON顶层字段：

```json
{
  "schema_version": 1,
  "profile_file": "profile.json",
  "settings": {"campaign_paused": false},
  "projects": []
}
```

每项目保留以下字段，未知用 null、unknown 或清楚的说明，不能用空值冒充已核验：

- `id`：持久唯一编号，沿用旧编号；`title`、`organizer`、`category`、活动年份。
- `deadline`：`date`（YYYY-MM-DD）、`time`（HH:MM或null）、`timezone`（默认Asia/Shanghai）；保留原文和延期证据。24:00表示次日零点；time=null保持未知，截止当天不能由程序推算成官方24:00。
- `workflow_status`：candidate、drafting、awaiting_confirmation、submitted、submission_uncertain、accepted、withdrawn、rejected、awarded、paid。
- `evidence_level`：primary、media、repost、unknown；`verified_at`是实际核验日期；`sources`包含URL、类型和支持哪些字段。
- `ai_policy`：allowed、prohibited、unspecified、unknown；可另附原文依据。
- `requirements`：字数口径、件数/次数、资格、说明和附件格式、必填信息、评选标准。
- `requirements.personal_data`：结构化必填字段、备选组、投稿/领奖阶段、完整程度与出处；匹配规则见 [profile-tiers.md](profile-tiers.md)。现有 `materials` 保留原文，不因标准字段映射而丢失细节。
- `prize_summary`及必要的数值：分清现金/实物/税务/叠加/空缺，不能把总奖金池当单人奖。
- `rights_summary`：版权适用所有稿还是获奖稿、何时转让、使用许可范围。
- `channel`：邮件/表单/小程序，收件方/入口/主题；咨询邮箱和投稿邮箱分开。
- `submissions`：每次实际提交或不确定尝试的证据，不覆盖旧记录；尚未提交为 []。
- `artifacts`、`notes`、`results`：草稿版本、文件路径、实质缺口、受理/获奖/到账依据。
- `follow_up`：公示/领奖时间、下一次检查、最近尝试/成功时间及追加式检查历史；全局 `settings.follow_up` 单独记录是否实际启用、自动化ID。详见 [follow-up.md](follow-up.md)。计划不等于定时任务已启用，停止新投稿与停止监测分别处理。

邮件 submission 通常记录 `provider`、`status`、`message_id`、`thread_id`、`sent_at`（带时区）、`sender`、`recipient`、`subject`、`body`、`attachments`、`archive_file`、对应用户确认和结果。不是邮件的提交用实际回执标识，不杜撰邮件ID。消息ID只能证明工具对应的那次操作。

## 更新规则

先读旧文件，再局部更新，保留未知扩展字段、历史正文、原来源及编号。写JSON前解析，采用临时文件再替换，避免损坏；出现同一提交ID跨项目重复时人工复核，不自动合并或再发。独立来源发现不同截止日期时保存冲突与各自出处。

工作流状态和截止时间状态相互独立：已经发出的参赛稿不会因为征集截止而变回“未报名”；历史候选超过旧截止只是按记录已到期，是否延期需联网核验；候选未来截止也不自动等于“今天有效”。

`ledger_status.py` 只读台账并报告这些状态，`--at`用于固定日期验证，`--format json`用于程序读取。它不更新来源、不推定原创合规、不代替审批和实际提交核验，也不写 LIST。

更新 Markdown LIST 时保留完整历史和归档链接，在顶部写清“记录整理日期”和“最后联网核验日期”，不得因安装技能或导入数据把旧核验日期改成今天。新候选与已报名必须分开；只归档实际发送内容，不把候选稿写成已发送。

已有名单迁移时，以原始发送记录逐字核对正文、收件方、时间及邮件ID。导入完成后两种格式应指向相同档案，不删除用户原来的可读 LIST。profile 中既有最终正文确认要求和暂停设置继续生效，历史批准不授予新项目提交权限。
