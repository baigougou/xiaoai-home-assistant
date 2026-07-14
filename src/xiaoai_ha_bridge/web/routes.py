from fastapi import APIRouter, HTTPException, Body
from fastapi.responses import HTMLResponse, FileResponse
from typing import Dict, Any, Optional
import os
import json
from ..config.config import AppConfig, ConfigManager, HomeAssistantConfig, XiaomiSpeakerConfig
from ..ha_client.client import HomeAssistantClient

router = APIRouter()
config_manager = ConfigManager()

_poller = None
_interceptor = None

def set_services(poller, interceptor):
    global _poller, _interceptor
    _poller = poller
    _interceptor = interceptor

@router.get("/", response_class=HTMLResponse)
async def index():
    index_file = os.path.join(os.path.dirname(__file__), "index.html")
    if not os.path.exists(index_file):
        web_dir = os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "web")
        index_file = os.path.join(web_dir, "index.html")

    with open(index_file, "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())

@router.get("/api/config")
async def get_config():
    try:
        config = config_manager.load()
        return config.dict()
    except FileNotFoundError:
        return {
            "home_assistant": {"url": "", "api_token": ""},
            "xiaomi_speakers": [],
            "bridge": {
                "host": "0.0.0.0",
                "port": 8000,
                "debug": False,
                "log_level": "INFO",
                "polling_interval": 3
            },
            "tts": {"enabled": True, "volume": 50},
            "commands": {}
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/api/config")
async def save_config(config_data: Dict[str, Any] = Body(...)):
    try:
        # 增量合并：先加载现有配置，再用前端传来的字段覆盖
        try:
            existing = config_manager.load()
            existing_dict = existing.dict()
        except FileNotFoundError:
            existing_dict = {}

        # 递归合并（只覆盖前端传来的字段，保留未传的字段）
        def deep_merge(base, update):
            for key, value in update.items():
                if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                    deep_merge(base[key], value)
                else:
                    base[key] = value

        deep_merge(existing_dict, config_data)

        if "xiaomi_speaker" in existing_dict and "xiaomi_speakers" not in existing_dict:
            existing_dict["xiaomi_speakers"] = [existing_dict.pop("xiaomi_speaker")]

        if "xiaomi_speakers" in existing_dict:
            speakers = []
            for sp in existing_dict["xiaomi_speakers"]:
                if isinstance(sp, str):
                    speakers.append({"entity_id": sp, "execute_text_service": "xiaomi_miot.intelligent_speaker", "play_text_service": "xiaomi_miot.intelligent_speaker"})
                elif isinstance(sp, dict) and sp.get("entity_id"):
                    speakers.append(sp)
            existing_dict["xiaomi_speakers"] = speakers

        if "commands" in existing_dict:
            for cmd_id, cmd in existing_dict["commands"].items():
                if "device_type" not in cmd or not cmd["device_type"]:
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

        config = AppConfig(**existing_dict)
        config_manager.save(config)

        if _interceptor and _poller:
            _interceptor.update_config(config)
            _poller.update_config(config)

        return {"message": "配置保存成功"}
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/api/test/ha")
async def test_ha_connection(config: Dict[str, Any] = Body(...)):
    from ..ha_client.client import HomeAssistantClient
    from ..config.config import HomeAssistantConfig

    try:
        ha_config = HomeAssistantConfig(**config)
        client = HomeAssistantClient(ha_config)
        success = await client.test_connection()
        await client.close()
        return {"success": success}
    except Exception as e:
        return {"success": False, "error": str(e)}

@router.post("/api/execute")
async def execute_command(text: str = Body(..., embed=True)):
    from ..engine.parser import CommandParser

    try:
        config = config_manager.load()
        parser = CommandParser(config.commands)
        parsed = parser.parse_command(text)
        if not parsed:
            return {"handled": False, "message": "未匹配到指令"}

        from ..ha_client.client import HomeAssistantClient
        from ..engine.interceptor import CommandInterceptor

        ha_client = HomeAssistantClient(config.home_assistant)
        interceptor = CommandInterceptor(config, ha_client)
        handled = await interceptor.intercept(text)
        await ha_client.close()

        return {"handled": handled, "parsed": parsed}
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/api/discover")
async def discover_entities():
    try:
        config = config_manager.load()
    except FileNotFoundError:
        raise HTTPException(status_code=400, detail="请先配置 Home Assistant 连接信息")

    try:
        ha_client = HomeAssistantClient(config.home_assistant)
        entities = await ha_client.discover_entities()
        await ha_client.close()
        return entities
    except Exception as e:
        raise HTTPException(status_code=500, detail="发现实体失败: {}".format(str(e)))

@router.get("/api/discover/speakers")
async def discover_xiaomi_miot_speakers():
    """发现支持语音捕获的 xiaomi_miot 音箱。"""
    try:
        config = config_manager.load()
    except FileNotFoundError:
        raise HTTPException(status_code=400, detail="请先配置 Home Assistant 连接信息")

    try:
        ha_client = HomeAssistantClient(config.home_assistant)
        speakers = await ha_client.discover_xiaomi_miot_speakers()
        await ha_client.close()
        return {"success": True, "speakers": speakers}
    except Exception as e:
        raise HTTPException(status_code=500, detail="发现音箱失败: {}".format(str(e)))

@router.get("/api/discover/devices")
async def discover_devices():
    """扫描 HA 所有设备，分类返回，标注米家原生 vs 需桥接。"""
    try:
        config = config_manager.load()
    except FileNotFoundError:
        raise HTTPException(status_code=400, detail="请先配置 Home Assistant 连接信息")

    try:
        ha_client = HomeAssistantClient(config.home_assistant)
        devices = await ha_client.discover_devices_for_bridge()
        await ha_client.close()
        return {"success": True, "categories": devices}
    except Exception as e:
        raise HTTPException(status_code=500, detail="发现设备失败: {}".format(str(e)))

@router.get("/api/discover/device-sensors")
async def discover_device_sensors(entity_id: str):
    """查找与某个设备相关的传感器（用于配置冰箱/洗衣机等）。"""
    try:
        config = config_manager.load()
    except FileNotFoundError:
        raise HTTPException(status_code=400, detail="请先配置 Home Assistant 连接信息")

    try:
        ha_client = HomeAssistantClient(config.home_assistant)
        sensors = await ha_client.get_sensors_for_device(entity_id)
        await ha_client.close()
        return {"success": True, "sensors": sensors}
    except Exception as e:
        raise HTTPException(status_code=500, detail="查找传感器失败: {}".format(str(e)))

@router.get("/api/discover/vacuum-rooms")
async def discover_vacuum_rooms(entity_id: str):
    """获取扫地机器人房间列表（从 HA 实时读取）。"""
    try:
        config = config_manager.load()
    except FileNotFoundError:
        raise HTTPException(status_code=400, detail="请先配置 Home Assistant 连接信息")

    try:
        ha_client = HomeAssistantClient(config.home_assistant)
        rooms = await ha_client.get_vacuum_rooms(entity_id)
        await ha_client.close()
        return {"success": True, "rooms": rooms}
    except Exception as e:
        raise HTTPException(status_code=500, detail="获取房间列表失败: {}".format(str(e)))

# ========== 设备 CRUD ==========

@router.post("/api/commands")
async def add_device(data: Dict[str, Any] = Body(...)):
    """添加一个设备到桥接配置。"""
    try:
        config = config_manager.load()
        cmd_id = data.get("id", "")
        if not cmd_id:
            raise HTTPException(status_code=400, detail="缺少设备ID")
        if cmd_id in config.commands:
            raise HTTPException(status_code=400, detail="设备 {} 已存在".format(cmd_id))

        # 构建 CommandConfig
        from ..config.config import CommandConfig
        cmd_data = {
            "name": data.get("name", cmd_id),
            "entity_id": data.get("entity_id", ""),
            "device_type": data.get("device_type", "climate"),
            "keywords": data.get("keywords", [data.get("name", cmd_id)]),
        }

        # 可选字段
        for field in ["rooms", "default_clean_mode", "default_repeats",
                       "fridge_sensors", "self_clean_entities", "appliance_sensors"]:
            if field in data and data[field] is not None:
                cmd_data[field] = data[field]

        cmd = CommandConfig(**cmd_data)
        config.commands[cmd_id] = cmd
        config_manager.save(config)

        if _interceptor:
            _interceptor.update_config(config)

        return {"success": True, "message": "设备 {} 添加成功".format(data.get("name", cmd_id))}
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=400, detail=str(e))

@router.delete("/api/commands/{cmd_id}")
async def remove_device(cmd_id: str):
    """从桥接配置中移除设备。"""
    try:
        config = config_manager.load()
        if cmd_id not in config.commands:
            raise HTTPException(status_code=404, detail="设备 {} 不存在".format(cmd_id))

        del config.commands[cmd_id]
        config_manager.save(config)

        if _interceptor:
            _interceptor.update_config(config)

        return {"success": True, "message": "设备已移除"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/api/commands/{cmd_id}")
async def update_device(cmd_id: str, data: Dict[str, Any] = Body(...)):
    """更新设备配置（名称、关键词、房间、传感器等）。"""
    try:
        config = config_manager.load()
        if cmd_id not in config.commands:
            raise HTTPException(status_code=404, detail="设备 {} 不存在".format(cmd_id))

        cmd = config.commands[cmd_id]

        # 更新基础字段
        for field in ["name", "entity_id", "device_type"]:
            if field in data:
                setattr(cmd, field, data[field])

        if "keywords" in data:
            cmd.keywords = data["keywords"]

        # 更新嵌套配置
        from ..config.config import VacuumRoomConfig, FridgeSensorsConfig, \
            VacuumSelfCleanConfig, WasherDryerSensorsConfig

        if "rooms" in data and data["rooms"]:
            cmd.rooms = {k: VacuumRoomConfig(**v) for k, v in data["rooms"].items()}

        if "fridge_sensors" in data and data["fridge_sensors"]:
            cmd.fridge_sensors = FridgeSensorsConfig(**data["fridge_sensors"])

        if "self_clean_entities" in data and data["self_clean_entities"]:
            cmd.self_clean_entities = VacuumSelfCleanConfig(**data["self_clean_entities"])

        if "appliance_sensors" in data and data["appliance_sensors"]:
            cmd.appliance_sensors = WasherDryerSensorsConfig(**data["appliance_sensors"])

        if "default_clean_mode" in data:
            cmd.default_clean_mode = data["default_clean_mode"]
        if "default_repeats" in data:
            cmd.default_repeats = data["default_repeats"]

        config_manager.save(config)

        if _interceptor:
            _interceptor.update_config(config)

        return {"success": True, "message": "设备配置已更新"}
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/api/discover/test")
async def discover_with_config(config_data: Dict[str, Any] = Body(...)):
    try:
        ha_config = HomeAssistantConfig(
            url=config_data["url"],
            api_token=config_data["api_token"]
        )
        ha_client = HomeAssistantClient(ha_config)
        success = await ha_client.test_connection()
        if not success:
            await ha_client.close()
            return {"success": False, "error": "无法连接到 Home Assistant"}
        entities = await ha_client.discover_entities()
        await ha_client.close()
        return {"success": True, "entities": entities}
    except Exception as e:
        return {"success": False, "error": str(e)}

@router.post("/api/command/test")
async def test_command(text: str = Body(..., embed=True)):
    try:
        config = config_manager.load()
        from ..engine.parser import CommandParser
        parser = CommandParser(config.commands)
        parsed = parser.parse_command(text)
        return {
            "text": text,
            "matched": parsed is not None,
            "parsed": parsed
        }
    except Exception as e:
        return {"error": str(e)}

@router.post("/api/command/execute")
async def execute_test_command(text: str = Body(..., embed=True)):
    try:
        config = config_manager.load()
        from ..ha_client.client import HomeAssistantClient
        from ..engine.interceptor import CommandInterceptor

        ha_client = HomeAssistantClient(config.home_assistant)
        interceptor = CommandInterceptor(config, ha_client)
        handled = await interceptor.intercept(text, None)
        await ha_client.close()

        return {
            "success": handled,
            "message": "指令执行成功，已发送TTS播报和手机通知" if handled else "未匹配到指令或执行失败"
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}

@router.get("/api/commands/suggestions")
async def get_command_suggestions():
    """返回所有设备的语音指令建议"""
    try:
        config = config_manager.load()
    except FileNotFoundError:
        return {"devices": [], "total": 0}

    type_icons = {
        "climate": "🌡️", "vacuum": "🤖", "refrigerator": "🧊",
        "washing_machine": "👕", "dryer": "👔",
        "light": "💡", "switch": "🔌", "fan": "🌀",
        "cover": "🪟", "curtain": "🪟"
    }
    type_labels = {
        "climate": "空调", "vacuum": "扫地机", "refrigerator": "冰箱",
        "washing_machine": "洗衣机", "dryer": "烘干机",
        "light": "灯光", "switch": "开关", "fan": "风扇",
        "cover": "窗帘/晾衣架", "curtain": "窗帘"
    }

    def get_suggestions(cmd):
        suggestions = []
        name = cmd.name
        dtype = getattr(cmd, "device_type", "climate")
        if dtype == "climate":
            suggestions = [
                "打开{}".format(name),
                "关闭{}".format(name),
                "{}多少度".format(name),
                "{}制冷26度".format(name),
                "{}制热模式".format(name),
                "{}调到24度".format(name),
            ]
        elif dtype == "vacuum":
            suggestions = [
                "扫拖客厅",
                "仅拖厨房",
                "打扫主卧",
                "自清洁",
                "回去充电",
                "状态",
            ]
        elif dtype == "refrigerator":
            suggestions = [
                "{}多少度".format(name),
                "{}温度".format(name),
                "{}状态".format(name),
                "{}门关好没".format(name),
            ]
        elif dtype in ("washing_machine", "dryer"):
            suggestions = [
                "{}状态".format(name),
                "{}还要多久".format(name),
                "{}开始".format(name),
                "{}停止".format(name),
            ]
        elif dtype in ("cover", "curtain"):
            suggestions = [
                "打开{}".format(name),
                "关闭{}".format(name),
                "{}状态".format(name),
            ]
        else:
            suggestions = [
                "打开{}".format(name),
                "关闭{}".format(name),
                "{}状态".format(name),
            ]
        return suggestions

    devices = []
    for cmd_id, cmd in config.commands.items():
        dtype = getattr(cmd, "device_type", "climate")
        devices.append({
            "id": cmd_id,
            "name": cmd.name,
            "entity_id": cmd.entity_id,
            "device_type": dtype,
            "type_icon": type_icons.get(dtype, "📦"),
            "type_label": type_labels.get(dtype, dtype),
            "keywords": cmd.keywords if hasattr(cmd, "keywords") else [],
            "suggestions": get_suggestions(cmd),
        })

    return {"devices": devices, "total": len(devices)}

@router.get("/api/health")
async def health_check():
    return {"status": "ok", "version": "0.2.3"}

@router.get("/api/vacuum/rooms")
async def get_vacuum_rooms(entity_id: str):
    try:
        config = config_manager.load()
        ha_client = HomeAssistantClient(config.home_assistant)
        rooms = await ha_client.get_vacuum_rooms(entity_id)
        await ha_client.close()
        return {"success": True, "rooms": rooms}
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e), "rooms": []}

@router.get("/api/notify/services")
async def get_notify_services():
    try:
        config = config_manager.load()
        ha_client = HomeAssistantClient(config.home_assistant)
        services = await ha_client.discover_notify_services()
        await ha_client.close()
        return {"success": True, "services": services}
    except Exception as e:
        return {"success": False, "error": str(e), "services": []}

@router.post("/api/notify/test")
async def test_notification(data: Dict[str, Any] = Body(...)):
    try:
        config = config_manager.load()
        notify_services = data.get("notify_services") or config.tts.notify_services
        if not notify_services:
            single_service = data.get("notify_service", "")
            if single_service:
                notify_services = [single_service]
        if not notify_services:
            return {"success": False, "error": "未配置通知服务"}

        import httpx
        title = data.get("title", "🧪 测试通知")
        message = data.get("message", "这是一条来自XiaoAI HA Bridge的测试消息")

        ha_url = config.home_assistant.url.rstrip("/")
        headers = {
            "Authorization": "Bearer {}".format(config.home_assistant.api_token),
            "Content-Type": "application/json"
        }

        results = {}
        success_count = 0
        async with httpx.AsyncClient(timeout=10.0) as client:
            for notify_service in notify_services:
                if not notify_service or not notify_service.startswith("notify."):
                    results[notify_service] = {"success": False, "error": "服务格式错误"}
                    continue
                service_name = notify_service.split(".", 1)[1]
                try:
                    resp = await client.post(
                        "{}/api/services/notify/{}".format(ha_url, service_name),
                        headers=headers,
                        json={"title": title, "message": message}
                    )
                    if resp.status_code == 200:
                        results[notify_service] = {"success": True}
                        success_count += 1
                    else:
                        error_detail = "HTTP {}".format(resp.status_code)
                        try:
                            error_json = resp.json()
                            error_detail += ": {}".format(error_json.get('message', str(error_json)))
                        except:
                            error_detail += ": {}".format(resp.text[:200])
                        results[notify_service] = {"success": False, "error": error_detail}
                except Exception as e:
                    results[notify_service] = {"success": False, "error": str(e)}

        if success_count > 0:
            return {"success": True, "message": "已向{}个设备发送测试通知，请检查手机".format(success_count), "results": results}
        else:
            return {"success": False, "error": "所有通知服务发送失败", "results": results}
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}

@router.post("/api/restart")
async def restart_service():
    import os
    import signal
    import threading

    def delayed_exit():
        import time
        time.sleep(1)
        os.kill(os.getpid(), signal.SIGTERM)

    threading.Thread(target=delayed_exit, daemon=True).start()
    return {"message": "服务正在重启..."}
