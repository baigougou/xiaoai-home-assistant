# XiaoAI Home Assistant Bridge - 优化报告

> 生成时间: 2026-07-13  
> 目标 HA: `https://ha.catop.cf:14444` (v2026.7.2)  
> 实体总数: 1987 | 自动化: 54

---

## 一、项目概况

从 GitHub 项目 [baigougou/xiaoai-home-assistant](https://github.com/baigougou/xiaoai-home-assistant) 拉取源码后，基于用户实际 Home Assistant 环境进行了全面优化适配。

### 优化前后对比

| 优化项 | 原始项目 | 优化后 |
|--------|---------|--------|
| TTS 服务 | `xiaomi_miot_raw.execute_text` / `play_text` | `xiaomi_miot.intelligent_speaker` |
| 小爱音箱实体 | 示例占位 | 3台真实音箱实体 |
| 空调设备 | 示例格力/美的 | 5台真实空调 (格力×2 + 客厅/老人房/书房) |
| 扫地机器人 | 无 | 追觅S30 铂金版 |
| 灯具控制 | 无 | 7个主要区域灯具 |
| 窗帘控制 | 无 | 8个窗帘/纱帘 |
| 浴霸 | 无 | 2个(主卧+公卫) |
| 设备绑定总数 | 4个示例 | 21个真实设备 |

---

## 二、核心修改详情

### 2.1 关键服务适配 ⚠️

**问题**: 用户的 HA 没有 `xiaomi_miot_raw` 集成，只有 `xiaomi_miot`。且该集成不提供 `execute_text`/`play_text` 服务，而是统一使用 `intelligent_speaker`。

**修改文件**: `ha_client/client.py`, `config/config.py`

```python
# 原始代码 (不适用于用户环境)
await self.call_service("xiaomi_miot_raw", "execute_text", entity_id, {"text": text})
await self.call_service("xiaomi_miot_raw", "play_text", entity_id, {"text": text})

# 优化后 (匹配用户 xiaomi_miot 集成)
await self.call_service("xiaomi_miot", "intelligent_speaker", entity_id, {
    "text": text, "execute": True, "silent": False
})
await self.call_service("xiaomi_miot", "intelligent_speaker", entity_id, {
    "text": text, "execute": False
})
```

### 2.2 小爱音箱选择策略

用户有 9 个 media_player 实体，经过分析选择策略如下：

| 集成 | 实体 | 状态 | 选择 |
|------|------|------|------|
| **xiaomihome** | `media_player.xiaomi_lx06_dd28_play_control` | idle ✓ | ✅ 客厅 |
| **xiaomihome** | `media_player.xiaomi_lx06_69fe_play_control` | idle ✓ | ✅ 主卧 |
| **xiaomihome** | `media_player.xiaomi_lx06_174f_play_control` | idle ✓ | ✅ 小孩房 |
| xiaomiiot | `media_player.xiaomi_cn_862652763_lx06` | unavailable ✗ | ❌ |
| xiaomiiot | `media_player.xiaomi_cn_862688817_lx06` | unavailable ✗ | ❌ |
| xiaomiiot | `media_player.xiaomi_cn_862667650_lx06` | unavailable ✗ | ❌ |

> **策略**: 选择 xiaomihome 的 `play_control` 实体。xiaomiiot 的对应音箱实体状态不可用。

### 2.3 按设备选择集成策略

| 设备类别 | 推荐集成 | 原因 |
|----------|---------|------|
| 小爱音箱 | **xiaomihome** | play_control 实体状态正常，xiaomiiot 不可用 |
| 门锁 M20 Pro | **xiaomiiot** | 提供 6/7 自动化关键事件(门铃、异常、门锁事件、猫眼电池等) |
| 灯具/开关 | **xiaomihome** | 实体状态正常，响应快 |
| 窗帘电机 | **xiaomihome** | Dooya 电机通过 xiaomihome 接入 |
| 空调(格力) | **gree** 集成 | 通过 Gree Climate 集成直接接入 |

---

## 三、设备绑定清单 (21个)

### 空调 (7个)

| 命令ID | 名称 | 实体ID | 关键词 |
|--------|------|--------|--------|
| `gree_main_ac` | 主卧空调 | `climate.gree_climate` | 主卧空调, 卧室空调 |
| `gree_kids_ac` | 小孩房空调 | `climate.gree_climate_2` | 小孩房空调, 儿童房空调 |
| `living_ac` | 客厅空调 | `climate.lemesh_cn_2043596866_b27m` | 客厅空调, 大厅空调 |
| `elder_ac` | 老人房空调 | `climate.210006737191564_thermostat` | 老人房空调, 长辈房空调 |
| `study_ac` | 书房空调 | `climate.210006737186322_thermostat` | 书房空调 |
| `master_bath_heater` | 主卧浴霸 | `climate.yeelink_cn_822085204_v13` | 主卧浴霸, 主卫浴霸 |
| `public_bath_heater` | 公卫浴霸 | `climate.yeelink_cn_822093474_v13` | 公卫浴霸, 客卫浴霸 |

### 扫地机器人 (1个)

| 命令ID | 名称 | 实体ID | 关键词 |
|--------|------|--------|--------|
| `vacuum_dreame` | 追觅S30 | `vacuum.zhui_mi_s30_bo_jin_ban` | 追觅, 扫地机, 扫地机器人, S30 |

### 灯具 (7个)

| 命令ID | 名称 | 实体ID |
|--------|------|--------|
| `living_main_light` | 客厅主灯 | `light.lemesh_cn_1101693473_wy0c09_s_2_2` |
| `dining_light` | 餐厅灯 | `light.lemesh_cn_1116703024_wy0c15_s_2_light` |
| `master_bed_light` | 主卧灯 | `light.lemesh_cn_944187535_wy0a22_s_2_light` |
| `kids_room_light` | 小孩房灯 | `light.lemesh_cn_1119143543_wy0c15_s_2_light` |
| `elder_room_light` | 老人房灯 | `light.lemesh_cn_1119141594_wy0c15_s_2_light` |
| `study_light` | 书房灯 | `light.lemesh_cn_1119142071_wy0c15_s_2_light` |
| `corridor_light` | 走廊灯 | `light.lemesh_cn_1115875946_wy0c15_s_2_light` |

### 窗帘 (6个)

| 命令ID | 名称 | 实体ID |
|--------|------|--------|
| `living_curtain` | 客厅窗帘 | `cover.dooya_cn_2002611066_dt98_s_2_curtain` |
| `master_curtain` | 主卧布帘 | `cover.dooya_cn_2002453892_dt98_s_2_curtain` |
| `master_sheer_curtain` | 主卧纱帘 | `cover.dooya_cn_2002508023_dt98_s_2_curtain` |
| `kids_curtain` | 小孩房窗帘 | `cover.dooya_cn_2001805496_dt98_s_2_curtain` |
| `elder_curtain` | 老人房窗帘 | `cover.dooya_cn_2022403134_dt98_s_2_curtain` |
| `study_curtain` | 书房窗帘 | `cover.dooya_cn_2001805533_dt98_s_2_curtain` |

### 其他 (1个)

| 命令ID | 名称 | 实体ID |
|--------|------|--------|
| `clothes_rack` | 晾衣架 | `cover.jns_cn_742251944_1_s_2_airer` |

---

## 四、支持语音指令示例

### 空调控制
- "打开主卧空调" → 打开主卧格力空调
- "小孩房空调调到26度" → 设置小孩房空调26°C
- "客厅空调开制冷" → 客厅空调制冷模式
- "老人房空调26度开制热" → 老人房空调制热26°C
- "书房空调多少度" → 查询书房空调状态
- "主卧浴霸打开" → 打开主卧浴霸

### 扫地机器人
- "扫地机开始打扫" → 追觅S30全屋清扫
- "追觅扫拖客厅" → 指定区域扫拖
- "扫地机器人回去充电" → 回充
- "扫地机暂停" → 暂停清扫

### 灯光/窗帘
- "打开客厅主灯" → 开客厅灯
- "关闭主卧灯" → 关主卧灯
- "打开客厅窗帘" → 开客厅窗帘
- "关闭主卧布帘" → 关主卧布帘

---

## 五、部署说明

### 方式一：Docker Compose (推荐)

```bash
cd xiaoai-home-assistant

# 1. 编辑 API Token
nano config/config.json  # 替换 YOUR_HA_LONG_LIVED_ACCESS_TOKEN_HERE

# 2. 启动
docker-compose up -d

# 3. 访问 Web 界面
# http://你的NAS-IP:8000
```

### 方式二：本地运行

```bash
cd xiaoai-home-assistant
pip install -r requirements.txt
PYTHONPATH=src python -m uvicorn xiaoai_ha_bridge.main:app --host 0.0.0.0 --port 8000
```

### 前置条件

1. Home Assistant 已安装 **Xiaomi Miot Auto** 集成
2. 小爱音箱已开启 **Action 调试模式**（在 Xiaomi Miot Auto 设备配置中）
3. 确认 HA 地址和 Token 在 `config/config.json` 中正确配置

---

## 六、注意事项

1. **API Token**: 配置文件中 `api_token` 需要替换为实际的 HA 长期访问令牌
2. **SSL 证书**: 用户 HA 使用自签名证书，已配置 `verify=False`（在 httpx 中默认不验证）
3. **小爱音箱**: 需要在 Xiaomi Miot Auto 集成中为每台音箱开启 Action 调试模式
4. **门锁 M20 Pro**: 目前仅作为传感器/事件使用，不支持语音控制开锁（安全考虑）
5. **窗帘**: 当前作为 switch 类型处理（开/关），如需百分比控制可后续升级

---

## 七、文件清单

```
xiaoai-home-assistant/
├── config/
│   └── config.json                  ← 优化后的配置 (需填入API Token)
├── src/xiaoai_ha_bridge/
│   ├── main.py                      ← FastAPI 主入口
│   ├── config/config.py             ← 配置模型 (已更新默认服务名)
│   ├── engine/
│   │   ├── parser.py                ← 指令解析引擎
│   │   └── interceptor.py           ← 指令拦截执行
│   ├── ha_client/
│   │   └── client.py                ← HA API 客户端 (已适配 xiaomi_miot)
│   ├── miservice/poller.py          ← 音箱轮询服务
│   ├── web/
│   │   ├── routes.py                ← Web API 路由
│   │   └── index.html               ← Web 配置界面
│   └── logging/logger.py            ← 日志管理
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── README.md
```
