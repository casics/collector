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

import sys
import os
import plac
from datetime import datetime
from time import sleep
from timeit import default_timer as timer

sys.path.append('../database')
sys.path.append('../comment')

from casicsdb import *
from utils import *
from github import *
from github_indexer import GitHubIndexer


# Main body.
# .............................................................................
# Currently this only does GitHub, but extending this to handle other hosts
# should hopefully be possible.  See later in this file for the definition
# of the arguments to main().

def main(api_only=False, create=False, index_license=False, text_lang=False,
         file=None, force=False, get_files=False, prefer_http=False, id=None,
         lang=None, index_langs=False, print_details=False, print_stats=False,
         index_readmes=False, print_summary=False, print_ids=False,
         infer_type=False, list_deleted=False, user=None, delete=False, *repos):
    '''Generate or print index of projects found in repositories.'''

    def convert(arg):
        return int(arg) if (arg and arg.isdigit()) else arg

    if api_only and prefer_http:
        raise SystemExit('Cannot specify both API-only and prefer-HTTP.')

    id = int(id) if id else 0
    lang = lang.split(',') if lang else None
    if repos:
        repos = [convert(x) for x in repos]
    elif file:
        with open(file) as f:
            repos = f.read().strip().splitlines()
            if len(repos) > 0 and repos[0].isdigit():
                repos = [int(x) for x in repos]

    args = {'targets': repos, 'languages': lang, 'prefer_http': prefer_http,
            'api_only': api_only, 'force': force, 'start_id': id}

    if   print_stats:     call('print_stats'  ,     user=user, **args)
    elif print_summary:   call('print_summary',     user=user, **args)
    elif print_ids:       call('print_indexed_ids', user=user, **args)
    elif print_details:   call('print_details',     user=user, **args)
    elif create:          call('create_entries',    user=user, **args)
    elif index_langs:     call('add_languages',     user=user, **args)
    elif index_readmes:   call('add_readmes',       user=user, **args)
    elif index_license:   call('add_licenses',      user=user, **args)
    elif delete:          call('mark_deleted',      user=user, **args)
    elif list_deleted:    call('list_deleted',      user=user, **args)
    elif infer_type:      call('infer_type',        user=user, **args)
    elif get_files:       call('add_files',         user=user, **args)
    elif text_lang:       call('detect_text_lang',  user=user, **args)
    else:
        raise SystemExit('No action specified. Use -h for help.')


def call(action, user, **kwargs):
    msg('Started at ', datetime.now())

    started = timer()
    casicsdb = CasicsDB()

    # Do each host in turn.  (Currently we handle only GitHub.)
    try:
        # Find out how we log into the hosting service.
        (github_user, github_password) = GitHub.login('github', user)
        # Open our Mongo database.
        github_db = casicsdb.open('github')
        # Initialize our worker object.
        indexer = GitHubIndexer(github_user, github_password, github_db)

        # Figure out what action we're supposed to perform, and do it.
        method = getattr(indexer, action, None)
        method(**kwargs)
    finally:
        casicsdb.close()

    # We're done.  Print some messages and exit.
    stopped = timer()
    msg('Stopped at {}'.format(datetime.now()))
    msg('Time elapsed: {}'.format(stopped - started))


# Plac annotations for main function arguments
# .............................................................................
# Argument annotations are: (help, kind, abbrev, type, choices, metavar)
# Plac automatically adds a -h argument for help, so no need to do it here.

main.__annotations__ = dict(
    api_only      = ('only use the API, without first trying HTTP',   'flag',   'A'),
    create        = ('create database entries by querying GitHub',    'flag',   'c'),
    index_license = ('index license(s)',                              'flag',   'e'),
    file          = ('use subset of repo names or id\'s from file',   'option', 'f'),
    force         = ('get info even if we know we already tried',     'flag',   'F'),
    get_files     = ('get list of files at GitHub repo top level',    'flag',   'g'),
    prefer_http   = ('prefer HTTP without using API, if possible',    'flag'  , 'H'),
    infer_type    = ('try to infer if repos contain code or not',     'flag',   'i'),
    id            = ('start iterations with this GitHub id',          'option', 'I'),
    index_langs   = ('gather programming languages',                  'flag',   'l'),
    lang          = ('(with -p/-s/-S) limit to given languages',      'option', 'L'),
    print_details = ('print details about entries',                   'flag',   'p'),
    print_stats   = ('print summary of database statistics',          'flag',   'P'),
    index_readmes = ('gather README files',                           'flag',   'r'),
    print_summary = ('print list of indexed repositories'   ,         'flag',   's'),
    print_ids     = ('print all known repository id numbers',         'flag',   'S'),
    text_lang     = ('detect text languages in description & readme', 'flag',   't'),
    user          = ('use specified GitHub user account name',        'option', 'u'),
    list_deleted  = ('list deleted entries',                          'flag',   'x'),
    delete        = ('mark specific entries as deleted',              'flag',   'X'),
    repos         = 'one or more repository identifiers or names',
)

# Entry point
# .............................................................................

def cli_main():
    plac.call(main)

cli_main()
