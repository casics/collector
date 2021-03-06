#!/usr/bin/env python3.4
#
# @file    github_html.py
# @brief   HTML scraper code specialized for GitHub web pages.
# @author  Michael Hucka
#
# <!---------------------------------------------------------------------------
# Copyright (C) 2015 by the California Institute of Technology.
# This software is part of CASICS, the Comprehensive and Automated Software
# Inventory Creation System.  For more information, visit http://casics.org.
# ------------------------------------------------------------------------- -->

import os
import requests
import sys
import urllib
import html
from time import sleep

sys.path.append(os.path.join(os.path.dirname(__file__), "../common"))
sys.path.append(os.path.join(os.path.dirname(__file__), "../database"))
from utils import *


class NetworkAccessException(Exception):
    def __init__(self, message, code):
        message = str(message).encode('utf-8')
        super(NetworkAccessException, self).__init__(message)
        self.code = code


class PageParsingException(Exception):
    def __init__(self, message, code):
        message = str(message).encode('utf-8')
        super(PageParsingException, self).__init__(message)
        self.code = code


class GitHubHomePage():
    _max_retries = 3
    _retries_pause_sec = 0.5


    def __init__(self):
        self._owner            = None
        self._name             = None
        self._url              = None
        self._html             = None
        self._description      = None
        self._homepage         = None
        self._languages        = None
        self._forked_from      = None
        self._default_branch   = None
        self._files            = None
        self._is_problem       = None
        self._is_empty         = None
        self._status_code      = None
        self._num_commits      = None
        self._num_branches     = None
        self._num_releases     = None
        self._num_contributors = None
        self._licenses     = None


    def get_html(self, owner, name, refresh=False):
        if not owner or not name:
            raise ValueError('Invalid arguments')
        self._owner = owner
        self._name  = name
        try:
            url = self.url()
            for _ in range(0, self._max_retries):
                r = timed_get(url, verify=False)
                if r == None:
                    # Network timeout or other serious problem.
                    raise NetworkAccessException('Cannot access {}: {}'.format(url, err))
                elif r.status_code == 202:
                    # 202 = "accepted". We try again after a pause.
                    sleep(self._retries_pause_sec)
                    continue
                elif r.status_code == 301:
                    # Redirection.  Start from the top with new URL.
                    url = response.getheader('Location')
                    continue
                elif r.status_code != 200:
                    # Something's wrong. Stop trying, let caller deal with it.
                    break

                # Success.
                self._html = r.text

                # If we're forcing a refresh of the HTML, we're done now.
                if refresh:
                    break

                # Initialize the remaining internal values based on what we
                # got.  It's critical to run through all of them so that the
                # values are set based on the content on the GitHub page,
                # because it will reflect the current owner and name (in case
                # the owner and/or name have changed).  Note: no need to set
                # the self._foo attributes directly here; the functions do it.
                self.owner(force=True)
                self.name(force=True)
                self.url(force=True)
                if not self.is_problem():
                    self.is_empty()
                    self.description()
                    self.homepage()
                    self.languages()
                    self.forked_from()
                    self.default_branch()
                    self.files()
                    self.num_commits()
                    self.num_releases()
                    self.num_branches()
                    self.num_contributors()
                    self.licenses()
                break
            self._status_code = r.status_code
            return r.status_code
        except Exception as err:
            raise PageParsingException('Getting GitHub page HTML: {}'.format(err), err)


    def status_code(self):
        return self._status_code


    def full_name(self):
        return self._owner + '/' + self._name


    def url(self, force=False):
        if (self._url == None and self._owner and self._name) or force:
            self._url = 'https://github.com/' + self.full_name()
        return self._url


    def is_problem(self, force=False):
        # This is not fool-proof.  Someone could actually have this text
        # literally inside a README file.  The probability is low, but....
        if (self._is_problem == None and self._html) or force:
            text = '<h3>There is a problem with this repository on disk.</h3>'
            self._is_problem = self._html.find(text) > 0
        return self._is_problem


    def is_empty(self, force=False):
        # This is not fool-proof.  Someone could actually have this text
        # literally inside a README file.  The probability is low, but....
        if (self._is_empty == None and self._html) or force:
            text = '<h3>This repository is empty.</h3>'
            problem = self._html.find(text) > 0
            self._is_empty = self._html.find(text) > 0
        return self._is_empty


    def owner(self, force=False):
        if (self._owner == None and self._html) or force:
            # Two forms of the title start sequences:
            #   <title>GitHub - owner/name
            #   <title>owner/name
            marker = '<title>GitHub - '
            start = self._html.find(marker)
            if start < 0:
                marker = '<title>'
                start = self._html.find(marker)
            if start > 0:
                endtitle = self._html.find('</title>', start)
                endpoint = self._html.find('/', start, endtitle)
                if endpoint > 0:
                    self._owner = self._html[start + len(marker) : endpoint].strip()
        return self._owner


    def name(self, force=False):
        if (self._name == None and self._html) or force:
            # Two forms of the title start sequences:
            #   <title>GitHub - owner/name
            #   <title>owner/name
            marker = '<title>GitHub '
            start = self._html.find(marker, 0)
            if start < 0:
                marker = '<title>'
                start = self._html.find(marker, 0)
            endtitle = self._html.find('</title>')
            start = self._html.find('/', start, endtitle)
            if start > 0:
                # Skip the slash.
                start += 1
                endpoint = self._html.find(':', start, endtitle)
                if endpoint > 0:
                    self._name = self._html[start : endpoint]
                else:
                    endpoint = self._html.find(' · GitHub', start, endtitle)
                    if endpoint >= 0:
                        self._name = self._html[start : endpoint]
                    else:
                        self._name = self._html[start : endtitle]

                    # if endpoint > 0:
                    #     self._name = self._html[start : endpoint]
                    # else:
                    #     endpoint = self._html.find(' - GitHub', start, endbound)
                    #     if endpoint > 0:
                    #         self._name = self._html[start : endpoint]
                    #     else:
                    #         endpoint = self._html.find(':', start, endbound)
                    #         self._name = self._html[start : endbound]
            else:
                raise PageParsingException('Cannot parse HTML repo name for {}'.format(
                    self.full_name()), None)
        return self._name


    def description(self, force=False):
        if self.is_problem():
            self._description = None
        elif (self._description == None and self._html) or force:
            marker = 'itemprop="about">'
            marker_len = 17
            start = self._html.find(marker)
            if start > 0:
                endpoint = self._html.find('</span>', start)
                self._description = self._html[start + marker_len : endpoint].strip()
            else:
                self._description = ''
        return self._description


    def homepage(self, force=False):
        if self.is_problem():
            self._homepage = None
        elif (self._homepage == None and self._html) or force:
            marker = 'itemprop="url"><a href="'
            marker_len = 24
            start = self._html.find(marker)
            if start > 0:
                endpoint = self._html.find('"', start + marker_len)
                self._homepage = self._html[start + marker_len : endpoint].strip()
            else:
                self._homepage = ''
        return self._homepage


    def default_branch(self, force=False):
        if self.is_problem():
            self._default_branch = None
        elif (self._default_branch == None and self._html) or force:
            # It seems that even if a repo is empty, the "recent commits" link
            # exists.  It has the following form:
            #   <link href="https://github.com/OWNER/NAME/commits/BRANCH.atom" ...
            # We look only for the string '/commits' from the top, because
            # the full link sometimes uses a different owner or repo name
            # than the actual repo owner+name.  (Maybe as a result of the
            # repo being renamed at some point?)
            marker = '.atom" rel="alternate"'
            endpoint = self._html.find(marker)
            if endpoint > 0:
                start = self._html.rfind('commits/', 0, endpoint) + 8
                self._default_branch = html.unescape(self._html[start : endpoint])
        return self._default_branch


    def languages(self, force=False):
        if self.is_problem():
            self._languages = None
        elif (self._languages == None and self._html) or force:
            marker = 'class="lang">'
            marker_len = 13
            self._languages = []
            start = self._html.find(marker)
            while start > 0:
                endpoint = self._html.find('<', start)
                self._languages.append(self._html[start + marker_len : endpoint])
                start = self._html.find(marker, endpoint)
            # Minor cleanup.
            if 'Other' in self._languages:
                self._languages.remove('Other')
        return self._languages


    def forked_from(self, force=False):
        if self.is_problem():
            self._forked_from = None
        elif (self._forked_from == None and self._html) or force:
            spanstart = self._html.find('<span class="fork-flag">')
            if spanstart > 0:
                marker = '<span class="text">forked from <a href="'
                marker_len = 40
                start = self._html.find(marker, spanstart)
                if start > 0:
                    endpoint = self._html.find('"', start + marker_len)
                    self._forked_from = self._html[start + marker_len + 1 : endpoint]
                else:
                    # Found the section marker, but couldn't parse the text for
                    # some reason.  Just return a Boolean value that it is a fork.
                    self._forked_from = True
            else:
                self._forked_from = False
        return self._forked_from


    def files(self, force=False):
        # Values returned
        #   None if we don't have html
        #   -1 if the repo is empty
        #   otherwise, a list of files
        if self.is_problem():
            self._files = None
            return self._files
        elif self.is_empty():
            self._files = -1
            return self._files
        elif (self._files != None or not self._html) and not force:
            return self._files

        startmarker = '"file-wrap"'
        start = self._html.find(startmarker)
        if start < 0:
            return self._files

        nextstart = self._html.find('<table', start + len(startmarker))
        base      = '/' + self._owner + '/' + self._name
        filepat   = base + '/blob/'
        dirpat    = base + '/tree/'
        found_file   = self._html.find(filepat, nextstart)
        found_dir    = self._html.find(dirpat, nextstart)
        if found_file < 0 and found_dir < 0:
            self._is_empty = True
            self._files = -1
            return self._files
        nextstart   = min([v for v in [found_file, found_dir] if v > -1])
        section     = self._html[nextstart : self._html.find('</table', nextstart)]
        url_name    = html_encode(self._default_branch)
        filepat     = filepat + url_name + '/'
        filepat_len = len(filepat)
        dirpat      = dirpat + url_name + '/'
        dirpat_len  = len(dirpat)
        # Now look inside the section were files are found.
        found_file  = section.find(filepat)
        found_dir   = section.find(dirpat)
        if found_file < 0 and found_dir < 0:
            raise PageParsingException('Problem parsing files list for {}'.format(
                self.full_name()), None)
        nextstart = min([v for v in [found_file, found_dir] if v > -1])
        self._files = []
        while nextstart >= 0:
            endpoint = section.find('"', nextstart)
            whole = section[nextstart : endpoint]
            if whole.find(filepat) > -1:
                self._files.append(whole[filepat_len :])
            elif whole.find(dirpat) > -1:
                path = whole[dirpat_len :]
                if path.find('/') > 0:
                    # It's a submodule.  Some of the other methods we use
                    # don't distinguish submodules from directories in the
                    # file lists, so we have to follow suit here for
                    # consistency: treat it like a directory.
                    endname = path[path.rfind('/') + 1:]
                    self._files.append(endname + '/')
                else:
                    self._files.append(path + '/')
            else:
                # Something is inconsistent. Bail for now.
                self._files = None
                break
            section = section[endpoint :]
            found_file   = section.find(filepat)
            found_dir    = section.find(dirpat)
            if found_file < 0 and found_dir < 0:
                break
            else:
                nextstart = min([v for v in [found_file, found_dir] if v > -1])
        return self._files


    def num_commits(self, force=False):
        if self.is_problem():
            self._num_commits = None
        elif (self._num_commits == None and self._html) or force:
            spanstart = self._html.find('<ul class="numbers-summary">')
            if spanstart < 0:
                # If there are no commits (which can happen if it's empty),
                # we legitimately can set this to 0.  Note: don't rely on only
                # testing for empty repo, because there might have been past
                # commits and then later the repo could have been emptied.
                self._num_commits = 0
                return self._num_commits
            marker = '<span class="num text-emphasized">'
            marker_len = 34
            start = self._html.find(marker, spanstart)
            if start > 0:
                endpoint = self._html.find('</span>', start + marker_len)
                self._num_commits = self._html[start + len(marker) : endpoint]
                self._num_commits = self._num_commits.strip()
                self._num_commits = int(self._num_commits.replace(',', ''))
        return self._num_commits


    def num_branches(self, force=False):
        if self.is_problem():
            self._num_branches = None
        elif (self._num_branches == None and self._html) or force:
            spanstart = self._html.find('<ul class="numbers-summary">')
            spanstart = self._html.find('/branches', spanstart)
            if spanstart < 0:
                # If there are no branches (which can happen if it's empty),
                # we legitimately can set this to 0.  Note: don't rely on only
                # testing for empty repo, because there might have been past
                # commits and then later the repo could have been emptied.
                self._num_branches = 0
                return self._num_branches
            marker = '<span class="num text-emphasized">'
            marker_len = 34
            start = self._html.find(marker, spanstart)
            if start > 0:
                endpoint = self._html.find('</span>', start + marker_len)
                self._num_branches = self._html[start + len(marker) : endpoint]
                self._num_branches = self._num_branches.strip()
                self._num_branches = int(self._num_branches.replace(',', ''))
        return self._num_branches


    def num_releases(self, force=False):
        if self.is_problem():
            self._num_releases = None
        elif (self._num_releases == None and self._html) or force:
            spanstart = self._html.find('<ul class="numbers-summary">')
            spanstart = self._html.find('/releases', spanstart)
            if spanstart < 0:
                # If there is no release info (which can happen if the repo
                # is empty), semantically, that's the same as 0 releases.
                self._num_releases = 0
                return self._num_releases
            marker = '<span class="num text-emphasized">'
            marker_len = 34
            start = self._html.find(marker, spanstart)
            if start > 0:
                endpoint = self._html.find('</span>', start + marker_len)
                self._num_releases = self._html[start + len(marker) : endpoint]
                self._num_releases = self._num_releases.strip()
                self._num_releases = int(self._num_releases.replace(',', ''))
        return self._num_releases


    def num_contributors(self, force=False, retry=False):
        if self.is_problem():
            self._num_contributors = None
        elif (self._num_contributors == None and self._html) or force:
            spanstart = self._html.find('<ul class="numbers-summary">')
            spanstart = self._html.find('/contributors', spanstart)
            if spanstart < 0:
                # If there is no release info (which can happen if the repo
                # is empty), semantically, that's the same as 0 contributors.
                self._num_contributors = 0
                return self._num_contributors
            marker = '<span class="num text-emphasized">'
            marker_len = 34
            start = self._html.find(marker, spanstart)
            if start > 0:
                endpoint = self._html.find('</span>', start + marker_len)
                self._num_contributors = self._html[start + len(marker) : endpoint]
                if (len(self._num_contributors) == 0 or
                    self._num_contributors.find('Fetching') > 0) and not retry:
                    # FIXME: Github doesn't load everything on the page right
                    # away.  There seems to be a reactive aspect to the list
                    # of contributors, and sometimes it comes up empty when
                    # you get the HTML.  Unfortunately, simply re-fetching the
                    # page does not produce an updated value.  Giving up for
                    # now and leaving it unknown when this happens.
                    self._num_contributors = None
                else:
                    self._num_contributors = self._num_contributors.strip()
                    self._num_contributors = int(self._num_contributors.replace(',', ''))
        return self._num_contributors


    def licenses(self, force=False, retry=False):
        if self.is_problem():
            self._licenses = None
        elif (self._licenses == None and self._html) or force:
            self._licenses = []
            spanstart = self._html.find('<ul class="numbers-summary">')
            spanstart = self._html.find('octicon-law', spanstart)
            if spanstart < 0:
                return self._licenses
            marker = '</svg>'
            marker_len = 6
            start = self._html.find(marker, spanstart)
            if start > 0:
                endpoint = self._html.find('</a>', start + marker_len)
                licenses = self._html[start + len(marker) : endpoint]
                # FIXME is there ever more than one?
                licenses = licenses.strip()
                if len(licenses) > 0:
                    self._licenses = [licenses]
        return self._licenses



# Utilities
# .............................................................................

def html_encode(s):
    htmlCodes = (
        ('&', '&amp;'),
        ("'", '&#39;'),
        ('"', '&quot;'),
        ('>', '&gt;'),
        ('<', '&lt;'),
        ('+', '%2B'),
        (',', '%2C'),
    )
    for code in htmlCodes:
        s = s.replace(code[0], code[1])
    return s




# # If the repo has been renamed, we may have gotten here using
# # an name.  First try to get the current name.
# #
# # Note: there seem to be 2 forms of the HTML for the file list:
# # 1.  <div class="file-wrap">
# #       <a href="/owner/name/tree/sha..."
# #
# # 2.  <include-fragment class="file-wrap" src="/owner/name/file-list/master">

# if html[start - 11 : start] == '<div class=':
#     url_start = html.find('<a href="/', start)
#     url_end   = html.find('"', url_start + 10)
#     url       = html[url_start + 10 : url_end]
#     owner     = url[: url.find('/')]
#     slash     = len(owner) + 1
#     name      = url[slash : url.find('/', slash)]
# elif html[start - 24 : start] == '<include-fragment class=':
#     line_end  = html.find('>', start)
#     url_start = html.find('src="/', start, line_end)
#     url       = html[url_start + 6 : line_end]
#     owner     = url[: url.find('/')]
#     slash     = len(owner) + 1
#     name      = url[slash : url.find('/', slash)]


        # if nextstart >= 0:
        #     branch_start = nextstart + len(base) + 6
        #     branch_end = html.find('/', branch_start)
        #     branch = html[branch_start : branch_end]
        #     if branch != self._default_branch:
        #         msg('*** adjusting default branch for {}'.
        # else:
        #     return self._files
