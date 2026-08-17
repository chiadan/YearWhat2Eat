"""parser 单元测试（§13.4）：用内存 md 文本验证解析逻辑，不依赖真实数据源。"""
from app.pipeline.parser import _parse_dish_md, _parse_tip_md, _dish_id, parse_corpus

SAMPLE_DISH = """# 测试菜的做法

这是一道测试菜的简介。

预估烹饪难度：★★★

## 必备原料和工具

- 手枪腿（或者鸡胸脯肉）
- 生抽酱油
- 炒锅
- 菜刀

### 可选原料

- 油泼辣子

## 计算

- 手枪腿 = 1 支（约 350g）

## 操作

### 简易版本

- 鸡肉切丁
- 大火翻炒 2 分钟

### 进阶版本

- 鸡肉腌制 1 小时
- 小火慢炒

## 附加内容

注意火候。
"""

SAMPLE_TIP = """# 测试技巧

## 为什么要焯水

焯水可以去除血沫和腥味。

## 焯水多久

绿叶菜 30 秒即可。
"""


def test_parse_dish_basic():
    dish = _parse_dish_md(SAMPLE_DISH, "meat_dish/测试菜.md")
    assert dish.name == "测试菜"
    assert dish.category == "meat_dish"
    assert dish.difficulty == 3
    assert dish.intro == "这是一道测试菜的简介。"
    assert "手枪腿" in " ".join(dish.required_raw)
    assert "油泼辣子" in " ".join(dish.optional_raw)
    assert "计算" in (dish.calculation_raw or "")
    assert len(dish.steps) == 4
    assert dish.steps[0].version == "简易版本"
    assert dish.steps[2].version == "进阶版本"
    assert dish.notes and "注意火候" in dish.notes


def test_parse_dish_missing_sections():
    dish = _parse_dish_md("# 极简菜的做法\n\n就一步。\n", "vegetable_dish/极简菜.md")
    assert dish.difficulty is None
    assert dish.required_raw == []
    assert dish.calculation_raw is None
    assert dish.steps == []


def test_dish_id_stable_and_unique():
    assert _dish_id("meat_dish/宫保鸡丁/宫保鸡丁.md") == _dish_id("meat_dish/宫保鸡丁/宫保鸡丁.md")
    assert _dish_id("meat_dish/a.md") != _dish_id("soup/a.md")
    # 同名菜（§2.2）：路径不同 → id 不同
    assert _dish_id("soup/陈皮排骨汤/陈皮排骨汤.md") != _dish_id("soup/陈皮排骨汤.md")


def test_parse_tip():
    tip = _parse_tip_md(SAMPLE_TIP, "learn/测试技巧.md")
    assert tip.title == "测试技巧"
    assert tip.category == "learn"
    assert len(tip.chunks) == 2
    assert "焯水" in tip.chunks[0]


def test_parse_corpus_uses_template_exclusion(tmp_path):
    (tmp_path / "dishes").mkdir(parents=True)
    (tmp_path / "tips").mkdir()
    (tmp_path / "dishes" / "template" / "示例菜").mkdir(parents=True)
    (tmp_path / "dishes" / "template" / "示例菜" / "示例菜.md").write_text("# 示例菜的做法\n", encoding="utf-8")
    (tmp_path / "dishes" / "meat_dish").mkdir()
    (tmp_path / "dishes" / "meat_dish" / "宫保鸡丁.md").write_text("# 宫保鸡丁的做法\n", encoding="utf-8")
    (tmp_path / "tips" / "learn").mkdir()
    (tmp_path / "tips" / "learn" / "去腥.md").write_text("# 去腥\n", encoding="utf-8")

    corpus = parse_corpus(tmp_path)
    assert len(corpus.dishes) == 1  # 模板被排除（§5 Step1）
    assert corpus.dishes[0].name == "宫保鸡丁"
    assert len(corpus.tips) == 1
    assert corpus.alias_table["宫保鸡丁"] == ["meat_dish/宫保鸡丁.md"]
