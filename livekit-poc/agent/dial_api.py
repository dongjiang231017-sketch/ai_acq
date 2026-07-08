"""外呼 HTTP 接口——同事系统对接点。

POST /calls  {"phone_number": "18100000000", "merchant_name": "张记烧烤"}
  -> 创建房间、dispatch agent，agent 自己完成拨号
  -> 返回 {"call_id": ..., "room": ...}

GET /calls/{call_id}  -> 读该通电话的打点事件（简单轮询用）

运行：uvicorn dial_api:app --host 0.0.0.0 --port 8100
"""

from __future__ import annotations

import json
import os
import uuid

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from livekit import api

load_dotenv()

app = FastAPI(title="livekit-poc dial api")

AGENT_NAME = "outbound-caller"


class DialRequest(BaseModel):
    phone_number: str
    merchant_name: str = ""


def _lk() -> api.LiveKitAPI:
    return api.LiveKitAPI(
        url=os.getenv("LIVEKIT_URL", "ws://127.0.0.1:7880"),
        api_key=os.getenv("LIVEKIT_API_KEY", ""),
        api_secret=os.getenv("LIVEKIT_API_SECRET", ""),
    )


@app.post("/calls")
async def create_call(req: DialRequest) -> dict:
    phone = req.phone_number.strip()
    if not phone:
        raise HTTPException(400, "phone_number 不能为空")
    call_id = f"lk-{uuid.uuid4().hex[:12]}"
    room = f"call-{call_id}"
    lkapi = _lk()
    try:
        await lkapi.agent_dispatch.create_dispatch(
            api.CreateAgentDispatchRequest(
                agent_name=AGENT_NAME,
                room=room,
                metadata=json.dumps(
                    {
                        "phone_number": phone,
                        "merchant_name": req.merchant_name,
                        "call_id": call_id,
                    },
                    ensure_ascii=False,
                ),
            )
        )
    finally:
        await lkapi.aclose()
    return {"call_id": call_id, "room": room}


@app.get("/calls/{call_id}")
async def get_call(call_id: str) -> dict:
    path = os.path.join(os.getenv("METRICS_DIR", "./metrics_logs"), f"{call_id}.jsonl")
    if not os.path.exists(path):
        raise HTTPException(404, "无此通话或尚未产生事件")
    events = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(json.loads(line))
    return {"call_id": call_id, "events": events}
