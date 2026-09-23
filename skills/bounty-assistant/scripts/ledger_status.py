#!/usr/bin/env python3
"""只读检查悬赏台账；仅使用 Python 标准库，不联网、不发送、不改文件。

用法：python3 ledger_status.py --ledger ledger.json [--at 2026-09-23]
      python3 ledger_status.py --ledger ledger.json --format json

--at 仅传日期时取 Asia/Shanghai 当天 00:00；日期时间必须带 UTC 偏移。
截止时间留空只按日期推算：当天标为“截止日，具体时刻待核”，不保证仍可投。
24:00 为明确的当地次日 00:00；恰好到达这一边界即过期。
输出只选取项目状态字段，不读取 profile_file，不打印个人资料或邮件内容。
"""

import argparse
import json
import re
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


LOCAL_ZONE = ZoneInfo("Asia/Shanghai")
WORKFLOW_STATES = {
    "candidate": "候选", "drafting": "创作中",
    "awaiting_confirmation": "待用户确认", "submitted": "已提交",
    "submission_uncertain": "发送结果不确定", "accepted": "已受理",
    "withdrawn": "已撤回", "rejected": "未通过", "awarded": "已获奖",
    "paid": "已到账",
}
TIME_STATES = {"not_due": "截止未到", "deadline_day": "截止日，具体时刻待核",
               "expired": "截止已过", "unknown": "截止未知"}
EVIDENCE_LEVELS = {"primary", "media", "repost", "unknown"}
AI_POLICIES = {"allowed", "prohibited", "unspecified", "unknown"}
UNCERTAIN_STATES = {"submission_uncertain", "uncertain", "unknown"}


class LedgerError(ValueError):
    """输入错误；错误消息不回显原始个人资料。"""


def parse_at(value):
    if value is None:
        return datetime.now(LOCAL_ZONE)
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            return datetime.combine(date.fromisoformat(value), time.min, LOCAL_ZONE)
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise LedgerError("--at 的日期时间必须包含时区；只传日期则按上海时间当天零点处理。")
        return parsed.astimezone(LOCAL_ZONE)
    except (TypeError, ValueError) as exc:
        if isinstance(exc, LedgerError):
            raise
        raise LedgerError("--at 必须为 ISO 日期或带时区的 ISO 日期时间。") from exc


def deadline_boundary(value):
    if value is None:
        return None
    if not isinstance(value, dict):
        raise LedgerError("项目 deadline 必须是对象或 null。")
    raw_date = value.get("date")
    if raw_date in (None, ""):
        return None
    try:
        if not isinstance(raw_date, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw_date):
            raise ValueError
        day = date.fromisoformat(raw_date)
        zone_name = value.get("timezone", "Asia/Shanghai")
        if not isinstance(zone_name, str):
            raise ValueError
        zone = ZoneInfo(zone_name)
        raw_time = value.get("time")
        if raw_time in (None, "", "24:00", "24:00:00"):
            return datetime.combine(day + timedelta(days=1), time.min, zone)
        if not isinstance(raw_time, str) or not re.fullmatch(r"\d{2}:\d{2}(?::\d{2})?", raw_time):
            raise ValueError
        return datetime.combine(day, time.fromisoformat(raw_time), zone)
    except (ValueError, TypeError, ZoneInfoNotFoundError, OverflowError) as exc:
        raise LedgerError("项目截止日期、时间或时区格式无效。") from exc


def verified_date(value):
    if value in (None, ""):
        return None
    try:
        return parse_at(value).date()
    except LedgerError as exc:
        raise LedgerError("verified_at 必须为 ISO 日期或带时区的 ISO 日期时间。") from exc


def safe_text(value):
    """避免把终端控制符作为显示指令；不会输出自由文本备注等资料。"""
    return " ".join("".join(char for char in value if char.isprintable() or char.isspace()).split())


def analyze_ledger(ledger, now):
    if not isinstance(ledger, dict) or ledger.get("schema_version") != 1:
        raise LedgerError("台账必须是 schema_version 为 1 的 JSON 对象。")
    if not isinstance(ledger.get("profile_file"), str):
        raise LedgerError("台账缺少字符串 profile_file；本工具不会打开该文件。")
    projects = ledger.get("projects")
    if not isinstance(projects, list):
        raise LedgerError("台账 projects 必须是数组。")
    settings = ledger.get("settings", {})
    if not isinstance(settings, dict):
        raise LedgerError("台账 settings 必须是对象。")
    campaign_paused = settings.get("campaign_paused")
    if campaign_paused is not None and not isinstance(campaign_paused, bool):
        raise LedgerError("settings.campaign_paused 必须是布尔值或 null（未知）。")
    project_ids = set()
    message_owners = {}
    output = []
    for position, item in enumerate(projects, start=1):
        if not isinstance(item, dict):
            raise LedgerError("projects 中每项必须是对象。")
        project_id = item.get("id")
        title = item.get("title")
        if not isinstance(project_id, str) or not project_id.strip():
            raise LedgerError("项目 id 必须是非空字符串。")
        if project_id in project_ids:
            raise LedgerError("发现重复项目 id；请合并重复条目后重试。")
        project_ids.add(project_id)
        if not isinstance(title, str) or not title.strip():
            raise LedgerError("项目 title 必须是非空字符串。")
        workflow = item.get("workflow_status")
        evidence = item.get("evidence_level", "unknown")
        ai_policy = item.get("ai_policy", "unknown")
        if not isinstance(workflow, str) or workflow not in WORKFLOW_STATES:
            raise LedgerError("项目 workflow_status 不属于支持的工作流状态。")
        if not isinstance(evidence, str) or evidence not in EVIDENCE_LEVELS:
            raise LedgerError("项目 evidence_level 无效。")
        if not isinstance(ai_policy, str) or ai_policy not in AI_POLICIES:
            raise LedgerError("项目 ai_policy 无效。")
        submissions = item.get("submissions", [])
        if not isinstance(submissions, list):
            raise LedgerError("项目 submissions 必须是数组。")
        uncertain = workflow == "submission_uncertain"
        for submission in submissions:
            if not isinstance(submission, dict):
                raise LedgerError("submissions 中每项必须是对象。")
            submission_status = submission.get("status")
            if submission_status is not None and not isinstance(submission_status, str):
                raise LedgerError("投稿 status 必须是字符串。")
            uncertain = uncertain or submission_status in UNCERTAIN_STATES
            message_id = submission.get("message_id")
            if message_id in (None, ""):
                continue
            provider = submission.get("provider", "unspecified")
            if not isinstance(message_id, str) or not isinstance(provider, str):
                raise LedgerError("投稿 provider 和 message_id 必须是字符串。")
            # 同一服务的消息 ID 跨项目复用通常是错记，先报错再输出表格。
            key = (provider.casefold().strip(), message_id.strip())
            owner = message_owners.get(key)
            if owner is not None and owner != position:
                raise LedgerError("发现两个项目使用相同服务的相同 message_id；请核对发送凭证，勿重复投稿。")
            message_owners[key] = position
        deadline = deadline_boundary(item.get("deadline"))
        deadline_date = None
        precision = "unknown"
        if deadline is None:
            time_state = "unknown"
        else:
            raw_deadline = item["deadline"]
            deadline_date = raw_deadline["date"]
            precision = "date" if raw_deadline.get("time") in (None, "") else "time"
            if precision == "date":
                local_day = now.astimezone(deadline.tzinfo).date()
                recorded_day = date.fromisoformat(deadline_date)
                time_state = ("expired" if local_day > recorded_day else
                              "deadline_day" if local_day == recorded_day else "not_due")
            else:
                time_state = "expired" if now >= deadline else "not_due"
        verified = verified_date(item.get("verified_at"))
        notices = []
        if uncertain:
            notices.append("发送结果不确定：先核查已发送邮件、回执或平台记录，不要重发。")
        if time_state == "not_due":
            notices.append("仅按台账日期判断截止未到，不代表活动当前有效；投稿前复核主办公告。")
        elif time_state == "deadline_day":
            notices.append("已到公告截止日，但未记录具体截止时刻；不能认定仍可投稿，需先核验主办公告。")
        elif time_state == "expired":
            notices.append("仅截止时间已过；保留原工作流状态及全部投稿历史。")
        else:
            notices.append("缺少明确截止日期，不能判断是否仍可报名。")
        if verified is None:
            notices.append("没有核验日期，需核验来源。")
        elif verified < now.date():
            notices.append("核验记录早于当前核查日，需重新核验活动状态。")
        elif verified > now.date():
            notices.append("核验日期晚于当前核查日，请检查记录。")
        if evidence != "primary":
            notices.append("当前证据未标为主办方一手来源。")
        if ai_policy == "prohibited":
            notices.append("记录显示禁止 AI 创作，排除 AI 代写投稿。")
        elif ai_policy in {"unspecified", "unknown"}:
            notices.append("AI 规则未说明或未知，不能视为已允许。")
        output.append({
            "id": safe_text(project_id), "title": safe_text(title),
            "workflow_status": workflow, "time_status": time_state,
            "deadline_precision": precision, "deadline_date": deadline_date,
            "deadline_at": deadline.isoformat() if precision == "time" else None,
            "calendar_boundary_at": deadline.isoformat() if precision == "date" else None,
            "evidence_level": evidence, "verified_at": item.get("verified_at"),
            "ai_policy": ai_policy, "notices": notices,
        })
    return {"schema_version": 1, "checked_at": now.isoformat(),
            "campaign_paused": campaign_paused, "projects": output}


def render_table(report):
    lines = [
        "悬赏台账状态（只读；截止未到不等于已核实有效）",
        "核查时间：" + report["checked_at"],
    ]
    if report["campaign_paused"]:
        lines.append("报名活动已暂停：本次仅查看状态，等待用户恢复后再继续创作、发送或提交。")
    elif report["campaign_paused"] is None:
        lines.append("暂停状态未知：先核对已有记录与用户指示，不据此恢复参赛。")
    lines.extend(["编号 | 项目 | 工作流状态 | 时间状态 | 截止日期或时刻",
                  "--- | --- | --- | --- | ---"])
    for item in report["projects"]:
        displayed_deadline = item["deadline_at"] or "未知"
        if item["deadline_precision"] == "date":
            displayed_deadline = item["deadline_date"] + "（时刻待核）"
        cells = [item["id"], item["title"], WORKFLOW_STATES[item["workflow_status"]],
                 TIME_STATES[item["time_status"]], displayed_deadline]
        lines.append(" | ".join(str(cell).replace("|", "／") for cell in cells))
        lines.append("  提示：" + "；".join(item["notices"]))
    if not report["projects"]:
        lines.append("（尚无项目）")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ledger", required=True, type=Path, help="只读 JSON 台账路径")
    parser.add_argument("--at", help="ISO 日期，或带时区的 ISO 日期时间")
    parser.add_argument("--format", choices=("table", "json"), default="table")
    args = parser.parse_args(argv)
    try:
        now = parse_at(args.at)
        try:
            ledger = json.loads(args.ledger.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise LedgerError("无法读取 UTF-8 JSON 台账；请检查路径、权限和 JSON 格式。") from exc
        report = analyze_ledger(ledger, now)
    except LedgerError as exc:
        print("错误：" + str(exc), file=sys.stderr)
        return 2
    if args.format == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render_table(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
