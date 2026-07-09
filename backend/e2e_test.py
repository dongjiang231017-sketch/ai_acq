# ruff: noqa
"""E2E 自动化测试（2026-07-09 需求对齐验收）。跑完自动清理测试数据。"""
import io
import json
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:8001/api"
PASS, FAIL = 0, 0
FAILURES = []


def check(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
    else:
        FAIL += 1
        FAILURES.append(f"{name}: {detail}")


def req(path, method="GET", body=None, token=None, raw=False, form=None):
    url = BASE + path
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = None
    if form is not None:
        boundary = "----e2eboundary"
        parts = []
        for key, (fname, content, ctype) in form.items():
            parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"; filename=\"{fname}\"\r\nContent-Type: {ctype}\r\n\r\n".encode() + content + b"\r\n")
        data = b"".join(parts) + f"--{boundary}--\r\n".encode()
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    elif body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=30) as resp:
        payload = resp.read()
        return resp.status, payload if raw else json.loads(payload or b"{}")


# ---------- 1. 登录 ×10 ----------
token = None
for i in range(10):
    status, data = req("/auth/login", "POST", {"identifier": "test", "password": "test123456"})
    token = data.get("accessToken")
    check(f"login#{i}", status == 200 and bool(token), str(status))

# ---------- 2. 分页接口 ×10 ----------
for i in range(10):
    status, data = req("/leads?page=1&pageSize=20", token=token)
    check(f"leads_page#{i}", status == 200 and set(data) >= {"items", "total", "page", "pageSize"} and len(data["items"]) <= 20, str(status))
    status, data = req("/collections/raw-records?page=1&pageSize=10", token=token)
    check(f"raw_page#{i}", status == 200 and len(data["items"]) <= 10, str(status))
    status, data = req("/collections/runs?page=1&pageSize=10", token=token)
    check(f"runs_page#{i}", status == 200 and "total" in data, str(status))
    status, data = req("/outbound/records?page=1&pageSize=10")
    check(f"records_page#{i}", status == 200 and "total" in data, str(status))

# ---------- 3. 线路状态 ×10 ----------
for i in range(10):
    status, data = req("/outbound/telephony/health")
    check(f"health#{i}", status == 200 and data.get("gatewayMode") == "livekit" and data.get("readyForTestCall") is True, json.dumps(data)[:80])
    status, data = req("/outbound/telephony/preflight")
    check(f"preflight#{i}", status == 200 and data.get("readyForSingleNumberTest") is True, str(status))
status, data = req("/outbound/overview")
check("seats=2", data.get("aiSeats") == 2, str(data.get("aiSeats")))


# ---------- 4. 通话落库链条 ×10（直接调 persist，验证 CallRecord/意向池/工单/勿扰） ----------
from app.db.session import SessionLocal
from app.models.lead import MerchantLead
from app.models.task import CallRecord
from app.models.growth import FollowUpWorkOrder, IntentCustomer, IntentEvent
from app.services.livekit_call_persistence import persist_livekit_call_result
from sqlalchemy import select

E2E_MARK = "E2E测试勿删"
test_lead_ids, test_record_ids = [], []

with SessionLocal() as db:
    owner = db.execute(select(MerchantLead.owner_user_id).limit(1)).scalar()

for i in range(10):
    phone = f"1990000{i:04d}"
    with SessionLocal() as db:
        lead = MerchantLead(
            name=f"E2E测试店{i}", platform="e2e", city="测试市", category="测试", phone=phone,
            source=E2E_MARK, status="待外呼", follow_up_status="未跟进", remark=E2E_MARK,
            owner_user_id=owner, created_by_user_id=owner,
        )
        db.add(lead); db.commit(); test_lead_ids.append(lead.id)
    scenario = ["A", "D", "C", "无效"][i % 4]
    kwargs = dict(
        action_id=f"e2e-{int(time.time())}-{i}", phone=phone, merchant_name=f"E2E测试店{i}",
        task_id=None, lead_id=test_lead_ids[-1], duration_seconds=42,
        transcript=f"AI：您好\n客户：{'可以加微信' if scenario=='A' else '不需要' if scenario=='D' else '嗯' if scenario=='C' else ''}",
        intent_reason="e2e",
    )
    if scenario == "A":
        rid = persist_livekit_call_result(connected=True, intent_level="A", outcome="有意向", refused=False, **kwargs)
    elif scenario == "D":
        rid = persist_livekit_call_result(connected=True, intent_level="D", outcome="拒绝", refused=True, **kwargs)
    elif scenario == "C":
        rid = persist_livekit_call_result(connected=True, intent_level="C", outcome="已接通", refused=False, **kwargs)
    else:
        rid = persist_livekit_call_result(connected=False, intent_level="无效", outcome="未接通", refused=False, **kwargs)
    test_record_ids.append(rid)
    with SessionLocal() as db:
        record = db.get(CallRecord, rid)
        lead = db.get(MerchantLead, test_lead_ids[-1])
        check(f"persist_record#{i}", record is not None and record.lead_id == lead.id, scenario)
        if scenario == "A":
            cust = db.scalar(select(IntentCustomer).where(IntentCustomer.lead_id == lead.id))
            order = cust and db.scalar(select(FollowUpWorkOrder).where(FollowUpWorkOrder.customer_id == cust.id))
            check(f"persist_A_chain#{i}", cust is not None and cust.intent_level == "A" and order is not None and lead.status == "有意向", f"cust={bool(cust)}")
        elif scenario == "D":
            check(f"persist_D_dnc#{i}", lead.status == "勿扰", lead.status)
        elif scenario == "C":
            check(f"persist_C_status#{i}", lead.status == "已拨打", lead.status)
        else:
            check(f"persist_miss#{i}", lead.status == "未接通" and record.gateway_status == "no_answer", lead.status)


# ---------- 5. Excel 导入 ×10（3新+1重+1无效 每轮） ----------
from openpyxl import Workbook

for i in range(10):
    wb = Workbook(); ws = wb.active
    ws.append(["商家名称", "电话", "城市", "类目", "地址"])
    for j in range(3):
        ws.append([f"E2E导入店{i}-{j}", f"1991{i:03d}{j:04d}", "测试市", "餐饮", f"测试路{i}-{j}号"])
    ws.append([f"E2E导入店{i}-0", f"1991{i:03d}0000", "测试市", "餐饮", f"测试路{i}-0号"])  # 与本轮第一条重复
    ws.append(["E2E无效店", "", "测试市", "餐饮", ""])  # 无电话
    buf = io.BytesIO(); wb.save(buf)
    status, data = req("/leads/import-excel", "POST", token=token,
                       form={"file": (f"e2e-{E2E_MARK}.xlsx", buf.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    check(f"excel_import#{i}", status == 200 and data.get("inserted") == 3 and data.get("duplicated") == 1 and data.get("invalid") == 1, json.dumps(data))

# 再导一遍第0轮文件应全部重复
wb = Workbook(); ws = wb.active
ws.append(["商家名称", "电话", "城市", "类目", "地址"])
for j in range(3):
    ws.append([f"E2E导入店0-{j}", f"1991000{j:04d}", "测试市", "餐饮", f"测试路0-{j}号"])
buf = io.BytesIO(); wb.save(buf)
status, data = req("/leads/import-excel", "POST", token=token,
                   form={"file": (f"e2e-{E2E_MARK}.xlsx", buf.getvalue(), "application/octet-stream")})
check("excel_reimport_alldup", status == 200 and data.get("inserted") == 0 and data.get("duplicated") == 3, json.dumps(data))

# ---------- 6. 批量外呼编排（安全空跑：名单全是勿扰 → 跳过不拨号） ----------
from app.models.task import OutreachTask

dnc_lead_ids = []
with SessionLocal() as db:
    for i in range(2):
        lead = MerchantLead(
            name=f"E2E勿扰店{i}", platform="e2e", city="测试市", category="测试", phone=f"19920000{i:03d}",
            source=E2E_MARK, status="勿扰", follow_up_status="已拒绝", remark=E2E_MARK,
            owner_user_id=owner, created_by_user_id=owner,
        )
        db.add(lead); db.flush(); dnc_lead_ids.append(lead.id)
    task = OutreachTask(name=f"E2E批量编排测试-{E2E_MARK}", channel="call", target_count=2,
                        target_lead_ids=",".join(dnc_lead_ids), concurrency=2, status="待启动")
    db.add(task); db.commit(); e2e_task_id = task.id

status, data = req(f"/outbound/tasks/{e2e_task_id}/start", "POST")
check("batch_start_202", status == 200 and data.get("status") in ("运行中", "已完成"), str(status))
deadline = time.time() + 30
final = None
while time.time() < deadline:
    with SessionLocal() as db:
        final = db.get(OutreachTask, e2e_task_id).status
    if final in ("已完成", "部分完成", "异常"):
        break
    time.sleep(2)
check("batch_dnc_skip_completed", final == "已完成", str(final))
with SessionLocal() as db:
    n = db.scalar(select(CallRecord.id).where(CallRecord.task_id == e2e_task_id)) 
check("batch_no_real_dial", n is None, str(n))

# ---------- 7. 报表导出 ×4类型 ----------
for rtype in ("线索明细", "通话记录", "意向客户", "渠道分析"):
    try:
        status, data = req("/reports/exports", "POST", {"reportType": rtype, "dateRange": "近7天", "fileFormat": "xlsx", "requester": "e2e", "includeSensitiveFields": False})
        ok = status == 200 and data.get("downloadUrl")
        if ok:
            status2, raw = req(data["downloadUrl"].replace("/api", ""), raw=True)
            ok = status2 == 200 and raw[:2] == b"PK"
        check(f"report_export_{rtype}", bool(ok), str(status))
    except Exception as exc:
        check(f"report_export_{rtype}", False, str(exc)[:80])

# ---------- 8. 意向池/工单接口反映测试数据 ----------
status, data = req("/intent/customers")
check("intent_customers_api", status == 200 and any("E2E测试店" in c.get("merchantName", "") for c in data), str(len(data) if isinstance(data, list) else data)[:60])
status, data = req("/intent/work-orders")
check("work_orders_api", status == 200 and any("E2E测试店" in o.get("title", "") for o in data), str(status))


# ---------- 清理全部测试数据 ----------
from sqlalchemy import delete, or_

with SessionLocal() as db:
    cust_ids = [c for c in db.scalars(select(IntentCustomer.id).join(MerchantLead, IntentCustomer.lead_id == MerchantLead.id, isouter=True).where(or_(MerchantLead.remark == E2E_MARK, IntentCustomer.merchant_name.like("E2E%")))).all()]
    if cust_ids:
        db.execute(delete(FollowUpWorkOrder).where(FollowUpWorkOrder.customer_id.in_(cust_ids)))
        db.execute(delete(IntentEvent).where(IntentEvent.customer_id.in_(cust_ids)))
        db.execute(delete(IntentCustomer).where(IntentCustomer.id.in_(cust_ids)))
    db.execute(delete(CallRecord).where(CallRecord.gateway_call_id.like("e2e-%")))
    db.execute(delete(OutreachTask).where(OutreachTask.name.like(f"%{E2E_MARK}%")))
    lead_ids = [l for l in db.scalars(select(MerchantLead.id).where(or_(MerchantLead.remark == E2E_MARK, MerchantLead.remark.like(f"%{E2E_MARK}%")))).all()]
    if lead_ids:
        db.execute(delete(IntentEvent).where(IntentEvent.lead_id.in_(lead_ids)))
        db.execute(delete(CallRecord).where(CallRecord.lead_id.in_(lead_ids)))
        db.execute(delete(MerchantLead).where(MerchantLead.id.in_(lead_ids)))
    db.commit()
    leftover = db.scalar(select(MerchantLead.id).where(MerchantLead.remark.like(f"%{E2E_MARK}%")))
    check("cleanup", leftover is None, str(leftover))

print(f"\n===== E2E 结果：PASS {PASS} / FAIL {FAIL} =====")
for f in FAILURES:
    print("  FAIL:", f)
sys.exit(1 if FAIL else 0)
