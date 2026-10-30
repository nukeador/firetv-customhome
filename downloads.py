"""Resolve upstream releases; never use mirror sites or package third-party APKs."""
import hashlib
import html.parser
import json
import re
import urllib.parse
import urllib.request
from pathlib import Path
from apkverify import verify

STREMIO_CERT = '7e6a979c968f771e3fbcf2c2e8718ce61e708d87caf91fc13e2d4c19a8022c6b'
USQUE_CERT = '087cce9ace990b160204908a44c3e73808c5567685cf1b9cf0ae3ad033f9901a'
AGENT = {'User-Agent': 'FireTV-setup/1.0', 'Accept': 'application/vnd.github+json'}
TRUSTED_HOSTS = {'github.com', 'api.github.com', 'www.stremio.com', 'dl.strem.io',
                 'objects.githubusercontent.com', 'release-assets.githubusercontent.com'}


class RestrictedRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def check_url(url):
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != 'https' or parsed.hostname not in TRUSTED_HOSTS or parsed.username or parsed.password:
        raise ValueError('Untrusted download URL')


def request(url, limit=4 * 1024 * 1024):
    check_url(url)
    opener = urllib.request.build_opener(RestrictedRedirect())
    with opener.open(urllib.request.Request(url, headers=AGENT), timeout=30) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError('Download exceeds size limit')
    return data


class Links(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            url = dict(attrs).get('href', '')
            if url:
                self.urls.append(urllib.parse.urljoin('https://www.stremio.com/downloads', url))


def stremio_url(abi):
    parser = Links()
    parser.feed(request('https://www.stremio.com/downloads').decode('utf-8'))
    candidates = []
    for url in parser.urls:
        parsed = urllib.parse.urlparse(url)
        if parsed.hostname != 'dl.strem.io' or not re.search(r'/v[0-9.]+-androidTV/', parsed.path):
            continue
        match = re.search(r'/v([0-9.]+)-androidTV/com\.stremio\.one-[^/]+-' + re.escape(abi) + r'\.apk$', parsed.path)
        if match:
            candidates.append((tuple(int(n) for n in match.group(1).split('.')), url))
    if not candidates:
        raise ValueError('No matching official Stremio TV download')
    return max(candidates)[1]


def github_release(repo, kind, abi):
    releases = json.loads(request('https://api.github.com/repos/' + repo + '/releases?per_page=50'))
    for release in releases:
        if release.get('draft') or (kind == 'usque' and release.get('prerelease')):
            continue
        for asset in release.get('assets', []):
            name = asset.get('name', '')
            match = (name.startswith('SmartTube_beta_') and name.endswith('_' + abi + '.apk')) if kind == 'smarttube' else (name.startswith('usque-') and name.endswith('-android-' + abi + '.apk'))
            digest = asset.get('digest') or ''
            if match:
                if not re.fullmatch('sha256:[0-9a-f]{64}', digest):
                    raise ValueError('Latest matching official release has no published SHA-256')
                return asset['browser_download_url'], digest[7:]
    raise ValueError('No official release with published SHA-256 for this ABI')


def fetch(kind, abi, directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    if kind == 'stremio':
        url, expected = stremio_url(abi), None
    elif kind == 'smarttube':
        url, expected = github_release('yuliskov/SmartTube', kind, abi)
    elif kind == 'usque':
        url, expected = github_release('GeorgeXie2333/usque-app', kind, abi)
    else:
        raise ValueError('Unknown app')
    data = request(url, 250 * 1024 * 1024)
    actual = hashlib.sha256(data).hexdigest()
    if expected and actual != expected:
        raise ValueError('Published APK SHA-256 does not match')
    path = directory / (kind + '.apk')
    path.write_bytes(data)
    try:
        if kind == 'stremio':
            verify(path, STREMIO_CERT)
        elif kind == 'usque':
            verify(path, USQUE_CERT)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return path, url, actual
