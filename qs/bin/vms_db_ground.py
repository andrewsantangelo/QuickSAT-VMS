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
        self.open()

    def __del__(self):
        self.close()

    def _execute(self, stmt, args=None):
        """
        simple function to allow executing unusual statements
        """
        print "*** EXECUTE GROUND"
        # Test if the connection to the ground DB is still alive
        if self.test_connection():
            with self.lock:
                if isinstance(args, list):
                    self.cursor.executemany(stmt, args)
                else:
                    self.cursor.execute(stmt, args)

                if self.cursor.with_rows:
                    return self.cursor.fetchall()
                else:
                    self.db.commit()
                    return True
        else:
            return False

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
            # pylint: disable=bare-except
            try:
                self._execute(stmt, (msg,))
            except:
                syslog.syslog(syslog.LOG_ERR, 'Error logging message "{}": {}'.format(msg, sys.exc_info()[1]))

    def test_connection(self):
        print "++++ In test_connection"
        with self.lock:
            if self.db.is_connected():
                print " #### DB CONNECTED to the Ground #### "
                if not self.cursor:
                    self.cursor = self.db.cursor(dictionary=True, buffered=True)
                return True
            else:
                try:
                    # Try to reconnect once, if that fails we probably need to
                    # wait until the connection has been re-established.
                    # if self.cursor:
                    del self.cursor
                    self.cursor = None
                    self.db.reconnect(attempts=1, delay=0)
                    self.cursor = self.db.cursor(dictionary=True, buffered=True)
                    print " &&&&&& Trying to Reconnect to the Ground"

                    # When re-establishing mysql connections you usually need
                    # to re-instantiate any cursors or prepared statements
                    self.cursor = self.db.cursor(dictionary=True)
                    return True
                except mysql.connector.Error as err:
                    print "-----> error connecting to the ground <-----------"
                    syslog.syslog(syslog.LOG_ERR, 'Error reconnecting to ground: {}'.format(err))
        return False

    def open(self):
        with self.lock:
            if not self.db:
                self.db = mysql.connector.connect(**self.config)

            if self.db and not self.cursor:
                self.cursor = self.db.cursor(dictionary=True)

    def close(self):
        with self.lock:

            if self.cursor:
                self.cursor.close()
                # print 'cursor.close'

            if self.db:
                self.db.close()
                # print 'db.close'

    def sync_selected_db_table(self, selected_table_name):
        print "----> Printing Selected Table"
        selected_table_name_quotes = '`{}`'.format(selected_table_name)
        stmt = '''
            LOAD DATA LOCAL INFILE '/opt/qs/tmp/{}.csv'
                INTO TABLE `stepSATdb_Flight`.{} FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"'
                ESCAPED BY '\\\\' LINES TERMINATED BY '\n'
        '''.format(selected_table_name, selected_table_name_quotes)
        # stmt_update_last_sync_time = '''
        #     UPDATE `stepSATdb_Flight`.`Recording_Session_State`
        #         SET `Recording_Session_State`.`last_FRNCS_sync` = NOW()
        #             WHERE `Recording_Session_State`.`Recording_Sessions_recording_session_id`=(
        #                 SELECT MAX(`Recording_Sessions`.`recording_session_id`)
        #                     FROM `stepSATdb_Flight`.`Recording_Sessions` LIMIT 1)
        # '''
        with self.lock:
            try:
                sync_Success = self._execute(stmt)
                # self._execute(stmt_update_last_sync_time)
                return sync_Success
            except mysql.connector.Error as err:
                print "-----> error connecting to the ground, sync_selected_db_table <-----------"
                syslog.syslog(syslog.LOG_ERR, 'Error reconnecting to ground: {}'.format(err))
                return False

    def sync_recording_sessions(self):
        stmt = '''
            LOAD DATA LOCAL INFILE '/opt/qs/tmp/recording_sessions.csv'
                INTO TABLE `stepSATdb_Flight`.`Recording_Sessions` FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"'
                ESCAPED BY '\\\\' LINES TERMINATED BY '\n'
        '''
        # stmt_update_last_sync_time = '''
        #     UPDATE `stepSATdb_Flight`.`Recording_Session_State`
        #         SET `Recording_Session_State`.`last_FRNCS_sync` = NOW()
        #             WHERE `Recording_Session_State`.`Recording_Sessions_recording_session_id`=(
        #                 SELECT MAX(`Recording_Sessions`.`recording_session_id`)
        #                     FROM `stepSATdb_Flight`.`Recording_Sessions` LIMIT 1)
        # '''
        with self.lock:
            try:
                sync_Success = self._execute(stmt)
                # self._execute(stmt_update_last_sync_time)
                return sync_Success
            except mysql.connector.Error as err:
                print "-----> error connecting to the ground, sync_recording_sessions <-----------"
                syslog.syslog(syslog.LOG_ERR, 'Error reconnecting to ground: {}'.format(err))
                return False

    def sync_recording_session_state(self):
        stmt = '''
            LOAD DATA LOCAL INFILE '/opt/qs/tmp/Recording_Session_State.csv'
                INTO TABLE `stepSATdb_Flight`.`Recording_Session_State` FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"'
                ESCAPED BY '\\\\' LINES TERMINATED BY '\n'
        '''
        # stmt_update_last_sync_time = '''
        #     UPDATE `stepSATdb_Flight`.`Recording_Session_State`
        #         SET `Recording_Session_State`.`last_FRNCS_sync` = NOW()
        #             WHERE `Recording_Session_State`.`Recording_Sessions_recording_session_id`=(
        #                 SELECT MAX(`Recording_Sessions`.`recording_session_id`)
        #                     FROM `stepSATdb_Flight`.`Recording_Sessions` LIMIT 1)
        # '''
        with self.lock:
            try:
                sync_Success = self._execute(stmt)
                # self._execute(stmt_update_last_sync_time)
                return sync_Success
            except mysql.connector.Error as err:
                print "-----> error connecting to the ground, sync_recording_session_state <-----------"
                syslog.syslog(syslog.LOG_ERR, 'Error reconnecting to ground: {}'.format(err))
                return False

    def sync_flight_pointers(self):
        stmt = '''
            LOAD DATA LOCAL INFILE '/opt/qs/tmp/Flight_Pointers.csv'
                INTO TABLE `stepSATdb_Flight`.`Flight_Pointers` FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"'
                ESCAPED BY '\\\\' LINES TERMINATED BY '\n'
        '''
        # stmt_update_last_sync_time = '''
        #     UPDATE `stepSATdb_Flight`.`Recording_Session_State`
        #         SET `Recording_Session_State`.`last_FRNCS_sync` = NOW()
        #             WHERE `Recording_Session_State`.`Recording_Sessions_recording_session_id`=(
        #                 SELECT MAX(`Recording_Sessions`.`recording_session_id`)
        #                     FROM `stepSATdb_Flight`.`Recording_Sessions` LIMIT 1)
        # '''
        with self.lock:
            try:
                sync_Success = self._execute(stmt)
                # self._execute(stmt_update_last_sync_time)
                return sync_Success
            except mysql.connector.Error as err:
                print "-----> error connecting to the ground, sync_flight_pointers <-----------"
                syslog.syslog(syslog.LOG_ERR, 'Error reconnecting to ground: {}'.format(err))
                return False

    def sync_system_applications(self):
        stmt = '''
            LOAD DATA LOCAL INFILE '/opt/qs/tmp/system_applications.csv'
                INTO TABLE `stepSATdb_Flight`.`System_Applications` FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"'
                ESCAPED BY '\\\\' LINES TERMINATED BY '\n'
        '''
        with self.lock:
            try:
                self._execute(stmt)
            except mysql.connector.Error as err:
                print "-----> error connecting to the ground, sync_system_applications <-----------"
                syslog.syslog(syslog.LOG_ERR, 'Error reconnecting to ground: {}'.format(err))
                return False

    def read_command_log(self, datetime_last_command):
        # Returns the appropriate row(s) of the ground db
        stmt = '''
            SELECT *
                FROM `stepSATdb_Flight`.`Command_Log`
                WHERE `Command_Log`.`command_state`='Pending-Ground'
                    AND `Command_Log`.`time_of_command` > datetime_last_command
                    AND `Command_Log`.`Recording_Sessions_recording_session_id`=(
                        SELECT MAX(`Recording_Sessions`.`recording_session_id`)
                            FROM `stepSATdb_Flight`.`Recording_Sessions`
                    )
        '''
        print stmt
        with self.lock:
            try:
                commands = self._execute(stmt)
                return commands
            except mysql.connector.Error as err:
                print "-----> error connecting to the ground, read_command_log <-----------"
                syslog.syslog(syslog.LOG_ERR, 'Error reconnecting to ground: {}'.format(err))
                return False

    def update_ground_command_log(self, ground_commands):
        # Writes updated row(s)to the ground db command log
        print "update ground command log"
        if ground_commands:
            for row in ground_commands:
                stmt = '''
                    UPDATE `stepSATdb_Flight`.`Command_Log`
                        SET `Command_Log`.`read_from_sv` = 1
                            WHERE `Command_Log`.`Recording_Sessions_recording_session_id` = %(Recording_Sessions_recording_session_id)s
                            AND `Command_log`.`time_of_command` = %(time_of_command)s
                '''
                with self.lock:
                    try:
                        self._execute(stmt, row)
                    except mysql.connector.Error as err:
                        print "-----> error connecting to the ground, update_ground_command_log <-----------"
                        syslog.syslog(syslog.LOG_ERR, 'Error reconnecting to ground: {}'.format(err))
                        return False

    def add_ground_command_log(self, ground_commands):
        # adds new row(s) to ground db
        print "----> In add_ground_command_log, db_ground"
        print ground_commands
        if ground_commands:
            for row in ground_commands:
                stmt = '''
                    INSERT INTO `stepSATdb_Flight`.`Command_Log` (`time_of_command`, `Recording_Sessions_recording_session_id`,`command`,
                        `command_state`, `command_data`, `priority`, `source`, `read_from_sv`, `pushed_to_ground`) VALUES (%(time_of_command)s,%(Recording_Sessions_recording_session_id)s,%(command)s,%(command_state)s,%(command_data)s,%(priority)s,%(source)s,%(read_from_sv)s,1)
                        ON DUPLICATE KEY UPDATE `Command_Log`.`pushed_to_ground` = 1 , `Command_Log`.`command_state` = %(command_state)s
                '''
                print stmt
                with self.lock:
                    try:
                        self._execute(stmt, row)
                    except mysql.connector.Error as err:
                        print "-----> error connecting to the ground, add_ground_command_log <-----------"
                        syslog.syslog(syslog.LOG_ERR, 'Error reconnecting to ground: {}'.format(err))
                        return False

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
            info = self._execute(app_stmt, (app_id,))[0]
            params = self._execute(params_stmt, (app_id,))

        return (info, params)
