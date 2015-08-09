#!/usr/bin/env python


import syslog
import itertools
import sys
import subprocess
import threading
import vms_db

# To connect to the QS/VMS database, install with
#   $ pip install MySQL-python
# but that requires other libraries, so it is recommended to install with this
# command, and then install the mysql connector package:
#   $ sudo apt-get install python-mysqldb
#   $ pip install mysql-connector-python
# install pip as described here:
#   https://pypi.python.org/pypi/setuptools
import mysql.connector


class vms_db_ground(object):
    def __init__(self, address, port, cert, username, password, dbname, **kwargs):
        self.lock = threading.RLock()
        self.db = None
        self.cursor = None
        self.config = {
            'user': username,
            'password': password,
            'host': address,
            'port': port,
            'database': dbname,
            'ssl_ca': cert,
        }
        if not self.config['ssl_ca']:
            del self.config['ssl_ca']    
        with self.lock:     
            self.open()

    def __del__(self):
        self.close()

    def _execute(self, stmt, args=None):
        """
        simple function to allow executing unusual statements
        """
    
        with self.lock:
            if isinstance(args, list):
                self.cursor.executemany(stmt, args)
            else:
                self.cursor.execute(stmt, args)
            if self.cursor.with_rows:
                return self.cursor.fetchall()
            else:
                self.db.commit()
                return None

    def _log_msg(self, msg):
        stmt = '''
            INSERT INTO `stepSATdb_Flight`.`System_Messages` (
                    `System_Messages`.`event_time`,
                    `System_Messages`.`sysmsg`,
                    `System_Messages`.`Recording_Sessions_recording_session_id`
                )
                VALUES ((NOW()+0),%s,(
                    SELECT MAX(`Recording_Sessions`.`recording_session_id`)
                        FROM `stepSATdb_Flight`.`Recording_Sessions`
                    )
                )
        '''
        # Handle exceptions for this cleanly, errors should get logged to the
        # syslog
        
        with self.lock:
            try:
                self.cursor.execute(stmt, (msg,))
                self.db.commit()
            except:
                syslog.syslog(syslog.LOG_ERR, 'Error logging message "{}": {}'.format(msg, sys.exc_info()[1]))
        

    def open(self):
        
        with self.lock:
            try:
                if not self.db:
                    self.db = mysql.connector.connect(**self.config)
              
                if self.db and not self.cursor:
                    self.cursor = self.db.cursor(dictionary=True)
            except:
                pass
                #print "can't open ground db"
                


    def close(self):
        with self.lock:
            
            if self.cursor:
                self.cursor.close()
                print 'cursor.close'

            if self.db:
                self.db.close()
                print 'db.close'
            
      

    def sync_selected_db_table(self, selected_table_name):
        selected_table_name_quotes = '`{}`'.format(selected_table_name)
        stmt = '''
            LOAD DATA LOCAL INFILE '/opt/qs/tmp/{}.csv' 
                INTO TABLE `stepSATdb_Flight`.{} FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"'
                ESCAPED BY '\\\\' LINES TERMINATED BY '\n'
        '''.format(selected_table_name, selected_table_name_quotes)
        stmt_update_last_sync_time = '''
            UPDATE `stepSATdb_Flight`.`Recording_Session_State`
                SET `Recording_Session_State`.`last_FRNCS_sync` = NOW()
                    WHERE `Recording_Session_State`.`Recording_Sessions_recording_session_id`=(
                        SELECT MAX(`Recording_Sessions`.`recording_session_id`)
                            FROM `stepSATdb_Flight`.`Recording_Sessions` LIMIT 1)
        '''
        with self.lock:
            self.cursor.execute(stmt)
            self.cursor.execute(stmt_update_last_sync_time)
            self.db.commit()

        
        
      