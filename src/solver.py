"""Constraint solver for hospital shift scheduling using OR-Tools CP-SAT."""
from ortools.sat.python import cp_model
from typing import Optional

from .models import (
    Staff, DayInfo, ShiftType, StaffPreferences,
    PreviousMonthCarryover, ShiftAssignment, MonthlySchedule,
    StaffStatistics, ShortageInfo, FeasibilityError, NoSolutionError
)


class ShiftScheduler:
    """Hospital shift scheduler using constraint programming."""

    # Shift type encoding for the solver
    SHIFT_OFF = 0
    SHIFT_EARLY = 1  # 7:30
    SHIFT_NORMAL = 2  # 8:00
    SHIFT_LATE = 3  # 9:00

    def __init__(
        self,
        staff_list: list[Staff],
        calendar: list[DayInfo],
        preferences: dict[str, StaffPreferences],
        carryover: list[PreviousMonthCarryover],
        config: dict
    ):
        self.staff_list = staff_list
        self.full_time_staff = [s for s in staff_list if s.is_full_time()]
        self.part_time_staff = [s for s in staff_list if s.is_part_time()]
        self.calendar = calendar
        self.preferences = preferences
        self.carryover = carryover
        self.config = config

        # Create day lookup
        self.day_info: dict[int, DayInfo] = {d.day: d for d in calendar}
        self.num_days = len(calendar)

        # Staff lookup
        self.staff_by_id = {s.id: s for s in staff_list}

        # Carryover lookup
        self.carryover_by_id = {c.staff_id: c for c in carryover}

        # Model and variables
        self.model: Optional[cp_model.CpModel] = None
        self.shift_vars: dict[tuple[str, int], cp_model.IntVar] = {}
        self.standby_vars: dict[tuple[str, int], cp_model.IntVar] = {}
        self.work_vars: dict[tuple[str, int], cp_model.IntVar] = {}

    def validate_input(self) -> list[str]:
        """
        Phase 0: Input validation.

        Returns list of validation errors.
        """
        errors = []

        # Check calendar consistency
        if self.num_days != 30:
            errors.append(f"カレンダーの日数が不正です: {self.num_days}日（期待: 30日）")

        # Check staff count
        if len(self.full_time_staff) < 7:
            errors.append(f"正社員が不足しています: {len(self.full_time_staff)}名（最低7名必要）")

        # Check preference conflicts (requested off vs work on same day)
        for staff_id, pref in self.preferences.items():
            overlap = set(pref.requested_off) & set(pref.requested_work)
            if overlap:
                staff = self.staff_by_id.get(staff_id)
                name = staff.name if staff else staff_id
                errors.append(f"{name}の希望休と勤務希望が重複しています: {sorted(overlap)}")

        # Check requested days are valid
        for staff_id, pref in self.preferences.items():
            staff = self.staff_by_id.get(staff_id)
            name = staff.name if staff else staff_id
            for day in pref.requested_off + pref.requested_work:
                if day < 1 or day > self.num_days:
                    errors.append(f"{name}の希望日が範囲外です: {day}日")

        return errors

    def check_feasibility(self) -> list[str]:
        """
        Phase 1: Feasibility check.

        Returns list of constraint conflicts.
        """
        conflicts = []

        # Check if requested off days allow 20 work days for each full-time staff
        for staff in self.full_time_staff:
            pref = self.preferences.get(staff.id, StaffPreferences(staff_id=staff.id))
            off_days = len(pref.requested_off)
            max_work_days = self.num_days - off_days

            if max_work_days < self.config["full_time_work_days"]:
                conflicts.append(
                    f"{staff.name}の希望休({off_days}日)により勤務日数が"
                    f"{max_work_days}日となり、必要な{self.config['full_time_work_days']}日を達成できません"
                )

        # Check if standby distribution is achievable
        standby_staff_count = len([s for s in self.full_time_staff if s.can_standby])
        total_standby_needed = self.num_days
        high_count, low_count = 3, 6  # 4回 × 3名, 3回 × 6名

        if standby_staff_count < high_count + low_count:
            conflicts.append(
                f"待機可能な正社員が{standby_staff_count}名しかおらず、"
                f"必要な{high_count + low_count}名に不足しています"
            )

        # Check standby interval constraint
        # With 6-day minimum interval, each person can do at most ceil(30/7) = 5 times
        max_standby_per_person = (self.num_days + self.config["standby_min_interval"]) // (self.config["standby_min_interval"] + 1) + 1

        if max_standby_per_person < 4:
            conflicts.append(
                f"待機間隔{self.config['standby_min_interval']}日制約により、"
                f"1人あたり最大{max_standby_per_person}回しか待機できません"
            )

        # Check weekend/holiday staffing
        weekend_days = [d for d in self.calendar if d.is_weekend_or_holiday()]
        total_weekend_shifts = len(weekend_days) * self.config["weekend_total_count"]
        # Each full-time staff has 20 work days, need to cover weekends

        return conflicts

    def build_model(self):
        """Build the CP-SAT model with all constraints."""
        self.model = cp_model.CpModel()
        self._create_variables()
        self._add_hard_constraints()
        self._add_soft_constraints()

    def _create_variables(self):
        """Create decision variables."""
        # Shift variables: shift[staff_id, day] = shift type (0-3)
        for staff in self.staff_list:
            for day in range(1, self.num_days + 1):
                self.shift_vars[staff.id, day] = self.model.NewIntVar(
                    0, 3, f"shift_{staff.id}_{day}"
                )
                # Work variable: 1 if working, 0 if off
                self.work_vars[staff.id, day] = self.model.NewBoolVar(
                    f"work_{staff.id}_{day}"
                )
                # Link shift and work variables
                self.model.Add(self.shift_vars[staff.id, day] != self.SHIFT_OFF).OnlyEnforceIf(
                    self.work_vars[staff.id, day]
                )
                self.model.Add(self.shift_vars[staff.id, day] == self.SHIFT_OFF).OnlyEnforceIf(
                    self.work_vars[staff.id, day].Not()
                )

        # Standby variables: standby[staff_id, day] = 1 if standby
        for staff in self.full_time_staff:
            for day in range(1, self.num_days + 1):
                self.standby_vars[staff.id, day] = self.model.NewBoolVar(
                    f"standby_{staff.id}_{day}"
                )

    def _add_hard_constraints(self):
        """Add all hard constraints (HC-01 to HC-10)."""
        self._add_hc01_work_days()
        self._add_hc03_weekday_staffing()
        self._add_hc04_weekend_staffing()
        self._add_hc05_standby_logic()
        self._add_hc06_carryover()
        self._add_hc07_consecutive_limit()
        self._add_hc08_requested_off()
        self._add_hc09_requested_work()
        self._add_hc10_standby_unavailable()

    def _add_hc01_work_days(self):
        """HC-01: Full-time staff must work exactly 20 days."""
        for staff in self.full_time_staff:
            work_days = sum(
                self.work_vars[staff.id, day]
                for day in range(1, self.num_days + 1)
            )
            self.model.Add(work_days == self.config["full_time_work_days"])

    def _add_hc03_weekday_staffing(self):
        """HC-03: Weekday staffing requirements."""
        for day_info in self.calendar:
            if not day_info.is_weekend_or_holiday():
                day = day_info.day

                # 7:30出勤: 1名（正社員）
                early_count = sum(
                    self.model.NewBoolVar(f"early_{staff.id}_{day}")
                    for staff in self.full_time_staff
                )
                early_vars = []
                for staff in self.full_time_staff:
                    is_early = self.model.NewBoolVar(f"is_early_{staff.id}_{day}")
                    self.model.Add(self.shift_vars[staff.id, day] == self.SHIFT_EARLY).OnlyEnforceIf(is_early)
                    self.model.Add(self.shift_vars[staff.id, day] != self.SHIFT_EARLY).OnlyEnforceIf(is_early.Not())
                    early_vars.append(is_early)
                self.model.Add(sum(early_vars) == self.config["weekday_early_count"])

                # 8:00出勤: 2名（正社員）
                normal_vars = []
                for staff in self.full_time_staff:
                    is_normal = self.model.NewBoolVar(f"is_normal_{staff.id}_{day}")
                    self.model.Add(self.shift_vars[staff.id, day] == self.SHIFT_NORMAL).OnlyEnforceIf(is_normal)
                    self.model.Add(self.shift_vars[staff.id, day] != self.SHIFT_NORMAL).OnlyEnforceIf(is_normal.Not())
                    normal_vars.append(is_normal)
                self.model.Add(sum(normal_vars) == self.config["weekday_normal_count"])

                # 正社員出勤数 ≥ 7名
                full_time_working = sum(
                    self.work_vars[staff.id, day]
                    for staff in self.full_time_staff
                )
                self.model.Add(full_time_working >= self.config["weekday_min_full_time"])

                # パート: 9:00出勤のみ（出勤する場合）
                for staff in self.part_time_staff:
                    # If part-time works, they must be 9:00
                    is_working = self.work_vars[staff.id, day]
                    self.model.Add(
                        self.shift_vars[staff.id, day] == self.SHIFT_LATE
                    ).OnlyEnforceIf(is_working)

    def _add_hc04_weekend_staffing(self):
        """HC-04: Weekend/holiday staffing requirements."""
        for day_info in self.calendar:
            if day_info.is_weekend_or_holiday():
                day = day_info.day

                # 出勤者 = 3名（正社員のみ）
                full_time_working = sum(
                    self.work_vars[staff.id, day]
                    for staff in self.full_time_staff
                )
                self.model.Add(full_time_working == self.config["weekend_total_count"])

                # パート: 出勤不可
                for staff in self.part_time_staff:
                    self.model.Add(self.shift_vars[staff.id, day] == self.SHIFT_OFF)

                # 7:30出勤: 禁止
                for staff in self.full_time_staff:
                    is_early = self.model.NewBoolVar(f"weekend_early_{staff.id}_{day}")
                    self.model.Add(self.shift_vars[staff.id, day] == self.SHIFT_EARLY).OnlyEnforceIf(is_early)
                    self.model.Add(self.shift_vars[staff.id, day] != self.SHIFT_EARLY).OnlyEnforceIf(is_early.Not())
                    self.model.Add(is_early == 0)

                # 8:00出勤: 1名
                normal_vars = []
                for staff in self.full_time_staff:
                    is_normal = self.model.NewBoolVar(f"weekend_normal_{staff.id}_{day}")
                    self.model.Add(self.shift_vars[staff.id, day] == self.SHIFT_NORMAL).OnlyEnforceIf(is_normal)
                    self.model.Add(self.shift_vars[staff.id, day] != self.SHIFT_NORMAL).OnlyEnforceIf(is_normal.Not())
                    normal_vars.append(is_normal)
                self.model.Add(sum(normal_vars) == self.config["weekend_normal_count"])

    def _add_hc05_standby_logic(self):
        """HC-05: Standby assignment logic."""
        # 毎日1名が待機担当
        for day in range(1, self.num_days + 1):
            self.model.Add(
                sum(self.standby_vars[staff.id, day] for staff in self.full_time_staff) == 1
            )

        for staff in self.full_time_staff:
            # 待機担当は9:00出勤
            for day in range(1, self.num_days + 1):
                self.model.Add(
                    self.shift_vars[staff.id, day] == self.SHIFT_LATE
                ).OnlyEnforceIf(self.standby_vars[staff.id, day])

            # 待機担当の翌日 → 必ず8:00出勤
            for day in range(1, self.num_days):
                self.model.Add(
                    self.shift_vars[staff.id, day + 1] == self.SHIFT_NORMAL
                ).OnlyEnforceIf(self.standby_vars[staff.id, day])

            # 待機間隔 ≥ 6日
            interval = self.config["standby_min_interval"]
            for day in range(1, self.num_days + 1):
                # If standby on day, cannot be standby on day+1 to day+interval
                for next_day in range(day + 1, min(day + interval + 1, self.num_days + 1)):
                    # standby[day] + standby[next_day] <= 1
                    self.model.Add(
                        self.standby_vars[staff.id, day] + self.standby_vars[staff.id, next_day] <= 1
                    )

            # パートは待機不可 (already enforced by not having standby vars)

        # 待機回数: 4回 × 3名, 3回 × 6名
        standby_counts = []
        for staff in self.full_time_staff:
            count = self.model.NewIntVar(0, self.num_days, f"standby_count_{staff.id}")
            self.model.Add(count == sum(
                self.standby_vars[staff.id, day]
                for day in range(1, self.num_days + 1)
            ))
            standby_counts.append((staff.id, count))

        # Create variables for who gets 4 times vs 3 times
        is_high = {}
        for staff in self.full_time_staff:
            is_high[staff.id] = self.model.NewBoolVar(f"standby_high_{staff.id}")

        # If high, count must be 4; if low, count must be 3
        for staff_id, count in standby_counts:
            self.model.Add(count == 4).OnlyEnforceIf(is_high[staff_id])
            self.model.Add(count == 3).OnlyEnforceIf(is_high[staff_id].Not())

        # Exactly 3 staff get 4 times
        self.model.Add(sum(is_high.values()) == 3)

    def _add_hc06_carryover(self):
        """HC-06: Previous month carryover constraints."""
        for carry in self.carryover:
            staff = self.staff_by_id.get(carry.staff_id)
            if staff and carry.had_standby_on_last_day:
                # Must work 8:00 on day 1
                self.model.Add(self.shift_vars[carry.staff_id, 1] == self.SHIFT_NORMAL)
                # Cannot be standby on day 1
                if (carry.staff_id, 1) in self.standby_vars:
                    self.model.Add(self.standby_vars[carry.staff_id, 1] == 0)

    def _add_hc07_consecutive_limit(self):
        """HC-07: Maximum 5 consecutive work days."""
        max_consec = self.config["max_consecutive_days"]

        for staff in self.full_time_staff:
            # For each window of (max_consec + 1) days, at least one must be off
            for start_day in range(1, self.num_days - max_consec + 1):
                window_vars = [
                    self.work_vars[staff.id, day]
                    for day in range(start_day, start_day + max_consec + 1)
                ]
                # Sum of work days in window <= max_consec
                self.model.Add(sum(window_vars) <= max_consec)

    def _add_hc08_requested_off(self):
        """HC-08: Requested off days must be respected."""
        for staff_id, pref in self.preferences.items():
            for day in pref.requested_off:
                if 1 <= day <= self.num_days:
                    self.model.Add(self.shift_vars[staff_id, day] == self.SHIFT_OFF)

    def _add_hc09_requested_work(self):
        """HC-09: Requested work days must be respected."""
        for staff_id, pref in self.preferences.items():
            for day in pref.requested_work:
                if 1 <= day <= self.num_days:
                    self.model.Add(self.shift_vars[staff_id, day] != self.SHIFT_OFF)

    def _add_hc10_standby_unavailable(self):
        """HC-10: Days when staff cannot do standby."""
        for staff_id, pref in self.preferences.items():
            for day in pref.standby_unavailable:
                if 1 <= day <= self.num_days and (staff_id, day) in self.standby_vars:
                    self.model.Add(self.standby_vars[staff_id, day] == 0)

    def _add_soft_constraints(self):
        """Add soft constraints for fairness optimization."""
        # SC-01: 出勤区分の公平性 (7:30/8:00/9:00 均等化)
        # SC-02: 土日祝出勤の公平性
        # SC-03: 待機回数の公平性 (already handled in HC-05)

        # Calculate shift type counts for each staff
        early_counts = []
        normal_counts = []
        weekend_counts = []

        for staff in self.full_time_staff:
            # Count 7:30 shifts
            early_count = self.model.NewIntVar(0, self.num_days, f"early_count_{staff.id}")
            early_indicators = []
            for day in range(1, self.num_days + 1):
                is_early = self.model.NewBoolVar(f"sc_early_{staff.id}_{day}")
                self.model.Add(self.shift_vars[staff.id, day] == self.SHIFT_EARLY).OnlyEnforceIf(is_early)
                self.model.Add(self.shift_vars[staff.id, day] != self.SHIFT_EARLY).OnlyEnforceIf(is_early.Not())
                early_indicators.append(is_early)
            self.model.Add(early_count == sum(early_indicators))
            early_counts.append(early_count)

            # Count 8:00 shifts
            normal_count = self.model.NewIntVar(0, self.num_days, f"normal_count_{staff.id}")
            normal_indicators = []
            for day in range(1, self.num_days + 1):
                is_normal = self.model.NewBoolVar(f"sc_normal_{staff.id}_{day}")
                self.model.Add(self.shift_vars[staff.id, day] == self.SHIFT_NORMAL).OnlyEnforceIf(is_normal)
                self.model.Add(self.shift_vars[staff.id, day] != self.SHIFT_NORMAL).OnlyEnforceIf(is_normal.Not())
                normal_indicators.append(is_normal)
            self.model.Add(normal_count == sum(normal_indicators))
            normal_counts.append(normal_count)

            # Count weekend/holiday work days
            weekend_count = self.model.NewIntVar(0, self.num_days, f"weekend_count_{staff.id}")
            weekend_indicators = []
            for day_info in self.calendar:
                if day_info.is_weekend_or_holiday():
                    weekend_indicators.append(self.work_vars[staff.id, day_info.day])
            self.model.Add(weekend_count == sum(weekend_indicators))
            weekend_counts.append(weekend_count)

        # Minimize the max difference in each category
        # For early shifts
        early_max = self.model.NewIntVar(0, self.num_days, "early_max")
        early_min = self.model.NewIntVar(0, self.num_days, "early_min")
        self.model.AddMaxEquality(early_max, early_counts)
        self.model.AddMinEquality(early_min, early_counts)

        # For normal shifts
        normal_max = self.model.NewIntVar(0, self.num_days, "normal_max")
        normal_min = self.model.NewIntVar(0, self.num_days, "normal_min")
        self.model.AddMaxEquality(normal_max, normal_counts)
        self.model.AddMinEquality(normal_min, normal_counts)

        # For weekend shifts
        weekend_max = self.model.NewIntVar(0, self.num_days, "weekend_max")
        weekend_min = self.model.NewIntVar(0, self.num_days, "weekend_min")
        self.model.AddMaxEquality(weekend_max, weekend_counts)
        self.model.AddMinEquality(weekend_min, weekend_counts)

        # Objective: minimize the sum of differences
        early_diff = self.model.NewIntVar(0, self.num_days, "early_diff")
        normal_diff = self.model.NewIntVar(0, self.num_days, "normal_diff")
        weekend_diff = self.model.NewIntVar(0, self.num_days, "weekend_diff")

        self.model.Add(early_diff == early_max - early_min)
        self.model.Add(normal_diff == normal_max - normal_min)
        self.model.Add(weekend_diff == weekend_max - weekend_min)

        # Weighted objective
        self.model.Minimize(early_diff + normal_diff + 2 * weekend_diff)

    def solve(self, time_limit_seconds: int = 60) -> Optional[MonthlySchedule]:
        """
        Solve the shift scheduling problem.

        Args:
            time_limit_seconds: Maximum time for solver

        Returns:
            MonthlySchedule if solution found, None otherwise
        """
        if self.model is None:
            self.build_model()

        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = time_limit_seconds

        status = solver.Solve(self.model)

        if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
            return self._extract_solution(solver)
        else:
            return None

    def _extract_solution(self, solver: cp_model.CpSolver) -> MonthlySchedule:
        """Extract the solution from the solver."""
        schedule = MonthlySchedule(year=2025, month=9)

        # Extract shift assignments
        for staff in self.staff_list:
            for day in range(1, self.num_days + 1):
                shift_value = solver.Value(self.shift_vars[staff.id, day])
                shift_type = self._value_to_shift_type(shift_value)

                is_standby = False
                if staff.is_full_time() and (staff.id, day) in self.standby_vars:
                    is_standby = solver.Value(self.standby_vars[staff.id, day]) == 1

                schedule.assignments.append(ShiftAssignment(
                    staff_id=staff.id,
                    day=day,
                    shift_type=shift_type,
                    is_standby=is_standby
                ))

                if is_standby:
                    schedule.standby_assignments[day] = staff.id

        # Calculate statistics
        schedule.statistics = self._calculate_statistics(schedule)

        # Generate suggestions
        schedule.suggestions = self._generate_suggestions(schedule)

        return schedule

    def _value_to_shift_type(self, value: int) -> ShiftType:
        """Convert solver value to ShiftType."""
        if value == self.SHIFT_OFF:
            return ShiftType.OFF
        elif value == self.SHIFT_EARLY:
            return ShiftType.EARLY
        elif value == self.SHIFT_NORMAL:
            return ShiftType.NORMAL
        else:
            return ShiftType.LATE

    def _calculate_statistics(self, schedule: MonthlySchedule) -> list[StaffStatistics]:
        """Calculate statistics for each staff member."""
        stats_list = []

        for staff in self.staff_list:
            stats = StaffStatistics(
                staff_id=staff.id,
                staff_name=staff.name
            )

            # Get preferences
            pref = self.preferences.get(staff.id, StaffPreferences(staff_id=staff.id))
            stats.requested_off_total = len(pref.requested_off)

            # Get assignments for this staff
            staff_assignments = [a for a in schedule.assignments if a.staff_id == staff.id]

            standby_days = []

            for assignment in staff_assignments:
                if assignment.shift_type == ShiftType.OFF:
                    stats.off_days += 1
                    if assignment.day in pref.requested_off:
                        stats.requested_off_fulfilled += 1
                else:
                    stats.work_days += 1
                    stats.total_hours += 8

                    if assignment.shift_type == ShiftType.EARLY:
                        stats.early_shifts += 1
                    elif assignment.shift_type == ShiftType.NORMAL:
                        stats.normal_shifts += 1
                    else:
                        stats.late_shifts += 1

                    if assignment.is_standby:
                        stats.standby_count += 1
                        standby_days.append(assignment.day)

                    # Check if weekend/holiday
                    day_info = self.day_info.get(assignment.day)
                    if day_info and day_info.is_weekend_or_holiday():
                        stats.weekend_holiday_count += 1

            # Calculate minimum standby interval
            if len(standby_days) >= 2:
                standby_days.sort()
                min_interval = min(
                    standby_days[i + 1] - standby_days[i]
                    for i in range(len(standby_days) - 1)
                )
                stats.min_standby_interval = min_interval

            stats_list.append(stats)

        return stats_list

    def _generate_suggestions(self, schedule: MonthlySchedule) -> list[str]:
        """Generate improvement suggestions based on the schedule."""
        suggestions = []

        # Check for staff with many requested off days
        for staff in self.full_time_staff:
            pref = self.preferences.get(staff.id, StaffPreferences(staff_id=staff.id))
            if len(pref.requested_off) >= 4:
                suggestions.append(
                    f"{staff.name}の希望休が{len(pref.requested_off)}日と多く、"
                    "他スタッフに負担が集中する可能性があります。"
                    "来月は希望休の上限設定を検討してください。"
                )

        # Check standby distribution
        standby_counts = {}
        for day, staff_id in schedule.standby_assignments.items():
            standby_counts[staff_id] = standby_counts.get(staff_id, 0) + 1

        high_standby = [sid for sid, count in standby_counts.items() if count == 4]
        if len(high_standby) == 3:
            names = [self.staff_by_id[sid].name for sid in high_standby]
            suggestions.append(
                f"待機4回担当: {', '.join(names)}。"
                "来月は異なるスタッフに4回担当を割り当てることで公平性を高められます。"
            )

        return suggestions
