# ruff: noqa
"""针对子代理审计发现 bug 的回归测试。跑完自动清理。"""
import sys
from datetime import datetime
from uuid import uuid4

from sqlalchemy import delete, select, func

from app.db.session import SessionLocal
from app.models.collection import LeadCollectionRun, LeadCollectionTask, RawLeadRecord
from app.models.lead import MerchantLead
from app.models.task import CallRecord
from app.services import collection as C
from app.services.livekit_call_persistence import persist_livekit_call_result

PASS, FAIL, FAILURES = 0, 0, []
MARK = "AUDIT_REGRESSION"


def check(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
    else:
        FAIL += 1
        FAILURES.append(f"{name}: {detail}")


with SessionLocal() as db:
    owner = db.execute(select(MerchantLead.owner_user_id).limit(1)).scalar()

# ---- BUG1: 采集快路径新建线索，raw 记录 lead_id 不能是 NULL ----
# ---- BUG2: 超长字段(category>80/name>120)不能让整批崩 ----
for rnd in range(10):
    with SessionLocal() as db:
        task = LeadCollectionTask(name=f"{MARK}任务{rnd}", provider="amap", collection_mode="discovery",
                                  cities=["测试市"], categories=["餐饮"], keywords=["火锅"],
                                  target_per_keyword=5, owner_user_id=owner, created_by_user_id=owner)
        db.add(task); db.flush()
        run = LeadCollectionRun(task_id=task.id, provider="amap", collection_mode="discovery", status="运行中")
        db.add(run); db.commit()
        task_id, run_id = task.id, run.id

    # 造 POI：含一条超长 type(>80) 和超长 name(>120)，验证截断不崩
    pois = [
        {"id": f"{MARK}-{rnd}-{i}", "name": ("超长店名" * 40) if i == 0 else f"审计店{rnd}-{i}",
         "type": ("餐饮服务;中餐厅;" * 20) if i == 1 else "餐饮服务;中餐厅",
         "cityname": "测试市", "adname": "测试区", "address": f"测试路{rnd}-{i}",
         "tel": f"1990{rnd:03d}{i:04d}", "location": "115.1,28.1", "pname": "江西省"}
        for i in range(5)
    ]
    with SessionLocal() as db:
        task = db.get(LeadCollectionTask, task_id); run = db.get(LeadCollectionRun, run_id)
        cache = C._DiscoveryIngestCache(db, owner, "amap")
        try:
            for poi in pois:
                C._record_import_result(db, task=task, run=run, city="测试市", category="餐饮", keyword="火锅", poi=poi, cache=cache)
            db.flush()
            db.commit()
            crashed = False
        except Exception as exc:
            crashed = True
            check(f"bug2_longfield_nocrash#{rnd}", False, str(exc)[:80])
    if not crashed:
        check(f"bug2_longfield_nocrash#{rnd}", True)
        with SessionLocal() as db:
            # 本轮新建线索的 raw 记录 lead_id 必须非空
            raws = db.scalars(select(RawLeadRecord).where(RawLeadRecord.run_id == run_id, RawLeadRecord.import_status == "已入库")).all()
            null_fk = [r for r in raws if r.lead_id is None]
            check(f"bug1_rawrecord_leadid#{rnd}", len(raws) > 0 and not null_fk, f"raws={len(raws)} nullfk={len(null_fk)}")
            # 每条 raw 的 lead_id 真能查到线索
            ok_fk = all(db.get(MerchantLead, r.lead_id) is not None for r in raws)
            check(f"bug1_fk_resolvable#{rnd}", ok_fk, "有raw的lead_id查不到线索")

# ---- persist 幂等：同 action_id 调两次只产生1条 CallRecord ----
for rnd in range(10):
    with SessionLocal() as db:
        lead = MerchantLead(id=uuid4().hex, name=f"{MARK}幂等店{rnd}", platform="audit", city="测试市",
                            category="测试", phone=f"1992{rnd:03d}0000", source=MARK, remark=MARK,
                            status="待外呼", follow_up_status="未跟进", owner_user_id=owner, created_by_user_id=owner)
        db.add(lead); db.commit(); lid = lead.id
    aid = f"audit-idem-{rnd}-{uuid4().hex[:8]}"
    kw = dict(action_id=aid, phone=f"1992{rnd:03d}0000", merchant_name="", task_id=None, lead_id=lid,
              duration_seconds=30, connected=True, intent_level="A", outcome="有意向",
              transcript="AI：加微信吗\n客户：可以", intent_reason="test", refused=False)
    r1 = persist_livekit_call_result(**kw)
    r2 = persist_livekit_call_result(**kw)  # 重复调用
    with SessionLocal() as db:
        n = db.scalar(select(func.count()).select_from(CallRecord).where(CallRecord.gateway_call_id == aid))
    check(f"persist_idempotent#{rnd}", r1 == r2 and n == 1, f"r1==r2:{r1==r2} count:{n}")

# ---- 并发原子计数：10个线程同时对同一task落库，completed/connected/intent 不能丢更新 ----
import threading as _th
from app.models.task import OutreachTask
with SessionLocal() as db:
    t = OutreachTask(name=f"{MARK}并发计数", channel="call", target_count=10, target_lead_ids="",
                     concurrency=8, status="运行中")
    db.add(t); db.commit(); ctask_id = t.id

def _concurrent_persist(idx):
    persist_livekit_call_result(
        action_id=f"audit-concur-{ctask_id}-{idx}", phone=f"1993000{idx:04d}", merchant_name="",
        task_id=ctask_id, lead_id=None, duration_seconds=20, connected=True,
        intent_level="A", outcome="有意向", transcript="x", intent_reason="c", refused=False)

threads = [_th.Thread(target=_concurrent_persist, args=(i,)) for i in range(10)]
for th in threads: th.start()
for th in threads: th.join()
with SessionLocal() as db:
    t = db.get(OutreachTask, ctask_id)
    # 10通并发 A 意向落库：completed/connected/intent 都必须=10（原子自增不丢）
    check("concurrent_completed_count", t.completed_count == 10, str(t.completed_count))
    check("concurrent_connected_count", t.connected_count == 10, str(t.connected_count))
    check("concurrent_intent_count", t.intent_count == 10, str(t.intent_count))
    n_records = db.scalar(select(func.count()).select_from(CallRecord).where(CallRecord.task_id == ctask_id))
    check("concurrent_no_dup_records", n_records == 10, str(n_records))

# ---- 唯一索引真实存在：手动插入重复 gateway_call_id 必须被拒 ----
from sqlalchemy.exc import IntegrityError
dup_ok = False
with SessionLocal() as db:
    aid = f"audit-uniq-{uuid4().hex[:8]}"
    db.add(CallRecord(merchant_name="u1", gateway_call_id=aid, outcome="已接通")); db.commit()
    try:
        db.add(CallRecord(merchant_name="u2", gateway_call_id=aid, outcome="已接通")); db.commit()
    except IntegrityError:
        db.rollback(); dup_ok = True
    db.execute(delete(CallRecord).where(CallRecord.gateway_call_id == aid)); db.commit()
check("gateway_call_id_unique_enforced", dup_ok, "重复gateway_call_id没被拒")

# ---- 清理 ----
with SessionLocal() as db:
    from app.models.growth import IntentCustomer, IntentEvent, FollowUpWorkOrder
    cids = list(db.scalars(select(IntentCustomer.id).where(IntentCustomer.merchant_name.like(f"{MARK}%"))))
    if cids:
        db.execute(delete(FollowUpWorkOrder).where(FollowUpWorkOrder.customer_id.in_(cids)))
        db.execute(delete(IntentEvent).where(IntentEvent.customer_id.in_(cids)))
        db.execute(delete(IntentCustomer).where(IntentCustomer.id.in_(cids)))
    db.execute(delete(CallRecord).where(CallRecord.gateway_call_id.like("audit-idem-%")))
    db.execute(delete(CallRecord).where(CallRecord.gateway_call_id.like("audit-concur-%")))
    db.execute(delete(OutreachTask).where(OutreachTask.name.like(f"{MARK}%")))
    lids = list(db.scalars(select(MerchantLead.id).where(MerchantLead.remark == MARK)))
    run_ids = list(db.scalars(select(LeadCollectionRun.id).join(LeadCollectionTask).where(LeadCollectionTask.name.like(f"{MARK}%"))))
    task_ids = list(db.scalars(select(LeadCollectionTask.id).where(LeadCollectionTask.name.like(f"{MARK}%"))))
    # raw records by run
    if run_ids:
        db.execute(delete(RawLeadRecord).where(RawLeadRecord.run_id.in_(run_ids)))
    # collected leads (审计店 from discovery)
    disc_lids = list(db.scalars(select(MerchantLead.id).where(MerchantLead.remark.like("采集关键词%"), MerchantLead.city == "测试市", MerchantLead.name.like("%审计%"))))
    disc_lids += list(db.scalars(select(MerchantLead.id).where(MerchantLead.city == "测试市", MerchantLead.name.like("超长店名%"))))
    for x in set(lids + disc_lids):
        db.execute(delete(IntentEvent).where(IntentEvent.lead_id == x))
        db.execute(delete(CallRecord).where(CallRecord.lead_id == x))
        db.execute(delete(RawLeadRecord).where(RawLeadRecord.lead_id == x))
    if set(lids+disc_lids):
        db.execute(delete(MerchantLead).where(MerchantLead.id.in_(set(lids+disc_lids))))
    if run_ids:
        db.execute(delete(LeadCollectionRun).where(LeadCollectionRun.id.in_(run_ids)))
    if task_ids:
        db.execute(delete(LeadCollectionTask).where(LeadCollectionTask.id.in_(task_ids)))
    db.commit()
    leftover = db.scalar(select(func.count()).select_from(RawLeadRecord).where(RawLeadRecord.source_poi_id.like(f"{MARK}%")))
    check("cleanup", leftover == 0, str(leftover))

print(f"\n===== 审计回归：PASS {PASS} / FAIL {FAIL} =====")
for f in FAILURES:
    print("  FAIL:", f)
sys.exit(1 if FAIL else 0)
