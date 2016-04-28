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

def summarize(entry):
    return '{}/{} (#{})'.format(entry['owner'], entry['name'], entry['_id'])


def msg_notfound(thing):
    msg('*** "{}" not found ***'.format(thing))


def msg_bad(thing):
    if isinstance(thing, int) or (isinstance(thing, str) and thing.isdigit()):
        msg('*** id #{} not found ***'.format(thing))
    elif isinstance(thing, str):
        msg('*** {} not an id or an "owner/name" string ***'.format(thing))
    else:
        msg('*** unrecognize type of thing: "{}" ***'.format(thing))


# Utilities for working with our MongoDB contents.
# .............................................................................


# Main class.
# .............................................................................

class GitHubIndexer():
    _max_failures   = 10

    def __init__(self, user_login=None, db=None):
        self.db = db
        cfg = Config()
        section = 'GitHub'
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
        try:
            # response = self.direct_api_call('/rate_limit')
            # if response and response != 404:
            #     content = json.loads(response)
            #     return content['rate']['remaining']
            # Backup approach if we fail:
            rate_limit = self.github().rate_limit()
            return rate_limit['resources']['core']['remaining']
        except Exception as err:
            msg('Got exception asking about rate limit: {}'.format(err))
            # Treat it as no time left, which in the rest of the code should
            # cause a pause and a retry later.
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
            try:
                return content.decode('utf-8')
            except:
                # Content is either binary or garbled.  We can't deal with it,
                # so we return an empty string.
                msg('Undecodable content received for {}'.format(url))
                return ''
        else:
            msg('Response status {} for {}'.format(response.status, url))
            return response.status


    def github_url(self, entry):
        return 'http://github.com/' + entry['owner'] + '/' + entry['name']


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


    def get_home_page(self, entry):
        r = requests.get(self.github_url(entry))
        return (r.status_code, r.text)


    def loop(self, body_function, selector, targets=None):
        msg('Initial GitHub API calls remaining: ', self.api_calls_left())
        count = 0
        failures = 0
        start = time()
        # By default, only consider those entries without language info.
        for entry in self.entry_list(targets or selector):
            if self.api_calls_left() < 1:
                self.wait_for_reset()
                failures = 0
            retry = True
            while retry and failures < self._max_failures:
                # Don't retry unless the problem may be transient.
                retry = False
                try:
                    body_function(entry)
                    failures = 0
                except github3.GitHubError as err:
                    # Occasionally an error even when not over the rate limit.
                    if err.code == 403:
                        calls_left = self.api_calls_left()
                        if calls_left < 1:
                            msg('GitHub API rate limit exceeded')
                            self.wait_for_reset()
                            loop_count = 0
                            calls_left = self.api_calls_left()
                            retry = True
                        else:
                            msg('GitHub code 403 for {}'.format(summarize(entry)))
                            self.update_field(entry, 'is_visible', False)
                            retry = False
                            failures += 1
                    elif err.code == 451:
                        msg('GitHub code 451 (blocked) for {}'.format(summarize(entry)))
                        self.update_field(entry, 'is_visible', False)
                        retry = False
                    else:
                        msg('GitHub API exception: {0}'.format(err))
                        failures += 1
                        # Might be a network or other transient error.
                        retry = True
                except EnumerationValueError as err:
                    # Encountered a language string that's not in our enum.
                    # Print a message and go on.
                    msg('Encountered unrecognized language: {}'.format(err))
                    retry = False
                except Exception as err:
                    msg('Exception for {}: {}'.format(summarize(entry), err))
                    failures += 1
                    # Might be a network or other transient error.
                    retry = True

            if failures >= self._max_failures:
                msg('Stopping because of too many consecutive failures')
                break
            count += 1
            if count % 100 == 0:
                msg('{} [{:2f}]'.format(count, time() - start))
                start = time()

        msg('')
        msg('Done.')


    def update_entry(self, entry):
        entry['refreshed'] = now_timestamp()
        self.db.replace_one({'_id' : entry['_id']}, entry)


    def update_field(self, entry, field, value):
        entry[field] = value
        now = now_timestamp()
        entry['refreshed'] = now
        self.db.update({'_id': entry['_id']},
                       {'$set': {field: value, 'refreshed': now}})


    def ensure_id(self, item):
        if isinstance(item, int):
            if self.db.find_one({'_id': item}):
                return item
            else:
                msg_notfound(item)
                return None
        elif isinstance(item, str):
            if item.isdigit():
                return int(item)
            elif item.find('/') > 1:
                owner = item[:item.find('/')]
                name  = item[item.find('/') + 1:]
                result = self.db.find_one({'owner': owner, 'name': name})
                if result:
                    return int(result['_id'])
                else:
                    msg_notfound(item)
                    return None
        msg_bad(item)
        return None


    def entry_list(self, targets=None, only_return=None):
        if only_return:
            only_return = {x:1 for x in only_return}
            if '_id' not in only_return:
                # By default, Mongodb will return _id even if not requested.
                # Skip it unless the caller explicitly wants it.
                only_return.append({'_id': 0})
        if isinstance(targets, dict):
            if only_return:
                return self.db.find(targets, only_return)
            else:
                return self.db.find(targets)
        elif isinstance(targets, list):
            id_list = [self.ensure_id(x) for x in targets]
            if only_return:
                return filter(None, [self.db.find_one({'_id': id}, only_return)
                                     for id in id_list])
            else:
                return filter(None, [self.db.find_one({'_id': id})
                                     for id in id_list])
        else:
            # Empty targets, so match against all entries.
            if only_return:
                return self.db.find({}, only_return)
            else:
                return self.db.find()


    def language_names(self, entry):
        if not entry['languages']:
            return []
        elif entry['languages'] == -1:
            return -1
        else:
            return [lang['name'] for lang in entry['languages']]


    def language_list(self, langs):
        return [{'name': lang} for lang in langs]


    def language_query(self, lang_filter):
        filter = None
        if isinstance(lang_filter, str):
            filter = {'languages.name': lang_filter}
        elif isinstance(lang_filter, list):
            filter = {'languages.name':  {"$in" : lang_filter}}
        return filter


    def summarize_language_stats(self, targets=None):
        msg('Gathering programming language statistics ...')
        totals = {}                     # Pairs of language:count.
        seen = 0                        # Total number of entries seen.
        for entry in self.entry_list(targets
                                     or {'languages':  {"$ne" : [], "$ne" : -1}},
                                     only_return=['languages']):
            seen += 1
            if seen % 100000 == 0:
                print(seen, '...', end='', flush=True)
            if not entry['languages']:
                continue
            for lang in self.language_names(entry):
                totals[lang] = totals[lang] + 1 if lang in totals else 1
        seen = humanize.intcomma(seen)
        msg('Language usage counts for {} entries:'.format())
        for name, count in sorted(totals.items(), key=operator.itemgetter(1),
                                 reverse=True):
            msg('  {0:<24s}: {1}'.format(name, count))


    def summarize_readme_stats(self, targets=None):
        have_readmes = self.db.find({'readme':  {'$ne' : '', '$ne' : -1}}).count()
        have_readmes = humanize.intcomma(have_readmes)
        msg('Database has {} entries with README files.'.format(have_readmes))


    def list_deleted(self, targets=None):
        msg("The following entries have 'is_deleted' = True:")
        for entry in self.entry_list(targets or {'is_deleted': True},
                                     only_return={'_id', 'owner', 'name'}):
            msg(summarize(entry))


    def print_summary(self):
        '''Print an overall summary of the database.'''
        total = humanize.intcomma(self.db.count())
        msg('Database has {} total GitHub entries.'.format(total))
        last_seen = self.db.find_one({'$query':{}, '$orderby':{'_id':-1}})
        if last_seen:
            msg('Last seen GitHub id: {}.'.format(last_seen['_id']))
        else:
            msg('*** no entries ***')
            return
        self.summarize_readme_stats()
        self.summarize_language_stats()


    def print_indexed_ids(self, targets={}, lang_filter=None):
        '''Print the known repository identifiers in the database.'''
        filter = None
        if lang_filter:
            msg('Limiting output to entries having languages', lang_filter)
            filter = self.language_query(lang_filter)
        if targets:
            msg('Total number of entries: {}'.format(humanize.intcomma(len(targets))))
        elif lang_filter:
            results = self.db.find(filter or targets)
            msg('Total number of entries: {}'.format(humanize.intcomma(results.count())))
        else:
            msg('Total number of entries: {}'.format(humanize.intcomma(self.db.count())))
        for entry in self.entry_list(filter or targets, only_return=['_id']):
            msg(entry['_id'])


    def print_details(self, targets={}, lang_filter=None):
        width = len('DESCRIPTION:')
        filter = None
        if lang_filter:
            msg('Limiting output to entries having languages', lang_filter)
            filter = self.language_query(lang_filter)
        for entry in self.entry_list(filter or targets):
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
            if entry['languages']:
                msg('LANGUAGES:'.ljust(width), ', '.join(self.language_names(entry)))
            else:
                msg('LANGUAGES:')
            msg('CREATED:'.ljust(width), timestamp_str(entry['created']))
            if entry['is_fork'] and entry['fork_of']:
                fork_status = 'Yes, forked from ' + entry['fork_of']
            elif entry['is_fork']:
                fork_status = 'Yes'
            else:
                fork_status = 'No'
            msg('IS FORK:'.ljust(width), fork_status)
            msg('IS DELETED:'.ljust(width), 'Yes' if entry['is_deleted'] else 'No')
            msg('REFRESHED:'.ljust(width), timestamp_str(entry['refreshed']))
            if entry['readme'] and entry['readme'] != -1:
                msg('README:')
                msg(entry['readme'])
        msg('='*70)


    def print_index(self, targets={}, lang_filter=None):
        '''Print the database contents.'''
        filter = None
        if lang_filter:
            msg('Limiting output to entries having languages', lang_filter)
            filter = self.language_query(lang_filter)
        fields = ['owner', 'name', '_id', 'languages']
        for entry in self.entry_list(filter or targets, only_return=fields):
            langs = self.language_names(entry)
            msg('{}/{} (#{}), langs: {}'.format(
                entry['owner'], entry['name'], entry['_id'],
                ' '.join(langs) if langs else ''))


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


    def get_languages(self, entry):
        # First try to get it by scraping the HTTP web page for the project.
        # This saves an API call.
        (code, html) = self.get_home_page(entry)
        if code == 404:
            return (False, 'http', [], None)
        if html:
            languages = self.extract_languages_from_html(html)
            if languages:
                # Succeeded in getting language info by scraping.
                # While we're here, pull out some other data too:
                fork_info = self.extract_fork_from_html(html)
                return (True, 'http', languages, fork_info)

        # Failed to get it by scraping.  Try the GitHub API.
        # Using github3.py would cause 2 API calls per repo to get this info.
        # Here we do direct access to bring it to 1 api call.
        url = 'https://api.github.com/repos/{}/{}/languages'.format(entry['owner'],
                                                                    entry['name'])
        response = self.direct_api_call(url)
        if response == 404 or response == 403:
            return (False, 'api', [], None)
        elif response == None:
            return (True, 'api', [], None)
        else:
            return (True, 'api', json.loads(response), None)


    def get_readme(self, entry, http_only=False):
        # First try to get it via direct HTTP access, to save on API calls.
        base_url = 'https://raw.githubusercontent.com/' + entry['owner'] + '/' + entry['name']
        readme_1 = base_url + '/master/README.md'
        readme_2 = base_url + '/master/README.rst'
        readme_3 = base_url + '/master/README'
        readme_4 = base_url + '/master/README.txt'
        readme_5 = base_url + '/master/README.rdoc'
        readme_6 = base_url + '/master/README.markdown'
        readme_7 = base_url + '/master/README.textile'
        for alternative in [readme_1, readme_2, readme_3, readme_4, readme_5,
                            readme_6, readme_7]:
            r = requests.get(alternative)
            if r.status_code == 200:
                return ('http', r.text)
            elif r.status_code < 300:
                import ipdb; ipdb.set_trace()
            sleep(0.1) # Don't hit their servers too hard.

        if http_only:
            return ('http', None)

        # Resort to GitHub API call.
        # Get the "preferred" readme file for a repository, as described in
        # https://developer.github.com/v3/repos/contents/
        # Using github3.py would need 2 api calls per repo to get this info.
        # Here we do direct access to bring it to 1 api call.
        url = 'https://api.github.com/repos/{}/{}/readme'.format(
            entry['owner'], entry['name'])
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


    def add_languages(self, targets=None):
        def body_function(entry):
            t1 = time()
            (found, method, langs, fork) = self.get_languages(entry)
            if not found:
                # Repo was renamed, deleted, made private, or there's
                # no home page.  See if our records need to be updated.
                repo = self.github().repository(entry['owner'], entry['name'])
                if not repo:
                    # Nope, it's gone.
                    self.update_field(entry, 'is_deleted', True)
                    self.update_field(entry, 'is_visible', False)
                    msg('*** {} no longer exists'.format(summarize(entry)))
                    found = True
                elif entry['owner'] != repo.owner.login \
                     or entry['name'] != repo.name:
                    # The owner or name changed.
                    self.update_field(entry, 'owner', repo.owner.login)
                    self.update_field(entry, 'name', repo.name)
                    # Try again with the info returned by github3.
                    (found, method, langs, fork) = self.get_languages(entry)
                else:
                    msg('*** {} appears to be private'.format(summarize(entry)))
                    self.update_field(entry, 'is_visible', False)
                    return
            if not found:
                # 2nd attempt failed. Bail.
                msg('*** Failed to get info about {}'.format(summarize(entry)))
                return
            if not entry['is_deleted']:
                t2 = time()
                fork_info = ', a fork of {},'.format(fork) if fork else ''
                lang_info = len(langs) if langs else 'no languages'
                msg('{}{} in {:.2f}s via {}, {}'.format(
                    summarize(entry), fork_info, (t2 - t1), method, lang_info))
                if langs:
                    self.update_field(entry, 'languages', self.language_list(langs))
                else:
                    self.update_field(entry, 'languages', -1)
                if fork:
                    # Don't change copy_of if we couldn't read it while
                    # looking for languages, because we might have stored
                    # it previously using a different data source.
                    self.update_field(entry, 'fork_of', fork)

        # Set up selection criteria and start the loop
        selected_repos = {'languages': {"$eq" : []}, 'is_deleted': False,
                          'is_visible': {"$ne" : False}}
        self.loop(body_function, selected_repos, targets)


    def add_readmes(self, targets=None, http_only=False):
        def body_function(entry):
            t1 = time()
            (method, readme) = self.get_readme(entry, http_only)
            if isinstance(readme, int) and readme >= 400 and not http_only:
                # Repo was renamed, deleted, made private, or there's
                # no home page.  See if our records need to be updated.
                repo = self.github().repository(entry['owner'], entry['name'])
                if not repo:
                    # Nope, it's gone.
                    self.update_field(entry, 'is_deleted', True)
                    self.update_field(entry, 'is_visible', False)
                    msg('*** {} no longer exists'.format(summarize(entry)))
                elif entry['owner'] != repo.owner.login \
                     or entry['name'] != repo.name:
                    # The owner or name changed.
                    self.update_field(entry, 'owner', repo.owner.login)
                    self.update_field(entry, 'name', repo.name)
                    # Try again with the info returned by github3.
                    (method, readme) = self.get_readme(entry, http_only)
                else:
                    # No readme available.  Drop to the -1 case below.
                    pass

            if readme and not isinstance(readme, int):
                t2 = time()
                msg('{} {} in {:.2f}s via {}'.format(
                    summarize(entry), len(readme), (t2 - t1), method))
                self.update_field(entry, 'readme', readme)
            else:
                # If GitHub doesn't return a README file, we need to
                # record something to indicate that we already tried.
                # The something can't be '', or None, or 0.  We use -1.
                msg('No readme for {}'.format(summarize(entry)))
                self.update_field(entry, 'readme', -1)

        # Set up selection criteria and start the loop
        selected_repos = {'readme': {"$eq" : ''}, 'is_deleted': False,
                          'is_visible': {"$ne" : False}}
        self.loop(body_function, selected_repos, targets)






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
    #         repo_iterator = self.get_repo_iterator(last_seen)
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
