"""Verify APK Signature Scheme v2 and the expected release certificate."""
import hashlib
import struct
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, padding


def lp(data, pos=0):
    if pos + 4 > len(data):
        raise ValueError('Campo APK truncado')
    size = struct.unpack_from('<I', data, pos)[0]
    start = pos + 4
    if start + size > len(data):
        raise ValueError('Campo APK truncado')
    return data[start:start + size], start + size


def records(data):
    pos = 0
    while pos < len(data):
        record, pos = lp(data, pos)
        yield record


def verify(path, expected_cert):
    data = path.read_bytes()
    eocd = data.rfind(b'PK\x05\x06', max(0, len(data) - 65557))
    if eocd < 0 or eocd + 22 + struct.unpack_from('<H', data, eocd + 20)[0] != len(data):
        raise ValueError('ZIP inválido')
    cd = struct.unpack_from('<I', data, eocd + 16)[0]
    if cd < 24 or data[cd - 16:cd] != b'APK Sig Block 42':
        raise ValueError('Falta la firma APK v2')
    size = struct.unpack_from('<Q', data, cd - 24)[0]
    start = cd - size - 8
    if start < 0 or struct.unpack_from('<Q', data, start)[0] != size:
        raise ValueError('Bloque de firma inválido')
    pos, v2 = start + 8, None
    while pos < cd - 24:
        length = struct.unpack_from('<Q', data, pos)[0]
        pos += 8
        if length < 4 or pos + length > cd - 24:
            raise ValueError('Bloque de firma truncado')
        if struct.unpack_from('<I', data, pos)[0] == 0x7109871a:
            v2 = data[pos + 4:pos + length]
        pos += length
    if v2 is None:
        raise ValueError('Falta la firma APK v2')
    signers, end = lp(v2)
    if end != len(v2):
        raise ValueError('Firmantes inválidos')
    signers = list(records(signers))
    if len(signers) != 1:
        raise ValueError('Número de firmantes inesperado')
    signed, pos = lp(signers[0])
    signatures, pos = lp(signers[0], pos)
    public_key, pos = lp(signers[0], pos)
    if pos != len(signers[0]):
        raise ValueError('Firmante inválido')
    digests, pos = lp(signed)
    certs, pos = lp(signed, pos)
    attrs, pos = lp(signed, pos)
    if any(signed[pos:]):
        raise ValueError('Datos de firma inválidos')
    certs = list(records(certs))
    if not certs or hashlib.sha256(certs[0]).hexdigest().lower() != expected_cert.lower():
        raise ValueError('Certificado de firma inesperado')
    key = x509.load_der_x509_certificate(certs[0]).public_key()
    if key.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo) != public_key:
        raise ValueError('La clave pública no coincide con el certificado')
    def parse_map(seq):
        result = {}
        for rec in records(seq):
            if len(rec) < 4:
                raise ValueError('Registro de firma inválido')
            ident = struct.unpack_from('<I', rec)[0]
            value, end = lp(rec, 4)
            if end != len(rec) or ident in result:
                raise ValueError('Registro de firma inválido')
            result[ident] = value
        return result
    digest_map, signature_map = parse_map(digests), parse_map(signatures)
    if set(digest_map) != set(signature_map):
        raise ValueError('Algoritmos de firma incoherentes')
    supported = {0x0101: ('sha256', 'pss'), 0x0102: ('sha512', 'pss'),
                 0x0103: ('sha256', 'rsa'), 0x0104: ('sha512', 'rsa'),
                 0x0201: ('sha256', 'ec'), 0x0202: ('sha512', 'ec')}
    candidates = [a for a in signature_map if a in supported]
    if not candidates:
        raise ValueError('Algoritmo de firma no soportado')
    eocd_copy = bytearray(data[eocd:])
    struct.pack_into('<I', eocd_copy, 16, start)
    for alg in candidates:
        hash_name, kind = supported[alg]
        hash_obj = hashes.SHA256() if hash_name == 'sha256' else hashes.SHA512()
        if kind == 'pss':
            key.verify(signature_map[alg], signed, padding.PSS(mgf=padding.MGF1(hash_obj), salt_length=hash_obj.digest_size), hash_obj)
        elif kind == 'rsa':
            key.verify(signature_map[alg], signed, padding.PKCS1v15(), hash_obj)
        else:
            key.verify(signature_map[alg], signed, ec.ECDSA(hash_obj))
        chunks = []
        for part in (data[:start], data[cd:eocd], bytes(eocd_copy)):
            for off in range(0, len(part), 1024 * 1024):
                chunk = part[off:off + 1024 * 1024]
                chunks.append(hashlib.new(hash_name, b'\xa5' + struct.pack('<I', len(chunk)) + chunk).digest())
        digest = hashlib.new(hash_name, b'\x5a' + struct.pack('<I', len(chunks)) + b''.join(chunks)).digest()
        if digest != digest_map[alg]:
            raise ValueError('Contenido APK modificado')
    return expected_cert.lower()
