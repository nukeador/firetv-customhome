"""Read package and minimum Android API from an APK binary manifest."""
import struct
import zipfile


def u16(data, offset):
    return struct.unpack_from('<H', data, offset)[0]


def u32(data, offset):
    return struct.unpack_from('<I', data, offset)[0]


def length8(data, offset):
    value = data[offset]
    return (((value & 0x7f) << 8) | data[offset + 1], offset + 2) if value & 0x80 else (value, offset + 1)


def length16(data, offset):
    value = u16(data, offset)
    return (((value & 0x7fff) << 16) | u16(data, offset + 2), offset + 4) if value & 0x8000 else (value, offset + 2)


def pool(data, offset, size):
    count, flags, string_start = u32(data, offset + 8), u32(data, offset + 16), u32(data, offset + 20)
    header = u16(data, offset + 2)
    if count > 100000 or header + count * 4 > size or string_start >= size:
        raise ValueError('Invalid string pool')
    result = []
    for index in range(count):
        pos = offset + string_start + u32(data, offset + header + index * 4)
        if pos >= offset + size:
            raise ValueError('Invalid string offset')
        if flags & 0x100:
            _, pos = length8(data, pos)
            length, pos = length8(data, pos)
            raw = data[pos:pos + length]
            result.append(raw.decode('utf-8'))
        else:
            length, pos = length16(data, pos)
            raw = data[pos:pos + length * 2]
            result.append(raw.decode('utf-16le'))
        if pos + len(raw) >= offset + size:
            raise ValueError('Truncated manifest string')
    return result


def inspect(path):
    with zipfile.ZipFile(path) as archive:
        info = archive.getinfo('AndroidManifest.xml')
        if info.file_size > 4 * 1024 * 1024:
            raise ValueError('Manifest too large')
        data = archive.read(info)
        abis = {name.split('/')[1] for name in archive.namelist() if name.startswith('lib/') and name.endswith('.so') and len(name.split('/')) >= 3}
    if len(data) < 8 or u16(data, 0) != 0x0003 or u32(data, 4) != len(data):
        raise ValueError('Invalid binary Android manifest')
    strings, package, minimum = None, None, 1
    offset = u16(data, 2)
    while offset + 8 <= len(data):
        kind, header, size = struct.unpack_from('<HHI', data, offset)
        if size < header or header < 8 or offset + size > len(data):
            raise ValueError('Invalid XML chunk')
        if kind == 0x0001:
            strings = pool(data, offset, size)
        elif kind == 0x0102:
            if strings is None or header < 16 or size < 36:
                raise ValueError('Invalid XML element')
            ext = offset + 16
            name_index = u32(data, ext + 4)
            if name_index >= len(strings):
                raise ValueError('Invalid element name')
            element = strings[name_index]
            attr_start, attr_size, attr_count = u16(data, ext + 8), u16(data, ext + 10), u16(data, ext + 12)
            if attr_size < 20 or ext + attr_start + attr_count * attr_size > offset + size:
                raise ValueError('Invalid attributes')
            for index in range(attr_count):
                a = ext + attr_start + index * attr_size
                name = u32(data, a + 4)
                raw = u32(data, a + 8)
                value_type = data[a + 15]
                value = u32(data, a + 16)
                if name >= len(strings):
                    raise ValueError('Invalid attribute name')
                key = strings[name]
                if element == 'manifest' and key == 'package':
                    string_index = raw if raw != 0xffffffff else value if value_type == 3 else 0xffffffff
                    if string_index >= len(strings):
                        raise ValueError('Invalid package')
                    package = strings[string_index]
                if element == 'uses-sdk' and key == 'minSdkVersion':
                    if value_type not in (0x10, 0x11):
                        raise ValueError('Unsupported minimum SDK value')
                    minimum = value
        offset += size
    if not package:
        raise ValueError('APK package missing')
    return {'package': package, 'min_sdk': minimum, 'abis': abis}
