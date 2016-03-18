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

class linkstar(object):
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

#    Radio monitoring functions
#
    def get_radio_status(self):
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
            if sync_to_ground == 1:      
                self.connect_to_ground(status)
            else:
                
                #print "adfwfr"
                stmt = '''
                    UPDATE `stepSATdb_Flight`.`Recording_Session_State`
                        SET test_connection=0
                        WHERE `Recording_Session_State`.`Recording_Sessions_recording_session_id`=(
                            SELECT MAX(`Recording_Sessions`.`recording_session_id`)
                                FROM `stepSATdb_Flight`.`Recording_Sessions`
                        )
                '''
                self.cursor.execute(stmt)
                self.db.commit()

    def connect_to_ground(self, status):
        print "connect_to_ground entered"

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

        #print connected
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
        

            
            
    
