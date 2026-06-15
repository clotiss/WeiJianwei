# 待办事项

## 1. ICP 备案
- 提交入口：[腾讯云 ICP 备案](https://console.cloud.tencent.com/beian)
- 个人备案约 7-20 个工作日
- 备案通过前：用开发者工具模拟器测试
- 备案通过后：切换回域名

## 2. 切换域名
- `miniprogram/app.js` 第 7 行 `API_BASE` 改为 `https://wjwjwjw.top/api/v1`

## 3. 微信公众平台配置
- 添加服务器域名白名单：`https://wjwjwjw.top`
- 申请订阅消息模板 ID，替换 `pages/index/index.js` 中的 `YOUR_TEMPLATE_ID`

## 4. 上传小程序
- 微信开发者工具 → 上传 → 版本号 0.1.0
- 微信公众平台 → 版本管理 → 选为体验版
- 体验版测试通过后 → 提交审核

## 5. 可选优化
- 申请正式 SSL 证书续期提醒
- 服务器监控和日志轮转
