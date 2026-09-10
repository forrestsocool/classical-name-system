"""在独立运行库启动服务后执行；需安装 playwright 和 Edge 浏览器。"""
import argparse
import json
from playwright.sync_api import sync_playwright, expect


def 主程序():
    参数器 = argparse.ArgumentParser()
    参数器.add_argument("--地址", default="http://127.0.0.1:8768")
    参数 = 参数器.parse_args()
    with sync_playwright() as 驱动:
        浏览器 = 驱动.chromium.launch(channel="msedge", headless=True)
        页面 = 浏览器.new_page(viewport={"width": 1280, "height": 900})
        错误 = []
        页面.on("pageerror", lambda 异常: 错误.append(str(异常)))
        页面.goto(参数.地址)
        页面.locator('#姓氏').wait_for()
        assert 页面.locator('#方向列表, #出生时间, input[name="五行"]').count() == 0
        页面.set_default_timeout(150000)
        页面.locator('#姓氏').fill("李")
        页面.get_by_role("button", name="开始起名", exact=True).click()
        页面.locator('.名字卡片').first.wait_for()
        第一批 = 页面.locator('.名字行 h2').all_inner_texts()
        with 页面.expect_response(lambda r: '/api/name-runs' in r.url and r.request.method == 'POST'):
            页面.locator('#换一批').click()
        expect(页面.locator('#状态')).to_contain_text('完成')
        第二批 = 页面.locator('.名字行 h2').all_inner_texts()
        assert 第二批 and set(第一批).isdisjoint(第二批)
        页面.locator('.结果标签').first.wait_for()
        页面.locator('.收藏按钮').first.click()
        expect(页面.locator('.收藏按钮').first).to_have_text("已收藏")
        页面.get_by_text("我的收藏与比较", exact=True).click()
        页面.locator('#加载收藏').click()
        页面.locator('input[name="比较选项"]').first.check()
        页面.locator('#比较收藏').click()
        页面.locator('#比较结果 article').first.wait_for()
        页面.get_by_text("任务历史", exact=True).click()
        页面.locator('#加载历史').click()
        页面.locator('.历史卡片').first.wait_for()
        页面.locator('#名字长度').select_option("1")
        页面.get_by_role("button", name="开始起名", exact=True).click()
        页面.locator('.名字卡片').first.wait_for()
        assert len(页面.locator('.名字行 h2').first.inner_text()) == 2
        页面.set_viewport_size({"width": 390, "height": 844})
        assert 页面.evaluate("document.documentElement.scrollWidth <= innerWidth"), "移动端横向溢出"
        assert not 错误, 错误
        print(json.dumps({"状态": "通过", "操作": ["取消预选", "双字名", "换一批不重复", "解释标签", "收藏", "比较", "历史", "单字名", "移动端布局"], "网页异常": 错误}, ensure_ascii=False))
        浏览器.close()


if __name__ == "__main__":
    主程序()
