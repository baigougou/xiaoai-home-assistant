import logging
import asyncio
from typing import Optional, Callable, Dict
from ..config.config import AppConfig
from ..ha_client.client import HomeAssistantClient

logger = logging.getLogger(__name__)

class SpeakerPoller:
    def __init__(
        self,
        config: AppConfig,
        ha_client: HomeAssistantClient,
        on_command: Optional[Callable[[str, str], bool]] = None,
        on_poll: Optional[Callable] = None
    ):
        self.config = config
        self.ha_client = ha_client
        self.on_command = on_command
        self.on_poll = on_poll
        self.running = False
        self.last_texts: Dict[str, str] = {}
        self.polling_interval = config.bridge.polling_interval
        self.retry_count = 0
        self.max_retries = 3
        self.poll_count = 0

    def update_config(self, config: AppConfig):
        self.config = config
        new_speaker_ids = set(config.get_speaker_entity_ids())
        for eid in list(self.last_texts.keys()):
            if eid not in new_speaker_ids:
                del self.last_texts[eid]

    async def start(self):
        self.running = True
        speaker_count = len(self.config.get_speaker_entity_ids())
        logger.info("开始轮询{}个小爱音箱，间隔{}秒".format(speaker_count, self.polling_interval))
        while self.running:
            try:
                await self._poll_all()
                self.poll_count += 1
                if self.on_poll and self.poll_count % 5 == 0:
                    try:
                        await self.on_poll()
                    except Exception as e:
                        logger.debug("轮询回调出错: {}".format(e))
                self.retry_count = 0
            except Exception as e:
                self.retry_count += 1
                logger.error("轮询出错: {}, 重试次数: {}".format(e, self.retry_count))
                if self.retry_count >= self.max_retries:
                    logger.error("连续{}次轮询失败，等待{}秒后重试".format(self.max_retries, self.polling_interval * 5))
                    await asyncio.sleep(self.polling_interval * 5)
                    self.retry_count = 0
            await asyncio.sleep(self.polling_interval)

    async def stop(self):
        self.running = False
        logger.info("停止轮询")

    async def _poll_all(self):
        speaker_entity_ids = self.config.get_speaker_entity_ids()
        for entity_id in speaker_entity_ids:
            try:
                await self._poll_speaker(entity_id)
            except Exception as e:
                logger.error("轮询音箱{}出错: {}".format(entity_id, e))

    async def _poll_speaker(self, entity_id: str):
        """轮询音箱对话内容。
        
        优先通过 xiaomi_miot 的 XiaoaiConversationSensor 读取，
        该 sensor 的 state 就是用户对话文本。
        conversation sensor 命名规则:
          media_player.xiaomi_lx06_xxxx_play_control
          -> sensor.xiaomi_lx06_xxxx_conversation
        """
        text = ""

        # 方案1: 通过 conversation sensor 读取（xiaomi_miot 集成）
        conv_entity_id = entity_id.replace("media_player.", "sensor.").replace("_play_control", "_conversation")
        conv_state = await self.ha_client.get_state(conv_entity_id)
        if conv_state and conv_state.get("state"):
            text = str(conv_state["state"]).strip()
            if text:
                logger.debug("[{}] 从 conversation sensor 读取: {}".format(entity_id, text))

        # 方案2: 回退 - 从 media_player 属性读取
        if not text:
            state = await self.ha_client.get_state(entity_id)
            if not state:
                return
            attributes = state.get("attributes", {})
            for key in ["last_text", "current_text", "text", "media_title",
                        "conversation_content", "last_command"]:
                if key in attributes and attributes[key]:
                    text = str(attributes[key]).strip()
                    if text:
                        logger.debug("[{}] 从 media_player 属性读取: {}".format(entity_id, text))
                        break

        if not text:
            return

        last_text = self.last_texts.get(entity_id, "")
        if text == last_text:
            return

        self.last_texts[entity_id] = text
        logger.info("[{}] 获取到语音指令: {}".format(entity_id, text))

        if self.on_command:
            handled = await self.on_command(text, entity_id)
            if handled:
                logger.info("指令已处理: {} (来自{})".format(text, entity_id))
            else:
                logger.debug("指令未匹配: {}".format(text))
