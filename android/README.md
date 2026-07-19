# 灵山小向导 Android APK

原生 Android WebView 外壳，默认打开：

`https://lingshanguide.de5.net/`

支持 WebRTC 数字人、麦克风语音输入、拍照/文件上传和浏览器定位。模型、RAG、语音和 LiveTalking 继续在服务器运行，APK 不包含模型权重。

## 构建

```bash
cd /home/gmn/codes/cup
bash android/build-apk.sh
```

构建产物会复制到：

`services/api/static/downloads/lingshan-guide-v1.0.1.apk`

当前 Release APK 使用 Android Debug 签名，适合直接下载、测试和比赛演示。若发布到应用商店，需要改用长期保存的正式签名密钥并递增 `versionCode`。
