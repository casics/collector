#!/usr/bin/env python3.4
#
# @file    dbinterface.py
# @brief   Database encapsulation.
# @author  Michael Hucka
#
# <!---------------------------------------------------------------------------
# Copyright (C) 2015 by the California Institute of Technology.
# This software is part of CASICS, the Comprehensive and Automated Software
# Inventory Creation System.  For more information, visit http://casics.org.
# ------------------------------------------------------------------------- -->

import sys
import os
import persistent
import transaction
import ZODB
from ZEO.ClientStorage import ClientStorage
from ZODB import FileStorage, DB
from BTrees.OOBTree import BTree

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from common import *


class Database:
    def __init__(self):
        '''Reads the configuration file but does not open the database.'''
        cfg = Config()
        self.dbserver = cfg.get('global', 'dbserver')
        self.dbport = cfg.get('global', 'dbport')
        self.dbfile = cfg.get('global', 'dbfile')
        self.dbname = cfg.get('global', 'dbname')


    def open(self):
        '''Opens a connection to the database server and either reads our
        top-level element, or creates the top-level element if it doesn't
        exist in the database.  Returns the top-level element.'''

        msg('Attempting connection to {} on port {}'.format(self.dbserver, self.dbport))
        server_port_tuple = (self.dbserver, int(self.dbport))
        serverconnection = ClientStorage(server_port_tuple)

        self.dbstorage = DB(serverconnection)
        self.dbconnection = self.dbstorage.open()
        self.dbroot = self.dbconnection.root()

        if not self.dbname in self.dbroot.keys():
            msg('Creating new database named "{}"'.format(self.dbname))
            self.dbroot[self.dbname] = BTree()
            transaction.commit()
        else:
            msg('Accessing existing database named "{}"'.format(self.dbname))
        self.dbtop = self.dbroot[self.dbname]

        return self.dbtop


    def close(self):
        '''Closes the connection to the database.'''
        self.dbconnection.close()
