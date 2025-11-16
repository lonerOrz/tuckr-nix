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
    """更美观的自定义颜色日志格式化器，使用符号前缀"""

    def __init__(self, use_color=True):
        super().__init__()
        self.use_color = use_color

    def format(self, record):
        level_map = {
            logging.DEBUG: (COLOR_CYAN, "[*]"),
            logging.INFO: (COLOR_GREEN, "[+]"),
            logging.WARNING: (COLOR_YELLOW, "[!]"),
            logging.ERROR: (COLOR_RED, "[-]"),
            logging.CRITICAL: (COLOR_BOLD + COLOR_RED, "[!!!]"),
        }

        if self.use_color:
            color, prefix = level_map.get(record.levelno, (COLOR_RESET, "[?]"))
            # Add bold to the prefix
            prefix = f"{color}{COLOR_BOLD}{prefix}{COLOR_RESET}"
        else:
            # No color, just the prefix text
            _, prefix = level_map.get(record.levelno, "[?]")

        # Create the final message
        formatter = logging.Formatter(f"{prefix} %(message)s")

        return formatter.format(record)


class Stats:
    """封装统计信息，提供增加、查询和打印摘要的方法"""

    def __init__(self):
        self.data = {
            "symlinked_printed": 0,
            "not_symlinked_processed": 0,
            "conflicts_processed": 0,
            "renamed_folders": 0,
            "renamed_files": 0,
            "added_groups": 0,
            "unsupported_printed": 0,
            "non_existent_printed": 0,
            "skipped_excluded": 0,
            "errors": 0,
            "warnings": 0,
        }

    def increment(self, key, value=1):
        """增加一个统计项"""
        if key in self.data:
            self.data[key] += value
        else:
            logging.warning(f"试图增加一个不存在的统计项: {key}")

    def get(self, key):
        """获取一个统计项的值"""
        return self.data.get(key, 0)

    def log_summary(self):
        """打印最终的统计摘要"""
        logging.info("处理摘要:")
        logging.info(
            "总处理的组数: %s",
            self.get("not_symlinked_processed") + self.get("conflicts_processed"),
        )
        logging.info("成功添加/链接的组数: %s", self.get("added_groups"))
        logging.info("为备份重命名的文件夹: %s", self.get("renamed_folders"))
        logging.info("为备份重命名的文件: %s", self.get("renamed_files"))
        if self.get("skipped_excluded") > 0:
            logging.warning("因排除而跳过的组: %s", self.get("skipped_excluded"))
        if self.get("warnings") > 0:
            logging.warning("总警告数: %s", self.get("warnings"))
        if self.get("errors") > 0:
            logging.error("总错误数: %s", self.get("errors"))


def setup_logging(verbose: bool = False, use_color: bool | None = None) -> None:
    """
    配置根日志记录器
    如果 use_color 为 None，则根据 TTY 检测
    """
    if use_color is None:
        use_color = sys.stdout.isatty()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(ColorFormatter(use_color=use_color))

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.DEBUG if verbose else logging.INFO)


def _log_and_count_error(stats, message, *args):
    """记录错误日志并增加错误计数"""
    logging.error(message, *args)
    stats.increment("errors")


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
        stats.increment("added_groups")
        return True
    except subprocess.CalledProcessError as e:
        # 在冲突解决过程中，tuckr 命令失败是预期的行为，不视为错误
        if not is_conflict_resolution:
            _log_and_count_error(
                stats,
                "  执行 'tuckr add %s' 时出错 (返回码 %s): %s",
                group_name,
                e.returncode,
                e.stderr.strip(),
            )
            logging.debug("命令标准输出 (部分):\n%s", (e.stdout or "").strip())
        else:
            logging.info(
                "  'tuckr add %s' 未成功 (预期的行为): %s",
                group_name,
                e.stderr.strip(),
            )
        return False
    except FileNotFoundError:
        _log_and_count_error(
            stats, "  在PATH中找不到 'tuckr'。请确保已安装二进制文件并设置PATH。"
        )
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
        stats.increment("renamed_folders")
    except Exception as e:
        _log_and_count_error(
            stats,
            "  重命名 '%s' 时出错: %s。跳过此组的 tuckr add。",
            original_path,
            e,
        )
        return False  # 表示失败

    logging.warning(
        "  通过运行 'tuckr add %s' 来解决 '%s' 的冲突。",
        group_name,
        group_name,
    )
    return _run_tuckr_add(group_name, exclude_groups, stats, is_conflict_resolution=True)


def _process_symlinked_groups(status_data, stats):
    """处理并记录已链接的组"""
    symlinked_groups = status_data.get("symlinked", [])
    if symlinked_groups:
        logging.info("已成功链接的组: %s", ", ".join(symlinked_groups))
        stats.increment("symlinked_printed", len(symlinked_groups))


def _process_unsupported_groups(status_data, stats):
    """处理并记录不支持的组"""
    unsupported_groups = status_data.get("unsupported", [])
    if unsupported_groups:
        for group in unsupported_groups:
            logging.warning("组 '%s' 不支持当前平台/条件", group)
            stats.increment("unsupported_printed")


def _process_non_existent_groups(status_data, stats):
    """处理并记录不存在的组"""
    non_existent_groups = status_data.get("nonexistent", []) or status_data.get(
        "non_existent", []
    )
    if non_existent_groups:
        for group in non_existent_groups:
            logging.warning("组 '%s' 不存在 (检查拼写或缺失的dotfiles)", group)
            stats.increment("non_existent_printed")


def _get_detailed_group_status(group, stats):
    """获取单个组的详细状态，处理潜在的错误"""
    try:
        detailed_result = subprocess.run(
            ["tuckr", "status", group, "--json"],
            capture_output=True,
            text=True,
        )
        if detailed_result.stdout:
            return json.loads(detailed_result.stdout)
        else:
            logging.warning("无法获取组 '%s' 的状态输出", group)
            stats.increment("warnings")
            return None
    except json.JSONDecodeError as e:
        _log_and_count_error(stats, "解码组 '%s' 的详细JSON时出错: %s", group, e)
        return None
    except FileNotFoundError:
        _log_and_count_error(stats, "为组 '%s' 获取状态时找不到 'tuckr' 命令", group)
        return None


def _find_project_folder(group, conflict_list):
    """从冲突文件路径推断项目文件夹"""
    first_target_path = conflict_list[0]["target_path"]
    project_folder_path = os.path.dirname(first_target_path)
    # 尝试向上查找直到找到包含组名的目录
    while project_folder_path != "/":
        if os.path.basename(project_folder_path) == group:
            return project_folder_path
        project_folder_path = os.path.dirname(project_folder_path)
    return None


def _attempt_conflict_resolution(group, backup_suffix, exclude_groups, stats):
    """
    尝试通过重命名和重新链接来解决组的冲突。

    之所以需要多次重试，是因为一个组可能在多个不相关的目录中存在冲突
    （例如，一个在 ~/.config/，另一个在 ~/.local/share/）。
    每次循环解决一个主要的冲突目录，然后重新获取状态，直到所有冲突都解决。
    """
    # 初始状态获取
    detailed_status = _get_detailed_group_status(group, stats)
    if not detailed_status:
        return

    # 设置最大重试次数以防止无限循环。
    # 这个值是一个固定的安全上限，通常足以处理具有多个冲突点的复杂组。
    max_retries = 5
    retry_count = 0
    while retry_count < max_retries:
        group_conflicts = detailed_status.get("conflicts", {}).get(group, [])
        if not group_conflicts:
            logging.info("  组 '%s' 的冲突已解决", group)
            stats.increment("not_symlinked_processed")
            return

        project_folder = _find_project_folder(group, group_conflicts)
        if project_folder:
            logging.debug("  检测到项目文件夹: %s", project_folder)
            _handle_project_folder_backup(
                project_folder, group, backup_suffix, exclude_groups, stats
            )
        else:
            logging.warning("无法找到组 '%s' 的项目根目录", group)
            stats.increment("warnings")
            return  # 无法解决，退出

        # 重新获取状态以检查冲突是否解决
        detailed_status = _get_detailed_group_status(group, stats)
        if not detailed_status:
            return  # 无法获取状态，退出

        retry_count += 1

    # 最后检查一次
    if not detailed_status.get("conflicts", {}).get(group, []):
        logging.info("  组 '%s' 的冲突已解决", group)
        stats.increment("not_symlinked_processed")
    else:
        logging.warning("  组 '%s' 可能仍有冲突未能解决", group)


def _handle_single_unlinked_group(group, backup_suffix, exclude_groups, stats):
    """处理单个未链接的组：检查冲突或直接链接"""
    detailed_status = _get_detailed_group_status(group, stats)
    if not detailed_status:
        return

    group_conflicts = detailed_status.get("conflicts", {}).get(group)

    if group_conflicts:
        logging.info("处理冲突组: %s", group)
        _attempt_conflict_resolution(group, backup_suffix, exclude_groups, stats)
    else:
        logging.info("链接组: %s", group)
        if _run_tuckr_add(group, exclude_groups, stats, is_conflict_resolution=False):
            logging.debug("成功链接 %s", group)
            stats.increment("not_symlinked_processed")


def _process_not_symlinked_groups(status_data, backup_suffix, exclude_groups, stats):
    """处理所有未链接的组"""
    not_symlinked_groups = status_data.get("not_symlinked", [])
    logging.debug("未链接组数量: %d", len(not_symlinked_groups))
    for group in not_symlinked_groups:
        if group in exclude_groups:
            logging.warning("跳过排除的组 '%s'", group)
            stats.increment("skipped_excluded")
            continue
        _handle_single_unlinked_group(group, backup_suffix, exclude_groups, stats)


def process_conflicts(json_input_str, backup_suffix, exclude_groups):
    """
    处理JSON状态，执行备份/重命名，并尝试链接dotfiles
    """
    stats = Stats()
    try:
        status_data = json.loads(json_input_str)
        logging.debug("解析的JSON键: %s", list(status_data.keys()))
    except json.JSONDecodeError as e:
        _log_and_count_error(stats, "解码JSON输入时出错: %s", e)
        stats.log_summary()
        return stats

    _process_symlinked_groups(status_data, stats)
    _process_not_symlinked_groups(status_data, backup_suffix, exclude_groups, stats)
    _process_unsupported_groups(status_data, stats)
    _process_non_existent_groups(status_data, stats)

    stats.log_summary()
    return stats


def valid_suffix(s):
    """校验后缀是否为非空字符串"""
    if not s.strip():
        raise argparse.ArgumentTypeError("后缀不能为空或只包含空白字符。")
    return s


def main():
    epilog_text = """
使用示例:
  1. 基本用法 (从管道读取):
     tuckr status --json | python3 tuckr.py

  2. 自定义备份后缀并排除某些组:
     tuckr status --json | python3 tuckr.py --suffix my-backup --exclude nvim zsh

  3. 启用详细日志输出:
     tuckr status --json | python3 tuckr.py --verbose
"""
    parser = argparse.ArgumentParser(
        description="处理tuckr状态JSON输出以备份和解决冲突。",
        epilog=epilog_text,
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "--suffix",
        default="backup",
        type=valid_suffix,
        metavar="SUFFIX",
        help="追加到重命名备份文件/文件夹的后缀。\n(默认: 'backup')",
    )
    parser.add_argument(
        "--exclude",
        nargs="*",
        default=[],
        metavar="GROUP",
        help="在运行tuckr add时要排除的组列表。",
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

    # 检查是否有来自stdin的输入
    if sys.stdin.isatty():
        logging.error("错误：此脚本需要从stdin接收tuckr的JSON输出。")
        logging.info("请尝试这样运行: tuckr status --json | python3 %s", sys.argv[0])
        sys.exit(1)

    logging.info("正在等待来自stdin的JSON输入...")
    json_input = sys.stdin.read()

    if not json_input.strip():
        logging.error("错误：从stdin读取的输入为空。没有要处理的数据。")
        sys.exit(1)

    process_conflicts(json_input, args.suffix, args.exclude)


if __name__ == "__main__":
    main()
