#!/usr/bin/env python3.4
#
# @file    convert-db.py
# @brief   Convert database to new record format
# @author  Michael Hucka
#
# <!---------------------------------------------------------------------------
# Copyright (C) 2015 by the California Institute of Technology.
# This software is part of CASICS, the Comprehensive and Automated Software
# Inventory Creation System.  For more information, visit http://casics.org.
# ------------------------------------------------------------------------- -->

import pdb
import sys
import plac
from time import time

from database import *
from reporecord import *
from utils import *


# Main body.
# .............................................................................
# Currently this only does GitHub, but extending this to handle other hosts
# should hopefully be possible.

def main():
    '''Create & manipulate index of projects found in repository hosting sites.'''
    convert()


def convert():
    db = Database()
    dbroot = db.open()
    msg('Converting ...')
    start = time()
    for i, key in enumerate(dbroot):
        entry = dbroot[key]
        if not isinstance(entry, RepoEntry) and hasattr(entry, 'id'):
            n = RepoEntry(Host.GITHUB,
                          entry.id,
                          entry.path,
                          entry.description,
                          entry.owner,
                          entry.owner_type)
            dbroot[key] = n
        if i % 10000 == 0:
            # update_progress(i/count)
            transaction.savepoint(True)
        if i % 100000 == 0:
            transaction.commit()
            msg('{} [{:2f}]'.format(i, time() - start))
            start = time()
    transaction.commit()
    # update_progress(1)

    db.close()
    msg('')
    msg('Done.')


# Entry point
# .............................................................................

def cli_main():
    plac.call(main)

cli_main()
