"""外部业务服务 Provider 协议与公共工具。

每个域一个协议 + Mock 实现（读 data/fixtures，确定性）+ Real 空壳
（NotImplementedError，正式落地对接官方开放 API 时替换）。
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"


def load_fixture(name: str) -> dict:
    with open(DATA_DIR / f"{name}.json", encoding="utf-8") as f:
        return json.load(f)


def resolve_date(offset_or_date: str | int | None = None) -> str:
    """'tomorrow' / '+N' / 'YYYY-MM-DD' / '今天' / '明天' / '后天' / None → ISO 日期。"""
    today = date.today()
    if offset_or_date is None:
        return today.isoformat()
    if isinstance(offset_or_date, int):
        return (today + timedelta(days=offset_or_date)).isoformat()
    s = str(offset_or_date).strip()
    chinese_map = {
        "今天": 0, "当日": 0, "当天": 0, "today": 0,
        "明天": 1, "次日": 1, "第二天": 1, "tomorrow": 1,
        "后天": 2, "大后天": 3,
    }
    if s in chinese_map:
        return (today + timedelta(days=chinese_map[s])).isoformat()
    for kw, offset in chinese_map.items():
        if kw in s:
            return (today + timedelta(days=offset)).isoformat()
    if s.startswith("+"):
        try:
            return (today + timedelta(days=int(s[1:]))).isoformat()
        except ValueError:
            pass
    return s


def derive_no(prefix: str, *parts) -> str:
    """由参数确定性派生编号（同输入同输出，演示可复现；不受 PYTHONHASHSEED 影响）。"""
    import hashlib

    digest = hashlib.md5("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()
    return f"{prefix}{int(digest[:8], 16) % 10_000_000:09d}"
