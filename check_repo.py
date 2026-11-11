#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gitee 上传前仓库合规自检。

用法：
    python check_repo.py

检查项（全部为文件层面的确定性检查，不涉及提示词行为验证）：
  1. 仓库必备文件是否齐全
  2. SKILL.md 的 YAML frontmatter 必填字段
  3. 文本文件是否为 UTF-8 无 BOM、LF 换行、无 NUL 字节（已知二进制资产只计体积）
  4. 单文件 <= 50 MB、仓库总体积 <= 500 MB（Gitee 社区版保守配额）
  5. 是否夹带本机绝对路径或疑似凭据
  6. Markdown 相对链接是否指向会进入版本库的文件（按 git ls-files 判定；非 Git 仓库回退磁盘）
  7. README.md 是否保持纯 Markdown（无裸 HTML 标签 / 命令块内的尖括号占位符）
  8. 发布版本号一致性（CHANGELOG vs 两个构建脚本 VERSION）；README 使用者可见面不得出现版本号

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
    "eval-checklist.md",
    "check_repo.py",
    "examples/few-shot.md",
    "examples/math-g5-fraction-pie.html",
    "examples/svg-animation-template.html",
]

TEXT_SUFFIXES = {
    ".md", ".html", ".py", ".txt", ".yml", ".yaml", ".json", ".svg", ".css", ".js",
}
TEXT_NAMES = {".gitignore", ".gitattributes", ".gitkeep", "LICENSE", "Makefile"}
# 合法发布资产：只计体积与单文件大小，不做文本层检查（含 NUL 字节属正常）
BINARY_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".ico", ".zip", ".pdf"}
SKIP_DIRS = {
    ".git", ".idea", ".vscode", ".workbuddy", ".codebuddy",
    "__pycache__", ".venv", "node_modules", "dist", "build",
}

# Gitee 社区版（个人用户）保守配额
MAX_SINGLE = 50 * 1024 * 1024       # 单文件 50 MB
MAX_TOTAL = 500 * 1024 * 1024       # 单仓库 500 MB

SENSITIVE_PATTERNS = [
    (re.compile(r"[A-Za-z]:[\\/]Users[\\/]", re.I), "Windows 本机绝对路径", "path"),
    (re.compile(r"/(?:Users|home)/[A-Za-z0-9._-]+/"), "Unix 本机绝对路径", "path"),
    (re.compile(r"(?:password|passwd|api_key|secret|access_token)\s*[:=]\s*\S+", re.I), "疑似凭据赋值", "cred"),
    (re.compile(r"\b(?:ghp_|gho_|github_pat_)[A-Za-z0-9_]{20,}"), "疑似访问令牌", "cred"),
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
# 任意位置的软件版本号，用于检查使用者可见文档（发布清单 7-1）
ANY_VER_RE = re.compile(r"v\d+\.\d+\.\d+")

errors: list[str] = []
warnings: list[str] = []


def is_text_file(p: Path) -> bool:
    return p.suffix.lower() in TEXT_SUFFIXES or p.name in TEXT_NAMES


def git_tracked() -> set[str] | None:
    """返回会进入版本库的相对路径（posix）集合；非 Git 仓库或 Git 不可用时返回 None。

    用 git ls-files 而不是磁盘遍历，这样被 .gitignore 忽略的本地目录
    （evals/、release/package/、.idea/ 等）不会被误当成仓库内容。
    """
    try:
        top = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=ROOT, capture_output=True, text=True, check=True, timeout=10,
        )
        if Path(top.stdout.strip()).resolve() != ROOT.resolve():
            return None
        listing = subprocess.run(
            ["git", "-c", "core.quotepath=false", "ls-files",
             "--cached", "--others", "--exclude-standard"],
            cwd=ROOT, capture_output=True, text=True, check=True, timeout=10,
        )
        return {
            line.strip().replace(chr(92), "/")
            for line in listing.stdout.splitlines() if line.strip()
        }
    except (OSError, subprocess.SubprocessError):
        return None


def all_files(tracked: set[str] | None) -> list[Path]:
    """收集会进入版本库的文件；非 Git 仓库时回退磁盘遍历并跳过本地状态目录。"""
    if tracked is not None:
        files = sorted(p for p in (ROOT / rel for rel in tracked) if p.is_file())
        if files:
            return files

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
        if p.suffix.lower() in BINARY_SUFFIXES:
            continue
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


# 内部运维记录：本机路径是记录内容的一部分（两机协作约定），只豁免路径类检查。
# 凭据 / 令牌类检查对包括白名单文件在内的全部文件仍然生效。
SENSITIVE_EXEMPT_FILES = {"开发修改记录.md"}
EXEMPT_KINDS = {"path"}


def check_sensitive(files: list[Path]) -> None:
    for p in files:
        if p == SELF or not is_text_file(p):
            continue
        rel = p.relative_to(ROOT).as_posix()
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for pattern, label, kind in SENSITIVE_PATTERNS:
            # 白名单文件只豁免本机绝对路径；凭据 / 令牌检查不豁免。
            if kind in EXEMPT_KINDS and rel in SENSITIVE_EXEMPT_FILES:
                continue
            if pattern.search(text):
                errors.append(f"{label}：{rel}")


def check_links(files: list[Path], tracked: set[str] | None) -> None:
    """Markdown 相对链接必须指向会进入版本库的文件或目录。

    按 git ls-files 判定，避免「本机恰好有 evals/ 目录所以自检 PASS、
    clone 后链接却是死链」这类判定盲点；非 Git 仓库回退磁盘存在性。
    目录链接只要其下有受控文件即视为可达（如 examples/、release/）。
    """
    def reachable(rel: str) -> bool:
        rel = rel.rstrip("/")
        if not rel:
            return True
        if tracked is None:
            return (ROOT / rel).exists()
        return rel in tracked or any(f.startswith(rel + "/") for f in tracked)

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
            candidates = []
            for base in (p.parent, ROOT):
                try:
                    candidates.append(
                        (base / t).resolve().relative_to(ROOT.resolve()).as_posix()
                    )
                except ValueError:
                    continue  # 指向仓库外的路径
            if not any(reachable(c) for c in candidates):
                errors.append(f"Markdown 链接目标不在版本库内：{rel} → {t}")


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
    """发布版本号一致性：CHANGELOG 首个发布版本 = 两个构建脚本的 VERSION。

    版本号是维护侧标识（见 release/发布清单.md 7-1）：维护层保留完整版本号，
    使用者可见的 README.md 不出现 vX.Y.Z；链接地址里的 ZIP 文件名不算——
    附件名与哈希校验需要它，按 7-1 允许留在地址里。
    真人试用说明.md 里用于区分该测哪份的消歧版本号，不参与本检查。
    """
    cl = ROOT / "CHANGELOG.md"
    if not cl.is_file():
        return
    m = RELEASE_VER_RE.search(cl.read_text(encoding="utf-8"))
    if not m:
        errors.append("CHANGELOG.md 未找到形如 '## vX.Y.Z' 的发布版本条目")
        return
    ver = m.group(1)
    num = ver.lstrip("v")  # 构建脚本的 VERSION 不带 v 前缀
    for rel in ("release/build_release.py", "release/build_expert.py"):
        p = ROOT / rel
        if p.is_file() and f'VERSION = "{num}"' not in p.read_text(encoding="utf-8"):
            errors.append(f"{rel} 的 VERSION 与当前发布版本 {ver} 不一致")
    readme = ROOT / "README.md"
    if readme.is_file():
        text = readme.read_text(encoding="utf-8")
        visible = re.sub(r"\]\([^)]*\)", "]", text)  # 剔除链接地址
        if ANY_VER_RE.search(visible):
            errors.append("README.md 可见文字出现软件版本号（发布清单 7-1：使用者可见面不显示版本号）")
    print(f"  · 当前发布版本 {ver}（维护层校验；README 不显示版本号）")


def main() -> int:
    print("Gitee 仓库合规自检")
    print(f"根目录：{ROOT}\n")

    tracked = git_tracked()
    files = all_files(tracked)
    print("[1/8] 必备文件")
    check_required()
    print("[2/8] SKILL.md frontmatter")
    check_frontmatter()
    print("[3/8] 编码 / BOM / 换行 / 体积")
    check_encoding_and_size(files)
    print("[4/8] 本机路径与凭据")
    check_sensitive(files)
    print("[5/8] Markdown 相对链接")
    check_links(files, tracked)
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
