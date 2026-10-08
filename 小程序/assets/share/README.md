# 本地分享卡片素材

背景来自既有分享设计，包含 AI 生成的「好名书中来」红印；姓名、出处、标签由 Canvas 2D 在设备上绘制。

姓名字体使用用户提供的 LXGWZhenKaiGB-Regular.ttf，版权信息：Copyright 2022, 2024–2026 LXGW；Copyright 2020 The Klee Project Authors。SIL Open Font License 1.1，见 OFL.txt 与字体内部元数据。

姓名字体现在只映射汉字，不包含拉丁字符、数字、标点或兼容汉字码位。字表共 16,538 字，涵盖《通用规范汉字表》全部 8,105 字及 8,433 个额外生僻字。

筛选依据 Unicode 17.0 Unihan：规范字通过 kTGHZ2013 保留（包括简繁共用字）；额外生僻字必须有大陆来源 kIRG_GSource，OpenCC t2s 转换后保持不变，且没有指向另一字形的 kSimplifiedVariant。非规范生僻字的繁简关系可能存在未收录项，这套规则不将“没有转换映射”解释为经过官方规范审定。

来源：https://www.unicode.org/Public/17.0.0/ucd/Unihan.zip 、 https://www.unicode.org/reports/tr38/ 、 https://github.com/BYVoid/OpenCC 。

原始 TTF 17,545,474 字节；纯汉字 TTF 12,287,672 字节；纯汉字 WOFF2 6,821,092 字节。保留生僻字后的体积大于旧 GB2312 子集，这是字数从 6,763 扩展至 16,538 所致。

再生成：`python 脚本/精简分享字体.py <原始字体.ttf> <Unihan.zip> --install`。脚本会核验全部 8,105 个规范字和输出字体 cmap，输出完整 TTF / WOFF2 / 字表 / 大小及文件 SHA256。

按每组最多 2,500 个汉字拆成 7 个子集，以 base64 JS 模块保存在 share-font-a 至 share-font-g 分包，通过 require.async 按需加载，wx.loadFontFace 的 native scope 用于 Canvas。字体包不依赖自建服务器下载。字体加载失败时回退到系统 serif；图片仍保留全部文字与红印。

分享接口传 include_image=false，仅获取 token；默认的服务端图片返回行为保留供旧版客户端使用。
