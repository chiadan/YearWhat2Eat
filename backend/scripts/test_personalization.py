"""个性化推荐验收（§14 M4 标准：千人千面闭环自动化验证，可复用）。

用法：
    python scripts/test_personalization.py                    # 默认 http://localhost:8000
    python scripts/test_personalization.py --url http://localhost:8000 --query "两个人晚餐想吃辣的"

覆盖（每项 [PASS]/[FAIL] + 原因，最终退出码 0/1）：
  1. 用户准备：spicy_test / mild_test 注册（已存在则登录，幂等可复用）
  2. 画像设置：辣度 5 vs 1、技能 熟练 vs 新手
  3. ★ 同 query 不同画像 → plan 推荐不同（§14 M4 核心验收）
  4. ★ 反馈闭环：spicy 👎 上轮第一道荤菜 → 重问 → 该菜消失或降权（§8.2）
  5. 游客流程：guest → 行为写入 → upgrade 合并 → 新账号可见行为
  6. ★ 忌口硬过滤：spicy 画像加 avoid_list=["香菜"] → 重问 → 推荐无香菜菜
  7. ★ 素食硬过滤：vegan_test 画像 diet_type=素食 → plan 荤菜槽为空
  8. ★ 工具硬过滤：tool_test 画像 tools=[空气炸锅,微波炉] → 推荐菜名含对应工具
  9. 新手难度：newbie_test 画像 skill_level=新手 → plan 正常产出（难度明细留前端展示）
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

DEFAULT_QUERY = "两个人晚餐想吃辣的"


def _http(base: str, method: str, path: str, body: dict | None = None, token: str | None = None):
    req = urllib.request.Request(
        base + path,
        method=method,
        data=json.dumps(body or {}).encode("utf-8") if body is not None else None,
        headers={"Content-Type": "application/json"},
    )
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            return resp.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read() or b"{}")
        except (ValueError, json.JSONDecodeError):
            detail = {}
        return exc.code, detail


def chat_stream(base: str, message: str, token: str | None = None, message_id: str | None = None):
    """调用 /chat/stream，返回 (events, plan, answer, sources)。"""
    body = {"message": message, "message_id": message_id}
    req = urllib.request.Request(
        base + "/chat/stream",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    events: list[tuple[str, dict]] = []
    plan: dict | None = None
    answer_parts: list[str] = []
    sources: list[dict] = []
    with urllib.request.urlopen(req, timeout=180) as resp:
        current = ""
        for raw in resp:
            line = raw.decode("utf-8").rstrip()
            if line.startswith("event: "):
                current = line[len("event: "):]
            elif line.startswith("data: "):
                data = json.loads(line[len("data: "):])
                events.append((current, data))
                if current == "plan":
                    plan = data.get("plan")
                elif current == "text":
                    answer_parts.append(data.get("delta", ""))
                elif current == "sources":
                    sources = data.get("items", [])
    return events, plan, "".join(answer_parts), sources


def ensure_user(base: str, username: str, password: str) -> str:
    code, data = _http(base, "POST", "/auth/register", {"username": username, "password": password})
    if code == 409:  # 已存在 → 登录（幂等复用）
        code, data = _http(base, "POST", "/auth/login", {"username": username, "password": password})
    if code not in (200, 201):
        raise SystemExit(f"[ERROR] 用户 {username} 准备失败: {code} {data}")
    return data["access_token"]


def plan_dish_ids(plan: dict | None, slot: str) -> list[str]:
    return [d.get("dish_id") for d in (plan or {}).get(slot, []) or []]


def main() -> None:
    parser = argparse.ArgumentParser(description="M4 千人千面验收")
    parser.add_argument("--url", default="http://localhost:8000/api/v1")
    parser.add_argument("--query", default=DEFAULT_QUERY)
    args = parser.parse_args()
    base = args.url.rstrip("/")

    checks: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str) -> None:
        checks.append((name, ok, detail))
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}: {detail}")

    print("== M4 千人千面验收 ==")

    # 1. 用户准备（幂等：已存在则登录）
    print("[1] 用户准备（spicy_test / mild_test）")
    spicy_tok = ensure_user(base, "spicy_test", "secret123")
    mild_tok = ensure_user(base, "mild_test", "secret123")
    print(f"  OK spicy_test={spicy_tok[:16]}... mild_test={mild_tok[:16]}...")

    # 2. 画像设置
    print("[2] 画像设置（辣度 5 vs 1，技能 熟练 vs 新手）")
    for tok, profile in (
        (spicy_tok, {"flavor_spicy": 5, "flavor_light": 1, "skill_level": "熟练", "avoid_list": []}),
        (mild_tok, {"flavor_spicy": 1, "flavor_light": 5, "skill_level": "新手", "avoid_list": []}),
    ):
        code, data = _http(base, "PUT", "/users/me/profile", profile, tok)
        if code != 200:
            raise SystemExit(f"[ERROR] 画像设置失败: {code} {data}")
    print("  OK")

    # 3. ★ 同 query 不同画像 → 推荐不同
    print(f"[3] 同 query 不同画像 -> 推荐不同（query: {args.query}）")
    stamp = str(int(time.time()))
    _, plan_a, _, _ = chat_stream(base, args.query, spicy_tok, f"m4a-{stamp}")
    _, plan_b, _, _ = chat_stream(base, args.query, mild_tok, f"m4b-{stamp}")

    if not plan_a or not plan_b:
        check("推荐差异", False, f"plan 为空（spicy={plan_a is not None}, mild={plan_b is not None}），请检查推荐链路")
    else:
        meat_a, veg_a = plan_dish_ids(plan_a, "meat"), plan_dish_ids(plan_a, "veg")
        meat_b, veg_b = plan_dish_ids(plan_b, "meat"), plan_dish_ids(plan_b, "veg")
        differ = (meat_a + veg_a) != (meat_b + veg_b)
        check(
            "推荐差异",
            differ,
            f"spicy={plan_a.get('meat', []) + plan_a.get('veg', [])} | "
            f"mild={plan_b.get('meat', []) + plan_b.get('veg', [])}",
        )
        if differ:
            names_a = [d["name"] for d in plan_a.get("meat", []) + plan_a.get("veg", [])]
            names_b = [d["name"] for d in plan_b.get("meat", []) + plan_b.get("veg", [])]
            print(f"      spicy 推荐: {'、'.join(names_a)}")
            print(f"      mild  推荐: {'、'.join(names_b)}")

    # 4. ★ 反馈闭环：spicy 👎 第一道荤菜 → 重问 → 消失或降权
    print("[4] 反馈闭环（👎 第一道荤菜 → 重问）")
    target = (plan_a or {}).get("meat", [{}])[0].get("dish_id") if (plan_a or {}).get("meat") else None
    if target is None:
        check("👎 闭环", False, "spicy 的 plan 无荤菜，无法测试 👎 闭环")
    else:
        code, data = _http(base, "POST", "/users/me/feedback", {"dish_id": target, "action": "dislike"}, spicy_tok)
        if code != 200:
            check("👎 闭环", False, f"feedback 失败: {code} {data}")
        else:
            _, plan_c, _, _ = chat_stream(base, args.query, spicy_tok, f"m4c-{stamp}")
            if not plan_c:
                check("👎 闭环", False, "重问后 plan 为空")
            else:
                current_ids = plan_dish_ids(plan_c, "meat") + plan_dish_ids(plan_c, "veg")
                gone = target not in current_ids
                names_c = [d["name"] for d in plan_c.get("meat", []) + plan_c.get("veg", [])]
                check(
                    "👎 闭环",
                    gone,
                    f"👎 的菜 {'已从推荐中移除' if gone else '仍在推荐中'}（候选不足时允许保留）: {names_c}",
                )
                print(f"      👎 菜: {target} | 重问推荐: {'、'.join(names_c)}")

    # 5. 游客 → 行为 → upgrade 合并
    print("[5] 游客升级合并")
    code, guest = _http(base, "POST", "/auth/guest")
    if code != 200:
        check("游客流程", False, f"guest 失败: {code} {guest}")
    else:
        g_tok = guest["access_token"]
        some_dish = (plan_a or {}).get("meat", [{}])[0].get("dish_id") or (plan_a or {}).get("veg", [{}])[0].get("dish_id")
        if some_dish:
            _http(base, "POST", "/users/me/feedback", {"dish_id": some_dish, "action": "view"}, g_tok)
        new_username = f"newbie_{stamp}"
        code, upgraded = _http(
            base, "POST", "/auth/upgrade",
            {"guest_token": g_tok, "username": new_username, "password": "secret123"},
        )
        if code != 200:
            check("游客流程", False, f"upgrade 失败: {code} {upgraded}")
        else:
            _, fb = _http(base, "GET", "/users/me/feedback?page_size=5", token=upgraded["access_token"])
            merged = bool(fb and fb.get("items"))
            check("游客流程", merged, f"游客行为已合并进新账号 {new_username}（行为数={len((fb or {}).get('items') or [])}）")

    # 6. ★ 忌口硬过滤（§8.1）：spicy 画像加"不吃香菜" → 推荐无香菜菜
    print("[6] 忌口硬过滤（不吃香菜）")
    code, data = _http(
        base, "PUT", "/users/me/profile",
        {"flavor_spicy": 5, "flavor_light": 1, "skill_level": "熟练", "avoid_list": ["香菜"]},
        spicy_tok,
    )
    if code != 200:
        check("忌口过滤", False, f"画像更新失败: {code} {data}")
    else:
        _, plan_d, _, _ = chat_stream(base, args.query, spicy_tok, f"m4d-{stamp}")
        if not plan_d:
            check("忌口过滤", False, "plan 为空")
        else:
            names = [d["name"] for d in plan_d.get("meat", []) + plan_d.get("veg", [])]
            no_coriander = not any("香菜" in n for n in names)
            check("忌口过滤", no_coriander, f"推荐: {'、'.join(names)}")

    # 7. ★ 素食硬过滤（§8.1）：vegan 画像 → plan 荤菜槽为空
    print("[7] 素食硬过滤（diet_type=素食）")
    vegan_tok = ensure_user(base, "vegan_test", "secret123")
    code, data = _http(
        base, "PUT", "/users/me/profile",
        {"diet_type": "素食", "flavor_spicy": 3, "avoid_list": []},
        vegan_tok,
    )
    if code != 200:
        check("素食过滤", False, f"画像更新失败: {code} {data}")
    else:
        _, plan_e, _, _ = chat_stream(base, "两个人晚餐吃什么", vegan_tok, f"m4e-{stamp}")
        if not plan_e:
            check("素食过滤", False, "plan 为空")
        else:
            meat_names = [d["name"] for d in plan_e.get("meat", [])]
            check(
                "素食过滤",
                not meat_names,
                f"荤菜槽应为空，实际: {meat_names or '（空，正确）'} | 素菜: {'、'.join(d['name'] for d in plan_e.get('veg', []))}",
            )

    # 8. ★ 工具硬过滤（§8.1）：tools=[空气炸锅,微波炉] → 推荐菜名含对应工具
    print("[8] 工具硬过滤（空气炸锅 / 微波炉）")
    tool_tok = ensure_user(base, "tool_test", "secret123")
    code, data = _http(
        base, "PUT", "/users/me/profile",
        {"tools": ["空气炸锅", "微波炉"], "skill_level": "新手", "avoid_list": []},
        tool_tok,
    )
    if code != 200:
        check("工具过滤", False, f"画像更新失败: {code} {data}")
    else:
        _, plan_f, _, _ = chat_stream(
            base, "两个人晚餐，用空气炸锅或微波炉能做点什么", tool_tok, f"m4f-{stamp}"
        )
        if not plan_f:
            check("工具过滤", False, "plan 为空")
        else:
            names = [d["name"] for d in plan_f.get("meat", []) + plan_f.get("veg", []) + plan_f.get("soup", [])]
            tool_match = any(("空气炸锅" in n or "微波炉" in n) for n in names)
            check("工具过滤", tool_match, f"推荐: {'、'.join(names)}")

    # 9. 新手难度（弱断言：plan 正常产出；难度明细由前端展示）
    print("[9] 新手技能过滤（skill_level=新手）")
    newbie_tok = ensure_user(base, "newbie_skill_test", "secret123")
    code, data = _http(
        base, "PUT", "/users/me/profile",
        {"skill_level": "新手", "flavor_spicy": 3, "avoid_list": []},
        newbie_tok,
    )
    if code != 200:
        check("新手过滤", False, f"画像更新失败: {code} {data}")
    else:
        _, plan_g, _, _ = chat_stream(base, "两个人晚餐吃点好的", newbie_tok, f"m4g-{stamp}")
        names = [d["name"] for d in (plan_g or {}).get("meat", []) + (plan_g or {}).get("veg", [])] if plan_g else []
        check("新手过滤", bool(names), f"推荐正常产出（难度≤3 由 rule_filter 保证）: {'、'.join(names) or 'plan 为空'}")

    print("\n提示: 可再运行 python -m tests.eval.run_eval 确认 M2/M3 检索与约束指标未回退")

    # 汇总
    passed = sum(1 for _, ok, _ in checks if ok)
    print(f"\n== 结果: {passed}/{len(checks)} PASS ==")
    for name, ok, detail in checks:
        if not ok:
            print(f"  [FAIL] {name}: {detail}")
    sys.exit(0 if passed == len(checks) and checks else 1)


if __name__ == "__main__":
    main()
