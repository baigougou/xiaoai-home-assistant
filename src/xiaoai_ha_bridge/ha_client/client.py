import httpx
import logging
from typing import Dict, Any, Optional, List
from ..config.config import HomeAssistantConfig

logger = logging.getLogger(__name__)

class HomeAssistantClient:
    def __init__(self, config: HomeAssistantConfig):
        self.url = config.url.rstrip("/")
        self.api_token = config.api_token
        self.headers = {
            "Authorization": "Bearer {}".format(self.api_token),
            "Content-Type": "application/json"
        }
        self.client = httpx.AsyncClient(timeout=30.0)

    async def close(self):
        await self.client.aclose()

    async def get_state(self, entity_id: str) -> Optional[Dict[str, Any]]:
        try:
            response = await self.client.get(
                "{}/api/states/{}".format(self.url, entity_id),
                headers=self.headers
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            logger.error("获取实体状态失败 {}: {}".format(entity_id, e))
            return None
        except Exception as e:
            logger.error("获取实体状态异常 {}: {}".format(entity_id, e))
            return None

    async def call_service(self, domain: str, service: str, entity_id: str, data: Dict[str, Any] = None) -> bool:
        try:
            payload = {
                "entity_id": entity_id
            }
            if data:
                payload.update(data)

            response = await self.client.post(
                "{}/api/services/{}/{}".format(self.url, domain, service),
                headers=self.headers,
                json=payload
            )
            response.raise_for_status()
            logger.info("调用服务成功 {}.{} - {}".format(domain, service, entity_id))
            return True
        except httpx.HTTPStatusError as e:
            logger.error("调用服务失败 {}.{} - {}: {}".format(domain, service, entity_id, e))
            return False
        except Exception as e:
            logger.error("调用服务异常 {}.{} - {}: {}".format(domain, service, entity_id, e))
            return False

    async def turn_on_ac(self, entity_id: str) -> bool:
        return await self.call_service("climate", "turn_on", entity_id)

    async def turn_off_ac(self, entity_id: str) -> bool:
        return await self.call_service("climate", "turn_off", entity_id)

    async def set_ac_temperature(self, entity_id: str, temperature: float) -> bool:
        return await self.call_service("climate", "set_temperature", entity_id, {"temperature": temperature})

    async def set_ac_mode(self, entity_id: str, mode: str) -> bool:
        mode_map = {
            "制冷": "cool",
            "制热": "heat",
            "除湿": "dry",
            "自动": "auto",
            "送风": "fan_only"
        }
        hvac_mode = mode_map.get(mode, "auto")
        return await self.call_service("climate", "set_hvac_mode", entity_id, {"hvac_mode": hvac_mode})

    async def execute_text(self, entity_id: str, text: str, silent: bool = False) -> bool:
        """通过 xiaomi_miot.intelligent_speaker 执行文本指令到小爱音箱"""
        return await self.call_service("xiaomi_miot", "intelligent_speaker", entity_id, {
            "text": text,
            "execute": True,
            "silent": silent
        })

    async def play_text(self, entity_id: str, text: str) -> bool:
        """通过 xiaomi_miot.intelligent_speaker 让小爱音箱播放 TTS"""
        return await self.call_service("xiaomi_miot", "intelligent_speaker", entity_id, {
            "text": text,
            "execute": False
        })

    async def get_all_states(self) -> List[Dict[str, Any]]:
        try:
            response = await self.client.get(
                "{}/api/states".format(self.url),
                headers=self.headers
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error("获取实体列表失败: {}".format(e))
            return []

    async def get_entities_by_domain(self, domain: str) -> List[Dict[str, Any]]:
        entities = await self.get_all_states()
        return [
            e for e in entities
            if e.get("entity_id", "").startswith("{}.".format(domain))
        ]

    async def vacuum_start(self, entity_id: str) -> bool:
        return await self.call_service("vacuum", "start", entity_id)

    async def vacuum_stop(self, entity_id: str) -> bool:
        return await self.call_service("vacuum", "stop", entity_id)

    async def vacuum_pause(self, entity_id: str) -> bool:
        return await self.call_service("vacuum", "pause", entity_id)

    async def vacuum_return_to_base(self, entity_id: str) -> bool:
        return await self.call_service("vacuum", "return_to_base", entity_id)

    async def vacuum_clean_segment(self, entity_id: str, segment_ids: List[int], repeats: int = 1, clean_mode: str = "sweep_and_mop") -> bool:
        clean_mode_map = {
            "sweep": 0,
            "sweep_and_mop": 1,
            "mop": 2,
        }
        mop_mode = clean_mode_map.get(clean_mode, 1)
        params = [{"segments": segment_ids, "repeat": repeats, "clean_mode": mop_mode}]
        return await self.call_service("vacuum", "send_command", entity_id, {
            "command": "app_segment_clean",
            "params": params
        })

    async def vacuum_self_clean(self, entity_id: str) -> bool:
        """触发基站自清洁（洗拖布）"""
        return await self.call_service("switch", "turn_on", entity_id)

    async def vacuum_start_drying(self, entity_id: str) -> bool:
        """触发拖布烘干"""
        return await self.call_service("button", "press", entity_id)

    async def generic_turn_on_select(self, entity_id: str, option: str = None) -> bool:
        """通过 select 域控制设备开关（海尔洗衣机/烘干机用 select 控制开关机）"""
        data = {}
        if option:
            data["option"] = option
        # 尝试 switch.turn_on，如果失败则尝试 select.select_option
        result = await self.call_service("switch", "turn_on", entity_id)
        if not result:
            # 海尔设备可能用 select 域控制开关
            if option:
                result = await self.call_service("select", "select_option", entity_id, {"option": option})
        return result

    async def get_vacuum_rooms(self, entity_id: str) -> List[Dict[str, Any]]:
        rooms = []
        seen_ids = set()

        state = await self.get_state(entity_id)
        if state:
            attributes = state.get("attributes", {})

            for key in ["rooms", "segments", "room_list", "segment_list"]:
                if key in attributes and isinstance(attributes[key], (list, dict)):
                    data = attributes[key]
                    if isinstance(data, dict):
                        for map_name, map_rooms in data.items():
                            if isinstance(map_rooms, list):
                                for item in map_rooms:
                                    if isinstance(item, dict):
                                        room_id = item.get("id") or item.get("segment_id") or item.get("uid")
                                        room_name = item.get("name") or item.get("room_name") or "区域{}".format(room_id)
                                        if room_id is not None and int(room_id) not in seen_ids:
                                            seen_ids.add(int(room_id))
                                            rooms.append({"id": int(room_id), "name": str(room_name), "map": map_name})
                            elif isinstance(map_rooms, dict):
                                for rid, rname in map_rooms.items():
                                    try:
                                        rid_int = int(rid)
                                        if rid_int not in seen_ids:
                                            seen_ids.add(rid_int)
                                            if isinstance(rname, str):
                                                rooms.append({"id": rid_int, "name": str(rname), "map": map_name})
                                            elif isinstance(rname, dict):
                                                rn = rname.get("name", "区域{}".format(rid))
                                                rooms.append({"id": rid_int, "name": str(rn), "map": map_name})
                                    except (ValueError, TypeError):
                                        pass
                    elif isinstance(data, list):
                        for item in data:
                            if isinstance(item, dict):
                                room_id = item.get("id") or item.get("segment_id") or item.get("uid")
                                room_name = item.get("name") or item.get("room_name") or "区域{}".format(room_id)
                                if room_id is not None and int(room_id) not in seen_ids:
                                    seen_ids.add(int(room_id))
                                    rooms.append({"id": int(room_id), "name": str(room_name)})
                            elif isinstance(item, (int, str)):
                                try:
                                    rid_int = int(item)
                                    if rid_int not in seen_ids:
                                        seen_ids.add(rid_int)
                                        rooms.append({"id": rid_int, "name": "区域{}".format(item)})
                                except (ValueError, TypeError):
                                    pass
                    break

        return rooms

    async def discover_notify_services(self) -> List[Dict[str, str]]:
        try:
            services_resp = await self.client.get("{}/api/services".format(self.url), headers=self.headers)
            if services_resp.status_code == 200:
                services = services_resp.json()
                notify_services = []
                for domain_data in services:
                    domain = domain_data.get("domain", "")
                    if domain == "notify":
                        services_dict = domain_data.get("services", {})
                        if isinstance(services_dict, dict):
                            for service_name in services_dict.keys():
                                service_id = "notify.{}".format(service_name)
                                if service_name.startswith("mobile_app_"):
                                    friendly_name = "📱 " + service_name.replace("mobile_app_", "").replace("_", " ").title()
                                else:
                                    friendly_name = service_name.replace("_", " ").title()
                                notify_services.append({"id": service_id, "name": friendly_name})
                logger.info("发现 {} 个通知服务".format(len(notify_services)))
                return notify_services
            return []
        except Exception as e:
            logger.error("获取通知服务列表失败: {}".format(e))
            import traceback
            traceback.print_exc()
            return []

    async def send_notification(self, notify_service: str, title: str, message: str) -> bool:
        if not notify_service or not notify_service.startswith("notify."):
            return False
        try:
            parts = notify_service.split(".", 1)
            domain = parts[0]
            service = parts[1]
            payload = {
                "title": title,
                "message": message
            }
            response = await self.client.post(
                "{}/api/services/{}/{}".format(self.url, domain, service),
                headers=self.headers,
                json=payload
            )
            response.raise_for_status()
            logger.info("通知发送成功 {}".format(notify_service))
            return True
        except httpx.HTTPStatusError as e:
            logger.error("发送通知失败 {}: {} - {}".format(notify_service, e.response.status_code, e.response.text))
            return False
        except Exception as e:
            logger.error("发送通知异常 {}: {}".format(notify_service, e))
            return False

    async def send_notifications(self, notify_services: List[str], title: str, message: str) -> Dict[str, bool]:
        results = {}
        for service in notify_services:
            if service and service.startswith("notify."):
                results[service] = await self.send_notification(service, title, message)
        return results

    async def generic_turn_on(self, domain: str, entity_id: str) -> bool:
        return await self.call_service(domain, "turn_on", entity_id)

    async def generic_turn_off(self, domain: str, entity_id: str) -> bool:
        return await self.call_service(domain, "turn_off", entity_id)

    async def cover_open(self, entity_id: str) -> bool:
        return await self.call_service("cover", "open_cover", entity_id)

    async def cover_close(self, entity_id: str) -> bool:
        return await self.call_service("cover", "close_cover", entity_id)

    async def cover_stop(self, entity_id: str) -> bool:
        return await self.call_service("cover", "stop_cover", entity_id)

    async def discover_entities(self) -> Dict[str, List[Dict[str, Any]]]:
        entities = await self.get_all_states()

        categories = {
            "climate": [],
            "vacuum": [],
            "media_player": [],
            "sensor": [],
            "switch": [],
            "light": [],
            "fan": [],
        }

        for entity in entities:
            entity_id = entity.get("entity_id", "")
            attributes = entity.get("attributes", {})
            friendly_name = attributes.get("friendly_name", entity_id)

            entity_info = {
                "entity_id": entity_id,
                "name": friendly_name,
                "state": entity.get("state", ""),
                "domain": entity_id.split(".")[0] if "." in entity_id else "",
            }

            domain = entity_info["domain"]
            if domain in categories:
                categories[domain].append(entity_info)
            else:
                if "other" not in categories:
                    categories["other"] = []
                categories["other"].append(entity_info)

        return categories

    async def test_connection(self) -> bool:
        try:
            response = await self.client.get(
                "{}/api/".format(self.url),
                headers=self.headers
            )
            return response.status_code == 200
        except Exception as e:
            logger.error("连接测试失败: {}".format(e))
            return False
