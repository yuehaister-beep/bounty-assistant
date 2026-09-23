# 悬赏参赛助手 · Bounty Assistant

面向中文有奖征集的 Codex Skill：搜集公开项目、核验要求、匹配已有资料、创作参赛作品，按用户确认投稿，并维护回执、公示和领奖记录。

首个发布版本：1.0.0。优先支持口号、命名、短文案；设计、代码或科研任务按实际交付条件单独评估。

仓库：[yuehaister-beep/bounty-assistant](https://github.com/yuehaister-beep/bounty-assistant) · 发布页：[v1.0.0](https://github.com/yuehaister-beep/bounty-assistant/releases/tag/v1.0.0)。

## 工作流程

搜索 → 来源与截止核验 → 资料匹配 → 创作与审稿 → 用户确认最终材料 → 投稿并保存凭证 → 公示、领奖与到账跟进。

可以单独执行其中一步。“找项目”只搜集筛选；“准备作品”只准备材料；已提交的活动默认查进度，避免重复投稿。最终确认对应确切收件人、主题、正文和附件，发送响应不确定时先核查实际结果。

## 资料按需提供

| 等级／阶段 | 典型字段 |
|---|---|
| 一级：基础联系 | 姓名、邮箱、电话 |
| 二级：背景资料 | 单位、地区、籍贯、简介 |
| 三级：实名及证明 | 详细地址、证件、签名、资格证明 |
| 领奖阶段 | 核实获奖后的收款、税务资料 |

按每个项目的实际必填项匹配，不必填满整级。“单位或籍贯”满足一个即可；未查看完整的表单保持待核。资料齐全、报名资格、AI规则和发送授权分别判断。

## 安装

本仓库的 Skill 位于 [`skills/bounty-assistant`](skills/bounty-assistant/SKILL.md)。

将以下指令直接复制给 Codex：

```text
使用 $skill-installer，从 https://github.com/yuehaister-beep/bounty-assistant 安装 skills/bounty-assistant。
```

也可从 [v1.0.0 发布页](https://github.com/yuehaister-beep/bounty-assistant/releases/tag/v1.0.0) 下载 `bounty-assistant-v1.0.0.zip`，解压后将 `bounty-assistant-1.0.0/skills/bounty-assistant` 文件夹放进个人技能目录 `~/.agents/skills/`；已有同名技能时先保留个人配置，避免生成两个同名副本。

安装后可以直接说：

> 使用 $bounty-assistant，找 5 个国内仍在征稿、适合一级资料的口号或命名悬赏。核验原公告，先列候选，不投稿。

Codex 可按描述自动选择技能；显式调用有助于确认使用的是本技能。安装位置和发现机制见 [OpenAI Docs：Build skills](https://learn.chatgpt.com/docs/build-skills)。

## 首次使用

查项目无需先填个人资料。没有旧记录时，技能会在当前工作目录的 `outputs/bounty-data` 建立空资料库；若已有台账或LIST，会先读取而不覆盖。也可指定其他个人数据目录。

脚本需要 Python 3.9+，日期检查需要系统可用的 IANA 时区数据库。可从本仓库根目录执行：

```bash
python3 skills/bounty-assistant/scripts/init_state.py --state-dir outputs/bounty-data
python3 skills/bounty-assistant/scripts/ledger_status.py --ledger outputs/bounty-data/ledger.json
python3 skills/bounty-assistant/scripts/profile_readiness.py --profile outputs/bounty-data/profile.json --ledger outputs/bounty-data/ledger.json
```

初始化器只创建空台账和默认偏好，不覆盖现有文件。后两个脚本只读本地记录，不联网、不发邮件，也不自动填表。

## 常用指令

- **搜集**：“找 10 个没有过期的国内口号悬赏，优先官方来源，不足 10 个就说明。”
- **补资料**：“按我已有资料匹配这批项目，只列选中项目缺少的必填项。”
- **创作**：“给选中的项目准备作品和投稿邮件，正文先让我确认。”
- **发送**：“确认发送刚才展示的这个版本，并保存完整正文和发送凭证。”
- **单次跟进**：“检查已报名项目的相关回执和最新公示。”
- **持续跟进**：“启用已报名项目监测，每天上午检查到期节点，有获奖、补件或领奖期限时通知我。”
- **暂停**：“暂停新投稿，保留已经启用的结果监测。”或“全部暂停，包括定时任务。”

## 运行能力与跟进

Skill提供流程，实际搜索、邮箱、浏览器和自动化操作依赖运行环境中可用且已授权的工具。没有邮箱写入工具时可以准备材料，不能声称已发送；没有自动化能力时可以单次检查，不能声称已开启主动提醒。

持续跟进需由用户明确启用。启用后记录公示与领奖节点、最近成功检查、失败和下次检查；恢复时补查逾期待办。结果匹配会结合作品或编号，不只看同名；没有公示不等于落选，获奖也不等于到账。依赖本地资料的定时任务需要电脑和应用保持可运行，详见 [OpenAI Docs：Scheduled tasks](https://learn.chatgpt.com/docs/automations)。

## 数据与发布范围

个人资料和报名历史存放在用户自己的数据目录。发布包不含账号、邮箱凭据、真实参赛邮件、个人台账或本机目录配置；也不附带统一的搜索或邮箱账号。证件、签名及收款资料只在明确需要时处理，普通LIST不展开这些内容。

转载仅作为线索；正式投稿前核对权威渠道、资格、AI及版权要求。明确禁止AI创作的项目不进入AI代创流程；不承诺全网覆盖、原创检索绝对完整或一定获奖。

## 验证

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

测试使用合成资料和临时目录，覆盖截止日期、时区、发送不确定、重复记录、资料任选组、未知表单、只读输出和初始化不覆盖旧数据。自动化和真实投稿仍须在使用者自己的环境中连接工具并核验结果。
