import logging
from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)


FIELD_LABELS = {
    "body": "请求体",
    "query": "查询参数",
    "path": "路径参数",
    "identifier": "账号或手机号",
    "password": "密码",
    "projectName": "客户/项目",
    "project_name": "客户/项目",
    "companyName": "公司名称",
    "company_name": "公司名称",
    "contactName": "联系人",
    "contact_name": "联系人",
    "contactPhone": "联系人手机号",
    "contact_phone": "联系人手机号",
    "contactEmail": "联系人邮箱",
    "contact_email": "联系人邮箱",
    "desiredUsername": "期望登录名",
    "desired_username": "期望登录名",
    "note": "备注",
    "name": "名称",
    "platform": "平台",
    "city": "城市",
    "category": "品类",
    "phone": "电话",
    "source": "来源",
    "intentScore": "意向分",
    "intent_score": "意向分",
    "status": "状态",
    "targetCount": "目标数量",
    "target_count": "目标数量",
    "scheduledAt": "预约时间",
    "scheduled_at": "预约时间",
}

HTTP_DETAIL_MESSAGES = {
    "Not Found": "接口不存在",
    "Method Not Allowed": "请求方法不支持",
    "Unauthorized": "未登录或登录已过期",
    "Forbidden": "没有权限访问",
    "Internal Server Error": "服务器内部错误，请稍后再试",
}

HTTP_STATUS_MESSAGES = {
    400: "请求参数不正确",
    401: "未登录或登录已过期",
    403: "没有权限访问",
    404: "接口不存在",
    405: "请求方法不支持",
    409: "数据冲突，请检查后重试",
    422: "请求参数不正确",
    500: "服务器内部错误，请稍后再试",
}


def _is_chinese_message(message: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in message)


def _field_label(location: tuple[Any, ...] | list[Any]) -> str:
    parts = [part for part in location if part not in {"body", "query", "path"}]
    if not parts:
        return "请求参数"
    return ".".join(FIELD_LABELS.get(str(part), str(part)) for part in parts)


def _translate_validation_error(error: dict[str, Any]) -> str:
    field = _field_label(error.get("loc", []))
    error_type = str(error.get("type", ""))
    ctx = error.get("ctx") or {}

    if error_type == "missing":
        return f"{field}不能为空"
    if error_type in {"string_too_short", "too_short"}:
        min_length = ctx.get("min_length") or ctx.get("min_length", "")
        return f"{field}长度不能少于{min_length}个字符" if min_length else f"{field}长度太短"
    if error_type in {"string_too_long", "too_long"}:
        max_length = ctx.get("max_length") or ctx.get("max_length", "")
        return f"{field}长度不能超过{max_length}个字符" if max_length else f"{field}长度太长"
    if error_type in {"int_parsing", "int_type"}:
        return f"{field}必须是整数"
    if error_type in {"float_parsing", "float_type"}:
        return f"{field}必须是数字"
    if error_type in {"bool_parsing", "bool_type"}:
        return f"{field}必须是布尔值"
    if error_type == "greater_than_equal":
        return f"{field}不能小于{ctx.get('ge')}"
    if error_type == "greater_than":
        return f"{field}必须大于{ctx.get('gt')}"
    if error_type == "less_than_equal":
        return f"{field}不能大于{ctx.get('le')}"
    if error_type == "less_than":
        return f"{field}必须小于{ctx.get('lt')}"

    message = str(error.get("msg", "")).strip()
    if message and _is_chinese_message(message):
        return message
    return f"{field}格式不正确"


def _http_detail_to_message(detail: Any, status_code: int) -> str:
    if isinstance(detail, str):
        if _is_chinese_message(detail):
            return detail
        return HTTP_DETAIL_MESSAGES.get(detail, HTTP_STATUS_MESSAGES.get(status_code, "请求失败，请稍后再试"))
    if isinstance(detail, list):
        messages = [str(item) for item in detail if item]
        return "；".join(messages) if messages else HTTP_STATUS_MESSAGES.get(status_code, "请求失败，请稍后再试")
    if detail:
        return str(detail)
    return HTTP_STATUS_MESSAGES.get(status_code, "请求失败，请稍后再试")


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    message = _http_detail_to_message(exc.detail, exc.status_code)
    return JSONResponse(status_code=exc.status_code, content={"detail": message})


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    errors = [_translate_validation_error(error) for error in exc.errors()]
    detail = "；".join(errors) if errors else "请求参数不正确"
    return JSONResponse(status_code=422, content={"detail": detail, "errors": errors})


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled server error: %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "服务器内部错误，请稍后再试"})


def setup_exception_handlers(app: Any) -> None:
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
