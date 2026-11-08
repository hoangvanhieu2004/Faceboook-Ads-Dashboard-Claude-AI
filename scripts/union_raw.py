"""Gộp (union) mọi file Excel trong 00_Raw thành 1 bảng duy nhất.

Chạy lại mỗi khi thêm file mới vào 00_Raw:
    python scripts/union_raw.py

Quy tắc:
- Đọc mọi *.xlsx trong 00_Raw (bỏ file tạm ~$...).
- Kiểm tra header: file nào khác cấu trúc chuẩn thì báo lỗi và bỏ qua.
- Chống trùng mức file: file có nội dung giống hệt file khác (vd "... - Copy.xlsx") bị bỏ.
- Cảnh báo nếu 1 ngày có nhiều file KHÁC nội dung (không tự chọn, giữ cả hai để bạn xử lý).
- Bỏ cột rỗng hoàn toàn (col1, col2); "Ad name" giữ dạng chuỗi để không mất chữ số ID.
- Thêm cột source_file để truy vết.
Đầu ra: 01_Union/fb_ads_union.csv (UTF-8 có BOM, mở được bằng Excel) + union_log.txt
"""
import hashlib
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "00_Raw"
OUT_DIR = ROOT / "01_Union"
OUT_CSV = OUT_DIR / "fb_ads_union.csv"
OUT_LOG = OUT_DIR / "union_log.txt"

EXPECTED_COLS = [
    "Reporting starts", "Campaign name", "Ad Set Name", "Ad name", "Objective",
    "Reach", "Impressions", "Frequency", "Spent", "CTR (link click-through rate)",
    "CPC (All) (VND)", "CPM (cost per 1,000 impressions) (VND)",
    "Cost per 1,000 people reached (VND)", "Conversions", "Conversion values",
    "Cost per conversion", "Post comments", "Link clicks", "Messaging", "col1", "col2",
]
DROP_IF_EMPTY = ["col1", "col2"]


def main() -> int:
    log = []
    say = lambda m: (log.append(m), print(m))

    # File tên có "copy" xếp sau để luôn giữ bản gốc khi trùng nội dung
    files = sorted((p for p in RAW_DIR.glob("*.xlsx") if not p.name.startswith("~$")),
                   key=lambda p: ("copy" in p.stem.lower(), p.name))
    say(f"Tìm thấy {len(files)} file trong {RAW_DIR}")

    frames, seen_hash = [], {}
    for f in files:
        df = pd.read_excel(f, sheet_name=0, dtype={"Ad name": str})
        if list(df.columns) != EXPECTED_COLS:
            say(f"  [BỎ] {f.name}: header khác chuẩn -> {list(df.columns)}")
            continue
        h = hashlib.md5(pd.util.hash_pandas_object(df, index=False).values.tobytes()).hexdigest()
        if h in seen_hash:
            say(f"  [BỎ] {f.name}: trùng nội dung với {seen_hash[h]}")
            continue
        seen_hash[h] = f.name
        df["source_file"] = f.name
        frames.append(df)

    if not frames:
        say("Không có dữ liệu hợp lệ.")
        return 1

    data = pd.concat(frames, ignore_index=True)
    data["Reporting starts"] = pd.to_datetime(data["Reporting starts"]).dt.date

    # Cảnh báo 1 ngày đến từ nhiều file khác nhau
    per_day = data.groupby("Reporting starts")["source_file"].nunique()
    for day, n in per_day[per_day > 1].items():
        srcs = sorted(data.loc[data["Reporting starts"] == day, "source_file"].unique())
        say(f"  [CẢNH BÁO] Ngày {day} có {n} file khác nội dung: {srcs}")

    # Cảnh báo ngày bị thiếu trong chuỗi
    days = pd.to_datetime(pd.Series(sorted(per_day.index)))
    missing = pd.date_range(days.min(), days.max()).difference(days)
    if len(missing):
        say(f"  [CẢNH BÁO] Thiếu ngày: {[d.date().isoformat() for d in missing]}")

    dup_rows = data.drop(columns="source_file").duplicated().sum()
    if dup_rows:
        say(f"  [CẢNH BÁO] {dup_rows} dòng trùng y hệt nhau (giữ nguyên, chưa xoá)")

    for c in DROP_IF_EMPTY:
        if data[c].isna().all():
            data = data.drop(columns=c)

    data = data.sort_values(["Reporting starts", "Campaign name", "Ad Set Name", "Ad name"])
    OUT_DIR.mkdir(exist_ok=True)
    data.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")

    say(f"Đã gộp {len(frames)} file -> {len(data)} dòng, {data.shape[1]} cột")
    say(f"Khoảng ngày: {days.min().date()} -> {days.max().date()} ({len(per_day)} ngày)")
    say(f"Ghi ra: {OUT_CSV}")
    OUT_LOG.write_text(f"Chạy lúc {datetime.now():%Y-%m-%d %H:%M:%S}\n" + "\n".join(log) + "\n",
                       encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
