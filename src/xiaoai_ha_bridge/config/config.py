import json
import os
from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field

class HomeAssistantConfig(BaseModel):
    url: str = Field(..., description="Home Assistant URL")
    api_token: str = Field(..., description="Long-lived access token")

class XiaomiSpeakerConfig(BaseModel):
    entity_id: str = Field(..., description="小爱音箱实体ID")
    execute_text_service: str = Field(default="xiaomi_miot.intelligent_speaker", description="执行文本指令服务")
    play_text_service: str = Field(default="xiaomi_miot.intelligent_speaker", description="播放文本服务")

class BridgeConfig(BaseModel):
    host: str = Field(default="0.0.0.0", description="服务监听地址")
    port: int = Field(default=8000, description="服务监听端口")
    debug: bool = Field(default=False, description="调试模式")
    log_level: str = Field(default="INFO", description="日志级别")
    polling_interval: int = Field(default=3, description="轮询间隔（秒）")

class VacuumRoomConfig(BaseModel):
    name: str = Field(..., description="房间名称")
    segment_id: int = Field(..., description="区域ID")
    clean_mode: str = Field(default="sweep_and_mop", description="清扫模式: sweep/sweep_and_mop/mop")
    repeats: int = Field(default=1, description="清扫次数")

class CommandConfig(BaseModel):
    name: str = Field(..., description="设备名称")
    entity_id: str = Field(..., description="Home Assistant实体ID")
    device_type: str = Field(default="climate", description="设备类型: climate/vacuum/light/switch/fan等")
    keywords: list = Field(..., description="触发关键词列表")
    rooms: Dict[str, VacuumRoomConfig] = Field(default_factory=dict, description="扫地机器人房间区域配置（仅vacuum类型）")
    default_clean_mode: str = Field(default="sweep_and_mop", description="默认清扫模式")
    default_repeats: int = Field(default=1, description="默认清扫次数")

class TTSConfig(BaseModel):
    enabled: bool = Field(default=True, description="是否启用TTS")
    volume: int = Field(default=50, description="音量（0-100）")
    notify_services: List[str] = Field(default_factory=list, description="手机通知服务列表，如 notify.mobile_app_xxx")
    notify_on_clean_complete: bool = Field(default=True, description="清扫完成发送手机通知")

class AppConfig(BaseModel):
    home_assistant: HomeAssistantConfig
    xiaomi_speakers: List[XiaomiSpeakerConfig] = Field(default_factory=list, description="小爱音箱列表（支持多个）")
    bridge: BridgeConfig = Field(default_factory=BridgeConfig)
    commands: Dict[str, CommandConfig] = Field(default_factory=dict)
    tts: TTSConfig = Field(default_factory=TTSConfig)

    def get_speaker_entity_ids(self) -> List[str]:
        return [sp.entity_id for sp in self.xiaomi_speakers]

class ConfigManager:
    def __init__(self, config_path: str = "config/config.json"):
        self.config_path = config_path
        self.config: Optional[AppConfig] = None

    def load(self) -> AppConfig:
        if not os.path.exists(self.config_path):
            return AppConfig(
                home_assistant=HomeAssistantConfig(url="", api_token=""),
                xiaomi_speakers=[],
            )

        with open(self.config_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if "xiaomi_speaker" in data and "xiaomi_speakers" not in data:
            data["xiaomi_speakers"] = [data.pop("xiaomi_speaker")]

        if "tts" in data:
            tts_data = data["tts"]
            if "notify_service" in tts_data and "notify_services" not in tts_data:
                old_service = tts_data.pop("notify_service")
                tts_data["notify_services"] = [old_service] if old_service else []

        if "commands" in data:
            for cmd_id, cmd in data["commands"].items():
                if "device_type" not in cmd:
                    entity_id = cmd.get("entity_id", "")
                    if entity_id.startswith("vacuum."):
                        cmd["device_type"] = "vacuum"
                    elif entity_id.startswith("light."):
                        cmd["device_type"] = "light"
                    elif entity_id.startswith("switch."):
                        cmd["device_type"] = "switch"
                    elif entity_id.startswith("fan."):
                        cmd["device_type"] = "fan"
                    else:
                        cmd["device_type"] = "climate"

        self.config = AppConfig(**data)
        return self.config

    def save(self, config: AppConfig):
        os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(config.dict(), f, ensure_ascii=False, indent=2)

    def reload(self) -> AppConfig:
        return self.load()
