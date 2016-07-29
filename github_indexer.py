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
import pprint
import urllib
import github3
import humanize
import socket
from base64 import b64encode
from datetime import datetime
from subprocess import PIPE, DEVNULL, Popen
from threading import Timer
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


def shell_cmd(args, max_time=5):
    # 'max_time' is in sec.
    # Based in part on http://stackoverflow.com/a/10768774/743730

    def kill_proc(proc, timeout):
        timeout['value'] = True
        proc.kill()

    proc = Popen(args, stdout=PIPE, stderr=PIPE, stdin=PIPE, preexec_fn=os.setsid)
    timeout = {'value': False}
    timer = Timer(max_time, kill_proc, [proc, timeout])
    timer.start()
    stdout, stderr = proc.communicate()
    timer.cancel()
    return proc.returncode, stdout.decode("utf-8"), stderr.decode("utf-8")


# Based on http://stackoverflow.com/a/14491059/743730
def flatten(the_list):
    for item in the_list:
        try:
            yield from flatten(item)
        except TypeError:
            yield item

# Code to normalize language names.
# List came from our first database approach to cataloging github repos.
lang_names = {
    # Lang name: is it for code?}
    "ABAP"                           : True,
    "ABC"                            : True,
    "AGS Script"                     : True,
    "AMPL"                           : True,
    "ANTLR"                          : True,
    "API Blueprint"                  : True,
    "APL"                            : True,
    "ASP"                            : True,
    "ATLAS"                          : True,
    "ATS"                            : True,
    "ActionScript"                   : True,
    "Ada"                            : True,
    "Agda"                           : True,
    "AgilentVEE"                     : True,
    "Algol"                          : True,
    "Alice"                          : True,
    "Alloy"                          : True,
    "Angelscript"                    : True,
    "Ant Build System"               : True,
    "ApacheConf"                     : True,
    "Apex"                           : True,
    "AppleScript"                    : True,
    "Arc"                            : True,
    "Arduino"                        : True,
    "AsciiDoc"                       : False,
    "AspectJ"                        : True,
    "Assembly"                       : True,
    "Augeas"                         : True,
    "AutoHotkey"                     : True,
    "AutoIt"                         : True,
    "AutoLISP"                       : True,
    "Automator"                      : True,
    "Avenue"                         : True,
    "Awk"                            : True,
    "BASIC"                          : True,
    "BCPL"                           : True,
    "BETA"                           : True,
    "Bash"                           : True,
    "Batchfile"                      : True,
    "BeanShell"                      : True,
    "Befunge"                        : True,
    "Bison"                          : True,
    "BitBake"                        : True,
    "BlitzBasic"                     : True,
    "BlitzMax"                       : True,
    "Bluespec"                       : True,
    "Boo"                            : True,
    "BourneShell"                    : True,
    "Brainfuck"                      : True,
    "Brightscript"                   : True,
    "Bro"                            : True,
    "C"                              : True,
    "C#"                             : True,
    "C++"                            : True,
    "C-ObjDump"                      : True,
    "C2hs Haskell"                   : True,
    "CFML"                           : True,
    "CHILL"                          : True,
    "CIL"                            : True,
    "CLIPS"                          : True,
    "CLU"                            : True,
    "CMake"                          : True,
    "COBOL"                          : True,
    "COMAL"                          : True,
    "COmega"                         : True,
    "CPL"                            : True,
    "CSS"                            : True,
    "CShell"                         : True,
    "Caml"                           : True,
    "Cap&#39;n Proto"                : True,
    "Cap'n Proto"                    : True,
    "CartoCSS"                       : True,
    "Ceylon"                         : True,
    "Ch"                             : True,
    "Chapel"                         : True,
    "Charity"                        : True,
    "Chef"                           : True,
    "ChucK"                          : True,
    "Cirru"                          : True,
    "Clarion"                        : True,
    "Clean"                          : True,
    "Clipper"                        : True,
    "Clojure"                        : True,
    "Cobra"                          : True,
    "CoffeeScript"                   : True,
    "ColdFusion CFC"                 : True,
    "ColdFusion"                     : True,
    "Common Lisp"                    : True,
    "Component Pascal"               : True,
    "Cool"                           : True,
    "Coq"                            : True,
    "Cpp-ObjDump"                    : True,
    "Creole"                         : True,
    "Crystal"                        : True,
    "Cucumber"                       : True,
    "Cuda"                           : True,
    "Curl"                           : True,
    "Cycript"                        : True,
    "Cython"                         : True,
    "D"                              : True,
    "D-ObjDump"                      : True,
    "DCL"                            : True,
    "DCPU-16 ASM"                    : True,
    "DCPU16ASM"                      : True,
    "DIGITAL Command Language"       : True,
    "DM"                             : True,
    "DNS Zone"                       : True,
    "DOT"                            : True,
    "DTrace"                         : True,
    "Darcs Patch"                    : True,
    "Dart"                           : True,
    "Delphi"                         : True,
    "DiBOL"                          : True,
    "Diff"                           : True,
    "Dockerfile"                     : True,
    "Dogescript"                     : True,
    "Dylan"                          : True,
    "E"                              : True,
    "ECL"                            : True,
    "ECLiPSe"                        : True,
    "ECMAScript"                     : True,
    "EGL"                            : True,
    "EPL"                            : True,
    "EXEC"                           : True,
    "Eagle"                          : True,
    "Ecere Projects"                 : True,
    "Ecl"                            : True,
    "Eiffel"                         : True,
    "Elixir"                         : True,
    "Elm"                            : True,
    "Emacs Lisp"                     : True,
    "EmberScript"                    : True,
    "Erlang"                         : True,
    "Escher"                         : True,
    "Etoys"                          : True,
    "Euclid"                         : True,
    "Euphoria"                       : True,
    "F#"                             : True,
    "FLUX"                           : True,
    "FORTRAN"                        : True,
    "Factor"                         : True,
    "Falcon"                         : True,
    "Fancy"                          : True,
    "Fantom"                         : True,
    "Felix"                          : True,
    "Filterscript"                   : True,
    "Formatted"                      : False,
    "Forth"                          : True,
    "Fortress"                       : True,
    "FourthDimension 4D"             : True,
    "FreeMarker"                     : True,
    "Frege"                          : True,
    "G-code"                         : True,
    "GAMS"                           : True,
    "GAP"                            : True,
    "GAS"                            : True,
    "GDScript"                       : True,
    "GLSL"                           : True,
    "GNU Octave"                     : True,
    "Gambas"                         : True,
    "Game Maker Language"            : True,
    "Genshi"                         : True,
    "Gentoo Ebuild"                  : True,
    "Gentoo Eclass"                  : True,
    "Gettext Catalog"                : True,
    "Glyph"                          : True,
    "Gnuplot"                        : True,
    "Go"                             : True,
    "Golo"                           : True,
    "GoogleAppsScript"               : True,
    "Gosu"                           : True,
    "Grace"                          : True,
    "Gradle"                         : True,
    "Grammatical Framework"          : False,
    "Graph Modeling Language"        : True,
    "Graphviz DOT"                   : True,
    "Groff"                          : False,
    "Groovy Server Pages"            : True,
    "Groovy"                         : True,
    "HCL"                            : True,
    "HPL"                            : True,
    "HTML"                           : False,
    "HTML+Django"                    : True,
    "HTML+EEX"                       : True,
    "HTML+ERB"                       : True,
    "HTML+PHP"                       : True,
    "HTTP"                           : True,
    "Hack"                           : True,
    "Haml"                           : True,
    "Handlebars"                     : True,
    "Harbour"                        : True,
    "Haskell"                        : True,
    "Haxe"                           : True,
    "Heron"                          : True,
    "Hy"                             : True,
    "HyPhy"                          : True,
    "HyperTalk"                      : True,
    "IDL"                            : True,
    "IGOR Pro"                       : True,
    "INI"                            : True,
    "INTERCAL"                       : True,
    "IRC log"                        : True,
    "Icon"                           : True,
    "Idris"                          : True,
    "Inform 7"                       : True,
    "Inform"                         : True,
    "Informix 4GL"                   : True,
    "Inno Setup"                     : True,
    "Io"                             : True,
    "Ioke"                           : True,
    "Isabelle ROOT"                  : True,
    "Isabelle"                       : True,
    "J"                              : True,
    "J#"                             : True,
    "JADE"                           : True,
    "JFlex"                          : True,
    "JSON"                           : False,
    "JSON5"                          : False,
    "JSONLD"                         : False,
    "JSONiq"                         : False,
    "JSX"                            : True,
    "JScript"                        : True,
    "JScript.NET"                    : True,
    "Jade"                           : True,
    "Jasmin"                         : True,
    "Java Server Pages"              : True,
    "Java"                           : True,
    "JavaFXScript"                   : True,
    "JavaScript"                     : True,
    "Julia"                          : True,
    "Jupyter Notebook"               : False,
    "KRL"                            : True,
    "KiCad"                          : True,
    "Kit"                            : True,
    "KornShell"                      : True,
    "Kotlin"                         : True,
    "LFE"                            : True,
    "LLVM"                           : True,
    "LOLCODE"                        : True,
    "LPC"                            : True,
    "LSL"                            : True,
    "LaTeX"                          : False,
    "LabVIEW"                        : True,
    "LadderLogic"                    : True,
    "Lasso"                          : True,
    "Latte"                          : True,
    "Lean"                           : True,
    "Less"                           : True,
    "Lex"                            : True,
    "LilyPond"                       : True,
    "Limbo"                          : True,
    "Lingo"                          : True,
    "Linker Script"                  : True,
    "Linux Kernel Module"            : True,
    "Liquid"                         : True,
    "Lisp"                           : True,
    "Literate Agda"                  : True,
    "Literate CoffeeScript"          : True,
    "Literate Haskell"               : True,
    "LiveScript"                     : True,
    "Logo"                           : True,
    "Logos"                          : True,
    "Logtalk"                        : True,
    "LookML"                         : True,
    "LoomScript"                     : True,
    "LotusScript"                    : True,
    "Lua"                            : True,
    "Lucid"                          : True,
    "Lustre"                         : True,
    "M"                              : True,
    "M4"                             : True,
    "MAD"                            : True,
    "MANTIS"                         : True,
    "MAXScript"                      : True,
    "MDL"                            : True,
    "MEL"                            : True,
    "ML"                             : True,
    "MOO"                            : True,
    "MSDOSBatch"                     : True,
    "MTML"                           : True,
    "MUF"                            : True,
    "MUMPS"                          : True,
    "Magic"                          : True,
    "Magik"                          : True,
    "Makefile"                       : True,
    "Mako"                           : True,
    "Malbolge"                       : True,
    "Maple"                          : True,
    "Markdown"                       : False,
    "Mask"                           : True,
    "Mathematica"                    : True,
    "Matlab"                         : True,
    "Maven POM"                      : True,
    "Max"                            : True,
    "MaxMSP"                         : True,
    "MediaWiki"                      : True,
    "Mercury"                        : True,
    "Metal"                          : True,
    "MiniD"                          : True,
    "Mirah"                          : True,
    "Miva"                           : True,
    "Modelica"                       : True,
    "Modula-2"                       : True,
    "Modula-3"                       : True,
    "Module Management System"       : True,
    "Monkey"                         : True,
    "Moocode"                        : True,
    "MoonScript"                     : True,
    "Moto"                           : True,
    "Myghty"                         : True,
    "NATURAL"                        : True,
    "NCL"                            : True,
    "NL"                             : True,
    "NQC"                            : True,
    "NSIS"                           : True,
    "NXTG"                           : True,
    "Nemerle"                        : True,
    "NetLinx"                        : True,
    "NetLinx+ERB"                    : True,
    "NetLogo"                        : True,
    "NewLisp"                        : True,
    "Nginx"                          : True,
    "Nimrod"                         : True,
    "Ninja"                          : True,
    "Nit"                            : True,
    "Nix"                            : True,
    "Nu"                             : True,
    "NumPy"                          : True,
    "OCaml"                          : True,
    "OPL"                            : True,
    "Oberon"                         : True,
    "ObjDump"                        : True,
    "Object Rexx"                    : True,
    "Objective-C"                    : True,
    "Objective-C++"                  : True,
    "Objective-J"                    : True,
    "Occam"                          : True,
    "Omgrofl"                        : True,
    "Opa"                            : True,
    "Opal"                           : True,
    "OpenCL"                         : True,
    "OpenEdge ABL"                   : True,
    "OpenEdgeABL"                    : True,
    "OpenSCAD"                       : True,
    "Org"                            : True,
    "Ox"                             : True,
    "Oxygene"                        : True,
    "Oz"                             : True,
    "PAWN"                           : True,
    "PHP"                            : True,
    "PILOT"                          : True,
    "PLI"                            : True,
    "PLSQL"                          : True,
    "PLpgSQL"                        : True,
    "POVRay"                         : True,
    "Pan"                            : True,
    "Papyrus"                        : True,
    "Paradox"                        : True,
    "Parrot Assembly"                : True,
    "Parrot Internal Representation" : True,
    "Parrot"                         : True,
    "Pascal"                         : True,
    "Perl"                           : True,
    "Perl6"                          : True,
    "PicoLisp"                       : True,
    "PigLatin"                       : True,
    "Pike"                           : True,
    "Pliant"                         : True,
    "Pod"                            : False,
    "PogoScript"                     : True,
    "PostScript"                     : False,
    "PowerBasic"                     : True,
    "PowerScript"                    : True,
    "PowerShell"                     : True,
    "Processing"                     : True,
    "Prolog"                         : True,
    "Propeller Spin"                 : True,
    "Protocol Buffer"                : True,
    "Public Key"                     : False,
    "Puppet"                         : True,
    "Pure Data"                      : True,
    "PureBasic"                      : True,
    "PureData"                       : True,
    "PureScript"                     : True,
    "Python traceback"               : True,
    "Python"                         : True,
    "Q"                              : True,
    "QML"                            : True,
    "QMake"                          : True,
    "R"                              : True,
    "RAML"                           : True,
    "RDoc"                           : False,
    "REALbasic"                      : True,
    "REALbasicDuplicate"             : True,
    "REBOL"                          : True,
    "REXX"                           : True,
    "RHTML"                          : True,
    "RMarkdown"                      : True,
    "RPGOS400"                       : True,
    "Racket"                         : True,
    "Ragel in Ruby Host"             : True,
    "Ratfor"                         : True,
    "Raw token data"                 : True,
    "Rebol"                          : True,
    "Red"                            : True,
    "Redcode"                        : True,
    "RenderScript"                   : True,
    "Revolution"                     : True,
    "RobotFramework"                 : True,
    "Rouge"                          : True,
    "Ruby"                           : True,
    "Rust"                           : True,
    "S"                              : True,
    "SAS"                            : True,
    "SCSS"                           : True,
    "SIGNAL"                         : True,
    "SMT"                            : True,
    "SPARK"                          : True,
    "SPARQL"                         : True,
    "SPLUS"                          : True,
    "SPSS"                           : True,
    "SQF"                            : True,
    "SQL"                            : True,
    "SQLPL"                          : True,
    "SQR"                            : True,
    "STON"                           : True,
    "SVG"                            : False,
    "Sage"                           : True,
    "SaltStack"                      : True,
    "Sass"                           : True,
    "Sather"                         : True,
    "Scala"                          : True,
    "Scaml"                          : True,
    "Scheme"                         : True,
    "Scilab"                         : True,
    "Scratch"                        : True,
    "Seed7"                          : True,
    "Self"                           : True,
    "Shell"                          : True,
    "ShellSession"                   : True,
    "Shen"                           : True,
    "Simula"                         : True,
    "Simulink"                       : True,
    "Slash"                          : True,
    "Slate"                          : True,
    "Slim"                           : True,
    "Smali"                          : True,
    "Smalltalk"                      : True,
    "Smarty"                         : True,
    "SourcePawn"                     : True,
    "Squeak"                         : True,
    "Squirrel"                       : True,
    "Standard ML"                    : True,
    "Stata"                          : True,
    "Stylus"                         : True,
    "Suneido"                        : True,
    "SuperCollider"                  : True,
    "Swift"                          : True,
    "SystemVerilog"                  : True,
    "TACL"                           : True,
    "TOM"                            : True,
    "TOML"                           : True,
    "TXL"                            : True,
    "Tcl"                            : True,
    "Tcsh"                           : True,
    "TeX"                            : False,
    "Tea"                            : True,
    "Text"                           : True,
    "Textile"                        : False,
    "Thrift"                         : True,
    "Transact-SQL"                   : True,
    "Turing"                         : True,
    "Turtle"                         : True,
    "Twig"                           : True,
    "TypeScript"                     : True,
    "Unified Parallel C"             : True,
    "Unity3D Asset"                  : True,
    "UnrealScript"                   : True,
    "VBScript"                       : True,
    "VCL"                            : True,
    "VHDL"                           : True,
    "Vala"                           : True,
    "Verilog"                        : True,
    "VimL"                           : True,
    "Visual Basic"                   : True,
    "Visual Basic.NET"               : True,
    "Visual Fortran"                 : True,
    "Visual FoxPro"                  : True,
    "Volt"                           : True,
    "Vue"                            : True,
    "Web Ontology Language"          : False,
    "WebDNA"                         : True,
    "WebIDL"                         : True,
    "Whitespace"                     : True,
    "Wolfram Language"               : True,
    "X10"                            : True,
    "XBase++"                        : True,
    "XC"                             : True,
    "XML"                            : True,
    "XPL"                            : True,
    "XPages"                         : True,
    "XProc"                          : True,
    "XQuery"                         : True,
    "XS"                             : True,
    "XSLT"                           : True,
    "Xen"                            : True,
    "Xojo"                           : True,
    "Xtend"                          : True,
    "YAML"                           : True,
    "Yacc"                           : True,
    "Yorick"                         : True,
    "Zephir"                         : True,
    "Zimpl"                          : True,
    "Zshell"                         : True,
    "bc"                             : True,
    "cT"                             : True,
    "cg"                             : True,
    "dBase"                          : True,
    "desktop"                        : True,
    "eC"                             : True,
    "edn"                            : True,
    "fish"                           : True,
    "haXe"                           : True,
    "ksh"                            : True,
    "mupad"                          : True,
    "nesC"                           : True,
    "ooc"                            : True,
    "reStructuredText"               : False,
    "sed"                            : True,
    "thinBasic"                      : True,
    "wisp"                           : True,
    "xBase"                          : True,
    "Other"                          : False,
}
lang_names_nocase = {k.lower():v for k,v in lang_names.items()}

def known_code_lang(lang):
    lang = lang.lower()
    if lang in lang_names_nocase:
        return lang_names_nocase[lang]
    else:
        return False


code_files = [
    'build.xml',
    'capfile',
    'gemfile',
    'makefile',
    'pom.xml',
    'rakefile',
]

code_file_extensions = [
    'am',
    'ac',
    'c',
    'class',
    'cpp',
    'cs',
    'h',
    'in',
    'java',
    'js',
    'jsp',
    'lua',
    'm',
    'mk',
    'msvc',
    'pl',
    'py',
    'r',
    'rb',
    'sh',
    'swift',
    'vb',
    'vcxproj',
    'xcodeproj/',
]

def is_code_file(name):
    return name.lower() in code_files

def has_code_extension(name):
    return name.split(".")[-1].lower() in code_file_extensions


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


class UnexpectedResponseException(Exception):
    def __init__(self, message, code):
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


    def get_github_iterator(self, last_seen=None, start_id=None):
        try:
            if last_seen or start_id:
                since = last_seen or start_id
                return self.github().iter_all_repos(since=since)
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

        # Turns out we can't trust the value returned by GitHub: if it's 0,
        # the repo is often *not* actually empty.  So all we can do is record
        # when we find it's not 0.
        if repo.size > 0 and entry['content_type'] == '':
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
            content_type = 'nonempty' if repo.size > 0 else ''
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


    def summarize_files(self, targets=None):
        with_files = self.db.find({'files': {'$ne': []}}).count()
        with_files = humanize.intcomma(with_files)
        msg('{} entries contain lists of files.'.format(with_files))


    def summarize_types(self, targets=None):
        no_content_type = self.db.find({'content_type': ''}).count()
        no_content_type = humanize.intcomma(no_content_type)
        msg('{} entries without content_type.'.format(no_content_type))
        are_empty = self.db.find({'content_type': 'empty'}).count()
        are_empty = humanize.intcomma(are_empty)
        msg('{} repos believed to be empty.'.format(are_empty))
        are_nonempty = self.db.find({'content_type': 'nonempty'}).count()
        are_nonempty = humanize.intcomma(are_nonempty)
        msg('{} repos believed to be nonempty.'.format(are_nonempty))
        are_code = self.db.find({'content_type': 'code'}).count()
        are_code = humanize.intcomma(are_code)
        msg('{} repos believed to contain code.'.format(are_code))
        are_noncode = self.db.find({'content_type': 'noncode'}).count()
        are_noncode = humanize.intcomma(are_noncode)
        msg('{} repos believed not to contain code.'.format(are_noncode))


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
        self.summarize_files()
        self.summarize_types()
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
            msg('CONTENT TYPE:'.ljust(width), entry['content_type'])
            if entry['files']:
                files_list = pprint.pformat(entry['files'], indent=width,
                                            width=(70), compact=True)
                # Get rid of leading and trailing cruft
                files_list = files_list[width+1:-1]
            msg('FILES:'.ljust(width), files_list)
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


    def extract_files_from_html(self, html, entry):
        empty_marker = '<h3>This repository is empty.</h3>'
        owner = entry['owner']
        name = entry['name']
        if not html:
            return (False, [], owner, name)
        elif html.find(empty_marker) > 0:
            return (True, [], owner, name)
        else:
            startmarker = '"file-wrap"'
            startpoint = html.find(startmarker)
            if startpoint < 0:
                return (False, None, owner, name)

            # If the repo has been renamed, we may have gotten here using an
            # name.  First try to get the current name.
            #
            # Note: there seem to be 2 forms of the HTML for the file list:
            # 1.  <div class="file-wrap">
            #       <a href="/owner/name/tree/sha..."
            #
            # 2.  <include-fragment class="file-wrap" src="/owner/name/file-list/master">

            if html[startpoint - 11 : startpoint] == '<div class=':
                url_start = html.find('<a href="/', startpoint)
                url_end   = html.find('"', url_start + 10)
                url       = html[url_start + 10 : url_end]
                owner     = url[: url.find('/')]
                slash     = len(owner) + 1
                name      = url[slash : url.find('/', slash)]
            elif html[startpoint - 24 : startpoint] == '<include-fragment class=':
                line_end  = html.find('>', startpoint)
                url_start = html.find('src="/', startpoint, line_end)
                url       = html[url_start + 6 : line_end]
                owner     = url[: url.find('/')]
                slash     = len(owner) + 1
                name      = url[slash : url.find('/', slash)]

            nextstart = html.find('<table', startpoint + len(startmarker))
            base      = '/' + owner + '/' + name
            filepat   = base + '/blob/'
            dirpat    = base + '/tree/'
            found_file   = html.find(filepat, nextstart)
            found_dir    = html.find(dirpat, nextstart)
            if found_file < 0 and found_dir < 0:
                return (True, None, owner, name)
            nextstart = min([v for v in [found_file, found_dir] if v > -1])
            if nextstart >= 0:
                branch_start = nextstart + len(base) + 6
                branch_end = html.find('/', branch_start)
                branch = html[branch_start : branch_end]
            else:
                return (False, None, owner, name)
            section   = html[nextstart : html.find('</table', nextstart)]
            # Update patterns now that we know the branch
            filepat       = filepat + branch + '/'
            filepat_len   = len(filepat)
            dirpat        = dirpat + branch + '/'
            dirpat_len    = len(dirpat)
            # Now look inside the section were files are found.
            found_file   = section.find(filepat)
            found_dir    = section.find(dirpat)
            nextstart = min([v for v in [found_file, found_dir] if v > -1])
            files = []
            while nextstart >= 0:
                endpoint = section.find('"', nextstart)
                whole = section[nextstart : endpoint]
                if whole.find(filepat) > -1:
                    files.append(whole[filepat_len :])
                elif whole.find(dirpat) > -1:
                    path = whole[dirpat_len :]
                    if path.find('/') > 0:
                        # It's a submodule.  Some of the other methods we use
                        # don't distinguish submodules from directories in the
                        # file lists, so we have to follow suit here for
                        # consistency: treat it like a directory.
                        endname = path[path.rfind('/') + 1:]
                        files.append(endname + '/')
                    else:
                        files.append(path + '/')
                else:
                    # Something is inconsistent. Bail for now.
                    return (False, None, owner, name)
                section = section[endpoint :]
                found_file   = section.find(filepat)
                found_dir    = section.find(dirpat)
                if found_file < 0 and found_dir < 0:
                    break
                else:
                    nextstart = min([v for v in [found_file, found_dir] if v > -1])
            return (False, files, owner, name)


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


    def extract_empty_from_html(self, html):
        if not html:
            return False
        else:
            # This is not fool-proof.  Someone could actually have this text
            # literally inside a README file.  The probability is low, but....
            text = '<h3>This repository is empty.</h3>'
            return html.find(text) > 0


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
        if not api_only:
            # Do we already have a list of files?  If so, look for the README.
            readme_file = None
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
                r = requests.get(base_url + '/' + branch + '/' + readme_file)
                if r.status_code == 200:
                    # Watch out for bad files.  Threshold at 5 MB.
                    if int(r.headers['content-length']) > 5242880:
                        return ('http', '')
                    else:
                        return ('http', r.text)
            elif entry['files']:
                # We have a list of files in the repo, and there's no README.
                return ('http', None)
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


    def check_empty(self, entry, prefer_http=False, api_only=False, html=None):
        # Returns tuple (method, tested, empty), where 'tested' is True if we
        # actually found the repo (as opposed to meeting an error of some
        # kind) and 'empty' is True if empty, False if not.

        if not api_only:
            if not html:
                (code, html) = self.get_home_page(entry)
                if code in [404, 451]:
                    # 404 = doesn't exist.  451 = unavailable for legal reasons.
                    # Don't bother try to get it via API either.
                    return ('http', False, True)
            # Do *not* turn this next condition into "else html".
            if html:
                return ('http', True, self.extract_empty_from_html(html))

        # If we get here and we're only doing HTTP, then we're done.
        if prefer_http:
            return ('http', False, True)

        # Resort to GitHub API call.
        # This approach is from http://stackoverflow.com/a/33400770/743730
        url = 'https://api.github.com/repos/{}/{}/stats/contributors'.format(
            entry['owner'], entry['name'])
        response = self.direct_api_call(url)
        if isinstance(response, int) and response >= 400:
            return ('api', False, True)
        elif response == None:
            return ('api', False, True)
        else:
            # In case of empty repos, you get status 204: no content.
            return ('api', True, response != 204)


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

            if readme != None and not isinstance(readme, int):
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
                     start_id=None, force=False, **kwargs):
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

        def body_function(thing):
            t1 = time()
            if isinstance(thing, github3.repos.repo.Repository):
                repo = thing
                (added, entry) = self.add_entry_from_github3(repo)
                if added:
                    msg('Added {}'.format(e_summary(entry)))
            else:
                entry = thing
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

            if not entry or (not entry['is_visible'] and not force):
                return
            if entry['content_type'] == '':
                (code, html) = self.get_home_page(entry)
                if code in [404, 451]:
                    return
                (method, tested, empty) = self.check_empty(entry, prefer_http, html)
                if not tested:
                    return
                elif empty:
                    msg('{} found empty via {}'.format(e_summary(entry), method))
                    self.update_field(entry, 'content_type', 'empty')
                else:
                    self.update_field(entry, 'content_type', 'nonempty')
                    (_, files, owner, name) = self.extract_files_from_html(html, entry)
                    if owner != entry['owner']:
                        import ipdb; ipdb.set_trace()
                    elif name != entry['name']:
                        import ipdb; ipdb.set_trace()
                    if files:
                        self.update_field(entry, 'files', files)
                        msg('added {} files for {}'.format(len(files), e_summary(entry)))
                    else:
                        # Something went wrong. Maybe the repository has been
                        # renamed and getting the http page now fails, etc.
                        msg('*** problem getting files for nonempty repo {}'.format(
                            e_summary(entry)))
                if entry['content_type'] != 'empty':
                    # If we got files, try to get the readme.
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


    def infer_type(self, targets=None, prefer_http=False, overwrite=False,
                   start_id=None, **kwargs):

        def guess_type(entry):
            # Test 1: If any file has a code file extension, then there is code.
            if entry['files'] != -1:
                for f in entry['files']:
                    if has_code_extension(f) or is_code_file(f):
                        return 'code'
            # Test 2: if GitHub reported any recognized programming language.
            if entry['languages'] != -1:
                for pair in entry['languages']:
                    if known_code_lang(pair['name']):
                        return 'code'
            return None

        def body_function(entry):
            t1 = time()
            if entry['content_type'] == '':
                (code, html) = self.get_home_page(entry)
                if code in [404, 451]:
                    return
                (method, tested, empty) = self.check_empty(entry, prefer_http)
                if not tested:
                    return
                elif empty:
                    msg('{} found empty via {}'.format(e_summary(entry), method))
                    self.update_field(entry, 'content_type', 'empty')
                else:
                    self.update_field(entry, 'content_type', 'nonempty')
                    (_, files, owner, name) = self.extract_files_from_html(html, entry)
                    if owner != entry['owner']:
                        import ipdb; ipdb.set_trace()
                    elif name != entry['name']:
                        import ipdb; ipdb.set_trace()
                    if files:
                        self.update_field(entry, 'files', files)
                        msg('added {} files for {}'.format(len(files), e_summary(entry)))
                    else:
                        # Something went wrong. Maybe the repository has been
                        # renamed and getting the http page now fails, etc.
                        msg('*** problem getting files for nonempty repo {}'.format(
                            e_summary(entry)))
            elif entry['content_type'] == 'empty':
                msg('*** {} believed to be empty -- skipping'.format(e_summary(entry)))
                return

            guessed = guess_type(entry)
            if guessed:
                msg('{} guessed to contain {}'.format(e_summary(entry), guessed))
                self.update_field(entry, 'content_type', guessed)
            else:
                msg('Unable to guess type of {}'.format(e_summary(entry)))

        # And let's do it.
        selected_repos = {'is_deleted': False, 'is_visible': True}
        if start_id > 0:
            msg('Skipping GitHub id\'s less than {}'.format(start_id))
            selected_repos['_id'] = {'$gte': start_id}
        self.loop(self.entry_list, body_function, selected_repos, targets, start_id)


    def update_files(self, targets=None, api_only=False, prefer_http=False,
                     overwrite=False, force=False, start_id=None, **kwargs):

        def get_files_via_api(entry):
            # Using the API is faster, but you're limited to 5000 calls/hr.
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
                # it might have no files.  FIXME: use api to get branch name.
                get_files_via_http(entry)
            else:
                results = json.loads(response)
                if 'message' in results and results['message'] == 'Not Found':
                    msg('*** {} not found -- skipping'.format(e_summary(entry)))
                    return
                elif 'tree' in results:
                    files = files_from_api(results['tree'])
                    self.update_field(entry, 'files', files)
                    self.update_field(entry, 'content_type', 'nonempty')
                    msg('added {} files for {}'.format(len(files), e_summary(entry)))
                else:
                    import ipdb; ipdb.set_trace()

        def get_files_via_http(entry):
            (code, html) = self.get_home_page(entry)
            if code in [404, 451]:
                # 404 = not found. 451 = unavailable for legal reasons.
                self.update_field(entry, 'is_visible', False)
                msg('*** {} no longer visible'.format(e_summary(entry)))
            elif code >= 400:
                # We got a code over 400, but we don't know why.
                raise UnexpectedResponseException('Getting files', code)
            elif html:
                (empty, files, owner, name) = self.extract_files_from_html(html, entry)
                if owner != entry['owner']:
                    msg('{} owner changed to {}'.format(e_summary(entry), owner))
                    self.update_field(entry, 'owner', owner)
                elif name != entry['name']:
                    msg('{} repo name changed to {}'.format(e_summary(entry), name))
                    self.update_field(entry, 'name', name)

                if empty:
                    msg('{} appears empty via http'.format(e_summary(entry)))
                    self.update_field(entry, 'content_type', 'empty')
                elif files:
                    self.update_field(entry, 'files', files)
                    self.update_field(entry, 'content_type', 'nonempty')
                    msg('added {} files for {}'.format(len(files), e_summary(entry)))
                else:
                    # Something went wrong. Maybe the repository has been
                    # renamed and getting the http page now fails, etc.
                    msg('*** problem getting files for nonempty repo {}'.format(
                        e_summary(entry)))
            else:
                import ipdb; ipdb.set_trace()

        def get_files_via_svn(entry):
            # SVN is not bound by same API rate limits, but is much slower.
            if not entry['default_branch'] or entry['default_branch'] == 'master':
                branch = '/trunk'
            else:
                branch = '/branches/' + entry['default_branch']
            path = 'https://github.com/' + e_path(entry) + branch
            try:
                (code, output, err) = shell_cmd(['svn', 'ls', path])
            except Exception as ex:
                msg('*** Error for {}: {}'.format(e_summary(entry), ex))
                return
            if code == 0:
                if output:
                    files = output.split('\n')
                    files = [f for f in files if f]  # Remove empty strings.
                    self.update_field(entry, 'files', files)
                    self.update_field(entry, 'content_type', 'nonempty')
                    msg('added {} files for {}'.format(len(files), e_summary(entry)))
                else:
                    msg('*** no result for {}'.format(e_summary(entry)))
            elif code == 1 and err.find('non-existent') > 1:
                msg('{} found empty'.format(e_summary(entry)))
                self.update_field(entry, 'content_type', 'empty')
            else:
                msg('*** Error for {}: {}'.format(e_summary(entry), err))

        def files_from_api(json_tree):
            files = []
            for thing in json_tree:
                if thing['type'] == 'blob':
                    files.append(thing['path'])
                elif thing['type'] == 'tree':
                    files.append(thing['path'] + '/')
                elif thing['type'] == 'commit':
                    # These are submodules.  Treat as subdirectories for our purposes.
                    files.append(thing['path'] + '/')
                else:
                    import ipdb; ipdb.set_trace()
            return files

        def body_function(entry):
            if not force:
                info = e_summary(entry)
                if entry['files']:
                    msg('*** {} has a files list -- skipping'.format(info))
                    return
                if entry['content_type'] == 'empty':
                    msg('*** {} believed to be empty -- skipping'.format(info))
                    return
                if entry['is_visible'] == False or entry['is_deleted'] == True:
                    msg('*** {} believed to be unavailable -- skipping'.format(info))
                    return
            if api_only:      get_files_via_api(entry)
            elif prefer_http: get_files_via_http(entry)
            else:             get_files_via_svn(entry)

        def iterator(targets, start_id):
            fields = ['files', 'content_type', 'default_branch', 'is_visible',
                      'is_deleted', 'owner', 'name', 'time', '_id']
            return self.entry_list(targets, fields, start_id)

        # And let's do it.
        if force:
            selected_repos = {'is_deleted': False, 'is_visible': True}
        else:
            # If we're not forcing re-getting the files, don't return results that
            # already have files data.
            selected_repos = {'is_deleted': False, 'is_visible': True,
                              'files': [], 'content_type': {'$ne': 'empty'}}
        if start_id > 0:
            msg('Skipping GitHub id\'s less than {}'.format(start_id))
            selected_repos['_id'] = {'$gte': start_id}
        # Note: the selector only has effect when targets are not explicit.
        self.loop(iterator, body_function, selected_repos, targets, start_id)
