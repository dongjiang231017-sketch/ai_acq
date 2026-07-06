from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.api.delivery import create_voice_gateway_device_discovery
from app.core.security import hash_password
from app.db.session import Base
from app.models.audit import AuditLog
from app.models.delivery import VoiceGatewayDeviceDiscovery, VoiceGatewayLine, VoiceGatewayLineEvent
from app.schemas.delivery import VoiceGatewayDeviceDiscoveryCreate
from app.models.user import User
from app.services.voice_gateway_delivery import (
    VoiceGatewayRedeliveryError,
    find_assigned_line_for_device,
    find_redelivery_discovery_for_line,
    redeliver_voice_gateway_line,
)


DEVICE_MAC = "F8:A0:3D:48:87:5A"
DEVICE_SERIAL = "db27-4200-1200-0132"


def main() -> None:
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(
        bind=engine,
        tables=[
            User.__table__,
            VoiceGatewayLine.__table__,
            VoiceGatewayDeviceDiscovery.__table__,
            VoiceGatewayLineEvent.__table__,
            AuditLog.__table__,
        ],
    )
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    with TemporaryDirectory() as tmpdir:
        asterisk_path = Path(tmpdir) / "pjsip_ai_acq_delivery_dynamic.conf"
        reloads: list[str] = []

        def fake_reload() -> str:
            reloads.append("reload")
            return "fake pjsip reload ok"

        with Session() as db:
            admin = _user("admin", "后台管理员", is_superuser=True)
            test_owner = _user("test_delivery", "测试账号")
            scan_customer = _user("scan_customer", "扫描客户")
            customer_a = _user("customer_a", "正式客户A")
            customer_b = _user("customer_b", "正式客户B")
            customer_c = _user("customer_c", "正式客户C")
            customer_d = _user("customer_d", "正式客户D")
            db.add_all([admin, test_owner, scan_customer, customer_a, customer_b, customer_c, customer_d])
            db.flush()

            source_line = _line(test_owner, "测试账号 8T", "sip_test_old", "tg_test_old", status="验收通过")
            db.add(source_line)
            db.flush()
            source_discovery = _discovery(test_owner, matched_line_id=source_line.id, status="matched")
            db.add(source_discovery)
            db.commit()

            api_discovery = create_voice_gateway_device_discovery(
                VoiceGatewayDeviceDiscoveryCreate.model_validate(
                    {
                        "deviceAdminUrl": "http://192.168.10.114/",
                        "deviceIp": "192.168.10.114",
                        "deviceMac": DEVICE_MAC,
                        "deviceSerial": DEVICE_SERIAL,
                        "gatewayProfileKey": "dinstar_8t_server",
                        "gatewayLabel": "鼎信 8T 多卡网关",
                        "sipPort": 5060,
                        "status": "found",
                        "summary": "api scan discovered occupied gateway",
                    }
                ),
                db=db,
                current_user=scan_customer,
            )
            assert api_discovery.status == "待转移"
            assert db.scalar(select(func.count()).select_from(VoiceGatewayLine)) == 1

            discovery_a = _discovery(customer_a, status="found")
            db.add(discovery_a)
            db.flush()
            occupied_line = find_assigned_line_for_device(db, discovery_a, exclude_owner_user_id=customer_a.id)
            assert occupied_line and occupied_line.id == source_line.id, "new customer scan must detect old owner occupancy"

            placeholder_a = _line(customer_a, "自动占位 8T", "sip_placeholder_a", "tg_placeholder_a", status="待设备注册")
            db.add(placeholder_a)
            db.flush()
            placeholder_discovery_a = _discovery(customer_a, matched_line_id=placeholder_a.id, status="matched")
            db.add(placeholder_discovery_a)
            db.flush()

            found_discovery = find_redelivery_discovery_for_line(db, source_line, target_owner_user_id=customer_a.id)
            assert found_discovery and found_discovery.id == discovery_a.id, "target discovery should be found by MAC/serial"
            result_a = redeliver_voice_gateway_line(
                db,
                source_line,
                found_discovery,
                customer_a,
                actor_user_id=admin.id,
                password="FirstRedeliveryPass01",
                sync_asterisk=True,
                asterisk_path=asterisk_path,
                reload_callback=fake_reload,
            )
            db.commit()
            assert result_a.previous_owner_user_id == test_owner.id
            assert source_line.owner_user_id == customer_a.id
            assert source_line.sip_username.startswith("sip_customer_a_")
            assert source_line.trunk_name.startswith("tg_customer_a_")
            assert source_line.registration_status == "待重新注册"
            assert discovery_a.matched_line_id == source_line.id
            assert discovery_a.status == "matched"
            assert source_discovery.status == "transferred"
            assert placeholder_a.status == "已合并停用"
            assert placeholder_a.device_mac == ""
            assert len(reloads) == 1
            pjsip_text = asterisk_path.read_text(encoding="utf-8")
            assert "FirstRedeliveryPass01" in pjsip_text
            assert source_line.sip_username in pjsip_text
            assert "sip_test_old" not in pjsip_text

            discovery_b = _discovery(customer_b, status="found")
            db.add(discovery_b)
            db.flush()
            result_b = redeliver_voice_gateway_line(
                db,
                source_line,
                discovery_b,
                customer_b,
                actor_user_id=admin.id,
                password="SecondRedeliveryPass02",
                sync_asterisk=True,
                asterisk_path=asterisk_path,
                reload_callback=fake_reload,
            )
            db.commit()
            assert result_b.previous_owner_user_id == customer_a.id
            assert source_line.owner_user_id == customer_b.id
            assert source_line.sip_username.startswith("sip_customer_b_")
            assert discovery_a.status == "transferred"
            assert discovery_b.status == "matched"
            assert len(reloads) == 2
            pjsip_text = asterisk_path.read_text(encoding="utf-8")
            assert "SecondRedeliveryPass02" in pjsip_text
            assert "FirstRedeliveryPass01" not in pjsip_text

            mismatch_discovery = _discovery(customer_c, status="found")
            db.add(mismatch_discovery)
            db.flush()
            try:
                redeliver_voice_gateway_line(
                    db,
                    source_line,
                    mismatch_discovery,
                    customer_d,
                    actor_user_id=admin.id,
                    password="MismatchedDiscoveryPass03",
                    sync_asterisk=False,
                )
            except VoiceGatewayRedeliveryError:
                db.rollback()
            else:
                raise AssertionError("discovery from another customer must not be accepted")

            discovery_d = _discovery(customer_d, status="found")
            db.add(discovery_d)
            db.flush()

            def failing_reload() -> str:
                reloads.append("failed-reload")
                raise RuntimeError("simulated reload failure")

            try:
                redeliver_voice_gateway_line(
                    db,
                    source_line,
                    discovery_d,
                    customer_d,
                    actor_user_id=admin.id,
                    password="RollbackPassword04",
                    sync_asterisk=True,
                    asterisk_path=asterisk_path,
                    reload_callback=failing_reload,
                )
            except RuntimeError:
                db.rollback()
            else:
                raise AssertionError("reload failure should abort redelivery")
            db.refresh(source_line)
            pjsip_text = asterisk_path.read_text(encoding="utf-8")
            assert source_line.owner_user_id == customer_b.id
            assert "SecondRedeliveryPass02" in pjsip_text
            assert "RollbackPassword04" not in pjsip_text

            active_duplicate_c = _line(customer_c, "已验收同设备", "sip_active_dup", "tg_active_dup", status="验收通过")
            discovery_c = _discovery(customer_c, status="found")
            db.add_all([active_duplicate_c, discovery_c])
            db.flush()
            reload_count_before_blocked_transfer = len(reloads)
            try:
                redeliver_voice_gateway_line(
                    db,
                    source_line,
                    discovery_c,
                    customer_c,
                    actor_user_id=admin.id,
                    password="ShouldNotWrite03",
                    sync_asterisk=True,
                    asterisk_path=asterisk_path,
                    reload_callback=fake_reload,
                )
            except VoiceGatewayRedeliveryError:
                db.rollback()
            else:
                raise AssertionError("active duplicate should block automatic redelivery")
            assert len(reloads) == reload_count_before_blocked_transfer, "blocked transfer must not reload/write Asterisk"
            assert "ShouldNotWrite03" not in asterisk_path.read_text(encoding="utf-8")

            orphan_line = _line(test_owner, "无设备身份线路", "sip_orphan", "tg_orphan", status="待配置")
            orphan_line.device_mac = ""
            orphan_line.device_serial = ""
            orphan_line.device_admin_url = ""
            db.add(orphan_line)
            db.flush()
            assert find_redelivery_discovery_for_line(db, orphan_line) is None

            inactive_line = _line(test_owner, "已停用旧设备", "sip_inactive", "tg_inactive", status="已合并停用")
            inactive_line.device_mac = "AA:BB:CC:DD:EE:FF"
            inactive_line.device_serial = "inactive-device-serial"
            inactive_line.device_admin_url = "http://192.168.10.200/"
            inactive_discovery = _discovery(customer_a, status="found")
            inactive_discovery.device_mac = inactive_line.device_mac
            inactive_discovery.device_serial = inactive_line.device_serial
            inactive_discovery.device_admin_url = inactive_line.device_admin_url
            inactive_discovery.device_ip = "192.168.10.200"
            db.add_all([inactive_line, inactive_discovery])
            db.flush()
            assert find_assigned_line_for_device(db, inactive_discovery, exclude_owner_user_id=customer_a.id) is None
            assert db.scalar(select(func.count()).select_from(VoiceGatewayLineEvent)) >= 2

    print("voice gateway redelivery smoke passed")


def _user(username: str, display_name: str, *, is_superuser: bool = False) -> User:
    return User(
        username=username,
        display_name=display_name,
        email=f"{username}@example.test",
        password_hash=hash_password("test-password"),
        status="启用",
        is_superuser=is_superuser,
    )


def _line(owner: User, line_name: str, sip_username: str, trunk_name: str, *, status: str) -> VoiceGatewayLine:
    return VoiceGatewayLine(
        owner_user_id=owner.id,
        line_name=line_name,
        customer_name=owner.display_name,
        status=status,
        gateway_profile_key="dinstar_8t_server",
        gateway_label="鼎信 8T 多卡网关",
        gateway_vendor="Dinstar/鼎信",
        gateway_model="8T GSM/LTE VoIP Gateway",
        gateway_category="multi_sim_lte_gateway",
        deployment_mode="server",
        sip_server_host="101.132.63.159",
        sip_server_port=5060,
        sip_transport="UDP",
        sip_username=sip_username,
        sip_auth_username=sip_username,
        sip_password_hash=hash_password("old-password"),
        sip_password_secret_alias=f"voice-gateway/{owner.id}/{trunk_name}/sip-password",
        trunk_name=trunk_name,
        channel_count=8,
        device_admin_url="http://192.168.10.114/",
        device_mac=DEVICE_MAC,
        device_serial=DEVICE_SERIAL,
        registration_status="已注册" if status == "验收通过" else "待注册",
        route_status="通过" if status == "验收通过" else "待检查",
        sim_status="正常" if status == "验收通过" else "待检查",
        rtp_status="通过" if status == "验收通过" else "待检查",
        acceptance_status="验收通过" if status == "验收通过" else "待单号验收",
    )


def _discovery(owner: User, *, status: str, matched_line_id: str | None = None) -> VoiceGatewayDeviceDiscovery:
    return VoiceGatewayDeviceDiscovery(
        owner_user_id=owner.id,
        matched_line_id=matched_line_id,
        status=status,
        source="desktop_client_discovery",
        gateway_profile_key="dinstar_8t_server",
        gateway_label="鼎信 8T 多卡网关",
        device_admin_url="http://192.168.10.114/",
        device_ip="192.168.10.114",
        device_mac=DEVICE_MAC,
        device_serial=DEVICE_SERIAL,
        sip_port=5060,
        summary="smoke discovered gateway",
    )


if __name__ == "__main__":
    main()
