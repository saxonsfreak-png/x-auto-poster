"""
「日本時間の HH:MM」の設定値を、Buffer API が要求する UTC の ISO8601(dueAt)に変換する。

日本にはDST(サマータイム)がないため単純な固定オフセットでも動くが、
zoneinfo を使うことで意図をコードに残し、将来的な変更にも強くしておく。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")
UTC = ZoneInfo("UTC")


def compute_due_at_utc(time_str: str, now_jst: datetime | None = None) -> str:
    """time_str 例: "07:25"。

    実行時刻(now_jst)がその時刻を過ぎていれば翌日にロールする
    (手動で日中に再実行した場合でも、既に過ぎた時間帯に投稿しようとしないため)。
    """
    now_jst = now_jst or datetime.now(JST)
    hour, minute = (int(x) for x in time_str.split(":"))

    candidate = now_jst.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= now_jst:
        candidate += timedelta(days=1)

    due_at_utc = candidate.astimezone(UTC)
    return due_at_utc.strftime("%Y-%m-%dT%H:%M:%S.000Z")
