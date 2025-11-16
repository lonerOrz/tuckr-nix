#!/usr/bin/env python3
"""
Tuckr辅助脚本 - 用于处理Tuckr状态输出并自动解决冲突

此脚本读取Tuckr的JSON状态输出，自动处理冲突的dotfiles组，
将冲突的整个文件夹重命名备份，然后重新链接它们。

作者: lonerOrz
使用方法:
    1. 通过管道传递Tuckr状态JSON输出给此脚本:
       `tuckr status --json | python3 tuckr.py`
    2. 可使用参数指定备份后缀和排除的组:
       `tuckr status --json | python3 tuckr.py --suffix backup --exclude group1 group2`
功能说明:
    - 自动链接未链接的组
    - 检测冲突的组
    - 将冲突的整个项目文件夹重命名为备份名称
    - 重新链接这些组
    - 提供详细的处理进度和统计信息
"""

import json
import os
import subprocess
import argparse
import sys
import logging
import shlex

# ANSI 颜色代码
COLOR_RESET = "\033[0m"
COLOR_BOLD = "\033[1m"
COLOR_RED = "\033[91m"
COLOR_GREEN = "\033[92m"
COLOR_YELLOW = "\033[93m"
COLOR_BLUE = "\033[94m"
COLOR_CYAN = "\033[96m"


class ColorFormatter(logging.Formatter):
    """自定义颜色日志格式化器"""

    COLORS = {
        logging.DEBUG: COLOR_CYAN,
        logging.INFO: COLOR_GREEN,
        logging.WARNING: COLOR_YELLOW,
        logging.ERROR: COLOR_RED,
        logging.CRITICAL: COLOR_BOLD + COLOR_RED,
    }

    def format(self, record):
        color = self.COLORS.get(record.levelno, "")
        message = super().format(record)
        return f"{color}{message}{COLOR_RESET}"


def setup_logging(verbose: bool = False, use_color: bool | None = None) -> None:
    """
    配置根日志记录器
    如果 use_color 为 None，则根据 TTY 检测
    """
    if use_color is None:
        use_color = sys.stdout.isatty()

    handler = logging.StreamHandler(sys.stdout)
    formatter = (
        ColorFormatter("%(levelname)s: %(message)s")
        if use_color
        else logging.Formatter("%(levelname)s: %(message)s")
    )
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.DEBUG if verbose else logging.INFO)


def _run_tuckr_add(group_name, exclude_groups, stats, is_conflict_resolution=False):
    """
    运行 'tuckr add <group>' 命令，可选择性地使用 --exclude 列表
    """
    cmd = ["tuckr", "add", group_name]
    if exclude_groups:
        cmd.append("--exclude")
        cmd.extend(exclude_groups)

    logging.debug("执行命令: %s", " ".join(shlex.quote(c) for c in cmd))
    try:
        completed = subprocess.run(cmd, check=True, capture_output=True, text=True)
        logging.debug("命令输出:\n%s", completed.stdout.strip())
        logging.info(f"  成功执行 'tuckr add {group_name}'。")
        stats["added_groups"] += 1
        return True
    except subprocess.CalledProcessError as e:
        # 在冲突解决过程中，tuckr 命令失败是预期的行为，不视为错误
        if not is_conflict_resolution:
            logging.error(
                "  执行 'tuckr add %s' 时出错 (返回码 %s): %s",
                group_name,
                e.returncode,
                e.stderr.strip(),
            )
            logging.debug("命令标准输出 (部分):\n%s", (e.stdout or "").strip())
            stats["errors"] += 1
        else:
            logging.info(
                "  'tuckr add %s' 未成功 (预期的行为): %s",
                group_name,
                e.stderr.strip(),
            )
        return False
    except FileNotFoundError:
        logging.error(
            "  在PATH中找不到 'tuckr'。请确保已安装二进制文件并设置PATH。"
        )
        stats["errors"] += 1
        return False


def _handle_project_folder_backup(
    original_path, group_name, backup_suffix, exclude_groups, stats
):
    """
    处理项目文件夹的备份重命名并为该组运行 tuckr add
    """
    backup_path = f"{original_path}-{backup_suffix}"
    logging.warning(
        "  发现项目文件夹 '%s'。尝试将其重命名为 '%s' 以进行备份。",
        original_path,
        backup_path,
    )
    try:
        os.rename(original_path, backup_path)
        logging.info("  成功将 '%s' 重命名为 '%s'。", original_path, backup_path)
        stats["renamed_folders"] += 1
    except Exception as e:
        logging.error(
            "  重命名 '%s' 时出错: %s。跳过此组的 tuckr add。",
            original_path,
            e,
        )
        stats["errors"] += 1
        return False  # 表示失败

    logging.warning(
        "  通过运行 'tuckr add %s' 来解决 '%s' 的冲突。",
        group_name,
        group_name,
    )
    return _run_tuckr_add(group_name, exclude_groups, stats, is_conflict_resolution=True)


def process_conflicts(json_input_str, backup_suffix, exclude_groups):
    """
    处理JSON状态，执行备份/重命名，并尝试链接dotfiles
    """
    # 初始化统计信息
    stats = {
        "symlinked_printed": 0,  # 已链接并打印的组数
        "not_symlinked_processed": 0,  # 已处理的未链接组数
        "conflicts_processed": 0,  # 已处理的冲突组数
        "renamed_folders": 0,  # 已重命名的文件夹数
        "renamed_files": 0,  # 已重命名的文件数
        "added_groups": 0,  # 已成功添加的组数
        "unsupported_printed": 0,  # 已打印的不支持组数
        "non_existent_printed": 0,  # 已打印的不存在组数
        "skipped_excluded": 0,  # 因排除而跳过的组数
        "errors": 0,  # 错误数
        "warnings": 0,  # 警告数
    }

    try:
        status_data = json.loads(json_input_str)
        logging.debug("解析的JSON键: %s", list(status_data.keys()))
    except json.JSONDecodeError as e:
        logging.error("解码JSON输入时出错: %s", e)
        stats["errors"] += 1
        return stats

    # 首先打印已成功链接的组
    symlinked_groups = status_data.get("symlinked", [])
    logging.debug("已链接组数量: %d", len(symlinked_groups))
    if symlinked_groups:
        logging.info("已成功链接的组: %s", ", ".join(symlinked_groups))
        for group in symlinked_groups:
            stats["symlinked_printed"] += 1

    # 处理未链接的组
    not_symlinked_groups = status_data.get("not_symlinked", [])

    logging.debug("未链接组数量: %d", len(not_symlinked_groups))

    if not_symlinked_groups:
        for group in not_symlinked_groups:
            if group in exclude_groups:
                logging.warning("跳过排除的组 '%s'", group)
                stats["skipped_excluded"] += 1
                continue

            # 获取此特定组的详细状态
            try:
                # 注意：即使tuckr返回错误码，我们也想获取其输出
                detailed_result = subprocess.run(
                    ["tuckr", "status", group, "--json"],
                    capture_output=True,
                    text=True,
                )

                # 即使返回码非0，我们仍然尝试解析输出
                if detailed_result.stdout:
                    detailed_status = json.loads(detailed_result.stdout)

                    # 提取此组的冲突详情
                    group_conflicts = detailed_status.get("conflicts", {})

                    # 检查是否有冲突
                    if (
                        isinstance(group_conflicts, dict) and group in group_conflicts
                    ):
                        conflict_list = group_conflicts[group]

                        # 如果有冲突，则备份整个项目文件夹并重新链接
                        if conflict_list:
                            logging.info("处理冲突组: %s", group)

                            # 循环处理，直到没有冲突或达到最大重试次数
                            max_retries = min(5, len(conflict_list))  # 重试次数不超过冲突数和最大次数中的较小值
                            retry_count = 0

                            while retry_count < max_retries:
                                conflict_list = group_conflicts.get(group, [])

                                if not conflict_list:
                                    # 没有冲突了，跳出循环
                                    logging.info("  组 '%s' 的冲突已解决", group)
                                    stats["not_symlinked_processed"] += 1
                                    break

                                # 从第一个冲突文件路径推断整个项目文件夹
                                first_target_path = conflict_list[0]["target_path"]
                                project_folder_path = os.path.dirname(first_target_path)

                                # 尝试向上查找直到找到包含组名的目录
                                # 例如，如果冲突是 ~/.config/nvim/init.lua，我们查找 ~/.config/nvim
                                while project_folder_path != "/":
                                    if os.path.basename(project_folder_path) == group:
                                        break
                                    project_folder_path = os.path.dirname(
                                        project_folder_path
                                    )

                                if project_folder_path != "/":
                                    logging.debug(
                                        "  检测到项目文件夹: %s", project_folder_path
                                    )

                                    # 重命名整个项目文件夹并尝试链接组
                                    _handle_project_folder_backup(
                                        project_folder_path,
                                        group,
                                        backup_suffix,
                                        exclude_groups,
                                        stats,
                                    )

                                    # 重新获取组的详细状态
                                    detailed_result = subprocess.run(
                                        ["tuckr", "status", group, "--json"],
                                        capture_output=True,
                                        text=True,
                                    )

                                    if detailed_result.stdout:
                                        detailed_status = json.loads(detailed_result.stdout)
                                        group_conflicts = detailed_status.get("conflicts", {})
                                    else:
                                        logging.warning("无法获取组 '%s' 的状态输出", group)
                                        break
                                else:
                                    logging.warning(
                                        "无法找到组 '%s' 的项目根目录", group
                                    )
                                    stats["warnings"] += 1
                                    break

                                retry_count += 1

                            # 检查最终是否还有冲突
                            final_conflicts = group_conflicts.get(group, []) if isinstance(group_conflicts, dict) and group in group_conflicts else []
                            if not final_conflicts:
                                logging.info("  组 '%s' 的冲突已解决", group)
                                stats["not_symlinked_processed"] += 1
                            else:
                                logging.warning("  组 '%s' 可能仍有冲突未能解决", group)
                        else:
                            # 无冲突，直接尝试链接
                            logging.info("链接组: %s", group)
                            if _run_tuckr_add(group, exclude_groups, stats, is_conflict_resolution=False):
                                logging.debug("成功链接 %s", group)
                                stats["not_symlinked_processed"] += 1
                    else:
                        # 未在冲突列表中，直接尝试链接
                        logging.info("链接组: %s", group)
                        if _run_tuckr_add(group, exclude_groups, stats, is_conflict_resolution=False):
                            logging.debug("成功链接 %s", group)
                            stats["not_symlinked_processed"] += 1
                else:
                    logging.warning("无法获取组 '%s' 的状态输出", group)
                    stats["warnings"] += 1
            except json.JSONDecodeError as e:
                logging.error("解码组 '%s' 的详细JSON时出错: %s", group, e)
                stats["errors"] += 1

    # 不支持的组
    unsupported_groups = status_data.get("unsupported", [])
    logging.debug("不支持组数量: %d", len(unsupported_groups))
    if unsupported_groups:
        for group in unsupported_groups:
            logging.warning("组 '%s' 不支持当前平台/条件", group)
            stats["unsupported_printed"] += 1

    # 不存在的组
    non_existent_groups = status_data.get("nonexistent", []) or status_data.get(
        "non_existent", []
    )
    logging.debug("不存在组数量: %d", len(non_existent_groups))
    if non_existent_groups:
        for group in non_existent_groups:
            logging.warning("组 '%s' 不存在 (检查拼写或缺失的dotfiles)", group)
            stats["non_existent_printed"] += 1

    # 最终摘要
    logging.info("处理摘要:")
    logging.info(
        "总处理的组数: %s",
        stats["not_symlinked_processed"] + stats["conflicts_processed"],
    )
    logging.info("成功添加/链接的组数: %s", stats["added_groups"])
    logging.info("为备份重命名的文件夹: %s", stats["renamed_folders"])
    logging.info("为备份重命名的文件: %s", stats["renamed_files"])
    if stats["skipped_excluded"] > 0:
        logging.warning("因排除而跳过的组: %s", stats["skipped_excluded"])
    if stats["warnings"] > 0:
        logging.warning("总警告数: %s", stats["warnings"])
    if stats["errors"] > 0:
        logging.error("总错误数: %s", stats["errors"])

    return stats


def main():
    parser = argparse.ArgumentParser(
        description="处理tuckr状态JSON输出以备份和解决冲突。"
    )
    parser.add_argument(
        "--suffix",
        default="backup",
        help="追加到重命名备份文件/文件夹的后缀。默认为 'backup'。",
    )
    parser.add_argument(
        "--exclude",
        nargs="*",
        default=[],
        help="在运行tuckr add时要排除的组。接受多个值。",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="启用调试日志以获得更详细的输出。",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="在日志输出中禁用ANSI颜色。",
    )
    args = parser.parse_args()

    setup_logging(verbose=args.verbose, use_color=not args.no_color)

    logging.info("正在等待来自stdin的JSON输入...")
    json_input = sys.stdin.read()
    process_conflicts(json_input, args.suffix, args.exclude)


if __name__ == "__main__":
    main()
