"""Main entry point for the hospital shift management system."""
import sys
from pathlib import Path

from .models import FeasibilityError, NoSolutionError
from .data import (
    get_staff_list, get_september_2025_calendar,
    get_merged_staff_preferences, get_previous_month_carryover,
    get_constraints_config
)
from .solver import ShiftScheduler
from .output import generate_all_outputs


def run_scheduler(output_dir: str = "output", time_limit: int = 60) -> bool:
    """
    Run the shift scheduler.

    Args:
        output_dir: Directory for output files
        time_limit: Solver time limit in seconds

    Returns:
        True if successful, False otherwise
    """
    print("=" * 60)
    print("  病院スタッフシフト管理システム")
    print("  2025年9月シフト生成")
    print("=" * 60)
    print()

    # Phase 0: Load data
    print("[Phase 0] データ読み込み中...")
    staff_list = get_staff_list()
    calendar = get_september_2025_calendar()
    preferences = get_merged_staff_preferences()
    carryover = get_previous_month_carryover()
    config = get_constraints_config()

    print(f"  - 正社員: {len([s for s in staff_list if s.is_full_time()])}名")
    print(f"  - パート: {len([s for s in staff_list if s.is_part_time()])}名")
    print(f"  - 対象日数: {len(calendar)}日")
    print()

    # Create scheduler
    scheduler = ShiftScheduler(staff_list, calendar, preferences, carryover, config)

    # Phase 1: Input validation
    print("[Phase 1] 入力データ検証中...")
    validation_errors = scheduler.validate_input()
    if validation_errors:
        print("  入力データに問題があります:")
        for error in validation_errors:
            print(f"    - {error}")
        return False
    print("  入力データ検証完了 ✓")
    print()

    # Phase 2: Feasibility check
    print("[Phase 2] 事前検算中...")
    conflicts = scheduler.check_feasibility()
    if conflicts:
        print("  制約条件に矛盾があります:")
        for conflict in conflicts:
            print(f"    - {conflict}")
        raise FeasibilityError(conflicts)
    print("  事前検算完了 ✓")
    print()

    # Phase 3-5: Build and solve model
    print("[Phase 3-5] モデル構築・最適化中...")
    print(f"  制限時間: {time_limit}秒")
    scheduler.build_model()

    print("  ソルバー実行中...")
    schedule = scheduler.solve(time_limit_seconds=time_limit)

    if schedule is None:
        print("  解が見つかりませんでした")
        raise NoSolutionError("Phase 3-5", "制約を満たす解が存在しません")

    print("  最適化完了 ✓")
    print()

    # Phase 6: Generate outputs
    print("[Phase 6] 出力ファイル生成中...")
    outputs = generate_all_outputs(schedule, staff_list, calendar, output_dir)

    print("  出力ファイル:")
    for output_type, filepath in outputs.items():
        print(f"    - {output_type}: {filepath}")
    print()

    # Print summary
    print("=" * 60)
    print("  生成完了")
    print("=" * 60)
    print()

    # Quick statistics
    full_time_stats = [s for s in schedule.statistics if s.staff_id.startswith("S")]

    print("【正社員集計サマリー】")
    for stats in full_time_stats:
        standby_info = f"待機{stats.standby_count}回" if stats.standby_count > 0 else ""
        print(f"  {stats.staff_name}: 勤務{stats.work_days}日, "
              f"7:30×{stats.early_shifts}, 8:00×{stats.normal_shifts}, "
              f"9:00×{stats.late_shifts}, {standby_info}, "
              f"土日祝{stats.weekend_holiday_count}回")
    print()

    if schedule.constraint_violations:
        print("【制約違反】")
        for violation in schedule.constraint_violations:
            print(f"  - {violation}")
        print()

    if schedule.suggestions:
        print("【改善提案】")
        for suggestion in schedule.suggestions:
            print(f"  - {suggestion}")
        print()

    return True


def main():
    """Main function."""
    import argparse

    parser = argparse.ArgumentParser(
        description="病院スタッフシフト管理システム"
    )
    parser.add_argument(
        "-o", "--output",
        default="output",
        help="出力ディレクトリ (default: output)"
    )
    parser.add_argument(
        "-t", "--time-limit",
        type=int,
        default=60,
        help="ソルバー制限時間（秒） (default: 60)"
    )

    args = parser.parse_args()

    try:
        success = run_scheduler(args.output, args.time_limit)
        sys.exit(0 if success else 1)
    except FeasibilityError as e:
        print(f"\nエラー: {e}")
        sys.exit(2)
    except NoSolutionError as e:
        print(f"\nエラー: {e}")
        sys.exit(3)
    except Exception as e:
        print(f"\n予期しないエラー: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(99)


if __name__ == "__main__":
    main()
