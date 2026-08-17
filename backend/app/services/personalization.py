"""个性化打分（§6.5 personal 子项，用真实画像 §8）。

personal(d) = Σ_k w_k × match_k(d) / Σ w_k
  match_口味 = 1 - |画像辣度 - 菜辣度| / 4     （w=0.40；甜/酸/清淡同法取均值）
  match_菜系 = 0.8 + 0.2 × 该菜系行为占比      （w=0.20，M4 无菜系行为统计 -> 0.8）
  match_难度 = 画像水平匹配 ? 1 : 0.5          （w=0.15）
  match_工具 = 工具具备 ? 1 : 0                （w=0.15）
  match_目标 = 快手目标且时长<20min ? 1 : 0.5  （w=0.10）
"""
from __future__ import annotations

_W = {"flavor": 0.40, "cuisine": 0.20, "difficulty": 0.15, "tool": 0.15, "goal": 0.10}

_SKILL_DIFF = {"新手": 3, "进阶": 4, "熟练": 5}
_FLAVOR_KEYWORDS = {"辣": ["辣"], "甜": ["甜"], "酸": ["酸"], "清淡": ["清淡", "清爽"]}


def _dish_spiciness(item: dict) -> int:
    """菜辣度 1~5 估计：从 flavors/text 关键词。"""
    text = str(item.get("text") or "") + "".join(item.get("flavors") or [])
    if "麻辣" in text or "重辣" in text:
        return 5
    if "辣" in text:
        return 4
    if "微辣" in text:
        return 3
    return 1


def personal_score(item: dict, profile: dict | None) -> float:
    """§6.5 personal(d)；无画像 -> 中性 0.5。profile 为 profile_to_dict 输出（dict）。"""
    if not profile:
        return 0.5

    matches: list[tuple[float, float]] = []  # (weight, match)

    # 口味（辣度差 + 甜/酸/清淡关键词命中）
    profile_spicy = int(profile.get("flavor_spicy", 3))
    spicy = _dish_spiciness(item)
    spicy_match = 1.0 - abs(profile_spicy - spicy) / 4.0
    flavor_matches = [spicy_match]
    text = str(item.get("text") or "") + "".join(item.get("flavors") or [])
    for key, profile_key in (("甜", "flavor_sweet"), ("酸", "flavor_sour"), ("清淡", "flavor_light")):
        level = int(profile.get(profile_key, 3))
        hit = any(k in text for k in _FLAVOR_KEYWORDS[key])
        flavor_matches.append(1.0 if (hit and level >= 4) else 0.6)
    matches.append((_W["flavor"], sum(flavor_matches) / len(flavor_matches)))

    # 菜系（M4 无菜系行为统计 -> 0.8 基线；M4 后接入行为占比）
    matches.append((_W["cuisine"], 0.8))

    # 难度
    diff = item.get("difficulty")
    if diff is not None:
        skill_max = _SKILL_DIFF.get(profile.get("skill_level", "新手"), 5)
        matches.append((_W["difficulty"], 1.0 if diff <= skill_max else 0.5))
    else:
        matches.append((_W["difficulty"], 0.6))

    # 工具（特殊工具不匹配则 0，§6.5 硬约束已在 rule_filter 处理，这里仅软加权）
    tools = profile.get("tools") or []
    need = [t for t in (item.get("techniques") or []) if t in ("微波炉", "空气炸锅", "电饭煲", "烤箱", "高压锅")]
    if need and not any(t in tools for t in need):
        matches.append((_W["tool"], 0.0))
    else:
        matches.append((_W["tool"], 1.0))

    # 目标（快手 -> 时长 < 20min 得 1）
    if profile.get("goal") == "快手":
        est = item.get("time_est")
        matches.append((_W["goal"], 1.0 if (est is not None and est <= 20) else 0.5))
    else:
        matches.append((_W["goal"], 0.6))

    total_w = sum(w for w, _ in matches)
    return sum(w * m for w, m in matches) / total_w
