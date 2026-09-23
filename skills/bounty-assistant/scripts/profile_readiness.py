#!/usr/bin/env python3
"""只读检查投稿阶段必填资料；不联网、不发送、不读取证件附件。

python3 profile_readiness.py --profile profile.json --ledger ledger.json
python3 profile_readiness.py --profile profile.json --ledger ledger.json --format json

只输出项目及资料字段名称，不输出资料值、邮件内容或附件路径。
data_ready 仅表示已知必填资料在本地存在，不等于已获投稿或披露授权。
"""

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo


LOCAL_ZONE = ZoneInfo("Asia/Shanghai")
TIERS = {
    1: ("name", "email", "phone"),
    2: ("unit", "region", "hometown", "bio"),
    3: ("postal_address", "id_number", "id_document", "signature",
        "qualification_document", "company_license", "company_authorization"),
    4: ("bank_account", "tax_information"),
}
FIELD_TIER = {key: tier for tier, keys in TIERS.items() for key in keys}
STATUSES = {
    "data_ready": "已知投稿必填资料齐全（不等于可投稿）",
    "missing_data": "缺少投稿必填资料",
    "rules_incomplete": "资料规则尚不完整，需先核规则",
}


class ReadinessError(ValueError):
    """不回显输入内容的结构错误。"""


def has_data(profile, key):
    # 字段值按文字或附件路径存储；true、数字、空白及容器都不能冒充资料。
    value = profile.get(key)
    return isinstance(value, str) and bool(value.strip())


def clean_label(value):
    return " ".join("".join(char for char in value if char.isprintable() or char.isspace()).split())


def freshness(value, today):
    if not isinstance(value, str) or not value.strip():
        return "unknown"
    try:
        if len(value) == 10:
            recorded = date.fromisoformat(value)
        else:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                return "unknown"
            recorded = parsed.astimezone(LOCAL_ZONE).date()
    except ValueError:
        return "unknown"
    if recorded == today:
        return "checked_today_still_recheck_before_submission"
    return "requires_recheck" if recorded < today else "future_record_requires_check"


def analyze_profile(profile, ledger, today=None):
    if not isinstance(profile, dict) or not isinstance(ledger, dict):
        raise ReadinessError("profile 和 ledger 必须是 JSON 对象。")
    if ledger.get("schema_version") != 1 or not isinstance(ledger.get("projects"), list):
        raise ReadinessError("ledger 必须使用 schema_version 1，projects 必须是数组。")
    today = today or datetime.now(LOCAL_ZONE).date()
    final_review = True if profile.get("submission_policy") == "require_final_review" else None
    settings = ledger.get("settings")
    paused = settings.get("campaign_paused") if isinstance(settings, dict) else None
    campaign_paused = paused if isinstance(paused, bool) else None
    results = []
    ids = set()
    for project in ledger["projects"]:
        if not isinstance(project, dict):
            raise ReadinessError("每个项目必须是 JSON 对象。")
        project_id, title = project.get("id"), project.get("title")
        if not isinstance(project_id, str) or not project_id.strip() or not isinstance(title, str) or not title.strip():
            raise ReadinessError("每个项目必须包含非空字符串 id 和 title。")
        if project_id in ids:
            raise ReadinessError("发现重复项目 id，请核对台账。")
        ids.add(project_id)
        requirements = project.get("requirements", {})
        if not isinstance(requirements, dict):
            raise ReadinessError("项目 requirements 必须是对象。")
        personal = requirements.get("personal_data", {})
        if not isinstance(personal, dict):
            raise ReadinessError("requirements.personal_data 必须是对象。")
        completeness = personal.get("completeness", "unknown")
        if completeness not in ("known", "partial", "unknown"):
            completeness = "unknown"
        fields, groups = personal.get("fields", []), personal.get("any_of", [])
        if not isinstance(fields, list) or not isinstance(groups, list):
            raise ReadinessError("personal_data 的 fields 和 any_of 必须是数组。")
        missing, unknown, phase_review = set(), set(), set()
        missing_groups, selected_alternatives, suggested = [], [], set()
        required_tiers = set()
        invalid_rules = False

        def active(rule):
            nonlocal invalid_rules
            if not isinstance(rule, dict):
                invalid_rules = True
                return False
            if not isinstance(rule.get("required"), bool):
                invalid_rules = True
                return False
            if not rule["required"]:
                return False
            if rule.get("phase") == "claim":
                return False
            if rule.get("phase") != "submission":
                invalid_rules = True
                return False
            return True

        def known_submission_key(key):
            nonlocal invalid_rules
            if not isinstance(key, str) or not key.strip():
                invalid_rules = True
                return False
            if key not in FIELD_TIER:
                unknown.add(clean_label(key))
                return False
            if FIELD_TIER[key] == 4:
                # 领奖资料不能因为出现在模板中就自动成为投稿补资料请求。
                phase_review.add(key)
                return False
            return True

        for rule in fields:
            if not active(rule):
                continue
            key = rule.get("key")
            if known_submission_key(key):
                required_tiers.add(FIELD_TIER[key])
                if not has_data(profile, key):
                    missing.add(key)

        for rule in groups:
            if not active(rule):
                continue
            keys = rule.get("keys")
            if not isinstance(keys, list) or not keys:
                invalid_rules = True
                continue
            valid = []
            for key in keys:
                if known_submission_key(key) and key not in valid:
                    valid.append(key)
            # 有现成资料时选最低层级的现成项，不索要其他替代项。
            available = [key for key in valid if has_data(profile, key)]
            if available:
                chosen = min(available, key=lambda key: (FIELD_TIER[key], valid.index(key)))
                required_tiers.add(FIELD_TIER[chosen])
                selected_alternatives.append(chosen)
            elif valid:
                missing_groups.append(valid)
                chosen = min(valid, key=lambda key: (FIELD_TIER[key], valid.index(key)))
                required_tiers.add(FIELD_TIER[chosen])
                suggested.add(chosen)

        if completeness != "known" or invalid_rules or unknown or phase_review:
            status = "rules_incomplete"
        elif missing or missing_groups:
            status = "missing_data"
        else:
            status = "data_ready"
        notices = [
            "仅核对已记录的投稿必填资料，不代表活动有效、资格合格、作品符合 AI 规则或已可投稿。",
            "已有资料不代表获准对外发送；需核对本次实际授权范围，不重复索要已有效给出的同一授权。",
            "资料按项目按需补齐，不要求填满某一层级；领奖资料不默认用于投稿。",
        ]
        if final_review is None:
            notices.append("最终确认策略未知，需读取用户本人要求；本工具不推定免确认。")
        if unknown:
            notices.append("存在未识别的必填字段，需核对规则和字段含义。")
        if phase_review:
            notices.append("记录把领奖资料列为投稿必填，需核查实际用途及主办规则，不自动索要。")
        if invalid_rules:
            notices.append("必填规则缺少有效阶段、字段或 required 标记，需修正规则。")
        results.append({
            "id": clean_label(project_id), "title": clean_label(title),
            "status": status, "rules_completeness": completeness,
            "missing_keys": sorted(missing), "missing_groups": missing_groups,
            "suggested_missing_keys": sorted(suggested),
            "selected_alternative_keys": selected_alternatives,
            "unknown_keys": sorted(unknown), "phase_review_keys": sorted(phase_review),
            "required_submission_tiers": sorted(required_tiers),
            "permission_review_required": True, "final_review_required": final_review,
            "other_checks": {
                "rules_freshness": freshness(project.get("verified_at"), today),
                "qualification": "requires_separate_verification",
                "ai_policy": "requires_separate_verification",
            },
            "notices": notices,
        })
    return {"schema_version": 1, "checked_date": today.isoformat(),
            "permission_review_required": True, "final_review_required": final_review,
            "campaign_paused": campaign_paused,
            "projects": results}


def render_table(report):
    lines = ["投稿资料就绪检查（只读；不显示个人资料值）", "检查日期：" + report["checked_date"],
             "资料齐全不等于可投稿；活动有效性、规则新鲜度、参赛资格及 AI 规则仍需另核。",
             "仅按项目补必填项，不要求填满整个等级；领奖资料不默认用于投稿。"]
    if report.get("campaign_paused") is True:
        lines.append("报名活动已暂停：仅检查资料，不恢复创作、发送或提交。")
    elif report.get("campaign_paused") is None:
        lines.append("暂停状态未记录：不据此推定已恢复或已有投稿授权。")
    lines.extend(["编号 | 项目 | 已知资料等级 | 资料状态 | 缺少字段或任选组 | 规则新鲜度 | 额外待核问题",
                  "--- | --- | --- | --- | --- | --- | ---"])
    short_status = {"data_ready": "已知必填齐全", "missing_data": "待补资料", "rules_incomplete": "资料规则待核"}
    short_freshness = {
        "unknown": "未知",
        "requires_recheck": "旧记录，待复核",
        "future_record_requires_check": "核验日期异常",
        "checked_today_still_recheck_before_submission": "今日记录，投前复核",
    }
    for item in report["projects"]:
        levels = "/".join(str(tier) for tier in item["required_submission_tiers"]) or "无已知必填"
        if item["rules_completeness"] != "known":
            levels += "（完整等级待核）"
        missing = list(item["missing_keys"])
        missing.extend("任选(" + " / ".join(group) + ")" for group in item["missing_groups"])
        extra = []
        if item["unknown_keys"]:
            extra.append("未知字段：" + ", ".join(item["unknown_keys"]))
        if item["phase_review_keys"]:
            extra.append("阶段待核：" + ", ".join(item["phase_review_keys"]))
        if any(notice.startswith("必填规则缺少") for notice in item["notices"]):
            extra.append("必填规则格式不全")
        cells = [item["id"], item["title"], levels, short_status[item["status"]],
                 "; ".join(missing) or "无已知缺项",
                 short_freshness[item["other_checks"]["rules_freshness"]], "; ".join(extra) or "—"]
        lines.append(" | ".join(cell.replace("|", "／") for cell in cells))
    lines.append("披露授权：资料存在不等于授权发送；核对本次有效授权，不重复索要已有的同一授权。")
    lines.append("最终正文确认：" + ("用户已要求确认" if report["final_review_required"] is True else "策略未知，需读本人要求"))
    if not report["projects"]:
        lines.append("（尚无项目）")
    return "\n".join(lines)


def read_object(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReadinessError("无法读取 UTF-8 JSON 文件；请检查文件路径、权限和格式。") from exc


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--profile", required=True, type=Path)
    parser.add_argument("--ledger", required=True, type=Path)
    parser.add_argument("--format", choices=("table", "json"), default="table")
    args = parser.parse_args(argv)
    try:
        report = analyze_profile(read_object(args.profile), read_object(args.ledger))
    except ReadinessError as exc:
        print("错误：" + str(exc), file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2) if args.format == "json" else render_table(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
