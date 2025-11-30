"""Streamlit application for hospital shift calendar display."""
import json
from pathlib import Path
from datetime import datetime
import streamlit as st

# Add src to path for imports
import sys
sys.path.insert(0, str(Path(__file__).parent))

from src.models import DayType, ShiftType
from src.data import get_staff_list, get_september_2025_calendar


def load_schedule_data(json_path: str = "output/shift_schedule.json") -> dict:
    """Load schedule data from JSON file."""
    path = Path(json_path)
    if not path.exists():
        return None
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def get_badge_class(shift_time: str) -> str:
    """Get CSS badge class for shift time."""
    if shift_time == "7:30":
        return "badge-730"
    elif shift_time == "8:00":
        return "badge-800"
    elif shift_time == "9:00":
        return "badge-900"
    return ""


def get_day_class(day_info) -> str:
    """Get CSS class for day type."""
    if day_info.day_type == DayType.SATURDAY:
        return "saturday"
    elif day_info.day_type in (DayType.SUNDAY, DayType.HOLIDAY):
        return "sunday-holiday"
    return "weekday"


def generate_calendar_html(schedule_data: dict, calendar: list, staff_list: list) -> str:
    """Generate HTML for the calendar display."""

    # Create staff name lookup
    staff_by_name = {s.name: s for s in staff_list}

    # Build day info lookup
    day_info_map = {d.day: d for d in calendar}

    # CSS Styles
    css = """
    <style>
    .calendar-container {
        overflow-x: auto !important;
        padding: 10px !important;
        background: #f5f5f5 !important;
    }
    .calendar-grid {
        display: grid !important;
        grid-template-columns: repeat(7, 140px) !important;
        gap: 4px !important;
        width: max-content !important;
    }
    .calendar-cell {
        width: 140px !important;
        height: 180px !important;
        min-width: 140px !important;
        min-height: 180px !important;
        max-width: 140px !important;
        max-height: 180px !important;
        overflow-y: auto !important;
        background: #FFFFFF !important;
        border: 1px solid #ddd !important;
        padding: 8px !important;
        box-sizing: border-box !important;
        border-radius: 4px !important;
    }
    .calendar-cell.saturday {
        background: #e3f2fd !important;
    }
    .calendar-cell.sunday-holiday {
        background: #ffebee !important;
    }
    .calendar-cell.empty {
        background: #f9f9f9 !important;
        border: 1px dashed #ddd !important;
    }
    .date-header {
        font-size: 16px !important;
        font-weight: bold !important;
        color: #333333 !important;
        margin-bottom: 8px !important;
        padding-bottom: 4px !important;
        border-bottom: 1px solid #eee !important;
    }
    .date-header.saturday {
        color: #1565c0 !important;
    }
    .date-header.sunday-holiday {
        color: #c62828 !important;
    }
    .holiday-note {
        font-size: 10px !important;
        color: #c62828 !important;
        margin-left: 4px !important;
    }
    .staff-row {
        font-size: 12px !important;
        color: #333333 !important;
        margin: 3px 0 !important;
        display: flex !important;
        align-items: center !important;
        gap: 4px !important;
    }
    .staff-name {
        color: #333333 !important;
        white-space: nowrap !important;
        overflow: hidden !important;
        text-overflow: ellipsis !important;
        max-width: 50px !important;
    }
    .badge-730 {
        background: #e3f2fd !important;
        color: #1565c0 !important;
        padding: 2px 6px !important;
        border-radius: 4px !important;
        font-size: 11px !important;
        white-space: nowrap !important;
    }
    .badge-800 {
        background: #e8f5e9 !important;
        color: #2e7d32 !important;
        padding: 2px 6px !important;
        border-radius: 4px !important;
        font-size: 11px !important;
        white-space: nowrap !important;
    }
    .badge-900 {
        background: #fff9c4 !important;
        color: #f57f17 !important;
        padding: 2px 6px !important;
        border-radius: 4px !important;
        font-size: 11px !important;
        white-space: nowrap !important;
    }
    .standby-mark {
        color: #c62828 !important;
        font-size: 12px !important;
    }
    .weekday-header {
        display: grid !important;
        grid-template-columns: repeat(7, 140px) !important;
        gap: 4px !important;
        margin-bottom: 4px !important;
        width: max-content !important;
    }
    .weekday-cell {
        width: 140px !important;
        text-align: center !important;
        font-weight: bold !important;
        padding: 8px !important;
        background: #fff !important;
        border-radius: 4px !important;
        color: #333333 !important;
    }
    .weekday-cell.sat {
        color: #1565c0 !important;
        background: #e3f2fd !important;
    }
    .weekday-cell.sun {
        color: #c62828 !important;
        background: #ffebee !important;
    }
    </style>
    """

    # Weekday header
    weekday_header = """
    <div class="weekday-header">
        <div class="weekday-cell">月</div>
        <div class="weekday-cell">火</div>
        <div class="weekday-cell">水</div>
        <div class="weekday-cell">木</div>
        <div class="weekday-cell">金</div>
        <div class="weekday-cell sat">土</div>
        <div class="weekday-cell sun">日</div>
    </div>
    """

    # Build calendar cells
    cells_html = []

    # September 2025 starts on Monday, so no empty cells at the start
    # But we need to add empty cells for proper grid alignment
    # Day 1 is Monday (index 0), so no leading empty cells needed

    for day_data in schedule_data["schedule"]:
        day_num = int(day_data["date"].split("-")[2])
        day_info = day_info_map[day_num]

        day_class = get_day_class(day_info)
        date_class = day_class

        # Holiday note
        holiday_note = ""
        if day_info.note:
            holiday_note = f'<span class="holiday-note">{day_info.note}</span>'

        # Date header
        date_header = f'<div class="date-header {date_class}">{day_num} ({day_info.weekday}){holiday_note}</div>'

        # Staff rows - only show working staff (not OFF)
        staff_rows = []
        shifts = day_data.get("shifts", {})

        # Get standby person for this day
        standby_name = schedule_data.get("standby_assignments", {}).get(str(day_num), "")

        # Sort staff by shift time for consistent display
        sorted_shifts = []
        for staff_name, shift_info in shifts.items():
            shift_type = shift_info.get("shift", "")
            if shift_type != "休":  # Only show working staff
                sorted_shifts.append((staff_name, shift_type, shift_info.get("is_standby", False)))

        # Sort by shift time: 7:30 -> 8:00 -> 9:00
        shift_order = {"7:30": 0, "8:00": 1, "9:00": 2}
        sorted_shifts.sort(key=lambda x: (shift_order.get(x[1], 99), x[0]))

        for staff_name, shift_type, is_standby in sorted_shifts:
            badge_class = get_badge_class(shift_type)
            standby_mark = '<span class="standby-mark">*</span>' if is_standby or staff_name == standby_name else ""

            staff_row = f'''
            <div class="staff-row">
                <span class="staff-name">{staff_name}</span>
                <span class="{badge_class}">[{shift_type}]</span>
                {standby_mark}
            </div>
            '''
            staff_rows.append(staff_row)

        staff_html = "".join(staff_rows)

        cell_html = f'''
        <div class="calendar-cell {day_class}">
            {date_header}
            {staff_html}
        </div>
        '''
        cells_html.append(cell_html)

    # Combine all cells
    grid_html = f'''
    <div class="calendar-container">
        {weekday_header}
        <div class="calendar-grid">
            {"".join(cells_html)}
        </div>
    </div>
    '''

    return css + grid_html


def main():
    """Main Streamlit application."""
    st.set_page_config(
        page_title="病院シフトカレンダー",
        page_icon="📅",
        layout="wide"
    )

    st.title("病院スタッフシフトカレンダー - 2025年9月")

    # Load data
    schedule_data = load_schedule_data()

    if schedule_data is None:
        st.error("シフトデータが見つかりません。先にスケジューラを実行してください。")
        st.code("python -m src.main", language="bash")

        # Show demo with sample data
        if st.button("デモデータで表示"):
            schedule_data = generate_demo_data()
        else:
            return

    # Get calendar and staff info
    calendar = get_september_2025_calendar()
    staff_list = get_staff_list()

    # Generate and display calendar
    calendar_html = generate_calendar_html(schedule_data, calendar, staff_list)
    st.markdown(calendar_html, unsafe_allow_html=True)

    # Legend
    st.markdown("---")
    st.subheader("凡例")

    legend_html = """
    <style>
    .legend-container {
        display: flex !important;
        gap: 20px !important;
        flex-wrap: wrap !important;
        padding: 10px !important;
        background: #fff !important;
        border-radius: 8px !important;
    }
    .legend-item {
        display: flex !important;
        align-items: center !important;
        gap: 8px !important;
        color: #333333 !important;
    }
    .legend-badge-730 {
        background: #e3f2fd !important;
        color: #1565c0 !important;
        padding: 2px 6px !important;
        border-radius: 4px !important;
        font-size: 11px !important;
    }
    .legend-badge-800 {
        background: #e8f5e9 !important;
        color: #2e7d32 !important;
        padding: 2px 6px !important;
        border-radius: 4px !important;
        font-size: 11px !important;
    }
    .legend-badge-900 {
        background: #fff9c4 !important;
        color: #f57f17 !important;
        padding: 2px 6px !important;
        border-radius: 4px !important;
        font-size: 11px !important;
    }
    .legend-standby {
        color: #c62828 !important;
    }
    .legend-bg-weekday {
        background: #FFFFFF !important;
        padding: 4px 8px !important;
        border: 1px solid #ddd !important;
        border-radius: 4px !important;
    }
    .legend-bg-saturday {
        background: #e3f2fd !important;
        padding: 4px 8px !important;
        border-radius: 4px !important;
    }
    .legend-bg-sunday {
        background: #ffebee !important;
        padding: 4px 8px !important;
        border-radius: 4px !important;
    }
    </style>
    <div class="legend-container">
        <div class="legend-item">
            <span class="legend-badge-730">[7:30]</span>
            <span style="color: #333333 !important;">早番</span>
        </div>
        <div class="legend-item">
            <span class="legend-badge-800">[8:00]</span>
            <span style="color: #333333 !important;">通常</span>
        </div>
        <div class="legend-item">
            <span class="legend-badge-900">[9:00]</span>
            <span style="color: #333333 !important;">遅番</span>
        </div>
        <div class="legend-item">
            <span class="legend-standby">*</span>
            <span style="color: #333333 !important;">待機担当</span>
        </div>
        <div class="legend-item">
            <span class="legend-bg-weekday">平日</span>
        </div>
        <div class="legend-item">
            <span class="legend-bg-saturday">土曜</span>
        </div>
        <div class="legend-item">
            <span class="legend-bg-sunday">日曜・祝日</span>
        </div>
    </div>
    """
    st.markdown(legend_html, unsafe_allow_html=True)

    # Statistics summary
    if schedule_data.get("statistics"):
        st.markdown("---")
        st.subheader("スタッフ別集計")

        stats_data = []
        for stat in schedule_data["statistics"]:
            stats_data.append({
                "スタッフ": stat["staff_name"],
                "勤務日数": stat["work_days"],
                "休日数": stat["off_days"],
                "7:30": stat["shift_distribution"]["7:30"],
                "8:00": stat["shift_distribution"]["8:00"],
                "9:00": stat["shift_distribution"]["9:00"],
                "待機回数": stat["standby_count"],
                "土日祝": stat["weekend_holiday_count"]
            })

        st.dataframe(stats_data, use_container_width=True)


def generate_demo_data() -> dict:
    """Generate demo data for display testing."""
    import random

    calendar = get_september_2025_calendar()
    staff_list = get_staff_list()

    data = {
        "year": 2025,
        "month": 9,
        "schedule": [],
        "standby_assignments": {},
        "statistics": []
    }

    shift_types = ["7:30", "8:00", "9:00", "休"]
    full_time_staff = [s for s in staff_list if s.is_full_time()]

    for day_info in calendar:
        day_data = {
            "date": f"2025-09-{day_info.day:02d}",
            "weekday": day_info.weekday,
            "day_type": day_info.day_type.value,
            "shifts": {}
        }

        # Assign shifts to staff
        for staff in staff_list:
            if staff.is_full_time():
                # Random shift assignment for demo
                if random.random() > 0.3:  # 70% chance of working
                    shift = random.choice(["7:30", "8:00", "9:00"])
                    day_data["shifts"][staff.name] = {
                        "shift": shift,
                        "is_standby": False
                    }
            else:
                # Part-time always 9:00 when working
                if random.random() > 0.5:
                    day_data["shifts"][staff.name] = {
                        "shift": "9:00",
                        "is_standby": False
                    }

        # Assign standby
        working_full_time = [s for s in full_time_staff if s.name in day_data["shifts"]]
        if working_full_time:
            standby = random.choice(working_full_time)
            data["standby_assignments"][str(day_info.day)] = standby.name
            if standby.name in day_data["shifts"]:
                day_data["shifts"][standby.name]["is_standby"] = True

        data["schedule"].append(day_data)

    return data


if __name__ == "__main__":
    main()
