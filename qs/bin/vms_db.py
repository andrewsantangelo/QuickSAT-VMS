#!/usr/bin/env python

import syslog
import itertools
import sys
import radio_status
import subprocess

# To connect to the QS/VMS database, install with
#   $ pip install MySQL-python
# but that requires other libraries, so it is recommended to install with this
# command, and then install the mysql connector package:
#   $ sudo apt-get install python-mysqldb
#   $ pip install mysql-connector-python
# install pip as described here:
#   https://pypi.python.org/pypi/setuptools
import mysql.connector

# utility function to test connection to server
def ping(address):
    args = ['ping', '-c1', address]
    f = open('/dev/null', 'w')
    return (0 == subprocess.call(args, stdout=f))

class vms_db(object):
    def __init__(self, address, port, cert, username, password, dbname, **kwargs):
        self.db = None
        self.cursor = None
        self.config = {
            'user': username,
            'password': password,
            'host': address,
            'port': port,
            'database': dbname,
            'ssl_ca': cert
        }
        if not self.config['ssl_ca']:
            del self.config['ssl_ca']         
        self.open()
        self.radio = radio_status.gsp1720()
        self.ppp = None

    def __del__(self):
        self.close()

    def _execute(self, stmt, args=None):
        """
        simple function to allow executing unusual statements
        """
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
        try:
            self.cursor.execute(stmt, (msg,))
            self.db.commit()
        except:
            syslog.syslog(syslog.LOG_ERR, 'Error logging message "{}": {}'.format(msg, sys.exc_info()[1]))

    def open(self):
        if not self.db:
            self.db = mysql.connector.connect(**self.config)

        if self.db and not self.cursor:
            self.cursor = self.db.cursor(dictionary=True)


    def close(self):
        if self.cursor:
            self.cursor.close()

        if self.db:
            self.db.close()

    def getapps(self):
        # Extract the application ID and name from the 'System_Applications'
        # table, and the parameter ID from the 'Parameter_ID_Table'
        stmt = '''
            SELECT `System_Applications`.`application_id` AS id,
                    `System_Applications`.`application_name` AS name,
                    `System_Applications`.`virtual_machine_id` AS vm,
                    `System_Applications`.`application_state` AS state,
                    `System_Applications`.`Configuration_Parts_part_key` AS part,
                    `System_Applications`.`Configuration_Parts_Configuration_configuration_key` AS config,
                    `System_Applications`.`Configuration_Parts_Configuration_Mission_mission_key` AS mission,
                    `Parameter_ID_Table`.`parameter_id` AS param
                FROM `stepSATdb_Flight`.`System_Applications`
                LEFT JOIN `stepSATdb_Flight`.`Parameter_ID_Table`
                ON `System_Applications`.`application_id` = `Parameter_ID_Table`.`System_Applications_application_id`
        '''
        self.cursor.execute(stmt)
        apps = self.cursor.fetchall()
        syslog.syslog(syslog.LOG_DEBUG, 'Retrieved applications "{}"'.format(str(apps)))
        return apps

    def all_pending_commands(self):
        stmt = '''
            SELECT `Command_Log`.`command` AS command,
                    `Command_Log`.`time_of_command` AS time,
                    `Command_Log`.`Recording_Sessions_recording_session_id` AS id,
                    `Command_Log`.`command_data` AS data,
                    `Command_Log`.`Recording_Sessions_recording_session_id` AS session,
                    `Command_Log`.`priority` AS priority,
                    `Command_Log`.`source` AS source
                FROM `stepSATdb_Flight`.`Command_Log`
                WHERE `Command_Log`.`command_state`='Pending'
                    AND `Command_Log`.`Recording_Sessions_recording_session_id`=(
                        SELECT MAX(`Recording_Sessions`.`recording_session_id`)
                            FROM `stepSATdb_Flight`.`Recording_Sessions`
                    )
        '''
        self.cursor.execute(stmt)
        commands = {}
        for row in self.cursor:
            cmd = row.pop('command')
            if cmd not in commands:
                commands[cmd] = []
            commands[cmd].append(row)
        if commands:
            syslog.syslog(syslog.LOG_DEBUG, 'Retrieved pending commands "{}"'.format(str(commands)))
        return commands

    def filter_pending_commands(self, cmd):
        stmt = '''
            SELECT `Command_Log`.`time_of_command` AS time,
                    `Command_Log`.`Recording_Sessions_recording_session_id` AS id,
                    `Command_Log`.`command_data` AS data,
                    `Command_Log`.`Recording_Sessions_recording_session_id` AS session,
                    `Command_Log`.`priority` AS priority,
                    `Command_Log`.`source` AS source                    
                FROM `stepSATdb_Flight`.`Command_Log`
                WHERE `Command_Log`.`command`=%s
                    AND `Command_Log`.`command_state`='Pending'
                    AND `Command_Log`.`Recording_Sessions_recording_session_id`=(
                        SELECT MAX(`Recording_Sessions`.`recording_session_id`)
                            FROM `stepSATdb_Flight`.`Recording_Sessions`
                    )
        '''
        self.cursor.execute(stmt, (cmd,))
        commands = self.cursor.fetchall()
        syslog.syslog(syslog.LOG_DEBUG, 'Retrieved pending "{}" commands "{}"'.format(cmd, str(commands)))
        return commands

    def pending_remove_commands(self):
        return self.filter_pending_commands('REMOVE')

    def pending_add_commands(self):
        return self.filter_pending_commands('ADD')

    def pending_stop_commands(self):
        return self.filter_pending_commands('STOP')

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
            state = 'Fail'
            log = 'Command Failed:\n' + message

        # transform the command list
        cmd_keys = ['time', 'id', 'data', 'session']
        if isinstance(commands, dict) and set(cmd_keys).issubset(set(commands.keys())):
            # if the command is a dictionary with keys of 'time', 'id', 'data',
            # and 'session', turn this into a list with one element.
            update_cmds = [(state, commands['time'], commands['session'])]
        elif isinstance(commands, dict):
            update_cmds = [(state, c['time'], c['session']) for c in itertools.chain(commands.items())]
        else: # if isinstance(commands, list):
            update_cmds = [(state, c['time'], c['session']) for c in commands]
        syslog.syslog(syslog.LOG_DEBUG, 'Updating stepSATdb_Flight.Command_Log with commands "{}"'.format(str(update_cmds)))

        # Identify if there are any pending "ADD" commands
        stmt = '''
            UPDATE `stepSATdb_Flight`.`Command_Log`
                SET `Command_Log`.`command_state`=%s
                WHERE `Command_Log`.`time_of_command`=%s
                    AND `Command_Log`.`Recording_Sessions_recording_session_id`=%s
        '''
        self.cursor.executemany(stmt, update_cmds)
        self.db.commit()

        self._log_msg(log)

    def set_application_state(self, app, state, status, msg):
        syslog.syslog(syslog.LOG_DEBUG, 'Updating app status "{}"/{}/{}/{}'.format(str(app), state, status, msg))
        stmt = '''
            UPDATE `stepSATdb_Flight`.`System_Applications`
                SET `System_Applications`.`application_state`=%(state)s,
                    `System_Applications`.`application_status`=%(status)s
                WHERE `System_Applications`.`application_id`=%(id)s
                    AND `System_Applications`.`Configuration_Parts_part_key`=%(part)s
                    AND `System_Applications`.`Configuration_Parts_Configuration_configuration_key`=%(config)s
                    AND `System_Applications`.`Configuration_Parts_Configuration_Mission_mission_key`=%(mission)s
        '''
        # Add the state and status message to the app so that we can use named
        # parameters in the query
        params = app.copy()
        params['state'] = state
        params['status'] = status
        self.cursor.execute(stmt, params)
        self.db.commit()

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
        self.cursor.execute(stmt, dict(session=session, timestamp=timestamp))
        if self.cursor.with_rows:
            # Get the maximum timestamp from the first row (because of the
            # ORDER BY ... DESC clause) and return it with the results.
            ret = self.cursor.fetchall()
            return (self.cursor.fetchall(), ret[0][column])
        else:
            # Return an empty list and 'None' for the timestamp
            return ([], None)

    def retrieve_command_poll_rate(self):
        # Get the latest state poll rate values
        return self.retrieve_poll_rate('command_poll_rate')

    def retrieve_flight_data_poll_rate(self):
        # Get the latest state poll rate values
        return self.retrieve_poll_rate('data_download_poll_rate')

    def retrieve_cmd_log_poll_rate(self):
        # Get the latest state poll rate values
        return self.retrieve_poll_rate('command_syslog_poll_rate')

    def retrieve_system_msgs_poll_rate(self):
        # TODO: replace with reference to real system message poll rate
        # Get the latest state poll rate values
        return self.retrieve_poll_rate('command_syslog_poll_rate')

    def retrieve_poll_rate(self, column):
        # Get the latest state poll rate values
        stmt = '''
            SELECT `Recording_Session_State`.`{}`,`Recording_Session_State`.`state_index`
                FROM `stepSATdb_Flight`.`Recording_Session_State`
                ORDER BY `Recording_Session_State`.`state_index` DESC
                LIMIT 1
        '''.format(column)
        self.cursor.execute(stmt)
        row = self.cursor.fetchone()
        if row:
            return row[column]
        else:
            return None

    def increment_session(self):
    
#
#       First increment and create new recording session
#    
        self.cursor.execute('''
            INSERT INTO `stepSATdb_Flight`.`Recording_Sessions` (`datetime_created`) VALUES ( NOW() )
                        ''')
        self.db.commit()

#
#       Get the new recording_session_id and then post in the Recording_Sessions_State table 

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
                `current_flight_phase`, `data_download_poll_rate`, `command_poll_rate`, `command_syslog_poll_rate`, 
                `ethernet_link_state`, `serial_link_state`, `active_board`, `last_FRNCS_sync`, 
                `test_connection`, `FRNCS_contact`, `active_ground_server`, `Recording_Sessions_recording_session_id`, `selected_server`) VALUES ( 
                 %(state_index)s, %(current_mode)s, 
                %(current_flight_phase)s, %(data_download_poll_rate)s, %(command_poll_rate)s, %(command_syslog_poll_rate)s, 
                %(ethernet_link_state)s, %(serial_link_state)s, %(active_board)s, %(last_FRNCS_sync)s, 
                %(test_connection)s, %(FRNCS_contact)s, %(active_ground_server)s, %(Recording_Sessions_recording_session_id)s, %(selected_server)s )
                        ''', row_recording_session_state)   
        self.db.commit()

        return None
        
        
        
#
#    Radio monitoring functions
#

    def get_radio_status(self):
        status = {
            'N': 'error',
            'W': 'error',
            'TIME': 'error',
            'ERR': 'error',
            'CALL TYPE': ' ',
            'CALL DURATION': '',
            'NUMBER': '',
            'PROVIDER' : '',
            'SERVICE AVAILABLE': '',
            'SERVICE MODE': '',
            'CALL STATE' : '',
            'REGISTRATION' : '',
            'RSSI' : '0',
            'ROAMING' : 'NO',
            'GATEWAY' : '0',
            'recording_session_id' : '0',
            'esn': '11111111'
        }         
        status.update(self.radio.get_status()[1])         
        status.update(self.radio.get_location()[1])         
        
        stmt = '''
            SELECT `recording_session_id` 
                FROM `stepSATdb_Flight`.`Recording_Sessions`
                ORDER BY `Recording_Sessions`.`recording_session_id` DESC LIMIT 1
         '''
        self.cursor.execute(stmt)
        row_recording_session = self.cursor.fetchone()        
        
        status.update(row_recording_session)         
        
        stmt = '''
            SELECT `esn` 
                FROM `stepSATdb_Flight`.`LinkStar_Duplex_Information` LIMIT 1
         '''
        self.cursor.execute(stmt)
        row_esn = self.cursor.fetchone()
        status.update(row_esn)  
        print(str(status)) 
        
        self.cursor.execute('''
           INSERT INTO `stepSATdb_Flight`.`LinkStar_Duplex_State` (`esn`, `call_type`, 
                `call_duration`, `call_number`, `provider`, `service_available`, 
                `service_mode`, `call_state`, `registration`, `rssi`, 
                `roaming`, `gateway`, `Recording_Sessions_recording_session_id`, `time_of_day`, `latitude`, `longitude`, `position_error`) VALUES ( 
                 %(esn)s, %(CALL TYPE)s, 
                %(CALL DURATION)s, %(NUMBER)s, %(PROVIDER)s, %(SERVICE AVAILABLE)s, 
                %(SERVICE MODE)s, %(CALL STATE)s, %(REGISTRATION)s, %(RSSI)s, 
                %(ROAMING)s, %(GATEWAY)s, %(recording_session_id)s, %(TIME)s, 
                %(N)s, %(W)s, %(ERR)s )
                        ''', status)   
        self.db.commit()                                
        self.connect_to_ground()

    def connect_to_ground(self):
        # look up server address and connect method (eth or linkstar), and current connection state
        
        stmt = '''
            SELECT `Recording_Session_State`.`test_connection`,
                   `Recording_Session_State`.`connection_type`
                FROM `stepSATdb_Flight`.`Recording_Session_State`
                WHERE `Recording_Session_State`.`Recording_Sessions_recording_session_id`=(
                    SELECT MAX(`Recording_Sessions`.`recording_session_id`)
                        FROM `stepSATdb_Flight`.`Recording_Sessions`
                )
            LIMIT 1
        '''
        self.cursor.execute(stmt)
        results = self.cursor.fetchone()
        connected = results['test_connection']
        method = results['connection_type']
        
        if connected == 0:
            stmt = '''
                SELECT `Ground_Server`.`test_server`
                    FROM `stepSATdb_Flight`.`Ground_Server`
                    WHERE `Ground_Server`.`ground_server_index` = 1
                LIMIT 1
            '''
            self.cursor.execute(stmt)
            results = self.cursor.fetchone()
            server_address = results['test_server']

            if method == 'Ethernet':
                connected = True
            elif method == 'LinkStar':
                if status['CALL STATE'] == 'TIA_PPP_MDT': 
                    connected = True
                elif status['CALL STATE'] == 'IDLE':
                    connected = self.call('777')
                    # If we were able to connect, wait about 10 seconds so we can
                    # ping immediately
                    if connected:
                        time.sleep(10)
            else:
                # Error?
                pass

            if connected:
                server_state = ping(server_address)

            #update db with newly discovered server state
            stmt = '''
                UPDATE `stepSATdb_Flight`.`Recording_Session_State`
                    SET test_connection=1 
                    WHERE `Recording_Session_State`.`Recording_Sessions_recording_session_id`=(
                        SELECT MAX(`Recording_Sessions`.`recording_session_id`)
                            FROM `stepSATdb_Flight`.`Recording_Sessions`
                    )
            '''
                    
            self.cursor.execute(stmt)
            self.db.commit()
                
             
    def call(self, number):
        (status, msg) = self.radio.call(number)
        if status:
            args = [ '/usr/sbin/pppd', '/dev/ttyO2', '19200', 'noauth', 'defaultroute', 'persist', 'maxfail', '0', 'crtscts', 'local' ]
            self.ppp = subprocess.Popen(args)
        else:
            self._log_msg('Failed to call #{}: {}'.format(number, msg))

        return status
      
    def hangup(self):
        # pkill pppd would could also work
        if self.ppp:
                self.ppp.kill()
                    
        self.radio.hangup()
    
