"""快速测试 /chat/stream（SSE 流式，§9.1）——Windows PowerShell 下无转义烦恼。

用法：
    python scripts/test_chat.py "宫保鸡丁怎么勾芡"
    python scripts/test_chat.py "两个人晚餐想吃辣的" --message-id test-002
    python scripts/test_chat.py "第二步再说细一点" --session-id 10    # 多轮追问（session_id 取上一条 done 帧）
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request


def main() -> None:
    parser = argparse.ArgumentParser(description="SSE 聊天测试（打印事件流）")
    parser.add_argument("message", help="要发送的消息")
    parser.add_argument("--message-id", default=None, help="幂等 ID（可选）")
    parser.add_argument("--session-id", type=int, default=None, help="会话 ID（多轮追问，取上一条 done 帧）")
    parser.add_argument("--token", default=None, help="Bearer access token（可选，带画像个性化）")
    parser.add_argument("--url", default="http://localhost:8000/api/v1/chat/stream")
    args = parser.parse_args()

    body = json.dumps({
        "message": args.message,
        "message_id": args.message_id,
        "session_id": args.session_id,
    }).encode("utf-8")
    req = urllib.request.Request(
        args.url,
        data=body,
        headers={"Content-Type": "application/json"},
    )
    if args.token:
        req.add_header("Authorization", f"Bearer {args.token}")
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            print(f"HTTP {resp.status} {resp.reason}", file=sys.stderr)
            body_lines = 0
            for raw in resp:
                line = raw.decode("utf-8", errors="replace").rstrip()
                if line:
                    print(line)
                    body_lines += 1
            if body_lines == 0:
                print("!! 响应体为空：后端可能未运行最新代码，或返回了空流", file=sys.stderr)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        print(f"HTTP {exc.code}: {detail}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:  # noqa: BLE001
        print(f"请求失败: {exc}", file=sys.stderr)
        sys.exit(1)
    print("--- stream ended ---")


if __name__ == "__main__":
    main()
