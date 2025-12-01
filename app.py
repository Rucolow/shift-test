"""Streamlit web application for hospital shift management."""
import streamlit as st
import pandas as pd
import calendar as cal_module
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
from src.validator import validate_schedule, ValidationResult, ValidationItem


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
# Calendar Display Functions (Native Streamlit)
# ============================================================================

def get_day_staff_list(schedule: MonthlySchedule, day: int, day_info: DayInfo, staff_list: list[Staff]) -> list[dict]:
    """Get list of staff working on a specific day with their shift info."""
    assignments = [a for a in schedule.assignments if a.day == day and a.shift_type != ShiftType.OFF]
    staff_map = {s.id: s for s in staff_list}
    standby_id = schedule.standby_assignments.get(day)
    is_weekday = day_info.day_type == DayType.WEEKDAY

    result = []
    for assignment in assignments:
        staff = staff_map.get(assignment.staff_id)
        if not staff:
            continue

        # Skip part-time staff on weekends/holidays
        if staff.is_part_time() and not is_weekday:
            continue

        # Sort order: 7:30=0, 8:00=1, 9:00=2
        if assignment.shift_type == ShiftType.EARLY:
            sort_order = 0
            shift_time = "7:30"
        elif assignment.shift_type == ShiftType.NORMAL:
            sort_order = 1
            shift_time = "8:00"
        else:
            sort_order = 2
            shift_time = "9:00"

        # For part-time, show work hours instead
        if staff.is_part_time():
            display_time = staff.work_hours
        else:
            display_time = shift_time

        result.append({
            "name": staff.name,
            "shift_type": assignment.shift_type,
            "shift_time": shift_time,
            "display_time": display_time,
            "is_standby": assignment.staff_id == standby_id,
            "is_part_time": staff.is_part_time(),
            "sort_order": sort_order
        })

    # Sort by shift time
    result.sort(key=lambda x: (x["sort_order"], x["name"]))
    return result


def render_calendar_native(calendar_data: list[DayInfo], schedule: Optional[MonthlySchedule], year: int, month: int):
    """Render calendar using native Streamlit components."""
    st.subheader(f"{year}年{month}月 シフトカレンダー")

    # Legend
    legend_cols = st.columns(5)
    with legend_cols[0]:
        st.write(":blue[●] 7:30 (早番)")
    with legend_cols[1]:
        st.write(":green[●] 8:00 (通常)")
    with legend_cols[2]:
        st.write(":orange[●] 9:00 (遅番)")
    with legend_cols[3]:
        st.write(":red[[待機]]")
    with legend_cols[4]:
        st.write(":gray[パート]")

    st.divider()

    # Create day lookup
    day_info_map = {d.day: d for d in calendar_data}
    staff_list = get_staff_list()

    # Calendar body (September 2025 starts on Monday)
    day = 1
    for week in range(5):
        cols = st.columns(7)
        for weekday_idx in range(7):
            with cols[weekday_idx]:
                if day <= 30:
                    day_data = day_info_map.get(day)
                    weekday_name = day_data.weekday if day_data else ""

                    # Day header with color based on day type
                    if day_data:
                        if day_data.day_type == DayType.SUNDAY:
                            day_label = f":red[{day} ({weekday_name})]"
                        elif day_data.day_type == DayType.SATURDAY:
                            day_label = f":blue[{day} ({weekday_name})]"
                        elif day_data.day_type == DayType.HOLIDAY:
                            day_label = f":red[{day} ({weekday_name})]"
                        else:
                            day_label = f"{day} ({weekday_name})"
                    else:
                        day_label = str(day)

                    # Use expander for each day
                    if schedule:
                        staff_entries = get_day_staff_list(schedule, day, day_data, staff_list)
                        count = len(staff_entries)
                        expander_label = f"**{day_label}** ({count}名)"

                        with st.expander(expander_label, expanded=False):
                            # Holiday name
                            if day_data and day_data.note:
                                st.caption(f":red[{day_data.note}]")

                            if staff_entries:
                                for entry in staff_entries:
                                    # Format: "名前 時間 [待機]"
                                    standby_mark = " :red[[待機]]" if entry["is_standby"] else ""

                                    if entry["is_part_time"]:
                                        # Part-time: gray color with work hours
                                        st.write(f":gray[{entry['name']} {entry['display_time']}]")
                                    elif entry["shift_type"] == ShiftType.EARLY:
                                        st.write(f":blue[{entry['name']} {entry['display_time']}]{standby_mark}")
                                    elif entry["shift_type"] == ShiftType.NORMAL:
                                        st.write(f":green[{entry['name']} {entry['display_time']}]{standby_mark}")
                                    else:  # LATE
                                        st.write(f":orange[{entry['name']} {entry['display_time']}]{standby_mark}")
                            else:
                                st.caption("勤務者なし")
                    else:
                        # No schedule yet
                        st.markdown(f"**{day_label}**")
                        if day_data and day_data.note:
                            st.caption(f":red[{day_data.note}]")
                        st.caption("-")

                    day += 1
                else:
                    st.write("")  # Empty cell

        # Add separator between weeks
        if week < 4:
            st.divider()


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
        st.sidebar.write(f"**希望休:** {', '.join(map(str, pref_summary['requested_off']))}日")
    if pref_summary["requested_work"]:
        st.sidebar.write(f"**勤務希望:** {', '.join(map(str, pref_summary['requested_work']))}日")
    if pref_summary["standby_unavailable"]:
        st.sidebar.write(f"**待機不可:** {', '.join(map(str, pref_summary['standby_unavailable']))}日")

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
    year = st.session_state.selected_year
    month = st.session_state.selected_month

    render_calendar_native(calendar, schedule, year, month)

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
    staff_map = {s.id: s for s in staff_list}

    # Build DataFrame
    data = []
    for staff in staff_list:
        row = {"スタッフ": staff.name}
        for day_info in calendar:
            assignment = next(
                (a for a in schedule.assignments
                 if a.staff_id == staff.id and a.day == day_info.day),
                None
            )

            if assignment:
                if assignment.shift_type == ShiftType.OFF:
                    text = "休"
                elif assignment.shift_type == ShiftType.EARLY:
                    text = "7:30"
                elif assignment.shift_type == ShiftType.NORMAL:
                    text = "8:00"
                else:
                    text = "9:00"

                if assignment.is_standby:
                    text += "*"
            else:
                text = "-"

            col_name = f"{day_info.day}({day_info.weekday})"
            row[col_name] = text
        data.append(row)

    # Add standby row
    standby_row = {"スタッフ": "【待機担当】"}
    for day_info in calendar:
        standby_id = schedule.standby_assignments.get(day_info.day)
        if standby_id:
            staff = staff_map.get(standby_id)
            name = staff.name if staff else standby_id
        else:
            name = "-"
        col_name = f"{day_info.day}({day_info.weekday})"
        standby_row[col_name] = name
    data.append(standby_row)

    df = pd.DataFrame(data)

    # Display with st.dataframe
    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        height=400
    )

    # Legend
    st.caption("* = 待機担当")

    # Color legend
    legend_cols = st.columns(4)
    with legend_cols[0]:
        st.write(":green[7:30] = 早番")
    with legend_cols[1]:
        st.write(":blue[8:00] = 通常")
    with legend_cols[2]:
        st.write(":violet[9:00] = 遅番")
    with legend_cols[3]:
        st.write("休 = 休日")


def render_statistics_tab():
    """Render the statistics and suggestions tab."""
    st.header("統計・提案")

    schedule = st.session_state.schedule

    if schedule is None:
        st.info("シフトを生成するには、サイドバーの「シフト生成」ボタンをクリックしてください。")
        return

    # Statistics section
    st.subheader("スタッフ別統計")

    # Build statistics DataFrame
    stats_data = []
    for stats in schedule.statistics:
        stats_data.append({
            "スタッフ": stats.staff_name,
            "勤務日数": stats.work_days,
            "休日数": stats.off_days,
            "7:30": stats.early_shifts,
            "8:00": stats.normal_shifts,
            "9:00": stats.late_shifts,
            "待機回数": stats.standby_count,
            "土日祝": stats.weekend_holiday_count,
            "希望休充足": f"{stats.requested_off_fulfilled}/{stats.requested_off_total}"
        })

    stats_df = pd.DataFrame(stats_data)
    st.dataframe(stats_df, use_container_width=True, hide_index=True)

    # Summary metrics
    st.subheader("サマリー")
    metric_cols = st.columns(4)

    total_work_days = sum(s.work_days for s in schedule.statistics)
    avg_work_days = total_work_days / len(schedule.statistics) if schedule.statistics else 0
    total_standby = sum(s.standby_count for s in schedule.statistics)

    with metric_cols[0]:
        st.metric("総勤務日数", total_work_days)
    with metric_cols[1]:
        st.metric("平均勤務日数", f"{avg_work_days:.1f}")
    with metric_cols[2]:
        st.metric("総待機回数", total_standby)
    with metric_cols[3]:
        st.metric("スタッフ数", len(schedule.statistics))

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

    # Validation section
    st.divider()
    render_validation_section(schedule)


def render_validation_section(schedule: MonthlySchedule):
    """Render the shift validation section."""
    st.subheader("🔍 シフト検証")

    # Get required data for validation
    staff_list = get_staff_list()
    calendar = get_september_2025_calendar()
    preferences = st.session_state.preferences
    carryover = get_previous_month_carryover()

    # Run validation
    result = validate_schedule(schedule, staff_list, calendar, preferences, carryover)

    # Summary
    if result.all_passed:
        st.success(f"✅ 全チェック通過: {result.total_checks}項目中 {result.passed_checks}項目 OK")
    else:
        failed = result.total_checks - result.passed_checks
        st.error(f"⚠️ 違反あり: {result.total_checks}項目中 {failed}項目 NG")

    st.divider()

    # Detailed results
    for item in result.items:
        render_validation_item(item)


def render_validation_item(item: ValidationItem, indent: int = 0):
    """Render a single validation item."""
    prefix = "  " * indent

    if item.passed:
        icon = "✅"
        color = "green"
    else:
        icon = "❌"
        color = "red"

    # Main item
    if item.sub_items:
        # Has sub-items, use expander
        with st.expander(f"{icon} {item.name}", expanded=not item.passed):
            for sub_item in item.sub_items:
                render_validation_item(sub_item, indent + 1)
    else:
        # No sub-items, show details
        if item.passed:
            st.write(f"{icon} **{item.name}**: OK")
            if item.details:
                for detail in item.details:
                    st.caption(f"  {detail}")
        else:
            st.write(f"{icon} **:{color}[{item.name}]**: NG")
            for detail in item.details:
                st.write(f"  - :{color}[{detail}]")


def render_preferences_tab():
    """Render the preferences overview tab."""
    st.header("希望休一覧")

    staff_list = get_staff_list()
    calendar = get_september_2025_calendar()

    # Build preferences DataFrame
    pref_data = []
    for staff in staff_list:
        pref_summary = get_staff_preference_summary(staff.id)

        off_list = []
        for day in pref_summary["requested_off"]:
            day_info = next((d for d in calendar if d.day == day), None)
            weekday = day_info.weekday if day_info else ""
            off_list.append(f"{day}日({weekday})")

        work_list = []
        for day in pref_summary["requested_work"]:
            day_info = next((d for d in calendar if d.day == day), None)
            weekday = day_info.weekday if day_info else ""
            work_list.append(f"{day}日({weekday})")

        standby_list = []
        for day in pref_summary["standby_unavailable"]:
            day_info = next((d for d in calendar if d.day == day), None)
            weekday = day_info.weekday if day_info else ""
            standby_list.append(f"{day}日({weekday})")

        pref_data.append({
            "スタッフ": f"{staff.name} ({staff.staff_type.value})",
            "希望休": ", ".join(off_list) if off_list else "-",
            "勤務希望": ", ".join(work_list) if work_list else "-",
            "待機不可": ", ".join(standby_list) if standby_list else "-"
        })

    pref_df = pd.DataFrame(pref_data)
    st.dataframe(pref_df, use_container_width=True, hide_index=True)

    # Legend
    st.divider()
    legend_cols = st.columns(3)
    with legend_cols[0]:
        st.write(":red[希望休] = 休みたい日")
    with legend_cols[1]:
        st.write(":green[勤務希望] = 働きたい日")
    with legend_cols[2]:
        st.write(":orange[待機不可] = 待機できない日")

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
            st.success("シフト生成が完了しました!")
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
    st.caption(f"対象期間: {st.session_state.selected_year}年{st.session_state.selected_month}月")

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
