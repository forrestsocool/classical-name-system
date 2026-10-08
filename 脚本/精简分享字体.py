"""Build a reproducible Han-only ZhenKai subset and mini-program font banks."""
import argparse
import base64
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
from pathlib import Path
import unicodedata
import zipfile

from fontTools import subset
from fontTools.ttLib import TTFont
from opencc import OpenCC


def build(job):
    source, codepoints, output, make_ttf = job
    font = TTFont(source)
    options = subset.Options()
    options.drop_tables += ['GSUB', 'GPOS']
    builder = subset.Subsetter(options=options)
    builder.populate(unicodes=codepoints)
    builder.subset(font)
    if make_ttf:
        font.save(str(Path(output).with_suffix('.ttf')))
    font.flavor = 'woff2'
    font.save(output)
    assert set(TTFont(output).getBestCmap()) == set(codepoints)
    return Path(output).stat().st_size


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('font')
    parser.add_argument('unihan_zip')
    parser.add_argument('--output', default='.local/fonts/zhenkai-han')
    parser.add_argument('--install', action='store_true')
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    standard, simplified, mainland = set(), {}, set()
    with zipfile.ZipFile(args.unihan_zip) as archive:
        for filename in archive.namelist():
            for line in archive.read(filename).decode('utf8').splitlines():
                if not line or line.startswith('#'):
                    continue
                point, field, value = line.split('\t')
                point = int(point[2:], 16)
                if field == 'kTGHZ2013':
                    standard.add(point)
                elif field == 'kSimplifiedVariant':
                    simplified[point] = {int(item[2:].split('<')[0], 16) for item in value.split()}
                elif field == 'kIRG_GSource':
                    mainland.add(point)
    cmap = TTFont(args.font).getBestCmap()
    converter = OpenCC('t2s')
    han = {c for c in cmap if unicodedata.name(chr(c), '').startswith('CJK UNIFIED IDEOGRAPH')}
    kept = sorted(c for c in han if c in standard or (
        c in mainland and converter.convert(chr(c)) == chr(c)
        and (c not in simplified or c in simplified[c])))
    assert standard.issubset(kept), 'Source font does not cover all 8,105 standard characters'
    assert all(unicodedata.name(chr(c), '').startswith('CJK UNIFIED IDEOGRAPH') for c in kept)
    groups = [kept[i:i + 2500] for i in range(0, len(kept), 2500)]
    (output / 'characters.txt').write_text(''.join(map(chr, kept)), encoding='utf8')
    jobs = [(args.font, group, str(output / f'bank-{chr(97+i)}.woff2'), False) for i, group in enumerate(groups)]
    jobs.append((args.font, kept, str(output / 'LXGWZhenKaiGB-HanOnly.woff2'), True))
    with ProcessPoolExecutor(max_workers=2) as pool:
        sizes = list(pool.map(build, jobs))
    report = {'source_bytes': Path(args.font).stat().st_size, 'han_count': len(kept),
        'standard_count': len(standard), 'additional_rare_count': len(set(kept) - standard),
        'subset_ttf_bytes': (output / 'LXGWZhenKaiGB-HanOnly.ttf').stat().st_size,
        'subset_woff2_bytes': sizes[-1], 'bank_woff2_bytes': sizes[:-1],
        'source_sha256': hashlib.sha256(Path(args.font).read_bytes()).hexdigest(),
        'unihan_sha256': hashlib.sha256(Path(args.unihan_zip).read_bytes()).hexdigest()}
    (output / 'sizes.json').write_text(json.dumps(report, indent=2), encoding='utf8')
    print(json.dumps(report), flush=True)
    if args.install:
        root = Path('小程序')
        for i, group in enumerate(groups):
            bank = chr(97 + i)
            directory = root / f'share-font-{bank}'
            directory.mkdir(exist_ok=True)
            data = base64.b64encode((output / f'bank-{bank}.woff2').read_bytes()).decode('ascii')
            content = 'module.exports = ' + json.dumps({'base64': data}) + ';\n'
            assert len(content.encode()) + 1024 < 2 * 1024 * 1024
            (directory / 'font.js').write_text(content, encoding='utf8')
            for extension, text in [('js', 'Page({});'), ('json', '{}'), ('wxml', '<view></view>'), ('wxss', '')]:
                (directory / f'index.{extension}').write_text(text, encoding='utf8')
        (root / 'assets/share/font-map.js').write_text('module.exports = ' +
            json.dumps([''.join(map(chr, group)) for group in groups], ensure_ascii=False) + ';\n', encoding='utf8')
        app = json.loads((root / 'app.json').read_text(encoding='utf8'))
        app['subPackages'] = [{'name': f'shareFont{chr(65+i)}', 'root': f'share-font-{chr(97+i)}',
                              'pages': ['index']} for i in range(len(groups))]
        (root / 'app.json').write_text(json.dumps(app, ensure_ascii=False, indent=2) + '\n', encoding='utf8')


if __name__ == '__main__':
    main()
