"""§8.5 对话偏好提取纯逻辑单测（不依赖容器）：信号解析 / 合并 / 打分消费。"""
from app.db.models import UserProfile
from app.services.personalization import personal_score
from app.services.preference_extractor import _parse_signals, merge_signals

_CONF = 0.7


def _sig(typ: str, value: str, **kw) -> dict:
    s = {"type": typ, "value": value, "confidence": _CONF}
    s.update(kw)
    return s


# ── 信号解析 ────────────────────────────────────────────────

def test_parse_signals_filters_invalid():
    raw = {
        "signals": [
            _sig("avoid", "香菜", reason="我不吃香菜"),
            {"type": "bogus", "value": "x", "confidence": 0.9},          # 类型不在白名单
            {"type": "avoid", "value": "", "confidence": 0.9},           # 空值
            {"type": "avoid", "value": "花生", "confidence": 0.3},       # 低置信度
            "not-a-dict",
        ]
    }
    out = _parse_signals(raw)
    assert len(out) == 1
    assert out[0]["type"] == "avoid" and out[0]["value"] == "香菜"


# ── 合并 ─────────────────────────────────────────────────────

def test_merge_avoid_and_flavor():
    p = UserProfile(user_id=1, flavor_spicy=3)
    n = merge_signals(p, [
        _sig("avoid", "香菜"),
        _sig("avoid", "香菜"),                    # 幂等：同 value 只记一次
        _sig("flavor", "辣", direction="up"),
        _sig("flavor", "辣", direction="up"),     # 幂等：已记录不重复调
    ])
    assert n == 2
    assert "香菜" in p.avoid_list
    assert p.flavor_spicy == 4
    log = p.preference_log
    assert len(log) == 2
    assert all(e["source"] == "chat" and e["created_at"] for e in log)


def test_merge_flavor_clip_bounds():
    p = UserProfile(user_id=1, flavor_spicy=5)
    merge_signals(p, [_sig("flavor", "辣", direction="up")])   # 上限 5
    assert p.flavor_spicy == 5
    p2 = UserProfile(user_id=2, flavor_spicy=1)
    merge_signals(p2, [_sig("flavor", "辣", direction="down")])  # 下限 1
    assert p2.flavor_spicy == 1


def test_merge_tool_diet_skill():
    p = UserProfile(user_id=1, diet_type="无限制", skill_level="新手")
    n = merge_signals(p, [
        _sig("tool", "空气炸锅"),
        _sig("diet", "减脂", confidence=0.9),
        _sig("skill", "进阶", confidence=0.6),    # 低置信不覆盖
        _sig("cuisine", "川菜"),
    ])
    assert n == 4
    assert "空气炸锅" in p.tools
    assert p.diet_type == "减脂"
    assert p.skill_level == "新手"
    assert p.preference_log[-1]["type"] == "cuisine"


# ── 打分消费（§8.5 cuisine 信号） ───────────────────────────

def _item(cuisines: list[str]) -> dict:
    return {"dish_id": "x", "name": "x", "cuisines": cuisines, "text": "", "flavors": []}


def test_personal_score_cuisine_signal_boost():
    base = {"flavor_spicy": 3, "flavor_sweet": 3, "flavor_sour": 3, "flavor_light": 3,
            "skill_level": "新手", "goal": "均衡", "tools": [], "preference_log": []}
    no_signal = personal_score(_item(["川菜"]), dict(base))
    base["preference_log"] = [_sig("cuisine", "川菜", confidence=0.9)]
    with_signal = personal_score(_item(["川菜"]), base)
    assert with_signal > no_signal
