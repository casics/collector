#!/usr/bin/env python3.4
#
# @file    test_reporecord.py
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

from reporecord import *

class TestClass:
    def test_enum_exists(self):
        assert Host.GITLAB

    def test_host_name(self):
        x = Host.name(Host.GITHUB)
        assert x == 'GitHub'
        x = Host.name(Host.LAUNCHPAD)
        assert x == 'LaunchPad'

    def test_host_identifier(self):
        x = Host.identifier('GitHub')
        assert x == Host.GITHUB
        x = Host.identifier('LaunchPad')
        assert x == Host.LAUNCHPAD

    def test_language_name(self):
        x = Language.name(Language.PHP)
        assert x == 'PHP'
        x = Language.name(Language.C)
        assert x == 'C'

    def test_language_identifier(self):
        x = Language.identifier('C++')
        assert x == Language.CPLUSPLUS
        x = Language.identifier('JavaScript')
        assert x == Language.JAVASCRIPT
