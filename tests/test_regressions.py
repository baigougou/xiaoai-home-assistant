import asyncio
import logging

import pytest
from fastapi import HTTPException

from xiaoai_ha_bridge.config.config import (
    AppConfig,
    BridgeConfig,
    CommandConfig,
    HomeAssistantConfig,
    TTSConfig,
    XiaomiSpeakerConfig,
)
from xiaoai_ha_bridge.engine.interceptor import CommandInterceptor
from xiaoai_ha_bridge.engine import interceptor as interceptor_module
from xiaoai_ha_bridge.web import routes
from xiaoai_ha_bridge.logging.logger import setup_logging


def build_config() -> AppConfig:
    return AppConfig(
        home_assistant=HomeAssistantConfig(url="http://ha.local:8123", api_token="token"),
        xiaomi_speakers=[XiaomiSpeakerConfig(entity_id="media_player.speaker")],
        bridge=BridgeConfig(),
        commands={
            "kids_ac": CommandConfig(
                name="小孩房空调",
                entity_id="climate.kids_ac",
                device_type="climate",
                keywords=["小孩房空调"],
            )
        },
        tts=TTSConfig(enabled=False),
    )


class FakeDiscoveryClient:
    def __init__(self, config):
        self.closed = False

    async def test_connection(self):
        return True

    async def discover_devices_for_bridge(self):
        return {"climate": {"label": "空调", "items": []}}

    async def close(self):
        self.closed = True


def test_discover_devices_uses_module_client(monkeypatch):
    monkeypatch.setattr(routes.config_manager, "load", lambda: build_config())
    monkeypatch.setattr(routes, "HomeAssistantClient", FakeDiscoveryClient)

    result = asyncio.run(routes.discover_devices())

    assert result["success"] is True
    assert result["live"] is True


class FakeCommandClient:
    def __init__(self, service_success=True):
        self.service_success = service_success
        self.turn_on_calls = 0

    async def turn_on_ac(self, entity_id):
        self.turn_on_calls += 1
        return self.service_success

    async def get_state(self, entity_id, quiet=False):
        state = "on" if self.service_success else "off"
        return {"entity_id": entity_id, "state": state, "attributes": {}}


def test_climate_turn_on_calls_home_assistant_once():
    client = FakeCommandClient(service_success=True)
    interceptor = CommandInterceptor(build_config(), client)

    handled = asyncio.run(interceptor.intercept("打开小孩房空调"))

    assert handled is True
    assert client.turn_on_calls == 1


def test_failed_climate_service_is_not_reported_as_handled():
    client = FakeCommandClient(service_success=False)
    interceptor = CommandInterceptor(build_config(), client)

    handled = asyncio.run(interceptor.intercept("打开小孩房空调"))

    assert handled is False


def test_execute_endpoint_does_not_claim_unconfigured_notifications(monkeypatch):
    class FakeInterceptor:
        def __init__(self, config, client):
            pass

        async def intercept(self, text, source_speaker_entity_id=None):
            return True

    monkeypatch.setattr(routes.config_manager, "load", lambda: build_config())
    monkeypatch.setattr(interceptor_module, "CommandInterceptor", FakeInterceptor)

    result = asyncio.run(routes.execute_test_command("打开小孩房空调"))

    assert result["success"] is True
    assert "手机通知" not in result["message"]


def test_setup_logging_is_idempotent(tmp_path):
    logger = logging.getLogger("xiaoai_ha_bridge")
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    setup_logging("INFO", str(tmp_path / "app.log"))
    setup_logging("DEBUG", str(tmp_path / "app.log"))

    assert len(logger.handlers) == 2
    assert logger.level == logging.DEBUG

    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
