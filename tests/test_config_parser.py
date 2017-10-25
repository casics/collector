#!/usr/bin/env python3.4
#
# @file    test_config_parser.py
# @brief   Py.test testing code.
# @author  Michael Hucka
#
# <!---------------------------------------------------------------------------
# Copyright (C) 2015 by the California Institute of Technology.
# This software is part of CASICS, the Comprehensive and Automated Software
# Inventory Creation System.  For more information, visit http://casics.org.
# ------------------------------------------------------------------------- -->

import pytest
import sys
import glob

sys.path.append('../')

from utils import Config
from reporecord import *


class TestClass:
    def test_init(self, capsys):
        out, err = capsys.readouterr()
        cfg = Config()

    def test_global_read(self, capsys):
        out, err = capsys.readouterr()
        cfg = Config()
        x = cfg.get('global', 'dbfile')
        assert x == 'data.fs'

    def test_host_read(self, capsys):
        out, err = capsys.readouterr()
        cfg = Config()
        x = cfg.get(Host.GITHUB, 'login')
        assert x
