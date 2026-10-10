# 本地分享卡片素材

背景来自既有分享设计，包含 AI 生成的「好名书中来」红印；姓名、出处、标签由 Canvas 2D 在设备上绘制。

姓名字体改用 LXGWWenKai-Medium.ttf（霞鹜文楷 Medium，v1.522）。版权信息保留在各字形分包模块中。SIL Open Font License 1.1，见 OFL.txt 与字体内部元数据。

仅保留 GB2312 汉字，不包含拉丁字符、数字或标点。源字体覆盖全部 6,763 个 GB2312 汉字。字表之外的字符回退系统 serif，文字不会消失。

iOS 兼容绘制使用原始 TrueType 字形轮廓，不再调用 wx.loadFontFace 或解析 WOFF2。保留轮廓坐标、on-curve 标志、轮廓边界和原始 advance，通过 Canvas 的线段/二次贝塞尔曲线填充姓名；系统字体仅用于小字和字表外的汉字。

再生成：`python 脚本/生成GB2312分享字形.py <LXGWWenKai-Medium.ttf>`。脚本核验字表和单包大小，输出两个 ZIP-base64 JS 字形分包。每包只含一个 glyphs.json，不含可执行代码；在用户目录本地解压，以源字体 SHA256 摘要和编码版本隔离缓存，换字体后不会复用旧字形。首次加载后可复用，仍然不依赖自建服务器。

每个字形分包小于 2 MiB，主包包含 Canvas 绘图逻辑。字形加载失败时允许重试，已支持的汉字不会悄悄改用系统字体。

分享接口传 include_image=false，仅获取 token；默认的服务端图片返回行为保留供旧版客户端使用。
