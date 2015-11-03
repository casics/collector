#!/usr/bin/env python3.4

import pytest
import sys
import glob

sys.path.append('../')

from github_indexer import GitHubIndexer

class TestClass:
    def test_init(self, capsys):
        out, err = capsys.readouterr()
        self.obj = GitHubIndexer()
        assert self.obj._github

    def test_calls_left(self, capsys):
        out, err = capsys.readouterr()
        self.obj = GitHubIndexer()
        self.obj.api_calls_left()

    def test_get_iterator(self, capsys):
        out, err = capsys.readouterr()
        self.obj = GitHubIndexer()
        self.obj.get_iterator()
