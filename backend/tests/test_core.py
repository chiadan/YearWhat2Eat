"""config / tagger 兜底单元测试（§13.4）。"""
from app.core.config import Settings
from app.pipeline.parser import DishRecord
from app.pipeline.tagger import _rule_fallback


def test_settings_defaults():
    s = Settings(_env_file=None)
    assert s.llm_model == "deepseek-v4-flash"
    assert s.embedding_model == "BAAI/bge-small-zh-v1.5"
    assert s.embedding_dim == 512
    assert s.backend_port == 8000
    assert "localhost:5173" in s.cors_origin_list


def test_settings_env_override(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "deepseek-chat")
    monkeypatch.setenv("BACKEND_PORT", "9000")
    s = Settings(_env_file=None)
    assert s.llm_model == "deepseek-chat"
    assert s.backend_port == 9000


def test_rule_fallback_category():
    dish = DishRecord(
        dish_id="x", name="红烧肉", category="meat_dish", rel_path="meat_dish/红烧肉.md",
        difficulty=3, intro=None,
        required_raw=["五花肉", "冰糖", "生抽酱油"],
        calculation_raw=None, steps=[], notes=None,
    )
    tags = _rule_fallback(dish)
    assert tags.meat_attr == "荤"
    assert "五花肉" in tags.main_ingredients


def test_rule_fallback_techniques_and_time():
    from app.pipeline.parser import StepRecord

    dish = DishRecord(
        dish_id="y", name="清蒸鱼", category="aquatic", rel_path="aquatic/清蒸鱼.md",
        difficulty=None, intro=None, required_raw=["鲈鱼"],
        calculation_raw=None,
        steps=[StepRecord(version="default", order=1, text="大火蒸 8 分钟")],
        notes=None,
    )
    tags = _rule_fallback(dish)
    assert "蒸" in tags.techniques
    assert tags.time_est_min == 8
