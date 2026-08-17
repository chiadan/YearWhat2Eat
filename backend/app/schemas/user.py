"""user 请求 DTO。"""
from pydantic import BaseModel, Field


class ProfileUpdateRequest(BaseModel):
    flavor_spicy: int | None = Field(default=None, ge=1, le=5)
    flavor_sweet: int | None = Field(default=None, ge=1, le=5)
    flavor_sour: int | None = Field(default=None, ge=1, le=5)
    flavor_light: int | None = Field(default=None, ge=1, le=5)
    avoid_list: list[str] | None = None
    diet_type: str | None = None
    skill_level: str | None = None
    tools: list[str] | None = None
    family_size: int | None = Field(default=None, ge=1, le=20)
    budget_level: str | None = None
    goal: str | None = None


class FeedbackRequest(BaseModel):
    dish_id: str
    action: str  # view|like|dislike|rating|made
    rating: int | None = Field(default=None, ge=1, le=5)
