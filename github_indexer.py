#!/usr/bin/env python3.4
#
# @file    github-indexer.py
# @brief   Create a database of all GitHub repositories
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
import requests
import json
import http
import urllib
import github3
import ZODB
import persistent
import transaction
from base64 import b64encode
from BTrees.OOBTree import BTree
from datetime import datetime
from time import time, sleep

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from common import *

from reporecord import *


# Summary
# .............................................................................
# This uses the GitHub API to download basic information about every GitHub
# repository and stores it in a ZODB database.  The data is stored as a simple
# object for every repository, and has the following fields:
#
#    id = repository unique id (an integer)
#    path = the GitHub URL to the repository, minus the http://github.com part
#    description = the description associated with the repository
#    owner = the name of the owner account
#    owner_type = whether the owner is a user or organization
#
# This code pays attention to the GitHub rate limit on API calls and pauses
# when it hits the 5000/hr limit, restarting again after the necessary time
# has elapsed to do another 5000 calls.  Each GitHub API call nets 100
# records, so a rate of 5000/hr = 500,000/hr.  GitHub is estimated to have
# 19,000,000 projects now, so that works out to 38 hours to download it all.
#
# This uses the github3.py module (https://github.com/sigmavirus24/github3.py),
# a convenient and reasonably full-featured Python GitHub API library.


# Main class.
# .............................................................................

class GitHubIndexer():
    _max_failures   = 5

    def __init__(self):
        cfg = Config()

        try:
            self._login = cfg.get(Host.name(Host.GITHUB), 'login')
            self._password = cfg.get(Host.name(Host.GITHUB), 'password')
        except Exception as err:
            msg(err)
            text = 'Failed to read "login" and/or "password" for {}'.format(
                Host.name(Host.GITHUB))
            raise SystemExit(text)

        msg('Connecting to GitHub as user {}'.format(self._login))
        try:
            self._github = github3.login(self._login, self._password)
        except Exception as err:
            msg(err)
            text = 'Failed to log into GitHub'
            raise SystemExit(text)

        if not self._github:
            msg('Unexpected failure in logging into GitHub')
            raise SystemExit()


    def api_calls_left(self):
        '''Returns an integer.'''
        rate_limit = self._github.rate_limit()
        return rate_limit['resources']['core']['remaining']


    def api_reset_time(self):
        '''Returns a timestamp value, i.e., seconds since epoch.'''
        rate_limit = self._github.rate_limit()
        return rate_limit['resources']['core']['reset']


    def get_iterator(self, last_seen=None):
        try:
            if last_seen:
                return self._github.all_repositories(since=last_seen)
            else:
                return self._github.all_repositories()
        except Exception as err:
            msg('github.all_repositories() failed with {0}'.format(err))
            sys.exit(1)


    def add_record(self, repo, db):
        db[repo.full_name] = RepoEntry(Host.GITHUB,
                                       repo.id,
                                       repo.full_name,
                                       repo.description,
                                       repo.owner.login,
                                       repo.owner.type)
        transaction.commit()


    def set_last_seen(self, id, db):
        db['__SINCE_MARKER__'] = id
        transaction.commit()


    def get_last_seen(self, db):
        if '__SINCE_MARKER__' in db:
            return db['__SINCE_MARKER__']
        else:
            return None


    def update_internal(self, db):
        last_seen = 0
        msg('Counting entries in the database ...')
        count = len(db)
        msg('Scanning every entry in the database ...')
        for i, key in enumerate(db):
            entry = db[key]
            if hasattr(entry, 'id') and entry.id > last_seen:
                last_seen = entry.id
            update_progress(i/count)
        msg('')
        msg('Done.  Last seen id: {}'.format(last_seen))
        self.set_last_seen(last_seen, db)


    def print_summary(self, db):
        msg('Counting entries in the database ...')
        count = len(db)
        if '__SINCE_MARKER__' in db:
            msg('Database contains {} entries.'.format(count - 1))
            msg('Last seen GitHub id: {}.'.format(db['__SINCE_MARKER__']))
        else:
            msg('Database contains {} entries.'.format(count))
            msg('No last_seen marker found.')


    def wait_for_reset(self):
        reset_time = datetime.fromtimestamp(self.api_reset_time())
        time_delta = reset_time - datetime.now()
        msg('Sleeping until ', reset_time)
        sleep(time_delta.total_seconds() + 1)  # Extra second to be safe.


    def direct_api_call(self, url):
        auth = '{0}:{1}'.format(self._login, self._password)
        headers = {
            'User-Agent': self._login,
            'Authorization': 'Basic ' + b64encode(bytes(auth, 'ascii')).decode('ascii'),
            'Accept': 'application/vnd.github.v3.raw',
        }
        conn = http.client.HTTPSConnection("api.github.com")
        conn.request("GET", url, {}, headers)
        response = conn.getresponse()
        if response.status == 200:
            content = response.readall()
            return content.decode('utf-8')
        else:
            return None


    def get_languages(self, entry):
        # Using github3.py would need 2 api calls per repo to get this info.
        # Here we do direct access to bring it to 1 api call.
        url = 'https://api.github.com/repos/{}/languages'.format(entry.path)
        response = self.direct_api_call(url)
        if response == None:
            return []
        else:
            return json.loads(response)


    def raise_exception_for_response(self, request):
        if request == None:
            raise RuntimeError('Null return value')
        elif request.ok:
            pass
        else:
            response = json.loads(request.text)
            msg = response['message']
            raise RuntimeError('{}: {}'.format(request.status_code, msg))


    def run(self, db):
        # If we're restarting this process, we'll already have entries.
        last_seen = None
        msg('Examining our current database')
        count = len(db)
        if count > 1:
            msg('There are {} entries in the database'.format(count))
            last_seen = self.get_last_seen(db)
            if last_seen:
                msg('We last read repository id = {}'.format(last_seen))

        # The iterator returned by github.all_repositories() is continuous; behind
        # the scenes, it uses the GitHub API to get new data when needed.  Each API
        # call nets 100 repository records, so after we go through 100 objects in the
        # 'for' loop below, we expect that github.all_repositories() will have made
        # another call, and the rate-limited number of API calls left in this
        # rate-limited period will go down by 1.  When we hit the limit, we pause
        # until the reset time.

        calls_left = self.api_calls_left()
        msg('Initial GitHub API calls remaining: ', calls_left)

        repo_iterator = self.get_iterator(last_seen)
        loop_count    = 0
        failures      = 0
        while failures < self._max_failures:
            try:
                repo = next(repo_iterator)
                if repo is None:
                    msg('Empty return value from github3 iterator')
                    failures += 1
                    continue

                if not repo.full_name:
                    msg('Empty repo name in data returned by github3 iterator')
                    failures += 1
                    continue

                if repo.full_name in db:
                    # print('Skipping {} -- already in the database'.format(repo.full_name))
                    continue
                else:
                    try:
                        self.add_record(repo, db)
                        msg('{}: {} (GitHub id: {})'.format(count, repo.full_name,
                                                            repo.id))
                        count += 1
                        failures = 0
                    except Exception as err:
                        msg('Exception when creating GitHubRecord: {0}'.format(err))
                        failures += 1
                        continue

                self.set_last_seen(repo.id, db)

                loop_count += 1
                if loop_count > 100:
                    calls_left = self.api_calls_left()
                    if calls_left > 1:
                        loop_count = 0
                    else:
                        self.wait_for_reset()
                        calls_left = self.api_calls_left()
                        msg('Continuing')

            except StopIteration:
                msg('github3 repository iterator reports it is done')
                break
            except github3.ForbiddenError:
                msg('GitHub API rate limit reached')
                self.wait_for_reset()
                loop_count = 0
                calls_left = self.api_calls_left()
            except Exception as err:
                msg('github3 generated an exception: {0}'.format(err))
                failures += 1

        if failures >= self._max_failures:
            msg('Stopping because of too many repeated failures')
        else:
            msg('Done')


    def add_languages(self, db):
        msg('Initial GitHub API calls remaining: ', self.api_calls_left())
        start = time()
        failures = 0
        for count, key in enumerate(db):
            entry = db[key]
            if hasattr(entry, 'id'):
                if hasattr(entry, 'languages') and entry.languages != None:
                    continue

                if self.api_calls_left() < 1:
                    self.wait_for_reset()
                    failures = 0
                    msg('Continuing')

                try:
                    raw_languages = [lang for lang in self.get_languages(entry)]
                    languages = [Language.identifier(x) for x in raw_languages]
                    record = RepoEntry(Host.GITHUB,
                                       entry.id,
                                       entry.path,
                                       entry.description,
                                       entry.owner,
                                       entry.owner_type,
                                       languages)
                    db[key] = record
                    failures = 0
                except Exception as err:
                    msg('Access error for "{}": {}'.format(entry.path, err))
                    failures += 1
            if count % 100 == 0:
                transaction.commit()
                msg('{} [{:2f}]'.format(count, time() - start))
                start = time()
            if failures >= self._max_failures:
                msg('Stopping because of too many consecutive failures')
                break

        msg('')
        msg('Done.')
        transaction.commit()
