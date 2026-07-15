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
from xiaoai_ha_bridge.ha_client.client import HomeAssistantClient
from xiaoai_ha_bridge.engine.interceptor import CommandInterceptor
from xiaoai_ha_bridge.engine import interceptor as interceptor_module
from xiaoai_ha_bridge.web import routes
from xiaoai_ha_bridge.logging.logger import setup_logging
from xiaoai_ha_bridge.miservice.poller import SpeakerPoller


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


def test_poller_ignores_restart_baseline_but_handles_repeated_text():
    entity_id = "media_player.xiaomi_lx06_dd28_play_control"
    conversation_id = "sensor.xiaomi_lx06_dd28_conversation"
    states = [
        {
            "entity_id": conversation_id,
            "state": "turn on study ac",
            "last_updated": "2026-07-15T10:00:00+00:00",
        },
        {
            "entity_id": conversation_id,
            "state": "turn on study ac",
            "last_updated": "2026-07-15T10:01:00+00:00",
        },
    ]

    class PollerClient:
        async def get_state(self, requested_entity_id, quiet=False):
            if requested_entity_id == conversation_id:
                return states.pop(0)
            return None

    handled = []

    async def on_command(text, source_entity_id):
        handled.append((text, source_entity_id))
        return True

    config = build_config()
    config.xiaomi_speakers = [XiaomiSpeakerConfig(entity_id=entity_id)]
    poller = SpeakerPoller(config, PollerClient(), on_command=on_command)

    asyncio.run(poller._poll_speaker(entity_id))
    assert handled == []

    asyncio.run(poller._poll_speaker(entity_id))
    assert handled == [("turn on study ac", entity_id)]


def test_ha_connection_preserves_http_failure_reason():
    class FakeResponse:
        status_code = 403
        text = "invalid authentication"

    class FakeHttpClient:
        async def get(self, url, headers):
            return FakeResponse()

    client = HomeAssistantClient(
        HomeAssistantConfig(url="http://ha.local:8123", api_token="token")
    )
    client.client = FakeHttpClient()

    assert asyncio.run(client.test_connection()) is False
    assert client.last_error == "Home Assistant 返回 HTTP 403"


def test_poller_ignores_unavailable_and_first_text_after_reconnect():
    entity_id = "media_player.xiaomi_lx06_dd28_play_control"
    conversation_id = "sensor.xiaomi_lx06_dd28_conversation"
    states = [
        {"entity_id": conversation_id, "state": "unavailable", "last_updated": "t1"},
        {"entity_id": conversation_id, "state": "old command", "last_updated": "t2"},
        {"entity_id": conversation_id, "state": "new command", "last_updated": "t3"},
    ]

    class PollerClient:
        async def get_state(self, requested_entity_id, quiet=False):
            if requested_entity_id == conversation_id:
                return states.pop(0)
            return None

    handled = []

    async def on_command(text, source_entity_id):
        handled.append(text)
        return True

    config = build_config()
    config.xiaomi_speakers = [XiaomiSpeakerConfig(entity_id=entity_id)]
    poller = SpeakerPoller(config, PollerClient(), on_command=on_command)

    for _ in states.copy():
        asyncio.run(poller._poll_speaker(entity_id))

    assert handled == ["new command"]

