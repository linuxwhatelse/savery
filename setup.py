import os

from setuptools import find_packages, setup

HERE = os.path.dirname(os.path.realpath(__file__))


def get_requirements():
    requirements = []
    with open(os.path.join(HERE, 'requirements.txt'), 'r') as f:
        for line in f.readlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            requirements.append(line)

    return requirements


setup(
    name='savery',
    version='0.0.0',
    description='A X11 Screensaver (and more) that actually does what I want.',
    long_description='',
    url='http://linuxwhatelse.de',
    author='linuxwhatelse',
    author_email='info@linuxwhatelse.de',
    license='GPLv3',
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Intended Audience :: End Users/Desktop',
        'License :: OSI Approved :: GNU General Public License v3 (GPLv3)',
        'Operating System :: POSIX :: Linux',
        'Programming Language :: Python :: 3 :: Only',
    ],
    python_requires='~=3.5',
    packages=find_packages(),
    scripts=['bin/savery'],
    install_requires=get_requirements(),
    zip_safe=False,
)
