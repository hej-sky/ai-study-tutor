#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从 Gitee 权威仓库派生「助力学」发布物料：
  1. package/           上架包展开目录（ZIP 内容，根目录第一层即 SKILL.md）
  2. ai-study-tutor-v{VERSION}.zip  可上传到 WorkBuddy 开放平台 / 挂 Gitee Release
  3. avatar-512.png     512×512 技能头像
  4. 控制台自检：ZIP 结构、frontmatter、引用路径、体积、头像

单一权威源：本仓库根目录（脚本会自动定位）。本脚本只读取仓库文档，不修改提示词正文。
唯一构建入口：仓库 release/build_release.py；仓库外不再保留第二份发布工作区，避免两份物料分叉。
升版本时改 VERSION，重跑本脚本，再同步 release/发布清单.md 里的版本号。
"""
from __future__ import annotations

import math
import re
import shutil
import struct
import zlib
import zipfile
from pathlib import Path

OUT = Path(__file__).resolve().parent
PKG = OUT / "package"


def find_repo() -> Path:
    """从脚本所在位置向上逐级定位仓库根（同时含 SKILL.md 与 system-prompt.md）。"""
    for c in (OUT, *OUT.parents):
        if (c / "SKILL.md").is_file() and (c / "system-prompt.md").is_file():
            return c
    raise SystemExit("找不到权威仓库（需含 SKILL.md 与 system-prompt.md）")


REPO = find_repo()
VERSION = "1.5.0"
SLUG = "ai-study-tutor"
REPO_URL = "https://gitee.com/hejsky/ai-study-tutor"
ZIP_NAME = f"{SLUG}-v{VERSION}.zip"
AVATAR_NAME = "avatar-512.png"

# 运行必需、原样复制的文件
COPY_AS_IS = [
    "examples/math-g5-fraction-pie.html",
    "examples/svg-animation-template.html",
]

# 上架包不携带的维护类文件（避免审核困惑 / 死链 / SkillHub 明确禁止 LICENSE）
EXCLUDE = {
    "README.md", "CHANGELOG.md", "LICENSE", ".gitignore", ".gitattributes",
    "check_repo.py", "eval-checklist.md",
}

FRONTMATTER = """---
name: ai-study-tutor
display_name: 助力学（AI 学习助教）
display_name_en: AI Study Tutor
description: 当学生、家长或老师提供课程、章节、知识点、教材照片或作业题，希望按年级与教材版本获得讲解、示意图、分层习题、批改与复习安排时使用本 Skill。触发词：帮我学、讲讲这个知识点、这道题不会、听不懂、拍照、出点题、帮我改、复习。
description_zh: 面向 1~12 年级、按年级与教材版本适配的 AI 学习助教，完成讲解、演示、习题、批改与复习的闭环。
description_en: An AI study tutor for grades 1-12 that adapts explanations, diagrams, tiered exercises, grading and review plans to each student's grade level and textbook edition.
version: {{VERSION}}
category: 教育学习
author: 何必再健
license: MIT
agent_created: true
examples:
  - 我上初二，物理，电流与电压、电阻的关系没听懂
  - 人教版，五年级，分数的基本性质，帮我讲讲并出点题
  - 我二年级，数学，认识分数，能不能画个图给我看
---
"""

TRIGGER_SECTION = """## 试试这样问我（触发场景示例）

用户常见的开场说法，按 `<引导模式>` 一次一问处理，不要一次抛出多个问题：

- 「我上初二，物理，电流与电压、电阻的关系没听懂」
- 「人教版，五年级，分数的基本性质，帮我讲讲并出点题」
- 「我二年级，数学，认识分数，能不能画个图给我看」

"""

PROJECT_SECTION = """## 关于本项目

本 Skill 是开源项目「助力学」的运行包，当前版本 **v{{VERSION}}**，仍处公开实践与验证阶段。完整仓库（首页说明、版本记录、规则核对清单与合规自检）见 https://gitee.com/hejsky/ai-study-tutor ；遇到问题欢迎到仓库提 issue，附上对话截图即可，不用懂代码或 git。
"""

USAGE_HEADER = """# 助力学 · 使用说明（上架包精简版）

> 本文件只保留使用者需要的部分；完整说明、版本记录与维护文档见 [Gitee 仓库](https://gitee.com/hejsky/ai-study-tutor)。当前版本 **v{{VERSION}}**，仍处公开实践阶段。

---

"""

KEEP_USAGE_SECTIONS = (
    "## 三步上手",
    "## 常见问题",
    "## 附：客观能力边界",
    "## 输入区字段与偏好",
)


def read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def write(rel: str, text: str) -> None:
    p = PKG / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text.replace("{{VERSION}}", VERSION), encoding="utf-8", newline="\n")


def build_skill_md() -> str:
    s = read("SKILL.md")
    # 1) 整块替换 frontmatter
    assert s.startswith("---\n"), "原 SKILL.md 没有 frontmatter"
    end = s.find("\n---\n", 4)
    assert end > 0, "原 SKILL.md frontmatter 未闭合"
    s = FRONTMATTER.rstrip("\n") + s[end + 4:]
    # 2) 触发示例插在「启动流程」之前
    anchor = "## 启动流程（必须按顺序）"
    assert s.count(anchor) == 1
    s = s.replace(anchor, TRIGGER_SECTION + anchor, 1)
    # 3) 删掉指向维护文件的两行（上架包内不存在）
    for line in (
        "| 要检查仓库是否符合 Gitee 上传条件 | 运行 `python check_repo.py` |\n",
        "| 部署后按固定用例与判定口径核对规则 | `eval-checklist.md` |\n",
    ):
        assert s.count(line) == 1, f"未找到表格行: {line[:30]}"
        s = s.replace(line, "", 1)
    # 4) 仓库说明改为指向线上仓库，去掉本地 README / CHANGELOG 死链
    i = s.find("## 仓库说明")
    assert i > 0
    s = s[:i] + PROJECT_SECTION
    return s


def build_usage_guide() -> str:
    s = read("usage-guide.md")
    blocks = re.split(r"(?=^## )", s, flags=re.M)
    picked = [b for b in blocks if any(b.startswith(k) for k in KEEP_USAGE_SECTIONS)]
    assert len(picked) == len(KEEP_USAGE_SECTIONS), f"章节提取数量不符: {len(picked)}"
    body = "---\n\n".join(b.strip() for b in picked)
    # 上架包内不存在的本地链接 → 指向线上仓库。只做链接转换，不改内容口径；
    # 若主文档改了措辞导致漏替换，check() 会因包内死链报 FAIL，不会静默放行。
    body = body.replace(
        "[`README.md`](README.md) 的「用哪种 AI 工具与模型」",
        f"[Gitee 仓库]({REPO_URL}) 的「用哪种 AI 工具与模型」",
    )
    body = body.replace(
        "[`eval-checklist.md`](eval-checklist.md)",
        f"[规则核对清单]({REPO_URL}/blob/master/eval-checklist.md)",
    )
    body = body.replace(
        "[`README.md`](README.md)",
        f"[Gitee 仓库]({REPO_URL})",
    )
    # 主仓库 usage-guide.md 已与 system-prompt.md 开头的权威口径一致，
    # 不再需要「内容纠错补丁」；仓库与上架包从同一份文字派生。
    return USAGE_HEADER + body + "\n"


def build_system_prompt() -> str:
    """只改写代码块外的说明文字，提示词正文（代码块内）一字不动。"""
    s = read("system-prompt.md")
    old = "> - 版本历史：`CHANGELOG.md`"
    assert s.count(old) == 1, "system-prompt.md 的版本历史说明行已变化，请复核"
    return s.replace(
        old,
        f"> - 版本历史：[Gitee 仓库 CHANGELOG]({REPO_URL}/blob/master/CHANGELOG.md)",
        1,
    )


def build_few_shot() -> str:
    s = read("examples/few-shot.md")
    old = "[`eval-checklist.md`](../eval-checklist.md)"
    assert s.count(old) == 1
    return s.replace(
        old,
        f"[规则核对清单]({REPO_URL}/blob/master/eval-checklist.md)",
        1,
    )


# ---------------------------------------------------------------- 头像（纯标准库 PNG）

def _rounded_box(x, y, cx, cy, half, radius):
    qx = abs(x - cx) - (half - radius)
    qy = abs(y - cy) - (half - radius)
    return math.hypot(max(qx, 0.0), max(qy, 0.0)) + min(max(qx, qy), 0.0) - radius


def _seg_dist(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _mix(a, b, t):
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def make_avatar(path: Path, size: int = 512, ss: int = 2) -> None:
    """暖色圆角底 + 白色打开的书 + 灯泡，纯标准库绘制，2 倍超采样抗锯齿。"""
    W = size * ss
    buf = bytearray(W * W * 4)
    c0, c1 = (255, 201, 101), (244, 110, 43)   # 渐变起止
    white = (255, 252, 246)
    # 光线线段（灯泡周围）
    rays = []
    for deg in (0, 40, 90, 140, 180, 220, 270, 320):
        a = math.radians(deg)
        r1, r2 = 76, 96
        if 200 <= deg <= 340:      # 下方留给书，不出光线
            continue
        rays.append((256 + math.cos(a) * r1, 178 + math.sin(a) * r1,
                     256 + math.cos(a) * r2, 178 + math.sin(a) * r2))

    for sy in range(W):
        y = sy / ss
        row = sy * W * 4
        for sx in range(W):
            x = sx / ss
            if _rounded_box(x, y, 256, 256, 248, 100) > 0:
                continue                                  # 背景外保持透明
            t = max(0.0, min(1.0, (x + y) / (2 * size)))
            col = _mix(c0, c1, t)
            a = 255

            # 灯泡：圆形 + 收窄的颈部 + 灯座
            bulb = math.hypot(x - 256, y - 178) <= 58
            if not bulb and 222 <= y <= 252:
                half = 30 - (y - 222) / 30 * 18
                bulb = abs(x - 256) <= half
            if not bulb and 252 <= y <= 272:
                bulb = _rounded_box(x, y, 256, 262, 18, 6) <= 0 and abs(x - 256) <= 18
            # 光线
            if not bulb:
                for ax, ay, bx, by in rays:
                    if _seg_dist(x, y, ax, ay, bx, by) <= 4.5:
                        bulb = True
                        break
            # 两颗小亮点
            if not bulb and (math.hypot(x - 108, y - 128) <= 8 or math.hypot(x - 404, y - 128) <= 8):
                bulb = True
            # 打开的书：左右两页，中间书脊留缝
            book = False
            if 100 <= x <= 250 and 0 <= y <= 512:
                u = (x - 100) / 150
                book = (292 + 22 * u) <= y <= (382 + 22 * u)
            elif 262 <= x <= 412 and 0 <= y <= 512:
                u = (x - 262) / 150
                book = (314 - 22 * u) <= y <= (404 - 22 * u)

            if bulb or book:
                col = white
            # 灯泡内的橙色灯丝与底座螺纹，让灯泡在小尺寸下仍可辨
            if bulb and math.hypot(x - 256, y - 178) < 58:
                if _seg_dist(x, y, 238, 186, 250, 198) <= 3.5 or \
                   _seg_dist(x, y, 250, 198, 274, 186) <= 3.5:
                    col = (244, 130, 52)
            if bulb and 258 <= y <= 268 and abs(x - 256) <= 18:
                if (y - 258) % 6 < 2.2:
                    col = (244, 130, 52)

            o = row + sx * 4
            buf[o], buf[o + 1], buf[o + 2], buf[o + 3] = col[0], col[1], col[2], a

    # 2×2 box filter 降采样
    out = bytearray(size * size * 4)
    for y in range(size):
        for x in range(size):
            r = g = b = al = 0
            for dy in range(ss):
                base = ((y * ss + dy) * W + x * ss) * 4
                for dx in range(ss):
                    o = base + dx * 4
                    r += buf[o]; g += buf[o + 1]; b += buf[o + 2]; al += buf[o + 3]
            n = ss * ss
            o = (y * size + x) * 4
            out[o], out[o + 1], out[o + 2], out[o + 3] = r // n, g // n, b // n, al // n

    raw = bytearray()
    for y in range(size):
        raw.append(0)
        raw.extend(out[y * size * 4:(y + 1) * size * 4])

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data +
                struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
           + chunk(b"IEND", b""))
    path.write_bytes(png)


# ---------------------------------------------------------------- 打包与自检

def build_package() -> list[str]:
    PKG.mkdir(parents=True, exist_ok=True)
    # 只清理本脚本会生成的已知文件，不整目录删除
    for p in PKG.rglob("*"):
        if p.is_file():
            p.unlink()
    for rel in COPY_AS_IS:
        src = REPO / rel
        dst = PKG / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
    write("system-prompt.md", build_system_prompt())
    write("SKILL.md", build_skill_md())
    write("usage-guide.md", build_usage_guide())
    write("examples/few-shot.md", build_few_shot())
    return sorted(str(p.relative_to(PKG)).replace("\\", "/") for p in PKG.rglob("*") if p.is_file())


def build_zip(files: list[str]) -> Path:
    zp = OUT / ZIP_NAME
    if zp.exists():
        zp.unlink()
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for rel in files:                      # arcname 不含外层文件夹
            # 固定条目时间戳，保证同一版本重跑得到字节一致的 ZIP（避免无意义的 git diff）
            info = zipfile.ZipInfo(rel, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, (PKG / rel).read_bytes())
    return zp


def check(files: list[str], zp: Path, avatar: Path) -> bool:
    issues = []
    ok = lambda cond, msg: None if cond else issues.append(msg)

    # ZIP 结构
    with zipfile.ZipFile(zp) as z:
        names = z.namelist()
    ok("SKILL.md" in names, "ZIP 根目录第一层缺 SKILL.md")
    ok(not any(n.startswith(SLUG + "/") for n in names), "ZIP 多套了一层 ai-study-tutor/ 文件夹")
    depths = [n.count("/") for n in names]
    ok(max(depths) <= 1, f"目录层级超过两层：{max(depths)} 个斜杠")
    for bad in EXCLUDE:
        ok(bad not in names, f"上架包不应含维护文件 {bad}")
    ok(not any(n.startswith(".git") or n.startswith("evals/") for n in names), "含 .git* 或 evals/")
    ok(zp.stat().st_size <= 3 * 1024 * 1024, "ZIP 超过 3 MB")

    # frontmatter
    fm_text = (PKG / "SKILL.md").read_text(encoding="utf-8")
    ok(fm_text.startswith("---\n"), "SKILL.md 未以 --- 开头")
    end = fm_text.find("\n---\n", 4)
    ok(end > 0, "frontmatter 未闭合")
    fm = fm_text[4:end]
    required = ["name", "display_name", "display_name_en", "description", "description_zh",
                "description_en", "version", "category", "author", "license", "examples"]
    for k in required:
        ok(re.search(rf"^{k}:", fm, re.M) is not None, f"frontmatter 缺必填字段 {k}")
    name_m = re.search(r"^name:\s*(\S+)\s*$", fm, re.M)
    ok(name_m is not None and re.fullmatch(r"[a-z0-9-]+", name_m.group(1)) is not None,
       "name 不是英文小写 + 连字符")
    ok(name_m and name_m.group(1) == SLUG, "name 与目录名不一致")
    ok(re.search(rf"^version:\s*{re.escape(VERSION)}\s*$", fm, re.M) is not None,
       f"frontmatter 的 version 与脚本 VERSION({VERSION}) 不一致")
    desc = re.search(r"^description:\s*(.+)$", fm, re.M)
    ok(desc is not None and len(desc.group(1)) <= 200, "description 超过 200 字")
    ok("\t" not in fm, "frontmatter 含 Tab 缩进")
    for line in fm.splitlines():
        if re.match(r"^[A-Za-z_]+:", line):
            ok(re.match(r"^[A-Za-z_]+:(\s|$)", line) is not None,
               f"YAML 冒号后缺空格: {line[:40]}")
        if line.startswith(" "):
            ok(line.startswith("  ") and not line.startswith("   ") or line.startswith("  - "),
               f"缩进不是两个空格: {line[:40]}")
    ok(fm.count("  - ") >= 3, "触发示例少于 3 条")

    # 引用路径：Markdown 链接 + 反引号裸路径，按文件所在目录与包根双重解析
    md_files = [f for f in files if f.endswith(".md")]
    pat = re.compile(r"\]\(([^)]+)\)|`([^`]+\.(?:md|html))`")
    checked = 0
    for rel in md_files:
        text = (PKG / rel).read_text(encoding="utf-8")
        for m in pat.finditer(text):
            raw = m.group(1) or m.group(2)
            if raw.startswith(("http://", "https://", "#", "data:")) or " " in raw:
                continue
            checked += 1
            base = PKG / rel
            candidates = [(base.parent / raw).resolve(), (PKG / raw).resolve()]
            ok(any(c.is_file() and PKG.resolve() in c.parents for c in candidates),
               f"{rel} 引用了包内不存在的文件: {raw}")
    print(f"  · 校验 {len(files)} 个文件、{checked} 处文档引用")

    # 头像
    data = avatar.read_bytes()
    ok(data[:8] == b"\x89PNG\r\n\x1a\n", "头像不是 PNG")
    w, h = struct.unpack(">II", data[16:24])
    ok((w, h) == (512, 512), f"头像尺寸应为 512×512，实际 {w}×{h}")
    ok(avatar.stat().st_size <= 500 * 1024, "头像超过 500 KB")

    for msg in issues:
        print(f"  [FAIL] {msg}")
    print(f"\n结果：{'PASS —— 上架包全部检查通过' if not issues else f'FAIL —— {len(issues)} 项未通过'}")
    print(f"  · ZIP {zp.stat().st_size / 1024:.1f} KB | 头像 {avatar.stat().st_size / 1024:.1f} KB | 版本 v{VERSION}")
    return not issues


def main() -> int:
    print(f"权威源：{REPO}")
    print(f"输出目录：{OUT}\n")
    files = build_package()
    zp = build_zip(files)
    avatar = OUT / AVATAR_NAME
    print("绘制 512×512 头像…")
    make_avatar(avatar)
    print(f"已生成 {zp.name} / {avatar.name}\n上架前自检：")
    return 0 if check(files, zp, avatar) else 1


if __name__ == "__main__":
    raise SystemExit(main())
