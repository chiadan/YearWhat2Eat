"""意图路由规则单测（§6.4 规则快判，纯逻辑无依赖）。"""
from app.rag.nodes.intent_router import _rule_intent


def test_rule_intent_chitchat():
    intent, conf = _rule_intent("你好")
    assert intent == "chitchat" and conf >= 0.7


def test_rule_intent_tips_qa():
    intent, _ = _rule_intent("焯水要多久")
    assert intent == "tips_qa"


def test_rule_intent_recommend():
    intent, _ = _rule_intent("两个人晚餐想吃辣的")
    assert intent == "recommend"


def test_rule_intent_dish_qa():
    intent, _ = _rule_intent("宫保鸡丁怎么做")
    assert intent == "dish_qa"


def test_rule_intent_default():
    intent, conf = _rule_intent("随便说点什么")
    assert intent == "dish_qa" and conf < 0.7  # 低置信度走兜底（§6.4）
