# 本地分享卡片素材

背景来自既有分享设计，包含 AI 生成的「好名书中来」红印；姓名、出处、标签由 Canvas 2D 在设备上绘制。

姓名字体使用用户提供的 LXGWZhenKaiGB-Regular.ttf，版权信息：Copyright 2022, 2024–2026 LXGW；Copyright 2020 The Klee Project Authors。SIL Open Font License 1.1，见 OFL.txt 与字体内部元数据。

GB2312 字表保留 6,763 个汉字、标点和基础拉丁字符，共 7,540 个码位。完整字体映射 23,878 个码位。子集 TTF 为 4,756,964 字节，WOFF2 为 2,632,272 字节；原始 TTF 为 17,545,474 字节，完整 WOFF2 为 9,524,684 字节。

拆为两个字体子集，以 base64 JS 模块保存在 share-font-a / share-font-b 分包，通过 require.async 按需加载，wx.loadFontFace 的 native scope 用于 Canvas。包内不依赖自建服务器下载字体。字表以外的字或字体加载失败时回退到系统 serif；图片仍保留全部文字与红印。

字体的二进制压缩体积和 base64 分包体积不同：分包字体模块分别约 1.44 MiB、1.94 MiB，主包约 302 KiB。每个分包均符合 2 MiB 限制。

分享接口传 include_image=false，仅获取 token；默认的服务端图片返回行为保留供旧版客户端使用。
