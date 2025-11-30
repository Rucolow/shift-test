"""Streamlit UI for the hospital shift management system."""
import streamlit as st
import calendar
from datetime import date
from typing import Optional

from src.models import (
    MonthlySchedule, ShiftType, DayType, Staff, DayInfo, ShiftAssignment
)
from src.data import (
    get_staff_list, get_september_2025_calendar,
    get_merged_staff_preferences, get_previous_month_carryover,
    get_constraints_config
)
from src.solver import ShiftScheduler


# Color definitions
SHIFT_COLORS = {
    ShiftType.EARLY: "#e3f2fd",   # Light blue for 7:30
    ShiftType.NORMAL: "#e8f5e9",  # Light green for 8:00
    ShiftType.LATE: "#fff9c4",    # Light yellow for 9:00
    ShiftType.OFF: "#f5f5f5",     # Light gray for off
}

SHIFT_TEXT_COLORS = {
    ShiftType.EARLY: "#1565c0",   # Dark blue
    ShiftType.NORMAL: "#2e7d32",  # Dark green
    ShiftType.LATE: "#f9a825",    # Dark yellow/orange
    ShiftType.OFF: "#9e9e9e",     # Gray
}

SATURDAY_BG = "#e3f2fd"  # Light blue
SUNDAY_HOLIDAY_BG = "#ffebee"  # Light red


def get_shift_badge_html(shift_type: ShiftType, is_standby: bool = False) -> str:
    """Generate HTML badge for shift type."""
    bg_color = SHIFT_COLORS[shift_type]
    text_color = SHIFT_TEXT_COLORS[shift_type]
    standby_mark = " [待機]" if is_standby else ""

    return f'<span style="background-color:{bg_color}; color:{text_color}; padding:2px 6px; border-radius:4px; font-size:0.8em; white-space:nowrap;">{shift_type.value}{standby_mark}</span>'


def run_scheduler_cached() -> tuple[Optional[MonthlySchedule], list[Staff], list[DayInfo]]:
    """Run the scheduler with caching."""
    staff_list = get_staff_list()
    calendar_data = get_september_2025_calendar()
    preferences = get_merged_staff_preferences()
    carryover = get_previous_month_carryover()
    config = get_constraints_config()

    scheduler = ShiftScheduler(staff_list, calendar_data, preferences, carryover, config)

    # Validate input
    errors = scheduler.validate_input()
    if errors:
        st.error("入力データエラー: " + ", ".join(errors))
        return None, staff_list, calendar_data

    # Check feasibility
    conflicts = scheduler.check_feasibility()
    if conflicts:
        st.error("制約矛盾: " + ", ".join(conflicts))
        return None, staff_list, calendar_data

    # Build and solve
    scheduler.build_model()
    schedule = scheduler.solve(time_limit_seconds=60)

    return schedule, staff_list, calendar_data


def get_assignments_by_day(schedule: MonthlySchedule) -> dict[int, list[ShiftAssignment]]:
    """Group assignments by day."""
    by_day: dict[int, list[ShiftAssignment]] = {}
    for assignment in schedule.assignments:
        if assignment.day not in by_day:
            by_day[assignment.day] = []
        by_day[assignment.day].append(assignment)
    return by_day


def render_calendar_view(
    schedule: MonthlySchedule,
    staff_list: list[Staff],
    calendar_data: list[DayInfo],
    highlight_staff: Optional[str] = None
):
    """Render the calendar view of the schedule."""
    staff_by_id = {s.id: s for s in staff_list}
    day_info_map = {d.day: d for d in calendar_data}
    assignments_by_day = get_assignments_by_day(schedule)

    # September 2025: starts on Monday (weekday 0)
    # Build week rows: we'll use Mon-Sun layout
    # Day 1 = Monday, so week 1 starts on day 1

    st.markdown("### 2025年9月 シフトカレンダー")

    # Legend
    st.markdown("""
    <div style="margin-bottom: 20px; padding: 10px; background-color: #fafafa; border-radius: 8px;">
        <strong>凡例:</strong>
        <span style="background-color:#e3f2fd; color:#1565c0; padding:2px 8px; border-radius:4px; margin-left:10px;">7:30</span>
        <span style="background-color:#e8f5e9; color:#2e7d32; padding:2px 8px; border-radius:4px; margin-left:10px;">8:00</span>
        <span style="background-color:#fff9c4; color:#f9a825; padding:2px 8px; border-radius:4px; margin-left:10px;">9:00</span>
        <span style="margin-left:20px;">| 土曜: 薄青背景 | 日曜・祝日: 薄赤背景 | [待機]: 待機担当</span>
    </div>
    """, unsafe_allow_html=True)

    # Header row
    weekday_names = ["月", "火", "水", "木", "金", "土", "日"]
    header_cols = st.columns(7)
    for i, name in enumerate(weekday_names):
        bg = ""
        if i == 5:  # Saturday
            bg = f"background-color: {SATURDAY_BG};"
        elif i == 6:  # Sunday
            bg = f"background-color: {SUNDAY_HOLIDAY_BG};"
        header_cols[i].markdown(
            f'<div style="text-align:center; font-weight:bold; padding:8px; {bg} border-radius:4px;">{name}</div>',
            unsafe_allow_html=True
        )

    # Build weeks
    # September 2025: Day 1 is Monday (index 0), 30 days total
    # Week 1: 1-7, Week 2: 8-14, Week 3: 15-21, Week 4: 22-28, Week 5: 29-30

    weeks = []
    current_week = []

    for day in range(1, 31):
        day_info = day_info_map[day]
        # weekday: 月=0, 火=1, ..., 日=6
        weekday_idx = (day - 1) % 7

        current_week.append((day, day_info, weekday_idx))

        if weekday_idx == 6:  # Sunday, end of week
            weeks.append(current_week)
            current_week = []

    # Add remaining days
    if current_week:
        # Pad with None for remaining days
        while len(current_week) < 7:
            current_week.append(None)
        weeks.append(current_week)

    # Render each week
    for week in weeks:
        cols = st.columns(7)

        for col_idx, day_data in enumerate(week):
            if day_data is None:
                cols[col_idx].markdown('<div style="height:120px;"></div>', unsafe_allow_html=True)
                continue

            day, day_info, weekday_idx = day_data

            # Determine background color
            if day_info.day_type == DayType.SUNDAY or day_info.day_type == DayType.HOLIDAY:
                cell_bg = SUNDAY_HOLIDAY_BG
            elif day_info.day_type == DayType.SATURDAY:
                cell_bg = SATURDAY_BG
            else:
                cell_bg = "#ffffff"

            # Build cell content
            day_assignments = assignments_by_day.get(day, [])
            working_staff = [a for a in day_assignments if a.shift_type != ShiftType.OFF]

            # Sort by shift type
            working_staff.sort(key=lambda a: (
                0 if a.shift_type == ShiftType.EARLY else
                1 if a.shift_type == ShiftType.NORMAL else 2
            ))

            # Build HTML
            html_parts = []

            # Date header
            note = f" ({day_info.note})" if day_info.note else ""
            html_parts.append(
                f'<div style="font-size:1.2em; font-weight:bold; margin-bottom:4px;">{day}{note}</div>'
            )

            # Staff list
            for assignment in working_staff:
                staff = staff_by_id.get(assignment.staff_id)
                if staff:
                    name = staff.name
                    badge = get_shift_badge_html(assignment.shift_type, assignment.is_standby)

                    # Highlight if selected
                    if highlight_staff and assignment.staff_id == highlight_staff:
                        html_parts.append(
                            f'<div style="background-color:#ffeb3b; padding:2px; border-radius:4px; margin:2px 0;">'
                            f'<strong>{name}</strong> {badge}</div>'
                        )
                    else:
                        html_parts.append(f'<div style="margin:2px 0;">{name} {badge}</div>')

            cell_html = f'''
            <div style="
                background-color:{cell_bg};
                border:1px solid #e0e0e0;
                border-radius:8px;
                padding:8px;
                min-height:120px;
                font-size:0.85em;
            ">
                {"".join(html_parts)}
            </div>
            '''

            cols[col_idx].markdown(cell_html, unsafe_allow_html=True)


def render_table_view(
    schedule: MonthlySchedule,
    staff_list: list[Staff],
    calendar_data: list[DayInfo],
    highlight_staff: Optional[str] = None
):
    """Render the traditional table view."""
    staff_by_id = {s.id: s for s in staff_list}
    day_info_map = {d.day: d for d in calendar_data}

    st.markdown("### シフト表（テーブル形式）")

    # Build table data
    full_time_staff = [s for s in staff_list if s.is_full_time()]
    part_time_staff = [s for s in staff_list if s.is_part_time()]

    # Create assignment lookup
    assignment_lookup: dict[tuple[str, int], ShiftAssignment] = {}
    for a in schedule.assignments:
        assignment_lookup[(a.staff_id, a.day)] = a

    # Build HTML table
    html = ['<table style="width:100%; border-collapse:collapse; font-size:0.85em;">']

    # Header row
    html.append('<tr style="background-color:#f5f5f5;">')
    html.append('<th style="border:1px solid #ddd; padding:6px;">日付</th>')
    html.append('<th style="border:1px solid #ddd; padding:6px;">曜日</th>')

    for staff in full_time_staff:
        bg = "#ffeb3b" if highlight_staff == staff.id else ""
        html.append(f'<th style="border:1px solid #ddd; padding:6px; background-color:{bg};">{staff.name}</th>')

    html.append('<th style="border:1px solid #ddd; padding:6px;">パート</th>')
    html.append('<th style="border:1px solid #ddd; padding:6px;">待機</th>')
    html.append('</tr>')

    # Data rows
    for day in range(1, 31):
        day_info = day_info_map[day]

        # Row background
        if day_info.day_type == DayType.SUNDAY or day_info.day_type == DayType.HOLIDAY:
            row_bg = SUNDAY_HOLIDAY_BG
        elif day_info.day_type == DayType.SATURDAY:
            row_bg = SATURDAY_BG
        else:
            row_bg = "#ffffff"

        html.append(f'<tr style="background-color:{row_bg};">')

        # Date
        note = f" {day_info.note}" if day_info.note else ""
        html.append(f'<td style="border:1px solid #ddd; padding:6px;">9/{day}{note}</td>')
        html.append(f'<td style="border:1px solid #ddd; padding:6px; text-align:center;">{day_info.weekday}</td>')

        # Full-time staff columns
        for staff in full_time_staff:
            assignment = assignment_lookup.get((staff.id, day))
            if assignment:
                bg_color = SHIFT_COLORS[assignment.shift_type]
                text_color = SHIFT_TEXT_COLORS[assignment.shift_type]
                text = str(assignment.shift_type)
                if assignment.is_standby:
                    text += "*"

                cell_bg = bg_color
                if highlight_staff == staff.id:
                    cell_bg = "#ffeb3b"

                html.append(
                    f'<td style="border:1px solid #ddd; padding:6px; text-align:center; '
                    f'background-color:{cell_bg}; color:{text_color};">{text}</td>'
                )
            else:
                html.append('<td style="border:1px solid #ddd; padding:6px;"></td>')

        # Part-time count
        part_count = sum(
            1 for s in part_time_staff
            if assignment_lookup.get((s.id, day)) and
               assignment_lookup[(s.id, day)].shift_type != ShiftType.OFF
        )
        html.append(f'<td style="border:1px solid #ddd; padding:6px; text-align:center;">{part_count}名</td>')

        # Standby
        standby_id = schedule.standby_assignments.get(day)
        if standby_id:
            standby_staff = staff_by_id.get(standby_id)
            standby_name = standby_staff.name if standby_staff else standby_id
            html.append(f'<td style="border:1px solid #ddd; padding:6px;">{standby_name}</td>')
        else:
            html.append('<td style="border:1px solid #ddd; padding:6px;">-</td>')

        html.append('</tr>')

    html.append('</table>')

    st.markdown("".join(html), unsafe_allow_html=True)


def render_statistics(schedule: MonthlySchedule, staff_list: list[Staff]):
    """Render staff statistics."""
    st.markdown("### スタッフ別集計")

    full_time_stats = [s for s in schedule.statistics if s.staff_id.startswith("S")]
    part_time_stats = [s for s in schedule.statistics if s.staff_id.startswith("P")]

    # Full-time staff table
    st.markdown("#### 正社員")

    cols = st.columns([1.5, 1, 1, 1, 1, 1, 1, 1])
    headers = ["名前", "勤務日数", "7:30", "8:00", "9:00", "待機", "土日祝", "希望休"]
    for col, header in zip(cols, headers):
        col.markdown(f"**{header}**")

    for stats in full_time_stats:
        cols = st.columns([1.5, 1, 1, 1, 1, 1, 1, 1])
        cols[0].write(stats.staff_name)
        cols[1].write(f"{stats.work_days}日")
        cols[2].write(f"{stats.early_shifts}回")
        cols[3].write(f"{stats.normal_shifts}回")
        cols[4].write(f"{stats.late_shifts}回")
        cols[5].write(f"{stats.standby_count}回")
        cols[6].write(f"{stats.weekend_holiday_count}回")
        cols[7].write(f"{stats.requested_off_fulfilled}/{stats.requested_off_total}")

    # Part-time staff
    if part_time_stats:
        st.markdown("#### パート")
        for stats in part_time_stats:
            st.write(f"{stats.staff_name}: 勤務{stats.work_days}日")


def render_suggestions(schedule: MonthlySchedule):
    """Render suggestions and violations."""
    if schedule.constraint_violations:
        st.markdown("### 制約違反")
        for violation in schedule.constraint_violations:
            st.warning(violation)

    if schedule.suggestions:
        st.markdown("### 改善提案")
        for suggestion in schedule.suggestions:
            st.info(suggestion)


def main():
    st.set_page_config(
        page_title="病院シフト管理システム",
        page_icon="🏥",
        layout="wide"
    )

    st.title("病院スタッフシフト管理システム")
    st.markdown("2025年9月 シフトスケジュール")

    # Sidebar for controls
    with st.sidebar:
        st.header("設定")

        # Staff filter
        staff_list = get_staff_list()
        staff_options = ["なし（全員表示）"] + [s.name for s in staff_list if s.is_full_time()]
        selected_staff_name = st.selectbox(
            "スタッフをハイライト",
            options=staff_options,
            index=0
        )

        highlight_staff_id = None
        if selected_staff_name != "なし（全員表示）":
            for s in staff_list:
                if s.name == selected_staff_name:
                    highlight_staff_id = s.id
                    break

        st.markdown("---")

        # Generate button
        if st.button("シフトを生成", type="primary"):
            st.session_state.generate = True

    # Check if we should generate
    if "generate" not in st.session_state:
        st.session_state.generate = False

    if st.session_state.generate:
        with st.spinner("シフトを最適化中..."):
            schedule, staff_list, calendar_data = run_scheduler_cached()

        if schedule:
            st.success("シフト生成完了!")

            # Store in session state
            st.session_state.schedule = schedule
            st.session_state.staff_list = staff_list
            st.session_state.calendar_data = calendar_data

    # Display results if available
    if "schedule" in st.session_state and st.session_state.schedule:
        schedule = st.session_state.schedule
        staff_list = st.session_state.staff_list
        calendar_data = st.session_state.calendar_data

        # Tabs for different views
        tab1, tab2, tab3 = st.tabs(["カレンダー表示", "テーブル表示", "統計・提案"])

        with tab1:
            render_calendar_view(schedule, staff_list, calendar_data, highlight_staff_id)

        with tab2:
            render_table_view(schedule, staff_list, calendar_data, highlight_staff_id)

        with tab3:
            render_statistics(schedule, staff_list)
            render_suggestions(schedule)
    else:
        st.info("サイドバーの「シフトを生成」ボタンをクリックしてシフトを生成してください。")


if __name__ == "__main__":
    main()
