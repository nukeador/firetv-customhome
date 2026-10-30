"""Conservative lists verified only on the documented AFTKA build."""
import re

METRICS = ('com.amazon.client.metrics.api', 'com.amazon.tv.fw.metrics',
           'com.amazon.wirelessmetrics.service', 'com.amazon.perfcollection',
           'com.amazon.perfc', 'com.amazon.dp.logger', 'com.amazon.tv.developer.dataservice',
           'com.amazon.livedeviceservice', 'com.amazon.privacypassservice', 'com.amazon.tv.acr')
CONTENT = ('com.amazon.kso.blackbird', 'com.amazon.sneakpeek', 'com.amazon.hybridadidservice',
           'com.amazon.providers.contentsupport', 'com.amazon.tv.easyupgrade', 'com.amazon.hedwig')
APPS = ('com.amazon.shoptv.client', 'com.amazon.shoptv.firetv.client',
        'com.amazon.bueller.photos', 'com.amazon.bueller.music', 'com.amazon.gamehub', 'com.amazon.firebat')
ALLOW = frozenset(METRICS + CONTENT + APPS)


def matches_identity(props, kernel, machine):
    return (props.get('ro.product.model') == 'AFTKA'
            and props.get('ro.product.device') == 'kara'
            and props.get('ro.build.version.incremental') == '0035334210436'
            and props.get('ro.build.version.sdk') == '28'
            and props.get('ro.product.cpu.abi') == 'armeabi-v7a'
            and kernel.strip() == '4.14.87+' and machine.strip() == 'armv7l')


def matches_sheldon_5746(props, kernel, machine):
    return (props.get('ro.product.model') == 'AFTSSS'
            and props.get('ro.product.device') == 'sheldonp'
            and props.get('ro.build.version.incremental') == '0036408029828'
            and props.get('ro.build.version.sdk') == '28'
            and props.get('ro.product.cpu.abi') == 'armeabi-v7a'
            and kernel.strip() == '4.4.162+' and machine.strip() == 'armv7l')


def parse_getprop(text):
    return dict(re.findall(r'^\[([^]]+)\]: \[([^]]*)\]$', text, re.M))


def validate_packages(items):
    if not set(items) <= ALLOW:
        raise ValueError('Package is not on the reviewed allowlist')
