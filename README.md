# XiaoAI HA Bridge

小爱音箱 → Home Assistant 桥接服务，让小爱同学控制非米家智能设备。

## 功能

- 🎤 捕获小爱音箱语音指令（通过 xiaomi_miot 集成）
- 🌡️ 控制非米家空调（格力、美的等）
- 🤖 控制追觅扫地机器人（分区清扫、自清洁）
- 🧊 查询冰箱温度/状态（海尔等）
- 👕 控制洗衣机/烘干机（海尔等）
- 📱 Web 管理界面（设备发现、配置、测试）
- 🔔 手机通知推送（清扫完成等）

## 快速开始

### Docker 部署

```bash
docker run -d \
  --name xiaoai-ha \
  -p 18000:8000 \
  -v /path/to/config:/app/config \
  ghcr.io/baigougou/xiaoai-home-assistant:latest
```

### 配置

1. 访问 `http://你的NAS_IP:18000`
2. 在「连接配置」Tab 填写 HA 地址和 Token
3. 在「设备管理」Tab 扫描并添加设备
4. 在「指令测试」Tab 测试语音命令

## 设备类型支持

| 类型 | 说明 | 示例命令 |
|------|------|---------|
| 空调 | 格力/美的等非米家空调 | "打开主卧空调" "空调多少度" |
| 扫地机 | 追觅等，支持分区清扫 | "扫拖客厅" "仅拖厨房" |
| 冰箱 | 海尔等，查询温度状态 | "冰箱多少度" "冰箱状态" |
| 洗衣机 | 海尔等 | "洗衣机状态" "洗衣机开始" |
| 烘干机 | 海尔等 | "烘干机还要多久" |

## 开发

```bash
pip install -r requirements.txt
cd src && python -m xiaoai_ha_bridge.main
```
