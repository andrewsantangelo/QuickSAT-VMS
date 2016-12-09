#!/usr/bin/env python
"""
A module that provides a python interface to the QS/VMS database.
"""

import syslog
import itertools
import sys
import threading
import string
import os
import os.path
import pwd
import grp

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
# pylint: disable=line-too-long,fixme,invalid-name,too-many-public-methods,too-many-arguments,too-many-locals,too-many-lines,too-many-statements
#
# there are mix of print syntaxes, so just ignore the () on some of them
# pylint: disable=superfluous-parens
#
# TEMPORARY:
# pylint: disable=missing-docstring


class vms_db(object):
    """
    A class that wraps up the QS/VMS database interface.
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
            'autocommit': True
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

        # pylint: disable=bare-except
        with self.lock:
            try:
                self.cursor.execute(stmt, (msg,))
                self.db.commit()
            except KeyboardInterrupt as e:
                raise e
            except:
                syslog.syslog(syslog.LOG_ERR, 'Error logging message "{}": {}'.format(msg, sys.exc_info()[1]))

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

            if self.db:
                self.db.close()

    def get_board_connection_data(self, ident=None, name=None):
        """
        Returns all the connection information for the configuration part
        associated with the specified application.  The info can be retrieved
        either with a unique app name or a unique app id.
        """
        stmt = '''
            SELECT `System_Applications`.`application_id` AS 'id',
                    `System_Applications`.`application_name` AS 'name',
                    `System_Applications`.`virtual_machine_id` AS 'vm',
                    `System_Applications`.`Configuration_Parts_part_key` AS 'part',
                    `Virtual_Machines`.`connection_method` AS 'method',
                    `Virtual_Machines`.`connection_address` AS 'address',
                    `Virtual_Machines`.`connection_username` AS 'username',
                    `Virtual_Machines`.`connection_password` AS 'password'
                FROM `stepSATdb_Flight`.`System_Applications`
                LEFT JOIN `stepSATdb_Flight`.`Virtual_Machines`
                ON `System_Applications`.`virtual_machine_id` = `Virtual_Machines`.`virtual_machine_id`
                WHERE `System_Applications`.`{}` = {}
        '''
        if ident:
            stmt = stmt.format('application_id', ident)
        elif name:
            stmt = stmt.format('application_name', repr(name))
        else:
            stmt = None

        if stmt:
            with self.lock:
                try:
                    self.cursor.execute(stmt)
                    info = self.cursor.fetchall()
                except mysql.connector.Error as err:
                    print("MySQL Error: {}".format(err))
                    syslog.syslog(syslog.LOG_DEBUG, "MySQL Error: {}".format(err))
            if len(info) == 1:
                info = info[0]
            return info
        else:
            syslog.syslog(syslog.LOG_DEBUG, 'get_board_connection_data() called with no application identification info')
            return None

    def get_app_info(self, ident=None, name=None):
        """
        Returns all database information regarding a single application.  The
        info can be retrieved either with a unique app name or a unique app id.
        """

        # If an application does not have a valid state, assume it is "50" - "On Ground"
        stmt = '''
            SELECT `System_Applications`.`application_id` AS 'id',
                    `System_Applications`.`application_name` AS 'name',
                    ifnull((
                        SELECT `System_Applications_State`.`application_state`
                            FROM `stepSATdb_Flight`.`System_Applications_State`
                            WHERE `System_Applications`.`application_id` = `System_Applications_State`.`application_id`
                            ORDER BY `System_Applications_State`.`event_key` DESC LIMIT 1
                    ), 50) AS 'state',
                    `System_Applications`.`Configuration_Parts_part_key` AS 'part',
                    `System_Applications`.`Configuration_Parts_Configuration_configuration_key` AS 'config',
                    `System_Applications`.`Configuration_Parts_Configuration_Mission_mission_key` AS 'mission',
                    `System_Applications`.`application_filename` AS 'application_filename',
                    `pid`.`parameter_id` AS 'param',
                    `pid`.`type` AS 'param_type',
                    `vm`.`virtual_machine_id` AS 'vm',
                    `vm`.`vm_os` AS 'vm_os',
                    `vm`.`virtual_machine_name` AS 'vm_name',
                    `vm`.`vm_core` AS 'vm_core'
                FROM `stepSATdb_Flight`.`System_Applications`
                LEFT JOIN `stepSATdb_Flight`.`Parameter_ID_Table` AS `pid`
                ON `System_Applications`.`application_id` = `pid`.`System_Applications_application_id`
                LEFT JOIN `stepSATdb_Flight`.`Virtual_Machines` AS `vm`
                ON `System_Applications`.`virtual_machine_id` = `vm`.`virtual_machine_id`
                WHERE `System_Applications`.`{0}` = {1}
        '''
        if ident:
            stmt = stmt.format('application_id', ident)
        elif name:
            stmt = stmt.format('application_name', repr(name))
        else:
            stmt = None

        print stmt

        if stmt:
            with self.lock:
                self.cursor.execute(stmt)
                info = self.cursor.fetchall()
            if len(info) == 1:
                info = info[0]
            return info
        else:
            syslog.syslog(syslog.LOG_DEBUG, 'get_app_info() called with no application identification info')
            return None

    def get_board_apps(self, ident=None, name=None):
        """
        Retrieves all applications in all VMs for the configuration part
        associated with the specified application.  The info can be retrieved
        either with a unique app name or a unique app id.

        Find which VMs are present on the target board.  The board can be
        identified by following the VM that this application is present on,
        then identifying all VMs that have the same vm_board_part_key value.
        """
        stmt = '''
            SELECT `System_Applications`.`application_id` AS 'id',
                    `System_Applications`.`application_name` AS 'name',
                    ifnull((
                        SELECT `System_Applications_State`.`application_state`
                            FROM `stepSATdb_Flight`.`System_Applications_State`
                            WHERE `System_Applications`.`application_id` = `System_Applications_State`.`application_id`
                            ORDER BY `System_Applications_State`.`event_key` DESC LIMIT 1
                    ), 50) AS 'state',
                    `System_Applications`.`Configuration_Parts_part_key` AS 'part',
                    `System_Applications`.`Configuration_Parts_Configuration_configuration_key` AS 'config',
                    `System_Applications`.`Configuration_Parts_Configuration_Mission_mission_key` AS 'mission',
                    `pid`.`parameter_id` AS 'param',
                    `pid`.`type` AS 'param_type',
                    `vm`.`virtual_machine_id` AS 'vm',
                    `vm`.`vm_os` AS 'vm_os',
                    `vm`.`virtual_machine_name` AS 'vm_name',
                    `vm`.`vm_core` AS 'vm_core'
                FROM `stepSATdb_Flight`.`System_Applications`
                LEFT JOIN `stepSATdb_Flight`.`Parameter_ID_Table` AS `pid`
                ON `System_Applications`.`application_id` = `pid`.`System_Applications_application_id`
                LEFT JOIN `stepSATdb_Flight`.`Virtual_Machines` AS `vm`
                ON `System_Applications`.`virtual_machine_id` = `vm`.`virtual_machine_id`
                WHERE `vm`.`vm_board_part_key` =
                    (SELECT `vm`.`vm_board_part_key`
                    FROM `stepSATdb_Flight`.`System_Applications`
                    LEFT JOIN `stepSATdb_Flight`.`Virtual_Machines` AS `vm`
                    ON `System_Applications`.`virtual_machine_id` = `vm`.`virtual_machine_id`
                    WHERE `System_Applications`.`{0}` = {1})
        '''
        if ident:
            stmt = stmt.format('application_id', ident)
        elif name:
            stmt = stmt.format('application_name', repr(name))
        else:
            stmt = None

        if stmt:
            with self.lock:
                self.cursor.execute(stmt)
                apps = self.cursor.fetchall()
            return apps
        else:
            syslog.syslog(syslog.LOG_DEBUG, 'get_board_apps() called with no application identification info')
            return None

    def all_pending_commands(self):
        # Get the current recording_session_id
        stmt = '''
                SELECT *
                    FROM `stepSATdb_Flight`.`Recording_Sessions`
                    ORDER BY `Recording_Sessions`.`recording_session_id` DESC LIMIT 1
             '''
        with self.lock:
            try:
                self.cursor.execute(stmt)
                row_recording_session = self.cursor.fetchone()
            except mysql.connector.Error as err:
                print("MySQL Error: {}".format(err))
                syslog.syslog(syslog.LOG_DEBUG, "MySQL Error: {}".format(err))

        print "entering vms_db.all_pending_commands()"
        stmt = '''
            SELECT `Command_Log`.`command` AS command,
                    `Command_Log`.`time_of_command` AS time,
                    `Command_Log`.`Recording_Sessions_recording_session_id` AS id,
                    `Command_Log`.`command_data` AS data,
                    `Command_Log`.`Recording_Sessions_recording_session_id` AS session,
                    `Command_Log`.`source` AS source,
                    `Command_Log`.`priority` AS priority,
                    `Command_Log`.`command_id` AS command_id
                FROM `stepSATdb_Flight`.`Command_Log`
                WHERE `Command_Log`.`command_state`='Pending' AND `Command_Log`.`read_from_sv`=0
                    AND `Command_Log`.`Recording_Sessions_recording_session_id`=(
                        SELECT MAX(`Recording_Sessions`.`recording_session_id`)
                            FROM `stepSATdb_Flight`.`Recording_Sessions`
                    )
        '''
        print stmt
        with self.lock:
            try:
                self.cursor.execute(stmt)
                commands = self.cursor.fetchall()
            except mysql.connector.Error as err:
                print("MySQL Error: {}".format(err))
                syslog.syslog(syslog.LOG_DEBUG, "MySQL Error: {}".format(err))
                
        # Set all Pending Commands to read_from_sv = 1
        stmt = '''
            UPDATE `stepSATdb_Flight`.`Command_Log`
                SET `Command_Log`.`read_from_sv` = 1
                    WHERE `Command_Log`.`Recording_Sessions_recording_session_id` = %(recording_session_id)s
                    AND `Command_Log`.`command_state`='Pending'
                '''
        print stmt
        with self.lock:
            try:
                self.cursor.execute(stmt, row_recording_session)
                self.db.commit()
            except mysql.connector.Error as err:
                print("MySQL Error: {}".format(err))
                syslog.syslog(syslog.LOG_DEBUG, "MySQL Error: {}".format(err))

        if commands:
            syslog.syslog(syslog.LOG_DEBUG, 'Retrieved pending commands "{}"'.format(str(commands)))
        return commands

    def start_command(self, command):
        # Insert the new command state
        stmt = '''
             INSERT INTO `stepSATdb_Flight`.`Command_Log` (`time_of_command`, `Recording_Sessions_recording_session_id`,`command`,
                `command_state`, `command_data`, `priority`, `source`, `read_from_sv`, `pushed_to_ground`, `command_id`)
                VALUES (NOW(),%(session)s,%(command)s,'Processing',%(data)s,%(priority)s,%(source)s,1, 1, %(command_id)s)
                        ON DUPLICATE KEY UPDATE `Command_Log`.`read_from_sv` = 1 , `Command_Log`.`command_state` = 'Processing'
        '''

        with self.lock:
            try:
                self.cursor.execute(stmt, command)
                self.db.commit()
            except mysql.connector.Error as err:
                print("MySQL Error: {}".format(err))
                syslog.syslog(syslog.LOG_DEBUG, "MySQL Error: {}".format(err))

    def complete_commands(self, commands, success=False, message=None):
        syslog.syslog(syslog.LOG_DEBUG, 'Completing commands "{}"/{}/"{}"'.format(str(commands), success, message))
        if message:
            if isinstance(message, list):
                message = ''.join(message)
        if success:
            state = 'Success'
            if message:
                log = 'Command Success:\n' + message
            else:
                log = 'Command Success'
        else:
            state = 'FAIL'
            if message:
                log = 'Command Failed:\n' + message
            else:
                log = 'Command Failed'

        # transform the command list
        cmd_keys = ['time', 'id', 'data', 'session', 'command', 'data', 'priority', 'source', 'command_id']
        if isinstance(commands, dict) and set(cmd_keys).issubset(set(commands.keys())):
            # if the command is a dictionary with keys of 'time', 'id', 'data',
            # and 'session', turn this into a list with one element.
            update_cmds = [(commands['session'], commands['command'], state, commands['data'], commands['priority'], commands['source'], commands['command_id'])]
        elif isinstance(commands, dict):
            update_cmds = [(commands['session'], commands['command'], state, commands['data'], commands['priority'], commands['source'], commands['command_id'], c) for c in itertools.chain(commands.items())]
        else:  # if isinstance(commands, list):
            update_cmds = [(commands['session'], commands['command'], state, commands['data'], commands['priority'], commands['source'], commands['command_id']) for c in commands]
        syslog.syslog(syslog.LOG_DEBUG, 'Updating stepSATdb_Flight.Command_Log with commands "{}"'.format(str(update_cmds)))

        # Now that the command is complete, update the "pushed_to_ground" flag
        # to let the final commmad state be sent to the ground.

        stmt = '''
             INSERT INTO `stepSATdb_Flight`.`Command_Log` (`time_of_command`, `Recording_Sessions_recording_session_id`,`command`,
                `command_state`, `command_data`, `priority`, `source`, `read_from_sv`, `pushed_to_ground`, `command_id`)
                VALUES (NOW(),%s,%s,%s,%s,%s,%s,1, 1, %s)
                        ON DUPLICATE KEY UPDATE `Command_Log`.`read_from_sv` = 1 , `Command_Log`.`command_state` = 'FAIL'
        '''

        with self.lock:
            try:
                self.cursor.executemany(stmt, update_cmds)
                self.db.commit()
            except mysql.connector.Error as err:
                print("MySQL Error: {}".format(err))
                syslog.syslog(syslog.LOG_DEBUG, "MySQL Error: {}".format(err))

        self._log_msg(log)

    def set_application_state(self, app, state, status, msg):
        # syslog.syslog(syslog.LOG_DEBUG, 'Updating app status "{}"/{}/{}/{}'.format(str(app), state, status, msg))
        stmt = '''
            INSERT INTO `stepSATdb_Flight`.`System_Applications_State` (`application_id`, `application_state`, `application_status`)
                VALUES (%(id)s, %(state)s, %(status)s )
        '''
        # Add the state and status message to the app so that we can use named
        # parameters in the query
        if isinstance(app, dict):
            params = app.copy()
        else:
            params = {'id': app}
        params['state'] = state
        params['status'] = status

        with self.lock:
            try:
                self.cursor.execute(stmt, params)
                self.db.commit()
            except mysql.connector.Error as err:
                print("MySQL Error: {}".format(err))
                syslog.syslog(syslog.LOG_DEBUG, "MySQL Error: {}".format(err))

        # Log more detail
        if msg:
            self._log_msg(msg)

    def retrieve_command_logs(self, session=None, timestamp=None):
        return self.retrieve_data('Command_Log', 'time_of_command', session, timestamp)

    def retrieve_system_messages(self, session=None, timestamp=None):
        return self.retrieve_data('System_Messages', 'event_time', session, timestamp)

    def retrieve_flight_data(self, session=None, timestamp=None):
        return self.retrieve_data('Flight_Data', 'time_stamp', session, timestamp)

    def retrieve_data(self, table, column, session=None, timestamp=None):
        if session:
            stmt = '''
                SELECT * FROM `stepSATdb_Flight`.`{table}`
                    WHERE `{table}`.`Recording_Sessions_recording_session_id`=%(session)s
                    ORDER BY `{table}`.`{column}` DESC
            '''.format(table=table, column=column)
        elif timestamp:
            stmt = '''
                SELECT * FROM `stepSATdb_Flight`.`{table}`
                    WHERE `{table}`.`{column}`>%(timestamp)s
                    ORDER BY `{table}`.`{column}` DESC
            '''.format(table=table, column=column)
        else:
            stmt = '''
                SELECT * FROM `stepSATdb_Flight`.`{table}`
                    ORDER BY `{table}`.`{column}` DESC
            '''.format(table=table, column=column)

        with self.lock:
            try:
                self.cursor.execute(stmt, dict(session=session, timestamp=timestamp))
                if self.cursor.with_rows:
                    # Get the maximum timestamp from the first row (because of the
                    # ORDER BY ... DESC clause) and return it with the results.
                    ret = self.cursor.fetchall()
                    return (self.cursor.fetchall(), ret[0][column])
                else:
                    # Return an empty list and 'None' for the timestamp
                    return ([], None)
            except mysql.connector.Error as err:
                print("MySQL Error: {}".format(err))
                syslog.syslog(syslog.LOG_DEBUG, "MySQL Error: {}".format(err))

    def retrieve_command_log_poll_rate(self):
        # Get the latest state poll rate values
        return self.retrieve_push_poll_rate('command_poll_rate')

    def retrieve_command_log_push_rate(self):
        # Get the latest state push rate values
        return self.retrieve_push_poll_rate('command_push_rate')

    def retrieve_data_download_push_rate(self):
        # Get the latest state push rate values
        return self.retrieve_push_poll_rate('data_download_push_rate')

    def retrieve_command_syslog_push_rate(self):
        # TODO: replace with reference to real system message push rate
        # Get the latest state push rate values
        return self.retrieve_push_poll_rate('command_syslog_push_rate')

    def retrieve_binary_data_push_rate(self):
        return self.retrieve_push_poll_rate('binary_data_push_rate')

    def retrieve_push_poll_rate(self, column):
        # Get the latest state push/poll rate values
        stmt = '''
            SELECT `Recording_Session_State`.`{}`,`Recording_Session_State`.`state_index`
                FROM `stepSATdb_Flight`.`Recording_Session_State`
                ORDER BY `Recording_Session_State`.`state_index` DESC
                LIMIT 1
        '''.format(column)

        with self.lock:
            self.cursor.execute(stmt)
            row = self.cursor.fetchone()

        if row:
            return row[column]
        else:
            return None

    def ls_duplex_installed_state(self):
        return self.retrieve_linkstar_duplex_info('radio_installed')

    def retrieve_linkstar_duplex_info(self, column):
        # Get the requested linkstar duplex radio information
        stmt = '''
            SELECT `LinkStar_Duplex_Information`.`{}`
                FROM `stepSATdb_Flight`.`LinkStar_Duplex_Information`
        '''.format(column)

        with self.lock:
            try:
                self.cursor.execute(stmt)
                row = self.cursor.fetchone()
            except mysql.connector.Error as err:
                print("MySQL Error: {}".format(err))
                syslog.syslog(syslog.LOG_DEBUG, "MySQL Error: {}".format(err))

        if row:
            return row[column]
        else:
            return None

    def ls_simplexstx3_installed_state(self):
        # return self.retrieve_linkstar_simplexstx3_info('radio_installed')
        return self.retrieve_linkstar_simplex_info('radio_installed')

    def retrieve_linkstar_simplex_info(self, column):
        # Get the requested linkstar simplex radio information
        stmt = '''
            SELECT `LinkStar_Simplex_Information`.`{}`
                FROM `stepSATdb_Flight`.`LinkStar_Simplex_Information`
        '''.format(column)

        with self.lock:
            try:
                self.cursor.execute(stmt)
                row = self.cursor.fetchone()
            except mysql.connector.Error as err:
                print("MySQL Error: {}".format(err))
                syslog.syslog(syslog.LOG_DEBUG, "MySQL Error: {}".format(err))

        if row:
            return row[column]
        else:
            return None

    def update_ls_location_info(self):
        # Get the current recording_session_id
        stmt = '''
                SELECT *
                    FROM `stepSATdb_Flight`.`Recording_Sessions`
                    ORDER BY `Recording_Sessions`.`recording_session_id` DESC LIMIT 1
             '''
        with self.lock:
            try:
                self.cursor.execute(stmt)
                row_recording_session = self.cursor.fetchone()
            except mysql.connector.Error as err:
                print("MySQL Error: {}".format(err))
                syslog.syslog(syslog.LOG_DEBUG, "MySQL Error: {}".format(err))

        # Get the most recent LinkStar_Duplex_State
        with self.lock:
            try:
                self.cursor.execute('''
                    SELECT *
                        FROM `stepSATdb_Flight`.`LinkStar_Duplex_State`
                             WHERE `LinkStar_Duplex_State`.`Recording_Sessions_recording_session_id`= %(recording_session_id)s
                             ORDER BY `LinkStar_Duplex_State`.`event_key` DESC LIMIT 1
                ''', row_recording_session)
                row_LinkStar_Duplex_State = self.cursor.fetchone()
                # Write the LinkStar location information into the Location_Data table
                self.cursor.execute('''
                   INSERT INTO `stepSATdb_Flight`.`Location_Data` (`recording_session_id`,`latitude`, `longitude`,
                        `time_recorded`, `timestamp_source`, `data_source`, `position_error`) VALUES (
                         %(Recording_Sessions_recording_session_id)s, %(latitude)s, %(longitude)s, %(time_recorded)s, %(time_of_day)s, 'LINKSTAR1', %(position_error)s )
                ''', row_LinkStar_Duplex_State)
                self.db.commit()
            except mysql.connector.Error as err:
                print("MySQL Error: {}".format(err))
                syslog.syslog(syslog.LOG_DEBUG, "MySQL Error: {}".format(err))

    def increment_session(self):
        # pylint: disable=too-many-statements
        # First increment and create new recording session
        with self.lock:

            self.cursor.execute('''
                INSERT INTO `stepSATdb_Flight`.`Recording_Sessions` (`datetime_created`) VALUES ( NOW() )
                            ''')
            self.db.commit()

            # Get the new recording_session_id and then post in the
            # Recording_Sessions_State table

            stmt = '''
                SELECT *
                    FROM `stepSATdb_Flight`.`Recording_Sessions`
                    ORDER BY `Recording_Sessions`.`recording_session_id` DESC LIMIT 1
             '''
            self.cursor.execute(stmt)
            row_recording_session = self.cursor.fetchone()

            stmt = '''
                SELECT *
                    FROM `stepSATdb_Flight`.`Recording_Session_State`
                    ORDER BY `Recording_Session_State`.`Recording_Sessions_recording_session_id` DESC
                    LIMIT 1
            '''
            self.cursor.execute(stmt)
            row_recording_session_state = self.cursor.fetchone()

            row_recording_session_state['Recording_Sessions_recording_session_id'] = row_recording_session['recording_session_id']

            self.cursor.execute('''
               INSERT INTO `stepSATdb_Flight`.`Recording_Session_State` (`state_index`, `current_mode`,
                    `current_flight_phase`, `data_download_push_rate`, `command_poll_rate`, `command_syslog_push_rate`,
                    `ethernet_link_state`, `serial_link_state`, `active_board`, `last_FRNCS_sync`,
                    `test_connection`, `FRNCS_contact`, `active_ground_server`, `Recording_Sessions_recording_session_id`, `selected_server`, `connection_type`, `gateway_ip_address`, `use_wired_link`, `selected_ground_server`, `binary_data_push_rate`, `flight_data_num_records_download`, `flight_data_object_num_records_download`,  `flight_data_binary_num_records_download`,  `command_log_num_records_download`,  `system_messages_num_records_download`,  `sync_to_ground`,
                    `command_push_rate`, `linkstar_duplex_state_num_records_download`, `location_data_num_records_download`) VALUES (
                     %(state_index)s, %(current_mode)s,
                    %(current_flight_phase)s, %(data_download_push_rate)s, %(command_poll_rate)s, %(command_syslog_push_rate)s,
                    %(ethernet_link_state)s, %(serial_link_state)s, %(active_board)s, %(last_FRNCS_sync)s,
                    %(test_connection)s, %(FRNCS_contact)s, %(active_ground_server)s, %(Recording_Sessions_recording_session_id)s, %(selected_server)s, %(connection_type)s, %(gateway_ip_address)s, %(use_wired_link)s, %(selected_ground_server)s, %(binary_data_push_rate)s, %(flight_data_num_records_download)s, %(flight_data_object_num_records_download)s, %(flight_data_binary_num_records_download)s, %(command_log_num_records_download)s, %(system_messages_num_records_download)s, %(sync_to_ground)s, %(command_push_rate)s,
                    %(linkstar_duplex_state_num_records_download)s, %(location_data_num_records_download)s )
            ''', row_recording_session_state)
            self.db.commit()

            # Create a new record in Flight_Pointers to coincide with the new
            # recording_session_id.

            stmt = '''
               SELECT *
                 FROM `stepSATdb_Flight`.`Flight_Pointers`
                 ORDER BY `Flight_Pointers`.`Recording_Sessions_recording_session_id` DESC LIMIT 1
             '''
            self.cursor.execute(stmt)
            row_flight_pointers = self.cursor.fetchone()

            row_flight_pointers['Recording_Sessions_recording_session_id'] = row_recording_session['recording_session_id']
            self.cursor.execute('''
               INSERT INTO `stepSATdb_Flight`.`Flight_Pointers` (`Recording_Sessions_recording_session_id`, `flight_data_event_key`,
                    `flight_data_binary_event_key`, `flight_data_object_event_key`, `system_messages_event_key`, `linkstar_duplex_state_event_key` ) VALUES (
                     %(Recording_Sessions_recording_session_id)s, %(flight_data_event_key)s,
                    %(flight_data_binary_event_key)s, %(flight_data_object_event_key)s, %(system_messages_event_key)s, %(linkstar_duplex_state_event_key)s )
            ''', row_flight_pointers)
            self.db.commit()

            # Update LinkStar Duplex information - the new recording_session_id information
            stmt = '''
                SELECT *
                    FROM `stepSATdb_Flight`.`LinkStar_Duplex_Information`
                    ORDER BY `LinkStar_Duplex_Information`.`esn` DESC LIMIT 1
             '''
            self.cursor.execute(stmt)
            row_linkStar_duplex_information = self.cursor.fetchone()

            row_linkStar_duplex_information['current_recording_session'] = row_recording_session['recording_session_id']
            self.cursor.execute('''
                UPDATE `stepSATdb_Flight`.`LinkStar_Duplex_Information`
                    SET `LinkStar_Duplex_Information`.`current_recording_session` = %(current_recording_session)s
                    WHERE `LinkStar_Duplex_Information`.`esn` = %(esn)s
            ''', row_linkStar_duplex_information)
            self.db.commit()

            #  With a new Recording_Session_State we need to download it to the ground station.
            if not os.path.exists('/opt/qs/tmp'):
                os.mkdir('/opt/qs/tmp')

            uid = pwd.getpwnam("mysql").pw_uid
            gid = grp.getgrnam("mysql").gr_gid

            if not os.stat('/opt/qs/tmp').st_uid == uid:
                os.chown('/opt/qs/tmp', uid, gid)

            if os.path.exists('/opt/qs/tmp/Recording_Session_State.csv'):
                os.remove('/opt/qs/tmp/Recording_Session_State.csv')

            stmt = '''
                SELECT * FROM `stepSATdb_Flight`.`Recording_Session_State` INTO OUTFILE '/opt/qs/tmp/Recording_Session_State.csv'
                       FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"' ESCAPED BY '\\\\' LINES TERMINATED BY '\n'
           '''
            with self.lock:
                self.cursor.execute(stmt)

            # set flag to indicate file is ready for download
            stmt_write_pointer = '''
                UPDATE `stepSATdb_Flight`.`Flight_Pointers`
                    SET `Flight_Pointers`.`recording_session_state_rt` = 1
                        WHERE `Flight_Pointers`.`Recording_Sessions_recording_session_id`=(
                            SELECT MAX(`Recording_Sessions`.`recording_session_id`)
                                FROM `stepSATdb_Flight`.`Recording_Sessions` LIMIT 1)
            '''
            with self.lock:
                self.cursor.execute(stmt_write_pointer)

            # ---- The time the last sync of the data occurred with the ground ----
            stmt_write_timesync = '''
                UPDATE `stepSATdb_Flight`.`Recording_Session_State`
                    SET `Recording_Session_State`.`last_FRNCS_sync` = NOW() ORDER BY Recording_Sessions_recording_session_id DESC LIMIT 1
            '''
            with self.lock:
                self.cursor.execute(stmt_write_timesync)

            #  Since a new Flight_Pointers record was created this needs to be added to the ground station.
            if not os.path.exists('/opt/qs/tmp'):
                os.mkdir('/opt/qs/tmp')

            uid = pwd.getpwnam("mysql").pw_uid
            gid = grp.getgrnam("mysql").gr_gid

            if not os.stat('/opt/qs/tmp').st_uid == uid:
                os.chown('/opt/qs/tmp', uid, gid)

            if os.path.exists('/opt/qs/tmp/Flight_Pointers.csv'):
                os.remove('/opt/qs/tmp/Flight_Pointers.csv')

            stmt = '''
                SELECT * FROM `stepSATdb_Flight`.`Flight_Pointers` INTO OUTFILE '/opt/qs/tmp/Flight_Pointers.csv'
                       FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"' ESCAPED BY '\\\\' LINES TERMINATED BY '\n'
            '''
            with self.lock:
                self.cursor.execute(stmt)

            # set flag to indicate file is ready for download
            stmt_write_pointer = '''
                UPDATE `stepSATdb_Flight`.`Flight_Pointers`
                    SET `Flight_Pointers`.`flight_pointers_rt` = 1
                        WHERE `Flight_Pointers`.`Recording_Sessions_recording_session_id`=(
                            SELECT MAX(`Recording_Sessions`.`recording_session_id`)
                                FROM `stepSATdb_Flight`.`Recording_Sessions` LIMIT 1)
            '''
            with self.lock:
                self.cursor.execute(stmt_write_pointer)

            # ---- The time the last sync of the data occurred with the ground ----
            stmt_write_timesync = '''
                UPDATE `stepSATdb_Flight`.`Recording_Session_State`
                    SET `Recording_Session_State`.`last_FRNCS_sync` = NOW() ORDER BY Recording_Sessions_recording_session_id DESC LIMIT 1
            '''
            with self.lock:
                self.cursor.execute(stmt_write_timesync)

    def get_db_ground_args(self):
        # Retrieve ground server identifying information
        stmt = '''
           SELECT *
               FROM `stepSATdb_Flight`.`QS_Servers` LIMIT 1
        '''
        with self.lock:
            self.cursor.execute(stmt)
            all_servers = self.cursor.fetchone()

        if all_servers['selected_server'] == 'TEST':
            selected_server = {
                'server': all_servers['test_server'],
                'username': all_servers['test_username'],
                'password': all_servers['test_password'],
                'fileserver_username': all_servers['fileserver_username'],
                'fileserver_password': all_servers['fileserver_password'],
                'fileserver_pathname': all_servers['fileserver_pathname'],
            }
        elif all_servers['selected_server'] == 'PRIMARY':
            selected_server = {
                'server': all_servers['primary_server'],
                'username': all_servers['primary_username'],
                'password': all_servers['primary_password'],
                'fileserver_username': all_servers['fileserver_username'],
                'fileserver_password': all_servers['fileserver_password'],
                'fileserver_pathname': all_servers['fileserver_pathname'],
            }
        elif all_servers['selected_server'] == 'ALTERNATE':
            selected_server = {
                'server': all_servers['alternate_server'],
                'username': all_servers['alternate_username'],
                'password': all_servers['alternate_password'],
                'fileserver_username': all_servers['fileserver_username'],
                'fileserver_password': all_servers['fileserver_password'],
                'fileserver_pathname': all_servers['fileserver_pathname'],
            }
        elif all_servers['selected_server'] == 'NONE':
            selected_server = {
                'server': '',
                'username': '',
                'password': '',
                'fileserver_username': '',
                'fileserver_password': '',
                'fileserver_pathname': '',
            }
        else:
            return None
        # print selected_server
        return selected_server

    def sync_selected_db_table(self, selected_table_name):
        # ----Get event_key number from Flight_Pointers table ----
        # print "test"
        stmt_event_key = '''
            SELECT `{}_event_key`, `{}_rt` FROM `stepSATdb_Flight`.`Flight_Pointers`
                WHERE `Flight_Pointers`.`Recording_Sessions_recording_session_id`=(
                    SELECT MAX(`Recording_Sessions`.`recording_session_id`)
                        FROM `stepSATdb_Flight`.`Recording_Sessions` LIMIT 1)
        '''.format(string.lower(selected_table_name), string.lower(selected_table_name))
        print stmt_event_key
        print "******"
        with self.lock:
            self.cursor.execute(stmt_event_key)
            row_flight_pointers_data = self.cursor.fetchall()
            row_flight_pointers = row_flight_pointers_data[0]
            print '{}_event_key'.format(string.lower(selected_table_name))
            event_key = row_flight_pointers['{}_event_key'.format(string.lower(selected_table_name))]
            file_flag = row_flight_pointers['{}_rt'.format(string.lower(selected_table_name))]
        print event_key
        print file_flag
        if file_flag == 0 and event_key > 0:

            print "Writing table ****"

            if not os.path.exists('/opt/qs/tmp'):
                os.mkdir('/opt/qs/tmp')

            uid = pwd.getpwnam("mysql").pw_uid
            gid = grp.getgrnam("mysql").gr_gid
            if not os.stat('/opt/qs/tmp').st_uid == uid:
                os.chown('/opt/qs/tmp', uid, gid)

            if os.path.exists('/opt/qs/tmp/{}.csv'.format(selected_table_name)):
                os.remove('/opt/qs/tmp/{}.csv'.format(selected_table_name))

            # ----Get number of records to download from Recording_Session_State table----
            stmt_num_records = '''
                SELECT `{}_num_records_download` FROM `stepSATdb_Flight`.`Recording_Session_State`
                    WHERE `Recording_Session_State`.`Recording_Sessions_recording_session_id`=(
                        SELECT MAX(`Recording_Sessions`.`recording_session_id`)
                            FROM `stepSATdb_Flight`.`Recording_Sessions` LIMIT 1)
            '''.format(string.lower(selected_table_name))
            print stmt_num_records
            with self.lock:
                self.cursor.execute(stmt_num_records)
                num_records = self.cursor.fetchone()

            # ----Formulate the statement to write the selected table to the file----
            print "outfile write ***"
            stmt_data_write = '''
                SELECT * FROM `stepSATdb_Flight`.`{}` WHERE event_key>={} LIMIT {} INTO OUTFILE '/opt/qs/tmp/{}.csv'
                    FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"' ESCAPED BY '\\\\' LINES TERMINATED BY '\n'
            '''.format(selected_table_name, event_key, num_records['{}_num_records_download'.format(string.lower(selected_table_name))], selected_table_name)
            # print stmt_data_write
            with self.lock:
                # pylint: disable=bare-except
                try:
                    self.cursor.execute(stmt_data_write)
                except KeyboardInterrupt as e:
                    raise e
                except:
                    # TODO: consider writing to syslog or message log
                    pass

            # ----Update the event_key pointer for next upload ----
            stmt_highest_pointer = '''SELECT MAX(`event_key`) AS 'pointer' FROM `stepSATdb_Flight`.`{}`'''.format(selected_table_name)
            # print stmt_highest_pointer
            with self.lock:
                self.cursor.execute(stmt_highest_pointer)
                highest_pointer = self.cursor.fetchone()

            last_used_key = (event_key + num_records['{}_num_records_download'.format(string.lower(selected_table_name))])
            if highest_pointer['pointer'] <= last_used_key:
                new_event_key = highest_pointer['pointer']
            else:
                new_event_key = last_used_key

            # set flag to indicate file is ready for download and update pointer
            stmt_write_pointer = '''
                UPDATE `stepSATdb_Flight`.`Flight_Pointers`
                    SET `Flight_Pointers`.`{}_event_key` = {}, `Flight_Pointers`.`{}_rt` = 1
                        WHERE `Flight_Pointers`.`Recording_Sessions_recording_session_id`=(
                            SELECT MAX(`Recording_Sessions`.`recording_session_id`)
                                FROM `stepSATdb_Flight`.`Recording_Sessions` LIMIT 1)
            '''.format(string.lower(selected_table_name), new_event_key, string.lower(selected_table_name))
            print stmt_write_pointer
            with self.lock:
                self.cursor.execute(stmt_write_pointer)

        # ---- The time the last sync of the data occurred with the ground ----
            stmt_write_timesync = '''
                UPDATE `stepSATdb_Flight`.`Recording_Session_State`
                    SET `Recording_Session_State`.`last_FRNCS_sync` = NOW() ORDER BY Recording_Sessions_recording_session_id DESC LIMIT 1
            '''
            with self.lock:
                self.cursor.execute(stmt_write_timesync)
            # This case means we just created a file from the table and it is ready to be downloaded
            return True
        elif event_key == 0:
            # This case means table has NO data, no file was generated and there is nothing to download
            return False
        else:
            # This case means table the previous generated file has NOT been downloaded yet; try and communicate with the ground again.
            return True

    def reset_sync_flag(self, selected_table_name):
        # set flag to indicate file is ready to be deleted and a new one written; the old file was written to the ground
        stmt_update_flag = '''
            UPDATE `stepSATdb_Flight`.`Flight_Pointers`
                SET `Flight_Pointers`.`{}_rt` = 0
                    WHERE `Flight_Pointers`.`Recording_Sessions_recording_session_id`=(
                        SELECT MAX(`Recording_Sessions`.`recording_session_id`)
                            FROM `stepSATdb_Flight`.`Recording_Sessions` LIMIT 1)
        '''.format(string.lower(selected_table_name))
        # print stmt_update_flag
        with self.lock:
            self.cursor.execute(stmt_update_flag)

    def sync_recording_sessions(self):
        # ----Get file usage flag from Flight_Pointers table ----
        stmt_flag_key = '''
            SELECT `recording_sessions_rt` FROM `stepSATdb_Flight`.`Flight_Pointers`
                WHERE `Flight_Pointers`.`Recording_Sessions_recording_session_id`=(
                    SELECT MAX(`Recording_Sessions`.`recording_session_id`)
                        FROM `stepSATdb_Flight`.`Recording_Sessions` LIMIT 1)
        '''
        with self.lock:
            self.cursor.execute(stmt_flag_key)
            row_flight_pointers = self.cursor.fetchone()
            file_flag = row_flight_pointers['recording_sessions_rt']

        if file_flag == 0:

            if not os.path.exists('/opt/qs/tmp'):
                os.mkdir('/opt/qs/tmp')

            uid = pwd.getpwnam("mysql").pw_uid
            gid = grp.getgrnam("mysql").gr_gid

            if not os.stat('/opt/qs/tmp').st_uid == uid:
                os.chown('/opt/qs/tmp', uid, gid)

            if os.path.exists('/opt/qs/tmp/recording_sessions.csv'):
                os.remove('/opt/qs/tmp/recording_sessions.csv')

            stmt = '''
                SELECT * FROM `stepSATdb_Flight`.`Recording_Sessions` INTO OUTFILE '/opt/qs/tmp/recording_sessions.csv'
                   FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"' ESCAPED BY '\\\\' LINES TERMINATED BY '\n'
                '''
            with self.lock:
                self.cursor.execute(stmt)

            # set flag to indicate file is ready for download
            stmt_write_pointer = '''
                UPDATE `stepSATdb_Flight`.`Flight_Pointers`
                    SET `Flight_Pointers`.`recording_sessions_rt` = 1
                        WHERE `Flight_Pointers`.`Recording_Sessions_recording_session_id`=(
                            SELECT MAX(`Recording_Sessions`.`recording_session_id`)
                                FROM `stepSATdb_Flight`.`Recording_Sessions` LIMIT 1)
            '''
            with self.lock:
                self.cursor.execute(stmt_write_pointer)

            # ---- The time the last sync of the data occurred with the ground ----
            stmt_write_timesync = '''
                UPDATE `stepSATdb_Flight`.`Recording_Session_State`
                    SET `Recording_Session_State`.`last_FRNCS_sync` = NOW() ORDER BY Recording_Sessions_recording_session_id DESC LIMIT 1
            '''
            with self.lock:
                self.cursor.execute(stmt_write_timesync)
        return True

    def sync_recording_session_state(self):
        # ----Get file usage flag from Flight_Pointers table ----
        stmt_flag_key = '''
            SELECT `recording_session_state_rt` FROM `stepSATdb_Flight`.`Flight_Pointers`
                WHERE `Flight_Pointers`.`Recording_Sessions_recording_session_id`=(
                    SELECT MAX(`Recording_Sessions`.`recording_session_id`)
                        FROM `stepSATdb_Flight`.`Recording_Sessions` LIMIT 1)
        '''
        with self.lock:
            self.cursor.execute(stmt_flag_key)
            row_flight_pointers = self.cursor.fetchone()
            file_flag = row_flight_pointers['recording_session_state_rt']

        if file_flag == 0:

            if not os.path.exists('/opt/qs/tmp'):
                os.mkdir('/opt/qs/tmp')

            uid = pwd.getpwnam("mysql").pw_uid
            gid = grp.getgrnam("mysql").gr_gid

            if not os.stat('/opt/qs/tmp').st_uid == uid:
                os.chown('/opt/qs/tmp', uid, gid)

            if os.path.exists('/opt/qs/tmp/Recording_Session_State.csv'):
                os.remove('/opt/qs/tmp/Recording_Session_State.csv')

            stmt = '''
                SELECT * FROM `stepSATdb_Flight`.`Recording_Session_State` INTO OUTFILE '/opt/qs/tmp/Recording_Session_State.csv'
                   FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"' ESCAPED BY '\\\\' LINES TERMINATED BY '\n'
                '''
            with self.lock:
                self.cursor.execute(stmt)

            # set flag to indicate file is ready for download
            stmt_write_pointer = '''
                UPDATE `stepSATdb_Flight`.`Flight_Pointers`
                    SET `Flight_Pointers`.`recording_session_state_rt` = 1
                        WHERE `Flight_Pointers`.`Recording_Sessions_recording_session_id`=(
                            SELECT MAX(`Recording_Sessions`.`recording_session_id`)
                                FROM `stepSATdb_Flight`.`Recording_Sessions` LIMIT 1)
            '''
            with self.lock:
                self.cursor.execute(stmt_write_pointer)

            # ---- The time the last sync of the data occurred with the ground ----
            stmt_write_timesync = '''
                UPDATE `stepSATdb_Flight`.`Recording_Session_State`
                    SET `Recording_Session_State`.`last_FRNCS_sync` = NOW() ORDER BY Recording_Sessions_recording_session_id DESC LIMIT 1
            '''
            with self.lock:
                self.cursor.execute(stmt_write_timesync)
        return True

    def sync_flight_pointers(self):
        # ----Get file usage flag from Flight_Pointers table ----
        stmt_flag_key = '''
            SELECT `flight_pointers_rt` FROM `stepSATdb_Flight`.`Flight_Pointers`
                WHERE `Flight_Pointers`.`Recording_Sessions_recording_session_id`=(
                    SELECT MAX(`Recording_Sessions`.`recording_session_id`)
                        FROM `stepSATdb_Flight`.`Recording_Sessions` LIMIT 1)
        '''
        with self.lock:
            self.cursor.execute(stmt_flag_key)
            row_flight_pointers = self.cursor.fetchone()
            file_flag = row_flight_pointers['flight_pointers_rt']

        if file_flag == 0:

            if not os.path.exists('/opt/qs/tmp'):
                os.mkdir('/opt/qs/tmp')

            uid = pwd.getpwnam("mysql").pw_uid
            gid = grp.getgrnam("mysql").gr_gid

            if not os.stat('/opt/qs/tmp').st_uid == uid:
                os.chown('/opt/qs/tmp', uid, gid)

            if os.path.exists('/opt/qs/tmp/Flight_Pointers.csv'):
                os.remove('/opt/qs/tmp/Flight_Pointers.csv')

            stmt = '''
                SELECT * FROM `stepSATdb_Flight`.`Flight_Pointers` INTO OUTFILE '/opt/qs/tmp/Flight_Pointers.csv'
                   FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"' ESCAPED BY '\\\\' LINES TERMINATED BY '\n'
                '''
            with self.lock:
                self.cursor.execute(stmt)

            # set flag to indicate file is ready for download
            stmt_write_pointer = '''
                UPDATE `stepSATdb_Flight`.`Flight_Pointers`
                    SET `Flight_Pointers`.`flight_pointers_rt` = 1
                        WHERE `Flight_Pointers`.`Recording_Sessions_recording_session_id`=(
                            SELECT MAX(`Recording_Sessions`.`recording_session_id`)
                                FROM `stepSATdb_Flight`.`Recording_Sessions` LIMIT 1)
            '''
            with self.lock:
                self.cursor.execute(stmt_write_pointer)

            # ---- The time the last sync of the data occurred with the ground ----
            stmt_write_timesync = '''
                UPDATE `stepSATdb_Flight`.`Recording_Session_State`
                    SET `Recording_Session_State`.`last_FRNCS_sync` = NOW() ORDER BY Recording_Sessions_recording_session_id DESC LIMIT 1
            '''
            with self.lock:
                self.cursor.execute(stmt_write_timesync)
        return True

#    def read_command_log(self):
#        # Returns the appropriate rows of the sv db
#        stmt = '''
#            SELECT *
#                FROM `stepSATdb_Flight`.`Command_Log`
#                    WHERE `Command_Log`.`command_state`='Pending-Ground'
#                    AND `Command_Log`.`Recording_Sessions_recording_session_id`=(
#                        SELECT MAX(`Recording_Sessions`.`recording_session_id`)
#                            FROM `stepSATdb_Flight`.`Recording_Sessions`)
#        '''
#        with self.lock:
#            self.cursor.execute(stmt)
#            commands = self.cursor.fetchall()
#            # print commands
#        return commands
#
    def add_sv_command_log(self, commands):
        # adds row(s) to sv command_log
        if commands:
            for row in commands:
                stmt = '''
                    INSERT INTO `stepSATdb_Flight`.`Command_Log` (`time_of_command`, `Recording_Sessions_recording_session_id`,`command`,
                        `command_state`, `command_data`, `priority`, `source`, `read_from_sv`, `pushed_to_ground`, `command_id`)
                        VALUES (%(time_of_command)s,%(Recording_Sessions_recording_session_id)s,%(command)s,%(command_state)s,%(command_data)s,%(priority)s,%(source)s,1, 1, %(command_id)s)
                        ON DUPLICATE KEY UPDATE `Command_Log`.`read_from_sv` = 1 , `Command_Log`.`command_state` = %(command_state)s
                '''
                with self.lock:
                    try:
                        self.cursor.execute(stmt, row)
                        self.db.commit()
                    except mysql.connector.Error as err:
                        print("MySQL Error: {}".format(err))
                        syslog.syslog(syslog.LOG_DEBUG, "MySQL Error: {}".format(err))
                # Add new command state -> Pending
                stmt = '''
                    INSERT INTO `stepSATdb_Flight`.`Command_Log` (`time_of_command`, `Recording_Sessions_recording_session_id`,`command`,
                        `command_state`, `command_data`, `priority`, `source`, `read_from_sv`, `pushed_to_ground`, `command_id`)
                        VALUES (NOW(),%(Recording_Sessions_recording_session_id)s,%(command)s,'Pending',%(command_data)s,%(priority)s,%(source)s,0, 0, %(command_id)s)
                        ON DUPLICATE KEY UPDATE `Command_Log`.`read_from_sv` = 1 , `Command_Log`.`command_state` = 'Pending'
                '''
                with self.lock:
                    try:
                        self.cursor.execute(stmt, row)
                        self.db.commit()
                    except mysql.connector.Error as err:
                        print("MySQL Error: {}".format(err))
                        syslog.syslog(syslog.LOG_DEBUG, "MySQL Error: {}".format(err))

    def update_sv_command_log(self, commands):
        # updates relevant row(s) in sv command log
        if commands:
            for row in commands:
                stmt = '''
                    UPDATE `stepSATdb_Flight`.`Command_Log`
                        SET `Command_Log`.`pushed_to_ground` = 1
                            WHERE `Command_Log`.`Recording_Sessions_recording_session_id` = %(Recording_Sessions_recording_session_id)s
                            AND `Command_Log`.`time_of_command` = %(time_of_command)s
                '''
                with self.lock:
                    try:
                        self.cursor.execute(stmt, row)
                        self.db.commit()
                    except mysql.connector.Error as err:
                        print("MySQL Error: {}".format(err))
                        syslog.syslog(syslog.LOG_DEBUG, "MySQL Error: {}".format(err))

    def check_test_connection(self):
        stmt = '''
            SELECT `Recording_Session_State`.`test_connection`
                FROM `stepSATdb_Flight`.`Recording_Session_State`
                WHERE `Recording_Session_State`.`Recording_Sessions_recording_session_id`=(
                    SELECT MAX(`Recording_Sessions`.`recording_session_id`)
                        FROM `stepSATdb_Flight`.`Recording_Sessions`
                )
            LIMIT 1
        '''
        # print stmt
        with self.lock:
            self.cursor.execute(stmt)
            results = self.cursor.fetchone()

        connection = results['test_connection']
        return connection

    def read_system_applications(self):
        # Returns the System_Application rows of the sv db
        stmt = '''
            SELECT *
                FROM `stepSATdb_Flight`.`System_Applications`
        '''
        with self.lock:
            try:
                self.cursor.execute(stmt)
                system_applications_data = self.cursor.fetchall()
                # print commands
            except mysql.connector.Error as err:
                print("MySQL Error: {}".format(err))
                syslog.syslog(syslog.LOG_DEBUG, "MySQL Error: {}".format(err))
        return system_applications_data

#    def change_system_application_state(self, app_id, app_state, app_status, app_locked, app_installed):
#        # changes the state of the System_Application
#        stmt = '''
#            UPDATE `stepSATdb_Flight`.`System_Applications`
#                SET `System_Applications`.`locked_flag` = %s, `System_Applications`.`target_board_installed` = %s
#                    WHERE `System_Applications`.`application_id` = %s
#        '''
#        with self.lock:
#            try:
#                self.cursor.execute(stmt, (app_locked, app_installed, app_id))
#                self.db.commit()
#            except mysql.connector.Error as err:
#                print("MySQL Error: {}".format(err))
#                syslog.syslog(syslog.LOG_DEBUG, "MySQL Error: {}".format(err))
#
#        # Then update the app state
#        self.set_application_state(app_id, app_state, app_status, None)
        
    def get_last_command_date(self, command_state_value):
        # Get the date of the last Pending-Ground command
        stmt = '''
            SELECT `Command_Log`.`time_of_command` FROM `Command_Log` WHERE `Command_Log`.`command_state` = '{}' ORDER BY `event_key` DESC LIMIT 1
        '''.format(command_state_value)
        print stmt
        row = ''
        with self.lock:
            try:
                self.cursor.execute(stmt)
                row = self.cursor.fetchone()
            except mysql.connector.Error as err:
                print("MySQL Error: {}".format(err))
                syslog.syslog(syslog.LOG_DEBUG, "MySQL Error: {}".format(err))

        if row:
            return row['time_of_command']
        else:
            return None

