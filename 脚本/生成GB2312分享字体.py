"""Generate two local font banks from the user-selected ZhenKai font."""
import argparse
import base64
from concurrent.futures import ProcessPoolExecutor
import json
from pathlib import Path

from fontTools.ttLib import TTFont
from 精简分享字体 import build


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('font')
    parser.add_argument('--output', default='.local/fonts/zhenkai-gb2312')
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    gb = set()
    for lead in range(0xA1, 0xF8):
        for trail in range(0xA1, 0xFF):
            try:
                char = bytes([lead, trail]).decode('gb2312')
                if 0x4E00 <= ord(char) <= 0x9FFF:
                    gb.add(ord(char))
            except UnicodeDecodeError:
                pass
    kept = sorted(gb & set(TTFont(args.font).getBestCmap()))
    assert len(kept) == 6760, 'Unexpected source font coverage'
    groups = [kept[:3380], kept[3380:]]
    with ProcessPoolExecutor(max_workers=2) as pool:
        sizes = list(pool.map(build, [(args.font, group, str(output / f'bank-{chr(97+i)}.woff2'), False)
                                     for i, group in enumerate(groups)]))
    root = Path('小程序')
    for i, group in enumerate(groups):
        directory = root / f'share-font-{chr(97+i)}'
        data = base64.b64encode((output / f'bank-{chr(97+i)}.woff2').read_bytes()).decode('ascii')
        content = 'module.exports = ' + json.dumps({'base64': data}) + ';\n'
        assert len(content.encode()) + 1024 < 2 * 1024 * 1024
        (directory / 'font.js').write_text(content, encoding='utf8')
    (root / 'assets/share/font-map.js').write_text('module.exports = ' +
        json.dumps([''.join(map(chr, group)) for group in groups], ensure_ascii=False) + ';\n', encoding='utf8')
    app_file = root / 'app.json'
    app = json.loads(app_file.read_text(encoding='utf8'))
    app['subPackages'] = [{'name': 'shareFontA', 'root': 'share-font-a', 'pages': ['index']},
                          {'name': 'shareFontB', 'root': 'share-font-b', 'pages': ['index']}]
    app_file.write_text(json.dumps(app, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
    print(json.dumps({'han_count': len(kept), 'bank_woff2_bytes': sizes,
                      'missing': [chr(c) for c in sorted(gb - set(kept))]}, ensure_ascii=True))


if __name__ == '__main__':
    main()
