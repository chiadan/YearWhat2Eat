"""M3 纯逻辑单测：荤素公式 / 动物识别 / 约束规则解析（不依赖容器与 LLM）。"""
from app.rag.nodes.planner import _animal_of
from app.rag.nodes.query_analyzer import _parse_people, _rule_constraints
from app.rag.tools import calculate_menu_ratio


def test_parse_people():
    assert _parse_people("3") == 3
    assert _parse_people("两") == 2
    assert _parse_people("三") == 3
    assert _parse_people("十二") == 12
    assert _parse_people("二十") == 20


def test_menu_ratio():
    assert calculate_menu_ratio(3) == {"veg": 2, "meat": 2, "people": 3}   # (3+1)/2
    assert calculate_menu_ratio(2) == {"veg": 1, "meat": 2, "people": 2}
    assert calculate_menu_ratio(4) == {"veg": 2, "meat": 3, "people": 4}


def test_animal_of():
    item = {"name": "宫保鸡丁", "main_ingredients": ["鸡胸肉", "花生"]}
    assert _animal_of(item) == "鸡"
    item2 = {"name": "红烧肉", "main_ingredients": ["五花肉"]}
    assert _animal_of(item2) == "猪"
    item3 = {"name": "地三鲜", "main_ingredients": ["茄子", "土豆"]}
    assert _animal_of(item3) is None


def test_rule_constraints_basic():
    c = _rule_constraints("3 人晚餐想吃辣，30 分钟内，不吃香菜", [])
    assert c.people == 3
    assert c.meal_time == "晚餐"
    assert c.max_time_min == 30
    assert "辣" in c.flavors
    assert "香菜" in c.avoids


def test_rule_constraints_diet():
    c = _rule_constraints("最近减肥，想吃清淡的", [])
    assert c.diet_type == "减脂"
    assert "清淡" in c.flavors


def test_rule_constraints_history_inherit():
    history = [{"role": "user", "content": "我不吃羊肉"}]
    c = _rule_constraints("那两个人晚上吃什么", history)
    assert "羊肉" in c.avoids  # 上轮约束继承（§6.2 第 7 条）
    assert c.people == 2
