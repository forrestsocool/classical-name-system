"""增量导入唐诗、宋词。默认演练；生产执行 --apply 前须备份并停止生产器。"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pypinyin import Style, pinyin
from 脚本.建立资料数据库 import 切分古籍
from 后端.数据库 import 连接数据库

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / '古籍与东亚年号参考资料'


def 读取诗词资料(目录=CORPUS):
    目录 = Path(目录)
    provenance = json.loads((目录 / '诗词来源/来源记录.json').read_text(encoding='utf-8'))
    result = []
    for name in ('唐诗', '宋词'):
        record = next(x for x in provenance['collections'] if x['name'] == name)
        path = 目录 / '古籍全文' / (name + '.txt')
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != record['text_sha256']:
            raise ValueError(f'{name}原文与来源记录哈希不一致')
        passages = 切分古籍(name, path, 0, 0)
        if len(passages) < record['poems']:
            raise ValueError(f'{name}篇章不完整')
        result.append({'name': name, 'sha256': digest, 'passages': passages,
                       'poems': record['poems']})
    return result


def 导入(连接, 目录=CORPUS, apply=False):
    corpus = 读取诗词资料(目录)
    summary = {'applied': apply, 'sources': []}
    with 连接.transaction(force_rollback=not apply):
        if not 连接.execute('SELECT pg_try_advisory_xact_lock(2026091702) AS locked').fetchone()['locked']:
            raise RuntimeError('生产器正在运行，请先停止后再导入')
        连接.execute('LOCK TABLE sources, books, passages, characters IN SHARE ROW EXCLUSIVE MODE')
        for collection in corpus:
            name = collection['name']
            path = f'poetry-selections/{name}.txt'
            existing = 连接.execute('SELECT id,sha256 FROM sources WHERE path=%s', (path,)).fetchone()
            if existing and existing['sha256'] != collection['sha256']:
                raise ValueError(f'{name}已导入的版本不同，需单独审查升级')
            if existing:
                sid = existing['id']
            else:
                sid = 连接.execute("""INSERT INTO sources(path,file_name,sha256,encoding,source_type,status)
                    VALUES (%s,%s,%s,'utf-8','古籍','待核验') RETURNING id""",
                    (path, name + '.txt', collection['sha256'])).fetchone()['id']
            bid = 连接.execute("""INSERT INTO books(source_id,name) VALUES (%s,%s)
                ON CONFLICT(source_id,name) DO UPDATE SET name=EXCLUDED.name RETURNING id""",
                (sid, name)).fetchone()['id']
            existing_passages = {x['ordinal']: x for x in 连接.execute(
                'SELECT ordinal,text,section_title FROM passages WHERE source_id=%s AND book_id=%s', (sid,bid))}
            inserted = 0
            for passage in collection['passages']:
                previous = existing_passages.get(passage['序号'])
                if previous:
                    if previous['text'] != passage['正文'] or previous['section_title'] != passage['篇章']:
                        raise ValueError(f'{name}原文定位冲突')
                    continue
                连接.execute("""INSERT INTO passages(source_id,book_id,section_title,ordinal,text,
                    source_line_start,source_line_end,status,can_generate,active_for_recall)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,'待核验',0,true)""",
                    (sid,bid,passage['篇章'],passage['序号'],passage['正文'],
                     passage['原始起始行'],passage['原始结束行']))
                inserted += 1
            characters = sorted({char for p in collection['passages'] for char in p['正文']
                                 if '\u3400' <= char <= '\u9fff'})
            with 连接.cursor() as cursor:
                cursor.executemany("""INSERT INTO characters(char,pinyin,pinyin_tone,source,status)
                    VALUES (%s,%s,%s,'拼音库自动生成','待校对') ON CONFLICT(char) DO NOTHING""",
                    [(char,pinyin(char,style=Style.NORMAL)[0][0],pinyin(char,style=Style.TONE3)[0][0])
                     for char in characters])
            summary['sources'].append({'name':name,'poems':collection['poems'],
                'passages':len(collection['passages']),'inserted_passages':inserted})
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--资料目录', type=Path, default=CORPUS)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    with 连接数据库() as connection:
        print(json.dumps(导入(connection,args.资料目录,args.apply),ensure_ascii=False,indent=2))
