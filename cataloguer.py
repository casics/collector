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

def main(user_login=None, index_create=False, index_recreate=False,
         print_details=False, file=None, id=None, languages=None,
         index_forks=False, index_langs=False, print_index=False,
         print_ids=False, index_readmes=False,
         summarize=False, update=False, locate_by_lang=False):
    '''Generate or print index of projects found in repositories.'''

    if id:
        id_list = [int(id)]
    elif file:
        with open(file) as f:
            id_list = [int(x) for x in f.read().splitlines()]
    else:
        id_list = None

    if languages:
        languages = languages.split(',')

    if   summarize:      do_action("print_summary",     user_login)
    elif update:         do_action("update_internal",   user_login)
    elif print_ids:      do_action("print_indexed_ids", user_login)
    elif print_index:    do_action("print_index",       user_login, id_list, languages)
    elif print_details:  do_action("print_details",     user_login, id_list)
    elif index_create:   do_action("create_index",      user_login, id_list)
    elif index_recreate: do_action("recreate_index",    user_login, id_list)
    elif index_langs:    do_action("add_languages",     user_login, id_list)
    elif index_forks:    do_action("add_fork_info",     user_login, id_list)
    elif index_readmes:  do_action("add_readmes",       user_login, id_list)
    else:
        raise SystemExit('No action specified. Use -h for help.')


def do_action(action, user_login=None, id_list=None, languages=None):
    msg('Started at ', datetime.now())
    started = timer()

    db = Database()
    dbroot = db.open()

    # Do each host in turn.  (Currently only GitHub.)

    try:
        indexer = GitHubIndexer(user_login)
        method = getattr(indexer, action, None)
        if id_list and languages:
            method(dbroot, id_list, languages)
        elif id_list:
            method(dbroot, id_list)
        elif languages:
            method(dbroot, None, languages)
        else:
            method(dbroot)
    finally:
        transaction.commit()
        db.close()

    # We're done.  Print some messages and exit.

    stopped = timer()
    msg('Stopped at {}'.format(datetime.now()))
    msg('Time elapsed: {}'.format(stopped - started))


# Plac annotations for main function arguments
# .............................................................................
# Argument annotations are: (help, kind, abbrev, type, choices, metavar)
# Plac automatically adds a -h argument for help, so no need to do it here.

main.__annotations__ = dict(
    user_login     = ('use specified account login',            'option', 'a'),
    index_create   = ('gather basic index data',                'flag',   'c'),
    index_recreate = ('re-gather basic index data',             'flag',   'C'),
    print_details  = ('print details about entries',            'flag',   'd'),
    file           = ('limit to projects listed in file',       'option', 'f'),
    id             = ('limit to (single) given repository id',  'option', 'i'),
    languages      = ('limit printing to specific languages',   'option', 'L'),
    index_forks    = ('gather repository copy/fork status',     'flag',   'k'),
    index_langs    = ('gather programming languages',           'flag',   'l'),
    print_index    = ('print summary of indexed repositories',  'flag',   'p'),
    print_ids      = ('print all known repository id numbers',  'flag',   'P'),
    index_readmes  = ('gather README files',                    'flag',   'r'),
    summarize      = ('summarize database statistics',          'flag',   's'),
    update         = ('update some internal database data',     'flag',   'u'),
)

# Entry point
# .............................................................................

def cli_main():
    plac.call(main)

cli_main()
