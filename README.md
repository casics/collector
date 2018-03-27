CASICS Collector
================

<img width="100px" align="right" src=".graphics/casics-logo-small.svg">

The CASICS Collector is a repository crawler and scraper that extracts data about projects and stores it in the [CASICS](http://casics.org) (Comprehensive and Automated Software Inventory Creation System) database.

*Authors*:      [Michael Hucka](http://github.com/mhucka)<br>
*Repository*:   [https://github.com/casics/collector](https://github.com/casics/collector)<br>
*License*:      Unless otherwise noted, this content is licensed under the [GPLv3](https://www.gnu.org/licenses/gpl-3.0.en.html) license.

☀ Introduction
-----------------------------

[CASICS](http://casics.org) (the Comprehensive and Automated Software Inventory Creation System) is a project to create a proof of concept that uses machine learning techniques to analyze source code in software repositories and classify the repositories.  As part of this project, we need to obtain data about software project repositories in GitHub and (eventually) other hosting systems such as SourceForge.  This module (the CASICS Collector) is designed to gather that data.

The Collector module queries hosting services via APIs (and for some purposes, also scrapes project web pages) and writes the data to the CASICS Database.  It is designed as a separate module so that one or more instances can be started and run simultaneously.  It does **not** download copies of repository files; that task is left to a separate module, the [CASICS Downloader](https://github.com/casics/downloader).

The CASICS Collector is written in Python.

⁇ Getting help and support
--------------------------

If you find an issue, please submit it in [the GitHub issue tracker](https://github.com/casics/collector/issues) for this repository.

♬ Contributing &mdash; info for developers
------------------------------------------

A lot remains to be done on CASICS in many areas.  We would be happy to receive your help and participation if you are interested.  Please feel free to contact the developers either via GitHub or the mailing list [casics-team@googlegroups.com](casics-team@googlegroups.com).

Everyone is asked to read and respect the [code of conduct](CONDUCT.md) when participating in this project.

❤️ Acknowledgments
------------------

This material is based upon work supported by the [National Science Foundation](https://nsf.gov) under Grant Number 1533792 (Principal Investigator: Michael Hucka).  Any opinions, findings, and conclusions or recommendations expressed in this material are those of the author(s) and do not necessarily reflect the views of the National Science Foundation.

<br>
<div align="center">
  <a href="https://www.nsf.gov">
    <img width="105" height="105" src=".graphics/NSF.svg">
  </a>
  &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;
  &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;
  <a href="https://www.caltech.edu">
    <img width="100" height="100" src=".graphics/caltech-round.svg">
  </a>
</div>
