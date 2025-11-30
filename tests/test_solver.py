"""Tests for the shift scheduler solver."""
import pytest
from src.solver import ShiftScheduler
from src.models import (
    Staff, StaffType, DayInfo, DayType,
    StaffPreferences, PreviousMonthCarryover, ShiftType
)
from src.data import (
    get_staff_list, get_september_2025_calendar,
    get_merged_staff_preferences, get_previous_month_carryover,
    get_constraints_config
)


class TestSchedulerValidation:
    def test_validate_input_success(self):
        scheduler = create_scheduler()
        errors = scheduler.validate_input()
        assert len(errors) == 0

    def test_validate_preference_conflict(self):
        staff_list = get_staff_list()
        calendar = get_september_2025_calendar()
        carryover = get_previous_month_carryover()
        config = get_constraints_config()

        # Create conflicting preference
        preferences = {
            "S01": StaffPreferences(
                staff_id="S01",
                requested_off=[5, 10],
                requested_work=[5, 15]  # Day 5 conflicts with requested_off
            )
        }

        scheduler = ShiftScheduler(staff_list, calendar, preferences, carryover, config)
        errors = scheduler.validate_input()

        assert len(errors) == 1
        assert "重複" in errors[0]


class TestSchedulerFeasibility:
    def test_feasibility_check_success(self):
        scheduler = create_scheduler()
        conflicts = scheduler.check_feasibility()
        assert len(conflicts) == 0


class TestSchedulerSolve:
    @pytest.mark.slow
    def test_solve_basic(self):
        """Test that the solver finds a solution for the standard case."""
        scheduler = create_scheduler()
        schedule = scheduler.solve(time_limit_seconds=120)

        assert schedule is not None
        assert schedule.year == 2025
        assert schedule.month == 9

    @pytest.mark.slow
    def test_solve_full_time_work_days(self):
        """Test HC-01: Full-time staff work exactly 20 days."""
        scheduler = create_scheduler()
        schedule = scheduler.solve(time_limit_seconds=120)

        assert schedule is not None

        for stats in schedule.statistics:
            if stats.staff_id.startswith("S"):  # Full-time
                assert stats.work_days == 20, f"{stats.staff_name} has {stats.work_days} work days"
                assert stats.off_days == 10, f"{stats.staff_name} has {stats.off_days} off days"

    @pytest.mark.slow
    def test_solve_standby_count(self):
        """Test HC-05: Standby distribution (4x3 + 3x6 = 30)."""
        scheduler = create_scheduler()
        schedule = scheduler.solve(time_limit_seconds=120)

        assert schedule is not None

        # Total standby should be 30
        assert len(schedule.standby_assignments) == 30

        # Count standby per person
        standby_counts = {}
        for day, staff_id in schedule.standby_assignments.items():
            standby_counts[staff_id] = standby_counts.get(staff_id, 0) + 1

        # Should have 3 people with 4 times and 6 people with 3 times
        four_times = sum(1 for c in standby_counts.values() if c == 4)
        three_times = sum(1 for c in standby_counts.values() if c == 3)

        assert four_times == 3, f"Expected 3 with 4 times, got {four_times}"
        assert three_times == 6, f"Expected 6 with 3 times, got {three_times}"

    @pytest.mark.slow
    def test_solve_requested_off_respected(self):
        """Test HC-08: Requested off days are respected."""
        scheduler = create_scheduler()
        schedule = scheduler.solve(time_limit_seconds=120)

        assert schedule is not None

        preferences = get_merged_staff_preferences()

        for staff_id, pref in preferences.items():
            for day in pref.requested_off:
                assignment = next(
                    (a for a in schedule.assignments
                     if a.staff_id == staff_id and a.day == day),
                    None
                )
                assert assignment is not None
                assert assignment.shift_type == ShiftType.OFF, \
                    f"{staff_id} should be off on day {day}"

    @pytest.mark.slow
    def test_solve_nagakawa_day1(self):
        """Test HC-06: Nagakawa must work 8:00 on day 1."""
        scheduler = create_scheduler()
        schedule = scheduler.solve(time_limit_seconds=120)

        assert schedule is not None

        nagakawa_day1 = next(
            (a for a in schedule.assignments
             if a.staff_id == "S09" and a.day == 1),
            None
        )

        assert nagakawa_day1 is not None
        assert nagakawa_day1.shift_type == ShiftType.NORMAL, \
            "Nagakawa should work 8:00 on day 1"

    @pytest.mark.slow
    def test_solve_standby_interval(self):
        """Test HC-05: Standby interval >= 6 days."""
        scheduler = create_scheduler()
        schedule = scheduler.solve(time_limit_seconds=120)

        assert schedule is not None

        # Group standby by staff
        standby_by_staff = {}
        for day, staff_id in schedule.standby_assignments.items():
            if staff_id not in standby_by_staff:
                standby_by_staff[staff_id] = []
            standby_by_staff[staff_id].append(day)

        # Check intervals
        for staff_id, days in standby_by_staff.items():
            days.sort()
            for i in range(len(days) - 1):
                interval = days[i + 1] - days[i]
                assert interval >= 7, \
                    f"{staff_id} has standby interval of {interval} days (days {days[i]} to {days[i+1]})"


def create_scheduler() -> ShiftScheduler:
    """Create a scheduler with standard data."""
    return ShiftScheduler(
        staff_list=get_staff_list(),
        calendar=get_september_2025_calendar(),
        preferences=get_merged_staff_preferences(),
        carryover=get_previous_month_carryover(),
        config=get_constraints_config()
    )
