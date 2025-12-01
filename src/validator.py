"""Shift schedule validation for the hospital shift management system."""
from dataclasses import dataclass, field
from typing import Optional

from .models import (
    Staff, StaffType, DayInfo, DayType, ShiftType,
    StaffPreferences, PreviousMonthCarryover, MonthlySchedule, ShiftAssignment
)


@dataclass
class ValidationItem:
    """A single validation check result."""
    name: str
    passed: bool
    details: list[str] = field(default_factory=list)
    sub_items: list["ValidationItem"] = field(default_factory=list)


@dataclass
class ValidationResult:
    """Complete validation result."""
    items: list[ValidationItem] = field(default_factory=list)

    @property
    def total_checks(self) -> int:
        return len(self.items)

    @property
    def passed_checks(self) -> int:
        return sum(1 for item in self.items if item.passed)

    @property
    def all_passed(self) -> bool:
        return all(item.passed for item in self.items)


class ShiftValidator:
    """Validates shift schedules against all constraints."""

    def __init__(
        self,
        schedule: MonthlySchedule,
        staff_list: list[Staff],
        calendar: list[DayInfo],
        preferences: dict[str, StaffPreferences],
        carryover: list[PreviousMonthCarryover]
    ):
        self.schedule = schedule
        self.staff_list = staff_list
        self.staff_map = {s.id: s for s in staff_list}
        self.full_time_staff = [s for s in staff_list if s.is_full_time()]
        self.calendar = calendar
        self.day_info_map = {d.day: d for d in calendar}
        self.preferences = preferences
        self.carryover = carryover
        self.carryover_map = {c.staff_id: c for c in carryover}

    def validate_all(self) -> ValidationResult:
        """Run all validation checks."""
        result = ValidationResult()

        result.items.append(self._check_work_days())
        result.items.append(self._check_weekday_staffing())
        result.items.append(self._check_weekend_holiday_staffing())
        result.items.append(self._check_standby_rules())
        result.items.append(self._check_requested_off())
        result.items.append(self._check_requested_work())
        result.items.append(self._check_standby_unavailable())
        result.items.append(self._check_consecutive_work())
        result.items.append(self._check_carryover())

        return result

    def _get_staff_assignments(self, staff_id: str) -> list[ShiftAssignment]:
        """Get all assignments for a staff member."""
        return [a for a in self.schedule.assignments if a.staff_id == staff_id]

    def _get_day_assignments(self, day: int) -> list[ShiftAssignment]:
        """Get all assignments for a specific day."""
        return [a for a in self.schedule.assignments if a.day == day]

    def _check_work_days(self) -> ValidationItem:
        """Check work days (20) and off days (10) for all full-time staff."""
        violations = []

        for staff in self.full_time_staff:
            assignments = self._get_staff_assignments(staff.id)
            work_days = sum(1 for a in assignments if a.shift_type != ShiftType.OFF)
            off_days = sum(1 for a in assignments if a.shift_type == ShiftType.OFF)

            if work_days != 20:
                diff = work_days - 20
                if diff > 0:
                    violations.append(f"{staff.name}: 勤務{work_days}日（{diff}日超過）")
                else:
                    violations.append(f"{staff.name}: 勤務{work_days}日（{-diff}日不足）")

            if off_days != 10:
                diff = off_days - 10
                if diff > 0:
                    violations.append(f"{staff.name}: 休日{off_days}日（{diff}日超過）")
                else:
                    violations.append(f"{staff.name}: 休日{off_days}日（{-diff}日不足）")

        return ValidationItem(
            name="勤務日数",
            passed=len(violations) == 0,
            details=violations if violations else ["全員20日勤務、10日休日"]
        )

    def _check_weekday_staffing(self) -> ValidationItem:
        """Check weekday staffing requirements."""
        violations = []

        for day_info in self.calendar:
            if day_info.day_type != DayType.WEEKDAY:
                continue

            day = day_info.day
            assignments = self._get_day_assignments(day)

            # Count full-time staff working
            ft_working = [
                a for a in assignments
                if a.shift_type != ShiftType.OFF
                and self.staff_map.get(a.staff_id, None)
                and self.staff_map[a.staff_id].is_full_time()
            ]
            ft_count = len(ft_working)

            if ft_count < 7:
                violations.append(f"9/{day}({day_info.weekday}): 正社員{ft_count}名（{7-ft_count}名不足）")

            # Check 7:30 count (should be 1)
            early_count = sum(1 for a in ft_working if a.shift_type == ShiftType.EARLY)
            if early_count != 1:
                violations.append(f"9/{day}({day_info.weekday}): 7:30出勤{early_count}名（1名必要）")

            # Check 8:00 count (should be 2)
            normal_count = sum(1 for a in ft_working if a.shift_type == ShiftType.NORMAL)
            if normal_count != 2:
                violations.append(f"9/{day}({day_info.weekday}): 8:00出勤{normal_count}名（2名必要）")

        return ValidationItem(
            name="平日人員",
            passed=len(violations) == 0,
            details=violations if violations else ["全平日で正社員7名以上、7:30×1名、8:00×2名"]
        )

    def _check_weekend_holiday_staffing(self) -> ValidationItem:
        """Check weekend/holiday staffing requirements."""
        violations = []

        for day_info in self.calendar:
            if day_info.day_type == DayType.WEEKDAY:
                continue

            day = day_info.day
            assignments = self._get_day_assignments(day)

            # Count full-time staff working
            ft_working = [
                a for a in assignments
                if a.shift_type != ShiftType.OFF
                and self.staff_map.get(a.staff_id, None)
                and self.staff_map[a.staff_id].is_full_time()
            ]
            ft_count = len(ft_working)

            if ft_count != 3:
                diff = ft_count - 3
                if diff > 0:
                    violations.append(f"9/{day}({day_info.weekday}): {ft_count}名出勤（{diff}名超過）")
                else:
                    violations.append(f"9/{day}({day_info.weekday}): {ft_count}名出勤（{-diff}名不足）")

            # Check no 7:30 shift (forbidden on weekends/holidays)
            early_count = sum(1 for a in ft_working if a.shift_type == ShiftType.EARLY)
            if early_count > 0:
                violations.append(f"9/{day}({day_info.weekday}): 7:30出勤{early_count}名（禁止）")

            # Check 8:00 count (should be 1)
            normal_count = sum(1 for a in ft_working if a.shift_type == ShiftType.NORMAL)
            if normal_count != 1:
                violations.append(f"9/{day}({day_info.weekday}): 8:00出勤{normal_count}名（1名必要）")

            # Check 9:00 count (should be 2)
            late_count = sum(1 for a in ft_working if a.shift_type == ShiftType.LATE)
            if late_count != 2:
                violations.append(f"9/{day}({day_info.weekday}): 9:00出勤{late_count}名（2名必要）")

        return ValidationItem(
            name="土日祝人員",
            passed=len(violations) == 0,
            details=violations if violations else ["全土日祝で3名出勤、7:30禁止、8:00×1名、9:00×2名"]
        )

    def _check_standby_rules(self) -> ValidationItem:
        """Check all standby-related rules."""
        sub_items = []

        # 1. Check every day has exactly one standby
        daily_violations = []
        for day in range(1, 31):
            standby_id = self.schedule.standby_assignments.get(day)
            if not standby_id:
                daily_violations.append(f"9/{day}: 待機担当なし")

        sub_items.append(ValidationItem(
            name="毎日1名",
            passed=len(daily_violations) == 0,
            details=daily_violations if daily_violations else ["全日に待機担当あり"]
        ))

        # 2. Check standby person is on 9:00 shift
        shift_violations = []
        for day, standby_id in self.schedule.standby_assignments.items():
            assignments = self._get_day_assignments(day)
            standby_assignment = next(
                (a for a in assignments if a.staff_id == standby_id),
                None
            )
            if standby_assignment and standby_assignment.shift_type != ShiftType.LATE:
                staff = self.staff_map.get(standby_id)
                name = staff.name if staff else standby_id
                violations.append(f"9/{day}: {name}が{standby_assignment.shift_type.value}出勤（9:00必要）")

        sub_items.append(ValidationItem(
            name="待機者9:00出勤",
            passed=len(shift_violations) == 0,
            details=shift_violations if shift_violations else ["全待機者が9:00出勤"]
        ))

        # 3. Check next day is 8:00 shift
        next_day_violations = []
        for day, standby_id in self.schedule.standby_assignments.items():
            next_day = day + 1
            if next_day > 30:
                continue

            assignments = self._get_day_assignments(next_day)
            next_assignment = next(
                (a for a in assignments if a.staff_id == standby_id),
                None
            )

            if next_assignment and next_assignment.shift_type != ShiftType.NORMAL:
                staff = self.staff_map.get(standby_id)
                name = staff.name if staff else standby_id
                next_day_violations.append(
                    f"{name}: 9/{day}待機→9/{next_day}が{next_assignment.shift_type.value}（8:00必要）"
                )

        sub_items.append(ValidationItem(
            name="翌日8:00",
            passed=len(next_day_violations) == 0,
            details=next_day_violations if next_day_violations else ["全待機翌日が8:00出勤"]
        ))

        # 4. Check standby interval (6 days minimum)
        interval_violations = []
        for staff in self.full_time_staff:
            standby_days = sorted([
                day for day, sid in self.schedule.standby_assignments.items()
                if sid == staff.id
            ])

            for i in range(1, len(standby_days)):
                interval = standby_days[i] - standby_days[i-1]
                if interval < 6:
                    interval_violations.append(
                        f"{staff.name}: 9/{standby_days[i-1]}→9/{standby_days[i]} = {interval}日間隔"
                    )

        sub_items.append(ValidationItem(
            name="間隔6日以上",
            passed=len(interval_violations) == 0,
            details=interval_violations if interval_violations else ["全待機間隔が6日以上"]
        ))

        # 5. Check standby count distribution (4回×3名, 3回×6名)
        count_violations = []
        standby_counts = {}
        for staff in self.full_time_staff:
            count = sum(1 for sid in self.schedule.standby_assignments.values() if sid == staff.id)
            standby_counts[staff.id] = count

        four_count = sum(1 for c in standby_counts.values() if c == 4)
        three_count = sum(1 for c in standby_counts.values() if c == 3)

        if four_count != 3:
            count_violations.append(f"4回待機: {four_count}名（3名必要）")
        if three_count != 6:
            count_violations.append(f"3回待機: {three_count}名（6名必要）")

        # Check for unexpected counts
        for staff_id, count in standby_counts.items():
            if count not in (3, 4):
                staff = self.staff_map.get(staff_id)
                name = staff.name if staff else staff_id
                count_violations.append(f"{name}: {count}回（3回か4回必要）")

        sub_items.append(ValidationItem(
            name="回数配分",
            passed=len(count_violations) == 0,
            details=count_violations if count_violations else ["4回×3名、3回×6名"]
        ))

        # Overall standby result
        all_passed = all(item.passed for item in sub_items)
        return ValidationItem(
            name="待機ルール",
            passed=all_passed,
            sub_items=sub_items
        )

    def _check_requested_off(self) -> ValidationItem:
        """Check all requested off days are honored."""
        violations = []

        for staff in self.full_time_staff:
            pref = self.preferences.get(staff.id)
            if not pref or not pref.requested_off:
                continue

            assignments = self._get_staff_assignments(staff.id)
            assignment_map = {a.day: a for a in assignments}

            for day in pref.requested_off:
                assignment = assignment_map.get(day)
                if assignment and assignment.shift_type != ShiftType.OFF:
                    violations.append(f"{staff.name}: 9/{day} 希望休が勤務になっている")

        return ValidationItem(
            name="希望休",
            passed=len(violations) == 0,
            details=violations if violations else ["全希望休が反映済み"]
        )

    def _check_requested_work(self) -> ValidationItem:
        """Check all requested work days are honored."""
        violations = []

        for staff in self.full_time_staff:
            pref = self.preferences.get(staff.id)
            if not pref or not pref.requested_work:
                continue

            assignments = self._get_staff_assignments(staff.id)
            assignment_map = {a.day: a for a in assignments}

            for day in pref.requested_work:
                assignment = assignment_map.get(day)
                if assignment and assignment.shift_type == ShiftType.OFF:
                    violations.append(f"{staff.name}: 9/{day} 勤務希望が休みになっている")

        return ValidationItem(
            name="勤務希望",
            passed=len(violations) == 0,
            details=violations if violations else ["全勤務希望が反映済み"]
        )

    def _check_standby_unavailable(self) -> ValidationItem:
        """Check standby unavailable days are honored."""
        violations = []

        for staff in self.full_time_staff:
            pref = self.preferences.get(staff.id)
            if not pref or not pref.standby_unavailable:
                continue

            for day in pref.standby_unavailable:
                standby_id = self.schedule.standby_assignments.get(day)
                if standby_id == staff.id:
                    violations.append(f"{staff.name}: 9/{day} 待機不可日に待機")

        return ValidationItem(
            name="待機不可日",
            passed=len(violations) == 0,
            details=violations if violations else ["全待機不可日が反映済み"]
        )

    def _check_consecutive_work(self) -> ValidationItem:
        """Check consecutive work days (max 5)."""
        violations = []

        for staff in self.full_time_staff:
            assignments = self._get_staff_assignments(staff.id)
            assignment_map = {a.day: a for a in assignments}

            consecutive = 0
            start_day = None

            for day in range(1, 31):
                assignment = assignment_map.get(day)
                is_working = assignment and assignment.shift_type != ShiftType.OFF

                if is_working:
                    if consecutive == 0:
                        start_day = day
                    consecutive += 1
                else:
                    if consecutive > 5:
                        violations.append(
                            f"{staff.name}: 9/{start_day}-9/{day-1} 連勤{consecutive}日"
                        )
                    consecutive = 0
                    start_day = None

            # Check end of month
            if consecutive > 5:
                violations.append(
                    f"{staff.name}: 9/{start_day}-9/30 連勤{consecutive}日"
                )

        return ValidationItem(
            name="連続勤務",
            passed=len(violations) == 0,
            details=violations if violations else ["全員の連勤が5日以内"]
        )

    def _check_carryover(self) -> ValidationItem:
        """Check previous month carryover rules."""
        violations = []

        for carry in self.carryover:
            if not carry.had_standby_on_last_day:
                continue

            staff = self.staff_map.get(carry.staff_id)
            if not staff:
                continue

            # Check day 1 is 8:00 shift
            assignments = self._get_day_assignments(1)
            day1_assignment = next(
                (a for a in assignments if a.staff_id == carry.staff_id),
                None
            )

            if day1_assignment:
                if day1_assignment.shift_type != ShiftType.NORMAL:
                    violations.append(
                        f"{staff.name}: 9/1が{day1_assignment.shift_type.value}出勤（8:00必要）"
                    )

            # Check day 1 is not standby
            day1_standby = self.schedule.standby_assignments.get(1)
            if day1_standby == carry.staff_id:
                violations.append(f"{staff.name}: 9/1に待機担当（前月末待機のため不可）")

        return ValidationItem(
            name="前月引継ぎ",
            passed=len(violations) == 0,
            details=violations if violations else ["前月末待機者が9/1に8:00出勤、待機なし"]
        )


def validate_schedule(
    schedule: MonthlySchedule,
    staff_list: list[Staff],
    calendar: list[DayInfo],
    preferences: dict[str, StaffPreferences],
    carryover: list[PreviousMonthCarryover]
) -> ValidationResult:
    """Convenience function to validate a schedule."""
    validator = ShiftValidator(schedule, staff_list, calendar, preferences, carryover)
    return validator.validate_all()
