from datetime import date, datetime, timezone
from unittest import TestCase
from unittest.mock import patch

from app.core.dates import shanghai_today


class FixedDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        utc_now = cls(2026, 5, 24, 19, 30, tzinfo=timezone.utc)
        return utc_now.astimezone(tz) if tz else utc_now.replace(tzinfo=None)


class ShanghaiTodayTests(TestCase):
    def test_uses_shanghai_date_when_server_utc_date_is_previous_day(self):
        with patch("app.core.dates.datetime", FixedDateTime):
            self.assertEqual(shanghai_today(), date(2026, 5, 25))
