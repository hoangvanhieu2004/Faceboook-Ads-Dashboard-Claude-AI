"""Backend: tính scalar (04_metrics_computed.json) và cube grain ngày (04_cubes.json) từ bảng sạch fb_ads_clean.

Chạy từ thư mục gốc dự án:  python work/compute_cubes.py
"""
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "work"
df = pd.read_csv(ROOT / "01_Union" / "fb_ads_clean.csv")

# ---------- scalar ----------
S = {c: float(df[c].sum()) for c in ["spend", "messages", "impressions", "reach", "link_clicks"]}
scalars = {
    "total_spend": {"value": S["spend"]}, "total_messages": {"value": S["messages"]},
    "total_impressions": {"value": S["impressions"]}, "total_reach": {"value": S["reach"]},
    "total_link_clicks": {"value": S["link_clicks"]},
    "cost_per_msg_all": {"value": S["spend"] / S["messages"]},
    "ctr_all": {"value": S["link_clicks"] / S["impressions"]},
    "cpc_link_all": {"value": S["spend"] / S["link_clicks"]},
}
as_of = df["date"].max()
(WORK / "04_metrics_computed.json").write_text(json.dumps({"as_of": as_of, "scalars": scalars}, ensure_ascii=False, indent=2), encoding="utf-8")

# ---------- cube ----------
DIMS = ["date", "unit", "product", "objective", "adset_type", "campaign", "adset"]
LABEL = {"date": "Ngày", "unit": "Đơn vị chạy", "product": "Dòng sản phẩm", "objective": "Mục tiêu campaign",
         "adset_type": "Loại ad set", "campaign": "Campaign", "adset": "Ad set"}
ORDER = {"unit": ["HEAD", "Q2", "Q7", "BR", "Khác"], "objective": ["Tin nhắn", "Tương tác", "Tiếp cận"], "adset_type": ["Chính", "Thử nghiệm"]}
MCOLS = ["spend", "messages", "impressions", "reach", "link_clicks"]


def values(d):
    vals = df[d].astype(str).unique().tolist()
    if d in ORDER:
        return [v for v in ORDER[d] if v in vals] + sorted(v for v in vals if v not in ORDER[d])
    return sorted(vals)


dims = {d: {"label": LABEL[d], "values": values(d)} for d in DIMS}
idx = {d: {v: i for i, v in enumerate(dims[d]["values"])} for d in DIMS}
g = df.groupby(DIMS, as_index=False)[MCOLS].sum()
cells = []
for r in g.itertuples(index=False):
    row = [idx[d][str(getattr(r, d))] for d in DIMS] + [int(getattr(r, m)) for m in MCOLS]
    if any(row[len(DIMS):]):
        cells.append(row)

SUM = lambda label, fmt, direction=None: {"type": "sum", "label": label, "format": fmt, **({"direction": direction} if direction else {})}
measures = {
    "spend": SUM("Chi tiêu (đ)", "compact"),
    "messages": SUM("Số tin nhắn", "int", "up"),
    "impressions": SUM("Lượt hiển thị", "compact"),
    "reach": SUM("Lượt tiếp cận cộng dồn", "compact"),
    "link_clicks": SUM("Lượt bấm link", "int"),
    "impr_k": {"type": "lincomb", "label": "Nghìn lượt hiển thị", "format": "dec1", "terms": [["impressions", 0.001]]},
    "cost_per_msg": {"type": "ratio", "label": "Chi phí mỗi tin nhắn (đ)", "format": "int", "direction": "down",
                     "num": "spend", "den": "messages", "guard": {"measure": "messages", "min": 5, "zero_label": "chưa có tin nhắn"}},
    "cpm": {"type": "ratio", "label": "CPM (đ)", "format": "int", "direction": "down",
            "num": "spend", "den": "impr_k", "guard": {"measure": "impr_k", "min": 1}},
    "msg_per_k": {"type": "ratio", "label": "Tin nhắn trên 1.000 lượt hiển thị", "format": "dec2", "direction": "up",
                  "num": "messages", "den": "impr_k", "guard": {"measure": "impr_k", "min": 1}},
    "ctr": {"type": "ratio", "label": "CTR link", "format": "pct2", "direction": "up",
            "num": "link_clicks", "den": "impressions", "guard": {"measure": "impressions", "min": 1000}},
    "adset_act_n": {"type": "group_class", "label": "Số ad set cần xử lý", "format": "int", "direction": "down",
                    "dim": "adset", "spend": "spend", "msgs": "messages", "min_msgs": 5, "classes": ["zero", "red"], "agg": "count"},
    "adset_red_spend": {"type": "group_class", "label": "Chi ở nhóm Cắt giảm (đ)", "format": "compact", "direction": "down",
                        "dim": "adset", "spend": "spend", "msgs": "messages", "min_msgs": 5, "classes": ["red"], "agg": "sum"},
    "spend_zero_adset": {"type": "group_zero", "label": "Chi ở ad set 0 tin nhắn (đ)", "format": "compact", "direction": "down",
                         "base": "spend", "zero": "messages", "dim": "adset"},
    "msg_per_click": {"type": "ratio", "label": "Tin nhắn trên mỗi lượt bấm link", "format": "pct", "direction": "up",
                      "num": "messages", "den": "link_clicks", "guard": {"measure": "link_clicks", "min": 10}},
    "cpc_link": {"type": "ratio", "label": "Chi phí mỗi lượt bấm link (đ)", "format": "int", "direction": "down",
                 "num": "spend", "den": "link_clicks", "guard": {"measure": "link_clicks", "min": 10}},
}
out = {"as_of": as_of, "dims": dims, "dim_meta": {"date": {"ordered": True}},
       "measures": measures, "cubes": {"ads": {"dims": DIMS, "measure_cols": MCOLS, "cells": cells}}}
(WORK / "04_cubes.json").write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
print({"as_of": as_of, "cells": len(cells), "dims": {d: len(v["values"]) for d, v in dims.items()},
       "cost_per_msg": round(scalars["cost_per_msg_all"]["value"], 1)})
