#!/usr/bin/env python

import syslog
import itertools
import sys
import radio_status
import subprocess
import threading
import string
import time
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

# utility function to test connection to server
def ping(address, method):
    if method == 'Ethernet':
        args = ['ping', '-c1', '-I', 'eth0', address]
    elif method == 'LinkStar':
        args = ['ping', '-c1', '-I', 'ppp0', address]
    f = open('/dev/null', 'w')
    return (0 == subprocess.call(args, stdout=f))

class vms_db(object):
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
        
        with self.lock:
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
                    `Command_Log`.`source` AS source,
                    `Command_Log`.`priority` AS priority
                FROM `stepSATdb_Flight`.`Command_Log`
                WHERE `Command_Log`.`command_state`='Pending'
                    AND `Command_Log`.`Recording_Sessions_recording_session_id`=(
                        SELECT MAX(`Recording_Sessions`.`recording_session_id`)
                            FROM `stepSATdb_Flight`.`Recording_Sessions`
                    )
        '''
        
        with self.lock:
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
                    `Command_Log`.`source` AS source ,
                    `Command_Log`.`priority` AS priority
                FROM `stepSATdb_Flight`.`Command_Log`
                WHERE `Command_Log`.`command`=%s
                    AND `Command_Log`.`command_state`='Pending'
                    AND `Command_Log`.`Recording_Sessions_recording_session_id`=(
                        SELECT MAX(`Recording_Sessions`.`recording_session_id`)
                            FROM `stepSATdb_Flight`.`Recording_Sessions`
                    )
        '''
        
        with self.lock:
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
            if message:
                log = 'Command Failed:\n' + message
            else:
                log = 'Command Failed'

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
        
        
        with self.lock:
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
        
        
        with self.lock:
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
            
        
        with self.lock:
            self.cursor.execute(stmt, dict(session=session, timestamp=timestamp))
            if self.cursor.with_rows:
                # Get the maximum timestamp from the first row (because of the
                # ORDER BY ... DESC clause) and return it with the results.
                ret = self.cursor.fetchall()
                return (self.cursor.fetchall(), ret[0][column])
            else:
                # Return an empty list and 'None' for the timestamp
                return ([], None)
        

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

    def increment_session(self):
    
#
#       First increment and create new recording session
#    
        
        with self.lock:
        
            self.cursor.execute('''
                INSERT INTO `stepSATdb_Flight`.`Recording_Sessions` (`datetime_created`) VALUES ( NOW() )
                            ''')
            self.db.commit()

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
                    `current_flight_phase`, `data_download_push_rate`, `command_poll_rate`, `command_syslog_push_rate`,
                    `ethernet_link_state`, `serial_link_state`, `active_board`, `last_FRNCS_sync`,
                    `test_connection`, `FRNCS_contact`, `active_ground_server`, `Recording_Sessions_recording_session_id`, `selected_server`, `connection_type`, `gateway_ip_address`, `use_wired_link`, `selected_ground_server`, `binary_data_push_rate`, `flight_data_num_records_download`, `flight_data_object_num_records_download`,  `flight_data_binary_num_records_download`,  `command_log_num_records_download`,  `system_messages_num_records_download`,  `sync_to_ground`,  `command_push_rate`) VALUES (
                     %(state_index)s, %(current_mode)s,
                    %(current_flight_phase)s, %(data_download_push_rate)s, %(command_poll_rate)s, %(command_syslog_push_rate)s,
                    %(ethernet_link_state)s, %(serial_link_state)s, %(active_board)s, %(last_FRNCS_sync)s,
                    %(test_connection)s, %(FRNCS_contact)s, %(active_ground_server)s, %(Recording_Sessions_recording_session_id)s, %(selected_server)s, %(connection_type)s, %(gateway_ip_address)s, %(use_wired_link)s, %(selected_ground_server)s, %(binary_data_push_rate)s, %(flight_data_num_records_download)s, %(flight_data_object_num_records_download)s, %(flight_data_binary_num_records_download)s, %(command_log_num_records_download)s, %(system_messages_num_records_download)s, %(sync_to_ground)s, %(command_push_rate)s )
            ''', row_recording_session_state)
            self.db.commit()
        
         #
         #      Create a new record in Flight_Pointers to coincide with the new recording_session_id.
         #

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
                    `flight_data_binary_event_key`, `flight_data_object_event_key`, `system_messages_event_key` ) VALUES (
                     %(Recording_Sessions_recording_session_id)s, %(flight_data_event_key)s,
                    %(flight_data_binary_event_key)s, %(flight_data_object_event_key)s, %(system_messages_event_key)s )
            ''', row_flight_pointers)
            self.db.commit()

        return None
        
            
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
                'password': all_servers['test_password']
            }
        elif all_servers['selected_server'] == 'PRIMARY':
            selected_server = {
                'server': all_servers['primary_server'],
                'username': all_servers['primary_username'],
                'password': all_servers['primary_password']
            } 
        elif all_servers['selected_server'] == 'ALTERNATE':
            selected_server = {
                'server': all_servers['alternate_server'],
                'username': all_servers['alternate_username'],
                'password': all_servers['alternate_password']
            } 
        elif all_servers['selected_server'] == 'NONE':
            selected_server = {
                 'server': '',
                 'username': '',
                 'password': ''
            } 
        else:
             return None
        #print selected_server
        return selected_server            
        
    
    def sync_selected_db_table(self, selected_table_name):
        import os
        import os.path
        import pwd
        import grp
        
        if not os.path.exists('/opt/qs/tmp'):
            os.mkdir('/opt/qs/tmp')
        
        uid = pwd.getpwnam("mysql").pw_uid
        gid = grp.getgrnam("mysql").gr_gid
        if not os.stat('/opt/qs/tmp').st_uid == uid:
            os.chown('/opt/qs/tmp', uid, gid)
        
        if os.path.exists('/opt/qs/tmp/{}.csv'.format(selected_table_name)):
            os.remove('/opt/qs/tmp/{}.csv'.format(selected_table_name))
            
        #----Get event_key number from Flight_Pointers table ----
        #print "test" 
        stmt_event_key = '''
            SELECT `{}_event_key` FROM `stepSATdb_Flight`.`Flight_Pointers`    
                WHERE `Flight_Pointers`.`Recording_Sessions_recording_session_id`=(
                    SELECT MAX(`Recording_Sessions`.`recording_session_id`)
                        FROM `stepSATdb_Flight`.`Recording_Sessions` LIMIT 1)
        '''.format(string.lower(selected_table_name))
        with self.lock:
            self.cursor.execute(stmt_event_key)
            event_key = self.cursor.fetchone()
        
        #----Get number of records to download from Recording_Session_State table----
        stmt_num_records = '''
            SELECT `{}_num_records_download` FROM `stepSATdb_Flight`.`Recording_Session_State`    
                WHERE `Recording_Session_State`.`Recording_Sessions_recording_session_id`=(
                    SELECT MAX(`Recording_Sessions`.`recording_session_id`)
                        FROM `stepSATdb_Flight`.`Recording_Sessions` LIMIT 1)
        '''.format(string.lower(selected_table_name))
        with self.lock:
            self.cursor.execute(stmt_num_records)
            num_records = self.cursor.fetchone()

        #----Formulate the statement to write the selected table to the file----
        stmt_data_write = '''
            SELECT * FROM `stepSATdb_Flight`.`{}` LIMIT {},{} INTO OUTFILE '/opt/qs/tmp/{}.csv' 
               FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"' ESCAPED BY '\\\\' LINES TERMINATED BY '\n'
        '''.format(selected_table_name, event_key['{}_event_key'.format(string.lower(selected_table_name))], num_records['{}_num_records_download'.format(string.lower(selected_table_name))], selected_table_name)
        with self.lock:
            try:
                self.cursor.execute(stmt_data_write)
            except:
                # TODO: consider writing to syslog or message log
                pass
        
        #----Update the event_key pointer for next upload ----
        stmt_highest_pointer = '''SELECT MAX(`event_key`) AS 'pointer' FROM `stepSATdb_Flight`.`{}`'''.format(selected_table_name)
        with self.lock:
            self.cursor.execute(stmt_highest_pointer)
            highest_pointer = self.cursor.fetchone()
            
        last_used_key = (event_key['{}_event_key'.format(string.lower(selected_table_name))] + num_records['{}_num_records_download'.format(string.lower(selected_table_name))])
        if highest_pointer['pointer'] <=  last_used_key:
            new_event_key = highest_pointer['pointer'] 
        else:
            new_event_key = last_used_key 
        
        stmt_write_pointer = '''
            UPDATE `stepSATdb_Flight`.`Flight_Pointers`
                SET `Flight_Pointers`.`{}_event_key` = {}
                    WHERE `Flight_Pointers`.`Recording_Sessions_recording_session_id`=(
                        SELECT MAX(`Recording_Sessions`.`recording_session_id`)
                            FROM `stepSATdb_Flight`.`Recording_Sessions` LIMIT 1)
        '''.format(string.lower(selected_table_name), new_event_key)
        with self.lock:
            self.cursor.execute(stmt_write_pointer)
            
    def sync_recording_sessions(self):
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

    def read_command_log(self):
    # Returns the appropriate rows of the sv db
        stmt = '''
            SELECT *
                FROM `stepSATdb_Flight`.`Command_Log`
                    WHERE `Command_Log`.`pushed_to_ground`!='1'
                    AND `Command_Log`.`Recording_Sessions_recording_session_id`=(
                        SELECT MAX(`Recording_Sessions`.`recording_session_id`)
                            FROM `stepSATdb_Flight`.`Recording_Sessions`)
        '''
        with self.lock:
            self.cursor.execute(stmt)
            commands = self.cursor.fetchall()
            #print commands
        return commands
        
    def add_sv_command_log(self, commands):
    # adds row(s) to sv command_log
        if commands:
            for row in commands:
                stmt = '''
                    INSERT INTO `stepSATdb_Flight`.`Command_Log` (`time_of_command`, `Recording_Sessions_recording_session_id`,`command`,
                        `command_state`, `command_data`, `priority`, `source`, `read_from_sv`, `pushed_to_ground`)
                        VALUES (%(time_of_command)s,%(Recording_Sessions_recording_session_id)s,%(command)s,%(command_state)s,%(command_data)s,%(priority)s,%(source)s,1, 1)
                        ON DUPLICATE KEY UPDATE `Command_Log`.`read_from_sv` = 1 , `Command_Log`.`command_state` = %(command_state)s
                '''
            with self.lock:
                self.cursor.execute(stmt, row)
                self.db.commit()

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
                    self.cursor.execute(stmt, row)
                    self.db.commit()
        
#    Radio monitoring functions
#
    def get_radio_status(self):
        status = {
            'N': 'error',
            'W': 'error',
            'TIME': 'error',
            'ERR': 'error',
            'CALL TYPE': '',
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
            'esn': '11111111',
            'time_recorded':''
        }         
        status.update(self.radio.get_status()[1])         
        status.update(self.radio.get_location()[1])         
        
        stmt = '''
            SELECT `recording_session_id` 
                FROM `stepSATdb_Flight`.`Recording_Sessions`
                ORDER BY `Recording_Sessions`.`recording_session_id` DESC LIMIT 1
        '''
        
        with self.lock:
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
            
            self.cursor.execute('''
               INSERT INTO `stepSATdb_Flight`.`LinkStar_Duplex_State` (`esn`, `call_type`, 
                    `call_duration`, `call_number`, `provider`, `service_available`, 
                    `service_mode`, `call_state`, `registration`, `rssi`, 
                    `roaming`, `gateway`, `Recording_Sessions_recording_session_id`, `time_of_day`, `latitude`, `longitude`, `position_error`,`time_recorded`) VALUES ( 
                     %(esn)s, %(CALL TYPE)s, 
                    %(CALL DURATION)s, %(NUMBER)s, %(PROVIDER)s, %(SERVICE AVAILABLE)s, 
                    %(SERVICE MODE)s, %(CALL STATE)s, %(REGISTRATION)s, %(RSSI)s, 
                    %(ROAMING)s, %(GATEWAY)s, %(recording_session_id)s, %(TIME)s, 
                    %(N)s, %(W)s, %(ERR)s, NOW() )
                            ''', status)   
            self.db.commit()              
        self.connect_to_ground(status)
            
        

    def connect_to_ground(self, status):
        print "connect_to_ground entered"
        stmt = '''
            SELECT `Recording_Session_State`.`sync_to_ground`
                FROM `stepSATdb_Flight`.`Recording_Session_State`
                WHERE `Recording_Session_State`.`Recording_Sessions_recording_session_id`=(
                    SELECT MAX(`Recording_Sessions`.`recording_session_id`)
                        FROM `stepSATdb_Flight`.`Recording_Sessions`
                ) LIMIT 1
        '''
        with self.lock:
            self.cursor.execute(stmt)
            results = self.cursor.fetchone()
        sync_to_ground = results['sync_to_ground']
    
        if sync_to_ground == 1:
            # look up server address and connect method (eth or linkstar), and current connection state
    
            stmt = '''
                SELECT `Recording_Session_State`.`test_connection`,
                       `Recording_Session_State`.`connection_type`,
                       `Recording_Session_State`.`selected_server`
                    FROM `stepSATdb_Flight`.`Recording_Session_State`
                    WHERE `Recording_Session_State`.`Recording_Sessions_recording_session_id`=(
                        SELECT MAX(`Recording_Sessions`.`recording_session_id`)
                            FROM `stepSATdb_Flight`.`Recording_Sessions`
                    )
                LIMIT 1
            '''

            with self.lock:
                self.cursor.execute(stmt)
                results = self.cursor.fetchone()
                connected = results['test_connection']
                method = results['connection_type']
                selected_server = results['selected_server']
                if selected_server == 'PRIMARY':
                   stmt = '''
                    SELECT `QS_Servers`.`primary_server`
                           FROM `stepSATdb_Flight`.`QS_Servers`
                       LIMIT 1
                   '''    
                elif selected_server == 'ALTERNATE':
                   stmt = '''
                       SELECT `QS_Servers`.`alternative_server`
                           FROM `stepSATdb_Flight`.`QS_Servers`
                       LIMIT 1
                   '''
                elif selected_server == 'TEST':
                   stmt = '''
                       SELECT `QS_Servers`.`test_server`
                           FROM `stepSATdb_Flight`.`QS_Servers`
                       LIMIT 1
                   '''
                else:
                   stmt = '''
                       SELECT `QS_Servers`.`test_server`
                           FROM `stepSATdb_Flight`.`QS_Servers`
                       LIMIT 1
                   '''
                self.cursor.execute(stmt)
                results = self.cursor.fetchone()
    
                if selected_server == 'PRIMARY':
                   server_address = results['primary_server']
                elif selected_server == 'ALTERNATE':
                   server_address = results['alternative_server']
                elif selected_server == 'TEST':
                   server_address = results['test_server']
                else:
                   server_address = results['test_server']           
            #print method

            if not connected:
                syslog.syslog(syslog.LOG_DEBUG, 'Server connection = {}, method = {}, call state = {}'.format(connected, method, status['CALL STATE']))
                if method == 'Ethernet':
                    connected = False
                    with open('/sys/class/net/eth0/carrier') as f:
                        connected = (1 == int(f.read()))
                elif method == 'LinkStar':
                    with self.radio.lock:
                        #print 'service available: {}'.format(status['SERVICE AVAILABLE'])
                        if status['CALL STATE'] == 'TIA_PPP_MDT': 
                            connected = True
                        elif status['CALL STATE'] == 'IDLE' or not status['CALL STATE']:
                            (avail, rssi, roaming) = self.radio.is_service_available()
                            syslog.syslog(syslog.LOG_DEBUG, 'LinkStar service avail = {}, rssi = {}, roaming = {}'.format(avail, rssi, roaming))
                            if avail and roaming == 'NO':
                                connected = self.call('777')
                                syslog.syslog(syslog.LOG_DEBUG, 'call result = {}'.format(connected))
                                # If we were able to connect, wait about 10 seconds so we can
                                # ping immediately
                                if connected:
                                    time.sleep(10)
                else:
                    self._log_msg('Unsupported ground connection method: {}'.format(method))

            if connected:
                print 'pinging'
                if method == 'Ethernet':
                    server_state = ping(server_address, method)
                elif method == 'LinkStar':
                    with self.radio.lock:
                        server_state = ping(server_address, method)
                #print 'server state = {}'.format(server_state)

                #update db with newly discovered ground connection state
                stmt = '''
                    UPDATE `stepSATdb_Flight`.`Recording_Session_State`
                        SET test_connection=%s
                        WHERE `Recording_Session_State`.`Recording_Sessions_recording_session_id`=(
                            SELECT MAX(`Recording_Sessions`.`recording_session_id`)
                                FROM `stepSATdb_Flight`.`Recording_Sessions`
                        )
                '''
                with self.lock:
                    self.cursor.execute(stmt, (server_state,))
                    self.db.commit()
             
    def call(self, number):
        with self.radio.lock:
            (status, msg) = self.radio.call(number)
            if status:
                args = [ '/usr/sbin/pppd', '/dev/ttyO2', '19200', 'noauth', 'defaultroute', 'persist', 'maxfail', '1', 'crtscts', 'local' ]
                self.ppp = subprocess.Popen(args)
            else:
                self._log_msg('Failed to call #{}: {}'.format(number, msg))

            return status
      
    def hangup(self):
        with self.radio.lock:
            # pkill pppd would could also work
            if self.ppp:
                    self.ppp.kill()
                    
            self.radio.hangup()
        
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
        
        with self.lock:
            self.cursor.execute(stmt)
            results = self.cursor.fetchone()
            
        connection = results['test_connection']
        return connection
            
            
    
