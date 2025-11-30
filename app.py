"""Streamlit web application for hospital shift management."""
import streamlit as st
from datetime import datetime, date
from typing import Optional
import json

# Add src to path
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from src.models import (
    Staff, StaffType, DayInfo, DayType, ShiftType,
    StaffPreferences, MonthlySchedule, ShiftAssignment
)
from src.data import (
    get_staff_list, get_september_2025_calendar,
    get_merged_staff_preferences, get_previous_month_carryover,
    get_constraints_config, get_full_time_staff
)
from src.solver import ShiftScheduler
from src.output import OutputGenerator


# ============================================================================
# Session State Initialization
# ============================================================================

def init_session_state():
    """Initialize session state variables."""
    if 'preferences' not in st.session_state:
        # Load initial preferences from data.py
        st.session_state.preferences = get_merged_staff_preferences()

    if 'schedule' not in st.session_state:
        st.session_state.schedule = None

    if 'selected_year' not in st.session_state:
        st.session_state.selected_year = 2025

    if 'selected_month' not in st.session_state:
        st.session_state.selected_month = 9


# ============================================================================
# Preference Management Functions
# ============================================================================

def add_preference(staff_id: str, day: int, pref_type: str):
    """Add a preference for a staff member."""
    if staff_id not in st.session_state.preferences:
        st.session_state.preferences[staff_id] = StaffPreferences(staff_id=staff_id)

    pref = st.session_state.preferences[staff_id]

    if pref_type == "希望休":
        if day not in pref.requested_off:
            pref.requested_off.append(day)
            pref.requested_off.sort()
            # Remove from conflicting lists
            if day in pref.requested_work:
                pref.requested_work.remove(day)
    elif pref_type == "勤務希望":
        if day not in pref.requested_work:
            pref.requested_work.append(day)
            pref.requested_work.sort()
            # Remove from conflicting lists
            if day in pref.requested_off:
                pref.requested_off.remove(day)
    elif pref_type == "待機不可":
        if day not in pref.standby_unavailable:
            pref.standby_unavailable.append(day)
            pref.standby_unavailable.sort()


def remove_preference(staff_id: str, day: int, pref_type: str):
    """Remove a preference for a staff member."""
    if staff_id not in st.session_state.preferences:
        return

    pref = st.session_state.preferences[staff_id]

    if pref_type == "希望休" and day in pref.requested_off:
        pref.requested_off.remove(day)
    elif pref_type == "勤務希望" and day in pref.requested_work:
        pref.requested_work.remove(day)
    elif pref_type == "待機不可" and day in pref.standby_unavailable:
        pref.standby_unavailable.remove(day)


def get_staff_preference_summary(staff_id: str) -> dict:
    """Get a summary of preferences for a staff member."""
    if staff_id not in st.session_state.preferences:
        return {"requested_off": [], "requested_work": [], "standby_unavailable": []}

    pref = st.session_state.preferences[staff_id]
    return {
        "requested_off": pref.requested_off,
        "requested_work": pref.requested_work,
        "standby_unavailable": pref.standby_unavailable
    }


# ============================================================================
# Calendar HTML Generation
# ============================================================================

def generate_calendar_html(calendar: list[DayInfo], schedule: Optional[MonthlySchedule] = None) -> str:
    """Generate an HTML calendar view."""
    # CSS styles
    css = """
    <style>
        .calendar-container {
            font-family: 'Hiragino Kaku Gothic Pro', 'Meiryo', sans-serif;
        }
        .calendar-table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 10px;
        }
        .calendar-table th, .calendar-table td {
            border: 1px solid #ddd;
            padding: 8px;
            text-align: center;
            min-width: 40px;
        }
        .calendar-table th {
            background-color: #4a6fa5;
            color: white;
            font-weight: bold;
        }
        .calendar-table th.saturday {
            background-color: #5a8fcf;
        }
        .calendar-table th.sunday {
            background-color: #e57373;
        }
        .day-cell {
            vertical-align: top;
            height: 80px;
            position: relative;
        }
        .day-number {
            font-weight: bold;
            font-size: 14px;
        }
        .day-saturday {
            color: #1976d2;
        }
        .day-sunday, .day-holiday {
            color: #d32f2f;
        }
        .holiday-name {
            font-size: 10px;
            color: #d32f2f;
        }
        .shift-info {
            font-size: 11px;
            margin-top: 5px;
        }
        .shift-early { color: #2e7d32; }
        .shift-normal { color: #1565c0; }
        .shift-late { color: #6a1b9a; }
        .shift-standby {
            background-color: #fff3e0;
            border-radius: 3px;
            padding: 2px 4px;
        }
        .empty-cell {
            background-color: #f5f5f5;
        }
    </style>
    """

    # Create day lookup
    day_info_map = {d.day: d for d in calendar}

    # Header row
    weekdays = ["月", "火", "水", "木", "金", "土", "日"]
    header_classes = ["", "", "", "", "", "saturday", "sunday"]

    header_html = "<tr>"
    for i, wd in enumerate(weekdays):
        header_html += f'<th class="{header_classes[i]}">{wd}</th>'
    header_html += "</tr>"

    # Body rows (5 weeks for September 2025)
    body_html = ""
    day = 1

    # September 2025 starts on Monday
    for week in range(5):
        body_html += "<tr>"
        for weekday in range(7):
            if day <= 30:
                day_data = day_info_map.get(day)

                # Determine day class
                day_class = "day-number"
                if day_data:
                    if day_data.day_type == DayType.SUNDAY:
                        day_class += " day-sunday"
                    elif day_data.day_type == DayType.SATURDAY:
                        day_class += " day-saturday"
                    elif day_data.day_type == DayType.HOLIDAY:
                        day_class += " day-holiday"

                # Holiday name if applicable
                holiday_html = ""
                if day_data and day_data.note:
                    holiday_html = f'<div class="holiday-name">{day_data.note}</div>'

                # Shift information if schedule exists
                shift_html = ""
                if schedule:
                    shift_html = generate_day_shift_html(schedule, day)

                body_html += f'''
                <td class="day-cell">
                    <div class="{day_class}">{day}</div>
                    {holiday_html}
                    {shift_html}
                </td>
                '''
                day += 1
            else:
                body_html += '<td class="empty-cell"></td>'
        body_html += "</tr>"

    # Combine everything
    html = f'''
    {css}
    <div class="calendar-container">
        <table class="calendar-table">
            <thead>{header_html}</thead>
            <tbody>{body_html}</tbody>
        </table>
    </div>
    '''

    return html


def generate_day_shift_html(schedule: MonthlySchedule, day: int) -> str:
    """Generate HTML for shifts on a specific day."""
    assignments = [a for a in schedule.assignments if a.day == day and a.shift_type != ShiftType.OFF]

    if not assignments:
        return '<div class="shift-info">-</div>'

    # Count by shift type
    early_count = sum(1 for a in assignments if a.shift_type == ShiftType.EARLY)
    normal_count = sum(1 for a in assignments if a.shift_type == ShiftType.NORMAL)
    late_count = sum(1 for a in assignments if a.shift_type == ShiftType.LATE)

    # Standby person
    standby_id = schedule.standby_assignments.get(day)

    html = '<div class="shift-info">'
    if early_count > 0:
        html += f'<span class="shift-early">7:30×{early_count}</span> '
    if normal_count > 0:
        html += f'<span class="shift-normal">8:00×{normal_count}</span> '
    if late_count > 0:
        html += f'<span class="shift-late">9:00×{late_count}</span>'
    html += '</div>'

    if standby_id:
        staff_list = get_staff_list()
        staff_map = {s.id: s for s in staff_list}
        staff = staff_map.get(standby_id)
        name = staff.name if staff else standby_id
        html += f'<div class="shift-standby">待機: {name}</div>'

    return html


# ============================================================================
# UI Components
# ============================================================================

def render_sidebar():
    """Render the sidebar with preferences input."""
    st.sidebar.title("シフト管理")

    # Year/Month selection
    st.sidebar.subheader("対象期間")
    col1, col2 = st.sidebar.columns(2)
    with col1:
        st.session_state.selected_year = st.number_input(
            "年", min_value=2024, max_value=2030,
            value=st.session_state.selected_year, key="year_input"
        )
    with col2:
        st.session_state.selected_month = st.number_input(
            "月", min_value=1, max_value=12,
            value=st.session_state.selected_month, key="month_input"
        )

    st.sidebar.divider()

    # Preference input section
    st.sidebar.subheader("希望休・勤務希望入力")

    staff_list = get_staff_list()
    staff_options = {f"{s.name} ({s.id})": s.id for s in staff_list}

    selected_staff_display = st.sidebar.selectbox(
        "スタッフ選択",
        options=list(staff_options.keys()),
        key="staff_select"
    )
    selected_staff_id = staff_options[selected_staff_display]

    # Preference type
    pref_type = st.sidebar.selectbox(
        "種類",
        options=["希望休", "勤務希望", "待機不可"],
        key="pref_type"
    )

    # Date input
    calendar = get_september_2025_calendar()
    day_options = [f"{d.day}日 ({d.weekday})" for d in calendar]

    selected_day_display = st.sidebar.selectbox(
        "日付",
        options=day_options,
        key="day_select"
    )
    selected_day = int(selected_day_display.split("日")[0])

    # Add button
    if st.sidebar.button("追加", key="add_pref_btn", type="primary"):
        add_preference(selected_staff_id, selected_day, pref_type)
        st.sidebar.success(f"{selected_staff_display}に{pref_type}を追加しました: {selected_day}日")

    # Current preferences for selected staff
    st.sidebar.divider()
    st.sidebar.subheader("現在の設定")
    pref_summary = get_staff_preference_summary(selected_staff_id)

    if pref_summary["requested_off"]:
        st.sidebar.markdown(f"**希望休:** {', '.join(map(str, pref_summary['requested_off']))}日")
    if pref_summary["requested_work"]:
        st.sidebar.markdown(f"**勤務希望:** {', '.join(map(str, pref_summary['requested_work']))}日")
    if pref_summary["standby_unavailable"]:
        st.sidebar.markdown(f"**待機不可:** {', '.join(map(str, pref_summary['standby_unavailable']))}日")

    st.sidebar.divider()

    # Generate schedule button
    if st.sidebar.button("シフト生成", key="generate_btn", type="primary"):
        with st.spinner("シフトを生成中..."):
            generate_schedule()


def render_calendar_tab():
    """Render the calendar view tab."""
    st.header("カレンダー表示")

    calendar = get_september_2025_calendar()
    schedule = st.session_state.schedule

    # Legend
    legend_html = """
    <div style="margin-bottom: 15px; font-size: 12px;">
        <span style="color: #2e7d32; margin-right: 15px;">● 7:30 (早番)</span>
        <span style="color: #1565c0; margin-right: 15px;">● 8:00 (通常)</span>
        <span style="color: #6a1b9a; margin-right: 15px;">● 9:00 (遅番)</span>
        <span style="background-color: #fff3e0; padding: 2px 6px; border-radius: 3px;">待機</span>
    </div>
    """
    st.markdown(legend_html, unsafe_allow_html=True)

    # Calendar
    calendar_html = generate_calendar_html(calendar, schedule)
    st.markdown(calendar_html, unsafe_allow_html=True)

    if schedule is None:
        st.info("シフトを生成するには、サイドバーの「シフト生成」ボタンをクリックしてください。")


def render_table_tab():
    """Render the table view tab."""
    st.header("テーブル表示")

    schedule = st.session_state.schedule

    if schedule is None:
        st.info("シフトを生成するには、サイドバーの「シフト生成」ボタンをクリックしてください。")
        return

    staff_list = get_staff_list()
    calendar = get_september_2025_calendar()

    # Create table HTML
    css = """
    <style>
        .shift-table {
            width: 100%;
            border-collapse: collapse;
            font-size: 11px;
        }
        .shift-table th, .shift-table td {
            border: 1px solid #ddd;
            padding: 4px;
            text-align: center;
        }
        .shift-table th {
            background-color: #4a6fa5;
            color: white;
            position: sticky;
            top: 0;
        }
        .shift-table th.staff-header {
            background-color: #5c6bc0;
        }
        .shift-table .weekend {
            background-color: #e3f2fd;
        }
        .shift-table .holiday {
            background-color: #ffebee;
        }
        .cell-early { background-color: #c8e6c9; }
        .cell-normal { background-color: #bbdefb; }
        .cell-late { background-color: #e1bee7; }
        .cell-off { background-color: #f5f5f5; color: #999; }
        .cell-standby {
            background-color: #fff3e0 !important;
            font-weight: bold;
        }
    </style>
    """

    # Header
    header_html = "<tr><th>スタッフ</th>"
    for day_info in calendar:
        day_class = ""
        if day_info.day_type == DayType.SATURDAY:
            day_class = "weekend"
        elif day_info.day_type in (DayType.SUNDAY, DayType.HOLIDAY):
            day_class = "holiday"
        header_html += f'<th class="{day_class}">{day_info.day}<br>{day_info.weekday}</th>'
    header_html += "</tr>"

    # Body
    body_html = ""
    for staff in staff_list:
        body_html += f'<tr><td class="staff-header">{staff.name}</td>'
        for day_info in calendar:
            assignment = next(
                (a for a in schedule.assignments
                 if a.staff_id == staff.id and a.day == day_info.day),
                None
            )

            if assignment:
                if assignment.shift_type == ShiftType.OFF:
                    cell_class = "cell-off"
                    text = "休"
                elif assignment.shift_type == ShiftType.EARLY:
                    cell_class = "cell-early"
                    text = "7:30"
                elif assignment.shift_type == ShiftType.NORMAL:
                    cell_class = "cell-normal"
                    text = "8:00"
                else:
                    cell_class = "cell-late"
                    text = "9:00"

                if assignment.is_standby:
                    cell_class += " cell-standby"
                    text += "*"
            else:
                cell_class = "cell-off"
                text = "-"

            body_html += f'<td class="{cell_class}">{text}</td>'
        body_html += "</tr>"

    # Standby row
    body_html += '<tr style="background-color: #fff8e1;"><td><strong>待機担当</strong></td>'
    staff_map = {s.id: s for s in staff_list}
    for day_info in calendar:
        standby_id = schedule.standby_assignments.get(day_info.day)
        if standby_id:
            staff = staff_map.get(standby_id)
            name = staff.name if staff else standby_id
            body_html += f'<td>{name}</td>'
        else:
            body_html += '<td>-</td>'
    body_html += "</tr>"

    html = f"""
    {css}
    <div style="overflow-x: auto;">
        <table class="shift-table">
            <thead>{header_html}</thead>
            <tbody>{body_html}</tbody>
        </table>
    </div>
    """

    st.markdown(html, unsafe_allow_html=True)
    st.markdown("<p style='font-size: 11px; color: #666;'>* = 待機担当</p>", unsafe_allow_html=True)


def render_statistics_tab():
    """Render the statistics and suggestions tab."""
    st.header("統計・提案")

    schedule = st.session_state.schedule

    if schedule is None:
        st.info("シフトを生成するには、サイドバーの「シフト生成」ボタンをクリックしてください。")
        return

    # Statistics section
    st.subheader("スタッフ別統計")

    # Create statistics table HTML
    stats_html = """
    <style>
        .stats-table {
            width: 100%;
            border-collapse: collapse;
            margin-bottom: 20px;
        }
        .stats-table th, .stats-table td {
            border: 1px solid #ddd;
            padding: 8px;
            text-align: center;
        }
        .stats-table th {
            background-color: #4a6fa5;
            color: white;
        }
        .stats-table tr:nth-child(even) {
            background-color: #f9f9f9;
        }
    </style>
    <table class="stats-table">
        <thead>
            <tr>
                <th>スタッフ</th>
                <th>勤務日数</th>
                <th>休日数</th>
                <th>7:30</th>
                <th>8:00</th>
                <th>9:00</th>
                <th>待機回数</th>
                <th>土日祝</th>
                <th>希望休充足</th>
            </tr>
        </thead>
        <tbody>
    """

    for stats in schedule.statistics:
        stats_html += f"""
        <tr>
            <td>{stats.staff_name}</td>
            <td>{stats.work_days}</td>
            <td>{stats.off_days}</td>
            <td>{stats.early_shifts}</td>
            <td>{stats.normal_shifts}</td>
            <td>{stats.late_shifts}</td>
            <td>{stats.standby_count}</td>
            <td>{stats.weekend_holiday_count}</td>
            <td>{stats.requested_off_fulfilled}/{stats.requested_off_total}</td>
        </tr>
        """

    stats_html += "</tbody></table>"
    st.markdown(stats_html, unsafe_allow_html=True)

    # Constraint violations
    if schedule.constraint_violations:
        st.subheader("制約違反")
        for violation in schedule.constraint_violations:
            st.warning(violation)

    # Suggestions
    st.subheader("改善提案")
    if schedule.suggestions:
        for suggestion in schedule.suggestions:
            st.info(suggestion)
    else:
        st.success("特に改善提案はありません。")


def render_preferences_tab():
    """Render the preferences overview tab."""
    st.header("希望休一覧")

    staff_list = get_staff_list()
    calendar = get_september_2025_calendar()

    # Create preferences table HTML
    css = """
    <style>
        .pref-table {
            width: 100%;
            border-collapse: collapse;
            margin-bottom: 20px;
        }
        .pref-table th, .pref-table td {
            border: 1px solid #ddd;
            padding: 10px;
            text-align: left;
        }
        .pref-table th {
            background-color: #4a6fa5;
            color: white;
        }
        .pref-table tr:nth-child(even) {
            background-color: #f9f9f9;
        }
        .pref-off {
            background-color: #ffcdd2;
            color: #c62828;
            padding: 2px 6px;
            border-radius: 3px;
            margin: 2px;
            display: inline-block;
        }
        .pref-work {
            background-color: #c8e6c9;
            color: #2e7d32;
            padding: 2px 6px;
            border-radius: 3px;
            margin: 2px;
            display: inline-block;
        }
        .pref-standby {
            background-color: #fff3e0;
            color: #e65100;
            padding: 2px 6px;
            border-radius: 3px;
            margin: 2px;
            display: inline-block;
        }
    </style>
    """

    table_html = """
    <table class="pref-table">
        <thead>
            <tr>
                <th>スタッフ</th>
                <th>希望休</th>
                <th>勤務希望</th>
                <th>待機不可</th>
            </tr>
        </thead>
        <tbody>
    """

    for staff in staff_list:
        pref_summary = get_staff_preference_summary(staff.id)

        off_html = ""
        for day in pref_summary["requested_off"]:
            day_info = next((d for d in calendar if d.day == day), None)
            weekday = day_info.weekday if day_info else ""
            off_html += f'<span class="pref-off">{day}日({weekday})</span> '

        work_html = ""
        for day in pref_summary["requested_work"]:
            day_info = next((d for d in calendar if d.day == day), None)
            weekday = day_info.weekday if day_info else ""
            work_html += f'<span class="pref-work">{day}日({weekday})</span> '

        standby_html = ""
        for day in pref_summary["standby_unavailable"]:
            day_info = next((d for d in calendar if d.day == day), None)
            weekday = day_info.weekday if day_info else ""
            standby_html += f'<span class="pref-standby">{day}日({weekday})</span> '

        table_html += f"""
        <tr>
            <td><strong>{staff.name}</strong> ({staff.staff_type.value})</td>
            <td>{off_html if off_html else '-'}</td>
            <td>{work_html if work_html else '-'}</td>
            <td>{standby_html if standby_html else '-'}</td>
        </tr>
        """

    table_html += "</tbody></table>"

    st.markdown(css + table_html, unsafe_allow_html=True)

    # Legend
    legend_html = """
    <div style="margin-top: 20px; font-size: 12px;">
        <strong>凡例:</strong>
        <span class="pref-off" style="background-color: #ffcdd2; color: #c62828; padding: 2px 6px; border-radius: 3px; margin-left: 10px;">希望休</span>
        <span class="pref-work" style="background-color: #c8e6c9; color: #2e7d32; padding: 2px 6px; border-radius: 3px; margin-left: 10px;">勤務希望</span>
        <span class="pref-standby" style="background-color: #fff3e0; color: #e65100; padding: 2px 6px; border-radius: 3px; margin-left: 10px;">待機不可</span>
    </div>
    """
    st.markdown(legend_html, unsafe_allow_html=True)

    # Delete preference section
    st.divider()
    st.subheader("希望の削除")

    col1, col2, col3, col4 = st.columns([2, 2, 2, 1])

    with col1:
        staff_options = {f"{s.name}": s.id for s in staff_list}
        del_staff = st.selectbox("スタッフ", options=list(staff_options.keys()), key="del_staff")
        del_staff_id = staff_options[del_staff]

    with col2:
        del_type = st.selectbox("種類", options=["希望休", "勤務希望", "待機不可"], key="del_type")

    with col3:
        pref_summary = get_staff_preference_summary(del_staff_id)
        if del_type == "希望休":
            days = pref_summary["requested_off"]
        elif del_type == "勤務希望":
            days = pref_summary["requested_work"]
        else:
            days = pref_summary["standby_unavailable"]

        if days:
            del_day = st.selectbox("日付", options=days, key="del_day")
        else:
            st.text("該当なし")
            del_day = None

    with col4:
        st.write("")  # Spacer
        st.write("")
        if del_day and st.button("削除", key="del_btn", type="secondary"):
            remove_preference(del_staff_id, del_day, del_type)
            st.rerun()


def generate_schedule():
    """Generate the shift schedule."""
    try:
        staff_list = get_staff_list()
        calendar = get_september_2025_calendar()
        preferences = st.session_state.preferences
        carryover = get_previous_month_carryover()
        config = get_constraints_config()

        scheduler = ShiftScheduler(staff_list, calendar, preferences, carryover, config)

        # Validate input
        validation_errors = scheduler.validate_input()
        if validation_errors:
            for error in validation_errors:
                st.error(f"入力エラー: {error}")
            return

        # Check feasibility
        conflicts = scheduler.check_feasibility()
        if conflicts:
            for conflict in conflicts:
                st.error(f"制約矛盾: {conflict}")
            return

        # Build and solve
        scheduler.build_model()
        schedule = scheduler.solve(time_limit_seconds=60)

        if schedule:
            st.session_state.schedule = schedule
            st.success("シフト生成が完了しました！")
        else:
            st.error("解が見つかりませんでした。制約条件を確認してください。")

    except Exception as e:
        st.error(f"エラーが発生しました: {str(e)}")


# ============================================================================
# Main Application
# ============================================================================

def main():
    """Main application entry point."""
    st.set_page_config(
        page_title="病院シフト管理システム",
        page_icon="🏥",
        layout="wide",
        initial_sidebar_state="expanded"
    )

    init_session_state()

    # Title
    st.title("病院スタッフシフト管理システム")
    st.markdown(
        f"<p style='color: #666;'>対象期間: {st.session_state.selected_year}年{st.session_state.selected_month}月</p>",
        unsafe_allow_html=True
    )

    # Sidebar
    render_sidebar()

    # Main content with tabs
    tab1, tab2, tab3, tab4 = st.tabs([
        "📅 カレンダー表示",
        "📊 テーブル表示",
        "📈 統計・提案",
        "📝 希望休一覧"
    ])

    with tab1:
        render_calendar_tab()

    with tab2:
        render_table_tab()

    with tab3:
        render_statistics_tab()

    with tab4:
        render_preferences_tab()


if __name__ == "__main__":
    main()
