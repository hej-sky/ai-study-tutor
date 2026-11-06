#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gitee 上传前仓库合规自检。

用法：
    python check_repo.py

检查项（全部为文件层面的确定性检查，不涉及提示词行为验证）：
  1. 仓库必备文件是否齐全
  2. SKILL.md 的 YAML frontmatter 必填字段
  3. 文本文件是否为 UTF-8 无 BOM、LF 换行、无 NUL 字节
  4. 单文件 <= 50 MB、仓库总体积 <= 500 MB（Gitee 社区版保守配额）
  5. 是否夹带本机绝对路径或疑似凭据
  6. Markdown 相对链接是否指向真实存在的文件
  7. README.md 是否保持纯 Markdown（无裸 HTML 标签 / 命令块内的尖括号占位符）
  8. 发布版本号一致性（CHANGELOG 首个发布版本 vs README / system-prompt 标注）

扫描范围：仅「会进入版本库」的文件。仓库已 git init 时以 git 判定为准（自动尊重
.gitignore），IDE 自动生成的 .idea/ 等本地状态文件不参与检查；尚未 git init 时
回退到磁盘遍历并跳过常见本地状态目录。

参考配额：
  https://help.gitee.com/questions/Gitee%E4%BA%A7%E5%93%81%E9%85%8D%E9%A2%9D%E8%AF%B4%E6%98%8E
  https://gitee.com/oschina/git-osc/wikis/FAQ
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SELF = Path(__file__).resolve()

REQUIRED = [
    "SKILL.md",
    "README.md",
    "LICENSE",
    "CHANGELOG.md",
    ".gitignore",
    ".gitattributes",
    "system-prompt.md",
    "usage-guide.md",
    "check_repo.py",
    "examples/grade2-fraction-lesson.md",
    "examples/guided-dialogue.md",
    "examples/math-g5-fraction-pie.html",
    "examples/svg-animation-template.html",
]

TEXT_SUFFIXES = {
    ".md", ".html", ".py", ".txt", ".yml", ".yaml", ".json", ".svg", ".css", ".js",
}
TEXT_NAMES = {".gitignore", ".gitattributes", ".gitkeep", "LICENSE", "Makefile"}
SKIP_DIRS = {
    ".git", ".idea", ".vscode", ".workbuddy", ".codebuddy",
    "__pycache__", ".venv", "node_modules", "dist", "build",
}

# Gitee 社区版（个人用户）保守配额
MAX_SINGLE = 50 * 1024 * 1024       # 单文件 50 MB
MAX_TOTAL = 500 * 1024 * 1024       # 单仓库 500 MB

SENSITIVE_PATTERNS = [
    (re.compile(r"[A-Za-z]:[\\/]Users[\\/]", re.I), "Windows 本机绝对路径"),
    (re.compile(r"/(?:Users|home)/[A-Za-z0-9._-]+/"), "Unix 本机绝对路径"),
    (re.compile(r"(?:password|passwd|api_key|secret|access_token)\s*[:=]\s*\S+", re.I), "疑似凭据赋值"),
    (re.compile(r"\b(?:ghp_|gho_|github_pat_)[A-Za-z0-9_]{20,}"), "疑似访问令牌"),
]

LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")

# 常见 HTML 标签。只用于检测 README 正文（代码块与行内代码会被剔除）。
# Gitee 的 Markdown 渲染器对 HTML 属性支持不一致，仓库首页应保持纯 Markdown。
HTML_TAG_RE = re.compile(
    r"</?(?:div|span|p|a|img|br|center|table|tr|td|th|h[1-6]|style|script|"
    r"iframe|font|section|article|header|footer|ul|ol|li|b|i|em|strong|hr)\b[^>]*>",
    re.I,
)

# CHANGELOG 中首个「## vX.Y.Z」即当前发布版本；附录里的开发期编号用 ### 前缀，不会命中。
RELEASE_VER_RE = re.compile(r"^## (v\d+\.\d+\.\d+)\b", re.M)

errors: list[str] = []
warnings: list[str] = []


def is_text_file(p: Path) -> bool:
    return p.suffix.lower() in TEXT_SUFFIXES or p.name in TEXT_NAMES


def all_files() -> list[Path]:
    """收集会进入版本库的文件。

    已初始化的仓库优先用 git 判定，这样 .gitignore 忽略掉的 IDE 本地配置
    （如 .idea/ 里的 CRLF 文件）不会被误判为仓库内容不合规；尚未 git init
    时回退到磁盘遍历，跳过常见本地状态目录。
    """
    try:
        top = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=ROOT, capture_output=True, text=True, check=True, timeout=10,
        )
        if Path(top.stdout.strip()).resolve() == ROOT.resolve():
            listing = subprocess.run(
                ["git", "-c", "core.quotepath=false", "ls-files",
                 "--cached", "--others", "--exclude-standard"],
                cwd=ROOT, capture_output=True, text=True, check=True, timeout=10,
            )
            paths = [ROOT / line for line in listing.stdout.splitlines() if line.strip()]
            if paths:
                return sorted(p for p in paths if p.is_file())
    except (OSError, subprocess.SubprocessError):
        pass

    result = []
    for p in ROOT.rglob("*"):
        if not p.is_file():
            continue
        if any(part in SKIP_DIRS for part in p.relative_to(ROOT).parts):
            continue
        result.append(p)
    return result


def check_required() -> None:
    for rel in REQUIRED:
        if not (ROOT / rel).is_file():
            errors.append(f"缺少必备文件：{rel}")


def check_frontmatter() -> None:
    p = ROOT / "SKILL.md"
    if not p.is_file():
        return
    text = p.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        errors.append("SKILL.md 缺少 YAML frontmatter（文件须以 --- 开头）")
        return
    end = text.find("\n---", 4)
    if end == -1:
        errors.append("SKILL.md 的 frontmatter 未闭合")
        return
    block = text[4:end]
    for key in ("name", "description", "agent_created", "license"):
        if not re.search(rf"^{key}\s*:", block, re.M):
            errors.append(f"SKILL.md frontmatter 缺少字段：{key}")


def check_encoding_and_size(files: list[Path]) -> None:
    total = 0
    for p in files:
        raw = p.read_bytes()
        total += len(raw)
        rel = p.relative_to(ROOT).as_posix()
        if len(raw) > MAX_SINGLE:
            errors.append(f"单文件超过 50 MB：{rel} ({len(raw) / 1024 / 1024:.1f} MB)")
        if b"\x00" in raw:
            errors.append(f"疑似二进制文件混入文本检查：{rel}")
            continue
        if raw.startswith(b"\xef\xbb\xbf"):
            errors.append(f"存在 UTF-8 BOM：{rel}")
        if b"\r\n" in raw:
            errors.append(f"含 CRLF 换行（应为 LF）：{rel}")
        if is_text_file(p):
            try:
                raw.decode("utf-8")
            except UnicodeDecodeError as exc:
                errors.append(f"非 UTF-8 编码：{rel}（{exc}）")
    if total > MAX_TOTAL:
        errors.append(f"仓库总体积超过 500 MB：{total / 1024 / 1024:.1f} MB")
    print(f"  · 文件总数 {len(files)} 个，总体积 {total / 1024:.1f} KB")


def check_sensitive(files: list[Path]) -> None:
    for p in files:
        if p == SELF or not is_text_file(p):
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        rel = p.relative_to(ROOT).as_posix()
        for pattern, label in SENSITIVE_PATTERNS:
            if pattern.search(text):
                errors.append(f"{label}：{rel}")


def check_links(files: list[Path]) -> None:
    for p in files:
        if p.suffix.lower() != ".md":
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        rel = p.relative_to(ROOT).as_posix()
        for target in LINK_RE.findall(text):
            t = target.strip().split("#", 1)[0].strip()
            if not t or t.startswith(("http://", "https://", "mailto:", "#")):
                continue
            if "<" in t or "~" in t or "*" in t:
                continue  # 占位符或示例路径
            c1 = (p.parent / t).resolve()
            c2 = (ROOT / t).resolve()
            if not c1.exists() and not c2.exists():
                errors.append(f"Markdown 链接目标不存在：{rel} → {t}")


def check_readme_markdown() -> None:
    """README 首页须为纯 Markdown。

    两类问题会被拦下：
      · 裸 HTML 标签（如用于居中的 div 标签及其属性）—— Gitee 渲染行为不一致；
      · bash 代码块中的尖括号占位符（如 <你的用户名>）—— shell 会当作输入重定向。
    提示词里的 <角色与教学理念> 等自定义结构标记不在本检查范围内（它们在代码块内且非 HTML 标签名）。
    """
    p = ROOT / "README.md"
    if not p.is_file():
        return
    text = p.read_text(encoding="utf-8")

    # 剔除围栏代码块（保留行数以便报错定位），再剔除行内代码
    outside = re.sub(r"```.*?```", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S)
    outside = re.sub(r"`[^`\n]*`", lambda m: " " * len(m.group(0)), outside)
    for m in HTML_TAG_RE.finditer(outside):
        line = outside[:m.start()].count("\n") + 1
        errors.append(
            f"README.md 第 {line} 行含裸 HTML 标签 {m.group(0)!r}"
            "（Gitee 渲染行为不一致，请改用纯 Markdown）"
        )

    for block in re.findall(r"```(?:bash|sh|shell)\n(.*?)```", text, flags=re.S):
        for m in re.finditer(r"<[^>\n]+>", block):
            errors.append(
                f"README.md 命令示例中含尖括号占位符 {m.group(0)!r}"
                "（shell 会视作输入重定向，请改为 ASCII 占位符）"
            )


def check_release_version() -> None:
    """对外发布版本号须一致：CHANGELOG 首个发布版本 = README 与 system-prompt 的标注。

    开发期内部编号（v1 ~ v4.5.1）保存在 CHANGELOG 附录与测试报告中，不参与此检查。
    """
    cl = ROOT / "CHANGELOG.md"
    if not cl.is_file():
        return
    m = RELEASE_VER_RE.search(cl.read_text(encoding="utf-8"))
    if not m:
        errors.append("CHANGELOG.md 未找到形如 '## vX.Y.Z' 的发布版本条目")
        return
    ver = m.group(1)
    for rel in ("README.md", "system-prompt.md"):
        p = ROOT / rel
        if p.is_file() and ver not in p.read_text(encoding="utf-8"):
            errors.append(f"{rel} 未标注当前发布版本 {ver}")
    print(f"  · 当前发布版本 {ver}")


def main() -> int:
    print("Gitee 仓库合规自检")
    print(f"根目录：{ROOT}\n")

    files = all_files()
    print("[1/8] 必备文件")
    check_required()
    print("[2/8] SKILL.md frontmatter")
    check_frontmatter()
    print("[3/8] 编码 / BOM / 换行 / 体积")
    check_encoding_and_size(files)
    print("[4/8] 本机路径与凭据")
    check_sensitive(files)
    print("[5/8] Markdown 相对链接")
    check_links(files)
    print("[6/8] README 纯 Markdown")
    check_readme_markdown()
    print("[7/8] 发布版本号一致性")
    check_release_version()
    print("[8/8] 汇总")

    if warnings:
        for w in warnings:
            print(f"  [WARN] {w}")
    if errors:
        print(f"\n结果：FAIL（{len(errors)} 项）")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("\n结果：PASS —— 全部检查项通过，可提交并推送到 Gitee。")
    print("提示：本脚本只验证文件层面，不验证提示词在目标模型上的行为。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
