"""Streamlit Web UI for Hospital Shift Scheduling System."""
import calendar
import io
from datetime import date

import pandas as pd
import streamlit as st

from src.data import (
    get_staff_list,
    get_september_2025_calendar,
    get_merged_staff_preferences,
    get_previous_month_carryover,
    get_constraints_config,
)
from src.models import (
    Staff,
    StaffType,
    DayInfo,
    DayType,
    StaffPreferences,
    ShiftType,
    MonthlySchedule,
)
from src.solver import ShiftScheduler

# ページ設定
st.set_page_config(
    page_title="シフト管理システム",
    page_icon="📅",
    layout="wide",
)

st.title("病院スタッフ シフト管理システム")


def generate_calendar(year: int, month: int) -> list[DayInfo]:
    """指定年月のカレンダーを生成する。"""
    # 9月2025年はサンプルデータを使用
    if year == 2025 and month == 9:
        return get_september_2025_calendar()

    # それ以外は動的に生成
    weekdays = ["月", "火", "水", "木", "金", "土", "日"]
    cal = []

    # その月の日数を取得
    _, num_days = calendar.monthrange(year, month)

    # 1日の曜日を取得 (0=月曜, 6=日曜)
    first_weekday = date(year, month, 1).weekday()

    for day in range(1, num_days + 1):
        weekday_index = (first_weekday + day - 1) % 7
        weekday = weekdays[weekday_index]

        if weekday_index == 5:  # 土曜
            day_type = DayType.SATURDAY
        elif weekday_index == 6:  # 日曜
            day_type = DayType.SUNDAY
        else:
            day_type = DayType.WEEKDAY

        cal.append(DayInfo(day=day, weekday=weekday, day_type=day_type, note=""))

    return cal


def init_session_state():
    """セッション状態を初期化する。"""
    if "staff_list" not in st.session_state:
        st.session_state.staff_list = get_staff_list()

    if "preferences" not in st.session_state:
        st.session_state.preferences = get_merged_staff_preferences()

    if "schedule" not in st.session_state:
        st.session_state.schedule = None

    if "year" not in st.session_state:
        st.session_state.year = 2025

    if "month" not in st.session_state:
        st.session_state.month = 9


def render_sidebar():
    """サイドバーを描画する。"""
    st.sidebar.header("設定")

    # 年月選択
    col1, col2 = st.sidebar.columns(2)
    with col1:
        st.session_state.year = st.selectbox(
            "年",
            options=[2024, 2025, 2026],
            index=1,
            key="year_select"
        )
    with col2:
        st.session_state.month = st.selectbox(
            "月",
            options=list(range(1, 13)),
            index=st.session_state.month - 1,
            key="month_select"
        )

    st.sidebar.divider()

    # スタッフ情報
    st.sidebar.subheader("スタッフ一覧")
    full_time = [s for s in st.session_state.staff_list if s.is_full_time()]
    part_time = [s for s in st.session_state.staff_list if s.is_part_time()]

    st.sidebar.markdown(f"**正社員**: {len(full_time)}名")
    for s in full_time:
        st.sidebar.text(f"  {s.id}: {s.name}")

    st.sidebar.markdown(f"**パート**: {len(part_time)}名")
    for s in part_time:
        st.sidebar.text(f"  {s.id}: {s.name} ({s.work_hours})")


def render_preferences_editor():
    """希望休編集フォームを描画する。"""
    st.subheader("希望休の編集")

    year = st.session_state.year
    month = st.session_state.month
    cal = generate_calendar(year, month)
    num_days = len(cal)

    # スタッフごとの希望休を編集
    full_time = [s for s in st.session_state.staff_list if s.is_full_time()]

    cols = st.columns(3)

    for i, staff in enumerate(full_time):
        with cols[i % 3]:
            pref = st.session_state.preferences.get(
                staff.id,
                StaffPreferences(staff_id=staff.id)
            )

            current_off = ",".join(str(d) for d in pref.requested_off) if pref.requested_off else ""

            new_off = st.text_input(
                f"{staff.name} の希望休 (カンマ区切り)",
                value=current_off,
                key=f"off_{staff.id}",
                placeholder="例: 1,5,10"
            )

            # 入力値をパース
            if new_off.strip():
                try:
                    days = [int(d.strip()) for d in new_off.split(",") if d.strip()]
                    days = [d for d in days if 1 <= d <= num_days]

                    if staff.id not in st.session_state.preferences:
                        st.session_state.preferences[staff.id] = StaffPreferences(staff_id=staff.id)
                    st.session_state.preferences[staff.id].requested_off = sorted(set(days))
                except ValueError:
                    st.error(f"{staff.name}: 数値をカンマ区切りで入力してください")
            else:
                if staff.id in st.session_state.preferences:
                    st.session_state.preferences[staff.id].requested_off = []


def run_solver():
    """ソルバーを実行してシフトを生成する。"""
    year = st.session_state.year
    month = st.session_state.month

    cal = generate_calendar(year, month)
    config = get_constraints_config()
    carryover = get_previous_month_carryover() if (year == 2025 and month == 9) else []

    scheduler = ShiftScheduler(
        staff_list=st.session_state.staff_list,
        calendar=cal,
        preferences=st.session_state.preferences,
        carryover=carryover,
        config=config,
    )

    # 入力検証
    errors = scheduler.validate_input()
    if errors:
        for err in errors:
            st.error(err)
        return None

    # 実行可能性チェック
    conflicts = scheduler.check_feasibility()
    if conflicts:
        for conflict in conflicts:
            st.warning(conflict)

    # モデル構築と解決
    scheduler.build_model()
    schedule = scheduler.solve(time_limit_seconds=30)

    return schedule


def schedule_to_dataframe(schedule: MonthlySchedule, cal: list[DayInfo], staff_list: list[Staff]) -> pd.DataFrame:
    """スケジュールをDataFrameに変換する。"""
    staff_by_id = {s.id: s for s in staff_list}

    data = []
    for day_info in cal:
        day = day_info.day
        row = {
            "日付": day,
            "曜日": day_info.weekday,
            "種別": day_info.day_type.value,
        }

        for staff in staff_list:
            assignment = next(
                (a for a in schedule.assignments if a.staff_id == staff.id and a.day == day),
                None
            )
            if assignment:
                val = str(assignment.shift_type)
                if assignment.is_standby:
                    val += "*"
                row[staff.name] = val
            else:
                row[staff.name] = ""

        # 待機担当
        standby_id = schedule.standby_assignments.get(day)
        if standby_id and standby_id in staff_by_id:
            row["待機"] = staff_by_id[standby_id].name
        else:
            row["待機"] = "-"

        data.append(row)

    return pd.DataFrame(data)


def style_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """DataFrameにスタイルを適用する。"""
    def highlight_cell(val):
        if val == "休":
            return "background-color: #e0e0e0; color: #666;"
        elif val == "7:30":
            return "background-color: #fff3cd;"
        elif val == "8:00":
            return "background-color: #d4edda;"
        elif "9:00" in str(val):
            return "background-color: #cce5ff;"
        return ""

    def highlight_row(row):
        if row["種別"] in ["土曜", "日曜", "祝日"]:
            return ["background-color: #f8d7da;"] * len(row)
        return [""] * len(row)

    return df.style.applymap(highlight_cell).apply(highlight_row, axis=1)


def render_schedule():
    """シフト表を描画する。"""
    st.subheader("シフト生成")

    col1, col2 = st.columns([1, 4])
    with col1:
        if st.button("シフトを生成", type="primary", use_container_width=True):
            with st.spinner("シフトを生成中..."):
                schedule = run_solver()
                if schedule:
                    st.session_state.schedule = schedule
                    st.success("シフト生成が完了しました")
                else:
                    st.error("シフトの生成に失敗しました。制約条件を確認してください。")

    if st.session_state.schedule:
        schedule = st.session_state.schedule
        year = st.session_state.year
        month = st.session_state.month
        cal = generate_calendar(year, month)

        st.markdown(f"### {year}年{month}月 シフト表")

        # DataFrame に変換
        df = schedule_to_dataframe(schedule, cal, st.session_state.staff_list)

        # 週単位で表示
        tabs = st.tabs(["第1週", "第2週", "第3週", "第4週", "第5週", "全体"])

        weeks = [
            (1, 7),
            (8, 14),
            (15, 21),
            (22, 28),
            (29, len(cal)),
        ]

        for i, (start, end) in enumerate(weeks):
            with tabs[i]:
                week_df = df[(df["日付"] >= start) & (df["日付"] <= end)]
                st.dataframe(
                    week_df,
                    use_container_width=True,
                    hide_index=True,
                )

        with tabs[5]:
            st.dataframe(df, use_container_width=True, hide_index=True, height=600)

        # CSVダウンロード
        st.divider()
        csv_buffer = io.StringIO()
        df.to_csv(csv_buffer, index=False, encoding="utf-8")
        csv_data = csv_buffer.getvalue()

        st.download_button(
            label="CSVダウンロード",
            data=csv_data,
            file_name=f"shift_{year}_{month:02d}.csv",
            mime="text/csv",
        )

        # 統計情報
        render_statistics(schedule)


def render_statistics(schedule: MonthlySchedule):
    """統計情報を描画する。"""
    st.markdown("### 統計情報")

    if not schedule.statistics:
        st.info("統計情報がありません")
        return

    # スタッフ別統計
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
            "土日祝出勤": stats.weekend_holiday_count,
        })

    stats_df = pd.DataFrame(stats_data)
    st.dataframe(stats_df, use_container_width=True, hide_index=True)

    # 提案
    if schedule.suggestions:
        st.markdown("### 改善提案")
        for suggestion in schedule.suggestions:
            st.info(suggestion)


def main():
    """メイン関数。"""
    init_session_state()
    render_sidebar()

    # タブで切り替え
    tab1, tab2 = st.tabs(["希望休の編集", "シフト生成・表示"])

    with tab1:
        render_preferences_editor()

    with tab2:
        render_schedule()


if __name__ == "__main__":
    main()
