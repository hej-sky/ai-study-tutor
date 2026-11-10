#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""助力学 · WorkBuddy 开放平台「专家」入口上架包构建（唯一入口）。

用法：
    python release/build_expert.py                 # 标准包（对标官方模板，带顶层目录）
    python release/build_expert.py --flat         # 备用包（不套顶层目录，仅当平台仍报
                                                  # 「未找到 .codebuddy-plugin/plugin.json」时使用）

为什么单独有一个包：
    开放平台「技能」入口要求「解压第一层即 SKILL.md」；「专家」入口要求
    .codebuddy-plugin/plugin.json + agents/ + avatars/ + README.md，是 Agent 角色包。
    两个入口的解析器不同，同一个 ZIP 无法同时满足。

同源保证（重要）：
    技能部分直接读取 release/ai-study-tutor-v1.5.2.zip 的 6 个文件，
    头像直接读取 release/avatar-512.png，不另存副本、不做内容补丁。
    因此专家包与技能包永远同版本、同内容，不会出现两份口径分叉。

产物：
    release/ai-study-tutor-expert-v1.5.2.zip
    （--flat 时：release/ai-study-tutor-expert-v1.5.2-flat.zip）
"""

from __future__ import annotations

import io
import json
import re
import struct
import sys
import zipfile
from pathlib import Path

OUT = Path(__file__).resolve().parent
VERSION = "1.5.2"
NAME = "ai-study-tutor"
AGENT_NAME = "ai-study-tutor"
SKILL_ZIP = f"ai-study-tutor-v{VERSION}.zip"
AVATAR = "avatar-512.png"
REPO_URL = "https://gitee.com/hejsky/ai-study-tutor"

# 平台官方专家包分类共 15 类；本机内置校验脚本只带前 12 类，故此处以平台文档为准。
PLATFORM_CATEGORY_IDS = {
    "01-ProductDesign", "02-Engineering", "03-GameSpatial", "04-DataAI",
    "05-MarketingGrowth", "06-ContentCreative", "07-SalesCommerce",
    "08-FinanceInvestment", "09-OperationsHR", "10-ProjectQuality",
    "11-SecurityCompliance", "12-IndustryConsultant", "13-TencentZone",
    "14-WorldWise", "15-Education",
}

QUICK_PROMPTS = [
    {
        "zh": "我上初二，物理，电流与电压、电阻的关系没听懂",
        "en": "I'm in grade 8. I don't understand the relationship between current, voltage and resistance in physics",
    },
    {
        "zh": "人教版，五年级，分数的基本性质，帮我讲讲并出点题",
        "en": "Grade 5, People's Education Press edition: explain the basic properties of fractions and give me exercises",
    },
    {
        "zh": "我二年级，数学，认识分数，能不能画个图给我看",
        "en": "I'm in grade 2. Can you draw a picture to help me understand fractions?",
    },
]

# author.email 取自本仓库 git 提交作者邮箱（已随公开提交记录公开），非虚构值。
# 若维护者不愿在对外包中公开邮箱，只需改这一处。
PLUGIN_JSON = {
    "name": NAME,
    "version": VERSION,
    "description": (
        "An agent-type expert delivering grade- and textbook-adapted tutoring for grades 1-12: "
        "explanations, diagrams, tiered exercises, grading and review plans."
    ),
    "author": {"name": "何必再健", "email": "hejmail@qq.com"},
    "agents": [f"./agents/{AGENT_NAME}.md"],
    "skills": [f"./skills/{NAME}"],
    "expertType": "agent",
    "agentName": AGENT_NAME,
    "displayName": {"en": "AI Study Tutor", "zh": "助力学"},
    "profession": {"en": "K-12 AI Study Tutor", "zh": "中小学 AI 学习助教"},
    "displayDescription": {
        "en": (
            "An AI study tutor for primary and secondary students. It adapts explanations, "
            "diagrams, tiered exercises, grading and review plans to each student's grade "
            "level and textbook edition, with lightweight SVG/CSS animations instead of "
            "large video files."
        ),
        # 平台要求中文 40-50 字；校验函数会复核长度。
        "zh": "面向中小学生，按年级与教材版本适配讲解、示意图、分层习题、批改与复习计划的 AI 学习助教。",
    },
    "avatar": "avatars/expert.png",
    "categoryId": "15-Education",
    "defaultInitPrompt": dict(QUICK_PROMPTS[0]),
    "plugin": NAME,
    "homepage": REPO_URL,
    "license": "MIT",
    "tags": [
        {"en": "Subject Tutoring", "zh": "分科讲解"},
        {"en": "Tiered Exercises", "zh": "分层习题"},
        {"en": "Textbook Alignment", "zh": "教材版本对齐"},
    ],
    "quickPrompts": QUICK_PROMPTS,
}

AGENT_MD = """---
name: ai-study-tutor
description: K-12 AI study tutor expert that adapts explanations, diagrams, tiered exercises, grading and review plans to the student's grade level and textbook edition
displayName:
  en: "AI Study Tutor"
  zh: "助力学"
profession:
  en: "K-12 AI Study Tutor"
  zh: "中小学 AI 学习助教"
maxTurns: 100
skills:
  - ai-study-tutor
---

# 助力学 · 中小学 AI 学习助教

你是「助力学」，面向小学一年级至高中三年级学生的 AI 学习助教。你把一节没听懂的课、一道不会的题、一张课本照片，变成「讲解 → 可视化演示 → 分层习题 → 批改 → 复习计划」的完整闭环，并让输出**匹配学生的年级、科目与教材版本**。

## 唯一权威规则

**本专家的全部教学行为规则由随包 Skill `ai-study-tutor` 提供，不在本文件中复述。**

每次会话开始时必须先加载该 Skill，并完整读取其 `system-prompt.md`（其中的提示词代码块为唯一权威来源），逐条遵守其输出格式、分轮节奏、导航条、篇幅规则与科目模块。不得凭记忆复述规则，不得用本文件的概要替代提示词正文。

该 Skill 同时提供 `SKILL.md`（启动流程与按需加载表）、`usage-guide.md`（使用说明）与 `examples/`（少数示例、两份 HTML/SVG 动画）。按 `SKILL.md` 的渐进加载表按需读取，不要一次全读。

## 核心能力

1. **分科与年龄适配**：语文 / 数学 / 英语 / 物理 / 化学各有专属教法；语言按四档年级分层，低年级不用书面词。
2. **教材版本对齐**：把教材版本作为第一解析字段，用于对齐术语与进度；未指定时不得默认任何版本，也不得编造教材原文、页码、单元号或例题原题。
3. **轻量可视化**：教学示意图与过程动画优先用 SVG/CSS 代码生成，不生成大型视频；纯文本环境给出代码块与建议保存路径，不得谎称已保存。
4. **巩固闭环**：分层习题后置答案，学生交回答案后批改，并给出费曼自测与 3 天复习计划；只增量输出变化部分。

## 工作流程

1. 加载 Skill `ai-study-tutor`，读取其 `system-prompt.md` 作为本次会话准则。
2. 按提示词首轮规则做四项解析回显（教材版本在首行），并声明本次交付模式（由宿主能力自行判定）。
3. 按对话状态机分轮推进，任何分支都不得一次性倾倒后续环节。
4. 学生交回答案后进入批改与巩固闭环，被标为薄弱点的知识点优先补讲。

## 输出规范

- 所有输出遵循「省的是冗余，不是内容」；宁可字数上浮，也不能让学生因为少了一句话而没读懂。
- 首轮只输出「科目与年级 / 概览 / 讲解」，末尾给带编号的知识点地图与一行导航条。
- 产物按 Skill 的归档规则命名，回复中给出相对路径与打开方式。
- 全程使用与学生输入一致的语言。

## 注意事项

- 本项目仍在实践验证阶段，文本规则只能提高模型遵守概率，不同 AI 工具与模型表现会有差异。
- 客观能力边界以随包 `usage-guide.md` 末尾「附：客观能力边界」为唯一权威清单，本文件不另写一套。
- 不得声明本专家自行拥有的工具权限；工具由宿主统一分配。
- 涉及未成年人使用时，不索取与学习无关的个人信息，不替代学校教育与监护人判断。
"""

README_MD = f"""# 助力学 · 专家包（WorkBuddy 开放平台「专家」入口）

本包是「助力学 / ai-study-tutor」的 **Agent 型专家包**，用于上传到 WorkBuddy 开放平台
「发布管理 → 专家」。它与「技能」入口的包不是同一份：技能入口要求解压第一层即 `SKILL.md`，
专家入口要求 `.codebuddy-plugin/plugin.json` + `agents/` + `avatars/` + `README.md`。

## 包内结构

```
{NAME}/
├── .codebuddy-plugin/plugin.json     专家核心配置与展示信息
├── agents/{AGENT_NAME}.md           Agent 角色定义（指向随包 Skill）
├── avatars/expert.png               512×512 PNG 头像
├── skills/{NAME}/                   完整技能包（与技能入口上架包同源）
│   ├── SKILL.md
│   ├── system-prompt.md             唯一权威提示词
│   ├── usage-guide.md
│   └── examples/                    3 个文件
└── README.md
```

## 与技能入口包的关系

`skills/{NAME}/` 下的 6 个文件**逐字节复制**自同版本技能入口上架包
`{SKILL_ZIP}`，头像复制自 `{AVATAR}`。两者由
`build_expert.py` 一次构建、同源派生，不存在内容补丁或第二份提示词。

构建方式（在仓库任意位置执行）：

```bash
python release/build_expert.py
```

## 关键字段口径

| 字段 | 值 | 说明 |
| --- | --- | --- |
| `expertType` | `agent` | 单角色专家，非专家团 |
| `categoryId` | `15-Education` | 平台 15 类行业分类中的「教育学习」 |
| `author.email` | 见 `plugin.json` | 取自仓库 git 提交作者邮箱，随包公开 |
| `version` | {VERSION} | 与技能入口包、仓库版本保持一致 |

## 上传提示

1. 只上传 `ai-study-tutor-expert-v{VERSION}.zip` 这一个 ZIP，不要上传 `release/` 目录。
2. 若平台仍提示「未找到 .codebuddy-plugin/plugin.json」，用 `python release/build_expert.py --flat`
   生成不带顶层目录的备用包再试。
3. 平台规则可能变动，最终以开放平台后台当前提示为准；官方文档见
   https://open.workbuddy.cn/docs/expert 。

## 项目信息

- 仓库：{REPO_URL}
- 许可证：MIT
- 客观能力边界：见 `skills/{NAME}/usage-guide.md` 末尾「附：客观能力边界」
"""


def find_repo() -> Path:
    for c in (OUT, *OUT.parents):
        if (c / "SKILL.md").is_file() and (c / "system-prompt.md").is_file():
            return c
    raise SystemExit("未找到仓库根目录（应含 SKILL.md 与 system-prompt.md）")


def read_sources() -> dict[str, bytes]:
    """从技能入口上架包与头像读取素材，保证同源。"""
    skill_zip = OUT / SKILL_ZIP
    avatar = OUT / AVATAR
    for p in (skill_zip, avatar):
        if not p.is_file():
            raise SystemExit(f"缺少素材：{p.name}（请先运行 build_release.py）")

    with zipfile.ZipFile(skill_zip) as z:
        names = z.namelist()
        expected = {
            "SKILL.md", "system-prompt.md", "usage-guide.md",
            "examples/few-shot.md",
            "examples/math-g5-fraction-pie.html",
            "examples/svg-animation-template.html",
        }
        if set(names) != expected:
            raise SystemExit(f"技能入口包内容已变化，需复核：{sorted(set(names) ^ expected)}")
        entries = {f"skills/{NAME}/{n}": z.read(n) for n in names}

    png = avatar.read_bytes()
    w, h = struct.unpack(">II", png[16:24])
    if png[:8] != b"\x89PNG\r\n\x1a\n" or (w, h) != (512, 512) or len(png) > 500 * 1024:
        raise SystemExit("头像不符合规格：需 512×512 PNG、≤500KB")
    entries["avatars/expert.png"] = png
    return entries


def build_entries() -> dict[str, bytes]:
    entries = read_sources()
    entries[".codebuddy-plugin/plugin.json"] = (
        json.dumps(PLUGIN_JSON, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")
    entries[f"agents/{AGENT_NAME}.md"] = AGENT_MD.encode("utf-8")
    entries["README.md"] = README_MD.encode("utf-8")
    return entries


def check(entries: dict[str, bytes]) -> list[str]:
    """按开放平台官方专家文档 + 本机校验脚本规则做静态预检。"""
    errors: list[str] = []
    pj = PLUGIN_JSON

    # 结构与目录
    if ".codebuddy-plugin/plugin.json" not in entries:
        errors.append("缺 .codebuddy-plugin/plugin.json")
    if f"agents/{AGENT_NAME}.md" not in entries:
        errors.append("缺 agents/<agentName>.md")
    if f"skills/{NAME}/SKILL.md" not in entries:
        errors.append("缺 skills/<name>/SKILL.md")
    if "avatars/expert.png" not in entries:
        errors.append("缺头像")
    if "README.md" not in entries:
        errors.append("缺 README.md")
    for n in entries:
        if "__MACOSX" in n or n.endswith("/.DS_Store") or n.endswith(".pyc"):
            errors.append(f"夹带打包垃圾：{n}")
        if n.count("/") > 4:
            errors.append(f"目录层级过深：{n}")

    # 基础字段
    for k in ("name", "version", "description", "author", "agents", "agentName",
              "expertType", "displayName", "profession", "displayDescription",
              "avatar", "categoryId", "defaultInitPrompt", "plugin", "tags", "quickPrompts"):
        if k not in pj:
            errors.append(f"plugin.json 缺字段 {k}")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*[a-z0-9]", pj["name"]):
        errors.append("name 非 kebab-case")
    if pj["plugin"] != pj["name"]:
        errors.append("plugin 与 name 不一致")
    if pj["expertType"] != "agent":
        errors.append("expertType 应为 agent")
    if pj["agentName"] == "team-lead":
        errors.append("agentName 不可为通用 team-lead")
    if pj["categoryId"] not in PLATFORM_CATEGORY_IDS:
        errors.append("categoryId 不在平台分类表内")
    if not isinstance(pj["author"], dict) or not re.fullmatch(
        r"[^@\s]+@[^@\s]+\.[^@\s]+", str(pj["author"].get("email", ""))
    ):
        errors.append("author.email 格式不合法")

    # 双语字段
    for k in ("displayName", "profession", "displayDescription", "defaultInitPrompt"):
        v = pj.get(k)
        if not isinstance(v, dict) or not v.get("zh") or not v.get("en"):
            errors.append(f"{k} 需为含 zh/en 的非空对象")
    for key, listname in (("tags", "tags"), ("quickPrompts", "quickPrompts")):
        arr = pj.get(listname, [])
        if not isinstance(arr, list) or len(arr) != 3:
            errors.append(f"{key} 必须恰好 3 个")
        for item in arr if isinstance(arr, list) else []:
            if not isinstance(item, dict) or not item.get("zh") or not item.get("en"):
                errors.append(f"{key} 每项需含 zh/en")
    if pj["defaultInitPrompt"] != pj["quickPrompts"][0]:
        errors.append("defaultInitPrompt 必须等于 quickPrompts[0]")
    zh_len = len(pj["displayDescription"]["zh"])
    if not 40 <= zh_len <= 50:
        errors.append(f"displayDescription.zh 为 {zh_len} 字，需 40-50")

    # 路径可解析
    for rel in pj["agents"] + pj["skills"]:
        key = rel[2:] if rel.startswith("./") else rel
        if key not in entries and not any(n.startswith(key + "/") for n in entries):
            errors.append(f"路径不可解析：{rel}")

    # Agent MD frontmatter 禁止 tools
    agent_txt = entries[f"agents/{AGENT_NAME}.md"].decode("utf-8")
    fm = re.match(r"^---\n(.*?)\n---", agent_txt, re.DOTALL)
    if not fm:
        errors.append("Agent MD 缺 frontmatter")
    else:
        if "tools:" in fm.group(1):
            errors.append("Agent MD frontmatter 不可声明 tools")
        if not re.search(r"^name:\s*" + re.escape(AGENT_NAME) + r"\s*$", fm.group(1), re.M):
            errors.append("Agent MD 的 name 与文件名不一致")

    # 全包文本层：UTF-8 / 无本机绝对路径 / 无凭据
    cred = re.compile(r"(?i)\b(?:api[_-]?key|password|passwd|secret|access[_-]?token)\b\s*[:=]")
    path = re.compile(r"[A-Za-z]:[\\/]Users[\\/]|/(?:Users|home)/[A-Za-z0-9._-]+/")
    for n, b in entries.items():
        if n.endswith(".png"):
            continue
        try:
            t = b.decode("utf-8")
        except UnicodeDecodeError:
            errors.append(f"非 UTF-8：{n}")
            continue
        if b"\x00" in b:
            errors.append(f"含 NUL：{n}")
        if path.search(t) or cred.search(t):
            errors.append(f"含本机路径或疑似凭据：{n}")
        if re.search(r"\[TODO", t):
            errors.append(f"残留 TODO 占位：{n}")
    return errors


def package(entries: dict[str, bytes], dest: Path, flat: bool) -> None:
    prefix = "" if flat else f"{NAME}/"
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        for name in sorted(entries):
            info = zipfile.ZipInfo(prefix + name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, entries[name])


def main() -> None:
    flat = "--flat" in sys.argv[1:]
    find_repo()
    entries = build_entries()
    issues = check(entries)
    if issues:
        print("专家包预检 FAIL：")
        for e in issues:
            print("  -", e)
        raise SystemExit(1)

    dest = OUT / (f"{NAME}-expert-v{VERSION}" + ("-flat" if flat else "") + ".zip")
    package(entries, dest, flat)
    # 复跑一次并比对，确保 ZIP 可复现
    again = io.BytesIO()
    prefix = "" if flat else f"{NAME}/"
    with zipfile.ZipFile(again, "w", zipfile.ZIP_DEFLATED) as z:
        for name in sorted(entries):
            info = zipfile.ZipInfo(prefix + name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, entries[name])
    if again.getvalue() != dest.read_bytes():
        raise SystemExit("ZIP 不可复现，构建中止")

    print(f"专家包预检 PASS：{len(entries)} 个文件，字段/双语/路径/编码/无垃圾全通过")
    print(f"可复现：是（固定时间戳）")
    print(f"产物：{dest.name} · {dest.stat().st_size} B")
    print(f"入口：WorkBuddy 开放平台 → 发布管理 → 专家")


if __name__ == "__main__":
    main()
