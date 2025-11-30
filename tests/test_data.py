"""Tests for data module."""
import pytest
from src.data import (
    get_staff_list, get_full_time_staff, get_part_time_staff,
    get_september_2025_calendar, get_staff_preferences,
    get_merged_staff_preferences, get_previous_month_carryover,
    get_constraints_config
)
from src.models import StaffType, DayType


class TestStaffList:
    def test_total_staff_count(self):
        staff_list = get_staff_list()
        assert len(staff_list) == 12

    def test_full_time_count(self):
        full_time = get_full_time_staff()
        assert len(full_time) == 9

    def test_part_time_count(self):
        part_time = get_part_time_staff()
        assert len(part_time) == 3

    def test_staff_ids_unique(self):
        staff_list = get_staff_list()
        ids = [s.id for s in staff_list]
        assert len(ids) == len(set(ids))


class TestCalendar:
    def test_calendar_days(self):
        calendar = get_september_2025_calendar()
        assert len(calendar) == 30  # September has 30 days

    def test_calendar_starts_monday(self):
        calendar = get_september_2025_calendar()
        assert calendar[0].weekday == "月"
        assert calendar[0].day == 1

    def test_holidays(self):
        calendar = get_september_2025_calendar()
        holidays = [d for d in calendar if d.day_type == DayType.HOLIDAY]
        assert len(holidays) == 3  # 15, 22, 23

        holiday_days = [d.day for d in holidays]
        assert 15 in holiday_days  # 敬老の日
        assert 22 in holiday_days  # 秋分の日振替
        assert 23 in holiday_days  # 秋分の日

    def test_weekday_count(self):
        # Sept 2025: 30 days - 4 Sat - 4 Sun - 3 holidays = 19 weekdays
        calendar = get_september_2025_calendar()
        weekdays = [d for d in calendar if d.day_type == DayType.WEEKDAY]
        assert len(weekdays) == 19

    def test_weekend_count(self):
        calendar = get_september_2025_calendar()
        saturdays = [d for d in calendar if d.day_type == DayType.SATURDAY]
        sundays = [d for d in calendar if d.day_type == DayType.SUNDAY]
        # Sept 2025 has 4 Saturdays (6, 13, 20, 27) and 4 Sundays (7, 14, 21, 28)
        assert len(saturdays) == 4
        assert len(sundays) == 4

    def test_weekend_holiday_total(self):
        calendar = get_september_2025_calendar()
        weekend_holidays = [d for d in calendar if d.is_weekend_or_holiday()]
        # 4 Sat + 4 Sun + 3 holidays = 11 total
        assert len(weekend_holidays) == 11


class TestPreferences:
    def test_merged_preferences(self):
        merged = get_merged_staff_preferences()

        # 阿部 (S01) has requested off
        assert "S01" in merged
        assert 23 in merged["S01"].requested_off
        assert 25 in merged["S01"].requested_off

        # 安藤 (S02) has requested work
        assert "S02" in merged
        assert merged["S02"].requested_work == [1, 2, 3, 4]

        # 矢羽田 (S07) has both requested off and work
        assert "S07" in merged
        assert merged["S07"].requested_off == [18, 19, 20]
        assert merged["S07"].requested_work == [12, 13, 14, 15]

    def test_standby_unavailable(self):
        merged = get_merged_staff_preferences()

        # 松竹谷 (S05) cannot do standby on day 25
        assert "S05" in merged
        assert 25 in merged["S05"].standby_unavailable

        # 長川 (S09) cannot do standby on day 1 and 15
        assert "S09" in merged
        assert 1 in merged["S09"].standby_unavailable
        assert 15 in merged["S09"].standby_unavailable


class TestCarryover:
    def test_nagakawa_carryover(self):
        carryover = get_previous_month_carryover()
        assert len(carryover) == 1
        assert carryover[0].staff_id == "S09"  # 長川
        assert carryover[0].had_standby_on_last_day


class TestConfig:
    def test_config_values(self):
        config = get_constraints_config()

        assert config["full_time_work_days"] == 20
        assert config["full_time_off_days"] == 10
        assert config["max_consecutive_days"] == 5
        assert config["standby_min_interval"] == 6
        assert config["weekday_min_full_time"] == 7
        assert config["weekend_total_count"] == 3
