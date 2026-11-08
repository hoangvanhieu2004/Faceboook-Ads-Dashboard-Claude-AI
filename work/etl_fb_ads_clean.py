"""Dựng bảng sạch fb_ads_clean từ 00_Raw theo đúng các luật trong 02_cleaning_rules.json.

Chạy:  python work/etl_fb_ads_clean.py
Ghi:   01_Union/fb_ads_clean.csv, work/02_reconcile.json, cập nhật rows_affected trong work/02_cleaning_rules.json
"""
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "00_Raw"
OUT = ROOT / "01_Union" / "fb_ads_clean.csv"
WORK = ROOT / "work"
NAME_RE = re.compile(r"^FB_Ads_Report_(\d{4}-\d{2}-\d{2})( - Copy.*)?\.xlsx$", re.I)
CAMP_RE = re.compile(r"^(\d{2})_(HEAD|Q2|Q7)_(.+)$")
PRODUCT_BY_CODE = {"01": "Embrace of Tana", "03": "Dreamy", "04": "Breezy", "05": "Thiết kế", "07": "Hoa cắt cành",
                   "08": "Daily Flower", "10": "Lan Hồ điệp", "11": "Hỗn hợp", "13": "Campaign mùa vụ"}
OBJECTIVE = {"Messages": "Tin nhắn", "Engagement": "Tương tác", "Reach": "Tiếp cận"}
NUM = {"Spent": "spend", "Impressions": "impressions", "Reach": "reach", "Link clicks": "link_clicks",
       "Messaging": "messages", "Post comments": "comments"}


def unit_product(camp: str):
    """CR-03, CR-04: tách đơn vị chạy và dòng sản phẩm từ tên campaign."""
    m = CAMP_RE.match(camp)
    if m:
        return m.group(2), PRODUCT_BY_CODE.get(m.group(1), m.group(3).strip())
    if camp.startswith("BR_"):
        parts = camp.split("_")
        return "BR", parts[1] if len(parts) > 1 else "Khác"
    if camp.startswith("13_"):
        return "HEAD", "Campaign mùa vụ"
    return "Khác", "Khác"


def main() -> int:
    stats, log = {}, []
    files = sorted((p for p in RAW.glob("*.xlsx") if not p.name.startswith("~$")),
                   key=lambda p: ("copy" in p.stem.lower(), p.name))
    # CR-01: chỉ nhận file đúng mẫu tên; file trùng nội dung với file đã nhận thì bỏ (giữ bản không có chữ Copy)
    seen, frames, dropped_rows, dropped_files = {}, [], 0, []
    for p in files:
        if not NAME_RE.match(p.name):
            log.append(f"bỏ file sai mẫu tên: {p.name}")
            dropped_files.append(p.name)
            continue
        df = pd.read_excel(p, sheet_name=0, dtype={"Ad name": str})
        h = hashlib.md5(pd.util.hash_pandas_object(df, index=False).values.tobytes()).hexdigest()
        if h in seen:
            dropped_rows += len(df); dropped_files.append(p.name)
            log.append(f"bỏ {p.name}: trùng nội dung {seen[h]}")
            continue
        seen[h] = p.name
        df["source_file"] = p.name
        frames.append(df)
    raw = pd.concat(frames, ignore_index=True)
    stats["CR-01"] = dropped_rows

    out = pd.DataFrame({"date": pd.to_datetime(raw["Reporting starts"]).dt.strftime("%Y-%m-%d")})
    out["campaign"] = raw["Campaign name"].astype(str).str.strip()
    # CR-02: chuẩn hoá khoảng trắng tên ad set; nhãn ad set gắn tên campaign để không lẫn giữa campaign
    name = raw["Ad Set Name"].astype(str)
    norm = name.str.replace(r"\s+", " ", regex=True).str.strip()
    stats["CR-02"] = int((norm != name).sum())
    out["adset_name"] = norm
    out["adset"] = norm + " (" + out["campaign"] + ")"
    up = out["campaign"].map(unit_product)
    out["unit"] = up.str[0]
    out["product"] = up.str[1]
    stats["CR-03"] = int((~out["campaign"].str.match(CAMP_RE)).sum())
    stats["CR-04"] = len(out)
    # CR-05: nhãn mục tiêu tiếng Việt
    out["objective"] = raw["Objective"].map(OBJECTIVE).fillna(raw["Objective"])
    stats["CR-05"] = len(out)
    # CR-06: ad set thử nghiệm
    is_test = norm.str.contains("test", case=False)
    out["adset_type"] = is_test.map({True: "Thử nghiệm", False: "Chính"})
    stats["CR-06"] = int(is_test.sum())
    for src, dst in NUM.items():
        out[dst] = pd.to_numeric(raw[src], errors="coerce").fillna(0).astype("int64")
    out["source_file"] = raw["source_file"]
    out = out.sort_values(["date", "campaign", "adset"]).reset_index(drop=True)
    OUT.parent.mkdir(exist_ok=True)
    out.to_csv(OUT, index=False, encoding="utf-8")

    # đối chiếu với tổng có sẵn trong file thô (mỗi ngày đúng 1 file, tổng chỉ số khớp)
    checks = []
    per_day_files = out.groupby("date")["source_file"].nunique()
    bad_days = per_day_files[per_day_files != 1]
    checks.append({"id": "one_file_per_day", "label": "Mỗi ngày đúng một file nguồn sau khi bỏ file trùng",
                   "matched": int((per_day_files == 1).sum()), "total": int(len(per_day_files)),
                   "mismatches": [{"ngày": d, "số file": int(n)} for d, n in bad_days.items()],
                   "impact": "ngày có 2 file khác nội dung sẽ bị cộng đôi mọi chỉ số", "hypothesis": "", "severity": "major"})
    file_dates = {NAME_RE.match(f).group(1) for f in out["source_file"].unique()}
    wrong = out[out.apply(lambda r: NAME_RE.match(r["source_file"]).group(1) != r["date"], axis=1)]
    checks.append({"id": "date_matches_filename", "label": "Ngày báo cáo trong file khớp ngày trong tên file",
                   "matched": int(len(out) - len(wrong)), "total": int(len(out)),
                   "mismatches": wrong[["source_file", "date"]].head(10).to_dict("records"),
                   "impact": "dòng bị xếp sai ngày", "hypothesis": "", "severity": "major"})
    rawsum = raw[list(NUM)].sum()
    cl = out[list(NUM.values())].sum()
    mism = [{"chỉ số": s, "file thô": int(rawsum[s]), "bảng sạch": int(cl[d])} for s, d in NUM.items() if int(rawsum[s]) != int(cl[d])]
    checks.append({"id": "totals", "label": "Tổng Spent, Impressions, Reach, Link clicks, Messaging, Post comments của bảng sạch bằng tổng các file thô đã nhận",
                   "matched": len(NUM) - len(mism), "total": len(NUM), "mismatches": mism,
                   "impact": "mọi chỉ số", "hypothesis": "", "severity": "major"})
    days = pd.to_datetime(pd.Series(sorted(file_dates)))
    missing = pd.date_range(days.min(), days.max()).difference(days)
    checks.append({"id": "no_missing_day", "label": "Không thiếu ngày nào giữa ngày đầu và ngày cuối",
                   "matched": len(days), "total": len(days) + len(missing),
                   "mismatches": [{"ngày thiếu": d.date().isoformat()} for d in missing],
                   "impact": "xu hướng và so kỳ trước bị hụt", "hypothesis": "chưa thả file của ngày đó vào 00_Raw", "severity": "major"})
    (WORK / "02_reconcile.json").write_text(json.dumps({"generated_at": datetime.now().isoformat(timespec="seconds"), "checks": checks},
                                                      ensure_ascii=False, indent=2), encoding="utf-8")
    rp = WORK / "02_cleaning_rules.json"
    if rp.exists():
        rules = json.loads(rp.read_text(encoding="utf-8"))
        for r in rules["rules"]:
            if r["id"] in stats:
                r["rows_affected"] = stats[r["id"]]
        rp.write_text(json.dumps(rules, ensure_ascii=False, indent=2), encoding="utf-8")
    other = out[out["unit"] == "Khác"]["campaign"].unique().tolist()
    print(json.dumps({"rows": len(out), "files_used": len(seen), "dropped_files": dropped_files, "stats": stats,
                      "date_range": [out["date"].min(), out["date"].max()], "unmapped_campaigns": other,
                      "reconcile_ok": all(c["matched"] == c["total"] for c in checks), "log": log}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
