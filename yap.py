#!/usr/bin/env python

import sys
import os

if sys.version[0] < 2 or sys.version[1] < 3:
    print >> sys.stderr, "Python 2.3 or better required"
    os.exit(1)

dir = os.path.dirname(os.path.dirname(sys.argv[0]))
sys.path.insert(0, os.path.join(dir, 'lib', 'yap'))

import yap
yap.yap.Yap().main(sys.argv[1:])
