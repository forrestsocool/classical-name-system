# 本地分享卡片素材

背景来自既有分享设计，包含 AI 生成的「好名书中来」红印；姓名、出处、标签由 Canvas 2D 在设备上绘制。

姓名字体使用用户提供的 LXGWZhenKai.ttf（2022 版本），版权信息：Copyright 2022 LXGW；Copyright 2020 The Klee Project Authors。SIL Open Font License 1.1，见 OFL.txt 与字体内部元数据。

仅保留 GB2312 汉字，不包含拉丁字符、数字或标点。源字体覆盖 6,760 个 GB2312 汉字，缺少「軎、麴、齄」。字表之外的字符回退系统 serif，文字不会消失。

原始 TTF 3,881,034 字节；汉字子集 TTF 3,192,160 字节；完整汉字子集 WOFF2 1,682,268 字节。

再生成：`python 脚本/生成GB2312分享字体.py <LXGWZhenKai.ttf>`。脚本核验字表、字体 cmap 与单包大小。

拆为两个字体子集，以 base64 JS 模块保存在 share-font-a / share-font-b 分包，通过 require.async 按需加载，wx.loadFontFace 的 native scope 用于 Canvas。字体包不依赖自建服务器下载。加载失败时回退系统字体，图片仍保留全部文字与红印。

分享接口传 include_image=false，仅获取 token；默认的服务端图片返回行为保留供旧版客户端使用。
