"""真实浏览器手势回归：全部业务接口拦截，不调用模型、不改变运行数据库。"""
import argparse
import json
import time
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

名字组 = ["清和","知远","望舒","怀瑾","景行","安宁","修竹","云舟","乐山","书宁","允文","若溪",
         "承泽","思齐","予安","照临","时雨","景初","闻溪","静川","嘉言","明舒","松月","星野"]
书目 = ["周易","周礼","孟子","尚书","庄子","楚辞","礼记","论语","诗经"]
当前 = ".滑动卡:not(.离场)"


def 一批(条件, 编号, 起点):
    卡片 = []
    for i, 名 in enumerate(名字组[起点:起点+8]):
        项 = {"姓名":条件["姓氏"]+名,"名字":名,"拼音带调":"qīng hé","书名":书目[(起点+i)%9],"篇章":"测试篇章",
             "现代释义":"清澄而温和，愿心中有清风，待人有暖意。此处仅为页面验收示例。","文化标签":["温润谦和","清朗自然"],
             "原文":"惠风和畅，清和有致。"*8,"原文位置":5,"取字方式":"原文连取","出处核验状态":"待核验",
             "五行匹配":{"已知字符":{},"说明":"五行仅作传统取名参考。"},
             "热门提示":{"命中":True,"提示":["仅供测试的热门提醒，不是真实榜单数据"]}}
        卡片.append({"项目":项,"任务编号":f"run-{编号}","投递编号":f"{编号}-{i}","到期时间":(time.time()+300)*1000})
    return {"队列编号":"a"*64,"卡片":卡片,"重试秒数":4,"提示":"正在从不同古籍挑选名字"}


def 主程序():
    p = argparse.ArgumentParser()
    p.add_argument("--地址",default="http://127.0.0.1:8000")
    p.add_argument("--截图目录")
    args = p.parse_args()
    目录 = Path(args.截图目录) if args.截图目录 else None
    if 目录: 目录.mkdir(parents=True,exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe",headless=True)
        错误, 已确认, 请求, 收藏请求, 收藏 = [], [], [], [], []
        def 安装(page, 挂起首批=False):
            状态 = {"起点":0,"挂起":[],"批次":0}
            page.on("pageerror",lambda e:错误.append(str(e)))
            def 路由(route):
                req = route.request
                if req.url.endswith("/api/feed/pull"):
                    body = req.post_data_json; 请求.append(body); 状态["批次"] += 1
                    if 挂起首批 and 状态["批次"] == 1:
                        状态["挂起"].append(route); return
                    data = 一批(body["条件"],状态["批次"],状态["起点"])
                    状态["起点"] += len(data["卡片"]); route.fulfill(json=data)
                elif req.url.endswith("/api/feed/sync"):
                    data = req.post_data_json; 已确认.extend(data["已展示"])
                    route.fulfill(json={"状态":"已同步","有效租约":data["续租"]})
                elif "/api/favorites" in req.url and req.method == "POST":
                    收藏请求.append(req.post_data_json)
                    if len(收藏请求) == 1: route.fulfill(status=503,json={"detail":"测试断网"})
                    else:
                        收藏.append({"id":len(收藏)+1,"full_name":req.post_data_json["full_name"],"book":"诗经","section_title":"测试篇章"})
                        route.fulfill(json={"状态":"已收藏"})
                else: route.fulfill(json={"结果":收藏,"任务":[]})
            page.route("**/api/**",路由)
            page.goto(args.地址)
            return 状态
        def 开始(page, 姓):
            page.locator("#姓氏").fill(姓); page.get_by_role("button",name="开始遇见名字",exact=True).click()
        def 名字(page): return page.locator(当前+" .名字行 h2")
        def 关闭环境(context):
            # Playwright撤销路由后，关闭页面触发的可见性事件也不能漏到真实接口。
            for tab in context.pages:
                tab.evaluate("() => { globalThis.fetch = () => Promise.reject(new Error('测试已结束')); }")
            context.close()

        context = browser.new_context(viewport={"width":1365,"height":900})
        page = context.new_page(); 安装(page); 开始(page,"李")
        expect(名字(page)).to_have_text("李清和")
        assert page.locator(".热门提醒").count()==0
        page.locator(当前+" .打开详情").click()
        expect(page.locator("#名字详情")).to_be_visible()
        assert not page.locator(".热门详情").evaluate("e=>e.open")
        page.locator(".热门详情 summary").click()
        expect(page.locator(".热门详情")).to_contain_text("仅供测试的热门提醒")
        page.locator("#关闭详情").click()
        # 同一帧连续触发六次，不应被离场动画锁吞掉。
        page.evaluate("() => { for(let i=0;i<6;i++) document.querySelector('#跳过').click(); }")
        expect(名字(page)).to_have_text("李修竹")
        page.locator("#撤回").click(); expect(名字(page)).to_have_text("李安宁")
        page.keyboard.press("ArrowRight"); expect(名字(page)).to_have_text("李修竹")
        expect(page.locator("#收藏同步提示")).to_be_visible()
        page.locator("#重试收藏").click(); expect(page.locator("#收藏同步提示")).to_be_hidden()
        assert 收藏请求[0]==收藏请求[1] and 收藏请求[0]["run_id"]=="run-1"
        page.wait_for_timeout(2100)
        assert len(set(已确认)) < 24, "未展示的预加载卡不应曝光"
        page.reload(); expect(名字(page)).to_have_text("李修竹"); expect(page.locator("#条件弹窗")).to_be_hidden()
        if 目录: page.screenshot(path=str(目录/"滑卡-桌面.png"))
        page.get_by_role("button",name="心动收藏").click(); expect(page.locator("#收藏列表")).to_contain_text("李安宁")
        关闭环境(context)

        context = browser.new_context(viewport={"width":390,"height":844},is_mobile=True,has_touch=True)
        page = context.new_page(); 安装(page); 开始(page,"欧阳"); expect(名字(page)).to_have_text("欧阳清和")
        cdp = context.new_cdp_session(page)
        def 触摸(dx,dy=0,取消=False):
            box = page.locator(当前).bounding_box(); x,y = box["x"]+box["width"]/2,box["y"]+box["height"]*.4
            cdp.send("Input.dispatchTouchEvent",{"type":"touchStart","touchPoints":[{"x":x,"y":y}]})
            for i in range(1,9): cdp.send("Input.dispatchTouchEvent",{"type":"touchMove","touchPoints":[{"x":x+dx*i/8,"y":y+dy*i/8}]})
            cdp.send("Input.dispatchTouchEvent",{"type":"touchCancel" if 取消 else "touchEnd","touchPoints":[]})
        触摸(-130,45); expect(名字(page)).to_have_text("欧阳知远")
        触摸(130,20); expect(名字(page)).to_have_text("欧阳望舒")
        触摸(5,100); expect(名字(page)).to_have_text("欧阳望舒")
        触摸(-100,0,True); expect(名字(page)).to_have_text("欧阳望舒")
        # 卡片内双指手势不会触发页面放大，也不会误作喜欢。
        box = page.locator(当前).bounding_box(); x,y = box["x"]+100,box["y"]+120
        cdp.send("Input.dispatchTouchEvent",{"type":"touchStart","touchPoints":[{"x":x,"y":y,"id":1},{"x":x+50,"y":y,"id":2}]})
        cdp.send("Input.dispatchTouchEvent",{"type":"touchMove","touchPoints":[{"x":x-30,"y":y,"id":1},{"x":x+100,"y":y,"id":2}]})
        cdp.send("Input.dispatchTouchEvent",{"type":"touchEnd","touchPoints":[]})
        assert page.evaluate("visualViewport.scale") == 1
        expect(名字(page)).to_have_text("欧阳望舒")
        if 目录: page.screenshot(path=str(目录/"滑卡-手机.png"))
        for w,h in [(320,568),(375,667),(390,844),(844,390)]:
            page.set_viewport_size({"width":w,"height":h})
            assert page.evaluate("document.documentElement.scrollWidth<=innerWidth && document.documentElement.scrollHeight<=innerHeight"), (w,h,"页面溢出")
            for s in ["#收藏","#跳过",当前+" .打开详情"]:
                b=page.locator(s).bounding_box(); assert b and b["y"]>=0 and b["y"]+b["height"]<=h+1,(w,h,s,b)
            assert page.locator("#姓氏").evaluate("e=>parseFloat(getComputedStyle(e).fontSize)")>=16
        关闭环境(context)

        context = browser.new_context(); page=context.new_page(); state=安装(page,True); 开始(page,"李")
        page.locator("#编辑条件").click(); 开始(page,"张")
        expect(名字(page)).to_have_text("张清和")
        assert state["批次"]>=2, "新条件不能等旧请求结束"
        for route in state["挂起"]:
            try: route.fulfill(json=一批({"姓氏":"李"},1,0))
            except Exception: pass
        expect(名字(page)).to_have_text("张清和")
        assert not 错误,错误
        关闭环境(context); browser.close()
        print(json.dumps({"状态":"通过","模式":"模拟接口，不消耗模型额度","检查":["同帧六次连滑","触摸斜滑与取消","双指误缩放防护","四种手机尺寸","详情折叠","收藏失败重试和任务归属","刷新续看","实际曝光确认","旧请求立即取消"],"网页异常":错误},ensure_ascii=False))


if __name__=="__main__": 主程序()
