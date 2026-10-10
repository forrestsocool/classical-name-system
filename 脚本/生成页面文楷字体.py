"""Build GB2312-only WOFF packages for non-blocking page-name font loading."""
import argparse
import base64
import json
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('font')
    args = parser.parse_args()
    original = TTFont(args.font)
    chars = set()
    for lead in range(0xA1, 0xF8):
        for trail in range(0xA1, 0xFF):
            try:
                char = bytes([lead, trail]).decode('gb2312')
                if 0x4E00 <= ord(char) <= 0x9FFF:
                    chars.add(ord(char))
            except UnicodeDecodeError:
                pass
    kept = sorted(chars & set(original.getBestCmap()))
    assert len(kept) == 6763
    packages = []
    for index in range(3):
        bank = kept[index * 2255:(index + 1) * 2255]
        font = TTFont(args.font)
        builder = subset.Subsetter()
        builder.populate(unicodes=bank)
        builder.subset(font)
        font.flavor = 'woff'
        directory = Path(f'小程序/page-font-{chr(97+index)}')
        directory.mkdir(exist_ok=True)
        import io
        stream = io.BytesIO()
        font.save(stream)
        content = 'module.exports = ' + json.dumps({
            'base64': base64.b64encode(stream.getvalue()).decode('ascii'),
            'copyright': original['name'].getDebugName(0), 'license': 'SIL OFL 1.1'}) + ';\n'
        assert len(content.encode()) + 1024 < 2 * 1024 * 1024
        (directory / 'font.js').write_text(content, encoding='utf8')
        for extension, text in [('js', 'Page({});'), ('json', '{}'), ('wxml', '<view></view>'), ('wxss', '')]:
            (directory / f'index.{extension}').write_text(text, encoding='utf8')
        packages.append({'name': f'pageFont{chr(65+index)}', 'root': directory.name, 'pages': ['index']})
    app_path = Path('小程序/app.json')
    app = json.loads(app_path.read_text(encoding='utf8'))
    app['subPackages'] = [v for v in app['subPackages'] if not v['root'].startswith('page-font-')] + packages
    app_path.write_text(json.dumps(app, ensure_ascii=False, indent=2) + '\n', encoding='utf8')


if __name__ == '__main__':
    main()
