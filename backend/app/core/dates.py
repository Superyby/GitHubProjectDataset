from datetime import date, datetime
from zoneinfo import ZoneInfo


SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


def shanghai_today() -> date:
    return datetime.now(SHANGHAI_TZ).date()
