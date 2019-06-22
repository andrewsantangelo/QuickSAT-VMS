#!/usr/bin/env python
"""
Module that handles the core QS/VMS processing actions.
"""
import threading
import traceback
import sys
import time
import datetime
import json
import syslog
import importlib
import operator
import multiprocessing
import subprocess

import vms_db
import periodic_timer
import vms_db_ground
import ls_comm_flight_stream
import linkstar
import linkstarstx3
import vms_gps
import vms_gps_novatel
import ctypes
import ctypes.util
from random import randint

# Disable some pylint warnings that I don't care about
# pylint: disable=line-too-long,fixme,invalid-name,too-many-public-methods,too-many-arguments
#
# TEMPORARY:
# pylint: disable=missing-docstring


# DEFINE GLOBAL VARIBLE to track when time is set.  One set, not longer needed to reset the time

time_set = False
packetDitherTimeUpper = 10

# DEFINE GLOBAL VARIABLE to track the alarm count.  This is used as part of the countdown for 
#    transmitting the alarm every 5 minutes.   Note delays are not used along with setting up
#    a separate thread because we want to turn off the alarm as soon as possible when the alarm state goes to zero
alarm_count = 14

# DEFINE GLOBAL VARIABLE TRACKING ON/OFF status of the STX3. DEFAULT IS ON
stx3_ON_OFF = 1

print time_set

#------ balloon_flight_count for testing ONLY BY SCIZONE ONLY!
#balloon_flight_count = 0
#print "*** Balloon Flight Count ***"
#print balloon_flight_count

def write_json_data(data, filename):
    f = open(filename, 'w')
    f.write(json.dumps(data))
    f.close()


def isfloat(value):
  try:
    float(value)
    return True
  except ValueError:
    return False

def unknown_command_wrapper(db_args, cmd, thread_run_event):
    status = 5

    local_db = vms_db.vms_db(**db_args)
    
    # If the command is "STRING.STRING", split the string and attempt
    # to import a module to handle the command.
    subcmd = cmd['command'].lower().split('.', 2)
    if len(subcmd) == 2:
        # pylint: disable=bare-except
        try:
            m = importlib.import_module(subcmd[0])
            cmd_process_func = getattr(m, 'process')
        except KeyboardInterrupt as e:
            raise e
        except:
            status = 3
            # The previous statements could fail if a custom command
            # package is not defined, or if it does not have a process
            # function defined.
            local_db.complete_commands(cmd, False, traceback.format_exception(*sys.exc_info()))
            cmd_process_func = None

        if cmd_process_func:
            try:
                result = cmd_process_func(local_db, subcmd[1], cmd['data'], thread_run_event)
                status = int(not result)
                local_db.complete_commands(cmd, result)
            except KeyboardInterrupt as e:
                raise e
            except:
                # Ensure that the threads are not stuck paused
                thread_run_event.set()

                status = 4
                local_db.complete_commands(cmd, False, traceback.format_exception(*sys.exc_info()))
    else:
        status = 2
        # This is not a custom command, just log it as an unknown error
        msg = 'Unknown command {}:{}'.format(cmd['command'], cmd)
        local_db.complete_commands(cmd, False, msg)

    return status




class vms(object):
    # pylint: disable=unused-argument,too-many-instance-attributes,too-many-statements
    def __init__(self, vms_address, vms_port, vms_cert, vms_username, vms_password, vms_dbname, flight_stream_flag, **kwargs):
        
        global packetDitherTimeUpper
        
        # Save the arguments
        self.args = {
            'vms': {
                'address': vms_address,
                'port': vms_port,
                'username': vms_username,
                'password': vms_password,
                'cert': vms_cert,
                'dbname': vms_dbname
            },
            'vms_ground': {
                'address': '159.118.1.204',
                'port': vms_port,
                'username': vms_username,
                'password': 'quicksat!1',
                'cert': vms_cert,
                'dbname': vms_dbname
            },
            'fsdata': {
                'flight-stream': flight_stream_flag
            }
        }
        
        print self.args

        # Connect to the QS/VMS DB
        self.db = vms_db.vms_db(**self.args['vms'])

        # Determine if LinkStar Duplex Radio is installed - first get the data if the radio is installed
        ls_duplex_installed = self.db.ls_duplex_installed_state()
        print "LinkStar duplex Installed Flag" + str(ls_duplex_installed)

        # Determine if LinkStar Simplex STX Radio is installed - first get the data if the radio is installed
        ls_simplexstx3_installed = self.db.ls_simplexstx3_installed_state()
        
        if ls_simplexstx3_installed == 1:
            radio_space_use = self.db.check_radio_space_use()
        
        # Check if bypassing the GPS. IF ALLOWED AND BYPASSING THE GPS do not get the time 
        #    or set the time - there is no GPS to access the time from
        gpsByPassAllowed = self.db.gps_bypass_allowed()
        print "BY PASS VALUE: " + str(gpsByPassAllowed)

        # Determine if GPS is installed
        vms_gps_state = self.db.gps_installed_state()
        print "gps_installed_state " + str(vms_gps_state)

        if ls_duplex_installed == 1:
            print "LinkStar Duplex INSTALLED"
            self.linkstar = linkstar.linkstar(**self.args['vms'])
        else: 
            print "LinkStar Duplex NOT Installed"
            
        # IF the SIMPLEX, LinkStar-STX3 is installed, define class
        if ls_simplexstx3_installed == 1:
            print "LinkStar-STX3 INSTALLED"
            self.linkstarSTX3 = linkstarstx3.linkstarSTX3()
        else: 
            print "LinkStar-STX3 NOT Installed"

        # IF the duplex radio is installed, get the ground server arguments
        if ls_duplex_installed == 1:
            gs_args = self.db.get_db_ground_args()
            print gs_args
            self.args['vms_ground'] = {
                'address': gs_args['server'],
                'port': vms_port,
                'username': gs_args['username'],
                'password': 'quicksat1',
                'cert': vms_cert,
                'dbname': vms_dbname
            }
            #self.db_ground = vms_db_ground.vms_db_ground(**self.args['vms_ground'])
            self.db_ground = None
            
        # Define ls_comm_flight_stream
        #if flight_stream_flag == 'ENABLED':
        #    self.db_fS = ls_comm_flight_stream.ls_comm_flight_stream(**self.args['lsav'])

        # Some mechanisms to allow threads to be paused by a command handler
        self.thread_run_event = multiprocessing.Event()

        # Keep track of the unknown command processes to ensure they aren't
        # deleted by the garbage collector.
        self.cmd_processes = []

        self.threads = []

        # Open the syslog
        syslog.openlog()
        syslog.syslog(syslog.LOG_NOTICE, 'Started')

        print "---> Duplex setup if installed "
        # IF the duplex radio is installed, send the duplex information to the ground periodically
        if ls_duplex_installed == 1:
            print "DUPLEX INSTALLED -  SYNC STATE"
            # Linkstar duplex state pushing uses command_log_rate
            t = periodic_timer.PeriodicTimer(self.sync_linkstar_duplex_state, 49)
            self.threads.append(t)

        # IF the duplex radio is installed, update the location information between the radio and location tables
        if ls_duplex_installed == 1:
            # For now location information update rate is fixed at every 60 sec
            print "DUPLEX INSTALLED -  UPDATE LOCATION *****"
            print "update location loop"
            t = periodic_timer.PeriodicTimer(self.update_linkstar_location_tables, 53)
            self.threads.append(t)

        # IF the duplex radio is installed, sync the location with the ground
        if ls_duplex_installed == 1:
            # System_Messages uses command_syslog_push_rate
            print "DUPLEX INSTALLED -  SYNC LOCATION *****"
            print "sync location"
            t = periodic_timer.PeriodicTimer(self.sync_location_table, 22)
            self.threads.append(t)
        
        print "----> Activate GPS loop if installed"
        # IF GPS is installed start tracking GPS location data
        if (vms_gps_state is not None) and ( vms_gps_state['gps_type'] != 'NONE'):
            if (vms_gps_state['gps_type'] == 'ADAFRUIT'):
                self.vms_gps = vms_gps.GPS()
            elif (vms_gps_state['gps_type'] == 'NOVATEL'):
                self.vms_gps = vms_gps_novatel.GPS()

            t = periodic_timer.PeriodicTimer(self.update_gps_data, vms_gps_state['sample_rate'])
            self.threads.append(t)

        print "----> Command Monitor"
        # For now, use the command poll rate to run the "command log monitor" function
        t = periodic_timer.PeriodicTimer(self.process, self.db.retrieve_command_log_poll_rate())
        self.threads.append(t)

        # Use a pre-defined radio status poll time for now
        if ls_duplex_installed == 1:
            print "----> Duplex Radio Status loop"
            t = periodic_timer.PeriodicTimer(self.radio_status, 35)
            self.threads.append(t)

        # Flight_Data and Flight_Data_Object use data_download_push_rate
        if ls_duplex_installed == 1:
            t = periodic_timer.PeriodicTimer(self.sync_flight_data, self.db.retrieve_data_download_push_rate())
            self.threads.append(t)

        if ls_duplex_installed == 1:
            t = periodic_timer.PeriodicTimer(self.sync_flight_data_object, self.db.retrieve_data_download_push_rate())
            self.threads.append(t)

        # Flight_Data_Binary uses binary_data_push_rate
        if ls_duplex_installed == 1:
            t = periodic_timer.PeriodicTimer(self.sync_flight_data_binary, self.db.retrieve_binary_data_push_rate())
            self.threads.append(t)

        # Command_Log_ground_to_sv uses command_poll_rate
        if ls_duplex_installed == 1:
            t = periodic_timer.PeriodicTimer(self.sync_command_log_ground_to_sv, self.db.retrieve_command_log_poll_rate())
            self.threads.append(t)

        # Command_Log_sv_to_ground uses command_push_rate
        if ls_duplex_installed == 1:
            t = periodic_timer.PeriodicTimer(self.sync_command_log_sv_to_ground, self.db.retrieve_command_log_push_rate())
            self.threads.append(t)

        # System_Messages uses command_syslog_push_rate
        if ls_duplex_installed == 1:
            t = periodic_timer.PeriodicTimer(self.sync_system_messages, self.db.retrieve_command_syslog_push_rate())
            self.threads.append(t)

        # recording_sessions uses command_syslog_push_rate
        if ls_duplex_installed == 1:
            t = periodic_timer.PeriodicTimer(self.sync_vms_recording_sessions, 37)
            self.threads.append(t)

        # Systems_Applications uses retrieve_command_log_poll_rate
        #    Update the ground station Systems_Application table - this tells the ground station the state of the applications on the SV.
        #

        if ls_duplex_installed == 1:
            t = periodic_timer.PeriodicTimer(self.update_system_applications_state_to_gnd, 38)
            self.threads.append(t)

        print "---> Set up STX3 if installed"
        # IF the SIMPLEX, LinkStar-STX3 is installed, beacon create a data packet group and transmit to the ground
        if ls_simplexstx3_installed == 1:
            # Get GSN number of the STX3 module and write it to the stepSATdb_Flight database
            
            #radioGSN ='0-1234567'
            radioGSN = self.linkstarSTX3.stx3_command('AT+GSN?')
            radioGSN_val = radioGSN.split(": ",1)[1]
            self.db.update_gsn(radioGSN_val)
            
            # Get the packet_group_xmit_rate...this sets the frequency the packet transmission is done.
            #    We will also use this to set the random, "dithering", time of the 
            #    the packet sent to the ground.  This dithering factor is based on the timing between messages
            #    to a limit of up to 5 minute dither
            
            packetGroupXmitRate = self.db.retrieve_packet_group_xmit_rate()
            number_repeats_val = self.db.retrieve_linkstar_simplex_info('maximum_repeats')
            repeat_delay_val = self.db.retrieve_linkstar_simplex_info('repeat_delay')
            print "The baseline transmit rate is ", str(packetGroupXmitRate),", and the Number of Repeats is ", str(number_repeats_val)," and the repeat time is ", str(repeat_delay_val)

            packetGroupXmitRate = packetGroupXmitRate - (number_repeats_val * repeat_delay_val)
            print "---> The net packet delay time is ", str(packetGroupXmitRate)
            
            t=periodic_timer.PeriodicTimer(self.transmit_packet_group, packetGroupXmitRate)
            if packetGroupXmitRate < 3600:
                packetDitherTimeUpper = int( 0.0666667 * float(packetGroupXmitRate))
                print "The packetDitherTimeUpper is -----> ", packetDitherTimeUpper
            else:
                packetDitherTimeUpper = 600
            self.threads.append(t)

        # Set Channel based on space use
        if ls_simplexstx3_installed == 1:
            if radio_space_use == 1:
                print "Channel C"
                stx3Channel = 2
                # channel "2" is Channel C to be used in SPACE AT ALL TIMES!!!
            else:
                print "Channel A"
                stx3Channel = 0
                
            self.linkstarSTX3.stx3_set_channel( stx3Channel )
            self.linkstarSTX3.stx3_CBTMIN(280)                     # required by Globalstar
            self.linkstarSTX3.stx3_CBTMAX(540)                     # required by Globalstar
            self.linkstarSTX3.stx3_number_burst_transmissions(3)   # required by Globalstar
        
        # Set loop to monitor alarm and timing/transmit changes
        if ls_simplexstx3_installed == 1:
            t=periodic_timer.PeriodicTimer(self.stx3_state_change_monitor, 20)      # Check the timing change and the alarm state every 20 seconds
            self.threads.append(t)
            
        # IF the SIMPLEX, LinkStar-STX3 is installed, beacon create a data packet group and transmit to the ground
        #if ls_simplexstx3_installed == 1:
        #        t=periodic_timer.PeriodicTimer(self.transmit_alarm_packet, 120)
        #        self.threads.append(t)

        # IF GPS is installed set the system time.  Because the time may not be correct at the start, and the system
        #    can experience a restart we will check set and the time every two minutes
        
        
        if (vms_gps_state is not None) and ( vms_gps_state['gps_type'] != 'NONE'):            
            # set system time
            print "tttt ---> Set GPS time"
            t=periodic_timer.PeriodicTimer(self.set_ls_system_time, 120)
            self.threads.append(t)


    def __del__(self):
        for t in self.threads:
            t.stop()
        for proc in self.cmd_processes[:]:
            proc.kill()
        syslog.syslog(syslog.LOG_NOTICE, 'Shutting down')
        syslog.closelog()

    def radio_status(self):
        # Check if this thread should be running or paused
        self.thread_run_event.wait()

        # Have the VMS DB connection retrieve and update the radio status
        self.linkstar.get_radio_status()
        # Keep the poll rate constant for now, it shouldn't change
        return 39

    def run(self):
        self.thread_run_event.set()
        for t in self.threads:
            t.start()
        runSys = True
        try:
            while runSys:
                time.sleep(30.0)
                # Check if timing changed.  If changed, restart vms
                timingChanged = self.db.check_timing_reset()
                if timingChanged == 1:
                    print "@@@@@@@@ TIMING CHANGED @@@@@@@@"
                    # set timing_reset flag to zero
                    self.db.zero_timing_reset_flag()
                    # restart command processing
                    for t in self.threads:
                        t.stop()
                    self.threads = []

                    for proc in self.cmd_processes:
                        proc.kill()
                    self.cmd_processes = []
                    
                    runSys = False
                else: 
                    runSys = True

        except KeyboardInterrupt:
            for t in self.threads:
                t.stop()
            self.threads = []

            for proc in self.cmd_processes:
                proc.kill()
            self.cmd_processes = []

            raise
            

    def process(self):
        # pylint: disable=too-many-branches
        commands = self.db.all_pending_commands()
        for cmd in sorted(commands, key=operator.itemgetter("priority")):
            # Most likely there should only be one set of these commands queued
            # up, but it is possible that some combinations may be pending at
            # the same time.  To make the logic simpler, just check for all
            # possibilities
            if cmd['command'] == 'RETRIEVE_COMMAND_LOGS':
                self.retrieve_command_logs(cmd)
            elif cmd['command'] == 'RETRIEVE_SYSTEM_MESSAGES':
                self.retrieve_system_messages(cmd)
            elif cmd['command'] == 'RETRIEVE_FLIGHT_DATA':
                self.retrieve_flight_data(cmd)
            elif cmd['command'] == 'CREATE_REC_SESSION':
                self.create_rec_session(cmd)
            elif cmd['command'] == 'CALL':
                self.call(cmd)
            elif cmd['command'] == 'HANGUP':
                self.hangup(cmd)
            elif cmd['command'] == 'SYNC_FLIGHT_DATA_OBJECT':
                self.sync_flight_data_object(cmd)
            elif cmd['command'] == 'SYNC_FLIGHT_DATA_BINARY':
                self.sync_flight_data_binary(cmd)
            elif cmd['command'] == 'SYNC_FLIGHT_DATA':
                self.sync_flight_data(cmd)
            elif cmd['command'] == 'SYNC_COMMAND_LOG_SV_TO_GROUND':
                self.sync_command_log_sv_to_ground(cmd)
            elif cmd['command'] == 'SYNC_COMMAND_LOG_GROUND_TO_SV':
                self.sync_command_log_ground_to_sv(cmd)
            elif cmd['command'] == 'SYNC_SYSTEM_MESSAGES':
                self.sync_system_messages(cmd)
            elif cmd['command'] == 'SYNC_RECORDING_SESSIONS':
                self.sync_vms_recording_sessions(cmd)
            elif cmd['command'] == 'STOP_STX3':
                print "in OFF COMMAND"
                self.set_STX3_to_OFF(cmd)
            elif cmd['command'] == 'START_STX3':
                print "in ON COMMAND"
                self.set_STX3_to_ON(cmd)
            else:
                self.handle_unknown_command(cmd['command'], cmd)

        # If there were any unknown command processes spawned, check them now
        if self.cmd_processes:
            msg = 'process status for cmd "{0.name}"= pid:{0.pid}, alive:{1}, return:{0.exitcode}'
            for proc in self.cmd_processes[:]:
                syslog.syslog(syslog.LOG_INFO, msg.format(proc, proc.is_alive()))
                if not proc.is_alive():
                    self.cmd_processes.remove(proc)

        # return the new poll rate if it has changed
        return self.db.retrieve_command_log_poll_rate()

    def retrieve_command_logs(self, cmd):
        # There are 3 different ways the command logs can be retrieved:
        #   1. within a time range
        #   2. command logs for a specific session
        #   3. all command logs
        #
        # Check the 'data' element to determine what type of command this is.
        # Each retrieve command should be processed separately
        # pylint: disable=bare-except
        try:
            session = None
            timestamp = None
            # Check if there is any data specified at all
            if len(cmd['data']):
                # First try an integer conversion
                try:
                    session = int(cmd['data'])
                except ValueError:
                    # Last possibility is a timestamp, use the standard MySQL
                    # timestamp format
                    timestamp = time.strptime(cmd['data'], '%Y-%m-%d %H:%M:%S')
            (msgs, _) = self.db.retrieve_command_logs(session, timestamp)
            write_json_data(msgs, '/opt/qs/outputs/cmd{}_command_log_{}'.format(cmd['time'], cmd['data']))
            self.db.complete_commands(cmd, True)
        except KeyboardInterrupt as e:
            raise e
        except:
            self.db.complete_commands(cmd, False, traceback.format_exception(*sys.exc_info()))

    def retrieve_system_messages(self, cmd):
        # There are 3 different ways the system messages can be retrieved:
        #   1. within a time range
        #   2. system messages for a specific session
        #   3. all system messages
        #
        # Check the 'data' element to determine what type of command this is.
        # Each retrieve command should be processed separately
        # pylint: disable=bare-except
        try:
            session = None
            timestamp = None
            # Check if there is any data specified at all
            if len(cmd['data']):
                # First try an integer conversion
                try:
                    session = int(cmd['data'])
                except ValueError:
                    # Last possibility is a timestamp, use the standard MySQL
                    # timestamp format
                    timestamp = time.strptime(cmd['data'], '%Y-%m-%d %H:%M:%S')
            (logs, _) = self.db.retrieve_system_messages(session, timestamp)
            write_json_data(logs, '/opt/qs/outputs/cmd{}_system_messages_{}'.format(cmd['time'], cmd['data']))
            self.db.complete_commands(cmd, True)
        except KeyboardInterrupt as e:
            raise e
        except:
            self.db.complete_commands(cmd, False, traceback.format_exception(*sys.exc_info()))

    def retrieve_flight_data(self, cmd):
        # There are 3 different ways the flight data can be retrieved:
        #   1. within a time range
        #   2. flight data for a specific session
        #   3. all flight data
        #
        # Check the 'data' element to determine what type of command this is.
        # Each retrieve command should be processed separately
        # pylint: disable=bare-except
        try:
            session = None
            timestamp = None
            # Check if there is any data specified at all
            if len(cmd['data']):
                # First try an integer conversion
                try:
                    session = int(cmd['data'])
                except ValueError:
                    # Last possibility is a timestamp, use the standard MySQL
                    # timestamp format
                    timestamp = time.strptime(cmd['data'], '%Y-%m-%d %H:%M:%S')
            (data, _) = self.db.retrieve_flight_data(session, timestamp)
            write_json_data(data, '/opt/qs/outputs/cmd{}_flight_{}'.format(cmd['time'], cmd['data']))
            self.db.complete_commands(cmd, True)
        except KeyboardInterrupt as e:
            raise e
        except:
            self.db.complete_commands(cmd, False, traceback.format_exception(*sys.exc_info()))

    def create_rec_session(self, cmd):
        # Creating a new recording session
        # pylint: disable=bare-except
        try:
            print "create rec session test"
            self.db.increment_session()
            self.db.complete_commands(cmd, True)
        except KeyboardInterrupt as e:
            raise e
        except:
            self.db.complete_commands(cmd, False, traceback.format_exception(*sys.exc_info()))

    def set_STX3_to_OFF(self, cmd):
        # pylint: disable=bare-except
        global stx3_ON_OFF
        try:
            print "@@@@@ TURN OFF STX3"
            stx3_ON_OFF = 0
            self.db.complete_commands(cmd, True, traceback.format_exception(*sys.exc_info()))
        except KeyboardInterrupt as e:
            raise e
        except:
            self.db.complete_commands(cmd, False, traceback.format_exception(*sys.exc_info()))

    def set_STX3_to_ON(self, cmd):
        # pylint: disable=bare-except
        global stx3_ON_OFF
        try:
            print "@@@@@ TURN ON STX3"
            stx3_ON_OFF = 1
            self.db.complete_commands(cmd, True, traceback.format_exception(*sys.exc_info()))
        except KeyboardInterrupt as e:
            raise e
        except:
            self.db.complete_commands(cmd, False, traceback.format_exception(*sys.exc_info()))

    def update_linkstar_location_tables(self, cmd=None):
        # Check if this thread should be running or paused (only if it wasn't
        # called as a command handler)
        if not cmd:
            self.thread_run_event.wait()

        #  Moves LinkStar Duplex State Location info into location table
        #    This is done to keep all location information in one consistent spot.
        #    Also, the goal is to keep location data frequency consistent, since
        #      Linkstar location information is updated irregularly and very frequently
        #
        # pylint: disable=bare-except
        try:
            print "update location table with LinkStar location information"
            self.db.update_ls_location_info()
            if cmd:
                self.db.complete_commands(cmd, True)
        except KeyboardInterrupt as e:
            raise e
        except:
            if cmd:
                self.db.complete_commands(cmd, False, traceback.format_exception(*sys.exc_info()))

    def handle_unknown_command(self, key, cmd):
        # Mark the command as being processed
        self.db.start_command(cmd)

        # Now spawn a separate process to handle the command
        proc = multiprocessing.Process(
            target=unknown_command_wrapper,
            name=cmd['command'],
            args=(self.args['vms'], cmd, self.thread_run_event))
        proc.start()

        msg = 'command process cmd "{0.name}" started (pid:{0.pid})'
        syslog.syslog(syslog.LOG_INFO, msg.format(proc))

        self.cmd_processes.append(proc)

    def call(self, cmd):
        # pylint: disable=bare-except
        try:
            self.linkstar.call('777')
            self.db.complete_commands(cmd, True)
        except KeyboardInterrupt as e:
            raise e
        except:
            self.db.complete_commands(cmd, False, traceback.format_exception(*sys.exc_info()))

    def hangup(self, cmd):
        # pylint: disable=bare-except
        try:
            self.linkstar.hangup()
            self.db.complete_commands(cmd, True)
        except KeyboardInterrupt as e:
            raise e
        except:
            self.db.complete_commands(cmd, False, traceback.format_exception(*sys.exc_info()))

    def check_db_ground_connection(self):
        print 'check_db_ground_connection'
        gs_args = self.db.get_db_ground_args()
        self.args['vms_ground'] = {
            'address': gs_args['server'],
            'port': self.args['vms_ground']['port'],
            'username': gs_args['username'],
            'password': gs_args['password'],
            'cert': self.args['vms_ground']['cert'],
            'dbname': self.args['vms_ground']['dbname']
        }
        print self.args['vms_ground']

        # Check if signal is lost.  If it is, delete db_ground
        #

        # pylint: disable=bare-except
        if self.db_ground:
            print "in DB GROUND CHECK"
            # This just indicates whether or not the ground connection has
            # ever been established.  Connection checking and reconnection
            # attempts are handled in the vms_db_ground class.
            return True
        else:
            print "creating new instance"
            try:
                self.db_ground = vms_db_ground.vms_db_ground(**self.args['vms_ground'])
                print "connected to ground db"
                return True
            except KeyboardInterrupt as e:
                raise e
            except:
                syslog.syslog(syslog.LOG_ERR, 'Error opening ground connection: {}'.format(traceback.format_exception(*sys.exc_info())))
        return False

    """
    Most functions that use the radio will need to check the radio status first
    """

    def remove_db_ground_connection(self):
        try:
            if self.db_ground:
                del self.db_ground
        except KeyboardInterrupt as e:
            raise e
        except:
            syslog.syslog(syslog.LOG_ERR, 'Error opening ground connection: {}'.format(traceback.format_exception(*sys.exc_info())))
        self.db_ground = None
        return

    def sync_flight_data_object(self, cmd=None):
        # Check if this thread should be running or paused (only if it wasn't
        # called as a command handler)
        if not cmd:
            self.thread_run_event.wait()

        print "****** IN sync_flight_data_object"
        #  generate the export file
        #      NOTE - this db module will only generate the file if FIRST TIME RUN
        #             or the file was already downloaded
        sync_to_ground = self.db.sync_selected_db_table('Flight_Data_Object')
        #  Download the export file IF there is a connection to the ground
        self.linkstar.get_radio_status()
        if self.db.check_test_connection():
            if self.check_db_ground_connection():
                print "flight data object test"
                # pylint: disable=bare-except
                try:
                    if sync_to_ground:
                        ground_Sync = self.db_ground.sync_selected_db_table('Flight_Data_Object')
                        if ground_Sync:
                            self.db.reset_sync_flag('Flight_Data_Object')
                    if cmd:
                        self.db.complete_commands(cmd, True)
                except KeyboardInterrupt as e:
                    raise e
                except:
                    if cmd:
                        self.db.complete_commands(cmd, False, traceback.format_exception(*sys.exc_info()))
        else:
            self.remove_db_ground_connection()

    def sync_flight_data_binary(self, cmd=None):
        # Check if this thread should be running or paused (only if it wasn't
        # called as a command handler)
        if not cmd:
            self.thread_run_event.wait()

        print "****** IN sync_flight_data_binary"
        #  generate the export file
        #      NOTE - this db module will only generate the file if FIRST TIME RUN
        #             or the file was already downloaded
        sync_to_ground = self.db.sync_selected_db_table('Flight_Data_Binary')
        self.linkstar.get_radio_status()
        if self.db.check_test_connection():
            if self.check_db_ground_connection():
                print "flight data binary test"
                # pylint: disable=bare-except
                try:
                    if sync_to_ground:
                        ground_Sync = self.db_ground.sync_selected_db_table('Flight_Data_Binary')
                        if ground_Sync:
                            self.db.reset_sync_flag('Flight_Data_Binary')
                    if cmd:
                        self.db.complete_commands(cmd, True)
                except:
                    if cmd:
                        self.db.complete_commands(cmd, False, traceback.format_exception(*sys.exc_info()))
        else:
            self.remove_db_ground_connection()

    def sync_flight_data(self, cmd=None):
        # Check if this thread should be running or paused (only if it wasn't
        # called as a command handler)
        if not cmd:
            self.thread_run_event.wait()

        print "****** IN sync_flight_data"
        #  generate the export file
        #      NOTE - this db module will only generate the file if FIRST TIME RUN
        #             or the file was already downloaded
        sync_to_ground = self.db.sync_selected_db_table('Flight_Data')
        print "Value for sync to ground - flight data"
        print sync_to_ground
        self.linkstar.get_radio_status()
        if self.db.check_test_connection():
            if self.check_db_ground_connection():
                print "flight data test"
                # pylint: disable=bare-except
                try:
                    if sync_to_ground:
                        print "---> Syncing Flight_Data to ground"
                        ground_Sync = self.db_ground.sync_selected_db_table('Flight_Data')
                        if ground_Sync:
                            self.db.reset_sync_flag('Flight_Data')
                    if cmd:
                        self.db.complete_commands(cmd, True)
                except:
                    if cmd:
                        self.db.complete_commands(cmd, False, traceback.format_exception(*sys.exc_info()))
        else:
            self.remove_db_ground_connection()

    def sync_system_messages(self, cmd=None):
        # Check if this thread should be running or paused (only if it wasn't
        # called as a command handler)
        #if not cmd:
        #    self.thread_run_event.wait()

        print "****** IN sync_system_messages"
        #  generate the export file
        #      NOTE - this db module will only generate the file if FIRST TIME RUN
        #             or the file was already downloaded
        sync_to_ground = self.db.sync_selected_db_table('System_Messages')
        print "Value for sync to ground - system messages"
        print sync_to_ground
        self.linkstar.get_radio_status()
        if self.db.check_test_connection():
            if self.check_db_ground_connection():
                # print "system message test"
                # pylint: disable=bare-except
                try:
                    if sync_to_ground:
                        print "---> Syncing System_Messages to ground"
                        ground_Sync = self.db_ground.sync_selected_db_table('System_Messages')
                        if ground_Sync:
                            self.db.reset_sync_flag('System_Messages')
                    if cmd:
                        self.db.complete_commands(cmd, True)
                except:
                    if cmd:
                        self.db.complete_commands(cmd, False, traceback.format_exception(*sys.exc_info()))
        else:
            self.remove_db_ground_connection()

    def sync_vms_recording_sessions(self, cmd=None):
        # Check if this thread should be running or paused (only if it wasn't
        # called as a command handler)
        if not cmd:
            self.thread_run_event.wait()

        self.linkstar.get_radio_status()
        if self.db.check_test_connection():
            if self.check_db_ground_connection():
                print "Syncing Recording Session Information"
                sync_to_ground = self.db.sync_recording_sessions()
                if sync_to_ground:
                    ground_Sync = self.db_ground.sync_recording_sessions()
                    if ground_Sync:
                        self.db.reset_sync_flag('Recording_Sessions')
                sync_to_ground = self.db.sync_recording_session_state()
                if sync_to_ground:
                    ground_Sync = self.db_ground.sync_recording_session_state()
                    if ground_Sync:
                        self.db.reset_sync_flag('Recording_Session_State')
                sync_to_ground = self.db.sync_flight_pointers()
                if sync_to_ground:
                    ground_Sync = self.db_ground.sync_flight_pointers()
                    if ground_Sync:
                        self.db.reset_sync_flag('Flight_Pointers')
                if cmd:
                    self.db.complete_commands(cmd, True)
        else:
            self.remove_db_ground_connection()

    def sync_command_log_sv_to_ground(self, cmd=None):
        # Check if this thread should be running or paused (only if it wasn't
        # called as a command handler)

        sync_to_ground = self.db.sync_selected_db_table('Command_Log')
        print "Value for sync to ground - Command_Log"
        print sync_to_ground
        self.linkstar.get_radio_status()
        if self.db.check_test_connection():
            if self.check_db_ground_connection():
                print "sync command log with the ground"
                try:
                    if sync_to_ground:
                        print "---> Syncing Command_Log to ground"
                        ground_Sync = self.db_ground.sync_selected_db_table('Command_Log')
                        if ground_Sync:
                            self.db.reset_sync_flag('Command_Log')
                    if cmd:
                        self.db.complete_commands(cmd, True)
                except:
                    if cmd:
                        self.db.complete_commands(cmd, False, traceback.format_exception(*sys.exc_info()))
        else:
            self.remove_db_ground_connection()

    def sync_command_log_ground_to_sv(self, cmd=None):
        # Check if this thread should be running or paused (only if it wasn't
        # called as a command handler)

        # sync from ground to sv
        # run pending commands
        print "****** IN sync command ground to SV"
        self.linkstar.get_radio_status()
        if self.db.check_test_connection():
            if self.check_db_ground_connection():
                # try:
                print "++++ Ground Command connection made ++++ "
                datetime_last_command = self.db.get_last_command_date('Pending-Ground')
                print "datetime_last_command value --->"
                print datetime_last_command
                ground_commands = self.db_ground.read_command_log(datetime_last_command)
                print ground_commands
                self.db.add_sv_command_log(ground_commands)  # write to sv db with read_from_sv set to true

                if cmd:
                    self.db.complete_commands(cmd, True)
                print "command log ground to sv test"
                # except:
                #    if cmd:
                #       self.db.complete_commands(cmd, False,
                #           traceback.format_exception(*sys.exc_info()))
        else:
            self.remove_db_ground_connection()

    def sync_linkstar_duplex_state(self, cmd=None):
        print "******>>>> IN sync_linkstar_duplex_state"
        # Check if this thread should be running or paused (only if it wasn't
        # called as a command handler)
        if not cmd:
            self.thread_run_event.wait()

        print "****** IN sync_linkstar_duplex_state"
        #  generate the export file
        #      NOTE - this db module will only generate the file if FIRST TIME RUN
        #             or the file was already downloaded
        sync_to_ground = self.db.sync_selected_db_table('LinkStar_Duplex_State')
        self.linkstar.get_radio_status()
        if self.db.check_test_connection():
            if self.check_db_ground_connection():
                # print "sync_linkstar_duplex test"
                # pylint: disable=bare-except
                try:
                    if sync_to_ground:
                        ground_Sync = self.db_ground.sync_selected_db_table('LinkStar_Duplex_State')
                        if ground_Sync:
                            self.db.reset_sync_flag('LinkStar_Duplex_State')
                    if cmd:
                        self.db.complete_commands(cmd, True)
                except:
                    if cmd:
                        self.db.complete_commands(cmd, False, traceback.format_exception(*sys.exc_info()))
        else:
            self.remove_db_ground_connection()

    def sync_location_table(self, cmd=None):
        print " ~~~~~~>> in sync_location_table  <<----------"
        # Check if this thread should be running or paused (only if it wasn't
        # called as a command handler)

        print " ~~~~~~ in sync_location_table"
        #  generate the export file
        #      NOTE - this db module will only generate the file if FIRST TIME RUN
        #             or the file was already downloaded
        sync_to_ground = self.db.sync_selected_db_table('Location_Data')
        print "Value for sync to ground - location table"
        print sync_to_ground
        self.linkstar.get_radio_status()
        if self.db.check_test_connection():
            if self.check_db_ground_connection():
                # print "sync location Data information with the ground"
                # pylint: disable=bare-except
                try:
                    if sync_to_ground:
                        print "In ground sync LOCATION"
                        ground_Sync = self.db_ground.sync_selected_db_table('Location_Data')
                        if ground_Sync:
                            self.db.reset_sync_flag('Location_Data')
                    if cmd:
                        self.db.complete_commands(cmd, True)
                except:
                    if cmd:
                        self.db.complete_commands(cmd, False, traceback.format_exception(*sys.exc_info()))
        else:
            self.remove_db_ground_connection()

    def update_system_applications_state_to_gnd(self, cmd=None):
        # Check if this thread should be running or paused (only if it wasn't
        # called as a command handler)

        print "****** IN update_system_applications_state_to_gnd"

        sync_to_ground = self.db.sync_selected_db_table('System_Applications_State')
        print sync_to_ground

        self.linkstar.get_radio_status()
        if self.db.check_test_connection():
            if self.check_db_ground_connection():
                # pylint: disable=bare-except
                try:
                    if sync_to_ground:
                        print "In ground sync Application State"
                        ground_Sync = self.db_ground.sync_selected_db_table('System_Applications_State')
                        if ground_Sync:
                            self.db.reset_sync_flag('System_Applications_State')
                    if cmd:
                        self.db.complete_commands(cmd, True)
                except:
                    if cmd:
                        self.db.complete_commands(cmd, False, traceback.format_exception(*sys.exc_info()))
        else:
            self.remove_db_ground_connection()

    def upload_app_from_gnd(self, cmd):
        self.linkstar.get_radio_status()
        if self.db.check_test_connection():
            if self.check_db_ground_connection():
                # pylint: disable=bare-except
                try:
                    print "Uploading app from GND to Vehicle"
                    #  read file
                    #  Set app state to 80 ONLY after file is completely uploaded
                    application_id = cmd['command_data']
                    self.db.change_system_application_state(self, application_id, 80, "GATEWAY Storage", 1)
                    if cmd:
                        self.db.complete_commands(cmd, True)
                except:
                    if cmd:
                        self.db.complete_commands(cmd, False, traceback.format_exception(*sys.exc_info()))
        else:
            self.remove_db_ground_connection()

    def delete_from_gateway(self, cmd):
        # This deletes apps/VMs with a status of 80 - APPS/VMs cannot be deleted if they are running, status > 100.
        #    Failed apps with status greater than 100 can be reset to a status of 80.
        #    Locked apps CANNOT be deleted.
        # This command can be acted upon without communicating with the ground station.
        # pylint: disable=bare-except
        try:
            print "Deleting APP/VM from Gateway"
            application_id = cmd['command_data']
            self.db.change_system_application_state(self, application_id, 50, "GROUND Storage", 0)
            if cmd:
                self.db.complete_commands(cmd, True)
        except:
            if cmd:
                self.db.complete_commands(cmd, False, traceback.format_exception(*sys.exc_info()))
                
    def transmit_packet_group(self):
        # This function builds the packet to be sent and
        #    transmits the packet to the ground through the LinkStar-STX3 radio
        
        global packetDitherTimeUpper
        global stx3_ON_OFF
        
        # Check if alarm is DETECTED.  IF ALARM is 1, DO NOT SEND PACKET GROUP!
        alarmStatus = self.db.check_alarm_status()

        # Verify activated to transmit
        
        sync_to_ground = self.db.ground_sync_allowed()
        print "-----> sync_to_ground" + str(sync_to_ground)
        
        if (sync_to_ground == 1) and (stx3_ON_OFF == 1) and (alarmStatus == 0):
        
            # Verify allowed to BY PASS THE GPS.  This allows the LinkStar-STX3 to
            #    operate without a GPS or without a GPS fix.
            #    THIS CAN ONLY BE USED FOR SPACE MISSIONS AND LAB TESTING by AUTHORIZED ORGANIATIONS

            gpsByPassAllowed = self.db.gps_bypass_allowed()

            print "-----> space use, BYPASS GPS --> " + str(gpsByPassAllowed)
        
            # get number of message repeats and the time between repeats
        
            number_repeats_val = self.db.retrieve_linkstar_simplex_info('maximum_repeats')
            repeat_delay_val = self.db.retrieve_linkstar_simplex_info('repeat_delay')
            print ">>>-----> number_repeats_val --> " + str(number_repeats_val)
            print ">>>-----> repeat_delay_val --> " + str(repeat_delay_val)
        

            packetType = self.db.get_packet_type(1)
        
        
        
            print "---->  SYNC LINKSTARSTX3 TO GROUND <--------"
        
            # Verify GPS has a fix.  If the GPS does have a fix allow transmission of the packet
            gpsInformation = self.db.gps_installed_state()
            
            if gpsInformation is not None:
                gpsFixQuality = gpsInformation['fix_quality']
            else:
                gpsFixQuality = 0

            # Set channel based on location
            #
            #  If SPACE USE, the channel is preset at vms startup AND CANNOT BE CHANGED!
            
            print "GPS Information FIX QUALITY: " + str(gpsFixQuality)
            
            if (gpsFixQuality!=0) or (gpsByPassAllowed == 1):
            
                print "----> *** PRE-DITHER TRANSMIT *** <----> ", packetDitherTimeUpper
                
                # delay based on random dither factor range
                
                time.sleep(randint(5,packetDitherTimeUpper))
                
                print "----> *** TRANSMITTING PACKET *** <----"
                 
                # Build packet
                
                # Retrieve current packet_id and get maximum number of packets in group
                packet_id = 1

                # Increment if maximum number of packets in group is greater than 2
                
                
                # Check GPS location IF NOT IN SPACE USE MODE.  This will determine whether to use Channel A or C.
                radio_space_use = self.db.check_radio_space_use()
                if radio_space_use != 1:                                 # SPACE USE NOT SET.  If SPACE USE, Channel is already set. No need to check Earth region
                    gpsLocation = self.db.get_location()
                    print gpsLocation['latitude']
                    print gpsLocation['longitude']
                    print gpsLocation['altitude']
                    if gpsLocation['latitude'] != 'error':
                        stx3Channel = self.linkstarSTX3.check_bounds(float(gpsLocation['latitude']), float(gpsLocation['longitude']), float(gpsLocation['altitude']))
                        print "----> *** Channel set for broadcast *** -> " + str(stx3Channel)
                        self.linkstarSTX3.stx3_set_channel( stx3Channel )
                
                # Retrieve packet
                message_packet_ascii = self.db.get_stx3_ascii_message(packet_id)
                print "The retrieved ASCII message"
                print message_packet_ascii
        
                # The LinkStar-STX3 only sends HEX messages.  This function allows you to send
                #    ASCII messages which then automatically converts the message to HEX before
                #    Sending the message
                
                message_is_ascii = False
                if ( packetType == 'GS_GPS'): 
                    message_is_ascii = True
                    self.linkstarSTX3.stx3_gps_message( message_packet_ascii )
                elif ( ( packetType == 'GPS_EXTENDED') or ( packetType == 'GPS_FULL') or ( packetType == 'TEST') or ( packetType == 'X')) :
                    message_is_ascii = True
                    print "In ASCII MESSAGE SEND"
                    self.linkstarSTX3.stx3_message_ascii( message_packet_ascii )
                else:
                    message_is_ascii = False
                    # parse message
                    parsed_message = message_packet_ascii.split(',')
                    
                    # Pack GPS code
                                        
                    # convert latitude to integer code
                    gps_lat_f = float(parsed_message[1])
                    
                    if (gps_lat_f < 0):
                        gps_lat_f = 180+gps_lat_f
                    
                    gps_lat_code_f = (gps_lat_f/90)*(2**23)
                    
                    if ( isfloat(gps_lat_code_f) ):
                        gps_lat_code_i = int(round(gps_lat_code_f))
                    else:
                        gps_lat_code_i = 0
                    
                    # convert latitude to HEX
                    gps_lat_hex = hex(gps_lat_code_i)
                    print "Lat Codes"
                    print gps_lat_hex
                    gps_lat_hex = gps_lat_hex.rstrip("L").lstrip("0x")
                    print gps_lat_hex
                    gps_lat_hex = gps_lat_hex.upper()
                    print gps_lat_hex
                   
                    # convert longitude to integer code
                    gps_lon_f = float(parsed_message[2])
                    
                    if (gps_lon_f < 0):
                        gps_lon_f = 360+gps_lon_f
                    
                    gps_lon_code_f = (gps_lon_f/180)*(2**23)
                    
                    if ( isfloat(gps_lon_code_f) ):
                        gps_lon_code_i = int(round(gps_lon_code_f))
                    else:
                        gps_lon_code_i = 0
                    
                    # convert latitude to HEX
                    gps_lon_hex = hex(gps_lon_code_i)
                    gps_lon_hex = gps_lon_hex.rstrip("L").lstrip("0x")
                    gps_lon_hex = gps_lon_hex.upper()
                    
                    # Convert packet type to HEX
                    packet_type_hex = parsed_message[0].encode("hex")
                    packet_type_hex = packet_type_hex.upper()
                    print "packet type hex: " + packet_type_hex
                    
                    # Convert message to HEX
                    
                    if ( parsed_message[0] == 'B' ):                # Transmit first two bytes
                        data_message_hex = parsed_message[3].encode("hex")
                        data_message_hex = data_message_hex.upper()
                        
                    if ( parsed_message[0] == 'G' ):                
                        data_message_hex = parsed_message[3].encode("hex")
                        data_message_hex = data_message_hex.upper()
                        
                    elif ( parsed_message[0] == 'A' ):              # Transmit altitude data
                        # convert string to float
                        if (parsed_message[3] is None) or (parsed_message[3] == ''):
                            data_value_f = 0.0
                        else:
                            data_value_f = float(parsed_message[3])
                        # convert float to integer
                        if ( isfloat(data_value_f) ):
                            data_value_i = int(round(data_value_f))
                        else:
                            data_value_i = 0
                        # convert integer to hex
                        data_message_hex = hex(data_value_i)
                        data_message_hex = data_message_hex.rstrip("L").lstrip("0x")
                        data_message_hex = data_message_hex.upper()
                    
                    elif ( parsed_message[0] == 'P' ):             # Transmit altitude in space data
                        # convert string to float
                        if (parsed_message[3] is None) or (parsed_message[3] == ''):
                            data_value_f = 0.0
                        else:
                            data_value_f = float(parsed_message[3])
                        # convert float to integer
                        if ( isfloat(data_value_f) ):
                            data_value_i = int(round(data_value_f))
                        else:
                            data_value_i = 0
                        # convert integer to hex
                        data_message_hex = hex(data_value_i)
                        data_message_hex = data_message_hex.rstrip("L").lstrip("0x")
                        data_message_hex = data_message_hex.upper()
                    
                    elif ( parsed_message[0] == 'S' ):             # Transmit speed
                        print "messages"
                        print parsed_message[3]
                        # convert string to float
                        if (parsed_message[3] is None) or (parsed_message[3] == ''):
                            data_value_f = 0.0
                        else:
                            data_value_f = float(parsed_message[3])
                        # convert float to integer
                        if ( isfloat(data_value_f) ):
                            data_value_i = int(round(data_value_f))
                        else:
                            data_value_i = 0
                        # convert integer to hex
                        print data_value_i
                        data_message_hex = hex(data_value_i)
                        print data_message_hex
                        data_message_hex = data_message_hex.rstrip("L").lstrip("0x")
                        print data_message_hex
                        data_message_hex = data_message_hex.upper()
                        print data_message_hex

                    elif ( parsed_message[0] == 'I' ):            # Transmit integer value
                        # convert string to float
                        if (parsed_message[3] is None) or (parsed_message[3] == ''):
                            data_value_f = 0.0
                        else:
                            data_value_f = float(parsed_message[3])
                        # convert float to integer
                        if ( isfloat(data_value_f) ):
                            data_value_i = int(round(data_value_f))
                        else:
                            data_value_i = 0
                        # convert integer to hex
                        data_message_hex = hex(data_value_i)
                        data_message_hex = data_message_hex.rstrip("L").lstrip("0x")
                        data_message_hex = data_message_hex.upper()

                    elif ( parsed_message[0] == '1' ):
                        print "messages"
                        print parsed_message[3]
                        # convert string to float
                        if (parsed_message[3] is None) or (parsed_message[3] == ''):
                            data_value_f = 0.0
                        else:
                            data_value_f = float(parsed_message[3])
                        # convert float to integer
                        if ( isfloat(data_value_f) ):
                            # move right of decimal data to left 1 place
                            data_value_f = data_value_f*10
                            data_value_i = int(round(data_value_f))
                        else:
                            data_value_i = 0
                        # convert integer to hex
                        print data_value_i
                        data_message_hex = hex(data_value_i)
                        print data_message_hex
                        data_message_hex = data_message_hex.rstrip("L").lstrip("0x")
                        print data_message_hex
                        data_message_hex = data_message_hex.upper()
                        print data_message_hex

                    elif ( parsed_message[0] == '2' ):
                        print "messages"
                        print parsed_message[3]
                        # convert string to float
                        if (parsed_message[3] is None) or (parsed_message[3] == ''):
                            data_value_f = 0.0
                        else:
                            data_value_f = float(parsed_message[3])
                        # convert float to integer
                        if ( isfloat(data_value_f) ):
                            # move right of decimal data to left 1 place
                            data_value_f = data_value_f*100
                            data_value_i = int(round(data_value_f))
                        else:
                            data_value_i = 0
                        # convert integer to hex
                        print data_value_i
                        data_message_hex = hex(data_value_i)
                        print data_message_hex
                        data_message_hex = data_message_hex.rstrip("L").lstrip("0x")
                        print data_message_hex
                        data_message_hex = data_message_hex.upper()
                        print data_message_hex

                    elif ( parsed_message[0] == '3' ):
                        # convert string to float
                        if (parsed_message[3] is None) or (parsed_message[3] == ''):
                            data_value_f = 0.0
                        else:
                            data_value_f = float(parsed_message[3])
                        # convert float to integer
                        if ( isfloat(data_value_f) ):
                            # move right of decimal data to left 1 place
                            data_value_f = +1000*data_value_f
                            data_value_i = int(round(data_value_f))
                        else:
                            data_value_i = 0
                        # convert integer to hex
                        data_message_hex = hex(data_value_i)
                        data_message_hex = data_message_hex.rstrip("L").lstrip("0x")
                        data_message_hex = data_message_hex.upper()

                    elif ( parsed_message[0] == '4' ):
                        # convert string to float
                        if (parsed_message[3] is None) or (parsed_message[3] == ''):
                            data_value_f = 0.0
                        else:
                            data_value_f = float(parsed_message[3])
                        # convert float to integer
                        if ( isfloat(data_value_f) ):
                            # move right of decimal data to left 1 place
                            data_value_f = +10000*data_value_f
                            data_value_i = int(round(data_value_f))
                        else:
                            data_value_i = 0
                        # convert integer to hex
                        data_message_hex = hex(data_value_i)
                        data_message_hex = data_message_hex.rstrip("L").lstrip("0x")
                        data_message_hex = data_message_hex.upper()

                    elif ( parsed_message[0] == '5' ):
                        # convert string to float
                        if (parsed_message[3] is None) or (parsed_message[3] == ''):
                            data_value_f = 0.0
                        else:
                            data_value_f = float(parsed_message[3])
                        # convert float to integer
                        if ( isfloat(data_value_f) ):
                            # move right of decimal data to left 1 place
                            data_value_f = +100000*data_value_f
                            data_value_i = int(round(data_value_f))
                        else:
                            data_value_i = 0
                        # convert integer to hex
                        data_message_hex = hex(data_value_i)
                        data_message_hex = data_message_hex.rstrip("L").lstrip("0x")
                        data_message_hex = data_message_hex.upper()
                    
                    else:   # Treat as type B
                        data_message_hex = parsed_message[3].encode("hex")
                        data_message_hex = data_message_hex.upper()
                    
                    
                    # Assemble Message
                    message_packet_hex = packet_type_hex + gps_lat_hex + gps_lon_hex + data_message_hex
                    print message_packet_hex
                    
                    # Send message as HEX
                    self.linkstarSTX3.stx3_message_hex( message_packet_hex )
                
                # Archive the sent packet
                self.db.archive_packet( message_packet_ascii, packet_id )     # save original message, not hex message
                
                # Check if repeating the message.  If so repeat...
                if number_repeats_val > 0:                # case of one or two repeat messages
                    time.sleep(repeat_delay_val)
                    if (message_is_ascii):
                        self.linkstarSTX3.stx3_message_ascii( message_packet_ascii )
                    else:
                        self.linkstarSTX3.stx3_message_hex( message_packet_hex )
                        
                    # Archive the sent packet
                    self.db.archive_packet( message_packet_ascii, packet_id )      # save original message, not hex message
                    print "----> *** TRANSMITTING PACKET #1 *** <----"
                    
                    if number_repeats_val > 1:            # case of two repeat messages
                        time.sleep(repeat_delay_val)
                        if (message_is_ascii):
                            self.linkstarSTX3.stx3_message_ascii( message_packet_ascii )
                        else:
                            self.linkstarSTX3.stx3_message_hex( message_packet_hex )
                        
                        # Archive the sent packet
                        self.db.archive_packet( message_packet_ascii, packet_id )        # save original message, not hex message
                        print "----> *** TRANSMITTING PACKET #2 *** <----"

    def transmit_alarm_packet(self):
        global stx3_ON_OFF

        # This function builds the packet to be sent and
        #    transmits the packet to the ground through the LinkStar-STX3 radio
        
        # Verify activated to transmit
        
        sync_to_ground = self.db.ground_sync_allowed()
        
        print "-----> ALARM sync_to_ground " + str(sync_to_ground)
        
        # Verify allowed to BY PASS THE GPS.  This allows the LinkStar-STX3 to
        #    operate without a GPS or without a GPS fix.
        #    THIS CAN ONLY BE USED FOR SPACE MISSIONS AND LAB TESTING by AUTHORIZED ORGANIATIONS

        gpsByPassAllowed = self.db.gps_bypass_allowed()

        print "-----> space use, BYPASS GPS --> " + str(gpsByPassAllowed)

        packetType = self.db.get_packet_type(1)
                
        if (sync_to_ground == 1) and (stx3_ON_OFF == 1):
        
            print "---->  SYNC LINKSTARSTX3 ALARM TO GROUND <--------"
        
            # Verify GPS has a fix.  If the GPS does have a fix allow transmission of the packet
            gpsInformation = self.db.gps_installed_state()
            
            if gpsInformation is not None:
                gpsFixQuality = gpsInformation['fix_quality']
            else:
                gpsFixQuality = 0

            # Set channel based on location
            #
            #  If SPACE USE, the channel is preset at vms startup AND CANNOT BE CHANGED!
            
            print "GPS Information FIX QUALITY: " + str(gpsFixQuality)
            
            if (gpsFixQuality!=0) or (gpsByPassAllowed == 1):
            
                print "----> *** PRE-DITHER TRANSMIT *** <----> 30"
                
                # delay based on random dither factor range
                
                time.sleep(randint(5,30))
                
                print "----> *** TRANSMITTING ALARM PACKET *** <----"
                 
                # Build packet
                
                # Retrieve current packet_id and get maximum number of packets in group
                packet_id = 1

                
                # Check GPS location IF NOT IN SPACE USE MODE.  This will determine whether to use Channel A or C.
                radio_space_use = self.db.check_radio_space_use()
                if radio_space_use != 1:                                 # SPACE USE NOT SET.  If SPACE USE, Channel is already set. No need to check Earth region
                    gpsLocation = self.db.get_location()
                    print gpsLocation['latitude']
                    print gpsLocation['longitude']
                    print gpsLocation['altitude']
                    if gpsLocation['latitude'] != 'error':
                        stx3Channel = self.linkstarSTX3.check_bounds(float(gpsLocation['latitude']), float(gpsLocation['longitude']), float(gpsLocation['altitude']))
                        print "----> *** Channel set for broadcast *** -> " + str(stx3Channel)
                        self.linkstarSTX3.stx3_set_channel( stx3Channel )
                
                # Retrieve packet
                message_packet_ascii = self.db.get_stx3_ascii_message(packet_id)
        
                # The LinkStar-STX3 only sends HEX messages.  This function allows you to send
                #    ASCII messages which then automatically converts the message to HEX before
                #    Sending the message
                
                message_is_ascii = False
                if ( packetType == 'GS_GPS'): 
                    message_is_ascii = True
                    self.linkstarSTX3.stx3_gps_message( message_packet_ascii )
                elif ( ( packetType == 'GPS_EXTENDED') or ( packetType == 'GPS_FULL') or ( packetType == 'TEST') or ( packetType == 'X')) :
                    message_is_ascii = True
                    print "In ASCII MESSAGE SEND"
                    self.linkstarSTX3.stx3_message_ascii( message_packet_ascii )
                else:
                    message_is_ascii = False
                    # parse message
                    parsed_message = message_packet_ascii.split(',')
                    
                    # Pack GPS code
                                        
                    # convert latitude to integer code
                    gps_lat_f = float(parsed_message[1])
                    
                    if (gps_lat_f < 0):
                        gps_lat_f = 180+gps_lat_f
                    
                    gps_lat_code_f = (gps_lat_f/90)*(2**23)
                    
                    if ( isfloat(gps_lat_code_f) ):
                        gps_lat_code_i = int(round(gps_lat_code_f))
                    else:
                        gps_lat_code_i = 0
                    
                    # convert latitude to HEX
                    gps_lat_hex = hex(gps_lat_code_i)
                    print "Lat Codes"
                    print gps_lat_hex
                    gps_lat_hex = gps_lat_hex.rstrip("L").lstrip("0x")
                    print gps_lat_hex
                    gps_lat_hex = gps_lat_hex.upper()
                    print gps_lat_hex
                   
                    # convert longitude to integer code
                    gps_lon_f = float(parsed_message[2])
                    
                    if (gps_lon_f < 0):
                        gps_lon_f = 360+gps_lon_f
                    
                    gps_lon_code_f = (gps_lon_f/180)*(2**23)
                    
                    if ( isfloat(gps_lon_code_f) ):
                        gps_lon_code_i = int(round(gps_lon_code_f))
                    else:
                        gps_lon_code_i = 0
                    
                    # convert latitude to HEX
                    gps_lon_hex = hex(gps_lon_code_i)
                    gps_lon_hex = gps_lon_hex.rstrip("L").lstrip("0x")
                    gps_lon_hex = gps_lon_hex.upper()
                    
                    # Convert packet type to HEX
                    packet_type_hex = parsed_message[0].encode("hex")
                    packet_type_hex = packet_type_hex.upper()
                    print "packet type hex: " + packet_type_hex
                    
                    # Convert message to HEX
                    
                    if ( parsed_message[0] == 'B' ):                # Transmit first two bytes
                        data_message_hex = parsed_message[3].encode("hex")
                        data_message_hex = data_message_hex.upper()
                        
                    if ( parsed_message[0] == 'G' ):                
                        data_message_hex = parsed_message[3].encode("hex")
                        data_message_hex = data_message_hex.upper()
                        
                    elif ( parsed_message[0] == 'A' ):              # Transmit altitude data
                        # convert string to float
                        data_value_f = float(parsed_message[3])
                        # convert float to integer
                        if ( isfloat(data_value_f) ):
                            data_value_i = int(round(data_value_f))
                        else:
                            data_value_i = 0
                        # convert integer to hex
                        data_message_hex = hex(data_value_i)
                        data_message_hex = data_message_hex.rstrip("L").lstrip("0x")
                        data_message_hex = data_message_hex.upper()
                    
                    elif ( parsed_message[0] == 'P' ):             # Transmit altitude in space data
                        # convert string to float
                        data_value_f = float(parsed_message[3])
                        # convert float to integer
                        if ( isfloat(data_value_f) ):
                            data_value_i = int(round(data_value_f))
                        else:
                            data_value_i = 0
                        # convert integer to hex
                        data_message_hex = hex(data_value_i)
                        data_message_hex = data_message_hex.rstrip("L").lstrip("0x")
                        data_message_hex = data_message_hex.upper()
                    
                    elif ( parsed_message[0] == 'S' ):             # Transmit speed
                        print "messages"
                        print parsed_message[3]
                        # convert string to float
                        data_value_f = float(parsed_message[3])
                        # convert float to integer
                        if ( isfloat(data_value_f) ):
                            data_value_i = int(round(data_value_f))
                        else:
                            data_value_i = 0
                        # convert integer to hex
                        print data_value_i
                        data_message_hex = hex(data_value_i)
                        print data_message_hex
                        data_message_hex = data_message_hex.rstrip("L").lstrip("0x")
                        print data_message_hex
                        data_message_hex = data_message_hex.upper()
                        print data_message_hex

                    elif ( parsed_message[0] == 'I' ):            # Transmit integer value
                        # convert string to float
                        data_value_f = float(parsed_message[3])
                        # convert float to integer
                        if ( isfloat(data_value_f) ):
                            data_value_i = int(round(data_value_f))
                        else:
                            data_value_i = 0
                        # convert integer to hex
                        data_message_hex = hex(data_value_i)
                        data_message_hex = data_message_hex.rstrip("L").lstrip("0x")
                        data_message_hex = data_message_hex.upper()

                    elif ( parsed_message[0] == '1' ):
                        print "messages"
                        print parsed_message[3]
                        # convert string to float
                        data_value_f = float(parsed_message[3])
                        # convert float to integer
                        if ( isfloat(data_value_f) ):
                            # move right of decimal data to left 1 place
                            data_value_f = data_value_f*10
                            data_value_i = int(round(data_value_f))
                        else:
                            data_value_i = 0
                        # convert integer to hex
                        print data_value_i
                        data_message_hex = hex(data_value_i)
                        print data_message_hex
                        data_message_hex = data_message_hex.rstrip("L").lstrip("0x")
                        print data_message_hex
                        data_message_hex = data_message_hex.upper()
                        print data_message_hex

                    elif ( parsed_message[0] == '2' ):
                        print "messages"
                        print parsed_message[3]
                        # convert string to float
                        data_value_f = float(parsed_message[3])
                        # convert float to integer
                        if ( isfloat(data_value_f) ):
                            # move right of decimal data to left 1 place
                            data_value_f = data_value_f*100
                            data_value_i = int(round(data_value_f))
                        else:
                            data_value_i = 0
                        # convert integer to hex
                        print data_value_i
                        data_message_hex = hex(data_value_i)
                        print data_message_hex
                        data_message_hex = data_message_hex.rstrip("L").lstrip("0x")
                        print data_message_hex
                        data_message_hex = data_message_hex.upper()
                        print data_message_hex

                    elif ( parsed_message[0] == '3' ):
                        # convert string to float
                        data_value_f = float(parsed_message[3])
                        # convert float to integer
                        if ( isfloat(data_value_f) ):
                            # move right of decimal data to left 1 place
                            data_value_f = +1000*data_value_f
                            data_value_i = int(round(data_value_f))
                        else:
                            data_value_i = 0
                        # convert integer to hex
                        data_message_hex = hex(data_value_i)
                        data_message_hex = data_message_hex.rstrip("L").lstrip("0x")
                        data_message_hex = data_message_hex.upper()

                    elif ( parsed_message[0] == '4' ):
                        # convert string to float
                        data_value_f = float(parsed_message[3])
                        # convert float to integer
                        if ( isfloat(data_value_f) ):
                            # move right of decimal data to left 1 place
                            data_value_f = +10000*data_value_f
                            data_value_i = int(round(data_value_f))
                        else:
                            data_value_i = 0
                        # convert integer to hex
                        data_message_hex = hex(data_value_i)
                        data_message_hex = data_message_hex.rstrip("L").lstrip("0x")
                        data_message_hex = data_message_hex.upper()

                    elif ( parsed_message[0] == '5' ):
                        # convert string to float
                        data_value_f = float(parsed_message[3])
                        # convert float to integer
                        if ( isfloat(data_value_f) ):
                            # move right of decimal data to left 1 place
                            data_value_f = +100000*data_value_f
                            data_value_i = int(round(data_value_f))
                        else:
                            data_value_i = 0
                        # convert integer to hex
                        data_message_hex = hex(data_value_i)
                        data_message_hex = data_message_hex.rstrip("L").lstrip("0x")
                        data_message_hex = data_message_hex.upper()
                    
                    else:   # Treat as type B
                        data_message_hex = parsed_message[3].encode("hex")
                        data_message_hex = data_message_hex.upper()
                    
                    
                    # Assemble Message
                    message_packet_hex = packet_type_hex + gps_lat_hex + gps_lon_hex + data_message_hex
                    print message_packet_hex
                    
                    # Send message as HEX
                    self.linkstarSTX3.stx3_message_hex( message_packet_hex )
                
                # Archive the sent packet
                self.db.archive_packet( message_packet_ascii, packet_id )
                
      
    def stx3_state_change_monitor(self):
        global alarm_count
        # Check alarm status
        alarmStatus = self.db.check_alarm_status()
        if alarmStatus == 1:
            alarm_count += 1
            print alarm_count
            if alarm_count >= 15:
                self.transmit_alarm_packet()
                alarm_count = 0
        else:
            alarm_count = 14
            print "@@@@@@ ALARM COUNT CHANGE; ALARM OFF "
            print alarm_count
            
    def update_gps_data(self):
        self.vms_gps.read()

        # ***** CUSTOM FOR THE TEST FLIGHT
        #  GET the GPS data
        if self.vms_gps.latHem == 'N':
            gpsLatHem = ''
        else:
            gpsLatHem = '-'
        
        if self.vms_gps.lonHem == 'W':
            gpsLonHem = '-'
        else:
            gpsLonHem = ' '

        print " GPS FIX TYPE "
        print self.vms_gps.gpsFixType
        gpsFixTypeVal = str(self.vms_gps.gpsFixType)
        fixVal = str(self.vms_gps.fix)
        print gpsFixTypeVal
        
        satellites_being_tracked = self.vms_gps.sats
        satellites_in_view = self.vms_gps.NumberSatellitesInView
        pdop = self.vms_gps.PDOP
        vdop = self.vms_gps.VDOP
        hdop = self.vms_gps.HDOP
         
        print "DOPS DONE ********" 
        gpsData = str(self.vms_gps.timeUTC) + ',' + gpsLatHem + str(self.vms_gps.latDeg) + ',' + str(self.vms_gps.latMin) +',' + gpsLonHem + str(self.vms_gps.lonDeg) + ',' + str(self.vms_gps.lonMin) + ',' + str(self.vms_gps.knots) +','+ str(self.vms_gps.altitude) + ',' + str(self.vms_gps.magTrue)+ ',' + gpsFixTypeVal + ',' + fixVal
        print gpsData
        #  WRITE THE GPS DATA as a packet to the database IF ENABLED
        #  
        #  check packet type
        packetType = self.db.get_packet_type(1)
        parameter_id = self.db.get_packet_parameter_id(1)
        print packetType

        # Write the data to the Location_Data table - this is used for the on board map function
        if isfloat(self.vms_gps.latDeg) and (self.vms_gps.latMin):
            gpsLattitude_num = float(self.vms_gps.latDeg) + float(self.vms_gps.latMin)/60
        else:
            gpsLattitude_num = 0
        
        gpsLattitude = gpsLatHem + str(gpsLattitude_num)


        if isfloat(self.vms_gps.lonDeg) and (self.vms_gps.lonMin):
            gpsLongitude_num = float(self.vms_gps.lonDeg) + float(self.vms_gps.lonMin)/60
        else:
            gpsLongitude_num = 0
        
        gpsLongitude = gpsLonHem + str(gpsLongitude_num)

        
        if ( packetType == 'GPS_SIMPLE'):
            gpsData = 'G'+',' + gpsLattitude +',' + gpsLongitude + ','+''
            print gpsData
            self.db.write_stx3_ascii_message(gpsData,1)
 
        elif ( packetType == 'GPS_EXTENDED'):
            gpsData = 'E'+','+str(self.vms_gps.timeUTC) + ',' + gpsLatHem + str(self.vms_gps.latDeg) + ',' + str(self.vms_gps.latMin) +',' + gpsLonHem + str(self.vms_gps.lonDeg) + ',' + str(self.vms_gps.lonMin) + ',' + str(self.vms_gps.knots) +','+ str(self.vms_gps.altitude)
            print gpsData
            self.db.write_stx3_ascii_message(gpsData,1)

        elif ( packetType == 'GPS_FULL'):
            gpsData = 'F'+',' + str(self.vms_gps.timeUTC) + ',' + gpsLatHem + str(self.vms_gps.latDeg) + ',' + str(self.vms_gps.latMin) +',' + gpsLonHem + str(self.vms_gps.lonDeg) + ',' + str(self.vms_gps.lonMin) + ',' + str(self.vms_gps.knots) +','+ str(self.vms_gps.altitude) + ',' + str(self.vms_gps.magTrue)+ ',' + gpsFixTypeVal + ',' + fixVal
            print gpsData
            self.db.write_stx3_ascii_message(gpsData,1)

        elif ( packetType == 'TEST'):
            gpsData = '*'+str(self.vms_gps.timeUTC)
            print gpsData
            self.db.write_stx3_ascii_message(gpsData,1)

        elif ( packetType == 'GS_GPS'):
            gpsData = str(self.vms_gps.latDeg) + str(int(round(float(self.vms_gps.latMin))))+'.0000' + ','+self.vms_gps.latHem+ ',' + str(self.vms_gps.lonDeg) + str(int(round(float(self.vms_gps.lonMin)))) + '.0000' + ','+self.vms_gps.lonHem + ','+ '0'
            print gpsData
            self.db.write_stx3_ascii_message(gpsData,1)
        elif ( packetType == 'B'):
            #  Get the data from flight data.   Only first two bytes will be used.
            stx3Data = self.db.retrieve_flight_data_last('Flight_Data','parameter_value',parameter_id)
            print stx3Data
            print "Two Bytes"
            print stx3Data[:2]
            gpsData = 'B'+ ',' + gpsLattitude +',' + gpsLongitude +  ',' + stx3Data[:2]
            self.db.write_stx3_ascii_message(gpsData,1)
        elif ( packetType == 'A'):
            #  Get the data from flight data.   Only first two bytes will be used.
            gpsData = 'A'+ ',' + gpsLattitude +',' + gpsLongitude +  ',' + str(self.vms_gps.altitude)
            self.db.write_stx3_ascii_message(gpsData,1)
        elif ( packetType == 'P'):
            #  Get the data from flight data.   Only first two bytes will be used.
            spaceAltitude = float(self.vms_gps.altitude)/1000.0
            gpsData = 'P'+ ',' + gpsLattitude +',' + gpsLongitude + ',' + str(spaceAltitude)
            self.db.write_stx3_ascii_message(gpsData,1)
        elif ( packetType == 'S'):
            #  Get the data from flight data.   Only first two bytes will be used.
            gpsData = 'S'+ ',' + gpsLattitude +',' + gpsLongitude + ',' + str(self.vms_gps.knots)
            self.db.write_stx3_ascii_message(gpsData,1)
        elif ( packetType == 'I'):
            #  Get the data from flight data.   Only first two bytes will be used.
            stx3Data = self.db.retrieve_flight_data_last('Flight_Data','parameter_value',parameter_id)
            print "* Integer Data --- "
            print stx3Data
            stx3Data_int = int(float(stx3Data))
            gpsData = 'I'+ ',' + gpsLattitude +',' + gpsLongitude +  ',' + str(stx3Data_int)
            self.db.write_stx3_ascii_message(gpsData,1)
        elif ( packetType == '1'):
            #  Get the data from flight data.   Only first two bytes will be used.
            stx3Data = self.db.retrieve_flight_data_last('Flight_Data','parameter_value',parameter_id)
            print "* Float 1 Data --- "
            print stx3Data
            gpsData = '1'+ ',' + gpsLattitude +',' + gpsLongitude + ',' + str(stx3Data)
            self.db.write_stx3_ascii_message(gpsData,1)
        elif ( packetType == '2'):
            #  Get the data from flight data.   Only first two bytes will be used.
            stx3Data = self.db.retrieve_flight_data_last('Flight_Data','parameter_value',parameter_id)
            print "* Float 2 Data --- "
            print stx3Data
            gpsData = '2'+ ',' + gpsLattitude +',' + gpsLongitude + ',' + str(stx3Data)
            self.db.write_stx3_ascii_message(gpsData,1)
        elif ( packetType == '3'):
            #  Get the data from flight data.   Only first two bytes will be used.
            stx3Data = self.db.retrieve_flight_data_last('Flight_Data','parameter_value',parameter_id)
            print "* Float 3 Data --- "
            print stx3Data
            gpsData = '3'+ ',' + gpsLattitude +',' + gpsLongitude + ',' + str(stx3Data)
            self.db.write_stx3_ascii_message(gpsData,1)
        elif ( packetType == '4'):
            #  Get the data from flight data.   Only first two bytes will be used.
            stx3Data = self.db.retrieve_flight_data_last('Flight_Data','parameter_value',parameter_id)
            print "* Float 4 Data --- "
            print stx3Data
            gpsData = '4'+ ',' + gpsLattitude +',' + gpsLongitude + ',' + str(stx3Data)
            self.db.write_stx3_ascii_message(gpsData,1)
        elif ( packetType == '5'):
            #  Get the data from flight data.   Only first two bytes will be used.
            stx3Data = self.db.retrieve_flight_data_last('Flight_Data','parameter_value',parameter_id)
            print "* Float 5 Data --- "
            print stx3Data
            gpsData = '5'+ ',' + gpsLattitude +',' + gpsLongitude + ',' + str(stx3Data)
            self.db.write_stx3_ascii_message(gpsData,1)
        elif ( packetType == 'X'):
            #  Get the data from flight data object. 
            stx3Data = self.db.retrieve_flight_data_last('Flight_Data_Object','parameter_value_object',parameter_id)
            print "* Parameter Object Data"
            print stx3Data
            gpsData = 'X'+ ',' + gpsLattitude +',' + gpsLongitude + ',' + str(stx3Data)
            self.db.write_stx3_ascii_message(gpsData,1)


        # Report the fix information to the GPS_Information table
        self.db.gps_write_GPS_fix_data(fixVal, gpsFixTypeVal, satellites_being_tracked, satellites_in_view, pdop, vdop, hdop)
        self.db.gps_satellite_data(satellites_in_view, satellites_being_tracked, self.vms_gps.SatellitesInTracked, self.vms_gps.SatellitesInView)
                
        # Write to the Location_Data table
        if self.vms_gps.fix!=0:
            if self.vms_gps.dateUTC == 0:
                self.db.gps_write_location_table(gpsLattitude, gpsLongitude, str(self.vms_gps.knots), 'error', str(self.vms_gps.altitude), 'GPS1',str(self.vms_gps.magTrue))
            else:
                self.db.gps_write_location_table(gpsLattitude, gpsLongitude, str(self.vms_gps.knots), str(self.vms_gps.dateUTC) + ' ' + str(self.vms_gps.timeUTC), str(self.vms_gps.altitude), 'GPS1',str(self.vms_gps.magTrue))
        else:
            self.db.gps_write_location_table('error', 'error', 'error', 'error', 'error', 'GPS1','error')

        if self.vms_gps.fix!=0:
        
            print 'Universal Time: ',self.vms_gps.timeUTC
            print 'Date: ',self.vms_gps.dateUTC
            if self.vms_gps.fix=='1':
                print 'GPS Fix (SPS)'
            elif self.vms_gps.fix=='2':
                print 'DGPS fix'
            elif self.vms_gps.fix=='3':
                print 'PPS fix'
            elif self.vms_gps.fix=='4':
                print 'Real Time Kinematic'
            elif self.vms_gps.fix=='5':
                print 'Float RTK'
            elif self.vms_gps.fix=='6':
                print 'estimated (dead reckoning)'
            elif self.vms_gps.fix=='7':
                print 'Manual input mode'
            elif self.vms_gps.fix=='8':
                print 'Simulation mode'
            else:
                print 'No Signal'

            if self.vms_gps.gpsFixType=='1':
                print 'No Fix'
            elif self.vms_gps.gpsFixType=='2':
                print '2D Fix'
            elif self.vms_gps.gpsFixType=='3':
                print '3D Fix'
            else:
                print 'none'
            
            print 'You are Tracking: ',self.vms_gps.sats,' satellites'
            print 'My Latitude: ',self.vms_gps.latDeg, 'Degrees ', self.vms_gps.latMin,' minutes ', self.vms_gps.latHem
            print 'My Longitude: ',self.vms_gps.lonDeg, 'Degrees ', self.vms_gps.lonMin,' minutes ', self.vms_gps.lonHem
            print 'My Speed: ', self.vms_gps.knots
            if isfloat(self.vms_gps.altitude):
                altitude_ft = float(self.vms_gps.altitude)*3.2808
            else:
                altitude_ft = 0
            print 'My Altitude: ',self.vms_gps.altitude,' m, and ',altitude_ft,' ft'
            print 'My Heading: ',self.vms_gps.magTrue,' deg '
            print 'Number of GSV Sentences: ',self.vms_gps.numDataSentences,'  '
            print 'Number of Satellites in View: ',self.vms_gps.NumberSatellitesInView,'  '
            print 'PDOP: ',self.vms_gps.PDOP,'  '
            print 'HDOP: ',self.vms_gps.HDOP,'  '
            print 'VDOP: ',self.vms_gps.VDOP,'  '
            print 'Satellites Tracked: ',self.vms_gps.SatellitesInTracked,'  '
            print 'Satellites In View: ',self.vms_gps.SatellitesInView,'  '

    def linux_set_time(self, time_tuple):

    
        print time_tuple
        
        if (time_tuple[0] > 2040):     # bug in adafruit gps when no GPS at all it forces a year of 2080 which causes crash
            correct_time = list(time_tuple)
            correct_time[0] = 2000
            time_tuple = tuple(correct_time)
            print time_tuple

        #
        # define CLOCK_REALTIME                     0
        CLOCK_REALTIME = 0

        print "in linux set time"
        class timespec(ctypes.Structure):
            _fields_ = [("tv_sec", ctypes.c_long),
                        ("tv_nsec", ctypes.c_long)]

        librt = ctypes.CDLL(ctypes.util.find_library("rt"))

        ts = timespec()
        ts.tv_sec = int( time.mktime( datetime.datetime( *time_tuple[:6]).timetuple() ) )
        ts.tv_nsec = time_tuple[6] * 1000000 # Millisecond to nanosecond

        librt.clock_settime(CLOCK_REALTIME, ctypes.byref(ts))
        
    def set_ls_system_time(self):
        global time_set
        print "------TIME SET FLAG------"
        print time_set
        # wait for GPS to warm up and write to the DB
        time.sleep(90)
        if not time_set: 
            time_tuple = self.db.build_time_tuple()
            if time_tuple != 'error':
                self.linux_set_time(time_tuple)
                time_set=True
                print "***** time was set *****"
                print "EVERYTHING GOOD"
        