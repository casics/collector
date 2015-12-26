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
import operator
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
from BTrees.OOBTree import TreeSet, Bucket
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

    def __init__(self, user_login=None):
        cfg = Config()
        section = Host.name(Host.GITHUB)

        try:
            if user_login:
                for name, value in cfg.items(section):
                    if name.startswith('login') and value == user_login:
                        self._login = user_login
                        index = name[len('login'):]
                        if index:
                            self._password = cfg.get(section, 'password' + index)
                        else:
                            # login entry doesn't have an index number.
                            # Might be a config file in the old format.
                            self._password = value
                        break
                # If we get here, we failed to find the requested login.
                msg('Cannot find "{}" in section {} of config.ini'.format(
                    user_login, section))
            else:
                try:
                    self._login = cfg.get(section, 'login1')
                    self._password = cfg.get(section, 'password1')
                except:
                    self._login = cfg.get(section, 'login')
                    self._password = cfg.get(section, 'password')
        except Exception as err:
            msg(err)
            text = 'Failed to read "login" and/or "password" for {}'.format(
                section)
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


    def wait_for_reset(self):
        reset_time = datetime.fromtimestamp(self.api_reset_time())
        time_delta = reset_time - datetime.now()
        msg('Sleeping until ', reset_time)
        sleep(time_delta.total_seconds() + 1)  # Extra second to be safe.


    def get_repo_iterator(self, last_seen=None):
        try:
            if last_seen:
                return self.github().iter_all_repos(since=last_seen)
            else:
                return self.github().iter_all_repos()
        except Exception as err:
            msg('github.iter_all_repos() failed with {0}'.format(err))
            sys.exit(1)


    def get_search_iterator(self, query, last_seen=None):
        try:
            if last_seen:
                return self.github().search_repositories(query, since=last_seen)
            else:
                return self.github().search_repositories(query)
        except Exception as err:
            msg('github.search_repositories() failed with {0}'.format(err))
            sys.exit(1)


    def add_record_from_github3(self, repo, db, languages=None):
        # Match impedances between github3's record format and ours.
        db[repo.full_name] = RepoEntry(host=Host.GITHUB,
                                       id=repo.id,
                                       path=repo.full_name,
                                       description=repo.description,
                                       copy_of=repo.fork,   # Only a Boolean.
                                       owner=repo.owner.login,
                                       owner_type=repo.owner.type,
                                       languages=languages)


    def get_globals(self, db):
        if '__GLOBALS__' in db:
            return db['__GLOBALS__']
        else:
            db['__GLOBALS__'] = Bucket()
            return db['__GLOBALS__']


    def set_last_seen(self, id, db):
        globals = self.get_globals(db)
        globals['__SINCE_MARKER__'] = id


    def get_last_seen(self, db):
        globals = self.get_globals(db)
        if '__SINCE_MARKER__' in globals:
            return globals['__SINCE_MARKER__']
        else:
            return None


    def set_language_list(self, value, db):
        globals = self.get_globals(db)
        globals['__ENTRIES_WITH_LANGUAGES__'] = value


    def get_language_list(self, db):
        globals = self.get_globals(db)
        if '__ENTRIES_WITH_LANGUAGES__' in globals:
            return globals['__ENTRIES_WITH_LANGUAGES__']
        else:
            return None


    def set_readme_list(self, value, db):
        globals = self.get_globals(db)
        globals['__ENTRIES_WITH_READMES__'] = value


    def get_readme_list(self, db):
        globals = self.get_globals(db)
        if '__ENTRIES_WITH_READMES__' in globals:
            return globals['__ENTRIES_WITH_READMES__']
        else:
            return None


    def set_total_entries(self, count, db):
        globals = self.get_globals(db)
        globals['__TOTAL_ENTRIES__'] = count


    def get_total_entries(self, db):
        globals = self.get_globals(db)
        if '__TOTAL_ENTRIES__' in globals:
            return globals['__TOTAL_ENTRIES__']
        else:
            msg('Did not find a count of entries.  Counting now...')
            count = len(db)
            self.set_total_entries(count, db)
            return count


    def summarize_language_stats(self, db):
        msg('Gathering programming language statistics ...')
        entries_with_languages = self.get_language_list(db)
        entries = 0                     # Total number of entries seen.
        language_counts = {}            # Pairs of language:count.
        for name in entries_with_languages:
            entries += 1
            if (entries + 1) % 100000 == 0:
                print(entries + 1, '...', end='', flush=True)
            if name in db:
                entry = db[name]
            else:
                msg('Cannot find entry "{}" in database'.format(name))
                continue
            if not isinstance(entry, RepoEntry):
                msg('Entry "{}" is not a RepoEntry'.format(name))
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


    def update_internal(self, db):
        last_seen = 0
        entries = 0
        entries_with_languages = TreeSet()
        entries_with_readmes = TreeSet()
        msg('Scanning every entry in the database ...')
        for key, entry in db.items():
            if not isinstance(entry, RepoEntry):
                if '__GLOBALS__' in db and not entry == db['__GLOBALS__']:
                    msg('Found non-RepoEntry: {}'.format(entry))
                continue
            entries += 1
            if entry.id > last_seen:
                last_seen = entry.id
            if entry.languages != None:
                entries_with_languages.add(key)
            if entry.readme != '':
                entries_with_readmes.add(key)
            if (entries + 1) % 100000 == 0:
                print(entries + 1, '...', end='', flush=True)
        msg('Done.')
        self.set_total_entries(entries, db)
        msg('Database has {} total GitHub entries.'.format(entries))
        self.set_last_seen(last_seen, db)
        msg('Last seen GitHub repository id: {}'.format(last_seen))
        self.set_language_list(entries_with_languages, db)
        msg('Number of entries with language info: {}'.format(len(entries_with_languages)))
        self.set_readme_list(entries_with_readmes, db)
        msg('Number of entries with README files: {}'.format(len(entries_with_readmes)))
        transaction.commit()
        # Remove stuff we kept at one time.
        if '__SINCE_MARKER__' in db:
            db['__SINCE_MARKER__'] = None
            msg('Deleted top-level __SINCE_MARKER__')
        if '__ENTRIES_WITH_LANGUAGES__' in db:
            db['__ENTRIES_WITH_LANGUAGES__'] = None
            msg('Deleted top-level __ENTRIES_WITH_LANGUAGES__')
        if '__ENTRIES_WITH_READMES__' in db:
            db['__ENTRIES_WITH_READMES__'] = None
            msg('Deleted top-level __ENTRIES_WITH_READMES__')
        if '__TOTAL_ENTRIES__' in db:
            db['__TOTAL_ENTRIES__'] = None
            msg('Deleted top-level __TOTAL_ENTRIES__')
        transaction.commit()


    def print_index(self, db):
        '''Print the database contents.'''
        last_seen = self.get_last_seen(db)
        if last_seen:
            msg('Last seen id: {}'.format(last_seen))
        else:
            msg('No record of last seen id.')
        for key, entry in db.items():
            if not isinstance(entry, RepoEntry):
                continue
            print(entry)
            if entry.description:
                msg(' ', entry.description.encode('ascii', 'ignore').decode('ascii'))
            else:
                msg('  -- no description --')


    def print_summary(self, db):
        '''Print a summary of the database, without listing every entry.'''
        total = self.get_total_entries(db)
        if total:
            msg('Database has {} total GitHub entries.'.format(total))
            last_seen = self.get_last_seen(db)
            if last_seen:
                msg('Last seen GitHub id: {}.'.format(last_seen))
            else:
                msg('No "last_seen" marker found.')
            entries_with_readmes = self.get_readme_list(db)
            if entries_with_readmes:
                msg('Database has {} entries with README files.'.format(len(entries_with_readmes)))
            else:
                msg('No entries recorded with README files.')
            entries_with_languages = self.get_language_list(db)
            if entries_with_languages:
                msg('Database has {} entries with language info.'.format(len(entries_with_languages)))
                self.summarize_language_stats(db)
            else:
                msg('No entries recorded with language info.')
        else:
            msg('Database has not been updated to include counts. Doing it now...')
            self.update_internal(db)
            total = self.get_total_entries(db)
            msg('Database has {} total GitHub entries'.format(total))


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


    def recreate_index(self, db):
        self.create_index_full(db, False)


    def create_index(self, db, project_list=None):
        if project_list:
            self.create_index_using_list(db, project_list)
        else:
            self.create_index_full(db)


    def create_index_full(self, db, continuation=True):
        msg('Examining our current database')
        count = self.get_total_entries(db)
        if not count:
            msg('Did not find a count of entries.  Counting now...')
            count = len(db)
            self.set_total_entries(count, db)
        msg('There are {} entries in the database'.format(count))

        last_seen = self.get_last_seen(db)
        if last_seen:
            if continuation:
                msg('Will contiue from last-read repository id {}'.format(last_seen))
            else:
                msg('Ignoring last repository id {} -- starting from the top'.format(last_seen))
                last_seen = None
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

        repo_iterator = self.get_repo_iterator(last_seen)
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
                    msg('Skipping {} ({}) -- already known'.format(
                        repo.full_name, repo.id))
                    continue
                else:
                    try:
                        self.add_record_from_github3(repo, db)
                        msg('{}: {} (GitHub id: {})'.format(count, repo.full_name,
                                                            repo.id))
                        count += 1
                        failures = 0
                    except Exception as err:
                        msg('Exception when creating RepoEntry: {0}'.format(err))
                        failures += 1
                        continue

                self.set_last_seen(repo.id, db)
                self.set_total_entries(count, db)

                transaction.commit()

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
            except github3.GitHubError as err:
                if err.code == 403:
                    msg('GitHub API rate limit reached')
                    self.wait_for_reset()
                    loop_count = 0
                    calls_left = self.api_calls_left()
                else:
                    msg('github3 generated an exception: {0}'.format(err))
                    failures += 1
            except Exception as err:
                msg('github3 generated an exception: {0}'.format(err))
                failures += 1

        transaction.commit()
        if failures >= self._max_failures:
            msg('Stopping because of too many repeated failures.')
        else:
            msg('Done.')


    def create_index_using_list(self, db, project_list):
        calls_left = self.api_calls_left()
        msg('Initial GitHub API calls remaining: ', calls_left)

        failures   = 0
        loop_count = 0
        count = 0
        with open(project_list, 'r') as f:
            for line in f:
                try:
                    line = line.strip()
                    owner = line[:line.find('/')]
                    project = line[line.find('/') + 1:]

                    repo = self.github().repository(owner, project)

                    if not repo:
                        msg('{} not found in GitHub'.format(line))
                        continue
                    if repo and not repo.full_name:
                        msg('Empty repo name in data returned by github3')
                        failures += 1
                        continue
                    if repo and repo.full_name in db:
                        msg('Skipping {} ({}) -- already known'.format(
                            repo.full_name, repo.id))
                        continue
                    try:
                        self.add_record_from_github3(repo, db)
                        msg('{}: {} (GitHub id: {})'.format(count, repo.full_name,
                                                            repo.id))
                        count += 1
                        failures = 0
                    except Exception as err:
                        msg('Exception when creating RepoEntry: {0}'.format(err))
                        failures += 1
                        continue

                    self.set_total_entries(count, db)
                    transaction.commit()

                    loop_count += 1
                    if loop_count > 100:
                        calls_left = self.api_calls_left()
                        if calls_left > 1:
                            loop_count = 0
                        else:
                            self.wait_for_reset()
                            calls_left = self.api_calls_left()
                            msg('Continuing')

                except github3.GitHubError as err:
                    if err.code == 403:
                        msg('GitHub API rate limit reached')
                        self.wait_for_reset()
                        loop_count = 0
                        calls_left = self.api_calls_left()
                    else:
                        msg('github3 generated an exception: {0}'.format(err))
                        failures += 1
                except Exception as err:
                    msg('github3 generated an exception: {0}'.format(err))
                    failures += 1

                if failures >= self._max_failures:
                    msg('Stopping because of too many repeated failures.')
                    break

        transaction.commit()
        msg('Done.')


    def add_languages(self, db):
        msg('Initial GitHub API calls remaining: ', self.api_calls_left())
        start = time()
        entries_with_languages = self.get_language_list(db)
        if not entries_with_languages:
            entries_with_languages = TreeSet()
        failures = 0

        # We can't iterate on the database if the number of elements may be
        # changing.  So, we make a copy of the keys (by making it a list),
        # and then iterate over our local in-memory copy of the keys.
        for count, key in enumerate(list(db.keys())):
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
                    entry.languages = languages
                    entry._p_changed = True # Needed for ZODB record updates.

                    # Misc bookkeeping.
                    entries_with_languages.add(key)
                    failures = 0
                except github3.GitHubError as err:
                    if err.code == 403:
                        msg('GitHub API rate limit reached')
                        self.wait_for_reset()
                        loop_count = 0
                        calls_left = self.api_calls_left()
                    else:
                        msg('github3 generated an exception: {0}'.format(err))
                        failures += 1
                except Exception as err:
                    msg('Access error for "{}": {}'.format(entry.path, err))
                    failures += 1
            self.set_language_list(entries_with_languages, db)
            transaction.commit()
            if count % 100 == 0:
                msg('{} [{:2f}]'.format(count, time() - start))
                start = time()
            if failures >= self._max_failures:
                msg('Stopping because of too many consecutive failures')
                break

        self.set_language_list(entries_with_languages, db)
        transaction.commit()
        msg('')
        msg('Done.')


    def add_readmes(self, db):
        msg('Initial GitHub API calls remaining: ', self.api_calls_left())
        start = time()
        entries_with_readmes = self.get_readme_list(db)
        if not entries_with_readmes:
            entries_with_readmes = TreeSet()
        failures = 0

        # We can't iterate on the database if the number of elements may be
        # changing.  So, we make a copy of the keys (by making it a list),
        # and then iterate over our local in-memory copy of the keys.
        for count, key in enumerate(list(db.keys())):
            entry = db[key]
            if hasattr(entry, 'id'):
                if key in entries_with_readmes:
                    continue

                if hasattr(entry, 'readme') and entry.readme:
                    # It has a non-empty readme field but it wasn't in our
                    # list of entries with readme's.  Add it, but go on.
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
                        entries_with_readmes.add(key)
                        entry.readme = zlib.compress(bytes(readme, 'utf-8'))
                        entry._p_changed = True # Needed for ZODB record updates.
                    else:
                        # If GitHub doesn't return a README file, we need to
                        # record something to indicate that we already tried.
                        # The something can't be '', or None, or 0.  We use -1.
                        entry.readme = -1
                    entry._p_changed = True # Needed for ZODB record updates.
                    failures = 0
                except github3.GitHubError as err:
                    if err.code == 403:
                        msg('GitHub API rate limit reached')
                        self.wait_for_reset()
                        loop_count = 0
                        calls_left = self.api_calls_left()
                    else:
                        msg('github3 generated an exception: {0}'.format(err))
                        failures += 1
                except Exception as err:
                    msg('Access error for "{}": {}'.format(entry.path, err))
                    failures += 1
            self.set_readme_list(entries_with_readmes, db)
            transaction.commit()
            if count % 100 == 0:
                msg('{} [{:2f}]'.format(count, time() - start))
                start = time()
            if failures >= self._max_failures:
                msg('Stopping because of too many consecutive failures')
                break

        self.set_readme_list(entries_with_readmes, db)
        transaction.commit()
        msg('')
        msg('Done.')


    def locate_by_languages(self, db):
        msg('Examining our current database')
        count = self.get_total_entries(db)
        msg('There are {} entries in the database'.format(count))

        # We have to do 2 separate searches because there does not seem to
        # be an "or" operator in the GitHub search syntax.

        # The iterator returned by github.search_repositories() is
        # continuous; behind the scenes, it uses the GitHub API to get new
        # data when needed.  Each API call nets 100 repository records, so
        # after we go through 100 objects in the 'for' loop below, we expect
        # that github.all_repositories() will have made another call, and the
        # rate-limited number of API calls left in this rate-limited period
        # will go down by 1.  When we hit the rate limit max, we pause until
        # the reset time.

        calls_left = self.api_calls_left()
        msg('Initial GitHub API calls remaining: ', calls_left)

        # Java

        search_iterator = self.get_search_iterator("language:java")
        loop_count    = 0
        failures      = 0
        while failures < self._max_failures:
            try:
                search_result = next(search_iterator)
                if search_result is None:
                    msg('Empty return value from github3 iterator')
                    failures += 1
                    continue

                repo = search_result.repository
                if repo.full_name in db:
                    # We have this in our database.  Good.
                    entry = db[repo.full_name]
                    if entry.languages:
                        if not Language.JAVA in entry.languages:
                            entry.languages.append(Language.JAVA)
                            entry._p_changed = True
                        else:
                            msg('Already knew about {}'.format(repo.full_name))
                    else:
                        entry.languages = [Language.JAVA]
                        entry._p_changed = True
                else:
                    # We don't have this in our database.  Add a new record.
                    try:
                        add_record(repo, db, languages=[Language.JAVA])
                        msg('{}: {} (GitHub id: {})'.format(count,
                                                            repo.full_name,
                                                            repo.id))
                        count += 1
                        failures = 0
                    except Exception as err:
                        msg('Exception when creating RepoEntry: {0}'.format(err))
                        failures += 1
                        continue

                self.set_last_seen(repo.id, db)
                self.set_total_entries(count, db)
                transaction.commit()

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
                msg('github3 search iterator reports it is done')
                break
            except github3.GitHubError as err:
                if err.code == 403:
                    msg('GitHub API rate limit reached')
                    self.wait_for_reset()
                    loop_count = 0
                    calls_left = self.api_calls_left()
                else:
                    msg('github3 generated an exception: {0}'.format(err))
                    failures += 1
            except Exception as err:
                msg('github3 generated an exception: {0}'.format(err))
                failures += 1

        transaction.commit()
        if failures >= self._max_failures:
            msg('Stopping because of too many repeated failures.')
        else:
            msg('Done.')
