from setuptools import setup
import setup_translate

pkg = 'SystemPlugins.M3UIPTV'
setup(
    name='enigma2-plugin-systemplugins-m3uiptv',
    version='1.0',
    author='DimitarCC',
    description='IPTV m3u list dynamic reader and runner',
    package_dir={pkg: 'src'},
    packages=[pkg],
    package_data={pkg: ['*.png', '*.xml', 'locale/*/LC_MESSAGES/*.mo']},
    cmdclass=setup_translate.cmdclass,  # for translation
    )
