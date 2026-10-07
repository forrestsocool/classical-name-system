"""Render public given-name share cards from stored source and tags."""
from functools import lru_cache
from io import BytesIO
import json
import os
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont

ASSETS = Path(__file__).with_name('share-assets')
SMALL_FONT = Path(os.getenv('SHARE_SMALL_FONT', '/app/构建产物/运行数据/分享字体/msyh.ttc'))


def 图片地址(token):
    base = os.getenv('SHARE_IMAGE_BASE_URL', 'https://name.sensen.li').rstrip('/')
    return f'{base}/share-card/{token}.jpg'


@lru_cache(maxsize=1)
def 底图():
    background = Image.open(ASSETS / 'background.jpg').convert('RGBA').resize((1500,1200))
    horizontal = Image.new('L',(1500,1200)); vertical = horizontal.copy()
    hd,vd = ImageDraw.Draw(horizontal),ImageDraw.Draw(vertical)
    for x in range(1500):
        alpha = max(0,min(1,(x-280)/210))*max(0,min(1,(1450-x)/240))
        hd.line((x,0,x,1200),fill=round(150*alpha))
    for y in range(1200):
        vd.line((0,y,1500,y),fill=round(255*max(0,min(1,(890-y)/230))))
    paper = Image.new('RGBA',background.size,(247,244,232))
    paper.putalpha(ImageChops.multiply(horizontal,vertical))
    background = Image.alpha_composite(background,paper)
    seal = Image.open(ASSETS / 'brand-seal.png').convert('RGBA')
    seal = seal.crop(seal.getchannel('A').getbbox())
    seal.thumbnail((88,320),Image.Resampling.LANCZOS)
    background.alpha_composite(seal,(1305,76))
    return background


def 字体(size, small=False):
    path = SMALL_FONT if small and SMALL_FONT.is_file() else ASSETS / 'LXGWWenKai-Medium.ttf'
    return ImageFont.truetype(str(path),size)


def 合适字体(text,size,width,small=False):
    while size>24:
        font=字体(size,small)
        if font.getlength(text)<=width: return font
        size-=2
    return 字体(size,small)


@lru_cache(maxsize=128)
def _渲染(name,book,chapter,tags_json):
    image=底图().copy()
    draw=ImageDraw.Draw(image)
    def centered(text,y,font,color):
        box=draw.textbbox((0,0),text,font=font)
        draw.text((800-draw.textlength(text,font=font)/2,y-box[1]),text,font=font,fill=color)
    font=合适字体(name,320,800)
    box=draw.textbbox((0,0),name,font=font)
    centered(name,350-(box[3]-box[1])/2,font,'#30493f')
    draw.line((768,578,832,578),fill='#a83d32',width=3)
    source=f'《{book}》' + (f' · {chapter}' if chapter else '') if book else ''
    source_font=合适字体(source,44,960,True)
    if source_font.getlength(source)>960:
        while source and source_font.getlength(source+'…')>960: source=source[:-1]
        source+='…'
    centered(source,629,source_font,'#52685b')
    tags=json.loads(tags_json)
    size=39
    while size>18:
        font=字体(size,True)
        widths=[draw.textlength(tag,font=font)+60 for tag in tags]
        if sum(widths)+24*max(0,len(tags)-1)<=960: break
        size-=1
    x=800-(sum(widths)+24*max(0,len(tags)-1))/2
    for tag,width in zip(tags,widths):
        draw.rounded_rectangle((x,728,x+width,808),radius=40,fill=(235,240,224,222),outline='#c4d1bc',width=2)
        box=draw.textbbox((0,0),tag,font=font)
        draw.text((x+(width-draw.textlength(tag,font=font))/2,768-(box[3]-box[1])/2-box[1]),tag,font=font,fill='#46624e')
        x+=width+24
    output=BytesIO()
    image.resize((750,600),Image.Resampling.LANCZOS).convert('RGB').save(output,format='JPEG',quality=92)
    return output.getvalue()


def 渲染分享图片(row):
    payload=row['payload']
    name=str(row['given_name'])[:4]
    book=str(payload.get('书名') or payload.get('book') or '')[:80]
    chapter=str(payload.get('篇章') or payload.get('chapter') or '')[:120]
    tags=payload.get('文化标签') or payload.get('tags') or []
    tags=[str(tag)[:12] for tag in tags[:3]] if isinstance(tags,list) else []
    return _渲染(name,book,chapter,json.dumps(tags,ensure_ascii=False))
