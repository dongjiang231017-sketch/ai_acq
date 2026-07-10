from __future__ import annotations

import argparse
import asyncio
import re
from pathlib import Path

from google.protobuf.json_format import MessageToDict
from livekit import api


DEFAULT_ENV_KEYS = {
    "REALTIME_CONVERSATION_MODE": "livekit",
    "LIVEKIT_AGENT_MODE": "qwen_omni",
    "LIVEKIT_DEFAULT_COUNTRY_CODE": "raw",
    "LIVEKIT_SIP_WAIT_UNTIL_ANSWERED": "true",
    "LIVEKIT_SIP_KRISP_ENABLED": "false",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bootstrap local self-hosted LiveKit SIP outbound trunk.")
    parser.add_argument("--livekit-url", default="ws://127.0.0.1:7880")
    parser.add_argument("--api-key", default="devkey")
    parser.add_argument("--api-secret", default="devsecret-key-for-ai-acq-local-20260709")
    parser.add_argument("--trunk-address", default="192.168.10.114:5060")
    parser.add_argument("--from-number", default="+8617750280920")
    parser.add_argument("--name", default="ai-acq-local-dinstar-8t")
    parser.add_argument("--write-env", action="store_true")
    parser.add_argument("--env-file", default=str(Path(__file__).resolve().parents[2] / ".env"))
    return parser.parse_args()


async def create_or_reuse_trunk(args: argparse.Namespace) -> str:
    lkapi = api.LiveKitAPI(url=args.livekit_url, api_key=args.api_key, api_secret=args.api_secret)
    try:
        existing = await lkapi.sip.list_sip_outbound_trunk(api.ListSIPOutboundTrunkRequest())
        for item in MessageToDict(existing, preserving_proto_field_name=True).get("items", []):
            if item.get("name") == args.name and item.get("address") == args.trunk_address:
                trunk_id = str(item.get("sip_trunk_id") or "")
                if trunk_id:
                    print(f"复用已有 outbound trunk：{trunk_id}")
                    return trunk_id

        trunk = api.SIPOutboundTrunkInfo(
            name=args.name,
            address=args.trunk_address,
            transport=api.SIPTransport.SIP_TRANSPORT_UDP,
            numbers=[args.from_number],
            metadata='{"route":"local-selfhost","target":"dinstar-8t"}',
        )
        created = await lkapi.sip.create_sip_outbound_trunk(api.CreateSIPOutboundTrunkRequest(trunk=trunk))
        payload = MessageToDict(created, preserving_proto_field_name=True)
        trunk_id = str(payload.get("sip_trunk_id") or payload.get("trunk", {}).get("sip_trunk_id") or "")
        if not trunk_id:
            raise RuntimeError(f"创建 trunk 成功但没有返回 sip_trunk_id：{payload}")
        print(f"已创建 outbound trunk：{trunk_id}")
        return trunk_id
    finally:
        await lkapi.aclose()


def update_env(path: Path, values: dict[str, str]) -> None:
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    found: set[str] = set()
    next_lines: list[str] = []

    for line in lines:
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)=", line)
        if match and match.group(1) in values:
            key = match.group(1)
            next_lines.append(f"{key}={values[key]}")
            found.add(key)
        else:
            next_lines.append(line)

    if next_lines and next_lines[-1].strip():
        next_lines.append("")
    next_lines.append("# Local self-hosted LiveKit")
    for key, value in values.items():
        if key not in found:
            next_lines.append(f"{key}={value}")

    path.write_text("\n".join(next_lines).rstrip() + "\n", encoding="utf-8")


def main() -> None:
    args = parse_args()
    trunk_id = asyncio.run(create_or_reuse_trunk(args))
    if args.write_env:
        env_values = {
            **DEFAULT_ENV_KEYS,
            "LIVEKIT_URL": args.livekit_url,
            "LIVEKIT_API_KEY": args.api_key,
            "LIVEKIT_API_SECRET": args.api_secret,
            "LIVEKIT_SIP_OUTBOUND_TRUNK_ID": trunk_id,
            "LIVEKIT_SIP_FROM_NUMBER": args.from_number,
        }
        update_env(Path(args.env_file), env_values)
        print(f"已更新本地环境文件：{args.env_file}")
    else:
        print("未写入 .env；如需自动切换，请追加 --write-env。")


if __name__ == "__main__":
    main()
