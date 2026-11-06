#!/usr/bin/env python3
"""Generate the result-comparison screenshot for the online user guide.

The script writes two sample tool-format result CSVs to a temporary
directory, drives the real ResultCompareDialog (load data + run
comparison) without connecting to a remote host, and captures the dialog
window. Run it from the repository root:

    python scripts/generate_result_compare_screenshot.py
"""

import csv
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import tkinter as tk

from PIL import ImageGrab

from log_parser import CSV_FIELDS
from result_compare import ResultCompareDialog


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "docs" / "images"
DATE = "20261106"

# (input_len, output_len, total_req, max_cc, cc)
CASES = [
    (16384, 512, 108, 46, 46),
    (16384, 1024, 108, 45, 45),
    (32768, 512, 54, 23, 23),
    (32768, 1024, 54, 22, 22),
]

BASELINE = {
    "TTFT_avg": (4523.1, 4410.8, 3895.4, 3748.2),
    "TPOT_avg": (12.3, 11.8, 13.1, 12.9),
    "output_throughput": (312.5, 290.1, 201.7, 188.4),
    "qps": (8.5, 7.2, 6.1, 5.4),
    "hbm_hit_rate": (92.3, 92.5, 94.8, 95.0),
    "external_hit_rate": (91.8, 91.6, 95.1, 94.7),
}

OPTIMIZED = {
    "TTFT_avg": (3612.4, 3548.2, 3021.6, 2934.9),
    "TPOT_avg": (11.8, 11.2, 12.5, 12.1),
    "output_throughput": (389.7, 372.4, 253.2, 242.1),
    "qps": (10.4, 9.1, 7.8, 6.9),
    "hbm_hit_rate": (95.8, 96.1, 97.4, 97.2),
    "external_hit_rate": (95.2, 95.5, 97.8, 97.4),
}


def build_row(index: int, case: tuple, core: dict) -> dict:
    """Build one CSV row with plausible derived metrics."""
    input_len, output_len, total_req, max_cc, cc = case
    ttft = core["TTFT_avg"][index]
    tpot = core["TPOT_avg"][index]
    qps = core["qps"][index]
    out_tput = core["output_throughput"][index]
    e2e_time = output_len * tpot / 1000.0  # seconds
    in_tput = qps * input_len
    return {
        "input_len": input_len,
        "output_len": output_len,
        "total_req": total_req,
        "max_cc": max_cc,
        "cc": cc,
        "hbm_hit_rate": core["hbm_hit_rate"][index],
        "external_hit_rate": core["external_hit_rate"][index],
        "TTFT_avg": round(ttft, 1),
        "TTFT_min": round(ttft * 0.62, 1),
        "TTFT_max": round(ttft * 1.80, 1),
        "TTFT_P90": round(ttft * 1.40, 1),
        "TPOT_avg": round(tpot, 1),
        "TPOT_min": round(tpot * 0.72, 1),
        "TPOT_max": round(tpot * 1.55, 1),
        "TPOT_SLO_P90": round(tpot * 1.25, 1),
        "E2E_time": round(e2e_time, 1),
        "output_throughput": round(out_tput, 1),
        "E2E_throughput": round((input_len + output_len) / e2e_time, 1),
        "qps": round(qps, 1),
        "qpm": round(qps * 60, 1),
        "input_token_throughput": round(in_tput, 1),
        "prefill_token_throughput": round(in_tput * 0.92, 1),
        "E2EL_avg": round(e2e_time * 1000, 1),
        "E2EL_min": round(e2e_time * 750, 1),
        "E2EL_max": round(e2e_time * 1500, 1),
        "E2EL_P90": round(e2e_time * 1300, 1),
    }


def write_csv(path: Path, core: dict) -> None:
    """Write a tool-format results CSV accepted by load_result_csv()."""
    rows = [build_row(i, case, core) for i, case in enumerate(CASES)]
    with open(path, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def pump_events(root: tk.Tk, seconds: float) -> None:
    """Keep processing Tk events so delayed chart redraws complete."""
    end = time.time() + seconds
    while time.time() < end:
        root.update_idletasks()
        root.update()
        time.sleep(0.02)


def capture(window: tk.Toplevel, filename: str) -> None:
    """Capture one Tk window to docs/images."""
    window.update_idletasks()
    window.update()
    x = window.winfo_rootx()
    y = window.winfo_rooty()
    width = window.winfo_width()
    height = window.winfo_height()
    path = OUTPUT_DIR / filename
    ImageGrab.grab(bbox=(x, y, x + width, y + height)).save(path)
    print(f"saved {path}")


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    work_dir = Path(tempfile.mkdtemp(prefix="aisbench-compare-"))
    try:
        file_a = work_dir / "results_test_logs_20261106_143000.csv"
        file_b = work_dir / "results_test_logs_20261106_160500.csv"
        write_csv(file_a, BASELINE)
        write_csv(file_b, OPTIMIZED)

        root = tk.Tk()
        root.title("AISBenchPrefixTools")
        root.geometry("300x150+60+50")
        root.attributes("-topmost", True)
        root.update()

        ui = ResultCompareDialog(root)
        ui.dialog.geometry("1180x860+60+50")
        ui.dialog.attributes("-topmost", True)

        ui.file_a_var.set(str(file_a))
        ui.file_b_var.set(str(file_b))
        ui.label_a_var.set("基线v1")
        ui.label_b_var.set("优化后v2")

        ui._load_data()
        assert ui.matches, "sample CSVs failed to match"
        ui._do_compare()
        assert ui.compared, "comparison did not complete"

        # BarChartWidget redraws are scheduled via after(60, ...).
        pump_events(root, 1.0)
        capture(ui.dialog, f"result-compare-{DATE}.png")

        ui.dialog.destroy()
        root.destroy()
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
