#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一键发布脚本 — 自动更新版本、构建、发布到 PyPI

用法:
    python scripts/publish.py patch      # 发布补丁版本 0.1.0 -> 0.1.1
    python scripts/publish.py minor      # 发布次版本   0.1.0 -> 0.2.0
    python scripts/publish.py major      # 发布主版本   0.1.0 -> 1.0.0
    python scripts/publish.py 1.2.3      # 发布指定版本

选项:
    --dry-run    只构建不发布，不提交 git
    --test-pypi  发布到 TestPyPI（测试用）
    --no-git     不执行 git 操作
"""

import os
import re
import subprocess
import sys
import shutil
from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent.resolve()

# 需要更新版本号的文件
VERSION_FILES = [
    ("pyproject.toml", r'version\s*=\s*"([^"]+)"'),
    ("qbu_crawler/__init__.py", r'__version__\s*=\s*"([^"]+)"'),
]


def run_cmd(cmd: str, check: bool = True, cwd: Path = None) -> subprocess.CompletedProcess:
    """执行命令并打印"""
    print(f"  $ {cmd}")
    result = subprocess.run(
        cmd,
        shell=True,
        cwd=cwd or PROJECT_ROOT,
        capture_output=False
    )
    if check and result.returncode != 0:
        print(f"\n  命令执行失败: {cmd}")
        sys.exit(1)
    return result


def get_current_version() -> str:
    """从 pyproject.toml 获取当前版本号"""
    pyproject = PROJECT_ROOT / "pyproject.toml"
    content = pyproject.read_text(encoding="utf-8")
    match = re.search(r'version\s*=\s*"([^"]+)"', content)
    if match:
        return match.group(1)
    raise ValueError("无法从 pyproject.toml 读取版本号")


def parse_version(version: str) -> tuple:
    """解析版本号为 (major, minor, patch)"""
    parts = version.split(".")
    if len(parts) != 3:
        raise ValueError(f"无效的版本号格式: {version}")
    return int(parts[0]), int(parts[1]), int(parts[2])


def calc_new_version(current: str, bump_type: str) -> str:
    """根据类型计算新版本号"""
    major, minor, patch = parse_version(current)

    if bump_type == "patch":
        return f"{major}.{minor}.{patch + 1}"
    elif bump_type == "minor":
        return f"{major}.{minor + 1}.0"
    elif bump_type == "major":
        return f"{major + 1}.0.0"
    else:
        # 直接使用指定的版本号
        parse_version(bump_type)  # 验证格式
        return bump_type


def update_version_in_file(filepath: str, pattern: str, new_version: str) -> bool:
    """更新文件中的版本号"""
    path = PROJECT_ROOT / filepath
    if not path.exists():
        print(f"    [跳过] {filepath} 不存在")
        return False

    content = path.read_text(encoding="utf-8")

    def replacer(match):
        full_match = match.group(0)
        old_version = match.group(1)
        return full_match.replace(old_version, new_version)

    new_content, count = re.subn(pattern, replacer, content, count=1)

    if count > 0:
        path.write_text(new_content, encoding="utf-8")
        print(f"    [更新] {filepath}")
        return True
    else:
        print(f"    [跳过] {filepath} 未找到版本号")
        return False


def step_clean():
    """清理构建目录"""
    print("\n[1/5] 清理构建目录...")
    dirs_to_clean = ["dist", "build", "*.egg-info"]
    cleaned = False
    for pattern in dirs_to_clean:
        for path in PROJECT_ROOT.glob(pattern):
            if path.is_dir():
                shutil.rmtree(path)
                print(f"    删除: {path.name}")
                cleaned = True
    if not cleaned:
        print("    无需清理")


def step_bump_version(bump_type: str) -> str:
    """更新版本号"""
    current = get_current_version()
    new_version = calc_new_version(current, bump_type)

    print(f"\n[2/5] 更新版本号: {current} -> {new_version}")

    for filepath, pattern in VERSION_FILES:
        update_version_in_file(filepath, pattern, new_version)

    return new_version


def step_build():
    """构建包"""
    print("\n[3/5] 构建包...")
    run_cmd("uv build")


def step_git(version: str):
    """Git 提交和打标签"""
    print(f"\n[4/5] Git 提交和打标签...")
    run_cmd("git add -A")
    run_cmd(f'git commit -m "chore: release v{version}"')
    run_cmd(f"git tag v{version}")
    print(f"    创建标签: v{version}")


def step_publish(test_pypi: bool = False):
    """发布到 PyPI"""
    print("\n[5/5] 发布到 PyPI...")
    if test_pypi:
        run_cmd("uv run twine upload --repository testpypi dist/*")
    else:
        run_cmd("uv run twine upload dist/*")


def check_prerequisites():
    """检查前置条件"""
    print("检查前置条件...")

    # 检查 uv 是否可用
    result = subprocess.run("uv --version", shell=True, capture_output=True)
    if result.returncode != 0:
        print("  - uv 未安装")
        print("  请参考 https://docs.astral.sh/uv/ 安装 uv")
        sys.exit(1)
    print(f"  + uv ({result.stdout.decode().strip()})")

    # 检查是否在 git 仓库中
    git_dir = PROJECT_ROOT / ".git"
    if not git_dir.exists():
        print("  - 当前目录不是 git 仓库")
        sys.exit(1)
    print("  + Git 仓库")

    # 检查 pyproject.toml
    if not (PROJECT_ROOT / "pyproject.toml").exists():
        print("  - pyproject.toml 不存在")
        sys.exit(1)
    print("  + pyproject.toml 存在")


def main():
    # 解析参数
    args = sys.argv[1:]
    if not args or "-h" in args or "--help" in args:
        print(__doc__)
        sys.exit(0)

    dry_run = "--dry-run" in args
    test_pypi = "--test-pypi" in args
    no_git = "--no-git" in args

    # 获取版本类型
    bump_type = None
    for arg in args:
        if not arg.startswith("--"):
            bump_type = arg.lower()
            break

    if not bump_type:
        print("错误: 请指定版本类型 (patch/minor/major/x.y.z)")
        sys.exit(1)

    # 打印标题
    print("=" * 50)
    print("  Qbu-Crawler 一键发布")
    print("=" * 50)

    current_version = get_current_version()
    new_version = calc_new_version(current_version, bump_type)

    print(f"\n版本: {current_version} -> {new_version}")

    if dry_run:
        print("模式: Dry Run (只构建不发布)")
    if test_pypi:
        print("目标: TestPyPI")
    if no_git:
        print("选项: 跳过 Git 操作")

    # 检查前置条件
    print()
    check_prerequisites()

    # 执行发布流程
    step_clean()
    version = step_bump_version(bump_type)
    step_build()

    if not dry_run:
        if not no_git:
            step_git(version)
        step_publish(test_pypi)
        if not no_git:
            print("\n[推送] 推送到远程仓库...")
            run_cmd("git push")
            run_cmd("git push --tags")

    # 完成
    print("\n" + "=" * 50)
    if dry_run:
        print("  Dry Run 完成!")
        print("=" * 50)
        print(f"\n构建产物在 dist/ 目录")
    else:
        print("  发布完成!")
        print("=" * 50)
        print(f"\n用户现在可以通过以下命令使用:")
        if test_pypi:
            print(f"  pip install --index-url https://test.pypi.org/simple/ qbu-crawler")
        else:
            print(f"  uvx qbu-crawler")
            print(f"  # 或")
            print(f"  pip install qbu-crawler")


if __name__ == "__main__":
    main()
