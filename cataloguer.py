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
from github_indexer import GitHubIndexer


# Main body.
# .............................................................................
# Currently this only does GitHub, but extending this to handle other hosts
# should hopefully be possible.  See later in this file for the definition
# of the arguments to main().

def main(acct=None, index_create=False, index_recreate=False,
         file=None, force=False, http=False, index_forks=False, lang=None,
         index_langs=False, print_details=False, print_ids=False,
         index_readmes=False, print_index=False, summarize=False, update=False,
         list_deleted=False, delete=False, *repos):
    '''Generate or print index of projects found in repositories.'''

    def convert(arg):
        return int(arg) if (arg and arg.isdigit()) else arg

    if repos:
        repos = [convert(x) for x in repos]
    elif file:
        with open(file) as f:
            repos = f.read().splitlines()
            if len(repos) > 0 and repos[0].isdigit():
                repos = [int(x) for x in repos]
    if lang:
        lang = lang.split(',')
    args = {"targets": repos, "languages": lang, "http_only": http, "force": force}

    if   summarize:       call("print_summary",     login=acct, **args)
    elif print_ids:       call("print_indexed_ids", login=acct, **args)
    elif print_index:     call("print_index",       login=acct, **args)
    elif print_details:   call("print_details",     login=acct, **args)
    elif index_create:    call("create_index",      login=acct, **args)
    elif index_recreate:  call("recreate_index",    login=acct, **args)
    elif index_langs:     call("add_languages",     login=acct, **args)
    elif index_forks:     call("add_fork_info",     login=acct, **args)
    elif index_readmes:   call("add_readmes",       login=acct, **args)
    elif delete:          call("mark_deleted",      login=acct, **args)
    elif list_deleted:    call("list_deleted",      login=acct, **args)
    elif update:          call("update_entries",    login=acct, **args)
    else:
        raise SystemExit('No action specified. Use -h for help.')


def call(action, login, **kwargs):
    msg('Started at ', datetime.now())

    targets   = kwargs['targets']
    languages = kwargs['languages']
    http_only = kwargs['http_only']
    force     = kwargs['force']

    started = timer()
    casicsdb = CasicsDB()

    # Do each host in turn.  (Currently we handle only GitHub.)
    try:
        # Find out how we log into the hosting service.
        (github_login, github_password) = github_info('github', login)
        # Open our Mongo database.
        github_db = casicsdb.open('github')
        # Initialize our worker object.
        indexer = GitHubIndexer(github_login, github_password, github_db)

        # Figure out what action we're supposed to perform, and do it.
        method = getattr(indexer, action, None)
        method(targets=targets, languages=languages, http_only=http_only, force=force)
    finally:
        casicsdb.close()

    # We're done.  Print some messages and exit.
    stopped = timer()
    msg('Stopped at {}'.format(datetime.now()))
    msg('Time elapsed: {}'.format(stopped - started))


def github_info(hosting_service, service_account):
    cfg = Config('mongodb.ini')
    section = hosting_service
    user_login = None
    user_password = None
    try:
        if service_account:
            for name, value in cfg.items(section):
                if name.startswith('login') and value == service_account:
                    user_login = service_account
                    index = name[len('login'):]
                    if index:
                        user_password = cfg.get(section, 'password' + index)
                    else:
                        # login entry doesn't have an index number.
                        # Might be a config file in the old format.
                        user_password = value
                    break
            # If we get here, we failed to find the requested login.
            msg('Cannot find "{}" in section {} of config.ini'.format(
                service_account, section))
        else:
            try:
                user_login = cfg.get(section, 'login1')
                user_password = cfg.get(section, 'password1')
            except:
                user_login = cfg.get(section, 'login')
                user_password = cfg.get(section, 'password')
    except Exception as err:
        msg(err)
        text = 'Failed to read "login" and/or "password" for {}'.format(
            section)
        raise SystemExit(text)
    return (user_login, user_password)


# Plac annotations for main function arguments
# .............................................................................
# Argument annotations are: (help, kind, abbrev, type, choices, metavar)
# Plac automatically adds a -h argument for help, so no need to do it here.

main.__annotations__ = dict(
    acct            = ('use specified GitHub account login',         'option', 'a'),
    index_create    = ('gather basic index data',                    'flag',   'c'),
    index_recreate  = ('re-gather basic index data',                 'flag',   'C'),
    file            = ('get repo names or identifiers from file',    'option', 'f'),
    force           = ('get info even if we already tried',          'flag',   'F'),
    http            = ('prefer HTTP without using API, if possible', 'flag'  , 'H'),
    lang            = ('limit printing to specific languages',       'option', 'L'),
    index_forks     = ('gather repository copy/fork status',         'flag',   'k'),
    index_langs     = ('gather programming languages',               'flag',   'l'),
    index_readmes   = ('gather README files',                        'flag',   'r'),
    print_details   = ('print details about entries',                'flag',   'p'),
    print_ids       = ('print all known repository id numbers',      'flag',   'P'),
    print_index     = ('print summary of indexed repositories',      'flag',   's'),
    summarize       = ('summarize database statistics',              'flag',   'S'),
    update          = ('update specific entries by querying GitHub', 'flag',   'u'),
    list_deleted    = ('list deleted entries',                       'flag',   'x'),
    delete          = ('mark specific entries as deleted',           'flag',   'X'),
    repos           = 'one or more repository identifiers or names',
)

# Entry point
# .............................................................................

def cli_main():
    plac.call(main)

cli_main()
