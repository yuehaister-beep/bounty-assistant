#!/usr/bin/env python3
"""初始化全新的悬赏个人数据目录；不复制示例身份、投稿历史或本机配置。

python3 init_state.py --state-dir /path/to/private-bounty-data

任一目标文件已存在时拒绝初始化。只创建 profile.json 和 ledger.json，
不联网、不创建自动化，也不修改 Skill 的 config.local.json。
"""

import argparse
import json
import os
from pathlib import Path
import stat
import sys


class InitializationError(ValueError):
    """初始化未完成；错误消息不回显文件内容。"""


def empty_documents():
    """每次返回全新对象；不读取环境中的个人资料。"""
    return {
        "profile.json": {
            "schema_version": 1,
            "submission_policy": "require_final_review",
            "information_preferences": {"collection_mode": "progressive"},
        },
        "ledger.json": {
            "schema_version": 1,
            "profile_file": "profile.json",
            "settings": {
                "campaign_paused": False,
                "follow_up": {
                    "enabled": False,
                    "automation_id": None,
                    "activation_status": "not_activated",
                    "policy": "on_demand_until_activated",
                },
            },
            "projects": [],
        },
    }


def cleanup_owned_files(created):
    """只清理本次独占创建且仍指向同一文件的路径，不删除后来替换的文件。"""
    for path, device, inode in reversed(created):
        try:
            current = path.lstat()
            if (stat.S_ISREG(current.st_mode)
                    and (current.st_dev, current.st_ino) == (device, inode)):
                path.unlink()
        except OSError:
            # 无法证明路径仍属于本次创建，或清理被拒绝时，保留它而不扩大删除。
            pass


def initialize_state(state_dir):
    state_dir = Path(state_dir).expanduser().absolute()
    documents = empty_documents()
    targets = [state_dir / name for name in documents]
    # lexists 也识别断开的符号链接，不能把它误判为空路径。
    if any(os.path.lexists(target) for target in targets):
        raise InitializationError("目标目录已有 profile.json 或 ledger.json，已保留全部内容，未初始化。")
    created = []
    descriptors = []
    try:
        state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        for target in targets:
            # 预检查之后仍以独占方式创建，绝不截断竞态中出现的现有文件。
            descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            descriptors.append(descriptor)
            metadata = os.fstat(descriptor)
            created.append((target, metadata.st_dev, metadata.st_ino))
            # 保留描述符直到完成或回滚，避免清理前原 inode 被回收重用。
            with os.fdopen(descriptor, "w", encoding="utf-8", closefd=False) as handle:
                json.dump(documents[target.name], handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
    except OSError as exc:
        cleanup_owned_files(created)
        raise InitializationError("初始化未完成；未覆盖已有文件，已尝试清理本次创建的文件。") from exc
    finally:
        for descriptor in descriptors:
            os.close(descriptor)
    return state_dir


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--state-dir", required=True, type=Path, help="新个人数据目录")
    args = parser.parse_args(argv)
    try:
        state_dir = initialize_state(args.state_dir)
    except InitializationError as exc:
        print("错误：" + str(exc), file=sys.stderr)
        return 2
    print("已初始化：" + str(state_dir))
    print("未启用自动提醒。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
