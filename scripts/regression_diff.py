#!/usr/bin/env python3
"""
Compare two regression-dump snapshots, file by file.

Usage:
    # 1. Dump baseline before refactor.
    python scripts/regression_dump.py --mode baseline

    # 2. After refactor, dump current state.
    python scripts/regression_dump.py --mode current

    # 3. Compare.
    python scripts/regression_diff.py

Exit code:
    0 if every file is byte-identical
    1 if anything differs (prints a per-file unified diff)
"""

import argparse
import difflib
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _list_files(dir_path):
    if not os.path.isdir(dir_path):
        return set()
    return {f for f in os.listdir(dir_path) if f.endswith(".json")}


def _read(path):
    with open(path) as fh:
        return fh.read().splitlines(keepends=True)


def diff_modes(baseline, current, max_lines_per_file=50):
    base_dir = os.path.join(ROOT, "explanation_test", "golden", baseline)
    curr_dir = os.path.join(ROOT, "explanation_test", "golden", current)
    base_files = _list_files(base_dir)
    curr_files = _list_files(curr_dir)

    missing = sorted(base_files - curr_files)
    added = sorted(curr_files - base_files)
    shared = sorted(base_files & curr_files)

    changed = []
    for name in shared:
        a = _read(os.path.join(base_dir, name))
        b = _read(os.path.join(curr_dir, name))
        if a != b:
            diff = list(difflib.unified_diff(
                a, b, fromfile=f"{baseline}/{name}", tofile=f"{current}/{name}", n=2,
            ))
            changed.append((name, diff))

    if not missing and not added and not changed:
        print(f"All {len(shared)} moments match {baseline} → {current}.")
        return 0

    print(f"DIFF: {baseline} → {current}")
    print(f"  shared: {len(shared)}, changed: {len(changed)}, added: {len(added)}, missing: {len(missing)}")
    if missing:
        print(f"  Missing in '{current}': {missing}")
    if added:
        print(f"  New in '{current}': {added}")
    for name, diff in changed:
        print()
        print(f"--- {name} ---")
        head = diff[:max_lines_per_file]
        sys.stdout.writelines(head)
        if len(diff) > max_lines_per_file:
            print(f"  ... ({len(diff) - max_lines_per_file} more diff lines) ...")
    return 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", default="baseline")
    parser.add_argument("--current", default="current")
    parser.add_argument("--max-lines", type=int, default=50)
    args = parser.parse_args()
    sys.exit(diff_modes(args.baseline, args.current, args.max_lines))


if __name__ == "__main__":
    main()
