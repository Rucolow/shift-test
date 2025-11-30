"""Tests for data models."""
import pytest
from src.models import (
    Staff, StaffType, ShiftType, DayType, DayInfo,
    StaffPreferences, FeasibilityError, NoSolutionError
)


class TestStaff:
    def test_full_time_staff(self):
        staff = Staff(id="S01", name="阿部", staff_type=StaffType.FULL_TIME)
        assert staff.is_full_time()
        assert not staff.is_part_time()
        assert staff.can_standby

    def test_part_time_staff(self):
        staff = Staff(id="P01", name="野中", staff_type=StaffType.PART_TIME, work_hours="9:00-17:00")
        assert not staff.is_full_time()
        assert staff.is_part_time()
        assert not staff.can_standby  # Part-time cannot do standby

    def test_part_time_cannot_standby(self):
        # Even if can_standby is set to True, it should be False for part-time
        staff = Staff(id="P01", name="野中", staff_type=StaffType.PART_TIME, can_standby=True)
        assert not staff.can_standby


class TestShiftType:
    def test_shift_type_values(self):
        assert str(ShiftType.EARLY) == "7:30"
        assert str(ShiftType.NORMAL) == "8:00"
        assert str(ShiftType.LATE) == "9:00"
        assert str(ShiftType.OFF) == "休"


class TestDayType:
    def test_weekday_not_weekend(self):
        assert not DayType.WEEKDAY.is_weekend_or_holiday()

    def test_weekend_and_holiday(self):
        assert DayType.SATURDAY.is_weekend_or_holiday()
        assert DayType.SUNDAY.is_weekend_or_holiday()
        assert DayType.HOLIDAY.is_weekend_or_holiday()


class TestDayInfo:
    def test_day_info_weekday(self):
        day = DayInfo(day=1, weekday="月", day_type=DayType.WEEKDAY)
        assert not day.is_weekend_or_holiday()

    def test_day_info_holiday(self):
        day = DayInfo(day=15, weekday="月", day_type=DayType.HOLIDAY, note="敬老の日")
        assert day.is_weekend_or_holiday()


class TestExceptions:
    def test_feasibility_error(self):
        conflicts = ["制約1が矛盾", "制約2が矛盾"]
        error = FeasibilityError(conflicts)
        assert error.conflicts == conflicts
        assert "制約1が矛盾" in str(error)

    def test_no_solution_error(self):
        error = NoSolutionError("Phase 3", "理由説明")
        assert error.phase == "Phase 3"
        assert error.reason == "理由説明"
