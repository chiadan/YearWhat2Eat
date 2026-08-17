"""评测集生成脚本（§13.1，决策 11 ✅：AI 生成草稿 + 规则校验 + 人工审核）。

用法：python -m tests.eval.generate_golden [--out tests/eval/golden_qa.json]
基于真实数据源自动构造 ~110 条（推荐 60 / 问答 30 / 技巧 10 + draft 20 条），
输出标注 "auto-generated-draft"，人工审核修订后作为评测基准。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND))

from app.core.config import get_settings  # noqa: E402

PEOPLE = [1, 2, 2, 3, 4]
MEAL_TYPES = ["早餐", "午餐", "晚餐", "夜宵"]
FLAVORS = ["辣", "清淡", "甜", "酸", "咸鲜"]
AVOIDS = [[], [], ["香菜"], ["内脏"], ["海鲜"]]
MAX_TIMES = [None, 15, 30, 45, 60]

DISH_QA_TEMPLATES = [
    "{name}怎么做",
    "怎么做{name}",
    "{name}要多久能做好",
    "{name}的步骤是什么",
    "{name}需要注意什么",
]
TIPS_QA_TEMPLATES = [
    "{title}要注意什么",
    "怎么{title}",
    "{title}有什么讲究",
    "{title}一般怎么做",
]


def dish_id(rel: str) -> str:
    return hashlib.sha1(rel.encode("utf-8")).hexdigest()[:12]


def collect_dishes(data_root: Path) -> list[dict]:
    dishes_dir = data_root / "dishes"
    out = []
    for md in sorted(dishes_dir.rglob("*.md")):
        rel = md.relative_to(dishes_dir).as_posix()
        if rel.startswith("template/"):
            continue
        out.append({"name": md.stem, "rel": rel, "category": rel.split("/")[0]})
    return out


def collect_tips(data_root: Path) -> list[dict]:
    tips_dir = data_root / "tips"
    out = []
    for md in sorted(tips_dir.rglob("*.md")):
        rel = md.relative_to(tips_dir).as_posix()
        out.append({"title": md.stem, "rel": rel})
    return out


def build_recommend(dishes: list[dict], rng: random.Random) -> dict:
    people = rng.choice(PEOPLE)
    meal = rng.choice(MEAL_TYPES)
    flavor = rng.choice(FLAVORS)
    avoid = rng.choice(AVOIDS)
    max_time = rng.choice(MAX_TIMES)

    parts = [f"{people} 人"]
    parts.append(meal)
    if flavor == "辣":
        parts.append("想吃辣")
    elif flavor == "清淡":
        parts.append("想吃清淡的")
    elif flavor == "甜":
        parts.append("想吃点甜的")
    elif flavor == "酸":
        parts.append("想吃酸的")
    else:
        parts.append("想吃咸鲜口")
    if max_time:
        parts.append(f"{max_time} 分钟内搞定")
    if avoid:
        parts.append("不吃" + "、".join(avoid))
    query = "，".join(parts)

    return {
        "id": f"auto-rec-{hashlib.md5(query.encode()).hexdigest()[:6]}",
        "type": "recommend",
        "query": query,
        "user_profile": {"avoid_list": avoid} if avoid else None,
        "expect": {
            "people": people,
            "meal_type": meal,
            "flavors": [flavor],
            "avoids": avoid,
            "max_time_min": max_time,
        },
        "expect_rewrite": {
            "rewritten_query": query,
            "entities": {"meal_type": [meal], "people": people, "flavors": [flavor]},
        },
    }


def build_dish_qa(dishes: list[dict], rng: random.Random) -> dict:
    dish = rng.choice(dishes)
    query = rng.choice(DISH_QA_TEMPLATES).format(name=dish["name"])
    return {
        "id": f"auto-qa-{dish_id(dish['rel'])}",
        "type": "dish_qa",
        "query": query,
        "user_profile": None,
        "expect": {"ref_doc": f"dishes/{dish['rel']}", "keywords": [dish["name"]]},
        "expect_rewrite": {
            "rewritten_query": f"{dish['name']} 做法",
            "entities": {"dish_names": [dish["name"]]},
        },
    }


def build_tips_qa(tips: list[dict], rng: random.Random) -> dict:
    tip = rng.choice(tips)
    query = rng.choice(TIPS_QA_TEMPLATES).format(title=tip["title"])
    return {
        "id": f"auto-tip-{dish_id('tips/' + tip['rel'])}",
        "type": "tips_qa",
        "query": query,
        "user_profile": None,
        "expect": {"ref_doc": f"tips/{tip['rel']}", "keywords": [tip["title"]]},
        "expect_rewrite": {
            "rewritten_query": f"{tip['title']} 技巧",
            "entities": {"techniques": [tip["title"]]},
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(BACKEND / "tests" / "eval" / "golden_qa.json"))
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    data_root = get_settings().data_source_root
    dishes = collect_dishes(data_root)
    tips = collect_tips(data_root)
    rng = random.Random(args.seed)

    items = [build_recommend(dishes, rng) for _ in range(60)]
    items += [build_dish_qa(dishes, rng) for _ in range(30)]
    items += [build_tips_qa(tips, rng) for _ in range(10)]

    # 并入 design/golden_qa.draft.json 的人工示例（20 条）
    draft_path = BACKEND.parent / "design" / "golden_qa.draft.json"
    if draft_path.exists():
        draft = json.loads(draft_path.read_text(encoding="utf-8"))
        items = list(draft.get("items", [])) + items

    rng.shuffle(items)
    out = {
        "version": "0.2-auto-draft",
        "note": "AI 自动生成草稿（决策 11 ✅）：60 推荐 + 30 问答 + 10 技巧 + 20 人工示例；"
                "检索指标按 expect.ref_doc 校验，需人工审核后作为评测基准",
        "item_count": len(items),
        "items": items,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"generated {len(items)} items -> {args.out}")


if __name__ == "__main__":
    main()
