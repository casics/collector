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

# Basic principles
# ----------------
# This is a front-end interface to a simple system to gather data about
# repositories hosted in places like GitHub and store that data in a database.
# The code is more or less abstracted from the specifics of individual
# repositories as well as the database format.  The relevant pieces are:
#    host communications           => github_indexer.py
#    repository data record format => RepoData from common/reporecord.py
#    database interface            => Database from common/dbinterface.py
#
# The system is meant to be expandable to other hosting sites in addition to
# GitHub, but right now only GitHub is implemented.
#
# The basic catalog-building procedure goes like this:
#
#  1) Start the database server (using ../database/startserver.py)
#
#  2) Run this cataloguer with the "-c" flag to query hosting sites like
#     GitHub and store the results in the database.  This can take a very long
#     time.  (It took several days for 25 million entries in GitHub.)  The
#     command line is very simple:
#
#      ./cataloguer -c
#
#     But it's a good idea to capture the output of that as well as send it to
#     the background, so really you want to run it like this (using csh/tcsh
#     shell syntax):
#
#      ./cataloguer -c >& log-cataloguer.txt &
#
#  3) The cataloguing process invoked with "-c" only retrieves very basic
#     information about the repositories in the case of GitHub, because the
#     GitHub API is such that you can get the most basic info for 100 repos
#     at a time with a single API call, but to get more detailed information
#     such as the programming languages used in a given repository, you have
#     to query each repo at one API call per repo.  Since GitHub's rate limit
#     is 5000 API calls per hour, it means that getting the detailed info
#     proceeds at a 100 times slower rate.  Consequently, the procedure to
#     get programming language info is implemented as a separate step in this
#     program.  It is invoked with the "-l" flag.  To invoke it:
#
#      ./cataloguer -l >& log-languages.txt &
#
#  4) Once the cataloguer is finished, you can use this program
#     (cataloguer.py) to print some information in the database.  E.g.,
#     "cataloguer -p" will print a summary of every entry in the database.

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

def main(user_login=None, index_create=False, index_langs=False,
         index_print=False, index_readmes=False, summarize=False, update=False):
    '''Generate or print index of projects found in repositories.'''
    if index_create:    create_index(user_login)
    elif index_langs:   add_languages_to_entries(user_login)
    elif index_readmes: add_readmes_to_entries(user_login)
    elif index_print:   print_index(user_login)
    elif summarize:     summarize_db(user_login)
    elif update:        update_db(user_login)
    else:
        raise SystemExit('No action specified. Use -h for help.')


def create_index(user_login=None):
    msg('Started at ', datetime.now())
    started = timer()

    db = Database()
    dbroot = db.open()

    # Do each host in turn.  (Currently only GitHub.)

    msg('Invoking GitHub indexer')
    indexer = GitHubIndexer(user_login)
    indexer.run(dbroot)

    # We're done.  Print some messages and exit.

    stopped = timer()
    msg('Stopped at {}'.format(datetime.now()))
    msg('Time to get repositories: {}'.format(stopped - started))

    db.close()


def add_languages_to_entries(user_login=None):
    msg('Started at ', datetime.now())
    started = timer()

    db = Database()
    dbroot = db.open()

    # Do each host in turn.  (Currently only GitHub.)

    msg('Invoking GitHub indexer')
    indexer = GitHubIndexer(user_login)
    indexer.add_languages(dbroot)

    # We're done.  Print some messages and exit.

    stopped = timer()
    msg('Stopped at {}'.format(datetime.now()))
    msg('Time to get repositories: {}'.format(stopped - started))

    db.close()


def add_readmes_to_entries(user_login=None):
    msg('Started at ', datetime.now())
    started = timer()

    db = Database()
    dbroot = db.open()

    # Do each host in turn.  (Currently only GitHub.)

    msg('Invoking GitHub indexer')
    indexer = GitHubIndexer(user_login)
    indexer.add_readmes(dbroot)

    # We're done.  Print some messages and exit.

    stopped = timer()
    msg('Stopped at {}'.format(datetime.now()))
    msg('Time to get repositories: {}'.format(stopped - started))

    db.close()


def print_index(user_login=None):
    '''Print the database contents.'''
    db = Database()
    dbroot = db.open()
    if '__SINCE_MARKER__' in dbroot:
        msg('Last seen id: {}'.format(dbroot['__SINCE_MARKER__']))
    for key, entry in dbroot.items():
        if not isinstance(entry, RepoData):
            continue
        print(entry)
        if entry.description:
            msg(' ', entry.description.encode('ascii', 'ignore').decode('ascii'))
        else:
            msg('  -- no description --')
    db.close()


def summarize_db(user_login=None):
    '''Print a summary of the database, without listing every entry.'''
    db = Database()
    dbroot = db.open()
    # Print summary info per host.
    indexer = GitHubIndexer(user_login)
    indexer.print_summary(dbroot)
    # Report some stats.
    entries_with_languages = get_language_list(dbroot)
    if not entries_with_languages:
        indexer = GitHubIndexer(user_login)
        indexer.update_internal(dbroot)
    summarize_language_stats(dbroot)
    db.close()


def update_db(user_login=None):
    '''Perform an internal update of the database, for consistency.'''
    db = Database()
    dbroot = db.open()
    # Do each host in turn.  (Currently only GitHub.)
    indexer = GitHubIndexer(user_login)
    indexer.update_internal(dbroot)
    db.close()


# Helpers
# .............................................................................

def get_language_list(dbroot):
    if '__ENTRIES_WITH_LANGUAGES__' in dbroot:
        return dbroot['__ENTRIES_WITH_LANGUAGES__']
    else:
        return None


def get_readme_list(db):
    if '__ENTRIES_WITH_READMES__' in db:
        return db['__ENTRIES_WITH_READMES__']
    else:
        return None


def summarize_language_stats(dbroot):
    msg('')
    msg('Gathering programming language statistics ...')
    entries_with_languages = get_language_list(dbroot)
    entries = 0                     # Total number of entries seen.
    language_counts = {}            # Pairs of language:count.
    for name in entries_with_languages:
        entries += 1
        if (entries + 1) % 100000 == 0:
            print(entries + 1, '...', end='', flush=True)
        if name in dbroot:
            entry = dbroot[name]
        else:
            msg('Cannot find entry "{}" in database'.format(name))
            continue
        if not isinstance(entry, RepoData):
            msg('Entry "{}" is not a RepoData'.format(name))
            continue
        if entry.languages != None:
            for lang in entry.languages:
                if lang in language_counts:
                    language_counts[lang] = language_counts[lang] + 1
                else:
                    language_counts[lang] = 1
    msg('Language usage counts:')
    for key, value in sorted(language_counts.items(), key=operator.itemgetter(1),
                             reverse=True):
        msg('  {0:<24s}: {1}'.format(Language.name(key), value))



# Plac annotations for main function arguments
# .............................................................................
# Argument annotations are: (help, kind, abbrev, type, choices, metavar)
# Plac automatically adds a -h argument for help, so no need to do it here.

main.__annotations__ = dict(
    user_login    = ('use specified account login',   'option', 'a'),
    index_create  = ('create index',                  'flag',   'c'),
    index_langs   = ('add programming languages',     'flag',   'l'),
    index_print   = ('print index',                   'flag',   'p'),
    index_readmes = ('add README files',              'flag',   'r'),
    summarize     = ('summarize database',            'flag',   's'),
    update        = ('update internal database data', 'flag',   'u'),
)

# Entry point
# .............................................................................

def cli_main():
    plac.call(main)

cli_main()
