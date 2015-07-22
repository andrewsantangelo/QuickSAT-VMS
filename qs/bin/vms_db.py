#!/usr/bin/env python

import syslog
import itertools
import sys
import radio_status
import subprocess
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

# utility function to test connection to server
def ping(address):
    args = ['ping', '-c1', address]
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
                
    def get_db_ground_args(self):
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
        
        return selected_server            
        
    def sync_selected_db_table(self):
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
        
        if os.path.exists('/opt/qs/tmp/retrieve_flight_data_object.csv'):
            os.remove('/opt/qs/tmp/retrieve_flight_data_object.csv')
            
        stmt_event_key = '''
            SELECT `flight_data_object_event_key` FROM `stepSATdb_Flight`.`Flight_Pointers`    
                WHERE `Flight_Pointers`.`Recording_Sessions_recording_session_id`=(
                    SELECT MAX(`Recording_Sessions`.`recording_session_id`)
                        FROM `stepSATdb_Flight`.`Recording_Sessions` LIMIT 1)
        '''
        stmt_num_records = '''
            SELECT `flight_data_object_num_records_download` FROM `stepSATdb_Flight`.`Recording_Session_State`    
                WHERE `Recording_Session_State`.`Recording_Sessions_recording_session_id`=(
                    SELECT MAX(`Recording_Sessions`.`recording_session_id`)
                        FROM `stepSATdb_Flight`.`Recording_Sessions` LIMIT 1)
        '''
        stmt_data_write = '''
            SELECT * FROM `stepSATdb_Flight`.`Flight_Data_Object` LIMIT %s,%s INTO OUTFILE '/opt/qs/tmp/retrieve_flight_data_object.csv' 
               FIELDS TERMINATED BY ',' OPTIONALLY ENCLOSED BY '"' ESCAPED BY '\\\\' LINES TERMINATED BY '\n'
        '''
        stmt_pointer_update = '''
            SELECT MAX FROM `Flight_Data_Object`.`event_key` LIMIT %s, %s 
        '''
        stmt_write_pointer = '''
            UPDATE `stepSATdb_Flight`.`Flight_Pointers`
                SET `Flight_Pointers`.`flight_data_object_event_key` = %s
                    WHERE `Flight_Pointers`.`Recording_Sessions_recording_session_id`=(
                        SELECT MAX(`Recording_Sessions`.`recording_session_id`)
                            FROM `stepSATdb_Flight`.`Recording_Sessions` LIMIT 1)
        '''
        with self.lock:
            self.cursor.execute(stmt_event_key)
            event_key = self.cursor.fetchone()
            
            self.cursor.execute(stmt_num_records)
            num_records = self.cursor.fetchone()
            
            try:
                self.cursor.execute(stmt_data_write, (event_key['flight_data_object_event_key'], num_records['flight_data_object_num_records_download']))
                self.cursor.execute(stmt_pointer_update, (event_key['flight_data_object_event_key'], num_records['flight_data_object_num_records_download']))
                pointer_update = self.cursor.fetchone()
                self.cursor.execute(stmt_write_pointer, (pointer_update['event_key'] + 1))
            except:
                # TODO: consider writing to syslog or message log
                

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

        if not connected:
            syslog.syslog(syslog.LOG_DEBUG, 'Server connection = {}, method = {}, call state = {}'.format(connected, method, status['CALL STATE']))
            if method == 'Ethernet':
                connected = False
                with open('/sys/class/net/eth0/carrier') as f:
                    connected = (1 == int(f.read()))
            elif method == 'LinkStar':
                if status['CALL STATE'] == 'TIA_PPP_MDT': 
                    connected = True
                elif status['CALL STATE'] == 'IDLE' or not status['CALL STATE']:
                    (avail, rssi) = self.radio.is_service_available()
                    syslog.syslog(syslog.LOG_DEBUG, 'LinkStar service avail = {}, rssi = {}'.format(avail, rssi))
                    if avail:
                        connected = self.call('777')
                        syslog.syslog(syslog.LOG_DEBUG, 'call result = {}'.format(connected))
                        # If we were able to connect, wait about 10 seconds so we can
                        # ping immediately
                        if connected:
                            time.sleep(10)
            else:
                self._log_msg('Unsupported ground connection method: {}'.format(method))

        if connected:
            server_state = ping(server_address)

            #update db with newly discovered server state
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
    
