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
         index_langs=False, locate_by_lang=False, index_print=False,
         index_readmes=False, summarize=False, update=False, project_list=None):
    '''Generate or print index of projects found in repositories.'''
    if   summarize:       do_action("print_summary",       user_login)
    elif update:          do_action("update_internal",     user_login)
    elif index_print:     do_action("print_index",         user_login)
    elif index_create:    do_action("create_index",        user_login, project_list)
    elif index_recreate:  do_action("recreate_index",      user_login)
    elif index_langs:     do_action("add_languages",       user_login)
    elif index_readmes:   do_action("add_readmes",         user_login)
#    elif locate_by_lang:  do_action("locate_by_languages", user_login)
    else:
        raise SystemExit('No action specified. Use -h for help.')


def do_action(action, user_login=None, project_list=None):
    msg('Started at ', datetime.now())
    started = timer()

    db = Database()
    dbroot = db.open()

    # Do each host in turn.  (Currently only GitHub.)

    indexer = GitHubIndexer(user_login)
    method = getattr(indexer, action, None)
    if project_list:
        method(dbroot, project_list)
    else:
        method(dbroot)

    # We're done.  Print some messages and exit.

    stopped = timer()
    msg('Stopped at {}'.format(datetime.now()))
    msg('Time elapsed: {}'.format(stopped - started))

    db.close()


# Plac annotations for main function arguments
# .............................................................................
# Argument annotations are: (help, kind, abbrev, type, choices, metavar)
# Plac automatically adds a -h argument for help, so no need to do it here.

main.__annotations__ = dict(
    user_login     = ('use specified account login',            'option', 'a'),
    index_create   = ('create basic index',                     'flag',   'c'),
    index_recreate = ('recreate basic index',                   'flag',   'C'),
    project_list   = ('limit to projects listed in file',       'option', 'f'),
    index_langs    = ('gather programming languages',           'flag',   'l'),
    index_print    = ('print index',                            'flag',   'p'),
    index_readmes  = ('gather README files',                    'flag',   'r'),
#    locate_by_lang = ('locate Java & Python projects',          'flag',   'L'),
    summarize      = ('summarize database',                     'flag',   's'),
    update         = ('update internal database data',          'flag',   'u'),
)

# Entry point
# .............................................................................

def cli_main():
    plac.call(main)

cli_main()
