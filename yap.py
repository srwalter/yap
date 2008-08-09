#!/usr/bin/env python

import sys
import os

version = '__VERSION__'

if sys.version[0] < 2 or sys.version[1] < 3:
    print >> sys.stderr, "Python 2.3 or better required"
    os.exit(1)

dir = os.path.dirname(os.path.dirname(sys.argv[0]))
sys.path.insert(0, os.path.join(dir, 'lib', 'yap'))

import yap
x = yap.yap.Yap()
x.version = version
x.main(sys.argv[1:])
