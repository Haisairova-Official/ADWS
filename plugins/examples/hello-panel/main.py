#!/usr/bin/env python3
"""ADWS panel.json-v1 示例插件。

--output-json  向 stdout 打印一行 JSON（宿主要求）
--click <键>    处理点击（可选，可空实现）
"""
import argparse
import json
from datetime import datetime


def render() -> dict:
    now = datetime.now()
    return {
        "text": "\U0001f44b",
        "alt": "hello",
        "class": "normal",
        "tooltip": "Hello ADWS\n%s" % now.strftime("%Y-%m-%d %H:%M:%S"),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="ADWS panel plugin")
    parser.add_argument("--output-json", action="store_true")
    parser.add_argument("--click", choices=("left", "right", "middle",
                                            "scroll-up", "scroll-down"))
    args = parser.parse_args(argv)
    if args.click:
        return 0  # 示例插件不响应点击
    payload = render()
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
