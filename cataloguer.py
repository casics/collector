#!/usr/bin/env python3.4
#
# @file    cataloguer.py
# @brief   Creates a database of all projects in repository hosts
# @author  Michael Hucka
#
# <!---------------------------------------------------------------------------
# Copyright (C) 2015 by the California Institute of Technology.
# This software is part of CASICS, the Comprehensive and Automated Software
# Inventory Creation System.  For more information, visit http://casics.org.
# ------------------------------------------------------------------------- -->

import pdb
import sys
import os
import plac
import operator
from datetime import datetime
from time import sleep
from timeit import default_timer as timer

sys.path.append(os.path.join(os.path.dirname(__file__), "../common"))
from dbinterface import *
from utils import *
from reporecord import *

from github_indexer import GitHubIndexer


# Main body.
# .............................................................................
# Currently this only does GitHub, but extending this to handle other hosts
# should hopefully be possible.

def main(index_create=False, index_langs=False, index_print=False,
         summarize=False, update=False):
    '''Generate or print index of projects found in repositories.'''
    if index_create:  create_index()
    elif index_langs: add_languages_to_entries()
    elif index_print: print_index()
    elif summarize:   summarize_db()
    elif update:      update_db()
    else:
        raise SystemExit('Unrecognized command line flag')


def create_index():
    msg('Started at ', datetime.now())
    started = timer()

    db = Database()
    dbroot = db.open()

    # Do each host in turn.  (Currently only GitHub.)

    msg('Invoking GitHub indexer')
    indexer = GitHubIndexer()
    indexer.run(dbroot)

    # We're done.  Print some messages and exit.

    stopped = timer()
    msg('Stopped at {}'.format(datetime.now()))
    msg('Time to get repositories: {}'.format(stopped - started))

    db.close()


def add_languages_to_entries():
    msg('Started at ', datetime.now())
    started = timer()

    db = Database()
    dbroot = db.open()

    # Do each host in turn.  (Currently only GitHub.)

    msg('Invoking GitHub indexer')
    indexer = GitHubIndexer()
    indexer.add_languages(dbroot)

    # We're done.  Print some messages and exit.

    stopped = timer()
    msg('Stopped at {}'.format(datetime.now()))
    msg('Time to get repositories: {}'.format(stopped - started))

    db.close()


def print_index():
    '''Print the database contents.'''
    db = Database()
    dbroot = db.open()
    if '__SINCE_MARKER__' in dbroot:
        msg('Last seen id: {}'.format(dbroot['__SINCE_MARKER__']))
    for key in dbroot:
        entry = dbroot[key]
        if not isinstance(entry, RepoEntry):
            continue
        print(entry)
        if entry.description:
            msg(' ', entry.description.encode('ascii', 'ignore').decode('ascii'))
        else:
            msg('  -- no description --')
    db.close()


def summarize_db():
    '''Print a summary of the database, without listing every entry.'''
    db = Database()
    dbroot = db.open()
    # Do each host in turn.  (Currently only GitHub.)
    indexer = GitHubIndexer()
    indexer.print_summary(dbroot)

    # Add up some stats.
    msg('Gathering programming language statistics ...')
    language_totals = {}                      # Pairs of language:count.
    for count, key in enumerate(dbroot):
        entry = dbroot[key]
        if not isinstance(entry, RepoEntry):
            continue
        if entry.languages != None:
            for lang in entry.languages:
                if lang in language_totals:
                    language_totals[lang] = language_totals[lang] + 1
                else:
                    language_totals[lang] = 1
    msg('Language use across {} repositories'.format(count))
    for key, value in sorted(language_totals.items(), key=operator.itemgetter(1),
                             reverse=True):
        msg('{}: {}'.format(Language.name(key), value))
    db.close()


def update_db():
    '''Perform an internal update of the database, for consistency.'''
    db = Database()
    dbroot = db.open()
    # Do each host in turn.  (Currently only GitHub.)
    indexer = GitHubIndexer()
    indexer.update_internal(dbroot)
    db.close()


# Plac annotations for main function arguments
# .............................................................................
# Argument annotations are: (help, kind, abbrev, type, choices, metavar)
# Plac automatically adds a -h argument for help, so no need to do it here.

main.__annotations__ = dict(
    index_create = ('create index',                  'flag', 'c'),
    index_langs  = ('add programming languages',     'flag', 'l'),
    index_print  = ('print index',                   'flag', 'p'),
    summarize    = ('summarize database',            'flag', 's'),
    update       = ('update internal database data', 'flag', 'u'),
)

# Entry point
# .............................................................................

def cli_main():
    plac.call(main)

cli_main()
