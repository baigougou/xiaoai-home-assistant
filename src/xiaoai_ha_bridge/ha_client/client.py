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

    async def get_state(self, entity_id: str, quiet: bool = False) -> Optional[Dict[str, Any]]:
        try:
            response = await self.client.get(
                "{}/api/states/{}".format(self.url, entity_id),
                headers=self.headers
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            if not quiet:
                logger.error("获取实体状态失败 {}: {}".format(entity_id, e))
            return None
        except Exception as e:
            if not quiet:
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

    async def discover_xiaomi_miot_speakers(self) -> List[Dict[str, Any]]:
        """发现支持语音捕获的 xiaomi_miot 音箱。

         Xiaomi Home 集成创建的音箱（如 xiaomi_cn_xxx, xiao_ai_yin_xiang_xxx）
        没有 conversation sensor，不能捕获语音，因此只返回 xiaomi_miot 的
        play_control 音箱。
        """
        entities = await self.get_all_states()
        all_states = {e.get("entity_id", ""): e for e in entities}

        speakers = []
        for entity in entities:
            entity_id = entity.get("entity_id", "")
            if not entity_id.startswith("media_player.xiaomi_lx06_"):
                continue
            if not entity_id.endswith("_play_control"):
                continue
            # 确认存在对应的 conversation sensor
            suffix = entity_id.replace("media_player.", "")
            conv_id = "sensor." + suffix.replace("_play_control", "_conversation")
            if conv_id not in all_states:
                continue
            speakers.append({
                "entity_id": entity_id,
                "name": entity.get("attributes", {}).get("friendly_name", entity_id),
                "conversation_sensor": conv_id
            })

        return speakers

    async def discover_devices_for_bridge(self) -> Dict[str, List[Dict[str, Any]]]:
        """扫描 HA 中所有实体，分类返回可接入桥接服务的设备。

        重点标注：
        - mi_native: 米家原生支持的设备（灯/窗帘/风扇等），小爱可直接控制，无需桥接
        - needs_bridge: 非米家设备（格力/美的空调、追觅扫地机、海尔冰箱/洗衣机等），需要桥接
        """
        entities = await self.get_all_states()

        # 设备分类规则
        # 米家原生：通过 xiaomi_miot/xiaomi_home 接入的灯/窗帘/风扇/开关
        # 非米家：格力/美的/海尔等第三方品牌，以及追觅等高阶功能

        mi_native_brands = ["yeelight", "dooya", "lemesh", "aqara", "lumi", "mijia", "xiaomi", "chuangmi", "philips"]
        mi_native_device_ids = set()

        # 先扫描所有设备，识别米家原生设备
        for e in entities:
            eid = e.get("entity_id", "")
            # 检查 entity_id 中是否包含米家品牌关键词
            for brand in mi_native_brands:
                if brand in eid.lower():
                    mi_native_device_ids.add(eid)
                    break

        categories = {
            "climate": {"label": "空调", "icon": "🌡️", "items": []},
            "vacuum": {"label": "扫地机", "icon": "🤖", "items": []},
            "refrigerator": {"label": "冰箱", "icon": "🧊", "items": []},
            "washing_machine": {"label": "洗衣机", "icon": "👕", "items": []},
            "dryer": {"label": "烘干机", "icon": "👔", "items": []},
            "light": {"label": "灯光", "icon": "💡", "items": []},
            "switch": {"label": "开关/插座", "icon": "🔌", "items": []},
            "cover": {"label": "窗帘/晾衣架", "icon": "🪟", "items": []},
            "fan": {"label": "风扇", "icon": "🌀", "items": []},
            "water_heater": {"label": "热水器/浴霸", "icon": "🔥", "items": []},
        }

        # 设备类型推断：根据 entity_id 模式
        for e in entities:
            eid = e.get("entity_id", "")
            attrs = e.get("attributes", {})
            fname = attrs.get("friendly_name", eid)
            domain = eid.split(".")[0] if "." in eid else ""
            state = e.get("state", "")

            is_mi = eid in mi_native_device_ids

            # 推断设备子类型
            info = {
                "entity_id": eid,
                "name": fname,
                "state": state,
                "domain": domain,
                "mi_native": is_mi,
                "needs_bridge": not is_mi,
            }

            if domain == "climate":
                # 过滤掉空调子功能（如 miir IR 控制器、浴霸风暖子项）
                name_lower = fname.lower()
                if "ir aircondition" in name_lower:
                    continue  # 跳过红外学习空调
                if "ptc_bath_heater" in eid.lower():
                    continue  # 跳过浴霸风暖子项
                categories["climate"]["items"].append(info)

            elif domain == "vacuum":
                info["rooms_count"] = len(attrs.get("rooms", attrs.get("segments", {})))
                categories["vacuum"]["items"].append(info)

            elif domain == "light":
                # 过滤掉指示灯、子灯
                if "指示灯" in fname or "indicator" in fname.lower():
                    continue
                categories["light"]["items"].append(info)

            elif domain == "switch":
                # switch 域智能过滤：只保留"主设备"，推断设备类型
                name_lower = fname.lower()
                eid_lower = eid.lower()

                # 智能推断：识别独立设备的主开关
                if "onoffstatus" in eid_lower or "开关机状态" in fname:
                    # 海尔设备主开关 → 根据名称推断类型
                    if "洗衣" in fname or "wash" in name_lower:
                        categories["washing_machine"]["items"].append(info)
                    elif "烘干" in fname or "干衣" in fname or "dry" in name_lower:
                        categories["dryer"]["items"].append(info)
                    elif "冰箱" in fname or "冷藏" in fname or "refrigerator" in name_lower:
                        categories["refrigerator"]["items"].append(info)
                    else:
                        categories["switch"]["items"].append(info)
                    continue

                # 过滤子功能开关（属于某个设备的二级功能）
                skip_patterns = [
                    "_x_fan", "_lights", "_health", "_power_save", "_8degc", "_sleep",
                    "_air", "_anti_direct", "_light_sensor", "_auto_x_fan", "_auto_light",
                    "_beeper", "_fresh_air", "_buzzer", "_screen_display", "_prevent_",
                    "_dry", "_ptc", "_fan", "_aux_heat",
                    # 海尔设备子功能
                    "_fastdry", "_aroma", "_photo", "_anion", "_remote", "_childlock",
                    "_mites", "_iron", "_delicate", "_sterilization", "_buzzer",
                    "_soakwash", "_strong", "_brighten", "_resn", "_strongdry",
                    "_projection", "_strongdisinfect", "_voice", "_doorauto",
                    "_uv", "_rinseadd", "_spray", "_lightload", "_speedup",
                    "_ultrasonic", "_steam", "_disinfect", "_ozone", "_decorative",
                    "_silent", "_loosen", "_freshair", "_nightwash", "_voicemodule",
                    "_autodisinfectant", "_shoes", "_antiallergy", "_anticrease",
                    "_dryprog", "_steamwash", "_autodetergent", "_detergentb",
                    "_highwater", "_creaseresist", "_energysaving", "_permanentpress",
                    "_uvsterilization", "_autosoftener", "_buzzerdisabled",
                    "_purifiedwash", "_intelligence", "_power",
                    # 追觅子功能
                    "_resume_cleaning", "_carpet_boost", "_obstacle_avoidance",
                    "_customized_cleaning", "_child_lock", "_dnd",
                    "_multi_floor_map", "_self_clean", "_auto_water_refilling",
                    "_intelligent_recognition", "_auto_drying", "_auto_add_detergent",
                    "_voice_assistant", "_cleaning_sequence", "_ai_obstacle",
                    "_fuzzy_obstacle", "_pet_", "_large_particles", "_fill_light",
                    "_collision_avoidance", "_stain_avoidance", "_floor_direction",
                    "_intensive_carpet", "_mop_extend", "_gap_cleaning",
                    "_mopping_under", "_off_peak", "_human_follow",
                    "_max_suction", "_streaming_voice", "_clean_carpets_first",
                    "_smart_mop_washing", "_camera_light",
                ]
                is_skip = False
                for pat in skip_patterns:
                    if pat in eid_lower:
                        is_skip = True
                        break
                if is_skip:
                    continue

                # 过滤自适应照明等辅助开关
                if "adaptive_lighting" in eid_lower:
                    continue

                # 保留核心开关
                categories["switch"]["items"].append(info)

            elif domain == "cover":
                categories["cover"]["items"].append(info)
            elif domain == "fan":
                # 过滤空调送风子项
                if "送风" in fname or "song_feng" in eid_lower or "_fan" in eid_lower:
                    continue
                categories["fan"]["items"].append(info)
            elif domain == "water_heater":
                categories["water_heater"]["items"].append(info)
            elif domain == "sensor":
                pass  # 传感器作为附属，不单独列

        # 过滤空分类
        result = {}
        for key, cat in categories.items():
            if cat["items"]:
                result[key] = cat

        return result

    async def get_sensors_for_device(self, entity_id: str) -> List[Dict[str, Any]]:
        """查找与某个设备相关的传感器（通过设备标识码匹配）。"""
        entities = await self.get_all_states()

        # 从 entity_id 中提取设备标识（如 MAC 地址片段）
        # 例如: climate.gree_climate → 找所有 gree 相关 sensor
        #       vacuum.zhui_mi_s30 → 找所有 zhui_mi_s30 相关 entity
        parts = entity_id.split(".")
        if len(parts) < 2:
            return []
        device_key = parts[1].lower()

        # 提取关键标识词
        keywords = []
        for segment in device_key.split("_"):
            if len(segment) >= 3:
                keywords.append(segment)

        related = []
        for e in entities:
            eid = e.get("entity_id", "")
            # 匹配规则：entity_id 中包含设备关键标识
            matched = False
            for kw in keywords:
                if kw in eid.lower():
                    matched = True
                    break
            if matched and eid != entity_id:
                attrs = e.get("attributes", {})
                related.append({
                    "entity_id": eid,
                    "name": attrs.get("friendly_name", eid),
                    "domain": eid.split(".")[0] if "." in eid else "",
                    "state": e.get("state", ""),
                })

        return related

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
