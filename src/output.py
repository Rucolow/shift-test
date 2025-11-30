"""Output generation for the hospital shift management system."""
import csv
import json
from pathlib import Path
from typing import Optional

from .models import MonthlySchedule, ShiftType, DayInfo, Staff, StaffStatistics


class OutputGenerator:
    """Generate various output formats for the shift schedule."""

    def __init__(
        self,
        schedule: MonthlySchedule,
        staff_list: list[Staff],
        calendar: list[DayInfo]
    ):
        self.schedule = schedule
        self.staff_list = staff_list
        self.staff_by_id = {s.id: s for s in staff_list}
        self.calendar = calendar
        self.day_info = {d.day: d for d in calendar}

    def to_csv(self, filepath: str) -> None:
        """Export schedule to CSV file."""
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)

        # Build header
        header = ["日付", "曜日", "種別"]
        for staff in self.staff_list:
            header.append(staff.name)
        header.append("待機担当")

        # Build rows
        rows = []
        for day in range(1, 31):
            day_info = self.day_info[day]
            row = [
                f"2025-09-{day:02d}",
                day_info.weekday,
                day_info.day_type.value
            ]

            # Get shift for each staff
            for staff in self.staff_list:
                assignment = self._get_assignment(staff.id, day)
                if assignment:
                    row.append(str(assignment.shift_type))
                else:
                    row.append("")

            # Standby
            standby_id = self.schedule.standby_assignments.get(day)
            if standby_id:
                standby_staff = self.staff_by_id.get(standby_id)
                row.append(standby_staff.name if standby_staff else standby_id)
            else:
                row.append("")

            rows.append(row)

        with open(path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(header)
            writer.writerows(rows)

    def to_json(self, filepath: str) -> None:
        """Export schedule to JSON file."""
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "year": self.schedule.year,
            "month": self.schedule.month,
            "schedule": [],
            "standby_assignments": {},
            "statistics": [],
            "shortages": [],
            "suggestions": self.schedule.suggestions,
            "constraint_violations": self.schedule.constraint_violations
        }

        # Build daily schedule
        for day in range(1, 31):
            day_info = self.day_info[day]
            day_data = {
                "date": f"2025-09-{day:02d}",
                "weekday": day_info.weekday,
                "day_type": day_info.day_type.value,
                "shifts": {}
            }

            for staff in self.staff_list:
                assignment = self._get_assignment(staff.id, day)
                if assignment:
                    day_data["shifts"][staff.name] = {
                        "shift": str(assignment.shift_type),
                        "is_standby": assignment.is_standby
                    }

            data["schedule"].append(day_data)

        # Standby assignments
        for day, staff_id in self.schedule.standby_assignments.items():
            staff = self.staff_by_id.get(staff_id)
            data["standby_assignments"][str(day)] = staff.name if staff else staff_id

        # Statistics
        for stats in self.schedule.statistics:
            data["statistics"].append({
                "staff_id": stats.staff_id,
                "staff_name": stats.staff_name,
                "work_days": stats.work_days,
                "off_days": stats.off_days,
                "total_hours": stats.total_hours,
                "shift_distribution": {
                    "7:30": stats.early_shifts,
                    "8:00": stats.normal_shifts,
                    "9:00": stats.late_shifts
                },
                "standby_count": stats.standby_count,
                "min_standby_interval": stats.min_standby_interval,
                "weekend_holiday_count": stats.weekend_holiday_count,
                "requested_off_fulfilled": f"{stats.requested_off_fulfilled}/{stats.requested_off_total}"
            })

        # Shortages
        for shortage in self.schedule.shortages:
            data["shortages"].append({
                "date": shortage.date,
                "required": shortage.required,
                "assigned": shortage.assigned,
                "shortage": shortage.shortage
            })

        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def to_weekly_text(self) -> str:
        """Generate weekly format text output."""
        lines = []
        lines.append("=" * 80)
        lines.append(f"  病院スタッフシフト表 - {self.schedule.year}年{self.schedule.month}月")
        lines.append("=" * 80)
        lines.append("")

        # Split into weeks
        weeks = [
            (1, 7, "第1週"),
            (8, 14, "第2週"),
            (15, 21, "第3週"),
            (22, 28, "第4週"),
            (29, 30, "第5週")
        ]

        full_time_staff = [s for s in self.staff_list if s.is_full_time()]
        part_time_staff = [s for s in self.staff_list if s.is_part_time()]

        for start_day, end_day, week_name in weeks:
            day_info_start = self.day_info[start_day]
            day_info_end = self.day_info[end_day]

            lines.append(f"【{week_name}: {self.schedule.month}/{start_day}({day_info_start.weekday}) 〜 "
                        f"{self.schedule.month}/{end_day}({day_info_end.weekday})】")
            lines.append("")

            # Header
            header = "日付  |"
            for staff in full_time_staff:
                header += f" {staff.name[:2]:^4} |"
            header += " パート | 待機"
            lines.append(header)
            lines.append("-" * len(header))

            # Rows
            for day in range(start_day, end_day + 1):
                day_info = self.day_info[day]
                row = f"{day:2d}({day_info.weekday})|"

                for staff in full_time_staff:
                    assignment = self._get_assignment(staff.id, day)
                    if assignment:
                        shift_str = str(assignment.shift_type)
                        if assignment.is_standby:
                            shift_str += "*"
                        row += f" {shift_str:^4} |"
                    else:
                        row += "      |"

                # Part-time count
                part_count = sum(
                    1 for s in part_time_staff
                    if self._get_assignment(s.id, day) and
                    self._get_assignment(s.id, day).shift_type != ShiftType.OFF
                )
                row += f"  {part_count}名  |"

                # Standby
                standby_id = self.schedule.standby_assignments.get(day)
                if standby_id:
                    standby_staff = self.staff_by_id.get(standby_id)
                    row += f" {standby_staff.name if standby_staff else standby_id}"
                else:
                    row += " -"

                lines.append(row)

            lines.append("")

        return "\n".join(lines)

    def to_statistics_text(self) -> str:
        """Generate statistics text output."""
        lines = []
        lines.append("=" * 60)
        lines.append("  スタッフ別集計")
        lines.append("=" * 60)
        lines.append("")

        for stats in self.schedule.statistics:
            lines.append(f"【{stats.staff_name}】")
            lines.append(f"  勤務日数: {stats.work_days}日")
            lines.append(f"  休日数: {stats.off_days}日")
            lines.append(f"  労働時間: {stats.total_hours:.0f}h")
            lines.append(f"  出勤区分:")
            lines.append(f"    7:30: {stats.early_shifts}回")
            lines.append(f"    8:00: {stats.normal_shifts}回")
            lines.append(f"    9:00: {stats.late_shifts}回")
            lines.append(f"  待機回数: {stats.standby_count}回")
            if stats.min_standby_interval is not None:
                lines.append(f"  最短待機間隔: {stats.min_standby_interval}日")
            lines.append(f"  土日祝出勤: {stats.weekend_holiday_count}回")
            lines.append(f"  希望休充足: {stats.requested_off_fulfilled}/{stats.requested_off_total}")
            lines.append("")

        # Overall summary
        lines.append("=" * 60)
        lines.append("  全体集計")
        lines.append("=" * 60)
        lines.append("")

        if self.schedule.shortages:
            lines.append(f"人員不足: {len(self.schedule.shortages)}件")
            for shortage in self.schedule.shortages:
                lines.append(f"  - {shortage.date}: 必要{shortage.required}名, 配置{shortage.assigned}名, 不足{shortage.shortage}名")
        else:
            lines.append("人員不足: なし")

        lines.append("")
        lines.append(f"制約違反: {len(self.schedule.constraint_violations)}件")
        for violation in self.schedule.constraint_violations:
            lines.append(f"  - {violation}")

        return "\n".join(lines)

    def to_suggestions_text(self) -> str:
        """Generate suggestions text output."""
        lines = []
        lines.append("=" * 60)
        lines.append("  改善提案")
        lines.append("=" * 60)
        lines.append("")

        if self.schedule.suggestions:
            for i, suggestion in enumerate(self.schedule.suggestions, 1):
                lines.append(f"{i}. {suggestion}")
                lines.append("")
        else:
            lines.append("改善提案はありません。")

        return "\n".join(lines)

    def _get_assignment(self, staff_id: str, day: int):
        """Get assignment for a specific staff and day."""
        for assignment in self.schedule.assignments:
            if assignment.staff_id == staff_id and assignment.day == day:
                return assignment
        return None


def generate_all_outputs(
    schedule: MonthlySchedule,
    staff_list: list[Staff],
    calendar: list[DayInfo],
    output_dir: str = "output"
) -> dict[str, str]:
    """
    Generate all output files.

    Returns dict of output type to filepath.
    """
    generator = OutputGenerator(schedule, staff_list, calendar)

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    outputs = {}

    # CSV
    csv_path = output_path / "shift_schedule.csv"
    generator.to_csv(str(csv_path))
    outputs["csv"] = str(csv_path)

    # JSON
    json_path = output_path / "shift_schedule.json"
    generator.to_json(str(json_path))
    outputs["json"] = str(json_path)

    # Text outputs
    weekly_text = generator.to_weekly_text()
    weekly_path = output_path / "shift_schedule.txt"
    with open(weekly_path, 'w', encoding='utf-8') as f:
        f.write(weekly_text)
    outputs["weekly"] = str(weekly_path)

    stats_text = generator.to_statistics_text()
    stats_path = output_path / "statistics.txt"
    with open(stats_path, 'w', encoding='utf-8') as f:
        f.write(stats_text)
    outputs["statistics"] = str(stats_path)

    suggestions_text = generator.to_suggestions_text()
    suggestions_path = output_path / "suggestions.txt"
    with open(suggestions_path, 'w', encoding='utf-8') as f:
        f.write(suggestions_text)
    outputs["suggestions"] = str(suggestions_path)

    return outputs
