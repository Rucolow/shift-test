"""Data models for the hospital shift management system."""
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class StaffType(Enum):
    """Staff employment type."""
    FULL_TIME = "正社員"
    PART_TIME = "パート"


class ShiftType(Enum):
    """Shift time classification."""
    EARLY = "7:30"      # 早番
    NORMAL = "8:00"     # 通常
    LATE = "9:00"       # 遅番
    OFF = "休"          # 休日

    def __str__(self) -> str:
        return self.value


class DayType(Enum):
    """Day classification."""
    WEEKDAY = "平日"
    SATURDAY = "土曜"
    SUNDAY = "日曜"
    HOLIDAY = "祝日"

    def is_weekend_or_holiday(self) -> bool:
        """Check if this is a weekend or holiday."""
        return self in (DayType.SATURDAY, DayType.SUNDAY, DayType.HOLIDAY)


@dataclass
class Staff:
    """Staff member information."""
    id: str
    name: str
    staff_type: StaffType
    work_hours: str = "8h"  # For part-time: "9:00-17:00" etc.
    can_standby: bool = True  # Part-time cannot do standby

    def __post_init__(self):
        # Part-time staff cannot do standby
        if self.staff_type == StaffType.PART_TIME:
            self.can_standby = False

    def is_full_time(self) -> bool:
        return self.staff_type == StaffType.FULL_TIME

    def is_part_time(self) -> bool:
        return self.staff_type == StaffType.PART_TIME


@dataclass
class DayInfo:
    """Information about a specific day."""
    day: int  # Day of month (1-30)
    weekday: str  # Japanese weekday name
    day_type: DayType
    note: str = ""  # Holiday name etc.

    def is_weekend_or_holiday(self) -> bool:
        return self.day_type.is_weekend_or_holiday()


@dataclass
class StaffPreferences:
    """Staff preferences and constraints for the month."""
    staff_id: str
    requested_off: list[int] = field(default_factory=list)  # Days off requested
    requested_work: list[int] = field(default_factory=list)  # Days must work
    standby_unavailable: list[int] = field(default_factory=list)  # Days cannot do standby


@dataclass
class PreviousMonthCarryover:
    """Information carried over from the previous month."""
    staff_id: str
    had_standby_on_last_day: bool = False  # If true, must work 8:00 on day 1


@dataclass
class ShiftAssignment:
    """A single shift assignment."""
    staff_id: str
    day: int
    shift_type: ShiftType
    is_standby: bool = False  # True if this person is the standby for this day


@dataclass
class StaffStatistics:
    """Statistics for a single staff member."""
    staff_id: str
    staff_name: str
    work_days: int = 0
    off_days: int = 0
    total_hours: float = 0.0
    early_shifts: int = 0  # 7:30
    normal_shifts: int = 0  # 8:00
    late_shifts: int = 0  # 9:00
    standby_count: int = 0
    min_standby_interval: Optional[int] = None
    weekend_holiday_count: int = 0
    requested_off_fulfilled: int = 0
    requested_off_total: int = 0


@dataclass
class ShortageInfo:
    """Information about staffing shortage on a day."""
    date: str
    day: int
    required: int
    assigned: int
    shortage: int


@dataclass
class MonthlySchedule:
    """Complete monthly schedule."""
    year: int
    month: int
    assignments: list[ShiftAssignment] = field(default_factory=list)
    standby_assignments: dict[int, str] = field(default_factory=dict)  # day -> staff_id
    statistics: list[StaffStatistics] = field(default_factory=list)
    shortages: list[ShortageInfo] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    constraint_violations: list[str] = field(default_factory=list)


class FeasibilityError(Exception):
    """Raised when constraints are mathematically incompatible."""

    def __init__(self, conflicts: list[str]):
        self.conflicts = conflicts
        message = "制約条件が両立しません:\n" + "\n".join(f"  - {c}" for c in conflicts)
        super().__init__(message)


class NoSolutionError(Exception):
    """Raised when the constraint solver cannot find a solution."""

    def __init__(self, phase: str, reason: str):
        self.phase = phase
        self.reason = reason
        message = f"Phase '{phase}'で解が見つかりません: {reason}"
        super().__init__(message)
