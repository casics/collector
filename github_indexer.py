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
import zlib
import ZODB
import persistent
import transaction
from base64 import b64encode
from BTrees.OOBTree import TreeSet
from datetime import datetime
from time import time, sleep

sys.path.append(os.path.join(os.path.dirname(__file__), "../common"))
from utils import *
from reporecord import *


# Summary
# .............................................................................
# This uses the GitHub API to download basic information about every GitHub
# repository and stores it in a ZODB database.
#
# This code pays attention to the GitHub rate limit on API calls and pauses
# when it hits the 5000/hr limit, restarting again after the necessary time
# has elapsed to do another 5000 calls.  For basic information, each GitHub
# API call nets 100 records, so a rate of 5000/hr = 500,000/hr.  More detailed
# information such as programming languages only goes at 1 per API call, which
# means no more than 5000/hr.
#
# This uses the github3.py module (https://github.com/sigmavirus24/github3.py),
# for some things.  Unfortunately, github3.py turns out to be inefficient for
# getting detailed info such as languages because it causes 2 API calls to be
# used for each repo.  So, for some things, this code uses the GitHub API
# directly, via the Python httplib interface.


# Main class.
# .............................................................................

class GitHubIndexer():
    _max_failures   = 10

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


    def github(self):
        '''Returns the github3.py connection object.  If no connection has
        been established yet, it connects to GitHub first.'''

        if hasattr(self, '_github') and self._github:
            return self._github

        msg('Connecting to GitHub as user {}'.format(self._login))
        try:
            self._github = github3.login(self._login, self._password)
            return self._github
        except Exception as err:
            msg(err)
            text = 'Failed to log into GitHub'
            raise SystemExit(text)

        if not self._github:
            msg('Unexpected failure in logging into GitHub')
            raise SystemExit()


    def api_calls_left(self):
        '''Returns an integer.'''
        rate_limit = self.github().rate_limit()
        return rate_limit['resources']['core']['remaining']


    def api_reset_time(self):
        '''Returns a timestamp value, i.e., seconds since epoch.'''
        rate_limit = self.github().rate_limit()
        return rate_limit['resources']['core']['reset']


    def get_iterator(self, last_seen=None):
        try:
            if last_seen:
                return self.github().all_repositories(since=last_seen)
            else:
                return self.github().all_repositories()
        except Exception as err:
            msg('github.all_repositories() failed with {0}'.format(err))
            sys.exit(1)


    def add_record(self, repo, db):
        db[repo.full_name] = RepoData(Host.GITHUB,
                                      repo.id,
                                      repo.full_name,
                                      repo.description,
                                      '',
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


    def set_language_list(self, value, db):
        db['__ENTRIES_WITH_LANGUAGES__'] = value
        transaction.commit()


    def get_language_list(self, db):
        if '__ENTRIES_WITH_LANGUAGES__' in db:
            return db['__ENTRIES_WITH_LANGUAGES__']
        else:
            return None


    def set_readme_list(self, value, db):
        db['__ENTRIES_WITH_READMES__'] = value
        transaction.commit()


    def get_readme_list(self, db):
        if '__ENTRIES_WITH_READMES__' in db:
            return db['__ENTRIES_WITH_READMES__']
        else:
            return None


    def set_total_entries(self, count, db):
        db['__TOTAL_ENTRIES__'] = count
        transaction.commit()


    def get_total_entries(self, db):
        if '__TOTAL_ENTRIES__' in db:
            return db['__TOTAL_ENTRIES__']
        else:
            return None


    def update_internal(self, db):
        last_seen = 0
        entries = 0
        entries_with_languages = TreeSet()
        msg('Scanning every entry in the database ...')
        for key, entry in db.items():
            if not isinstance(entry, RepoData):
                continue
            entries += 1
            if entry.id > last_seen:
                last_seen = entry.id
            if entry.languages != None:
                entries_with_languages.add(key)
            if (entries + 1) % 100000 == 0:
                print(entries + 1, '...', end='', flush=True)
        msg('Done.')
        self.set_total_entries(entries, db)
        msg('Database has {} total GitHub entries.'.format(entries))
        self.set_last_seen(last_seen, db)
        msg('Last seen GitHub repository id: {}'.format(last_seen))
        self.set_language_list(entries_with_languages, db)
        msg('Number of entries with language info: {}'.format(len(entries_with_languages)))


    def print_summary(self, db):
        total = self.get_total_entries(db)
        if total:
            msg('Database has {} total GitHub entries.'.format(total))
            last_seen = self.get_last_seen(db)
            if last_seen:
                msg('Last seen GitHub id: {}.'.format(db['__SINCE_MARKER__']))
            else:
                msg('No "last_seen" marker found.')
            entries_with_languages = self.get_language_list(db)
            if entries_with_languages:
                msg('Database has {} entries with language info.'.format(len(entries_with_languages)))
            else:
                msg('No entries recorded with language info.')
            entries_with_readmes = self.get_readme_list(db)
            if entries_with_readmes:
                msg('Database has {} entries with README files.'.format(len(entries_with_readmes)))
            else:
                msg('No entries recorded with README files.')
        else:
            msg('Database has not been updated to include counts. Doing it now...')
            self.update_internal(db)
            total = self.get_total_entries(db)
            msg('Database has {} total GitHub entries'.format(total))


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


    def get_readme(self, entry):
        # Get the "preferred" readme file for a repository, as described in
        # https://developer.github.com/v3/repos/contents/
        # Using github3.py would need 2 api calls per repo to get this info.
        # Here we do direct access to bring it to 1 api call.
        url = 'https://api.github.com/repos/{}/readme'.format(entry.path)
        return self.direct_api_call(url)


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
        msg('Examining our current database')
        count = self.get_total_entries(db)
        if not count:
            msg('Did not find a count of entries.  Counting now...')
            count = len(db)
            self.set_total_entries(count, db)
        msg('There are {} entries in the database'.format(count))

        last_seen = self.get_last_seen(db)
        if last_seen:
            msg('We last read repository id = {}'.format(last_seen))
        else:
            msg('No record of the last entry seen.  Starting from the top.')

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
                self.set_total_entries(count, db)

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
            msg('Stopping because of too many repeated failures.')
        else:
            msg('Done.')


    def add_languages(self, db):
        msg('Initial GitHub API calls remaining: ', self.api_calls_left())
        start = time()
        entries_with_languages = self.get_language_list(db)
        if not entries_with_languages:
            entries_with_languages = TreeSet()
        failures = 0
        for count, key in enumerate(db):
            entry = db[key]
            if hasattr(entry, 'id'):
                if key in entries_with_languages:
                    continue

                if hasattr(entry, 'languages') and entry.languages != None:
                    entries_with_languages.add(key)
                    continue

                if self.api_calls_left() < 1:
                    self.wait_for_reset()
                    failures = 0
                    msg('Continuing')

                try:
                    raw_languages = [lang for lang in self.get_languages(entry)]
                    languages = [Language.identifier(x) for x in raw_languages]

                    # Old record format didn't have readme, but we need to
                    # preserve the value if this entry has it.
                    readme = entry.readme if hasattr(entry, 'readme') else None

                    # Now update the record.
                    record = RepoData(Host.GITHUB,
                                      entry.id,
                                      entry.path,
                                      entry.description,
                                      readme,
                                      entry.owner,
                                      entry.owner_type,
                                      languages)
                    db[key] = record

                    # Misc bookkeeping.
                    entries_with_languages.add(key)
                    failures = 0
                except Exception as err:
                    msg('Access error for "{}": {}'.format(entry.path, err))
                    failures += 1
            if count % 100 == 0:
                self.set_language_list(entries_with_languages, db)
                msg('{} [{:2f}]'.format(count, time() - start))
                start = time()
            if failures >= self._max_failures:
                msg('Stopping because of too many consecutive failures')
                break

        self.set_language_list(entries_with_languages, db)
        msg('')
        msg('Done.')


    def add_readmes(self, db):
        msg('Initial GitHub API calls remaining: ', self.api_calls_left())
        start = time()
        entries_with_readmes = self.get_readme_list(db)
        if not entries_with_readmes:
            entries_with_readmes = TreeSet()
        failures = 0
        for count, key in enumerate(db):
            entry = db[key]
            if hasattr(entry, 'id'):
                if key in entries_with_readmes:
                    continue

                if hasattr(entry, 'readme') and entry.readme:
                    entries_with_readmes.add(key)
                    continue

                if self.api_calls_left() < 1:
                    self.wait_for_reset()
                    failures = 0
                    msg('Continuing')

                try:
                    readme = self.get_readme(entry)
                    if readme:
                        msg(entry.path)
                        record = RepoData(Host.GITHUB,
                                          entry.id,
                                          entry.path,
                                          entry.description,
                                          zlib.compress(bytes(readme, 'utf-8')),
                                          entry.owner,
                                          entry.owner_type,
                                          entry.languages)
                        db[key] = record
                        failures = 0
                        entries_with_readmes.add(key)
                    else:
                        # If GitHub doesn't return a README file, we need to
                        # record something to indicate that we already tried.
                        # The something can't be '', or None, or 0.  We use -1.
                        record = RepoData(Host.GITHUB,
                                          entry.id,
                                          entry.path,
                                          entry.description,
                                          -1,
                                          entry.owner,
                                          entry.owner_type,
                                          entry.languages)
                except Exception as err:
                    msg('Access error for "{}": {}'.format(entry.path, err))
                    failures += 1
            if count % 100 == 0:
                self.set_readme_list(entries_with_readmes, db)
                msg('{} [{:2f}]'.format(count, time() - start))
                start = time()
            if failures >= self._max_failures:
                msg('Stopping because of too many consecutive failures')
                break

        self.set_readme_list(entries_with_readmes, db)
        msg('')
        msg('Done.')
