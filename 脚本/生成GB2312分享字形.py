"""Package original TrueType outlines for identical local Canvas rendering on iOS."""
import argparse
import base64
import io
import hashlib
import json
from pathlib import Path
import zipfile

from fontTools.ttLib import TTFont


def unsigned(buffer, value):
    while value >= 128:
        buffer.append((value & 127) | 128)
        value >>= 7
    buffer.append(value)


def signed(value):
    return value * 2 if value >= 0 else -value * 2 - 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('font')
    args = parser.parse_args()
    font = TTFont(args.font)
    cmap = font.getBestCmap()
    characters = set()
    for lead in range(0xA1, 0xF8):
        for trail in range(0xA1, 0xFF):
            try:
                char = bytes([lead, trail]).decode('gb2312')
                if 0x4E00 <= ord(char) <= 0x9FFF and ord(char) in cmap:
                    characters.add(char)
            except UnicodeDecodeError:
                pass
    characters = sorted(characters)
    assert len(characters) >= 6760
    midpoint = (len(characters) + 1) // 2
    groups = [characters[:midpoint], characters[midpoint:]]
    copyright = font['name'].getDebugName(0)
    family = font['name'].getDebugName(1)
    font_id = hashlib.sha256(Path(args.font).read_bytes()).hexdigest()[:16]
    for index, group in enumerate(groups):
        data = {'units': font['head'].unitsPerEm, 'glyphs': {}}
        for char in group:
            name = cmap[ord(char)]
            glyph = font['glyf'][name]
            coordinates, ends, flags = glyph.getCoordinates(font['glyf'])
            buffer = bytearray()
            unsigned(buffer, len(ends))
            previous = -1
            for end in ends:
                unsigned(buffer, end - previous)
                previous = end
            x = y = 0
            for (nx, ny), flag in zip(coordinates, flags):
                unsigned(buffer, signed(round(nx) - x))
                unsigned(buffer, signed(round(ny) - y))
                buffer.append(flag & 1)
                x, y = round(nx), round(ny)
            data['glyphs'][char] = {'advance': font['hmtx'][name][0],
                'bounds': [glyph.xMin, glyph.yMin, glyph.xMax, glyph.yMax],
                'points': base64.b64encode(buffer).decode('ascii')}
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w') as archive:
            entry = zipfile.ZipInfo('glyphs.json', date_time=(1980, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(entry, json.dumps(data, ensure_ascii=False, separators=(',', ':')).encode('utf8'), compresslevel=9)
        content = 'module.exports = ' + json.dumps({'zip_base64': base64.b64encode(output.getvalue()).decode('ascii'),
            'copyright': copyright,
            'license': 'SIL Open Font License 1.1'}) + ';\n'
        assert len(content.encode()) + 1024 < 2 * 1024 * 1024
        Path(f'小程序/share-font-{chr(97+index)}/font.js').write_text(content, encoding='utf8')
        print(chr(97+index), len(output.getvalue()), len(content.encode()))
    Path('小程序/assets/share/font-map.js').write_text('module.exports = ' +
        json.dumps([''.join(group) for group in groups], ensure_ascii=False) + ';\n', encoding='utf8')
    Path('小程序/assets/share/font-info.js').write_text('module.exports = ' +
        json.dumps({'id': font_id, 'family': family, 'characters': len(characters)}, ensure_ascii=False) + ';\n', encoding='utf8')


if __name__ == '__main__':
    main()
