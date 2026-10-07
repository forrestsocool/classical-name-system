from io import BytesIO
from pathlib import Path
import unittest
from PIL import Image
from 后端.分享图片 import 渲染分享图片


class ShareImageTests(unittest.TestCase):
    def test_cards_render_for_single_double_and_long_names(self):
        images=[]
        for name in ('清','至贵','清和致远'):
            data=渲染分享图片({'given_name':name,'full_name':'不应显示的姓氏'+name,
                'payload':{'书名':'庄子','篇章':'在宥','文化标签':['高贵典雅','人格独立']}})
            image=Image.open(BytesIO(data))
            self.assertEqual(image.size,(750,600))
            self.assertEqual(image.format,'JPEG')
            images.append(data)
        self.assertNotEqual(images[0],images[1])

    def test_long_source_tags_and_missing_tags_do_not_break_rendering(self):
        for tags in ([],['很长的已有标签内容'*3]*3):
            data=渲染分享图片({'given_name':'清和','payload':{'书名':'唐诗','篇章':'已有篇名'*50,'文化标签':tags}})
            self.assertGreater(len(data),1000)


if __name__=='__main__': unittest.main()
