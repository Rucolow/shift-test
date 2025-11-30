"""Master data for the hospital shift management system."""
from .models import (
    Staff, StaffType, DayInfo, DayType,
    StaffPreferences, PreviousMonthCarryover
)


def get_staff_list() -> list[Staff]:
    """Get the list of all staff members."""
    return [
        # Full-time staff (正社員)
        Staff(id="S01", name="阿部", staff_type=StaffType.FULL_TIME),
        Staff(id="S02", name="安藤", staff_type=StaffType.FULL_TIME),
        Staff(id="S03", name="山田", staff_type=StaffType.FULL_TIME),
        Staff(id="S04", name="佐々木", staff_type=StaffType.FULL_TIME),
        Staff(id="S05", name="松竹谷", staff_type=StaffType.FULL_TIME),
        Staff(id="S06", name="松尾", staff_type=StaffType.FULL_TIME),
        Staff(id="S07", name="矢羽田", staff_type=StaffType.FULL_TIME),
        Staff(id="S08", name="林田", staff_type=StaffType.FULL_TIME),
        Staff(id="S09", name="長川", staff_type=StaffType.FULL_TIME),
        # Part-time staff (パート)
        Staff(id="P01", name="野中", staff_type=StaffType.PART_TIME, work_hours="9:00-17:00"),
        Staff(id="P02", name="若松", staff_type=StaffType.PART_TIME, work_hours="9:00-17:00"),
        Staff(id="P03", name="多賀", staff_type=StaffType.PART_TIME, work_hours="9:00-16:00"),
    ]


def get_full_time_staff() -> list[Staff]:
    """Get only full-time staff members."""
    return [s for s in get_staff_list() if s.is_full_time()]


def get_part_time_staff() -> list[Staff]:
    """Get only part-time staff members."""
    return [s for s in get_staff_list() if s.is_part_time()]


def get_september_2025_calendar() -> list[DayInfo]:
    """Get the calendar for September 2025."""
    # Weekday names in Japanese
    weekdays = ["月", "火", "水", "木", "金", "土", "日"]

    calendar = []

    # September 2025 starts on Monday
    # Day 1 = Monday (index 0)
    for day in range(1, 31):
        weekday_index = (day - 1) % 7  # 0 = Monday, 6 = Sunday
        weekday = weekdays[weekday_index]

        # Determine day type
        if day == 15:
            day_type = DayType.HOLIDAY
            note = "敬老の日"
        elif day == 22:
            day_type = DayType.HOLIDAY
            note = "秋分の日振替"
        elif day == 23:
            day_type = DayType.HOLIDAY
            note = "秋分の日"
        elif weekday_index == 5:  # Saturday
            day_type = DayType.SATURDAY
            note = ""
        elif weekday_index == 6:  # Sunday
            day_type = DayType.SUNDAY
            note = ""
        else:
            day_type = DayType.WEEKDAY
            note = ""

        calendar.append(DayInfo(day=day, weekday=weekday, day_type=day_type, note=note))

    return calendar


def get_staff_preferences() -> list[StaffPreferences]:
    """Get staff preferences for September 2025."""
    return [
        # HC-08: 希望休（必ず尊重）
        StaffPreferences(staff_id="S01", requested_off=[23, 25]),  # 阿部
        StaffPreferences(staff_id="S03", requested_off=[13, 25]),  # 山田
        StaffPreferences(staff_id="S04", requested_off=[2, 15, 30]),  # 佐々木
        StaffPreferences(staff_id="S05", requested_off=[8]),  # 松竹谷
        StaffPreferences(staff_id="S06", requested_off=[5, 16, 27, 28]),  # 松尾
        StaffPreferences(staff_id="S07", requested_off=[18, 19, 20]),  # 矢羽田
        StaffPreferences(staff_id="S08", requested_off=[9, 10]),  # 林田

        # HC-09: 勤務希望（必ず尊重）
        StaffPreferences(staff_id="S02", requested_work=[1, 2, 3, 4]),  # 安藤
        StaffPreferences(staff_id="S07", requested_work=[12, 13, 14, 15]),  # 矢羽田

        # HC-10: 待機不可日
        StaffPreferences(staff_id="S05", standby_unavailable=[25]),  # 松竹谷
        StaffPreferences(staff_id="S09", standby_unavailable=[1, 15]),  # 長川
    ]


def get_merged_staff_preferences() -> dict[str, StaffPreferences]:
    """Get merged staff preferences by staff ID."""
    merged: dict[str, StaffPreferences] = {}

    for pref in get_staff_preferences():
        if pref.staff_id not in merged:
            merged[pref.staff_id] = StaffPreferences(staff_id=pref.staff_id)

        existing = merged[pref.staff_id]
        existing.requested_off.extend(pref.requested_off)
        existing.requested_work.extend(pref.requested_work)
        existing.standby_unavailable.extend(pref.standby_unavailable)

    # Remove duplicates
    for pref in merged.values():
        pref.requested_off = sorted(set(pref.requested_off))
        pref.requested_work = sorted(set(pref.requested_work))
        pref.standby_unavailable = sorted(set(pref.standby_unavailable))

    return merged


def get_previous_month_carryover() -> list[PreviousMonthCarryover]:
    """Get carryover information from August 2025."""
    return [
        # HC-06: 長川は前月末に待機担当 → 9/1は8:00出勤
        PreviousMonthCarryover(staff_id="S09", had_standby_on_last_day=True),
    ]


def get_standby_distribution() -> tuple[int, int]:
    """
    Get the standby distribution.

    Returns:
        Tuple of (count_for_4_times, count_for_3_times)
        HC-05: 待機回数: 4回 × 3名, 3回 × 6名（合計30回/月）
    """
    return (3, 6)  # 3 staff with 4 times, 6 staff with 3 times


def get_constraints_config() -> dict:
    """Get constraint configuration."""
    return {
        # HC-01: 勤務日数
        "full_time_work_days": 20,
        "full_time_off_days": 10,

        # HC-02: 労働時間
        "full_time_monthly_hours": 160,
        "hours_per_day": 8,

        # HC-03: 平日の人員配置
        "weekday_early_count": 1,  # 7:30出勤
        "weekday_normal_count": 2,  # 8:00出勤（うち1名は前日待機者）
        "weekday_min_full_time": 7,  # 正社員最低出勤数
        "weekday_max_part_time": 3,  # パート最大出勤数

        # HC-04: 土日祝の人員配置
        "weekend_total_count": 3,  # 出勤者合計
        "weekend_normal_count": 1,  # 8:00出勤（前日待機者）
        "weekend_late_count": 2,  # 9:00出勤

        # HC-05: 待機ロジック
        "standby_per_day": 1,  # 毎日1名
        "standby_min_interval": 6,  # 待機間隔 ≥ 6日
        "standby_high_count": 4,  # 4回担当する人数
        "standby_low_count": 3,  # 3回担当する人数

        # HC-07: 連続勤務制限
        "max_consecutive_days": 5,
    }
