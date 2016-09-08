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
import json
import http
import pprint
import urllib
import github3
import humanize
import socket
import langid
import markdown
import re
import warnings
from bs4 import BeautifulSoup
from base64 import b64encode
from datetime import datetime
from time import time, sleep

sys.path.append(os.path.join(os.path.dirname(__file__), "../common"))
sys.path.append(os.path.join(os.path.dirname(__file__), "../database"))
from casicsdb import *
from utils import *
from content_inferencer import *
from github_html import *


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
        msg('*** Unrecognize type of thing: "{}" ***'.format(thing))


# Error classes for internal communication.
# .............................................................................

class DirectAPIException(Exception):
    def __init__(self, message, code):
        message = str(message).encode('utf-8')
        super(DirectAPIException, self).__init__(message)
        self.code = code


class UnexpectedResponseException(Exception):
    def __init__(self, message, code):
        message = str(message).encode('utf-8')
        super(UnexpectedResponseException, self).__init__(message)
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
            msg('*** Unexpected failure in logging into GitHub')
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
            msg('*** Got exception asking about rate limit: {}'.format(err))
            msg('*** Sleeping for 1 minute and trying again.')
            sleep(60)
            msg('Trying again.')
            try:
                return calls_left()
            except Exception as err:
                msg('*** Got another exception asking about rate limit: {}'.format(err))
                # Treat it as no time left.  Caller should pause for longer.
                return 0


    def api_reset_time(self):
        '''Returns a timestamp value, i.e., seconds since epoch.'''
        try:
            rate_limit = self.github().rate_limit()
            return rate_limit['resources']['core']['reset']
        except Exception as err:
            msg('*** Got exception asking about reset time: {}'.format(err))
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
                return (True, self.github().repository(owner, name))
            except github3.GitHubError as err:
                if err.code == 403:
                    # This can happen for rate limits, and also when there is
                    # a disk error or other problem on GitHub. (It's happened.)
                    if self.api_calls_left() < 1:
                        self.wait_for_reset()
                        failures += 1
                        retry = True
                    else:
                        msg('*** GitHb code 403 for {}/{}'.format(owner, name))
                        return (False, None)
                elif err.code == 451:
                    # https://developer.github.com/changes/2016-03-17-the-451-status-code-is-now-supported/
                    msg('*** GitHub code 451 (blocked) for {}/{}'.format(owner, name))
                    break
                else:
                    msg('*** github3 generated an exception: {0}'.format(err))
                    failures += 1
                    # Might be a network or other transient error. Try again.
                    sleep(0.5)
                    retry = True
            except Exception as err:
                msg('*** Exception for {}/{}: {}'.format(owner, name, err))
                # Something even more unexpected.
                return (False, None)
        return (True, None)


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
                msg('*** Failed direct api call: {}'.format(err))
                return None
        conn.request("GET", url, {}, headers)
        response = conn.getresponse()
        # First check for 202, "accepted". Wait half a second and try again.
        if response.status == 202:
            sleep(0.5)                  # Arbitrary.
            msg('*** Got code 202 for {} -- retrying'.format(url))
            return self.direct_api_call(url)
        # Note: next "if" must not be an "elif"!
        if response.status == 200:
            content = response.readall()
            try:
                return content.decode('utf-8')
            except:
                # Content is either binary or garbled.  We can't deal with it,
                # so we return an empty string.
                msg('*** Undecodable content received for {}'.format(url))
                return ''
        elif response.status == 301:
            # Redirection.  Start from the top with new URL.
            return self.direct_api_call(response.getheader('Location'))
        else:
            msg('*** Response status {} for {}'.format(response.status, url))
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
                msg('*** Failed url check for {}: {}'.format(url_path, err))
                return None
        conn.request('HEAD', url_path)
        resp = conn.getresponse()
        if resp.status == 200:
            return url_path
        elif resp.status < 400:
            return resp.headers['Location']
        else:
            return False


    def github_current_owner_name(self, entry, owner=None, name=None):
        '''Visit the repo on github.com using HTTP and return the current
        owner and name as a tuple.  This may be the same as 'owner' and 'name'
        or it may be different if the repo has moved.'''
        if entry and not owner:
            owner = entry['owner']
        if entry and not name:
            name = entry['name']
        url = self.github_url_exists(None, owner, name)
        if not url:
            return (None, None)
        else:
            return self.owner_name_from_github_url(url)


    def owner_name_from_github_url(self, url):
        '''Returns a tuple of (owner, name).'''
        if url.startswith('https'):
            # length of https://github.com/ = 18
            path = url[19:]
            return (path[:path.find('/')], path[path.find('/') +1:])
        elif url.startswith('http'):
            path = url[18:]
            return (path[:path.find('/')], path[path.find('/') +1:])
        elif url.startswith('/'):
            path = url[1:]
            return (path[:path.find('/')], path[path.find('/') +1:])
        else:
            return (None, None)


    def github_iterator(self, last_seen=None, start_id=None):
        try:
            if last_seen or start_id:
                since = last_seen or start_id
                return self.github().iter_all_repos(since=since)
            else:
                return self.github().iter_all_repos()
        except Exception as err:
            msg('*** github.iter_all_repos() failed with {0}'.format(err))
            sys.exit(1)


    def last_seen_id(self):
        last = self.db.find_one({'$query':{}, '$orderby':{'_id':-1}}, {})
        return last['_id']


    def add_entry_from_github3(self, repo, overwrite=False):
        # 'repo' is a github3 object.  Returns True if it's a new entry.
        entry = self.db.find_one({'_id' : repo.id})
        if entry == None:
            # Create a new entry.
            # This purposefully does not change 'languages' and 'readme',
            # because they are not in the github3 structure and if we're
            # updating an existing entry in our database, we don't want to
            # destroy those fields if we have them.  Also: the github3 api
            # does not have all the fields we store.
            fork_of = repo.parent.full_name if repo.parent else None
            fork_root = repo.source.full_name if repo.source else None
            languages = make_languages([repo.language]) if repo.language else []
            entry = repo_entry(id=repo.id,
                               name=repo.name,
                               owner=repo.owner.login,
                               description=repo.description,
                               languages=languages,
                               default_branch=repo.default_branch,
                               homepage=repo.homepage,
                               is_deleted=False,
                               is_visible=not repo.private,
                               is_fork=repo.fork,
                               fork_of=fork_of,
                               fork_root=fork_root,
                               created=canonicalize_timestamp(repo.created_at),
                               last_updated=canonicalize_timestamp(repo.updated_at),
                               last_pushed=canonicalize_timestamp(repo.pushed_at),
                               data_refreshed=now_timestamp())
            self.db.insert_one(entry)
            return (True, entry)
        elif overwrite:
            return (False, self.update_entry_from_github3(entry, repo))
        else:
            return (False, entry)


    def update_entry_from_github3(self, entry, repo, force=False):
        # Update or delete entry, based on repo object from github3 API.
        summary = e_summary(entry)
        if not repo:
            # The repo must have existed at some point because we have it in
            # our database, but the API no longer returns it for this
            # owner/name combination.
            msg('*** {} no longer found -- marking deleted'.format(summary))
            self.mark_entry_deleted(entry)
            return None
        elif entry['_id'] != repo.id:
            # Same owner & name, but different id.  It might have been
            # deleted and recreated by the user (which would generate a new
            # id in GitHub).  Create a new entry for the updated _id.
            msg('*** {} id changed -- creating #{}'.format(summary, repo.id))
            (_, new_entry) = self.add_entry_from_github3(repo, True)
            # Mark the old entry as deleted.
            self.mark_entry_deleted(entry)
            msg('{} marked as deleted'.format(summary))
            return new_entry

        # Since github3 accesses the live github API, whatever data we get,
        # we assume is authoritative and overrides almost everything we may
        # already have for the entry.  However, we're careful not to
        # overwrite data like 'languages' and 'readme' because we may have
        # more info than what is supplied by the repo entry via the API.
        updates = {}
        if entry['is_deleted'] != False:
            # We found it via github3 => not deleted.
            msg('{} deleted status set to False'.format(summary))
            updates['is_deleted'] = entry['is_deleted'] = False
        if entry['is_visible'] != bool(not repo.private):
            msg('{} visibility changed to {}'.format(summary, not repo.private))
            updates['is_visible'] = entry['is_visible'] = bool(not repo.private)
        if entry['owner'] != repo.owner.login:
            msg('{} owner changed to {}'.format(summary, repo.owner.login))
            updates['owner'] = entry['owner'] = repo.owner.login
        if entry['name'] != repo.name:
            msg('{} repo name changed to {}'.format(summary, repo.name))
            updates['name'] = entry['name'] = repo.name
        if entry['description'] != repo.description.strip():
            msg('{} description changed'.format(summary))
            updates['description'] = entry['description'] = repo.description.strip()
        if entry['default_branch'] != repo.default_branch:
            msg('{} default_branch changed to {}'.format(summary, repo.default_branch))
            updates['default_branch'] = entry['default_branch'] = repo.default_branch
        if entry['homepage'] != repo.homepage:
            msg('{} homepage changed to {}'.format(summary, repo.homepage))
            updates['homepage'] = entry['homepage'] = repo.homepage

        if repo.language and (not entry['languages'] or entry['languages'] == -1):
            # We may add more languages than the single language returned by
            # the API, so we don't overwrite this field unless we have nothing.
            msg('added language for {}'.format(summary))
            updates['languages'] = entry['languages'] = [{'name': repo.language}]

        if repo.fork:
            fork = make_fork(repo.parent.full_name if repo.parent else None,
                             repo.source.full_name if repo.source else None)
            if fork != entry['fork']:
                msg('updated fork info for {}'.format(summary))
                updates['fork'] = entry['fork'] = fork
        elif entry['fork']:
            # We have something for fork, but are not supposed to.
            updates['fork'] = entry['fork'] = False

        if 'repo_created' not in entry['time']:
            entry['time']['repo_created'] = None
            updates['time.repo_created'] = None
        elif entry['time']['repo_created'] != canonicalize_timestamp(repo.created_at):
            entry['time']['repo_created']= canonicalize_timestamp(repo.created_at)
            updates['time.repo_created'] = entry['time']['repo_created']

        if 'repo_updated' not in entry['time']:
            entry['time']['repo_updated'] = None
            updates['time.repo_updated'] = None
        elif entry['time']['repo_updated'] != canonicalize_timestamp(repo.updated_at):
            entry['time']['repo_updated'] = canonicalize_timestamp(repo.updated_at)
            updates['time.repo_updated'] = entry['time']['repo_updated']

        if 'repo_pushed' not in entry['time']:
            entry['time']['repo_pushed'] = None
            updates['time.repo_pushed'] = None
        elif entry['time']['repo_pushed'] != canonicalize_timestamp(repo.pushed_at):
            entry['time']['repo_pushed'] = canonicalize_timestamp(repo.pushed_at)
            updates['time.repo_pushed'] = entry['time']['repo_pushed']

        if 'time.repo_created' in updates or 'time.repo_updated' in updates \
           or 'time.repo_pushed' in updates:
            entry['time']['data_refreshed'] = now_timestamp()
            updates['time.data_refreshed'] = entry['time']['data_refreshed']
            msg('updated time info for {}'.format(summary))

        if updates:
            self.db.update({'_id': entry['_id']}, {'$set': updates}, upsert=False)
        else:
            msg('{} has no changes'.format(summary))
        return entry


    def update_entry_from_html(self, entry, page, force=False):
        if page.status_code() in [404, 451]:
            # 404 = not found. 451 = unavailable for legal reasons.
            self.mark_entry_invisible(entry)
            return None
        updates = {}
        summary = e_summary(entry)
        if not entry['is_visible']:
            # Obviously it's visible if we got the HTML.
            msg('{} visibility set to True'.format(summary))
            updates['is_visible'] = entry['is_visible'] = True
        if entry['is_deleted']:
            # Obviously it's not deleted if we got the HTML.
            msg('{} deleted state set to False'.format(summary))
            updates['is_deleted'] = entry['is_deleted'] = False
        if page.owner() != entry['owner']:
            msg('{} owner changed to {}'.format(summary, page.owner()))
            updates['owner'] = entry['owner'] = page.owner()
        if page.name() != entry['name']:
            msg('{} repo name changed to {}'.format(summary, page.name()))
            updates['name'] = entry['name'] = page.name()
        if page.description() != entry['description']:
            msg('added description for {}'.format(summary))
            updates['description'] = entry['description'] = page.description()
        if page.homepage() != entry['homepage']:
            msg('added homepage for {}'.format(summary))
            updates['homepage'] = entry['homepage'] = page.homepage()
        if page.default_branch() != entry['default_branch']:
            msg('{} default_branch set to {}'.format(summary, page.default_branch()))
            updates['default_branch'] = entry['default_branch'] = page.default_branch()
        if page.files() != entry['files']:
            num = len(page.files()) if (page.files() and page.files() != -1) else 0
            msg('added {} files for {}'.format(num, summary))
            updates['files'] = entry['files'] = page.files()
        if page.num_commits() != entry['num_commits']:
            msg('{} num_commits set to {}'.format(summary, page.num_commits()))
            updates['num_commits'] = entry['num_commits'] = page.num_commits()
        if page.num_branches() != entry['num_branches']:
            msg('{} num_branches set to {}'.format(summary, page.num_branches()))
            updates['num_branches'] = entry['num_branches'] = page.num_branches()
        if page.num_releases() != entry['num_releases']:
            msg('{} num_releases set to {}'.format(summary, page.num_releases()))
            updates['num_releases'] = entry['num_releases'] = page.num_releases()
        if page.languages() != e_languages(entry):
            page_lang = page.languages()
            num_lang = len(page_lang) if page_lang else 0
            if num_lang > 0 and (not entry['languages'] or entry['languages'] == -1):
                # The HTML pages don't always have languages. Don't reset our
                # value if we don't actually pull something out of the HTML.
                msg('added {} languages for {}'.format(num_lang, summary))
                updates['languages'] = entry['languages'] = make_languages(page_lang)

        # Special case: contributors is unusual in that GitHub's value is
        # produced reactively.  If we don't get a value from HTML it doesn't
        # necessarily mean there is no value, so don't overwrite what we have.
        if page.num_contributors() and page.num_contributors() != entry['num_contributors']:
            msg('{} num_contributors set to {}'.format(summary, page.num_contributors()))
            updates['num_contributors'] = entry['num_contributors'] = page.num_contributors()

        if updates:
            updates['time.data_refreshed'] = now_timestamp()
            entry['time']['data_refreshed'] = updates['time.data_refreshed']
            self.db.update({'_id': entry['_id']},
                           {'$set': updates},
                           upsert=False)
        # Fork field is too complicated, and handled separately.
        if (not entry['fork'] and page.forked_from()):
            # We don't have it as a fork, but it is.
            # Don't know the root when we're getting the data from this source.
            # So, we can only update the parent.
            msg('updated fork info for {}'.format(summary))
            parent = page.forked_from() if page.forked_from() != True else None
            self.update_entry_fork_field(entry, True, parent, None)
        elif entry['fork'] and page.forked_from() == False:
            # We had it as a fork, but apparently it's not.
            msg('updated fork info for {}'.format(summary))
            self.update_entry_fork_field(entry, False, None, None)
        elif entry['fork'] and page.forked_from() != entry['fork']['parent']:
            # We have it as a fork, it is a fork, and we have parent info.
            msg('updated fork info for {}'.format(summary))
            self.update_entry_fork_field(entry, True, page.forked_from(), None)
        elif not updates:
            # This last case is weird but the logic is that if we get here, we
            # have no updates to fork or anything else.
            msg('{} has no changes'.format(summary))
        return entry


    def update_entry_field(self, entry, field, value, append=False):
        # If 'append' == True, the field is assumed to be a set of values, and
        # the 'value' is added if it's not already there.
        now = now_timestamp()
        if append:
            if value in entry[field]:
                return
            else:
                entry[field].append(value)
                self.db.update({'_id': entry['_id']},
                               {'$addToSet': {field: value},
                                '$set':      {'time.data_refreshed': now}})
        else:
            entry[field] = value
            self.db.update({'_id': entry['_id']},
                           {'$set': {field: value,
                                     'time.data_refreshed': now}})
        # Update this so that the object being held by the caller reflects
        # what was written to the database.
        entry['time']['data_refreshed'] = now


    def update_entry_fork_field(self, entry, is_fork, fork_parent, fork_root):
        if entry['fork'] and not is_fork:
            # We had it as a fork, but it's not.
            entry['fork'] = False
        elif entry['fork']:
            # It's a fork, and we had it as such. Maybe update our fields,
            # but don't overwrite something that we may already have had
            # gathered if the new value is None -- we may have gotten the
            # existing value a different, possibly more thorough way.
            if fork_parent:
                entry['fork']['parent'] = fork_parent
            if fork_root:
                entry['fork']['root'] = fork_root
        elif is_fork:
            # We don't have it as a fork, but it is.
            entry['fork'] = make_fork(fork_parent, fork_root)
        self.update_entry_field(entry, 'fork', entry['fork'])


    def update_entry_moved(self, entry, owner, name):
        (success, repo) = self.repo_via_api(owner, name)
        if not success:
            msg('*** Unable to access {}/{} -- skipping'.format(name, name))
            return None
        elif repo.owner.login != entry['owner'] or repo.name != entry['name']:
            return self.update_entry_from_github3(entry, repo)
        else:
            return entry


    def mark_entry_deleted(self, entry):
        msg('{} marked as deleted'.format(e_summary(entry)))
        self.update_entry_field(entry, 'is_deleted', True)
        self.update_entry_field(entry, 'is_visible', False)


    def mark_entry_invisible(self, entry):
        msg('{} marked as not visible'.format(e_summary(entry)))
        self.update_entry_field(entry, 'is_visible', False)


    def loop(self, iterator, body_function, selector, targets=None, start_id=0):
        msg('Initial GitHub API calls remaining: ', self.api_calls_left())
        count = 0
        failures = 0
        retry_after_max_failures = True
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
                            msg('*** GitHub API rate limit exceeded')
                            self.wait_for_reset()
                            retry = True
                        else:
                            # Occasionally get 403 even when not over the limit.
                            msg('*** GitHub code 403 for {}'.format(e_summary(entry)))
                            self.mark_entry_invisible(entry)
                            failures += 1
                    elif err.code == 451:
                        msg('*** GitHub code 451 (blocked) for {}'.format(e_summary(entry)))
                        self.mark_entry_invisible(entry)
                    else:
                        msg('*** GitHub API exception: {0}'.format(err))
                        failures += 1
                        # Might be a network or other transient error.
                        retry = True
                except Exception as err:
                    msg('*** Exception for {} -- skipping it -- {}'.format(
                        e_summary(entry), err))
                    # Something unexpected.  Don't retry this entry, but count
                    # this failure in case we're up against a roadblock.
                    failures += 1

            if failures >= self._max_failures:
                # Pause & continue once, in case of transient network issues.
                if retry_after_max_failures:
                    msg('*** Pausing because of too many consecutive failures')
                    sleep(120)
                    failures = 0
                    retry_after_max_failures = False
                else:
                    # We've already paused & restarted once.
                    msg('*** Stopping because of too many consecutive failures')
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
                results = self.db.find({'owner': owner, 'name': name}, {'_id': 1})
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
                    result = self.db.find_one({'owner': n_owner, 'name': n_name}, {'_id': 1})
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
        output = []
        count = 0
        total = 0
        start = time()
        msg('Constructing target list...')
        for item in targets:
            count += 1
            if isinstance(item, int) or item.isdigit():
                # We can only deal with numbers if we already have the id's
                # in our database.  Try it.
                entry = self.db.find_one({'_id': item})
                if entry:
                    output.append(entry)
                    total += 1
                    continue
                else:
                    msg('*** Cannot find id {} -- skipping'.format(item))
                    continue
            elif item.find('/') > 1:
                owner = item[:item.find('/')]
                name  = item[item.find('/') + 1:]
                # Do we already know about this in our database?  If so, just
                # return it.
                entry = self.db.find_one({'owner': owner, 'name': name})
                if entry:
                    output.append(entry)
                    total += 1
                    continue
            else:
                msg('*** Skipping uninterpretable "{}"'.format(item))
                continue

            # We don't know about it, so we have to get info from the API.
            (success, repo) = self.repo_via_api(owner, name)
            if not success:
                # We hit a problem. Skip this one.
                continue
            if not repo:
                # The API says it doesn't exist.  Could our name be an older
                # one?  Try one last-ditch effort.  Github seems to redirect
                # URLs to the new pages of projects that have been renamed,
                # so this works even if we have an old owner/name combination.
                url = self.github_url_exists(None, owner, name)
                if url:
                    (owner, name) = self.owner_name_from_github_url(url)
                    (success, repo) = self.repo_via_api(owner, name)
                if not success:
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
        c = self.db.count({'readme':  {'$nin': ['', -1, -2, None]},
                                      'is_visible': True})
        c = humanize.intcomma(c)
        msg('{} visible entries have README content.'.format(c))
        c = self.db.count({'readme': -2, 'is_visible': True})
        c = humanize.intcomma(c)
        msg('{} repos had bad/garbage README files.'.format(c))


    def summarize_visible(self, targets=None):
        c = self.db.count({'is_deleted': True})
        c = humanize.intcomma(c)
        msg('{} repos have been deleted in GitHub.'.format(c))
        c = self.db.count({'is_visible': False})
        c = humanize.intcomma(c)
        msg('{} repos are no longer visible in GitHub (maybe due to deletion).'.format(c))
        c = self.db.count({'is_visible': True})
        c = humanize.intcomma(c)
        msg('{} visible repos.'.format(c))


    def summarize_files(self, targets=None):
        c = self.db.count({'files': {'$nin': [-1, []]}, 'is_visible': True})
        c = humanize.intcomma(c)
        msg('{} visible repos contain lists of files.'.format(c))
        c = self.db.count({'files': -1, 'is_visible': True})
        c = humanize.intcomma(c)
        msg('{} visible repos are empty.'.format(c))
        c = self.db.count({'files': [], 'is_visible': True})
        c = humanize.intcomma(c)
        msg('{} visible entries still lack file lists.'.format(c))


    def summarize_types(self, targets=None):
        c = self.db.count({'content_type': {'$elemMatch': {'content': 'code'}},
                           'is_visible': True})
        c = humanize.intcomma(c)
        msg('{} visible repos believed to contain code.'.format(c))
        c = self.db.count({'content_type': {'$elemMatch': {'content': 'noncode'}},
                           'is_visible': True})
        c = humanize.intcomma(c)
        msg('{} visible repos believed not to contain code.'.format(c))
        c = self.db.count({'content_type': [], 'is_visible': True})
        c = humanize.intcomma(c)
        msg('{} visible entries still lack content_type.'.format(c))


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
        last_seen_id = self.last_seen_id()
        if last_seen_id:
            msg('Last seen GitHub id: {}.'.format(last_seen_id))
        else:
            msg('*** No entries ***')
            return
        total = humanize.intcomma(self.db.count())
        msg('{} total database entries.'.format(total))
        self.summarize_visible()
        self.summarize_files()
        self.summarize_types()
        self.summarize_readme_stats()
        # self.summarize_language_stats()


    def print_indexed_ids(self, targets={}, languages=None, start_id=0, **kwargs):
        '''Print the known repository identifiers in the database.'''
        msg('Printing known GitHub id numbers.')
        filter = {}
        if start_id > 0:
            msg("Skipping GitHub id's less than {}".format(start_id))
            filter['_id'] = {'$gte': start_id}
        if languages:
            msg('Limiting output to entries having languages', languages)
            filter.update(self.language_query(languages))
        if targets:
            msg('Total number of entries: {}'.format(humanize.intcomma(len(targets))))
        else:
            c = self.db.count(filter or targets)
            msg('Total number of entries: {}'.format(humanize.intcomma(c)))
        for entry in self.entry_list(filter or targets, fields=['_id'], start_id=start_id):
            msg(entry['_id'])


    def print_details(self, targets={}, languages=None, start_id=0, **kwargs):
        msg('Printing descriptions of indexed GitHub repositories.')
        width = len('NUM. CONTRIBUTORS:')
        filter = {}
        if start_id > 0:
            msg("Skipping GitHub id's less than {}".format(start_id))
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
            if entry['text_languages'] and entry['text_languages'] != -1:
                msg('TEXT LANGUAGES:'.ljust(width),
                    ', '.join(x + ' (' + name_for_language_code(x) + ')'
                              for x in entry['text_languages']))
            else:
                msg('TEXT LANGUAGES:')
            if entry['languages'] and entry['languages'] != -1:
                lang_list = pprint.pformat(e_languages(entry), indent=width+1,
                                           width=70, compact=True)
                lang_list = lang_list.replace("'", "")
                # Get rid of leading and trailing cruft
                if len(lang_list) > 70:
                    lang_list = lang_list[width+1:-1]
                else:
                    lang_list = lang_list[1:-1]
                msg('CODE LANGUAGES:'.ljust(width), lang_list)
            else:
                msg('CODE LANGUAGES:')
            if entry['fork'] and entry['fork']['parent']:
                fork_status = 'Yes, forked from ' + entry['fork']['parent']
            else:
                fork_status = 'No'
            msg('FORK:'.ljust(width), fork_status)
            msg('CONTENT TYPE:'.ljust(width), entry['content_type'])
            msg('DEFAULT BRANCH:'.ljust(width), entry['default_branch'])
            msg('NUM. COMMITS:'.ljust(width), entry['num_commits'])
            msg('NUM. BRANCHES:'.ljust(width), entry['num_branches'])
            msg('NUM. RELEASES:'.ljust(width), entry['num_releases'])
            if entry['num_contributors']:
                msg('NUM. CONTRIBUTORS:'.ljust(width), entry['num_contributors'])
            if entry['files'] and entry['files'] != -1:
                files_list = pprint.pformat(entry['files'], indent=width+1,
                                            width=(70), compact=True)
                # Get rid of leading and trailing cruft
                if len(files_list) > 70:
                    files_list = files_list[width+1:-1]
                else:
                    files_list = files_list[1:-1]
                msg('FILES:'.ljust(width), files_list)
            elif entry['files'] == -1:
                msg('FILES:'.ljust(width), '(empty repo)')
            else:
                msg('FILES:'.ljust(width))
            msg('VISIBLE:'.ljust(width), 'Yes' if entry['is_visible'] else 'No')
            msg('DELETED:'.ljust(width), 'Yes' if entry['is_deleted'] else 'No')
            msg('CREATED:'.ljust(width), timestamp_str(entry['time']['repo_created']))
            msg('UPDATED:'.ljust(width), timestamp_str(entry['time']['repo_updated']))
            msg('PUSHED:'.ljust(width), timestamp_str(entry['time']['repo_pushed']))
            msg('DATA REFRESHED:'.ljust(width), timestamp_str(entry['time']['data_refreshed']))
            msg('EXTERNAL HOMEPAGE:'.ljust(width), entry['homepage'])
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


    def get_languages(self, entry):
        # Using github3.py would cause 2 API calls per repo to get this info.
        # Here we do direct access to bring it to 1 api call.
        url = 'https://api.github.com/repos/{}/{}/languages'.format(entry['owner'],
                                                                    entry['name'])
        response = self.direct_api_call(url)
        if isinstance(response, int) and response >= 400:
            return -1
        elif response == None:
            return -1
        else:
            return json.loads(response)


    def get_readme(self, entry, prefer_http=False, api_only=False):

        def get_raw(url):
            r = timed_get(url, verify=False)
            if not r:
                # 408 is a standard http code for a time out.  May as well use
                # that here, as we need to return a number.
                return (408, None)
            code = r.status_code
            if code in [200, 203, 206]:
                # Got it, but watch out for bad files.  Threshold at 5 MB.
                if int(r.headers['content-length']) > 5242880:
                    return (code, -2)
                else:
                    return (code, r.text)
            elif code in [404, 451]:
                # 404 = doesn't exist.  451 = unavailable for legal reasons.
                return (code, -1)
            else:
                return (code, None)

        # First try to get it via direct HTTP access, to save on API calls.
        # If that fails and prefer_http != False, we resport to API calls.
        if not api_only:
            # Do we already have a list of files?  If so, look for the README.
            readme_file = None
            if isinstance(entry['files'], list):
                for f in entry['files']:
                    # GitHub preferentially shows README.md, and ranks README.txt
                    # below all others.
                    if f == 'README.md':
                        readme_file = f
                        break
                    elif f.startswith('README.') and f != 'README.txt':
                        readme_file = f
                        break
                    elif f == 'README':
                        readme_file = f
                        break
                    elif f == 'README.txt':
                        readme_file = f
                        break
            base_url = 'https://raw.githubusercontent.com/' + e_path(entry)
            branch = entry['default_branch'] if entry['default_branch'] else 'master'
            if readme_file:
                url = base_url + '/' + branch + '/' + readme_file
                (status, content) = get_raw(url)
                if status == 503:
                    # Weird behavior -- not sure if it's our system or theirs,
                    # but we sometimes get 503 and if you try it again, it works.
                    msg('*** Code 503 -- retrying {}'.format(url))
                    (status, content) = get_raw(url)
                if content != None:
                    return ('http', content)
                else:
                    msg('*** Code {} getting readme for {}'.format(r.status_code, url))
                    return ('http', None)
            elif entry['files'] and entry['files'] != -1:
                # We have a list of files in the repo, and there's no README.
                return ('http', -1)
            else:
                # We don't know repo's files, so we don't know the name of
                # the README file (if any).  We resort to trying different
                # alternatives one after the other.  The order is based on
                # the popularity of README file extensions a determined by
                # the following searches on GitHub (updated on 2016-05-09):
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

                exts = ['', '.md', '.txt', '.markdown', '.rdoc', '.rst']
                for ext in exts:
                    alternative = base_url + '/master/README' + ext
                    r = timed_get(alternative, verify=False)
                    if r and r.status_code == 200:
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


    def set_files_via_api(self, entry, force=False):
        branch   = 'master' if not entry['default_branch'] else entry['default_branch']
        base     = 'https://api.github.com/repos/' + e_path(entry)
        url      = base + '/git/trees/' + branch
        response = self.direct_api_call(url)
        if response == None:
            msg('*** No response for {} -- skipping'.format(e_summary(entry)))
        elif isinstance(response, int) and response in [403, 451]:
            # We hit the rate limit or a problem.  Bubble it up to loop().
            raise DirectAPIException('Getting files', response)
        elif isinstance(response, int) and response >= 400:
            # We got a code over 400, but not for things like API limits.
            # The repo might have been renamed, deleted, made private, or
            # it might have no files.  Try one more time using http.
            self.set_files_via_http(entry)
        else:
            results = json.loads(response)
            if 'message' in results and results['message'] == 'Not Found':
                msg('*** {} not found -- skipping'.format(e_summary(entry)))
                return
            elif 'tree' in results:
                files = []
                for thing in results['tree']:
                    if thing['type'] == 'blob':
                        files.append(thing['path'])
                    elif thing['type'] == 'tree':
                        files.append(thing['path'] + '/')
                    elif thing['type'] == 'commit':
                        # These are submodules.  Treat as subdirectories for our purposes.
                        files.append(thing['path'] + '/')
                    else:
                        import ipdb; ipdb.set_trace()
                if not files:
                    files = -1
                self.update_entry_field(entry, 'files', files)
                msg('added {} files for {}'.format(len(files), e_summary(entry)))
            else:
                # If we ever get here, something has changed in the GitHub
                # API or our assumptions, and we have to stop and fix it.
                import ipdb; ipdb.set_trace()


    def set_files_via_http(self, entry, force=False):
        page = GitHubHomePage()
        status = page.get_html(entry['owner'], entry['name'])
        if status >= 400 and status not in [404, 451]:
            raise UnexpectedResponseException('Getting HTML', status)
        elif page.is_problem():
            msg('*** GitHub problem for {} -- skipping'.format(e_summary(entry)))
        else:
            self.update_entry_from_html(entry, page, force)


    def set_files_via_svn(self, entry, force=False):
        # SVN is not bound by same API rate limits, but is much slower.
        if not entry['default_branch'] or entry['default_branch'] == 'master':
            branch = '/trunk'
        else:
            branch = '/branches/' + entry['default_branch']
        path = 'https://github.com/' + e_path(entry) + branch
        try:
            (code, output, err) = shell_cmd(['svn', '--non-interactive', 'ls', path])
        except Exception as ex:
            raise UnexpectedResponseException(ex)
        if code <= 0:
            if output:
                files = output.split('\n')
                files = [f for f in files if f]  # Remove empty strings.
                self.update_entry_field(entry, 'files', files)
                msg('added {} files for {}'.format(len(files), e_summary(entry)))
            else:
                msg('*** No result for {}'.format(e_summary(entry)))
        elif code == 1 and err.find('non-existent') > 1:
            msg('{} found empty'.format(e_summary(entry)))
            self.update_entry_field(entry, 'files', -1)
        elif code == 1 and err.find('authorization failed') > 1:
            msg('{} svn access requires authentication'.format(e_summary(entry)))
        else:
            raise UnexpectedResponseException('{}: {}'.format(
                e_summary(entry), str(err)), err)


    def add_languages(self, targets=None, force=False, prefer_http=False,
                      start_id=0, **kwargs):
        def body_function(entry):
            t1 = time()
            if entry['languages'] and entry['languages'] != -1 and not force:
                msg('*** {} has languages -- skipping'.format(e_summary(entry)))
                return
            if prefer_http:
                # The HTML scraper will get the languages as a by-product.
                page = GitHubHomePage()
                status = page.get_html(entry['owner'], entry['name'])
                if status >= 400 and status not in [404, 451]:
                    raise UnexpectedResponseException('Getting HTML', status)
                elif page.is_problem():
                    msg('*** problem with GitHub page for {}'.format(e_summary(entry)))
                langs = page.languages()
            else:
                # Use the API.  This is the best approach and gives a fuller
                # language list, but of course, costs API calls.
                # This will have a form like: {'Shell': 4051, 'Java': 1444052}
                # We turn it it into a straight list of names.
                lang_dict = self.get_languages(entry)
                langs = [k for k in lang_dict.keys()] if lang_dict else None
                langs = make_languages(langs)
            if langs:
                # We don't set languages to -1 if only using HTTP, as the web
                # pages don't always have a language list.  If we used the API,
                # our get_languages() will return -1 if appropriate.
                self.update_entry_field(entry, 'languages', langs)
                msg('{} languages added to {}'.format(len(langs), e_summary(entry)))

        msg('Gathering language data for repositories.')
        # Set up default selection criteria WHEN NOT USING 'targets'.
        selected_repos = {'languages': {"$eq" : []}, 'is_deleted': False,
                          'is_visible': {"$ne" : False}}
        if start_id > 0:
            msg("Skipping GitHub id's less than {}".format(start_id))
            selected_repos['_id'] = {'$gte': start_id}
        # And let's do it.
        self.loop(self.entry_list, body_function, selected_repos, targets, start_id)


    def add_readmes(self, targets=None, languages=None, prefer_http=False,
                    api_only=False, start_id=0, force=False, **kwargs):

        def no_readme(entry):
            msg('{} has no readme'.format(e_summary(entry)))
            self.update_entry_field(entry, 'readme', -1)

        def body_function(entry):
            if entry['is_visible'] == False:
                # See note at the end of the parent function (add_readmes).
                return
            t1 = time()
            (method, readme) = self.get_readme(entry, prefer_http, api_only)
            if isinstance(readme, int) and readme in [403, 451]:
                # We hit a problem.  Bubble it up to loop().
                raise DirectAPIException('Getting README', readme)
            elif isinstance(readme, int) and readme >= 400:
                # Got a code over 400, probably 404, but don't know why.
                # Repo might have been renamed, deleted, made private, or it
                # has no README file.  If we used the API, the API will have
                # account for repo moves already, so we're done.  If not
                # using the API, we have to check if the repo moved.
                if api_only:
                    no_readme(entry)
                    return
                # Use http to check if the repo still exists but has moved.
                (owner, name) = self.github_current_owner_name(entry)
                if not owner:
                    msg('*** {} not found in GitHub anymore'.format(e_summary(entry)))
                    self.mark_entry_invisible(entry)
                    return
                if owner != entry['owner'] or name != entry['name']:
                    if prefer_http:
                        msg('*** {} moved to {}/{} -- skipping b/c not using API'.format(
                            e_summary(entry), owner, name))
                        return
                    updated = self.update_entry_moved(entry, owner, name)
                    if updated:
                        (method, readme) = self.get_readme(updated, prefer_http, api_only)
            if readme != None and not isinstance(readme, int):
                t2 = time()
                msg('{} {} in {:.2f}s via {}'.format(
                    e_summary(entry), len(readme), (t2 - t1), method))
                self.update_entry_field(entry, 'readme', readme)
            elif isinstance(readme, int) and readme in [404, 451]:
                # If we have gotten this far and still have a 404, it's not there.
                no_readme(entry)
            elif readme == None or readme == -1:
                no_readme(entry)
            else:
                msg('Got {} for readme for {}'.format(readme, e_summary(entry)))

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
            msg("Skipping GitHub id's less than {}".format(start_id))
            selected_repos['_id'] = {'$gte': start_id}
        if force:
            # "Force" in this context means get readmes even if we previously
            # tried to get them, which is indicated by a -1 or -2 value.
            selected_repos['readme'] = {'$in': [None, -1, -2]}
        else:
            selected_repos['readme'] = None

        # And let's do it.
        self.loop(self.entry_list, body_function, selected_repos, targets, start_id)


    def create_entries(self, targets=None, api_only=False, prefer_http=False,
                       force=False, start_id=None, **kwargs):
        '''Create index by looking for new entries in GitHub, or adding entries
        whose id's or owner/name paths are given in the parameter 'targets'.
        If something is already in our database, this won't change it unless
        the flag 'force' is True.
        '''
        def body_function(thing):
            if isinstance(thing, github3.repos.repo.Repository):
                (is_new, entry) = self.add_entry_from_github3(thing, force)
                if is_new:
                    msg('{} added'.format(e_summary(entry)))
                return

            # The targets are not github3 objects but rather our database
            # entry dictionaries, which means they're in our database,
            # which means we only do something if we're forcing an update.
            if not force:
                msg('Skipping existing entry {}'.format(e_summary(thing)))
                return
            # We're forcing an update of existing database entries.
            entry = thing
            if prefer_http:
                page = GitHubHomePage()
                status = page.get_html(entry['owner'], entry['name'])
                if status in [404, 451]:
                    # Is no longer visible.
                    self.mark_entry_invisible(entry)
                elif page.is_problem():
                    msg('*** Problem with GitHub page for {}'.format(e_summary(entry)))
                elif status >= 400:
                    raise UnexpectedResponseException('Getting HTML', status)
                else:
                    self.update_entry_from_html(entry, page, force)
            else:
                # Use the API.
                (success, repo) = self.repo_via_api(entry['owner'], entry['name'])
                if not success:
                    # Hit a problem.
                    msg('*** Skipping existing entry {}'.format(e_summary(thing)))
                self.update_entry_from_github3(entry, repo)

        if targets or start_id:
            # We have a list of id's or repo paths.
            if force:
                # Using the force flag only makes sense if we expect that
                # the entries are in the database already => use entry_list()
                repo_iterator = self.entry_list
            else:
                # We're indexing but not overwriting. This won't do anything
                # to existing entries, so we assume that the targets are new
                # repo id's or paths (or a mix of known and unknown).
                repo_iterator = self.repo_list
            last_seen = None
        else:
            last_seen = self.last_seen_id()
            if last_seen:
                msg('Continuing from highest-known id {}'.format(last_seen))
            else:
                msg('No record of the last-seen repo.  Starting from the top.')
                last_seen = -1
            repo_iterator = self.github_iterator

        msg('Indexing entries.')
        # Set up selection criteria and start the loop
        selected_repos = {}
        if start_id > 0:
            msg("Skipping GitHub id's less than {}".format(start_id))
            selected_repos['_id'] = {'$gte': start_id}
        self.loop(repo_iterator, body_function, selected_repos, targets or last_seen, start_id)


    def infer_type(self, targets=None, api_only=False, prefer_http=False,
                   force=False, start_id=None, **kwargs):

        def guess_type(entry):
            # File tests are very basic and conservative.  They are
            # necessarily heuristic, so they could be wrong if someone does
            # something really unusual.
            if entry['files'] != -1:
                if any(is_code_file(f) for f in entry['files']):
                    return ('code', 'file names')
                if all(is_noncode_file(f) for f in entry['files']):
                    return ('noncode', 'file names')

            # The language-based heuristics are more iffy because GitHub's
            # language analyzer sometimes guesses wrong.
            if entry['languages'] != -1:
                if any(known_code_lang(lang['name']) for lang in entry['languages']):
                    return ('code', 'languages')
            return (None, None)

        def body_function(entry):
            if not force:
                summary = e_summary(entry)
                if entry['files'] == -1:
                    msg('*** {} empty -- skipping'.format(summary))
                    return
                if entry['content_type']:
                    msg('*** {} already has content_type -- skipping'.format(summary))
                    return
            if not entry['files']:
                # We don't have a files list yet. Get it.
                if api_only:      self.set_files_via_api(entry, force)
                elif prefer_http: self.set_files_via_http(entry, force)
                else:             self.set_files_via_svn(entry, force)
            (guessed, method) = guess_type(entry)
            if guessed:
                msg('{} guessed to contain {}'.format(e_summary(entry), guessed))
                self.update_entry_field(entry, 'content_type',
                                        make_content_type(guessed, method),
                                        append=True)
            else:
                msg('*** Unable to guess type of {}'.format(e_summary(entry)))

        # Main loop.
        msg('Inferring content_type for repositories.')
        selected_repos = {'is_deleted': False, 'is_visible': True}
        if start_id > 0:
            msg("Skipping GitHub id's less than {}".format(start_id))
            selected_repos['_id'] = {'$gte': start_id}
        self.loop(self.entry_list, body_function, selected_repos, targets, start_id)


    def add_files(self, targets=None, api_only=False, prefer_http=False,
                  force=False, start_id=None, **kwargs):

        def body_function(entry):
            if not force:
                info = e_summary(entry)
                if entry['files'] and entry['files'] != -1:
                    msg('*** {} has a files list -- skipping'.format(info))
                    return
                if entry['files'] == -1:
                    msg('*** {} believed to be empty -- skipping'.format(info))
                    return
                if entry['is_visible'] == False or entry['is_deleted'] == True:
                    msg('*** {} believed to be unavailable -- skipping'.format(info))
                    return
            if api_only:      self.set_files_via_api(entry, force)
            elif prefer_http: self.set_files_via_http(entry, force)
            else:             self.set_files_via_svn(entry, force)

        def iterator(targets, start_id):
            fields = ['files', 'default_branch', 'is_visible', 'is_deleted',
                      'owner', 'name', 'time', '_id', 'description',
                      'languages', 'fork', 'num_releases', 'num_branches',
                      'num_commits', 'num_contributors', 'homepage']
            return self.entry_list(targets, fields, start_id)

        # And let's do it.
        msg('Gathering lists of files.')
        if force:
            selected_repos = {'is_deleted': False, 'is_visible': True}
        else:
            # If we're not forcing re-getting the files, don't return results that
            # already have files data.
            selected_repos = {'is_deleted': False, 'is_visible': True, 'files': []}
        if start_id > 0:
            msg("Skipping GitHub id's less than {}".format(start_id))
            selected_repos['_id'] = {'$gte': start_id}
        # Note: the selector only has effect when targets are not explicit.
        self.loop(iterator, body_function, selected_repos, targets, start_id)


    def detect_text_lang(self, targets=None, force=False,
                         start_id=None, **kwargs):

        min_readme_length = 125
        min_description_length = 60

        def guess_markdown(text):
            if not isinstance(text, str):
                text = text.decode()
            return re.search('^#', text) or text.find('](')

        def guess_html(text):
            with warnings.catch_warnings():
                warnings.simplefilter('ignore')
                return BeautifulSoup(text, 'html.parser').find()

        def remove_html(text):
            with warnings.catch_warnings():
                warnings.simplefilter('ignore')
                return ''.join(BeautifulSoup(text, 'lxml').findAll(text=True))

        def body_function(entry):
            info = e_summary(entry)
            if not force:
                if entry['text_languages']:
                    msg('*** {} has text_language -- skipping'.format(info))
                    return
                current_langs = entry['text_languages']
            else:
                current_langs = []
            no_text = True
            # The best inferences come from long text.  The langid module
            # gets things wrong for short text with unusual terms (which is
            # typical for programmer-speak).  So the approach is: if we have
            # a README and it's reasonably long, we use that exclusively;
            # otherwise, we try the description but only if it's long enough.
            if entry['readme'] and entry['readme'] != -1:
                readme = entry['readme']
                if not isinstance(readme, str):
                    readme = readme.decode().encode('ascii', 'ignore')
                if guess_html(readme):
                    readme = remove_html(readme)
                elif guess_markdown(readme):
                    # Use Markdown formatter to generate HTML, then strip it.
                    readme = remove_html(markdown.markdown(readme))
                if len(readme) > min_readme_length:
                    lang, _ = langid.classify(readme)
                    current_langs.append(lang)
                    no_text = False
            elif entry['description'] and entry['description'] != -1:
                description = entry['description']
                if not isinstance(description, str):
                    description = description.decode().encode('ascii', 'ignore')
                if guess_html(description):
                    description = remove_html(description)
                if len(description) > min_description_length:
                    lang, _ = langid.classify(description)
                    current_langs.append(lang)
                    no_text = False
            if current_langs or force:
                # If we couldn't make an inference, we set it to -1.
                current_langs = list(set(current_langs)) or -1
                self.db.update({'_id': entry['_id']},
                               {'$set': {'text_languages': current_langs}})
                msg('{} languages inferred to be {}'.format(info, current_langs))
            elif no_text:
                self.db.update({'_id': entry['_id']}, {'$set': {'text_languages': -1}})
                msg('{} has no description or readme, or they are too short'.format(info))
            else:
                msg('could not infer language for {}'.format(info))

        def iterator(targets, start_id):
            fields = ['description', 'readme', 'text_languages', '_id',
                      'owner', 'name', 'is_deleted', 'is_visible']
            return self.entry_list(targets, fields, start_id)

        # And let's do it.
        msg('Examining text in description and readme fields.')
        selected_repos = {}
        if not force:
            selected_repos['text_languages'] = []
        if start_id > 0:
            msg("Skipping GitHub id's less than {}".format(start_id))
            selected_repos['_id'] = {'$gte': start_id}
        if selected_repos == {}:
            selected_repos = None
        # Note: the selector only has effect when targets are not explicit.
        self.loop(iterator, body_function, selected_repos, targets, start_id)
