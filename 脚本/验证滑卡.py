"""滑卡交互回归：拦截模型和收藏接口，不调用真实模型、不修改数据库。"""
import argparse
import json
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

名字组 = ["清和", "知远", "望舒", "怀瑾", "景行", "安宁", "修竹", "云舟", "乐山", "书宁", "允文", "若溪",
         "承泽", "思齐", "予安", "照临", "时雨", "景初", "闻溪", "静川", "嘉言", "明舒", "松月", "星野"]


def 一批(请求, 编号, 起点=0):
    长度 = 请求.get("名字长度", 2)
    return {"任务编号": f"run-{编号}", "状态": "完成", "候选": [
        {"姓名": 请求["姓氏"] + x[:长度], "名字": x[:长度], "拼音带调": "qing1 he2",
         "现代释义": "清澄而温和，愿心中有清风，待人有暖意。此处为页面验收用的示例释义。",
         "文化标签": ["温润谦和", "清朗自然"], "书名": "诗经", "篇章": "测试篇章",
         "原文": "惠风和畅，清和有致。", "取字方式": "原文连取", "原文位置": 5,
         "来源片段编号": 1, "出处核验状态": "待核验", "五行匹配": {"已知字符": {}, "说明": "五行仅作传统取名参考。"}}
        for x in 名字组[起点:起点+12]]}


def 主程序():
    参数器 = argparse.ArgumentParser()
    参数器.add_argument("--地址", default="http://127.0.0.1:8000")
    参数器.add_argument("--截图目录")
    参数 = 参数器.parse_args()
    with sync_playwright() as 驱动:
        浏览器 = 驱动.chromium.launch(channel="msedge", headless=True)
        环境 = 浏览器.new_context(viewport={"width": 1365, "height": 1024}, reduced_motion="reduce")
        页面 = 环境.new_page()
        错误 = []
        页面.on("pageerror", lambda e: 错误.append(str(e)))
        生成请求, 待响应, 收藏请求, 收藏 = [], [], [], []
        def 路由(route):
            req = route.request
            path = req.url
            if path.endswith("/api/name-runs") and req.method == "POST":
                数据 = req.post_data_json
                生成请求.append(数据)
                if len(生成请求) == 2: 待响应.append(route)
                elif len(生成请求) == 1: route.fulfill(json=一批(数据, 1))
                else: route.fulfill(status=503, json={"detail": "测试：下一批暂时不可用"})
            elif "/api/favorites" in path and req.method == "POST":
                收藏请求.append(req.post_data_json)
                if len(收藏请求) == 1: route.fulfill(status=503, json={"detail": "测试：收藏连接中断"})
                else:
                    收藏.append({"id": len(收藏), "full_name": req.post_data_json["full_name"], "book": "诗经", "section_title": "测试篇章"})
                    route.fulfill(json={"状态": "已收藏"})
            elif "/api/favorites" in path: route.fulfill(json={"结果": 收藏})
            else: route.fulfill(json={"任务": [], "结果": []})
        页面.route("**/api/**", 路由)
        页面.goto(参数.地址)
        expect(页面.locator("#条件弹窗")).to_be_visible()
        页面.locator("#姓氏").fill("李")
        页面.get_by_role("button", name="开始遇见名字", exact=True).click()
        expect(页面.locator(".名字行 h2")).to_have_text("李清和")
        expect(页面.locator("#预载状态")).to_contain_text("下一组正在准备")
        assert len(生成请求) == 2
        assert len(生成请求[1]["排除名字"]) == 12
        页面.locator("#跳过").click()
        expect(页面.locator(".名字行 h2")).to_have_text("李知远")
        页面.locator("#撤回").click()
        expect(页面.locator(".名字行 h2")).to_have_text("李清和")
        页面.keyboard.press("ArrowRight")
        expect(页面.locator(".名字行 h2")).to_have_text("李知远")
        expect(页面.locator("#同步文字")).to_contain_text("暂未同步")
        assert 收藏请求[0]["run_id"] == "run-1" and 收藏请求[0]["full_name"] == "李清和"
        页面.locator("#重试收藏").click()
        expect(页面.locator("#收藏同步提示")).to_be_hidden()
        assert 收藏请求[1] == 收藏请求[0]
        待响应.pop().fulfill(json=一批(生成请求[1], 2, 12))
        expect(页面.locator("#预载状态")).to_contain_text("23 个名字")
        expect(页面.locator(".名字行 h2")).to_have_text("李知远")
        卡 = 页面.locator(".滑动卡").bounding_box()
        x, y = 卡["x"] + 卡["width"] / 2, 卡["y"] + 145
        页面.mouse.move(x, y); 页面.mouse.down(); 页面.mouse.move(x-145, y+4, steps=8); 页面.mouse.up()
        expect(页面.locator(".名字行 h2")).to_have_text("李望舒")
        页面.mouse.move(x, y); 页面.mouse.down(); 页面.mouse.move(x+3, y+120, steps=8); 页面.mouse.up()
        expect(页面.locator(".名字行 h2")).to_have_text("李望舒")
        页面.reload()
        expect(页面.locator("#条件弹窗")).to_be_hidden()
        expect(页面.locator("#姓氏摘要")).to_contain_text("李姓")
        expect(页面.locator(".名字行 h2")).to_have_text("李望舒")
        assert len(生成请求) == 2, "刷新不应丢弃已经准备好的卡片"
        if 参数.截图目录:
            目录 = Path(参数.截图目录); 目录.mkdir(parents=True, exist_ok=True)
            页面.screenshot(path=str(目录 / "滑卡-桌面.png"), full_page=True)
        页面.set_viewport_size({"width": 390, "height": 844})
        assert 页面.evaluate("document.documentElement.scrollWidth <= innerWidth"), "移动端横向溢出"
        if 参数.截图目录: 页面.screenshot(path=str(目录 / "滑卡-手机.png"), full_page=True)
        for _ in range(10): 页面.locator("#跳过").click()
        expect(页面.locator(".名字行 h2")).to_have_text("李承泽")
        页面.locator("#收藏").click()
        expect(页面.locator(".名字行 h2")).to_have_text("李思齐")
        expect(页面.locator("#收藏同步提示")).to_be_hidden()
        assert 收藏请求[-1]["run_id"] == "run-2"
        expect(页面.locator("#预载状态")).to_contain_text("暂时不可用")
        assert len(生成请求) == 3, "失败后不应自动无限重试"
        页面.get_by_role("button", name="心动收藏").click()
        expect(页面.locator("#收藏列表")).to_contain_text("李清和")
        expect(页面.locator("#收藏列表")).to_contain_text("李承泽")
        环境.close()

        环境 = 浏览器.new_context(reduced_motion="reduce")
        页面 = 环境.new_page()
        页面.on("pageerror", lambda e: 错误.append(str(e)))
        挂起, 请求表 = [], []
        def 切换路由(route):
            if route.request.method == "POST":
                req = route.request.post_data_json; 请求表.append(req)
                if len(请求表) == 1: 挂起.append(route)
                elif len(请求表) == 2: route.fulfill(json=一批(req, 2))
                else: route.fulfill(status=503, json={"detail": "测试暂停预载"})
            else: route.fulfill(json={"结果": []})
        页面.route("**/api/**", 切换路由)
        页面.goto(参数.地址)
        页面.locator("#姓氏").fill("李")
        页面.get_by_role("button", name="开始遇见名字", exact=True).click()
        expect(页面.locator("#预载状态")).to_contain_text("正在细读")
        页面.locator("#编辑条件").click()
        页面.locator("#姓氏").fill("张")
        页面.get_by_role("button", name="开始遇见名字", exact=True).click()
        assert len(请求表) == 1
        挂起.pop().fulfill(json=一批(请求表[0], 1))
        expect(页面.locator(".名字行 h2")).to_have_text("张清和")
        队列 = 页面.evaluate("JSON.parse(localStorage.getItem('起名滑卡v1:' + localStorage.getItem('起名收藏夹'))).队列")
        assert all(x["项目"]["姓名"].startswith("张") for x in 队列)
        环境.close()
        # 使用真实触摸事件验证手机左右滑，而不是只改变桌面视口大小。
        环境 = 浏览器.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True, reduced_motion="reduce")
        页面 = 环境.new_page()
        页面.on("pageerror", lambda e: 错误.append(str(e)))
        手机收藏, 手机生成 = [], []
        def 手机路由(route):
            if route.request.url.endswith("/api/name-runs"):
                手机生成.append(route.request.post_data_json)
                route.fulfill(json=一批(手机生成[-1], len(手机生成), 0 if len(手机生成) == 1 else 12))
            elif route.request.method == "POST":
                手机收藏.append(route.request.post_data_json)
                route.fulfill(json={"状态": "已收藏"})
            else: route.fulfill(json={"结果": []})
        页面.route("**/api/**", 手机路由)
        页面.goto(参数.地址)
        页面.locator("#姓氏").fill("欧阳")
        页面.get_by_role("button", name="开始遇见名字", exact=True).click()
        expect(页面.locator(".名字行 h2")).to_have_text("欧阳清和")
        expect(页面.locator("#预载状态")).to_contain_text("24 个名字")
        通道 = 环境.new_cdp_session(页面)
        def 触摸滑动(偏移):
            框 = 页面.locator(".滑动卡").bounding_box()
            x, y = 框["x"] + 框["width"] / 2, 框["y"] + 145
            通道.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": x, "y": y}]})
            for 步 in range(1, 9):
                通道.send("Input.dispatchTouchEvent", {"type": "touchMove", "touchPoints": [{"x": x + 偏移 * 步 / 8, "y": y}]})
            通道.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
        触摸滑动(-135)
        expect(页面.locator(".名字行 h2")).to_have_text("欧阳知远")
        触摸滑动(135)
        expect(页面.locator(".名字行 h2")).to_have_text("欧阳望舒")
        expect(页面.locator("#收藏同步提示")).to_be_hidden()
        assert 手机收藏[0]["full_name"] == "欧阳知远"
        assert 页面.evaluate("document.documentElement.scrollWidth <= innerWidth")
        assert not 错误, 错误
        环境.close(); 浏览器.close()
        print(json.dumps({"状态": "通过", "模式": "模拟接口，不调用真实模型", "检查": ["滑动与键盘", "撤回跳过", "后台预加载", "跨批收藏归属", "收藏失败保留及重试", "刷新续看", "记住姓氏", "旧条件响应隔离", "预载失败保留卡片", "移动端布局"], "网页异常": 错误}, ensure_ascii=False))


if __name__ == "__main__":
    主程序()
