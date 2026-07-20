# 定位点配置 schema 与上线前采集清单

定位服务支持两种运行模式（见 `services/api/app/location.py` 的 `_load_location_config`）：

- `demo`（默认）：使用代码内置的 5 个 GPS 演示锚点 + 4 个手动 Wi-Fi 静态节点。
- `production`：当存在 `data/lingshan/location_points.json` 时自动切换，使用景区实测坐标与真实节点。

> 当前为 `demo` 模式。上线前请按下方 schema 采集实测数据并写入
> `data/lingshan/location_points.json`，服务重启后即自动生效，无需改代码。

## data/lingshan/location_points.json

```json
{
  "gps_anchors": {
    "LS-001": {"name": "灵山大照壁", "lat": 31.41480, "lng": 120.99750},
    "LS-006": {"name": "九龙灌浴",   "lat": 31.41720, "lng": 120.99840},
    "LS-011": {"name": "灵山大佛",   "lat": 31.42210, "lng": 120.99860},
    "LS-013": {"name": "灵山梵宫",   "lat": 31.41920, "lng": 121.00260},
    "LS-014": {"name": "五印坛城",   "lat": 31.42030, "lng": 121.00460}
  },
  "wifi_anchors": {
    "LS-WIFI-SOUTH":  {"spot_id": "LS-001", "name": "南门入口区"},
    "LS-WIFI-NINE":   {"spot_id": "LS-006", "name": "九龙灌浴区"},
    "LS-WIFI-BUDDHA": {"spot_id": "LS-011", "name": "灵山大佛区"},
    "LS-WIFI-BRAHMA": {"spot_id": "LS-013", "name": "灵山梵宫区"}
  }
}
```

字段说明：
- `gps_anchors`：key 为景点 `spot_id`（与 `attractions.py` 的 `id` 一致），值为 WGS-84 经纬度。
  GPS 自动匹配半径见 `location.py` 的 `GPS_MATCH_RADIUS_M=320` / `GPS_CANDIDATE_RADIUS_M=600`。
- `wifi_anchors`：key 为节点代号，`spot_id` 指向所属景点。当前是"手动选区域节点"，
  **未读取真实 BSSID**；上线前需替换为真实 BSSID→景点映射或改用蓝牙信标方案。

## 上线前采集清单

1. **GPS 实测坐标**：为全部 22 个子景点（灵山 16 + 拈花湾 6）采集 WGS-84 经纬度，
   每点建议在主体建筑正前方采集 3–5 次取平均，精度优于 10m。室内/遮挡区不强配 GPS，
   交给二维码/蓝牙。
2. **二维码物料**：二维码点位由 `attractions.py` 自动派生（22 个子景点），印刷物料上的
   `spot_id` 需与系统一致（如 `LS-011`）。核对印刷码与系统码一一对应。
3. **室内蓝牙/Wi-Fi 定位**：梵宫、拈花湾室内等 GPS 遮挡区，部署蓝牙信标或真实 Wi-Fi BSSID
   采集，建立 BSSID/信标 → 景点映射，替换 `wifi_anchors`。需前端配合实现真实 BSSID 扫描
   （浏览器受限，通常需原生壳或景区小程序）。
4. **界面口径**：游客端定位面板已标注"定位结果为候选，需要确认"；上线后若实测精度达标，
   可在 `location.py` 调整 `GPS_GOOD_ACCURACY_M` / `GPS_MATCH_RADIUS_M` 放宽自动确认阈值。

## 管理接口

- `GET /v1/admin/location/config`：查看当前 GPS/Wi-Fi 配置与模式。
- `PUT /v1/admin/location/config`：写入 `location_points.json`（需 `gps_anchors`/`wifi_anchors`）。
