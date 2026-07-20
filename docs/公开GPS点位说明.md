# 公开 GPS 点位说明

当前点位用于比赛演示和现场采点前的初始定位，坐标统一为 WGS-84。它们来自公开地图或公开照片的地理标签，不是景区运营方实测数据，因此游客端只会给出候选景点并要求确认，不会据此直接认定位置。

| ID | 景点 | 纬度 | 经度 | 公开来源 | 估计地标级误差 |
|---|---|---:|---:|---|---:|
| LS-006 | 九龙灌浴 | 31.426620 | 120.095240 | [OpenStreetMap way 1359777214](https://www.openstreetmap.org/way/1359777214) | 50 m |
| LS-010 | 祥符禅寺 | 31.429860 | 120.093090 | [OpenStreetMap way 303420710](https://www.openstreetmap.org/way/303420710) | 60 m |
| LS-011 | 灵山大佛 | 31.432050 | 120.091510 | [OpenStreetMap node 606957371](https://www.openstreetmap.org/node/606957371) | 35 m |
| LS-013 | 灵山梵宫 | 31.430650 | 120.097560 | [OpenStreetMap way 215163091](https://www.openstreetmap.org/way/215163091) | 70 m |
| LS-014 | 五印坛城 | 31.426640 | 120.098130 | [OpenStreetMap way 303420711](https://www.openstreetmap.org/way/303420711) | 60 m |
| NH-002 | 梵天花海 | 31.416326 | 120.068877 | [Wikimedia Commons 实景照片](https://commons.wikimedia.org/wiki/File:灵山小镇拈花湾20200913_35.jpg) | 100 m |
| NH-003 | 香月花街 | 31.419480 | 120.069110 | [Wikimedia Commons 实景照片](https://commons.wikimedia.org/wiki/File:灵山小镇拈花湾20200912_04.jpg) | 100 m |
| NH-005 | 五灯湖 | 31.420621 | 120.071103 | [Wikimedia Commons 实景照片](https://commons.wikimedia.org/wiki/File:灵山小镇拈花湾20200912_03.jpg) | 90 m |
| NH-006 | 鹿鸣谷 | 31.428342 | 120.074948 | [Wikimedia Commons 实景照片](https://commons.wikimedia.org/wiki/File:灵山小镇拈花湾20200913_05.jpg) | 120 m |

未加入公开 GPS 锚点的景点仍可通过景点二维码或手动选择。后续取得现场实测结果时，应将点位的 `survey_status` 改为 `field-verified`，并记录测量日期、设备、样本数和水平精度。

OpenStreetMap 数据按 ODbL 使用；Wikimedia Commons 照片页面及地理标签应按各文件页面标注的许可和署名要求使用。
