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

import sys
import os
import operator
import requests
import json
import http
import requests
import urllib
import github3
import humanize
import socket
from base64 import b64encode
from datetime import datetime
from time import time, sleep

sys.path.append(os.path.join(os.path.dirname(__file__), "../common"))
sys.path.append(os.path.join(os.path.dirname(__file__), "../database"))
from casicsdb import *
from utils import *


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


# Miscellaneous general utilities.
# .............................................................................

def msg_notfound(thing):
    msg('*** "{}" not found ***'.format(thing))


def msg_bad(thing):
    if isinstance(thing, int) or (isinstance(thing, str) and thing.isdigit()):
        msg('*** id #{} not found ***'.format(thing))
    elif isinstance(thing, str):
        msg('*** {} not an id or an "owner/name" string ***'.format(thing))
    else:
        msg('*** unrecognize type of thing: "{}" ***'.format(thing))

# Based on http://stackoverflow.com/a/14491059/743730
def flatten(the_list):
    for item in the_list:
        try:
            yield from flatten(item)
        except TypeError:
            yield item


# Utilities for working with our MongoDB contents.
# .............................................................................

def e_path(entry):
    return entry['owner'] + '/' + entry['name']


def e_summary(entry):
    return '{} (#{})'.format(e_path(entry), entry['_id'])


def e_languages(entry):
    if not entry['languages']:
        return []
    elif entry['languages'] == -1:
        return -1
    elif isinstance(entry['languages'], list):
        return [lang['name'] for lang in entry['languages']]
    else:
        # This shouldn't happen.
        return entry['languages']


def make_lang_dict(langs):
    return [{'name': lang} for lang in langs]


# Error classes for internal communication.
# .............................................................................

class DirectAPIException(Exception):
    def __init__(self, message, code):
        super(DirectAPIException, self).__init__(message)
        self.code = code


# Main class.
# .............................................................................

class GitHubIndexer():
    _max_failures   = 10

    def __init__(self, github_login=None, github_password=None, github_db=None):
        self.db        = github_db.repos
        self._login    = github_login
        self._password = github_password


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
        # We call this more than once:
        def calls_left():
            rate_limit = self.github().rate_limit()
            return rate_limit['resources']['core']['remaining']

        try:
            return calls_left()
        except Exception as err:
            msg('Got exception asking about rate limit: {}'.format(err))
            msg('Sleeping for 1 minute and trying again.')
            sleep(60)
            msg('Trying again.')
            try:
                return calls_left()
            except Exception as err:
                msg('Got another exception asking about rate limit: {}'.format(err))
                # Treat it as no time left.  Caller should pause for longer.
                return 0


    def api_reset_time(self):
        '''Returns a timestamp value, i.e., seconds since epoch.'''
        try:
            rate_limit = self.github().rate_limit()
            return rate_limit['resources']['core']['reset']
        except Exception as err:
            msg('Got exception asking about reset time: {}'.format(err))
            raise err


    def wait_for_reset(self):
        reset_time = datetime.fromtimestamp(self.api_reset_time())
        time_delta = reset_time - datetime.now()
        msg('Sleeping until ', reset_time)
        sleep(time_delta.total_seconds() + 1)  # Extra second to be safe.
        msg('Continuing')


    def repo_via_api(self, owner, name):
        failures = 0
        retry = True
        while retry and failures < self._max_failures:
            # Don't retry unless the problem may be transient.
            retry = False
            try:
                return self.github().repository(owner, name)
            except github3.GitHubError as err:
                if err.code == 403:
                    if self.api_calls_left() < 1:
                        self.wait_for_reset()
                        failures += 1
                        retry = True
                    else:
                        msg('GitHb code 403 for {}/{}'.format(owner, name))
                        break
                elif err.code == 451:
                    # https://developer.github.com/changes/2016-03-17-the-451-status-code-is-now-supported/
                    msg('GitHub code 451 (blocked) for {}/{}'.format(owner, name))
                    break
                else:
                    msg('github3 generated an exception: {0}'.format(err))
                    failures += 1
                    # Might be a network or other transient error. Try again.
                    sleep(0.5)
                    retry = True
            except Exception as err:
                msg('Exception for {}/{}: {}'.format(owner, name, err))
                # Something even more unexpected.
                break
        return None


    def direct_api_call(self, url):
        auth = '{0}:{1}'.format(self._login, self._password)
        headers = {
            'User-Agent': self._login,
            'Authorization': 'Basic ' + b64encode(bytes(auth, 'ascii')).decode('ascii'),
            'Accept': 'application/vnd.github.v3.raw',
        }
        try:
            conn = http.client.HTTPSConnection("api.github.com", timeout=15)
        except:
            # If we fail (maybe due to a timeout), try it one more time.
            try:
                sleep(1)
                conn = http.client.HTTPSConnection("api.github.com", timeout=15)
            except Exception:
                msg('Failed direct api call: {}'.format(err))
                return None
        conn.request("GET", url, {}, headers)
        response = conn.getresponse()
        if response.status == 200:
            content = response.readall()
            try:
                return content.decode('utf-8')
            except:
                # Content is either binary or garbled.  We can't deal with it,
                # so we return an empty string.
                msg('Undecodable content received for {}'.format(url))
                return ''
        elif response.status == 301:
            # Redirection
            return self.direct_api_call(response.getheader('Location'))
        else:
            msg('Response status {} for {}'.format(response.status, url))
            return response.status


    def github_url_path(self, entry, owner=None, name=None):
        if not owner:
            owner = entry['owner']
        if not name:
            name  = entry['name']
        return '/' + owner + '/' + name


    def github_url(self, entry, owner=None, name=None):
        return 'https://github.com' + self.github_url_path(entry, owner, name)


    def github_url_exists(self, entry, owner=None, name=None):
        '''Returns the URL actually returned by GitHub, in case of redirects.'''
        url_path = self.github_url_path(entry, owner, name)
        try:
            conn = http.client.HTTPSConnection('github.com', timeout=15)
        except:
            # If we fail (maybe due to a timeout), try it one more time.
            try:
                sleep(1)
                conn = http.client.HTTPSConnection('github.com', timeout=15)
            except Exception:
                msg('Failed url check for {}: {}'.format(url_path, err))
                return None
        conn.request('HEAD', url_path)
        resp = conn.getresponse()
        if resp.status < 400:
            return resp.headers['Location']
        else:
            return False


    def owner_name_from_github_url(self, url):
        if url.startswith('https'):
            # length of https://github.com/ = 18
            path = url[19:]
            return (path[:path.find('/')], path[path.find('/') +1:])
        elif url.startswith('http'):
            path = url[18:]
            return (path[:path.find('/')], path[path.find('/') +1:])
        else:
            return (None, None)


    def get_github_iterator(self, last_seen=None):
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


    def get_last_seen_id(self):
        last = self.db.find_one({'$query':{}, '$orderby':{'_id':-1}}, {})
        return last['_id']


    def get_home_page(self, entry, owner=None, name=None):
        r = requests.get(self.github_url(entry, owner, name))
        return (r.status_code, r.text)


    def add_entry(self, entry):
        self.db.insert_one(entry)


    def update_entry(self, entry):
        self.db.replace_one({'_id' : entry['_id']}, entry)


    def update_field(self, entry, field, value):
        entry[field] = value
        now = now_timestamp()
        self.db.update({'_id': entry['_id']},
                       {'$set': {field: value,
                                 'time.data_refreshed': now}})
        # Update this so that the object being held by the caller reflects
        # what was written to the database.
        entry['time']['data_refreshed'] = now


    def update_fork_field(self, entry, fork_parent, fork_root):
        if entry['fork']:
            if fork_parent:
                entry['fork']['parent'] = fork_parent
            if fork_root:
                entry['fork']['root'] = fork_root
        else:
            fork_dict = {}
            fork_dict['parent'] = fork_parent
            fork_dict['root']   = fork_root
            entry['fork'] = fork_dict
        self.update_field(entry, 'fork', entry['fork'])


    def update_entry_from_github3(self, entry, repo):
        # Update existing entry.
        #
        # Since github3 accesses the live github API, whatever data we get,
        # we assume is authoritative and overrides almost everything we may
        # already have for the entry.
        #
        # However, this purposefully does not change 'languages' and
        # 'readme', because they are not in the github3 structure and if
        # we're updating an existing entry in our database, we don't want to
        # destroy those fields if we have them.

        entry['owner']          = repo.owner.login
        entry['name']           = repo.name
        entry['description']    = repo.description
        entry['default_branch'] = repo.default_branch
        entry['homepage']       = repo.homepage
        entry['is_visible']     = not repo.private
        entry['is_deleted']     = False   # github3 found it => not deleted.

        if repo.language and (not entry['languages'] or entry['languages'] == -1):
            # We may add more languages than the single language returned by
            # the github API, so we don't overwrite this field unless warranted.
            entry['languages'] = [{'name': repo.language}]

        if repo.fork:
            fork_dict = {}
            fork_dict['parent'] = repo.parent.full_name if repo.parent else ''
            fork_dict['root']   = repo.source.full_name if repo.source else ''
            entry['fork'] = fork_dict
        else:
            entry['fork'] = False

        entry['time']['repo_created']   = canonicalize_timestamp(repo.created_at)
        entry['time']['repo_updated']   = canonicalize_timestamp(repo.updated_at)
        entry['time']['repo_pushed']    = canonicalize_timestamp(repo.pushed_at)
        entry['time']['data_refreshed'] = now_timestamp()

        if repo.size == 0:
           entry['content_type'] = 'empty'
       elif repo.size > 0 and entry['content_type'] == '':
           # Only set this if we didn't know anything at all before, so that we
           # don't blow away a value we may have already found some other way.
           entry['content_type'] = 'nonempty'

        self.update_entry(entry)


    def add_entry_from_github3(self, repo, overwrite=False):
        # 'repo' is a github3 object.  Returns True if it's a new entry.
        entry = self.db.find_one({'_id' : repo.id})
        if entry == None:
            # Create a new entry.
            # This purposefully does not change 'languages' and 'readme',
            # because they are not in the github3 structure and if we're
            # updating an existing entry in our database, we don't want to
            # destroy those fields if we have them.
            fork_of = repo.parent.full_name if repo.parent else ''
            fork_root = repo.source.full_name if repo.source else ''
            languages = [{'name': repo.language}] if repo.language else []
            content_type = 'empty' if repo.size == 0 else 'nonempty'
            entry = repo_entry(id=repo.id,
                               name=repo.name,
                               owner=repo.owner.login,
                               description=repo.description,
                               languages=languages,
                               default_branch=repo.default_branch,
                               homepage=repo.homepage,
                               content_type=content_type,
                               is_deleted=False,
                               is_visible=not repo.private,
                               is_fork=repo.fork,
                               fork_of=fork_of,
                               fork_root=fork_root,
                               created=canonicalize_timestamp(repo.created_at),
                               last_updated=canonicalize_timestamp(repo.updated_at),
                               last_pushed=canonicalize_timestamp(repo.pushed_at),
                               data_refreshed=now_timestamp())
            self.add_entry(entry)
            return (True, entry)
        elif overwrite:
            self.update_entry_from_github3(entry, repo)
            return (False, entry)
        else:
            return (False, entry)


    def loop(self, iterator, body_function, selector, targets=None, start_id=0):
        msg('Initial GitHub API calls remaining: ', self.api_calls_left())
        count = 0
        failures = 0
        start = time()
        # By default, only consider those entries without language info.
        for entry in iterator(targets or selector, start_id=start_id):
            retry = True
            while retry and failures < self._max_failures:
                # Don't retry unless the problem may be transient.
                retry = False
                try:
                    body_function(entry)
                    failures = 0
                except StopIteration:
                    msg('Iterator reports it is done')
                    break
                except (github3.GitHubError, DirectAPIException) as err:
                    if err.code == 403:
                        if self.api_calls_left() < 1:
                            msg('GitHub API rate limit exceeded')
                            self.wait_for_reset()
                            retry = True
                        else:
                            # Occasionally get 403 even when not over the limit.
                            msg('GitHub code 403 for {}'.format(e_summary(entry)))
                            self.update_field(entry, 'is_visible', False)
                            retry = False
                            failures += 1
                    elif err.code == 451:
                        msg('GitHub code 451 (blocked) for {}'.format(e_summary(entry)))
                        self.update_field(entry, 'is_visible', False)
                        retry = False
                    else:
                        msg('GitHub API exception: {0}'.format(err))
                        failures += 1
                        # Might be a network or other transient error.
                        retry = True
                except Exception as err:
                    msg('Exception for {} -- skipping it -- {}'.format(
                        e_summary(entry), err))
                    # Something unexpected.  Don't retry this entry, but count
                    # this failure in case we're up against a roadblock.
                    failures += 1
                    retry = False

            if failures >= self._max_failures:
                msg('Stopping because of too many consecutive failures')
                break
            count += 1
            if count % 100 == 0:
                msg('{} [{:2f}]'.format(count, time() - start))
                start = time()

        msg('')
        msg('Done.')


    def ensure_id(self, item):
        # This may return a list of id's, in the case where an item is given
        # as an owner/name string and there are multiple entries for it in
        # the database (e.g., because the user deleted the repo and recreated
        # it in GitHub, thus causing a new id to be generated by GitHub).
        if isinstance(item, int):
            return item
        elif isinstance(item, str):
            if item.isdigit():
                return int(item)
            elif item.find('/') > 1:
                owner = item[:item.find('/')]
                name  = item[item.find('/') + 1:]
                # There may be multiple entries with the same owner/name, e.g. when
                # a repo was deleted and recreated afresh.
                results = self.db.find({'owner': owner, 'name': name})
                id_list = []
                for entry in results:
                    id_list.append(int(entry['_id']))
                if len(id_list) == 1:
                    return id_list[0]
                elif len(id_list) > 1:
                    return id_list
                # No else case -- continue further.
                # We may yet have the entry in our database, but its name may
                # have changed.  Either we have to use an API call or we can
                # check if the home page exists on github.com.
                url = self.github_url_exists(None, owner, name)
                if not url:
                    msg_notfound(item)
                    return None
                (n_owner, n_name) = self.owner_name_from_github_url(url)
                if n_owner and n_name:
                    result = self.db.find_one({'owner': n_owner, 'name': n_name})
                    if result:
                        msg('*** {}/{} is now {}/{}'.format(owner, name,
                                                            n_owner, n_name))
                        return int(result['_id'])
                msg_notfound(item)
                return None
        msg_bad(item)
        return None


    def entry_list(self, targets=None, fields=None, start_id=0):
        # Returns a list of mongodb entries.
        if fields:
            # Restructure the list of fields into the format expected by mongo.
            fields = {x:1 for x in fields}
            if '_id' not in fields:
                # By default, Mongodb will return _id even if not requested.
                # Skip it unless the caller explicitly wants it.
                fields['_id'] = 0
        if isinstance(targets, dict):
            # Caller provided a query string, so use it directly.
            return self.db.find(targets, fields, no_cursor_timeout=True)
        elif isinstance(targets, list):
            # Caller provided a list of id's or repo names.
            ids = list(flatten(self.ensure_id(x) for x in targets))
            if start_id > 0:
                ids = [id for id in ids if id >= start_id]
            return self.db.find({'_id': {'$in': ids}}, fields,
                                no_cursor_timeout=True)
        elif isinstance(targets, int):
            # Single target, assumed to be a repo identifier.
            return self.db.find({'_id' : targets}, fields,
                                no_cursor_timeout=True)
        else:
            # Empty targets; match against all entries greater than start_id.
            query = {}
            if start_id > 0:
                query['_id'] = {'$gte': start_id}
            return self.db.find(query, fields, no_cursor_timeout=True)


    def repo_list(self, targets=None, prefer_http=False, start_id=0):
        # Returns a list of github3 repo objects.
        output = []
        count = 0
        total = 0
        start = time()
        msg('Constructing target list...')
        for item in targets:
            count += 1
            if isinstance(item, int) or item.isdigit():
                msg('*** Cannot retrieve new repos by id -- skipping {}'.format(item))
                continue
            elif item.find('/') > 1:
                owner = item[:item.find('/')]
                name  = item[item.find('/') + 1:]
                if prefer_http:
                    # Github seems to redirect URLs to the new pages of
                    # projects that have been renamed, so this works even if
                    # we have an old owner/name combination.
                    url = self.github_url_exists(None, owner, name)
                    if url:
                        (owner, name) = self.owner_name_from_github_url(url)
                        repo = self.repo_via_api(owner, name)
                    else:
                        msg('*** No home page for {}/{} -- skipping'.format(owner, name))
                        continue
                else:
                    # Don't prefer http => we go straight to API.
                    repo = self.repo_via_api(owner, name)
            else:
                msg('*** Skipping uninterpretable "{}"'.format(item))
                continue

            if repo:
                output.append(repo)
                total += 1
            else:
                msg('*** {} not found in GitHub'.format(item))

            if count % 100 == 0:
                msg('{} [{:2f}]'.format(count, time() - start))
                start = time()
        msg('Constructing target list... Done.  {} entries'.format(total))
        return output


    def repo_list_prefer_http(self, targets=None, start_id=0):
        return self.repo_list(targets, True)


    def language_query(self, languages):
        filter = None
        if isinstance(languages, str):
            filter = {'languages.name': languages}
        elif isinstance(languages, list):
            filter = {'languages.name':  {"$in" : languages}}
        return filter


    def summarize_language_stats(self, targets=None):
        msg('Gathering programming language statistics ...')
        totals = {}                     # Pairs of language:count.
        seen = 0                        # Total number of entries seen.
        for entry in self.entry_list(targets
                                     or {'languages':  {"$nin": [-1, []]} },
                                     fields=['languages']):
            seen += 1
            if seen % 100000 == 0:
                print(seen, '...', end='', flush=True)
            if not entry['languages']:
                continue
            for lang in e_languages(entry):
                totals[lang] = totals[lang] + 1 if lang in totals else 1
        seen = humanize.intcomma(seen)
        msg('Language usage counts for {} entries:'.format(seen))
        for name, count in sorted(totals.items(), key=operator.itemgetter(1),
                                 reverse=True):
            msg('  {0:<24s}: {1}'.format(name, count))


    def summarize_readme_stats(self, targets=None):
        have_readmes = self.db.find({'readme':  {'$nin': ['', -1]} }).count()
        have_readmes = humanize.intcomma(have_readmes)
        msg('Database has {} entries with README files.'.format(have_readmes))


    def list_deleted(self, targets=None, **kwargs):
        msg('-'*79)
        msg("The following entries have 'is_deleted' = True:")
        for entry in self.entry_list(targets or {'is_deleted': True},
                                     fields={'_id', 'owner', 'name'},
                                     start_id=start_id):
            msg(e_summary(entry))
        msg('-'*79)


    def print_stats(self, **kwargs):
        '''Print an overall summary of the database.'''
        msg('Printing general statistics.')
        total = humanize.intcomma(self.db.count())
        msg('Database has {} total GitHub entries.'.format(total))
        last_seen_id = self.get_last_seen_id()
        if last_seen_id:
            msg('Last seen GitHub id: {}.'.format(last_seen_id))
        else:
            msg('*** no entries ***')
            return
        self.summarize_readme_stats()
        self.summarize_language_stats()


    def print_indexed_ids(self, targets={}, languages=None, start_id=0, **kwargs):
        '''Print the known repository identifiers in the database.'''
        msg('Printing known GitHub id numbers.')
        filter = {}
        if start_id > 0:
            msg('Skipping GitHub id\'s less than {}'.format(start_id))
            filter['_id'] = {'$gte': start_id}
        if languages:
            msg('Limiting output to entries having languages', languages)
            filter.update(self.language_query(languages))
        if targets:
            msg('Total number of entries: {}'.format(humanize.intcomma(len(targets))))
        else:
            results = self.db.find(filter or targets)
            msg('Total number of entries: {}'.format(humanize.intcomma(results.count())))
        for entry in self.entry_list(filter or targets, fields=['_id'], start_id=start_id):
            msg(entry['_id'])


    def print_details(self, targets={}, languages=None, start_id=0, **kwargs):
        msg('Printing descriptions of indexed GitHub repositories.')
        width = len('DEFAULT BRANCH:')
        filter = {}
        if start_id > 0:
            msg('Skipping GitHub id\'s less than {}'.format(start_id))
            filter['_id'] = {'$gte': start_id}
        if languages:
            msg('Limiting output to entries having languages', languages)
            filter.update(self.language_query(languages))
        for entry in self.entry_list(filter or targets, start_id=start_id):
            msg('='*70)
            msg('ID:'.ljust(width), entry['_id'])
            msg('URL:'.ljust(width), self.github_url(entry))
            msg('NAME:'.ljust(width), entry['name'])
            msg('OWNER:'.ljust(width), entry['owner'])
            if entry['description']:
                msg('DESCRIPTION:'.ljust(width),
                    entry['description'].encode(sys.stdout.encoding, errors='replace'))
            else:
                msg('DESCRIPTION:')
            if entry['languages'] and entry['languages'] != -1:
                msg('LANGUAGES:'.ljust(width), ', '.join(e_languages(entry)))
            else:
                msg('LANGUAGES:')
            if entry['fork'] and entry['fork']['parent']:
                fork_status = 'Yes, forked from ' + entry['fork']['parent']
            elif entry['fork']:
                fork_status = 'Yes'
            else:
                fork_status = 'No'
            msg('FORK:'.ljust(width), fork_status)
            msg('VISIBLE:'.ljust(width), 'Yes' if entry['is_visible'] else 'No')
            msg('DELETED:'.ljust(width), 'Yes' if entry['is_deleted'] else 'No')
            msg('CREATED:'.ljust(width), timestamp_str(entry['time']['repo_created']))
            msg('UPDATED:'.ljust(width), timestamp_str(entry['time']['repo_updated']))
            msg('PUSHED:'.ljust(width), timestamp_str(entry['time']['repo_pushed']))
            msg('DATA REFRESHED:'.ljust(width), timestamp_str(entry['time']['data_refreshed']))
            msg('DEFAULT BRANCH:'.ljust(width), entry['default_branch'])
            if entry['readme'] and entry['readme'] != -1:
                msg('README:')
                msg(entry['readme'])
        msg('='*70)


    def print_summary(self, targets={}, languages=None, start_id=0, **kwargs):
        '''Print a list summarizing indexed repositories.'''
        msg('Summarizing indexed GitHub repositories.')
        filter = {}
        if start_id > 0:
            msg('Skipping GitHub id\'s less than {}'.format(start_id))
            filter['_id'] = {'$gte': start_id}
        if languages:
            msg('Limiting output to entries having languages', languages)
            filter.update(self.language_query(languages))
        fields = ['owner', 'name', '_id', 'languages']
        msg('-'*79)
        for entry in self.entry_list(filter or targets, fields=fields,
                                     start_id=start_id):
            langs = e_languages(entry)
            if langs != -1:
                langs = ' '.join(langs) if langs else ''
            msg('{}/{} (#{}), langs: {}'.format(
                entry['owner'], entry['name'], entry['_id'], langs))
        msg('-'*79)


    def extract_languages_from_html(self, html):
        if not html:
            return False
        marker = 'class="lang">'
        marker_len = len(marker)
        languages = []
        startpoint = html.find(marker)
        while startpoint > 0:
            endpoint = html.find('<', startpoint)
            languages.append(html[startpoint + marker_len : endpoint])
            startpoint = html.find(marker, endpoint)
        # Minor cleanup.
        if 'Other' in languages:
            languages.remove('Other')
        return languages


    def extract_fork_from_html(self, html):
        if not html:
            return False
        spanstart = html.find('<span class="fork-flag">')
        if spanstart > 0:
            marker = '<span class="text">forked from <a href="'
            marker_len = len(marker)
            startpoint= html.find(marker, spanstart)
            if startpoint > 0:
                endpoint = html.find('"', startpoint + marker_len)
                return html[startpoint + marker_len + 1 : endpoint]
            else:
                # Found the section marker, but couldn't parse the text for
                # some reason.  Just return a Boolean value.
                return True
        else:
            return False


    def extract_description_from_html(self, html):
        if not html:
            return False
        marker = 'itemprop="about">'
        marker_len = len(marker)
        description = []
        startpoint = html.find(marker)
        if startpoint > 0:
            endpoint = html.find('</span>', startpoint)
            description = html[startpoint + marker_len : endpoint]
        if description:
            return description.strip()
        else:
            return None


    def get_languages(self, entry):
        # First try to get it by scraping the HTTP web page for the project.
        # This saves an API call.
        languages = []
        fork_info = None
        description = None
        (code, html) = self.get_home_page(entry)
        if code in [404, 451]:
            # 404 = doesn't exist.  451 = unavailable for legal reasons.
            # Don't bother try to get it via API either.
            return (False, 'http', [], None, None)
        if html:
            languages   = self.extract_languages_from_html(html)
            fork_info   = self.extract_fork_from_html(html)
            description = self.extract_description_from_html(html)
            if languages:
                return (True, 'http', languages, fork_info, description)

        # Failed to get it by scraping.  Try the GitHub API.
        # Using github3.py would cause 2 API calls per repo to get this info.
        # Here we do direct access to bring it to 1 api call.
        url = 'https://api.github.com/repos/{}/{}/languages'.format(entry['owner'],
                                                                    entry['name'])
        response = self.direct_api_call(url)
        if isinstance(response, int) and response >= 400:
            return (False, 'api', [], fork_info, description)
        elif response == None:
            return (True, 'api', [], fork_info, description)
        else:
            return (True, 'api', json.loads(response), fork_info, description)


    def get_readme(self, entry, prefer_http=False, api_only=False):
        # First try to get it via direct HTTP access, to save on API calls.
        # If that fails and prefer_http != False, we resport to API calls.

        # The direct HTTP access approach simply tries different alternatives
        # one after the other.  The order is based on the popularity of
        # README file extensions a determined by the following searches on
        # GitHub (updated on 2016-05-09):
        #
        # filename:README                             = 75,305,118
        # filename:README.md extension:md             = 58,495,885
        # filename:README.txt extension:txt           =  4,269,189
        # filename:README.markdown extension:markdown =  2,618,347
        # filename:README.rdoc extension:rdoc         =    627,375
        # filename:README.html                        =    337,131  **
        # filename:README.rst extension:rst           =    244,631
        # filename:README.textile extension:textile   =     49,468
        #
        # ** (this doesn't appear to be common for top-level readme's.)  I
        # decided to pick the top 6.  Another note: using concurrency here
        # doesn't speed things up.  The approach here is to return as soon as
        # we find a result, which is faster than anything else.

        if not api_only:
            exts = ['', '.md', '.txt', '.markdown', '.rdoc', '.rst']
            base_url = 'https://raw.githubusercontent.com/' + e_path(entry)
            for ext in exts:
                alternative = base_url + '/master/README' + ext
                r = requests.get(alternative)
                if r.status_code == 200:
                    return ('http', r.text)

        # If we get here and we're only doing HTTP, then we're done.
        if prefer_http:
            return ('http', None)

        # Resort to GitHub API call.
        # Get the "preferred" readme file for a repository, as described in
        # https://developer.github.com/v3/repos/contents/
        # Using github3.py would need 2 api calls per repo to get this info.
        # Here we do direct access to bring it to 1 api call.
        url = 'https://api.github.com/repos/{}/readme'.format(e_path(entry))
        return ('api', self.direct_api_call(url))


    def get_fork_info(self, entry):
        # As usual, try to get it by scraping the web page.
        (code, html) = self.get_home_page(entry)
        if html:
            fork_info = self.extract_fork_from_html(html)
            if fork_info != None:
                return ('http', fork_info)

        # Failed to scrape it from the web page.  Resort to using the API.
        url = 'https://api.github.com/repos/{}/{}/forks'.format(entry['owner'], entry['name'])
        response = self.direct_api_call(url)
        if response:
            values = json.loads(response)
            return ('api', values['fork'])
        return None


    def add_languages(self, targets=None, start_id=0, **kwargs):
        def body_function(entry):
            t1 = time()
            (found, method, langs, fork, desc) = self.get_languages(entry)
            if not found:
                # Repo was renamed, deleted, made private, or there's
                # no home page.  See if our records need to be updated.
                repo = self.github().repository(entry['owner'], entry['name'])
                if not repo:
                    # Nope, it's gone.
                    self.update_field(entry, 'is_deleted', True)
                    self.update_field(entry, 'is_visible', False)
                    msg('*** {} no longer exists'.format(e_summary(entry)))
                    found = True
                elif entry['owner'] != repo.owner.login \
                     or entry['name'] != repo.name:
                    # The owner or name changed.
                    self.update_field(entry, 'owner', repo.owner.login)
                    self.update_field(entry, 'name', repo.name)
                    # Try again with the info returned by github3.
                    (found, method, langs, fork, desc) = self.get_languages(entry)
                else:
                    msg('*** {} appears to be private'.format(e_summary(entry)))
                    self.update_field(entry, 'is_visible', False)
                    return
            if not found:
                # 2nd attempt failed. Bail.
                msg('*** Failed to get info about {}'.format(e_summary(entry)))
                return
            if not entry['is_deleted']:
                t2 = time()
                fork_info = ', a fork of {},'.format(fork) if fork else ''
                lang_info = len(langs) if langs else 'no languages'
                msg('{}{} in {:.2f}s via {}, {}'.format(
                    e_summary(entry), fork_info, (t2 - t1), method, lang_info))
                if langs:
                    self.update_field(entry, 'languages', make_lang_dict(langs))
                else:
                    self.update_field(entry, 'languages', -1)
                if desc:
                    self.update_field(entry, 'description', desc)
                if fork:
                    if isinstance(fork, str):
                        self.update_fork_field(entry, fork, '')
                    elif entry['fork']['parent'] != '':
                        # The data we got back is only "True" and not a repo
                        # path.  If we have more data about the fork in our
                        # db (meaning it's not ''), we're better off keeping it.
                        pass
                    else:
                        self.update_fork_field(entry, '', '')
                self.update_field(entry, 'is_visible', True)

        msg('Gathering language data for repositories.')
        # Set up default selection criteria WHEN NOT USING 'targets'.
        selected_repos = {'languages': {"$eq" : []}, 'is_deleted': False,
                          'is_visible': {"$ne" : False}}
        if start_id > 0:
            msg('Skipping GitHub id\'s less than {}'.format(start_id))
            selected_repos['_id'] = {'$gte': start_id}
        # And let's do it.
        self.loop(self.entry_list, body_function, selected_repos, targets, start_id)


    def add_readmes(self, targets=None, languages=None, prefer_http=False,
                    api_only=False, start_id=0, force=False, **kwargs):
        def body_function(entry):
            if entry['is_visible'] == False:
                # See note at the end of the parent function (add_readmes).
                return
            t1 = time()
            (method, readme) = self.get_readme(entry, prefer_http, api_only)
            if isinstance(readme, int) and readme in [403, 451]:
                # We hit a problem.  Bubble it up to loop().
                raise DirectAPIException('Getting README', readme)
            if isinstance(readme, int) and readme >= 400:
                # We got a code over 400, probably 404, but don't know why.
                # Repo might have been renamed, deleted, made private, or it
                # has no README file.  If we're only using the API, it means
                # we already tried to get the README using the most certain
                # method (via the API), so we if we think the repo exists, we
                # call it quits now.  Otherwise, we have more ambiguity and
                # we try one more time to find the README file.
                if api_only or prefer_http:
                    msg('No readme for {}'.format(e_summary(entry)))
                    self.update_field(entry, 'readme', -1)
                    return
                repo = self.github().repository(entry['owner'], entry['name'])
                if not repo:
                    # Nope, it's gone.
                    self.update_field(entry, 'is_deleted', True)
                    self.update_field(entry, 'is_visible', False)
                    msg('*** {} no longer exists'.format(e_summary(entry)))
                    return
                elif entry['owner'] != repo.owner.login \
                     or entry['name'] != repo.name:
                    # The owner or name changed.
                    self.update_field(entry, 'owner', repo.owner.login)
                    self.update_field(entry, 'name', repo.name)
                    # Try again with the info returned by github3.
                    (method, readme) = self.get_readme(entry, prefer_http, api_only)
                else:
                    # No readme available.  Drop to the -1 case below.
                    pass

            if readme and not isinstance(readme, int):
                t2 = time()
                msg('{} {} in {:.2f}s via {}'.format(
                    e_summary(entry), len(readme), (t2 - t1), method))
                self.update_field(entry, 'readme', readme)
            else:
                # If GitHub doesn't return a README file, we need to
                # record something to indicate that we already tried.
                # The something can't be '', or None, or 0.  We use -1.
                msg('No readme for {}'.format(e_summary(entry)))
                self.update_field(entry, 'readme', -1)
            self.update_field(entry, 'is_visible', True)

        # Set up default selection criteria WHEN NOT USING 'targets'.
        #
        # Note 2016-05-27: I had trouble with adding a check against
        # is_visible here.  Adding the following tests caused entries to be
        # skipped that (via manual searches without the criteria) clearly
        # should have been returned by the mongodb find() operation:
        #   'is_visible': {"$ne": False}
        #   'is_visible': {"$in": ['', True]}
        # It makes no sense to me, and I don't understand what's going on.
        # To be safer, I removed the check against visibility here, and added
        # an explicit test in body_function() above.
        msg('Gathering README files for repositories.')
        selected_repos = {'is_deleted': False}
        if start_id > 0:
            msg('Skipping GitHub id\'s less than {}'.format(start_id))
            selected_repos['_id'] = {'$gte': start_id}
        if force:
            # "Force" in this context means get readmes even if we previously
            # tried to get them, which is indicated by a -1 value.
            selected_repos['readme'] = {'$in': ['', -1]}
        else:
            selected_repos['readme'] = ''

        # And let's do it.
        self.loop(self.entry_list, body_function, selected_repos, targets, start_id)


    def create_index(self, targets=None, prefer_http=False, overwrite=False, **kwargs):
        '''Create index by looking for new entries in GitHub, or adding entries
        whose id's or owner/name paths are given in the parameter 'targets'.
        If something is already in our database, this won't change it unless
        the flag 'overwrite' is True.
        '''
        def body_function(thing):
            t1 = time()
            if isinstance(thing, github3.repos.repo.Repository):
                (is_new, entry) = self.add_entry_from_github3(thing, overwrite)
                if is_new:
                    msg('{} added'.format(e_summary(entry)))
                elif overwrite:
                    msg('{} updated'.format(e_summary(entry)))
                else:
                    msg('*** Skipping existing entry {}'.format(e_summary(entry)))
            elif overwrite:
                # The targets are not github3 objects but rather our database
                # entry dictionaries, which means they're in our database,
                # which means we're doing updates of existing entries.
                entry = thing
                repo = self.github().repository(entry['owner'], entry['name'])
                if repo:
                    self.update_entry_from_github3(entry, repo)
                    msg('{} updated'.format(e_summary(entry)))
                else:
                    msg('*** {} no longer exists'.format(e_summary(entry)))
                    self.update_field(entry, 'is_visible', False)
            else:
                # We have an entry already, but we're not doing an update.
                msg('*** Skipping existing entry {}'.format(e_summary(thing)))

        msg('Indexing GitHub repositories.')
        if overwrite:
            msg('Overwriting existing data.')
        if targets:
            # We have a list of id's or repo paths.
            if overwrite:
                # Using the overwrite flag only makes sense if we expect that
                # the entries are in the database already => use entry_list()
                repo_iterator = self.entry_list
            else:
                # We're indexing but not overwriting. We assume that what
                # we're given as targets are completely new repo id's or paths.
                if prefer_http:
                    repo_iterator = self.repo_list_prefer_http
                else:
                    repo_iterator = self.repo_list
        else:
            last_seen = self.get_last_seen_id()
            total = humanize.intcomma(self.db.count())
            msg('Database has {} total GitHub entries.'.format(total))
            if last_seen:
                msg('Continuing from highest-known id {}'.format(last_seen))
            else:
                msg('No record of the last-seen repo.  Starting from the top.')
                last_seen = -1
            repo_iterator = self.get_github_iterator

        # Set up selection criteria and start the loop
        self.loop(repo_iterator, body_function, None, targets or last_seen)


    def recreate_index(self, targets=None, prefer_http=False, **kwargs):
        '''Reindex entries from GitHub, even if they are already in our db.'''
        self.create_index(targets, prefer_http=prefer_http, overwrite=True)


    def verify_index(self, targets=None, prefer_http=False, overwrite=False,
                     start_id=None, **kwargs):
        '''Verify entries against GitHub.  Does not modify anything unless the
        flag 'overwrite' is true.
        '''
        def check(entry, entry_field, repo, repo_field):
            if hasattr(repo, repo_field):
                if entry[entry_field] != getattr(repo, repo_field):
                    newvalue = getattr(repo, repo_field)
                    msg('*** {} {} changed from {} to {}'.format(
                        e_summary(entry), entry_field, entry[entry_field], newvalue))
                    self.update_field(entry, entry_field, newvalue)
            else:
                import ipdb; ipdb.set_trace()

        def body_function(entry):
            t1 = time()
            if entry['is_deleted']:
                msg('*** {} known to be deleted -- skipping'.format(e_summary(entry)))
                return
            if not entry['is_visible']:
                msg('*** {} known to be not visible -- skipping'.format(e_summary(entry)))
                return
            owner = entry['owner']
            name = entry['name']
            repo = self.repo_via_api(owner, name)
            if not repo:
                # The repo must have existed at some point because we have it
                # in our database, but the API no longer returns it for this
                # owner/name combination.
                msg('*** {} no longer found in GitHub -- marking as deleted'.format(
                    e_summary(entry)))
                self.update_field(entry, 'is_deleted', True)
                self.update_field(entry, 'is_visible', False)
                return
            else:
                if entry['_id'] == repo.id:
                    self.update_entry_from_github3(entry, repo)
                    msg('{} verified'.format(e_summary(entry)))
                else:
                    # Have to delete and recreate the entry to update _id.
                    msg('*** id changed for {} -- created new entry as #{}'.format(
                        e_summary(entry), repo.id))
                    # It existed under this id at one time. Mark it deleted.
                    self.update_field(entry, 'is_deleted', True)
                    self.update_field(entry, 'is_visible', False)
                    # Create whole new entry for the new id.
                    (is_new, entry) = self.add_entry_from_github3(repo, True)

                if entry and entry['is_visible']:
                    # Try to get the readme.
                    try:
                        (method, readme) = self.get_readme(entry, prefer_http, False)
                        if readme and not isinstance(readme, int):
                            self.update_field(entry, 'readme', readme)
                    except:
                        msg('*** failed to get readme for {}'.format(e_summary(entry)))


        if overwrite:
            msg('Verifying and reconciling database entries against GitHub.')
        else:
            msg('Verifying database entries with GitHub.')
        if targets:
            # We have an explicit list of id's or repo paths.
            repo_iterator = self.entry_list
        else:
            # We don't have a list => we're running through all of them.
            repo_iterator = self.get_github_iterator
            total = humanize.intcomma(self.db.count())
            msg('Database has {} total GitHub entries.'.format(total))

        # Set up selection criteria and start the loop
        self.loop(repo_iterator, body_function, None, targets, start_id)




    # =============================================================================

    # def add_record_from_github3(self, repo):
    #     # Match impedances between github3's record format and ours.
    #     # 'repo' is github3 object.

    #     if repo.fork and repo.parent:
    #         copy_info = repo.parent.owner.login + '/' + repo.parent.name
    #     else:
    #         copy_info = repo.fork
    #     if repo.id in db:
    #         # Update an existing entry.  The github3 record has less info
    #         # than we keep, so grab the old values for the other fields, but
    #         # update the 'refreshed' field value to now.
    #         old_entry = db[repo.id]
    #         db[repo.id].name        = repo.name
    #         db[repo.id].owner       = repo.owner.login
    #         db[repo.id].owner_type  = canonicalize_owner_type(repo.owner.type)
    #         db[repo.id].description = repo.description
    #         db[repo.id].copy_of     = copy_info
    #         db[repo.id].owner_type  = repo.owner.type
    #         db[repo.id].created     = canonicalize_timestamp(repo.created_at)
    #         db[repo.id].refreshed   = now_timestamp()
    #         db[repo.id].deleted     = False
    #     else:
    #         # New entry.
    #         db[repo.id] = RepoData(host=Host.GITHUB,
    #                                id=repo.id,
    #                                name=repo.name,
    #                                owner=repo.owner.login,
    #                                description=repo.description,
    #                                copy_of=copy_info,
    #                                owner_type=repo.owner.type,
    #                                created=repo.created_at,
    #                                refreshed=now_timestamp())

    # def add_name_mapping(self, entry, db):
    #     mapping = self.get_name_mapping(db)
    #     mapping[entry.owner + '/' + entry.name] = entry.id


    # def get_globals(self, db):
    #     # We keep globals at position 0 in the database, since repo identifiers
    #     # in GitHub start at 1.
    #     if 0 in db:
    #         return db[0]
    #     else:
    #         db[0] = Bucket()            # This needs to be an OOBucket.
    #         return db[0]


    # def set_in_globals(self, var, value, db):
    #     globals = self.get_globals(db)
    #     globals[var] = value


    # def from_globals(self, db, var):
    #     globals = self.get_globals(db)
    #     return globals[var] if var in globals else None


    # def set_last_seen(self, id, db):
    #     self.set_in_globals('last seen id', id, db)


    # def get_last_seen(self, db):
    #     return self.from_globals(db, 'last seen id')


    # def set_highest_github_id(self, id, db):
    #     self.set_in_globals('highest id number', id, db)


    # def get_highest_github_id(self, db):
    #     globals = self.get_globals(db)
    #     highest = self.from_globals(db, 'highest id number')
    #     if highest:
    #         return highest
    #     else:
    #         msg('Did not find a record of the highest id.  Searching now...')
    #         import ipdb; ipdb.set_trace()


    # def set_language_list(self, value, db):
    #     self.set_in_globals('entries with languages', value, db)


    # def get_language_list(self, db):
    #     key = 'entries with languages'
    #     lang_list = self.from_globals(db, key)
    #     if lang_list != None:           # Need explicit test against None.
    #         return lang_list
    #     else:
    #         msg('Did not find list of entries with languages. Creating it.')
    #         self.set_in_globals(key, TreeSet(), db)
    #         return self.from_globals(db, key)


    # def set_readme_list(self, value, db):
    #     self.set_in_globals('entries with readmes', value, db)


    # def get_readme_list(self, db):
    #     key = 'entries with readmes'
    #     readme_list = self.from_globals(db, key)
    #     if readme_list != None:           # Need explicit test against None.
    #         return readme_list
    #     else:
    #         msg('Did not find list of entries with readmes. Creating it.')
    #         self.set_in_globals(key, TreeSet(), db)
    #         return self.from_globals(db, key)


    # def set_total_entries(self, count, db):
    #     self.set_in_globals('total entries', count, db)


    # def get_total_entries(self, db):
    #     key = 'total entries'
    #     globals = self.get_globals(db)
    #     if key in globals:
    #         return globals[key]
    #     else:
    #         msg('Did not find a count of entries.  Counting now...')
    #         count = len(list(db.keys()))
    #         self.set_total_entries(count, db)
    #         return count


    # def set_name_mapping(self, value, db):
    #     self.set_in_globals('name to identifier mapping', value, db)


    # def get_name_mapping(self, db):
    #     key = 'name to identifier mapping'
    #     mapping = self.from_globals(db, key)
    #     if mapping != None:           # Need explicit test against None.
    #         return mapping
    #     else:
    #         msg('Did not find name to identifier mapping.  Creating it.')
    #         self.set_in_globals(key, OIBTree(), db)
    #         return self.from_globals(db, key)


    # def recreate_index(self, db, id_list=None):
    #     self.create_index(db, id_list, continuation=False)


    # def create_index(self, db, id_list=None, continuation=True):
    #     count = self.get_total_entries(db)
    #     msg('There are {} entries currently in the database'.format(count))

    #     last_seen = self.get_last_seen(db)
    #     if last_seen:
    #         if continuation:
    #             msg('Continuing from highest-known id {}'.format(last_seen))
    #         else:
    #             msg('Ignoring last id {} -- starting from the top'.format(last_seen))
    #             last_seen = -1
    #     else:
    #         msg('No record of the last repo id seen.  Starting from the top.')
    #         last_seen = -1

    #     calls_left = self.api_calls_left()
    #     msg('Initial GitHub API calls remaining: ', calls_left)

    #     # The iterator returned by github.all_repositories() is continuous; behind
    #     # the scenes, it uses the GitHub API to get new data when needed.  Each API
    #     # call nets 100 repository records, so after we go through 100 objects in the
    #     # 'for' loop below, we expect that github.all_repositories() will have made
    #     # another call, and the rate-limited number of API calls left in this
    #     # rate-limited period will go down by 1.  When we hit the limit, we pause
    #     # until the reset time.

    #     if id_list:
    #         repo_iterator = iter(id_list)
    #     else:
    #         repo_iterator = self.get_github_iterator(last_seen)
    #     loop_count    = 0
    #     failures      = 0
    #     start         = time()
    #     while failures < self._max_failures:
    #         try:
    #             repo = next(repo_iterator)
    #             if repo is None:
    #                 break

    #             update_count = True
    #             if isinstance(repo, int):
    #                 # GitHub doesn't provide a way to go from an id to a repo,
    #                 # so all we can do if we're using a list of identifiers is
    #                 # update our existing entry (if we know about it already).
    #                 identifier = repo
    #                 if identifier in db:
    #                     msg('Overwriting entry for #{}'.format(identifier))
    #                     entry = db[identifier]
    #                     repo = self.github().repository(entry.owner, entry.name)
    #                     update_count = False
    #                 else:
    #                     msg('Skipping {} -- unknown repo id'.format(repo))
    #                     continue
    #             else:
    #                 identifier = repo.id
    #                 if identifier in db:
    #                     if continuation:
    #                         msg('Skipping {}/{} (id #{}) -- already known'.format(
    #                             repo.owner.login, repo.name, identifier))
    #                         continue
    #                     else:
    #                         msg('Overwriting entry {}/{} (id #{})'.format(
    #                             repo.owner.login, repo.name, identifier))
    #                         update_count = False

    #             self.add_record_from_github3(repo, db)
    #             if update_count:
    #                 count += 1
    #                 msg('{}: {}/{} (id #{})'.format(count, repo.owner.login, repo.name, identifier))
    #                 self.set_total_entries(count, db)
    #             if identifier > last_seen:
    #                 self.set_last_seen(identifier, db)
    #             transaction.commit()
    #             failures = 0

    #             loop_count += 1
    #             if loop_count > 100:
    #                 calls_left = self.api_calls_left()
    #                 if calls_left > 1:
    #                     loop_count = 0
    #                 else:
    #                     self.wait_for_reset()
    #                     calls_left = self.api_calls_left()

    #         except StopIteration:
    #             msg('github3 repository iterator reports it is done')
    #             break
    #         except github3.GitHubError as err:
    #             # Occasionally an error even when not over the rate limit.
    #             if err.code == 403:
    #                 msg('Code 403 for {}'.format(repo.id))
    #                 calls_left = self.api_calls_left()
    #                 if calls_left < 1:
    #                     self.wait_for_reset()
    #                     calls_left = self.api_calls_left()
    #                     loop_count = 0
    #                 else:
    #                     failures += 1
    #             elif err.code == 451:
    #                 msg('GitHub replied with code 451 (access blocked) for {}/{} ({})'.format(
    #                     entry.owner, entry.name, entry.id))
    #                 retry = False
    #             else:
    #                 msg('github3 generated an exception: {0}'.format(err))
    #                 failures += 1
    #         except Exception as err:
    #             msg('Exception: {0}'.format(err))
    #             failures += 1

    #     transaction.commit()
    #     if failures >= self._max_failures:
    #         msg('Stopping because of too many repeated failures.')
    #     else:
    #         msg('Done.')


    # def update_entries(self, db, targets=None):
    #     msg('Initial GitHub API calls remaining: ', self.api_calls_left())
    #     failures = 0
    #     start = time()

    #     if targets:
    #         mapping = self.get_name_mapping(db)
    #         id_list = [self.ensure_id(x, mapping) for x in targets]
    #     else:
    #         # If we're iterating over the entire database, we have to make a
    #         # copy of the keys list because we can't iterate on the database
    #         # if the number of elements may be changing.  Making this list is
    #         # incredibly inefficient and takes many minutes to create.
    #         id_list = list(db.keys())

    #     entries_with_languages = self.get_language_list(db)
    #     entries_with_readmes = self.get_readme_list(db)
    #     for count, key in enumerate(id_list):
    #         if key not in db:
    #             msg('Repository id {} is unknown'.format(key))
    #             continue
    #         entry = db[key]
    #         if not hasattr(entry, 'id'):
    #             continue

    #         # FIXME TEMPORARY HACK
    #         # if entry.refreshed:
    #         #     continue

    #         if self.api_calls_left() < 1:
    #             self.wait_for_reset()
    #             failures = 0

    #         retry = True
    #         while retry and failures < self._max_failures:
    #             # Don't retry unless the problem may be transient.
    #             retry = False
    #             try:
    #                 t1 = time()
    #                 repo = self.github().repository(entry.owner, entry.name)
    #                 if not repo:
    #                     entry.deleted = True
    #                     msg('{}/{} (#{}) deleted'.format(entry.owner, entry.name,
    #                                                      entry.id))
    #                 else:
    #                     entry.owner = repo.owner.login
    #                     entry.name = repo.name
    #                     self.add_record_from_github3(repo, db)
    #                     # We know the repo exists.  Get more info but use our
    #                     # http-based method because it gets more data.
    #                     (found, method, langs, fork) = self.get_languages(entry)
    #                     if not found:
    #                         msg('Failed to update {}/{} (#{}) but it supposedly exists'.format(
    #                             entry.owner, entry.name, entry.id))
    #                     else:
    #                         languages = [Language.identifier(x) for x in langs]
    #                         entry.languages = languages
    #                         if key not in entries_with_languages:
    #                             msg('entries_with_languages <-- {}/{} (#{})'.format(
    #                                 entry.owner, entry.name, entry.id))

    #                     # Ditto for the README.
    #                     (method, readme) = self.get_readme(entry)
    #                     if readme and readme != 404:
    #                         entry.readme = zlib.compress(bytes(readme, 'utf-8'))
    #                         if key not in entries_with_readmes:
    #                             msg('entries_with_readmes <-- {}/{} (#{})'.format(
    #                                 entry.owner, entry.name, entry.id))

    #                     t2 = time()
    #                     msg('{}/{} (#{}) in {:.2f}s'.format(
    #                         entry.owner, entry.name, entry.id, t2 - t1))

    #                 entry.refreshed = now_timestamp()
    #                 entry._p_changed = True # Needed for ZODB record updates.
    #                 failures = 0
    #             except github3.GitHubError as err:
    #                 # Occasionally an error even when not over the rate limit.
    #                 if err.code == 403:
    #                     calls_left = self.api_calls_left()
    #                     if calls_left < 1:
    #                         msg('GitHub API rate limit exceeded')
    #                         self.wait_for_reset()
    #                         loop_count = 0
    #                         calls_left = self.api_calls_left()
    #                         retry = True
    #                     else:
    #                         msg('GitHub replied with code 403 for {}/{} ({})'.format(
    #                             entry.owner, entry.name, entry.id))
    #                         entry.refreshed = now_timestamp()
    #                         retry = False
    #                         failures += 1
    #                 elif err.code == 451:
    #                     msg('GitHub replied with code 451 (access blocked) for {}/{} ({})'.format(
    #                         entry.owner, entry.name, entry.id))
    #                     entry.refreshed = now_timestamp()
    #                     retry = False
    #                 else:
    #                     msg('GitHub API exception: {0}'.format(err))
    #                     failures += 1
    #                     # Might be a network or other transient error.
    #                     retry = True
    #             except Exception as err:
    #                 msg('Exception for "{}/{}": {}'.format(entry.owner, entry.name, err))
    #                 failures += 1
    #                 # Might be a network or other transient error.
    #                 retry = True

    #         if failures >= self._max_failures:
    #             msg('Stopping because of too many consecutive failures')
    #             break
    #         if count % 100 == 0:
    #             transaction.commit()
    #             msg('{} [{:2f}]'.format(count, time() - start))
    #             start = time()

    #     transaction.commit()
    #     msg('')
    #     msg('Done.')


    # def add_fork_info(self, db, targets=None):
    #     msg('Initial GitHub API calls remaining: ', self.api_calls_left())
    #     failures = 0
    #     start = time()

    #     if targets:
    #         mapping = self.get_name_mapping(db)
    #         id_list = [self.ensure_id(x, mapping) for x in targets]
    #     else:
    #         # If we're iterating over the entire database, we have to make a
    #         # copy of the keys list because we can't iterate on the database
    #         # if the number of elements may be changing.  Making this list is
    #         # incredibly inefficient and takes many minutes to create.
    #         id_list = list(db.keys())

    #     for count, key in enumerate(id_list):
    #         if key not in db:
    #             msg('repository id {} is unknown'.format(key))
    #             continue
    #         entry = db[key]
    #         if not hasattr(entry, 'id'):
    #             continue
    #         if entry.copy_of != None:
    #             # Already have the info.
    #             continue
    #         if entry.deleted:
    #             msg('Skipping {} because it is marked deleted'.format(entry.id))

    #         retry = True
    #         while retry and failures < self._max_failures:
    #             # Don't retry unless the problem may be transient.
    #             retry = False
    #             try:
    #                 t1 = time()
    #                 (method, fork_info) = self.get_fork_info(entry)
    #                 t2 = time()
    #                 if fork_info != None:
    #                     msg('{}/{} (#{}) in {:.2f}s via {}: {}'.format(
    #                         entry.owner, entry.name, entry.id, t2-t1, method,
    #                         'fork' if fork_info else 'not fork'))
    #                     entry.copy_of = fork_info
    #                     entry.refreshed = now_timestamp()
    #                     entry._p_changed = True # Needed for ZODB record updates.
    #                 else:
    #                     msg('Failed to get fork info for {}/{} (#{})'.format(
    #                         entry.owner, entry.name, entry.id))
    #                 failures = 0
    #             except github3.GitHubError as err:
    #                 # Occasionally an error even when not over the rate limit.
    #                 if err.code == 403:
    #                     calls_left = self.api_calls_left()
    #                     if calls_left < 1:
    #                         msg('GitHub API rate limit exceeded')
    #                         self.wait_for_reset()
    #                         loop_count = 0
    #                         calls_left = self.api_calls_left()
    #                         retry = True
    #                     else:
    #                         msg('GitHub replied with code 403 for {}/{} ({})'.format(
    #                             entry.owner, entry.name, entry.id))
    #                         entry.refreshed = now_timestamp()
    #                         retry = False
    #                         failures += 1
    #                 elif err.code == 451:
    #                     msg('GitHub replied with code 451 (access blocked) for {}/{} ({})'.format(
    #                         entry.owner, entry.name, entry.id))
    #                     retry = False
    #                 else:
    #                     msg('GitHub API exception: {0}'.format(err))
    #                     failures += 1
    #                     # Might be a network or other transient error.
    #                     retry = True
    #             except Exception as err:
    #                 msg('Exception for "{}/{}": {}'.format(entry.owner, entry.name, err))
    #                 failures += 1
    #                 # Might be a network or other transient error.
    #                 retry = True

    #         if failures >= self._max_failures:
    #             msg('Stopping because of too many consecutive failures')
    #             break
    #         transaction.commit()
    #         if count % 100 == 0:
    #             msg('{} [{:2f}]'.format(count, time() - start))
    #             start = time()

    #     transaction.commit()
    #     msg('')
    #     msg('Done.')


    # def mark_deleted(self, db, targets=None):
    #     if not targets:
    #         raise ValueError('Must identify specific repositories to delete.')
    #     start = time()
    #     mapping = self.get_name_mapping(db)
    #     list = [self.ensure_id(x, mapping) for x in targets]
    #     for count, key in enumerate(list):
    #         if key not in db:
    #             msg('repository id {} is unknown'.format(key))
    #             continue
    #         entry = db[key]
    #         entry.deleted = True
    #         entry._p_changed = True # Needed for ZODB record updates.
    #         if count % 1000 == 0:
    #             msg('{} [{:2f}]'.format(count, time() - start))
    #             start = time()
    #             Transaction.commit()

    #     transaction.commit()
    #     msg('')
    #     msg('Done.')




    # -------
    # older
    # -------

    # def locate_by_languages(self, db):
    #     msg('Examining our current database')
    #     count = self.get_total_entries(db)
    #     msg('There are {} entries in the database'.format(count))

    #     # We have to do 2 separate searches because there does not seem to
    #     # be an "or" operator in the GitHub search syntax.

    #     # The iterator returned by github.search_repositories() is
    #     # continuous; behind the scenes, it uses the GitHub API to get new
    #     # data when needed.  Each API call nets 100 repository records, so
    #     # after we go through 100 objects in the 'for' loop below, we expect
    #     # that github.all_repositories() will have made another call, and the
    #     # rate-limited number of API calls left in this rate-limited period
    #     # will go down by 1.  When we hit the rate limit max, we pause until
    #     # the reset time.

    #     calls_left = self.api_calls_left()
    #     msg('Initial GitHub API calls remaining: ', calls_left)

    #     # Java

    #     search_iterator = self.get_search_iterator("language:java")
    #     loop_count    = 0
    #     failures      = 0
    #     while failures < self._max_failures:
    #         try:
    #             search_result = next(search_iterator)
    #             if search_result is None:
    #                 msg('Empty return value from github3 iterator')
    #                 failures += 1
    #                 continue

    #             repo = search_result.repository
    #             if repo.full_name in db:
    #                 # We have this in our database.  Good.
    #                 entry = db[repo.full_name]
    #                 if entry.languages:
    #                     if not Language.JAVA in entry.languages:
    #                         entry.languages.append(Language.JAVA)
    #                         entry._p_changed = True
    #                     else:
    #                         msg('Already knew about {}'.format(repo.full_name))
    #                 else:
    #                     entry.languages = [Language.JAVA]
    #                     entry._p_changed = True
    #             else:
    #                 # We don't have this in our database.  Add a new record.
    #                 try:
    #                     add_record(repo, db, languages=[Language.JAVA])
    #                     msg('{}: {} (GitHub id: {})'.format(count,
    #                                                         repo.full_name,
    #                                                         repo.id))
    #                     count += 1
    #                     failures = 0
    #                 except Exception as err:
    #                     msg('Exception when creating RepoEntry: {0}'.format(err))
    #                     failures += 1
    #                     continue

    #             self.set_last_seen(repo.id, db)
    #             self.set_total_entries(count, db)
    #             transaction.commit()

    #             loop_count += 1
    #             if loop_count > 100:
    #                 calls_left = self.api_calls_left()
    #                 if calls_left > 1:
    #                     loop_count = 0
    #                 else:
    #                     self.wait_for_reset()
    #                     calls_left = self.api_calls_left()

    #         except StopIteration:
    #             msg('github3 search iterator reports it is done')
    #             break
    #         except github3.GitHubError as err:
    #             if err.code == 403:
    #                 msg('GitHub API rate limit reached')
    #                 self.wait_for_reset()
    #                 loop_count = 0
    #                 calls_left = self.api_calls_left()
    #             else:
    #                 msg('github3 generated an exception: {0}'.format(err))
    #                 failures += 1
    #         except Exception as err:
    #             msg('github3 generated an exception: {0}'.format(err))
    #             failures += 1

    #     transaction.commit()
    #     if failures >= self._max_failures:
    #         msg('Stopping because of too many repeated failures.')
    #     else:
    #         msg('Done.')




    # This will no longer work, with the switch to using id numbers as keys.
    # Keeping it here because the sequence of steps took time to work out
    # and may be applicable to other things.
    #
    # def create_index_using_list(self, db, project_list):
    #     calls_left = self.api_calls_left()
    #     msg('Initial GitHub API calls remaining: ', calls_left)

    #     count = self.get_total_entries(db)
    #     if not count:
    #         msg('Did not find a count of entries.  Counting now...')
    #         count = db.__len__()
    #         self.set_total_entries(count, db)
    #     msg('There are {} entries in the database'.format(count))

    #     last_seen = self.get_last_seen(db)

    #     failures   = 0
    #     loop_count = 0
    #     with open(project_list, 'r') as f:
    #         for line in f:
    #             retry = True
    #             while retry and failures < self._max_failures:
    #                 # Don't retry unless the problem may be transient.
    #                 retry = False
    #                 try:
    #                     full_name = line.strip()
    #                     if full_name in db:
    #                         msg('Skipping {} -- already known'.format(full_name))
    #                         continue
    #                     if requests.get('http://github.com/' + full_name).status_code == 404:
    #                         msg('{} not found in GitHub using https'.format(full_name))
    #                         continue

    #                     owner = full_name[:full_name.find('/')]
    #                     project = full_name[full_name.find('/') + 1:]
    #                     repo = self.github().repository(owner, project)

    #                     if not repo:
    #                         msg('{} not found in GitHub using API'.format(full_name))
    #                         continue
    #                     if repo.full_name in db:
    #                         msg('Already know {} renamed from {}'.format(repo.full_name,
    #                                                                      full_name))
    #                         continue

    #                     self.add_record_from_github3(repo, db)
    #                     msg('{}: {} (GitHub id: {})'.format(count, repo.full_name,
    #                                                         repo.id))
    #                     count += 1
    #                     failures = 0
    #                     if repo.id > last_seen:
    #                         self.set_last_seen(repo.id, db)
    #                     self.set_total_entries(count, db)

    #                     transaction.commit()

    #                     loop_count += 1
    #                     if loop_count > 100:
    #                         calls_left = self.api_calls_left()
    #                         if calls_left > 1:
    #                             loop_count = 0
    #                         else:
    #                             self.wait_for_reset()
    #                             calls_left = self.api_calls_left()
    #                 except github3.GitHubError as err:
    #                     if err.code == 403:
    #                         msg('GitHub API rate limit reached')
    #                         self.wait_for_reset()
    #                         loop_count = 0
    #                         calls_left = self.api_calls_left()
    #                     else:
    #                         msg('GitHub API error: {0}'.format(err))
    #                         failures += 1
    #                         # Might be a network or other transient error.
    #                         retry = True
    #                 except Exception as err:
    #                     msg('github3 generated an exception: {0}'.format(err))
    #                     failures += 1
    #                     # Might be a network or other transient error.
    #                     retry = True

    #             # Stop for-loop if we accumulate too many failures.
    #             if failures >= self._max_failures:
    #                 msg('Stopping because of too many repeated failures.')
    #                 break

    #     transaction.commit()
    #     msg('Done.')


# Tried this concurrent approach but it's slower.


# def get_file_http(path):
#     # Needed as top-level function so that concurrent processes can be used.
#     r = requests.get(path)
#     return r.text if r.status_code == 200 else None

#         pool = Pool(processes=2)
#         files = list(filter(None, pool.map(get_file_http, urls)))
#         if files:
#             return ('http', files[0])
