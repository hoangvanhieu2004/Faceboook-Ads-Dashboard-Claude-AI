"""Làm mới dashboard FB Ads sau khi thả file báo cáo mới vào 00_Raw.

Chạy:  python refresh_dashboard.py            (làm mới đầy đủ, gồm kiểm tra bằng trình duyệt)
       python refresh_dashboard.py --fast     (bỏ interaction check và chụp ảnh, nhanh hơn; render check vẫn chạy)
       python refresh_dashboard.py --publish  (làm mới rồi đăng lên https://fbads-dashboard.vercel.app; chỉ đăng khi cổng QC mở)

Thứ tự (bước nào lỗi thì dừng, dashboard cũ giữ nguyên):
 1. ETL: ghép 00_Raw thành 01_Union/fb_ads_clean.csv theo luật đã duyệt, đối chiếu tổng với file thô.
 2. Tính cube, validate số và cube.
 3. Cập nhật spec: dòng 'Dữ liệu tới', khoảng ngày mặc định (7 ngày trọn gần nhất), các nút chọn nhanh, danh sách file nguồn.
 4. Kiểm công thức, build dashboard.html (dừng nếu cấu trúc spec khác bản PRD đã duyệt).
 5. Render check (+ interaction check, chụp ảnh nếu không --fast), bảng kiểm toán, metrics log, nhật ký QC.
Không đổi định nghĩa chỉ số, luật làm sạch hay bố cục: những thay đổi đó phải qua duyệt PRD.
"""
import json
import os
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WORK = ROOT / "work"
RAW = ROOT / "00_Raw"
SKILL = Path(os.environ.get("DASHBOARD_SKILL_DIR", r"C:\Users\HIEU\AppData\Local\Claude-Data\claude_pzs8sxrjxfjjc\local-agent-mode-sessions"
                            r"\skills-plugin\c0e7873b-0818-4d26-a0b6-9c3e77955392\272f8c2e-c367-47c8-ae68-64fe60f361ae\skills\dashboard-workflow"))
SC = SKILL / "scripts"
TITLE = "FB Ads: chi phí mỗi tin nhắn"
ENV = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
PY = sys.executable


def run(step, args, allow_fail=False, quiet=False):
    print(f"\n== {step}")
    r = subprocess.run([PY, *map(str, args)], cwd=ROOT, env=ENV, capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = (r.stdout or "").strip()
    if out and not quiet:
        print(out[-1500:])
    if r.returncode != 0 and not allow_fail:
        print((r.stderr or "").strip()[-2000:])
        sys.exit(f"\nDỪNG ở bước: {step} (mã thoát {r.returncode}). Dashboard cũ giữ nguyên.")
    return r


def dmy(d):
    return d.strftime("%d/%m/%Y")


def update_spec(as_of: date):
    """Chỉ đổi phần trình bày theo ngày: dòng 'Dữ liệu tới', khoảng ngày mặc định, nút chọn nhanh. Không đổi cấu trúc đã duyệt."""
    p = WORK / "03_dashboard_spec.json"
    s = json.loads(p.read_text(encoding="utf-8"))
    iso = lambda d: d.isoformat()  # noqa: E731
    d7, d14, m1 = as_of - timedelta(days=6), as_of - timedelta(days=13), as_of.replace(day=1)
    s["as_of_label"] = f"Dữ liệu tới {dmy(as_of)}"
    for f in s["filters"]:
        if f.get("type") == "date_range":
            f["default"] = {"from": iso(d7), "to": iso(as_of)}
            f["presets"] = [{"label": "7 ngày trọn gần nhất", "from": iso(d7), "to": iso(as_of)},
                            {"label": "14 ngày gần nhất", "from": iso(d14), "to": iso(as_of)},
                            {"label": f"Tháng {as_of.strftime('%m/%Y')} (tới nay)", "from": iso(m1), "to": iso(as_of)}]
    p.write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")
    # danh sách file nguồn cho gói kiểm toán (không thuộc cấu trúc đã duyệt)
    rp = WORK / "02_cleaning_rules.json"
    r = json.loads(rp.read_text(encoding="utf-8"))
    files = sorted(x.name for x in RAW.glob("*.xlsx") if not x.name.startswith("~$"))
    for t in r["clean_tables"]:
        t["sources"] = [f"{n}: Data" for n in files]
    rp.write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Spec: Dữ liệu tới {dmy(as_of)}, mặc định {dmy(d7)}-{dmy(as_of)}; {len(files)} file nguồn.")


def merge_ic():
    R = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(WORK.glob("06_ic_s*.json"))]
    ic = {"passed": len(R) == 3 and all(r["passed"] for r in R), "steps": sum(r["steps"] for r in R), "seeds": sum((r["seeds"] for r in R), []),
          "issues": sum((r["issues"] for r in R), [])[:30], "js_errors": sum((r["js_errors"] for r in R), [])[:10],
          "skipped_actions": sum((r["skipped_actions"] for r in R), [])[:20]}
    (WORK / "06_interaction_check.json").write_text(json.dumps(ic, ensure_ascii=False, indent=2), encoding="utf-8")
    return ic


def main():
    fast = "--fast" in sys.argv
    t0 = datetime.now()
    if not SC.exists():
        sys.exit(f"Không thấy thư mục skill dashboard-workflow: {SKILL}. Đặt biến môi trường DASHBOARD_SKILL_DIR.")

    # 1. ETL (kèm bảng gộp thô 01_Union/fb_ads_union.csv cho ai cần mở bằng Excel)
    if (ROOT / "scripts" / "union_raw.py").exists():
        run("1a. Gộp thô (fb_ads_union.csv)", [ROOT / "scripts" / "union_raw.py"], allow_fail=True, quiet=True)
    r = run("1. Ghép và làm sạch dữ liệu thô", [WORK / "etl_fb_ads_clean.py"], quiet=True)
    etl = json.loads(r.stdout[r.stdout.index("{"):])
    print(f"{etl['rows']} dòng, {etl['files_used']} file, ngày {etl['date_range'][0]} tới {etl['date_range'][1]}; bỏ: {etl['dropped_files'] or 'không'}")
    warn = []
    if etl.get("unmapped_campaigns"):
        warn.append(f"Campaign mới không theo quy ước tên, đang xếp vào Đơn vị và Dòng sản phẩm 'Khác': {etl['unmapped_campaigns']}. Báo builder để thêm ánh xạ (cần duyệt lại luật CR-03, CR-04).")
    if not etl.get("reconcile_ok"):
        rec = json.loads((WORK / "02_reconcile.json").read_text(encoding="utf-8"))
        for c in rec["checks"]:
            if c["matched"] != c["total"]:
                warn.append(f"Đối chiếu dữ liệu lệch: {c['label']}: {c['mismatches'][:5]}")
        for w in warn:
            print("CẢNH BÁO:", w)
        sys.exit("\nDỪNG: dữ liệu thô chưa sạch (xem cảnh báo trên). Sửa file trong 00_Raw (ví dụ xoá file trùng ngày) rồi chạy lại. Dashboard cũ giữ nguyên.")
    as_of = date.fromisoformat(etl["date_range"][1])

    # 2. cube và validate
    update_spec(as_of)
    run("2a. Kiểm luật làm sạch", [SC / "check_cleaning.py", "work/"], quiet=True)
    run("2b. Tính cube", [WORK / "compute_cubes.py"])
    run("2c. Validate số tổng", [SC / "validate_numbers.py", "01_Union", "work/02_data_contract.json", "work/04_metrics_computed.json", "work/04_validation_report.json"])
    run("2d. Validate cube", [SC / "validate_cube.py", "01_Union", "work/02_data_contract.json", "work/04_cubes.json", "work/04_cube_validation.json"])

    # 3. build
    run("3a. Kiểm công thức", [SC / "check_spec_metrics.py", "work/"])
    run("3b. Build dashboard", [SC / "build_html.py", "work/04_cubes.json", "work/03_dashboard_spec.json", "work/dashboard.html", TITLE])

    # 4. kiểm (chạy song song)
    print("\n== 4. Kiểm số trên màn hình" + ("" if fast else ", tương tác và chụp ảnh (song song)"))
    for f in ["06_render_check.json", "06_interaction_check.json"] + [p.name for p in WORK.glob("06_ic_s*.json")]:
        (WORK / f).unlink(missing_ok=True)
    procs = [subprocess.Popen([PY, SC / "render_check.py", "work/dashboard.html", "work/06_render_check.json"], cwd=ROOT, env=ENV,
                              stdout=open(WORK / "06_render.log", "w", encoding="utf-8"), stderr=subprocess.STDOUT)]
    if not fast:
        for s in (1, 2, 3):
            procs.append(subprocess.Popen([PY, SC / "interaction_check.py", "work/dashboard.html", f"work/06_ic_s{s}.json", "40", str(s)], cwd=ROOT, env=ENV,
                                          stdout=open(WORK / f"06_ic_s{s}.log", "w", encoding="utf-8"), stderr=subprocess.STDOUT))
        procs.append(subprocess.Popen([PY, SC / "screenshot.py", "work/dashboard.html", "work/shots/"], cwd=ROOT, env=ENV,
                                      stdout=open(WORK / "06_shot.log", "w", encoding="utf-8"), stderr=subprocess.STDOUT))
    for p in procs:
        p.wait()
    rc_path = WORK / "06_render_check.json"
    if not rc_path.exists():
        sys.exit("DỪNG: render check không ghi báo cáo, xem work/06_render.log.")
    rc = json.loads(rc_path.read_text(encoding="utf-8"))
    print(f"Render check: {'pass' if rc['passed'] else 'FAIL'}, {rc['states_checked']} trạng thái, {rc['n_errors']} lỗi")
    if not fast:
        ic = merge_ic()
        print(f"Interaction check: {'pass' if ic['passed'] else 'FAIL'}, {ic['steps']} thao tác")
        if not ic["passed"]:
            sys.exit(f"DỪNG: interaction check fail: {ic['issues'][:3]} {ic['js_errors'][:2]}")
    if not rc["passed"]:
        sys.exit(f"DỪNG: render check fail: {rc['errors'][:3]} {rc['console_errors'][:2]}")

    # 5. bảng kiểm toán, metrics log, QC
    run("5a. Bảng kiểm toán", [SC / "build_audit_tables.py", "work/", "00_Raw"], quiet=True)
    run("5b. Metrics log", [SC / "build_metrics_log.py", "work/", "--html", "work/dashboard.html"], allow_fail=True, quiet=True)
    q = run("5c. Nhật ký QC (cổng giao)", [SC / "build_qc_log.py", "work/"], allow_fail=True, quiet=True)
    gate_open = q.returncode == 0

    # 6. đăng lên Vercel (chỉ khi gọi --publish, mọi kiểm tra pass và cổng QC mở)
    published = None
    if "--publish" in sys.argv:
        if not gate_open:
            print("\nKHÔNG đăng lên Vercel: cổng QC đang chặn.")
        elif not (ROOT / "deploy" / ".vercel").exists():
            print("\nKHÔNG đăng lên Vercel: thư mục deploy chưa liên kết project (chạy 'npx vercel deploy deploy --prod' một lần).")
        else:
            import shutil
            shutil.copyfile(WORK / "dashboard.html", ROOT / "deploy" / "index.html")
            npx = shutil.which("npx") or r"C:\Program Files\nodejs\npx.cmd"
            print("\n== 6. Đăng lên Vercel")
            d = subprocess.run([npx, "vercel", "deploy", "--cwd", "deploy", "--prod", "--yes"], cwd=ROOT, env=ENV, capture_output=True, text=True, encoding="utf-8", errors="replace")
            published = d.returncode == 0
            print(((d.stdout or "") + (d.stderr or "")).strip()[-600:])

    print("\n================ KẾT QUẢ ================")
    if published is not None:
        print(f"Vercel: {'đã đăng, https://fbads-dashboard.vercel.app' if published else 'LỖI khi đăng, xem log phía trên'}")
    print(f"Dashboard: {WORK / 'dashboard.html'}  (dữ liệu tới {dmy(as_of)}, mặc định xem 7 ngày tới ngày này)")
    print(f"Cổng giao QC: {'MỞ' if gate_open else 'CHẶN, xem qc_dashboard/qc_log.md'}")
    print("Gói kiểm toán đã sinh lại: dữ liệu đổi nên các câu QA cũ thành 'Không kiểm được' tới khi chạy lại kiểm toán.")
    print("Trang Nhận định và đề xuất: số đi qua token tự cập nhật; câu chữ nhận định viết theo dữ liệu tới 20/10/2026, nên viết lại khi xu hướng đổi.")
    for w in warn:
        print("CẢNH BÁO:", w)
    print(f"Thời gian: {(datetime.now() - t0).seconds} giây")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
