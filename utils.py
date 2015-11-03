#!/usr/bin/env python3.4
#
# @file    utils.py
# @brief   Helper classes.
# @author  Michael Hucka
#
# <!---------------------------------------------------------------------------
# Copyright (C) 2015 by the California Institute of Technology.
# This software is part of CASICS, the Comprehensive and Automated Software
# Inventory Creation System.  For more information, visit http://casics.org.
# ------------------------------------------------------------------------- -->

from reporecord import *
from configparser import ConfigParser
import logging
import six


# -----------------------------------------------------------------------------
# General-purpose classes
# -----------------------------------------------------------------------------

# Configuration file handling
# .............................................................................

class Config():
    '''A class to encapsulate reading our configuration file.'''

    _default_config_file = 'config.ini'

    def __init__(self, cfg_file=_default_config_file):
        self._cfg = ConfigParser()
        self._cfg.read(cfg_file)

    def get(self, section, prop):
        '''Read a property value from the configuration file.
        Two forms of the value of argument "section" are understood:
           * value of section is an integer => section named after host
           * value of section is a string => literal section name
        '''
        if isinstance(section, str):
            return self._cfg.get(section, prop)
        elif isinstance(section, int):
            section_name = Host.name(section)
            if section_name:
                return self._cfg.get(section_name, prop)
            else:
                return None


# Logging.
# .............................................................................

class CataloguerLogger(object):
    quiet   = False
    logger  = None
    outlog  = None

    def __init__(self, logfile, quiet):
        self.quiet = quiet
        self.configure_logging(logfile)


    def configure_logging(self, logfile):
        self.logger = logging.getLogger('Cataloguer')
        self.logger.setLevel(logging.DEBUG)
        logging.getLogger('Cataloguer').addHandler(logging.NullHandler())
        if logfile:
            handler = logging.FileHandler(logfile)
        else:
            handler = logging.StreamHandler()
        formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)
        self.outlog = handler.stream


    def info(self, *args):
        msg = ' '.join(args)
        self.logger.info(msg)


    def fail(self, *args):
        msg = 'ERROR: ' + ' '.join(args)
        self.logger.error(msg)
        self.logger.error('Exiting.')
        raise SystemExit(msg)


    def get_log(self):
        return self.outlog



# -----------------------------------------------------------------------------
# General-purpose functions
# -----------------------------------------------------------------------------

def msg(*args):
    '''Like the standard print(), but flushes the output immediately.
    This is useful when piping the output of a script, because Python by
    default will buffer the output in that situation and this makes it very
    difficult to see what is happening in real time.
    '''
    six.print_(*args, flush=True)


def update_progress(progress):
    '''Value of "progress" should be a float from 0 to 1.'''
    six.print_('\r[{0:10}] {1:.0f}%'.format('#' * int(progress * 10),
                                            progress*100), end='')
