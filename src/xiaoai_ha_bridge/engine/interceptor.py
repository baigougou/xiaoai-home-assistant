import logging
import time
from typing import Dict, Any, Optional
from ..config.config import AppConfig
from ..ha_client.client import HomeAssistantClient
from .parser import CommandParser

logger = logging.getLogger(__name__)

class CommandInterceptor:
    def __init__(self, config: AppConfig, ha_client: HomeAssistantClient):
        self.config = config
        self.ha_client = ha_client
        self.parser = CommandParser(config.commands)
        self.last_processed_text = ""
        self.processing = False
        self.active_cleaning_tasks: Dict[str, Dict[str, Any]] = {}
        self.last_vacuum_states: Dict[str, str] = {}
        self._last_notify_message = ""

    def update_config(self, config: AppConfig):
        self.config = config
        self.parser = CommandParser(config.commands)

    async def intercept(self, text: str, source_speaker_entity_id: str = None) -> bool:
        if not text or text.strip() == "":
            return False

        if text == self.last_processed_text:
            return False

        parsed = self.parser.parse_command(text)
        if not parsed:
            return False

        self.last_processed_text = text
        self.processing = True

        try:
            await self._execute_command(parsed, source_speaker_entity_id)
            return True
        finally:
            self.processing = False

    def _get_tts_speaker(self, source_entity_id: str = None) -> str:
        if source_entity_id:
            speaker_ids = self.config.get_speaker_entity_ids()
            if source_entity_id in speaker_ids:
                return source_entity_id
        if self.config.xiaomi_speakers:
            return self.config.xiaomi_speakers[0].entity_id
        return ""

    async def _execute_command(self, parsed: Dict[str, Any], source_speaker_entity_id: str = None):
        entity_id = parsed["entity_id"]
        action = parsed["action"]
        temperature = parsed["temperature"]
        mode = parsed["mode"]
        is_query = parsed["query"]
        device_name = parsed["name"]
        device_type = parsed["device_type"]
        command_id = parsed.get("command_id", "")
        room = parsed.get("room")
        segment_id = parsed.get("segment_id")
        clean_mode = parsed.get("clean_mode")
        repeats = parsed.get("repeats", 1)

        tts_speaker = self._get_tts_speaker(source_speaker_entity_id)

        if is_query:
            await self._handle_query(entity_id, device_name, device_type, tts_speaker, command_id)
            return

        tts_messages = []
        self._last_notify_message = ""

        if device_type == "climate":
            tts_messages = await self._execute_climate(entity_id, action, temperature, mode, device_name)
        elif device_type == "vacuum":
            tts_messages = await self._execute_vacuum(entity_id, action, device_name, room, segment_id, clean_mode, repeats)
        elif device_type in ("light", "switch", "fan"):
            tts_messages = await self._execute_switch_light(entity_id, action, device_name, device_type)
        elif device_type in ("cover", "curtain"):
            tts_messages = await self._execute_cover(entity_id, action, device_name)
        elif device_type in ("refrigerator", "dishwasher", "washing_machine", "dryer"):
            tts_messages = await self._execute_appliance(entity_id, action, device_name, device_type, command_id)

        if self.config.tts.enabled and tts_messages and tts_speaker:
            await self.ha_client.play_text(
                tts_speaker,
                "，".join(tts_messages)
            )

        notify_services = self.config.tts.notify_services
        notify_message = self._last_notify_message if self._last_notify_message else "，".join(tts_messages)
        if notify_services and tts_messages and not is_query and notify_message:
            title = self._get_notify_title(device_type, action)
            try:
                await self.ha_client.send_notifications(notify_services, title, notify_message)
            except Exception as e:
                logger.warning(f"发送手机通知失败: {e}")

    async def _execute_climate(self, entity_id: str, action: str, temperature: float, mode: str, device_name: str):
        messages = []
        notify_msg = ""

        if action == "turn_on":
            success = await self.ha_client.turn_on_ac(entity_id)
            if success:
                if mode:
                    await self.ha_client.set_ac_mode(entity_id, mode)
                    mode_map_dict = {"cool": "制冷", "heat": "制热", "dry": "除湿", "auto": "自动", "fan_only": "送风"}
                    mode_text = mode_map_dict.get(mode, mode)
                    tts_msg = "好的，已为你打开{}，{}模式".format(device_name, mode_text)
                    notify_msg = "已经打开{}，模式{}".format(device_name, mode_text)
                    if temperature:
                        await self.ha_client.set_ac_temperature(entity_id, temperature)
                        tts_msg += "，温度{}度".format(int(temperature))
                        notify_msg += "，温度{}度".format(int(temperature))
                    messages.append(tts_msg)
                else:
                    success = await self.ha_client.turn_on_ac(entity_id)
                    if success:
                        messages.append("好的，已为你打开{}".format(device_name))
                        notify_msg = "已经打开{}".format(device_name)
                        state = await self.ha_client.get_state(entity_id)
                        if state:
                            attrs = state.get("attributes", {})
                            current_mode = attrs.get("hvac_mode", "")
                            current_temp = attrs.get("temperature")
                            mode_map_dict = {"cool": "制冷", "heat": "制热", "dry": "除湿", "auto": "自动", "fan_only": "送风"}
                            if current_mode and current_mode != "off":
                                mode_text = mode_map_dict.get(current_mode, current_mode)
                                notify_msg += "，模式{}".format(mode_text)
                            if current_temp:
                                notify_msg += "，温度{}度".format(current_temp)

        elif action == "turn_off":
            success = await self.ha_client.turn_off_ac(entity_id)
            if success:
                messages.append("好的，已为你关闭{}".format(device_name))
                notify_msg = "已经关闭{}".format(device_name)
            else:
                messages.append("抱歉，关闭{}失败了，请稍后再试".format(device_name))

        elif action == "adjust":
            need_turn_on = False
            state = await self.ha_client.get_state(entity_id)
            if state and state.get("state") == "off":
                need_turn_on = True
                await self.ha_client.turn_on_ac(entity_id)

            mode_map_dict = {"cool": "制冷", "heat": "制热", "dry": "除湿", "auto": "自动", "fan_only": "送风"}
            tts_parts = ["好的，已为你设置{}".format(device_name)]
            notify_parts = ["已经设置{}".format(device_name)]

            if temperature is not None:
                success = await self.ha_client.set_ac_temperature(entity_id, temperature)
                if success:
                    tts_parts.append("温度{}度".format(int(temperature)))
                    notify_parts.append("温度{}度".format(int(temperature)))
            if mode is not None:
                success = await self.ha_client.set_ac_mode(entity_id, mode)
                if success:
                    mode_text = mode_map_dict.get(mode, mode)
                    tts_parts.append("{}模式".format(mode_text))
                    notify_parts.append("模式{}".format(mode_text))

            if len(tts_parts) > 1:
                messages.append("，".join(tts_parts))
                notify_msg = "，".join(notify_parts)

        self._last_notify_message = notify_msg
        return messages

    async def _execute_vacuum(self, entity_id: str, action: str, device_name: str, room: str = None, segment_id: int = None, clean_mode: str = None, repeats: int = 1):
        messages = []
        notify_msg = ""

        clean_mode_text_map = {
            "sweep": "仅清扫",
            "sweep_and_mop": "扫拖",
            "mop": "仅拖地",
        }

        if action == "self_clean":
            # 基站自清洁（洗拖布）
            # 查找 self_clean_entities 配置
            clean_entity_id = entity_id  # fallback
            for cmd_id, cmd in self.config.commands.items():
                if cmd.entity_id == entity_id and getattr(cmd, 'self_clean_entities', None):
                    clean_entity_id = cmd.self_clean_entities.smart_mop_washing
                    break
            success = await self.ha_client.vacuum_self_clean(clean_entity_id)
            if success:
                messages.append("好的，{}开始洗拖布".format(device_name))
                notify_msg = "{}基站自清洁已启动".format(device_name)
            else:
                messages.append("抱歉，{}自清洁启动失败了".format(device_name))

        elif action == "start_drying":
            # 烘干拖布
            dry_entity_id = entity_id
            for cmd_id, cmd in self.config.commands.items():
                if cmd.entity_id == entity_id and getattr(cmd, 'self_clean_entities', None):
                    dry_entity_id = cmd.self_clean_entities.manual_drying
                    break
            success = await self.ha_client.vacuum_start_drying(dry_entity_id)
            if success:
                messages.append("好的，{}开始烘干拖布".format(device_name))
                notify_msg = "{}拖布烘干已启动".format(device_name)
            else:
                messages.append("抱歉，{}烘干启动失败了".format(device_name))

        elif action == "clean_segment" and segment_id is not None:
            success = await self.ha_client.vacuum_clean_segment(
                entity_id,
                segment_ids=[segment_id],
                repeats=repeats,
                clean_mode=clean_mode or "sweep_and_mop"
            )
            if success:
                mode_text = clean_mode_text_map.get(clean_mode or "sweep_and_mop", "扫拖")
                task_desc = "{}{}".format(mode_text, room)
                if repeats > 1:
                    task_desc += "{}次".format(repeats)
                tts_msg = "好的，{}开始{}".format(device_name, task_desc)
                notify_msg = "{}开始{}".format(device_name, task_desc)
                messages.append(tts_msg)
                self.active_cleaning_tasks[entity_id] = {
                    "device_name": device_name,
                    "task_desc": task_desc,
                    "start_time": time.time()
                }
            else:
                messages.append("抱歉，{}启动{}失败了".format(device_name, task_desc if 'task_desc' in dir() else "清扫"))
        elif action == "start":
            success = await self.ha_client.vacuum_start(entity_id)
            if success:
                mode_text = clean_mode_text_map.get(clean_mode or "sweep_and_mop", "扫拖") if clean_mode else ""
                task_desc = "{}".format(mode_text) if mode_text else "全屋清扫"
                tts_msg = "好的，{}开始{}".format(device_name, task_desc)
                notify_msg = "{}开始{}".format(device_name, task_desc)
                messages.append(tts_msg)
                self.active_cleaning_tasks[entity_id] = {
                    "device_name": device_name,
                    "task_desc": task_desc,
                    "start_time": time.time()
                }
            else:
                messages.append("抱歉，{}启动失败了".format(device_name))
        elif action == "stop":
            success = await self.ha_client.vacuum_stop(entity_id)
            if success:
                messages.append("好的，{}已停止".format(device_name))
                notify_msg = "{}已停止".format(device_name)
                if entity_id in self.active_cleaning_tasks:
                    del self.active_cleaning_tasks[entity_id]
            else:
                messages.append("抱歉，停止{}失败了".format(device_name))
        elif action == "pause":
            success = await self.ha_client.vacuum_pause(entity_id)
            if success:
                messages.append("好的，{}已暂停".format(device_name))
                notify_msg = "{}已暂停".format(device_name)
            else:
                messages.append("抱歉，暂停{}失败了".format(device_name))
        elif action == "return_to_base":
            success = await self.ha_client.vacuum_return_to_base(entity_id)
            if success:
                messages.append("好的，{}开始回充".format(device_name))
                notify_msg = "{}开始回充".format(device_name)
            else:
                messages.append("抱歉，{}回充失败了".format(device_name))

        self._last_notify_message = notify_msg
        return messages

    async def _execute_switch_light(self, entity_id: str, action: str, device_name: str, device_type: str):
        messages = []
        notify_msg = ""
        domain = device_type

        if action == "turn_on":
            success = await self.ha_client.generic_turn_on(domain, entity_id)
            if success:
                messages.append("好的，已为你打开{}".format(device_name))
                notify_msg = "已经打开{}".format(device_name)
            else:
                messages.append("抱歉，打开{}失败了，请稍后再试".format(device_name))
        elif action == "turn_off":
            success = await self.ha_client.generic_turn_off(domain, entity_id)
            if success:
                messages.append("好的���已为你关闭{}".format(device_name))
                notify_msg = "已经关闭{}".format(device_name)
            else:
                messages.append("抱歉，关闭{}失败了，请稍后再试".format(device_name))

        self._last_notify_message = notify_msg
        return messages

    async def _execute_cover(self, entity_id: str, action: str, device_name: str):
        """执行窗帘/晾衣架等 cover 类设备指令"""
        messages = []
        notify_msg = ""

        if action == "turn_on":
            success = await self.ha_client.cover_open(entity_id)
            if success:
                messages.append("好的，已为你打开{}".format(device_name))
                notify_msg = "已经打开{}".format(device_name)
            else:
                messages.append("抱歉，打开{}失败了，请稍后再试".format(device_name))
        elif action == "turn_off":
            success = await self.ha_client.cover_close(entity_id)
            if success:
                messages.append("好的，已为你关闭{}".format(device_name))
                notify_msg = "已经关闭{}".format(device_name)
            else:
                messages.append("抱歉，关闭{}失败了，请稍后再试".format(device_name))
        elif action == "stop":
            success = await self.ha_client.cover_stop(entity_id)
            if success:
                messages.append("好的，{}已停止".format(device_name))
                notify_msg = "{}已停止".format(device_name)
            else:
                messages.append("抱歉，停止{}失败了".format(device_name))

        self._last_notify_message = notify_msg
        return messages

    async def _execute_appliance(self, entity_id: str, action: str, device_name: str, device_type: str, command_id: str = ""):
        messages = []
        notify_msg = ""

        if action == "query":
            state = await self.ha_client.get_state(entity_id)
            if state:
                response = await self._format_appliance_state(device_name, device_type, state.get("state", ""), state.get("attributes", {}), command_id)
                messages.append(response)
        elif action == "turn_on":
            # 洗衣机/烘干机：海尔用 select 域控制开关机，需要选"开机"
            if device_type in ("washing_machine", "dryer"):
                success = await self.ha_client.generic_turn_on_select(entity_id, "开机")
            else:
                success = await self.ha_client.generic_turn_on("switch", entity_id)
            if success:
                verb = {"washing_machine": "启动", "dryer": "启动", "dishwasher": "启动"}.get(device_type, "启动")
                messages.append("好的，已为你{}{}".format(verb, device_name))
                notify_msg = "已经{}{}".format(verb, device_name)
            else:
                messages.append("抱歉，{}{}失败了".format("启动", device_name))
        elif action == "turn_off":
            if device_type in ("washing_machine", "dryer"):
                success = await self.ha_client.generic_turn_off("switch", entity_id)
            else:
                success = await self.ha_client.generic_turn_off("switch", entity_id)
            if success:
                verb = {"washing_machine": "停止", "dryer": "停止", "dishwasher": "停止"}.get(device_type, "停止")
                messages.append("好的，已为你{}{}".format(verb, device_name))
                notify_msg = "已经{}{}".format(verb, device_name)
            else:
                messages.append("抱歉，{}{}失败了".format("停止", device_name))

        self._last_notify_message = notify_msg
        return messages

    async def _handle_query(self, entity_id: str, device_name: str, device_type: str, tts_speaker: str, command_id: str = ""):
        state = await self.ha_client.get_state(entity_id)
        if not state:
            if self.config.tts.enabled and tts_speaker:
                await self.ha_client.play_text(
                    tts_speaker,
                    "无法获取{}的状态".format(device_name)
                )
            return

        state_value = state.get("state", "")
        attributes = state.get("attributes", {})

        appliance_types = ("refrigerator", "dishwasher", "washing_machine", "dryer")
        if device_type in appliance_types:
            response_text = await self._format_appliance_state(device_name, device_type, state_value, attributes, command_id)
        else:
            response_text = self._format_state_response(device_name, device_type, state_value, attributes)

        if self.config.tts.enabled and tts_speaker:
            await self.ha_client.play_text(
                tts_speaker,
                response_text
            )

    def _format_state_response(self, device_name: str, device_type: str, state: str, attributes: Dict[str, Any]) -> str:
        if device_type == "vacuum":
            status_map = {
                "cleaning": "正在清扫",
                "docked": "已回充",
                "idle": "待机中",
                "paused": "已暂停",
                "returning": "正在回充",
                "error": "出错了",
                "off": "已关闭",
            }
            status = status_map.get(state.lower(), state)
            battery = attributes.get("battery_level", "")
            if battery and state.lower() not in ("docked", "charging"):
                return "{}当前{}，电量{}%".format(device_name, status, battery)
            return "{}当前{}".format(device_name, status)

        if device_type == "climate":
            temp = attributes.get("current_temperature", attributes.get("temperature", ""))
            hvac_mode = attributes.get("hvac_mode", "")
            mode_map = {
                "cool": "制冷",
                "heat": "制热",
                "dry": "除湿",
                "auto": "自动",
                "fan_only": "送风",
                "off": "已关闭",
            }
            mode_text = mode_map.get(hvac_mode, hvac_mode)
            if state == "off":
                return "{}当前已关闭".format(device_name)
            if temp:
                return "{}当前{}模式，温度{}度".format(device_name, mode_text, temp)
            return "{}当前{}模式".format(device_name, mode_text)

        if device_type in ("light", "switch", "fan"):
            if state == "on":
                return "{}当前已打开".format(device_name)
            elif state == "off":
                return "{}当前已关闭".format(device_name)

        if device_type in ("cover", "curtain"):
            is_closed = attributes.get("is_closed")
            if is_closed is True or state == "closed":
                return "{}当前已关闭".format(device_name)
            elif is_closed is False or state == "open":
                return "{}当前已打开".format(device_name)
            elif state == "opening":
                return "{}正在打开".format(device_name)
            elif state == "closing":
                return "{}正在关闭".format(device_name)

        return "{}当前状态: {}".format(device_name, state)

    async def _format_appliance_state(self, device_name: str, device_type: str, state: str, attributes: Dict[str, Any], command_id: str = "") -> str:
        def find_attr(*names):
            for name in names:
                for key in attributes:
                    if name.lower() in key.lower():
                        val = attributes[key]
                        if val is not None and val != "" and val != "unknown" and val != "unavailable":
                            return val
            return None

        state_lower = state.lower()

        if device_type == "refrigerator":
            parts = ["{}".format(device_name)]

            # 优先从 fridge_sensors 配置查询实际传感器
            fridge_sensors = None
            if command_id and command_id in self.config.commands:
                cmd = self.config.commands[command_id]
                fridge_sensors = getattr(cmd, 'fridge_sensors', None)

            if fridge_sensors:
                # 查询冷藏室温度
                if fridge_sensors.refrigerator_temp:
                    s = await self.ha_client.get_state(fridge_sensors.refrigerator_temp)
                    if s and s.get("state"):
                        parts.append("冷藏室{}度".format(s["state"]))

                # 查询冷冻室温度
                if fridge_sensors.freezer_temp:
                    s = await self.ha_client.get_state(fridge_sensors.freezer_temp)
                    if s and s.get("state"):
                        parts.append("冷冻室{}度".format(s["state"]))

                # 查询速冻锁鲜状态
                if fridge_sensors.quick_freezing:
                    s = await self.ha_client.get_state(fridge_sensors.quick_freezing)
                    if s and s.get("state") == "on":
                        parts.append("速冻锁鲜已开启")

                # 查询智能存储状态
                if fridge_sensors.intelligence_mode:
                    s = await self.ha_client.get_state(fridge_sensors.intelligence_mode)
                    if s and s.get("state") == "off":
                        parts.append("智能存储已关闭")

                # 查询珍品变温
                if fridge_sensors.vt_room:
                    s = await self.ha_client.get_state(fridge_sensors.vt_room)
                    if s and s.get("state"):
                        parts.append("变温室{}".format(s["state"]))
            else:
                # 回退：从当前 entity 的 attributes 里找
                temp = find_attr("temperature", "current_temp", "temp")
                freezer_temp = find_attr("freezer_temp", "freezer")
                if temp is not None:
                    parts.append("当前温度{}度".format(temp))
                if freezer_temp is not None:
                    parts.append("冷冻室{}度".format(freezer_temp))

            if len(parts) == 1:
                parts.append("运行正常")
            return "，".join(parts)

        if device_type in ("dishwasher", "washing_machine", "dryer"):
            device_label = {
                "dishwasher": "洗碗机",
                "washing_machine": "洗衣机",
                "dryer": "烘干机"
            }.get(device_type, device_name)

            # 优先从 appliance_sensors 配置查询实际传感器
            appliance_sensors = None
            if command_id and command_id in self.config.commands:
                cmd = self.config.commands[command_id]
                appliance_sensors = getattr(cmd, 'appliance_sensors', None)

            parts = ["{}".format(device_name)]

            if appliance_sensors:
                # 查询运行模式
                if appliance_sensors.running_mode:
                    s = await self.ha_client.get_state(appliance_sensors.running_mode)
                    if s and s.get("state"):
                        run_state = str(s["state"]).lower()
                        if run_state in ("running", "washing", "drying", "on", "cleaning"):
                            parts.append("正在运行")
                        elif run_state in ("finished", "completed", "done"):
                            parts.append("已经完成了")
                        elif run_state in ("pause", "paused"):
                            parts.append("已暂停")
                        elif run_state in ("idle", "standby", "off"):
                            parts.append("当前待机")

                # 查询剩余时间
                if appliance_sensors.remaining_time:
                    s = await self.ha_client.get_state(appliance_sensors.remaining_time)
                    if s and s.get("state"):
                        try:
                            mins = int(float(s["state"]))
                            if mins > 0:
                                parts.append("还剩{}分钟".format(mins))
                            else:
                                parts.append("即将完成")
                        except (ValueError, TypeError):
                            pass

                # 查询当前程序
                if appliance_sensors.program:
                    s = await self.ha_client.get_state(appliance_sensors.program)
                    if s and s.get("state"):
                        parts.append("当前程序: {}".format(s["state"]))
            else:
                # 回退：从当前 entity attributes 里找
                remaining_time = find_attr("remaining_time", "remaining", "time_left", "remain_time")
                program = find_attr("program", "cycle", "wash_program", "current_program")

                if state_lower in ("on", "running", "cleaning", "washing", "drying"):
                    parts.append("正在运行")
                elif state_lower in ("off", "idle", "standby", "finished", "completed", "done"):
                    parts.append("当前待机" if state_lower not in ("finished", "completed", "done") else "已经完成了")
                else:
                    parts.append("状态: {}".format(state))

                if program:
                    parts.append("当前程序: {}".format(program))
                if remaining_time is not None:
                    try:
                        mins = int(float(remaining_time))
                        if mins > 0:
                            parts.append("还剩{}分钟".format(mins))
                    except (ValueError, TypeError):
                        pass

            if len(parts) == 1:
                parts.append("当前待机")
            return "，".join(parts)

        return self._format_state_response(device_name, device_type, state, attributes)

    async def check_cleaning_tasks(self):
        if not self.active_cleaning_tasks:
            return

        completed = []
        for entity_id, task in list(self.active_cleaning_tasks.items()):
            state = await self.ha_client.get_state(entity_id)
            if not state:
                continue

            current_state = state.get("state", "").lower()
            prev_state = self.last_vacuum_states.get(entity_id, "")

            finished_states = ("docked", "idle", "off", "charging", "returning")
            cleaning_states = ("cleaning", "paused")

            if prev_state in cleaning_states and current_state in finished_states:
                duration = int(time.time() - task["start_time"])
                mins = duration // 60
                secs = duration % 60
                time_text = "{}分{}秒".format(mins, secs) if mins > 0 else "{}秒".format(secs)
                battery = state.get("attributes", {}).get("battery_level", "")

                title = "🤖 扫地机器人清扫完成"
                message = "{}完成{}，用时{}".format(task['device_name'], task['task_desc'], time_text)
                if battery:
                    message += "，当前电量{}%".format(battery)

                logger.info("清扫任务完成: {}".format(message))

                notify_services = self.config.tts.notify_services
                if self.config.tts.notify_on_clean_complete and notify_services:
                    await self.ha_client.send_notifications(notify_services, title, message)

                speaker_ids = self.config.get_speaker_entity_ids()
                if self.config.tts.enabled and speaker_ids:
                    for speaker in speaker_ids:
                        try:
                            await self.ha_client.play_text(speaker, message)
                        except Exception:
                            pass

                completed.append(entity_id)

            self.last_vacuum_states[entity_id] = current_state

        for entity_id in completed:
            del self.active_cleaning_tasks[entity_id]

    def _get_notify_title(self, device_type: str, action: str) -> str:
        title_map = {
            "climate": "🌡️ 空调控制",
            "vacuum": "🤖 扫地机器人",
            "light": "💡 灯光控制",
            "switch": "🔌 开关控制",
            "fan": "🌀 风扇控制",
            "refrigerator": "🧊 冰箱",
            "dishwasher": "🍽️ 洗碗机",
            "washing_machine": "👕 洗衣机",
            "dryer": "👔 烘干机",
        }
        return title_map.get(device_type, "🏠 智能家居控制")
