#!/usr/bin/env python3
"""fetch_pricing.py — 拉取 aihubmix 的模型官方定价，生成 pricing.json。

pricing.json 结构：{ "<model_id>": {"input": .., "output": .., "cache_read": .., "cache_write": ..} }
价格单位：USD / 每 1M tokens。带 context 分档 (tiers) 的模型当前只取基础档价格。

用法：python fetch_pricing.py
"""

import json
import urllib.request

URL = "https://aihubmix.com/api/v1/models"


def main():
    req = urllib.request.Request(URL, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r)

    out = {}
    for m in data.get("data", []):
        p = m.get("pricing") or {}
        out[m["model_id"]] = {
            "input": p.get("input", 0),
            "output": p.get("output", 0),
            "cache_read": p.get("cache_read", 0),
            "cache_write": p.get("cache_write", 0),
        }

    with open("pricing.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1, sort_keys=True)
    print(f"wrote {len(out)} models to pricing.json")


if __name__ == "__main__":
    main()
