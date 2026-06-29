from fastapi import APIRouter

router = APIRouter()

MODULES = [
    {"key": "dashboard", "name": "实时工作台", "description": "监控今日获客、外呼、私信和预警。", "pageCount": 4, "status": "ready"},
    {"key": "collector", "name": "线索采集", "description": "采集任务、来源配置、清洗规则。", "pageCount": 5, "status": "ready"},
    {"key": "leads", "name": "商家线索库", "description": "商家资料、电话库、主页和去重审核。", "pageCount": 5, "status": "ready"},
    {"key": "outbound", "name": "AI外呼系统", "description": "外呼任务、话术流程、通话记录。", "pageCount": 6, "status": "ready"},
    {"key": "dm", "name": "平台私信系统", "description": "平台个人号、私信任务、模板和会话。", "pageCount": 6, "status": "ready"},
    {"key": "intent", "name": "意向客户池", "description": "客户分级、工单跟进和分配规则。", "pageCount": 4, "status": "ready"},
    {"key": "learning", "name": "AI学习中心", "description": "建议队列、知识库和实验结果。", "pageCount": 5, "status": "ready"},
    {"key": "voice", "name": "声音档案", "description": "授权、音色训练和使用记录。", "pageCount": 4, "status": "ready"},
    {"key": "reports", "name": "数据报表", "description": "渠道、绩效和导出中心。", "pageCount": 4, "status": "ready"},
    {"key": "settings", "name": "系统设置", "description": "线路、账号、模型 API、权限和审计。", "pageCount": 6, "status": "ready"},
]


@router.get("")
def list_modules() -> list[dict[str, str | int]]:
    return MODULES
