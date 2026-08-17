"""md 解析器（§5 Step1 / Step7）：扫描 dishes/ 与 tips/，容错解析为结构化记录。

- dish_id = 相对路径 sha1 前 12 位（§2.2：同名菜冲突，如 soup 下两个"陈皮排骨汤"）
- 菜谱结构按 §2.2 模板（标题/简介/难度/原料/计算/操作[含多版本]/附加内容）
- 容错：缺失章节置 None/空，不阻塞入库；解析结果先落 SQLite 再驱动 Neo4j/Qdrant
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

# 难度星级：预估烹饪难度：★★★
_DIFFICULTY_RE = re.compile(r"预估烹饪难度[：:]\s*(★+)")
# 标题：# 菜名的做法
_TITLE_RE = re.compile(r"^#\s+(.+?)(?:的做法)?\s*$")
# 列表项
_LIST_ITEM_RE = re.compile(r"^[-*]\s+(.+)$")
# 章节标题（## 或 ###）
_SECTION_RE = re.compile(r"^(#{2,3})\s+(.+?)\s*$")
# 图片行
_IMAGE_RE = re.compile(r"^!\[.*\]\(.*\)\s*$")

_SECTION_ALIASES = {
    "必备原料和工具": "required",
    "可选原料": "optional",
    "计算": "calculation",
    "操作": "steps",
    "附加内容": "notes",
}


@dataclass
class StepRecord:
    version: str           # 简易版本 / 稍加复杂... / default
    order: int
    text: str


@dataclass
class DishRecord:
    dish_id: str
    name: str
    category: str
    rel_path: str          # 相对 dishes/ 的路径
    difficulty: int | None
    intro: str | None
    required_raw: list[str] = field(default_factory=list)
    optional_raw: list[str] = field(default_factory=list)
    calculation_raw: str | None = None
    steps: list[StepRecord] = field(default_factory=list)
    notes: str | None = None


@dataclass
class TipRecord:
    tip_id: str
    title: str
    category: str          # general | learn | advanced
    rel_path: str
    content: str
    chunks: list[str] = field(default_factory=list)   # 按 ## 分块（§4.2 tips 集合）


@dataclass
class ParsedCorpus:
    dishes: list[DishRecord]
    tips: list[TipRecord]

    @property
    def alias_table(self) -> dict[str, list[str]]:
        """菜名 -> 相对路径列表（§6.4 query_rewriter 兜底；同名菜归并展示）。"""
        table: dict[str, list[str]] = {}
        for d in self.dishes:
            table.setdefault(d.name, []).append(d.rel_path)
        return table


def _dish_id(rel_path: str) -> str:
    return hashlib.sha1(rel_path.encode("utf-8")).hexdigest()[:12]


def _parse_difficulty(text: str) -> int | None:
    m = _DIFFICULTY_RE.search(text)
    if not m:
        return None
    return min(len(m.group(1)), 5)


def _parse_dish_md(md_text: str, rel_path: str) -> DishRecord:
    lines = md_text.splitlines()
    name = Path(rel_path).stem
    category = rel_path.split("/")[0] if "/" in rel_path else "other"
    difficulty: int | None = None
    intro: str | None = None
    current_section: str | None = None
    current_version = "default"
    step_index = 0
    section_bodies: dict[str, list[str]] = {"required": [], "optional": [], "calculation": [], "steps": [], "notes": []}

    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if _IMAGE_RE.match(line) or line.startswith("<!--"):
            continue

        sec = _SECTION_RE.match(line)
        if sec:
            key = _SECTION_ALIASES.get(sec.group(2).strip())
            if key:
                # 已知章节：切换当前章节
                current_section = key
            elif current_section == "steps":
                # 版本小标题（如 "### 简易版本"）：仅更新步骤版本标记，不退出 steps 章节
                current_version = sec.group(2).strip()
            continue

        if current_section is None:
            # 标题行或简介段落
            t = _TITLE_RE.match(line)
            if t and t.group(1).strip():
                name = t.group(1).strip()
            elif difficulty is None:
                d = _parse_difficulty(line)
                if d is not None:
                    difficulty = d
                elif intro is None and not line.startswith("#"):
                    intro = line
            continue

        if current_section in ("required", "optional", "calculation", "notes"):
            section_bodies[current_section].append(line)
        elif current_section == "steps":
            m = _LIST_ITEM_RE.match(line)
            if m:
                section_bodies["steps"].append(f"{current_version}|{m.group(1)}")
            else:
                section_bodies["steps"].append(f"{current_version}|{line}")

    required_raw, optional_raw = _split_required_optional(section_bodies["required"])
    steps: list[StepRecord] = []
    for item in section_bodies["steps"]:
        if "|" in item:
            version, text = item.split("|", 1)
        else:
            version, text = current_version, item
        step_index += 1
        steps.append(StepRecord(version=version, order=step_index, text=text.strip()))

    return DishRecord(
        dish_id=_dish_id(rel_path),
        name=name,
        category=category,
        rel_path=rel_path,
        difficulty=difficulty,
        intro=intro,
        required_raw=required_raw,
        optional_raw=optional_raw,
        calculation_raw="\n".join(section_bodies["calculation"]) or None,
        steps=steps,
        notes="\n".join(section_bodies["notes"]) or None,
    )


def _split_required_optional(required_body: list[str]) -> tuple[list[str], list[str]]:
    """必备原料章节内可能嵌 `### 可选原料`；此函数把行按列表项收集。"""
    items = [_LIST_ITEM_RE.match(l) for l in required_body]
    return [m.group(1) for m in items if m], []


def _parse_tip_md(md_text: str, rel_path: str) -> TipRecord:
    lines = md_text.splitlines()
    title = Path(rel_path).stem
    content_parts: list[str] = []
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("<!--"):
            continue
        t = _TITLE_RE.match(line)
        if t and t.group(1).strip():
            title = t.group(1).strip()
            continue
        content_parts.append(line)
    content = "\n".join(content_parts)

    # 按 ## 分块（§4.2 tips 集合）
    chunks: list[str] = []
    current: list[str] = []
    for line in content_parts:
        if _SECTION_RE.match(line) and line.startswith("## "):
            if current:
                chunks.append("\n".join(current))
                current = []
        current.append(line)
    if current:
        chunks.append("\n".join(current))

    cat = rel_path.split("/")[0] if "/" in rel_path else "general"
    return TipRecord(
        tip_id=_dish_id(f"tips/{rel_path}"),
        title=title,
        category=cat,
        rel_path=rel_path,
        content=content,
        chunks=chunks,
    )


def parse_corpus(data_root: Path) -> ParsedCorpus:
    """扫描并解析全部菜谱与技巧（§5 Step1）。"""
    dishes_dir = data_root / "dishes"
    tips_dir = data_root / "tips"

    dishes: list[DishRecord] = []
    if dishes_dir.is_dir():
        for md in sorted(dishes_dir.rglob("*.md")):
            rel = md.relative_to(dishes_dir).as_posix()
            if rel.startswith("template/"):
                continue  # 排除模板菜
            try:
                dishes.append(_parse_dish_md(md.read_text(encoding="utf-8"), rel))
            except Exception:  # noqa: BLE001 —— 单篇失败不阻塞整体
                dishes.append(DishRecord(
                    dish_id=_dish_id(rel), name=Path(rel).stem, category=rel.split("/")[0],
                    rel_path=rel, difficulty=None, intro=f"[解析失败] {md}",
                ))

    tips: list[TipRecord] = []
    if tips_dir.is_dir():
        for md in sorted(tips_dir.rglob("*.md")):
            rel = md.relative_to(tips_dir).as_posix()
            tips.append(_parse_tip_md(md.read_text(encoding="utf-8"), rel))

    return ParsedCorpus(dishes=dishes, tips=tips)
