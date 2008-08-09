#!/usr/bin/env python

from distutils.core import setup
import os
import sys

if sys.version[0] < 2 or sys.version[1] < 3:
    print >> sys.stderr, "Python 2.3 or better required"
    os.exit(1)

vers = os.popen("git describe --tags HEAD").readline().strip()
os.system("cat yap.py | sed -e 's/__VERSION__/%s/' > yap.bin" % vers)

setup(name='Yap',
      version=vers,
      description='Yet Another (Git) Porcelein',
      author='Steven Walter',
      author_email='stevenrwalter@gmail.com',
      packages=['yap'])
