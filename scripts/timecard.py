#!/usr/bin/env python3
"""
Simple Time Card Tracker
Track clock-in and clock-out times for each work day.

Usage:
    python timecard.py clock-in
    python timecard.py clock-out
    python timecard.py status
    python timecard.py history [--days N]
    python timecard.py report [--week | --month]
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta


DATA_FILE = os.path.expanduser("~/.timecard.json")
TIME_FMT = "%Y-%m-%d %H:%M:%S"
DATE_FMT = "%Y-%m-%d"


def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    return {"entries": []}


def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)


def now_str():
    return datetime.now().strftime(TIME_FMT)


def parse_time(ts):
    return datetime.strptime(ts, TIME_FMT)


def format_duration(seconds):
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    return f"{hours}h {minutes:02d}m"


def get_open_entry(data):
    """Return the last entry if it has no clock-out time."""
    if data["entries"]:
        last = data["entries"][-1]
        if last.get("clock_out") is None:
            return last
    return None


def cmd_clock_in(data):
    open_entry = get_open_entry(data)
    if open_entry:
        clocked_in_at = parse_time(open_entry["clock_in"])
        print(f"Already clocked in at {open_entry['clock_in']}.")
        print("Clock out first before clocking in again.")
        return

    ts = now_str()
    entry = {"clock_in": ts, "clock_out": None, "note": None}
    data["entries"].append(entry)
    save_data(data)
    print(f"Clocked in at {ts}")


def cmd_clock_out(data, note=None):
    open_entry = get_open_entry(data)
    if not open_entry:
        print("Not currently clocked in. Use 'clock-in' first.")
        return

    ts = now_str()
    open_entry["clock_out"] = ts
    if note:
        open_entry["note"] = note

    duration = parse_time(ts) - parse_time(open_entry["clock_in"])
    save_data(data)
    print(f"Clocked out at {ts}")
    print(f"Duration: {format_duration(duration.total_seconds())}")


def cmd_status(data):
    open_entry = get_open_entry(data)
    if open_entry:
        elapsed = datetime.now() - parse_time(open_entry["clock_in"])
        print(f"Status:     CLOCKED IN")
        print(f"Since:      {open_entry['clock_in']}")
        print(f"Elapsed:    {format_duration(elapsed.total_seconds())}")
    else:
        print("Status:     CLOCKED OUT")
        # Show last session if any
        completed = [e for e in data["entries"] if e.get("clock_out")]
        if completed:
            last = completed[-1]
            duration = parse_time(last["clock_out"]) - parse_time(last["clock_in"])
            print(f"Last clock-in:  {last['clock_in']}")
            print(f"Last clock-out: {last['clock_out']}")
            print(f"Last duration:  {format_duration(duration.total_seconds())}")


def cmd_history(data, days=7):
    cutoff = datetime.now() - timedelta(days=days)
    entries = [
        e for e in data["entries"]
        if parse_time(e["clock_in"]) >= cutoff
    ]

    if not entries:
        print(f"No entries in the last {days} day(s).")
        return

    # Group by date
    by_date = {}
    for entry in entries:
        date = parse_time(entry["clock_in"]).strftime(DATE_FMT)
        by_date.setdefault(date, []).append(entry)

    print(f"{'Date':<12} {'Clock In':<20} {'Clock Out':<20} {'Duration':<12} {'Note'}")
    print("-" * 80)
    for date in sorted(by_date.keys()):
        day_entries = by_date[date]
        for entry in day_entries:
            clock_in = entry["clock_in"]
            clock_out = entry.get("clock_out") or "(open)"
            note = entry.get("note") or ""
            if entry.get("clock_out"):
                dur = parse_time(entry["clock_out"]) - parse_time(entry["clock_in"])
                duration = format_duration(dur.total_seconds())
            else:
                elapsed = datetime.now() - parse_time(entry["clock_in"])
                duration = format_duration(elapsed.total_seconds()) + " *"
            print(f"{date:<12} {clock_in:<20} {clock_out:<20} {duration:<12} {note}")

        # Daily total
        total_secs = 0
        for entry in day_entries:
            end = parse_time(entry["clock_out"]) if entry.get("clock_out") else datetime.now()
            total_secs += (end - parse_time(entry["clock_in"])).total_seconds()
        print(f"{'':>53} {'Daily total: ' + format_duration(total_secs)}")
        print()


def cmd_report(data, period="week"):
    if period == "week":
        cutoff = datetime.now() - timedelta(days=7)
        label = "Last 7 days"
    elif period == "month":
        cutoff = datetime.now() - timedelta(days=30)
        label = "Last 30 days"
    else:
        cutoff = datetime.now() - timedelta(days=7)
        label = "Last 7 days"

    entries = [
        e for e in data["entries"]
        if parse_time(e["clock_in"]) >= cutoff
    ]

    if not entries:
        print(f"No entries for {label}.")
        return

    total_secs = 0
    days_worked = set()
    sessions = 0
    for entry in entries:
        end = parse_time(entry["clock_out"]) if entry.get("clock_out") else datetime.now()
        total_secs += (end - parse_time(entry["clock_in"])).total_seconds()
        days_worked.add(parse_time(entry["clock_in"]).strftime(DATE_FMT))
        sessions += 1

    avg_secs = total_secs / len(days_worked) if days_worked else 0

    print(f"=== Report: {label} ===")
    print(f"Days worked:      {len(days_worked)}")
    print(f"Sessions:         {sessions}")
    print(f"Total time:       {format_duration(total_secs)}")
    print(f"Average/day:      {format_duration(avg_secs)}")


def main():
    parser = argparse.ArgumentParser(
        description="Simple time card tracker",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")

    # clock-in
    subparsers.add_parser("clock-in", help="Record clock-in time")

    # clock-out
    out_parser = subparsers.add_parser("clock-out", help="Record clock-out time")
    out_parser.add_argument("--note", "-n", help="Optional note for this session")

    # status
    subparsers.add_parser("status", help="Show current clock status")

    # history
    hist_parser = subparsers.add_parser("history", help="Show clock-in/out history")
    hist_parser.add_argument(
        "--days", "-d", type=int, default=7,
        help="Number of days to show (default: 7)"
    )

    # report
    report_parser = subparsers.add_parser("report", help="Show summary report")
    period_group = report_parser.add_mutually_exclusive_group()
    period_group.add_argument("--week", action="store_const", dest="period", const="week",
                              help="Report for last 7 days (default)")
    period_group.add_argument("--month", action="store_const", dest="period", const="month",
                              help="Report for last 30 days")
    report_parser.set_defaults(period="week")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    data = load_data()

    if args.command == "clock-in":
        cmd_clock_in(data)
    elif args.command == "clock-out":
        cmd_clock_out(data, note=getattr(args, "note", None))
    elif args.command == "status":
        cmd_status(data)
    elif args.command == "history":
        cmd_history(data, days=args.days)
    elif args.command == "report":
        cmd_report(data, period=args.period)


if __name__ == "__main__":
    main()
