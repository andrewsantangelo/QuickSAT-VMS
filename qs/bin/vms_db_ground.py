#!/usr/bin/env python
"""
A module that provides a python interface to the QS/VMS ground database.
"""

import syslog
import sys
import threading

# To connect to the QS/VMS database, install with
#   $ pip install MySQL-python
# but that requires other libraries, so it is recommended to install with this
# command, and then install the mysql connector package:
#   $ sudo apt-get install python-mysqldb
#   $ pip install mysql-connector-python
# install pip as described here:
#   https://pypi.python.org/pypi/setuptools
import mysql.connector

# Disable some pylint warnings that I don't care about
# pylint: disable=line-too-long,fixme,invalid-name,too-many-public-methods,too-many-arguments
#
# TEMPORARY:
# pylint: disable=missing-docstring


class vms_db_ground(object):
    """
    A class that wraps up the QS/VMS ground database interface.
    """
    # pylint: disable=unused-argument
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
            'autocommit': True,
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
            # pylint: disable=bare-except
            except:
                syslog.syslog(syslog.LOG_ERR, 'Error logging message "{}": {}'.format(msg, sys.exc_info()[1]))

    def open(self):
        with self.lock:
            try:
                if not self.db:
                    self.db = mysql.connector.connect(**self.config)

                if self.db and not self.cursor:
                    self.cursor = self.db.cursor(dictionary=True)
            # pylint: disable=bare-except
            except:
                raise

    def close(self):
        with self.lock:

            if self.cursor:
                self.cursor.close()
                # print 'cursor.close'

            if self.db:
                self.db.close()
                # print 'db.close'

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

    def sync_recording_sessions(self):
        stmt = '''
            LOAD DATA LOCAL INFILE '/opt/qs/tmp/recording_sessions.csv'
                INTO TABLE `stepSATdb_Flight`.`Recording_Sessions` FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"'
                ESCAPED BY '\\\\' LINES TERMINATED BY '\n'
        '''
        with self.lock:
            self.cursor.execute(stmt)
            self.db.commit()

    def read_command_log(self):
        # Returns the appropriate row(s) of the ground db
        stmt = '''
            SELECT *
                FROM `stepSATdb_Flight`.`Command_Log`
                WHERE `Command_Log`.`command_state`='Pending'
                    AND `Command_Log`.`read_from_sv`!='1'
                    AND `Command_Log`.`Recording_Sessions_recording_session_id`=(
                        SELECT MAX(`Recording_Sessions`.`recording_session_id`)
                            FROM `stepSATdb_Flight`.`Recording_Sessions`
                    )
        '''
        with self.lock:
            self.cursor.execute(stmt)
            commands = self.cursor.fetchall()
        return commands

    def update_ground_command_log(self, ground_commands):
        # Writes updated row(s)to the ground db command log
        if ground_commands:
            for row in ground_commands:
                stmt = '''
                    UPDATE `stepSATdb_Flight`.`Command_Log`
                        SET `Command_Log`.`read_from_sv` = 1
                            WHERE `Command_Log`.`Recording_Sessions_recording_session_id` = %(Recording_Sessions_recording_session_id)s
                            AND `Command_log`.`time_of_command` = %(time_of_command)s
                '''
                with self.lock:
                    self.cursor.execute(stmt, row)
                    self.db.commit()

    def add_ground_command_log(self, ground_commands):
        # adds new row(s) to ground db
        if ground_commands:
            for row in ground_commands:
                stmt = '''
                    INSERT INTO `stepSATdb_Flight`.`Command_Log` (`time_of_command`, `Recording_Sessions_recording_session_id`,`command`,
                        `command_state`, `command_data`, `priority`, `source`, `read_from_sv`, `pushed_to_ground`) VALUES (%(time_of_command)s,%(Recording_Sessions_recording_session_id)s,%(command)s,%(command_state)s,%(command_data)s,%(priority)s,%(source)s,%(read_from_sv)s,1)
                        ON DUPLICATE KEY UPDATE `Command_Log`.`pushed_to_ground` = 1 , `Command_Log`.`command_state` = %(command_state)s
                '''
                # print stmt
                with self.lock:
                    self.cursor.execute(stmt, row)
                    self.db.commit()

    def get_application_info(self, app_id):
        app_stmt = '''
            SELECT *
                FROM `stepSATdb_Flight`.`System_Applications`
                WHERE `System_Applications`.`application_id`=%s
                LIMIT 1
        '''
        params_stmt = '''
            SELECT *
                FROM `stepSATdb_Flight`.`Parameter_ID_Table`
                WHERE `Parameter_ID_Table`.`System_Applications_application_id`=%s
        '''
        with self.lock:
            self.cursor.execute(app_stmt, (app_id,))
            info = self.cursor.fetchone()

            self.cursor.execute(params_stmt, (app_id,))
            params = self.cursor.fetchall()

        return (info, params)
