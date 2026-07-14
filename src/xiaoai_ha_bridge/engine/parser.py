import re
import logging
from typing import Dict, Any, Optional, Tuple
from ..config.config import CommandConfig

logger = logging.getLogger(__name__)

class CommandParser:
    def __init__(self, commands: Dict[str, CommandConfig]):
        self.commands = commands
        self.command_cache: Dict[str, str] = {}
        self._build_keyword_cache()

    def _build_keyword_cache(self):
        self.command_cache = {}
        self.room_cache = {}
        self.vacuum_devices = []
        for cmd_id, cmd_config in self.commands.items():
            device_type = getattr(cmd_config, 'device_type', '')
            if device_type == 'vacuum':
                self.vacuum_devices.append(cmd_id)
            for keyword in cmd_config.keywords:
                self.command_cache[keyword] = cmd_id
            rooms = getattr(cmd_config, 'rooms', {})
            if rooms and device_type == 'vacuum':
                for room_key, room_config in rooms.items():
                    room_name = room_config.name if hasattr(room_config, 'name') else room_config.get('name', room_key)
                    if room_name not in self.room_cache:
                        self.room_cache[room_name] = (cmd_id, room_config)

    def find_matching_command(self, text: str) -> Optional[str]:
        sorted_keywords = sorted(self.command_cache.keys(), key=len, reverse=True)
        for keyword in sorted_keywords:
            if keyword in text:
                return self.command_cache[keyword]

        # 无关键词匹配时，如果只有一台扫地机，通过动作词自动路由
        room_action_keywords = ["打扫", "清扫", "扫", "拖", "清洁", "清理", "扫地"]
        vacuum_control_keywords = ["停止", "回充", "暂停", "回去", "回家", "回去充电", "回基站", "停一下", "先停"]
        vacuum_self_clean_keywords = ["自清洁", "洗拖布", "基站自清洁", "基站清洗"]
        vacuum_dry_keywords = ["烘干拖布", "烘干抹布", "拖布烘干", "抹布烘干"]
        has_clean_action = any(kw in text for kw in room_action_keywords)
        has_vacuum_control = any(kw in text for kw in vacuum_control_keywords)
        has_self_clean = any(kw in text for kw in vacuum_self_clean_keywords)
        has_dry = any(kw in text for kw in vacuum_dry_keywords)

        if len(self.vacuum_devices) == 1 and (has_clean_action or has_vacuum_control or has_self_clean or has_dry):
            return self.vacuum_devices[0]

        if has_clean_action and self.room_cache:
            sorted_rooms = sorted(self.room_cache.keys(), key=len, reverse=True)
            for room_name in sorted_rooms:
                if room_name in text:
                    cmd_id, _ = self.room_cache[room_name]
                    return cmd_id

        return None

    def _parse_climate(self, text: str, result: Dict[str, Any]) -> Dict[str, Any]:
        has_turn_off = "关闭" in text or "关掉" in text or ("关" in text and "开" not in text)

        temp_match = re.search(r"(\d{1,2})[度℃°]", text)
        if temp_match:
            result["temperature"] = float(temp_match.group(1))

        mode_patterns = [
            (r"制冷", "cool"),
            (r"制热", "heat"),
            (r"除湿", "dry"),
            (r"自动", "auto"),
            (r"送风", "fan_only"),
            (r"风扇", "fan_only"),
        ]
        for pattern, mode in mode_patterns:
            if pattern in text:
                result["mode"] = mode
                break

        mode_words = ["制冷", "制热", "除湿", "自动", "送风", "风扇"]
        has_mode_only_open = False
        for mode_word in mode_words:
            if f"开{mode_word}" in text or mode_word in text and "关" not in text:
                has_mode_only_open = True
                break

        has_turn_on = "打开" in text or "开" in text or has_mode_only_open or (result["mode"] is not None and not has_turn_off)

        has_adjust = "调到" in text or "设置" in text or "调至" in text or result["temperature"] is not None

        query_patterns = [
            "是多少",
            "多少度",
            "状态",
            "运行",
            "工作",
            "温度",
        ]
        has_query = any(pattern in text for pattern in query_patterns) and not has_turn_on and not has_turn_off and not has_adjust

        fan_patterns = [
            (r"自动风", "auto"),
            (r"低速风|小风|低风", "low"),
            (r"中速风|中风|中速", "medium"),
            (r"高速风|大风|高风|强风", "high"),
        ]
        for pattern, fan_mode in fan_patterns:
            if pattern in text:
                result["fan_mode"] = fan_mode
                has_adjust = True
                break

        if has_query:
            result["query"] = True
            result["action"] = "query"
        elif has_adjust:
            result["action"] = "adjust"
        elif has_turn_off:
            result["action"] = "turn_off"
        elif has_turn_on:
            result["action"] = "turn_on"

        return result

    def _parse_vacuum(self, text: str, result: Dict[str, Any], cmd_config=None) -> Dict[str, Any]:
        # 自清洁关键词（优先级最高）
        self_clean_keywords = ["自清洁", "洗拖布", "基站自清洁", "基站清洗"]
        has_self_clean = any(kw in text for kw in self_clean_keywords)

        # 烘干拖布
        dry_keywords = ["烘干拖布", "烘干抹布", "拖布烘干", "抹布烘干"]
        has_start_drying = any(kw in text for kw in dry_keywords)

        if has_self_clean:
            result["action"] = "self_clean"
            result["query"] = False
            return result

        if has_start_drying:
            result["action"] = "start_drying"
            result["query"] = False
            return result

        has_turn_off = any(kw in text for kw in ["关闭", "关掉", "停止", "回去", "回充", "回去充电"])
        pause_keywords = ["暂停", "停一下", "先停"]
        has_pause = any(kw in text for kw in pause_keywords)
        if has_pause:
            has_turn_off = True

        return_home_keywords = ["回去", "回充", "回去充电", "回家", "回基站"]
        has_return_home = any(kw in text for kw in return_home_keywords)

        query_patterns = ["状态", "在哪", "在哪里", "工作", "电量", "多少电"]
        has_query = any(pattern in text for pattern in query_patterns) and not has_return_home

        room_name = None
        rooms = getattr(cmd_config, 'rooms', {}) if cmd_config else {}
        if rooms:
            room_name_list = []
            room_name_map = {}
            for rk, rv in rooms.items():
                rn = rv.name if hasattr(rv, 'name') else rv.get('name', rk)
                room_name_list.append(rn)
                room_name_map[rn] = rv
            sorted_room_names = sorted(room_name_list, key=len, reverse=True)
            for r_name in sorted_room_names:
                if r_name in text:
                    room_name = r_name
                    rv = room_name_map[r_name]
                    result["room"] = r_name
                    result["segment_id"] = rv.segment_id if hasattr(rv, 'segment_id') else rv.get('segment_id')
                    break

        clean_mode = None
        if "仅拖" in text or "只拖" in text or "拖地" in text or "拖一下" in text:
            clean_mode = "mop"
        elif "仅扫" in text or "只扫" in text or ("扫地" in text and "拖" not in text):
            clean_mode = "sweep"
        elif "扫拖" in text or "拖扫" in text or "打扫" in text or "清扫" in text or "清洁" in text or "扫一下" in text:
            clean_mode = "sweep_and_mop"
        if clean_mode:
            result["clean_mode"] = clean_mode

        repeats = 1
        repeat_match = re.search(r"(\d+)[次次遍]", text)
        if repeat_match:
            repeats = int(repeat_match.group(1))
            result["repeats"] = repeats

        start_keywords = ["开始", "启动", "开始打扫", "开始清扫", "清扫", "打扫", "扫地", "清洁", "清理", "扫"]
        has_turn_on = any(kw in text for kw in start_keywords) or room_name is not None

        if has_query:
            result["query"] = True
            result["action"] = "query"
        elif has_return_home:
            result["action"] = "return_to_base"
        elif has_pause:
            result["action"] = "pause"
        elif has_turn_off and not has_turn_on:
            result["action"] = "stop"
        elif room_name:
            result["action"] = "clean_segment"
            if not clean_mode:
                result["clean_mode"] = getattr(cmd_config, 'default_clean_mode', 'sweep_and_mop') if cmd_config else "sweep_and_mop"
        elif has_turn_on:
            result["action"] = "start"
            if not clean_mode:
                result["clean_mode"] = getattr(cmd_config, 'default_clean_mode', 'sweep_and_mop') if cmd_config else "sweep_and_mop"
        else:
            result["action"] = "start"
            result["clean_mode"] = getattr(cmd_config, 'default_clean_mode', 'sweep_and_mop') if cmd_config else "sweep_and_mop"

        return result

    def _parse_switch_light(self, text: str, result: Dict[str, Any]) -> Dict[str, Any]:
        has_turn_off = any(kw in text for kw in ["关闭", "关掉", "关"]) and "开" not in text
        has_turn_on = any(kw in text for kw in ["打开", "开"]) or (not has_turn_off)

        query_patterns = ["状态", "开了吗", "关了吗", "是否打开"]
        has_query = any(pattern in text for pattern in query_patterns) and not has_turn_on and not has_turn_off

        if has_query:
            result["query"] = True
            result["action"] = "query"
        elif has_turn_off:
            result["action"] = "turn_off"
        elif has_turn_on:
            result["action"] = "turn_on"

        return result

    def _parse_appliance(self, text: str, result: Dict[str, Any]) -> Dict[str, Any]:
        has_turn_off = any(kw in text for kw in ["关闭", "关掉", "停止", "暂停", "关"])
        has_turn_on = any(kw in text for kw in ["打开", "开启", "启动", "开始", "开"])

        query_keywords = [
            "状态", "多少度", "温度", "几度", "洗完了吗", "好了吗",
            "还要多久", "剩余时间", "还剩多久", "多久", "结束",
            "工作", "运行", "在干嘛", "在做什么", "门关好没", "门没关"
        ]
        has_explicit_query = any(kw in text for kw in query_keywords)
        has_query = has_explicit_query or (not has_turn_on and not has_turn_off)

        if has_query:
            result["query"] = True
            result["action"] = "query"
        elif has_turn_off:
            result["action"] = "turn_off"
        elif has_turn_on:
            result["action"] = "turn_on"

        return result

    def parse_command(self, text: str) -> Optional[Dict[str, Any]]:
        cmd_id = self.find_matching_command(text)
        if not cmd_id:
            return None

        cmd_config = self.commands[cmd_id]
        device_type = getattr(cmd_config, 'device_type', 'climate')

        appliance_types = ("refrigerator", "dishwasher", "washing_machine", "dryer")

        result = {
            "command_id": cmd_id,
            "name": cmd_config.name,
            "entity_id": cmd_config.entity_id,
            "device_type": device_type,
            "action": None,
            "temperature": None,
            "mode": None,
            "fan_mode": None,
            "query": False,
            "room": None,
            "segment_id": None,
            "clean_mode": None,
            "repeats": 1
        }

        if device_type == "climate":
            result = self._parse_climate(text, result)
        elif device_type == "vacuum":
            result = self._parse_vacuum(text, result, cmd_config)
        elif device_type in ("light", "switch", "fan", "cover", "curtain"):
            result = self._parse_switch_light(text, result)
        elif device_type in appliance_types:
            result = self._parse_appliance(text, result)
        else:
            result = self._parse_appliance(text, result)

        logger.info(f"解析指令: {text} -> {result}")
        return result
