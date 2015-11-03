#!/usr/bin/env python3.4

from utils import *

import os
import plac
from subprocess import call
import pdb


# Main body.
# .............................................................................
# Currently this only does GitHub, but extending this to handle other hosts
# should hopefully be possible.

def main():
    try:
        cfg = Config()
        dbserver = cfg.get('global', 'dbserver')
        dbport = cfg.get('global', 'dbport')
        dbfile = cfg.get('global', 'dbfile')
        runzeo = cfg.get('global', 'runzeo')
    except Exception as err:
        raise SystemExit('Failed to read "dbserver" and/or "dbport" from config file')

    try:
        portinfo = '{}:{}'.format(dbserver, dbport)
        msg('Starting server on', portinfo)
        os.system('python3.4 ' + runzeo + ' -a ' + portinfo + ' -f ' + dbfile)
    except PermissionError:
        msg('Permission error -- maybe something is using port {}?'.format(dbport))
    except Exception as err:
        msg(err)


# Entry point
# .............................................................................

def cli_main():
    plac.call(main)

cli_main()
