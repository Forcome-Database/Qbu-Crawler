"""
模拟测试报告生成：使用外部 products.db 生成邮件正文、PDF、Excel
用法: uv run python scripts/test_report_generation.py
"""

import os
import sys
from pathlib import Path

# ── 1. 配置：指向外部数据库 ──────────────────────────
DB_DIR = r"C:\Users\leo\Desktop\新建文件夹 (5)"
OUTPUT_DIR = Path(DB_DIR) / "test-reports"
OUTPUT_DIR.mkdir(exist_ok=True)

os.environ["QBU_DATA_DIR"] = DB_DIR
os.environ["REPORT_DIR"] = str(OUTPUT_DIR)

# 确保项目根在 sys.path
PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# ── 2. 导入（必须在设置环境变量之后） ──────────────────
from qbu_crawler import config
from qbu_crawler.server import report, report_analytics, report_llm, report_pdf
from qbu_crawler.server.report_snapshot import generate_full_report_from_snapshot
from qbu_crawler import models

print(f"DB_PATH:    {config.DB_PATH}")
print(f"REPORT_DIR: {config.REPORT_DIR}")
print(f"OUTPUT_DIR: {OUTPUT_DIR}")
print()

# 补建可能缺失的表和索引
models.init_db()
print("init_db() 完成\n")

# ── 3. 查询数据并构造 snapshot ────────────────────────
# 数据时间范围: 2026-04-01，使用一个宽泛的窗口
DATA_SINCE = "2026-04-01T00:00:00+08:00"
DATA_UNTIL = "2026-04-02T00:00:00+08:00"
LOGICAL_DATE = "2026-04-01"

products, reviews = report.query_report_data(since=DATA_SINCE, until=DATA_UNTIL)
print(f"查询到 {len(products)} 个产品, {len(reviews)} 条评论")

if not products:
    print("[ERROR] 无产品数据，请检查数据库和时间范围")
    sys.exit(1)

# 统计翻译情况
translated = sum(1 for r in reviews if r.get("translate_status") == "done")
untranslated = len(reviews) - translated
print(f"已翻译: {translated}, 未翻译: {untranslated}")

# 手动构造 snapshot（模拟 freeze_report_snapshot 的输出）
import hashlib, json
snapshot_data = {"products": products, "reviews": reviews}
snapshot_hash = hashlib.sha1(json.dumps(snapshot_data, default=str, sort_keys=True).encode()).hexdigest()[:12]

snapshot = {
    "run_id": 9999,
    "logical_date": LOGICAL_DATE,
    "data_since": DATA_SINCE,
    "data_until": DATA_UNTIL,
    "snapshot_at": config.now_shanghai().isoformat(),
    "snapshot_hash": snapshot_hash,
    "products_count": len(products),
    "reviews_count": len(reviews),
    "translated_count": translated,
    "untranslated_count": untranslated,
    "products": products,
    "reviews": reviews,
}

# ── 4. 标签分类 + 分析 ────────────────────────────────
print("\n=== 标签分类 ===")
report_analytics.sync_review_labels(snapshot)

print("=== 构建分析 ===")
analytics = report_analytics.build_report_analytics(snapshot)

print("=== LLM 分析（当前为规则模式）===")
llm_result = report_llm.run_llm_report_analysis(snapshot, analytics)
validated = report_llm.validate_findings(snapshot, analytics, llm_result)
analytics = report_llm.merge_final_analytics(analytics, llm_result, validated)

# 保存 analytics JSON
analytics_path = OUTPUT_DIR / f"test-analytics-{LOGICAL_DATE}.json"
analytics_path.write_text(json.dumps(analytics, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
print(f"[OK] Analytics 已保存: {analytics_path}")

# 打印关键 KPI
kpis = analytics.get("kpis", {})
print(f"   产品数: {kpis.get('product_count', 'N/A')}")
print(f"   新评论: {kpis.get('ingested_review_rows', 'N/A')}")
print(f"   负面评论: {kpis.get('negative_review_rows', 'N/A')}")
print(f"   自有风险产品: {len(analytics.get('self', {}).get('risk_products', []))}")

# ── 5. 生成 Excel ─────────────────────────────────────
print("\n=== 生成 Excel ===")
excel_path = report.generate_excel(
    products,
    reviews,
    output_path=str(OUTPUT_DIR / f"test-report-{LOGICAL_DATE}.xlsx"),
)
print(f"[OK] Excel 已保存: {excel_path}")

# ── 6. 生成 PDF ───────────────────────────────────────
print("\n=== 生成 PDF ===")
pdf_output = str(OUTPUT_DIR / f"test-report-{LOGICAL_DATE}.pdf")
try:
    pdf_path = report_pdf.generate_pdf_report(snapshot, analytics, pdf_output)
    print(f"[OK] PDF 已保存: {pdf_path}")
except Exception as e:
    print(f"[WARN] PDF 生成失败: {e}")
    print("   （需要安装 Playwright: uv run playwright install chromium）")
    pdf_path = None

# ── 7. 生成邮件正文 ───────────────────────────────────
print("\n=== 生成邮件正文 ===")
subject, body = report.build_daily_deep_report_email(snapshot, analytics)

email_subject_path = OUTPUT_DIR / f"test-email-subject-{LOGICAL_DATE}.txt"
email_body_path = OUTPUT_DIR / f"test-email-body-{LOGICAL_DATE}.txt"
email_subject_path.write_text(subject, encoding="utf-8")
email_body_path.write_text(body, encoding="utf-8")
print(f"[OK] 邮件主题: {subject}")
print(f"[OK] 邮件主题已保存: {email_subject_path}")
print(f"[OK] 邮件正文已保存: {email_body_path}")

# ── 8. 汇总 ──────────────────────────────────────────
print("\n" + "=" * 60)
print("[DONE] 测试报告生成完成！")
print("=" * 60)
print(f"  输出目录: {OUTPUT_DIR}")
print(f"  Analytics: {analytics_path.name}")
print(f"  Excel:     {Path(excel_path).name}")
if pdf_path:
    print(f"  PDF:       {Path(pdf_path).name}")
print(f"  邮件主题:  {email_subject_path.name}")
print(f"  邮件正文:  {email_body_path.name}")
print()
print("邮件正文预览（前 500 字）:")
print("-" * 40)
print(body[:500])
