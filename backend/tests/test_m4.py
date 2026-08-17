"""M4 纯逻辑单测：personal_score 画像差异 / profile 默认 / 密码哈希（不依赖容器）。"""
from app.services.auth_service import hash_password, verify_password
from app.services.personalization import personal_score
from app.services.profile_service import DEFAULT_PROFILE


def test_password_hash():
    h = hash_password("secret123")
    assert verify_password("secret123", h)
    assert not verify_password("wrong", h)


def _item(name: str, spicy_text: str) -> dict:
    return {
        "dish_id": name, "name": name, "category": "meat_dish", "difficulty": 3,
        "time_est": 30, "meat_attr": "荤", "text": spicy_text, "flavors": [spicy_text[0]],
    }


def test_personal_score_spicy_vs_mild():
    """辣党（spicy=5）与清淡党（spicy=1）对辣菜打分应显著不同（§6.5 口味匹配）。"""
    spicy_dish = _item("辣子鸡", "麻辣鲜香")
    mild_dish = _item("清蒸鲈鱼", "清淡鲜美")
    base = dict(DEFAULT_PROFILE, skill_level="进阶")

    p_spicy = dict(base, flavor_spicy=5)
    p_mild = dict(base, flavor_spicy=1)

    assert personal_score(spicy_dish, p_spicy) > personal_score(mild_dish, p_spicy)
    assert personal_score(mild_dish, p_mild) > personal_score(spicy_dish, p_mild)


def test_personal_score_no_profile_neutral():
    assert personal_score({"dish_id": "x"}, None) == 0.5
    assert personal_score({"dish_id": "x"}, {}) == 0.5


def test_profile_defaults():
    assert DEFAULT_PROFILE["flavor_spicy"] == 3
    assert DEFAULT_PROFILE["skill_level"] == "新手"
    assert DEFAULT_PROFILE["family_size"] == 2
