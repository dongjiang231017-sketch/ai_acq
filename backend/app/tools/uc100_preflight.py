import argparse
import json
from typing import Any

from app.services.telephony_preflight import build_telephony_preflight


STATUS_LABELS = {
    "pass": "PASS",
    "warn": "WARN",
    "fail": "FAIL",
}


def _json_default(value: object) -> str:
    return str(value)


def print_text_report(report: dict[str, Any]) -> None:
    print("UC100 / Asterisk preflight (legacy wrapper; use voice_gateway_preflight for generic delivery)")
    print(f"checkedAt: {report['checkedAt']}")
    print(f"readyForDeviceTest: {report['readyForDeviceTest']}")
    print(f"readyForSingleNumberTest: {report['readyForSingleNumberTest']}")
    print(f"readyForBulkTasks: {report['readyForBulkTasks']}")
    print()
    for step in report["steps"]:
        status = STATUS_LABELS.get(step["status"], step["status"].upper())
        print(f"[{status}] {step['label']}: {step['detail']}")
        if step["action"]:
            print(f"       next: {step['action']}")
    print()
    print(f"nextStep: {report['nextStep']}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Check UC100/Asterisk readiness without placing a real call. Legacy wrapper for the generic voice gateway preflight.")
    parser.add_argument("--phone", help="Optional test phone number for rendering the Asterisk Channel only.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args()

    report = build_telephony_preflight(test_phone=args.phone)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, default=_json_default, indent=2))
    else:
        print_text_report(report)


if __name__ == "__main__":
    main()
