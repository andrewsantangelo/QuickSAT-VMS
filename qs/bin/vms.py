#!/usr/bin/env python
"""
Module that handles the core QS/VMS processing actions.
"""

import traceback
import sys
import time
import json
import syslog
import importlib
import operator
import multiprocessing

import vms_db
import periodic_timer
import vms_db_ground
import ls_comm_flight_stream
import linkstar

# Disable some pylint warnings that I don't care about
# pylint: disable=line-too-long,fixme,invalid-name,too-many-public-methods,too-many-arguments
#
# TEMPORARY:
# pylint: disable=missing-docstring


def write_json_data(data, filename):
    f = open(filename, 'w')
    f.write(json.dumps(data))
    f.close()


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
            'fsdata': {
                'flight-stream': flight_stream_flag
            }
        }
        self.linkstar = linkstar.linkstar(**self.args['vms'])

        # Connect to the QS/VMS DB
        self.db = vms_db.vms_db(**self.args['vms'])

        gs_args = self.db.get_db_ground_args()

        self.args['vms_ground'] = {
            'address': gs_args['server'],
            'port': vms_port,
            'username': gs_args['username'],
            'password': gs_args['password'],
            'cert': vms_cert,
            'dbname': vms_dbname
        }
        # self.db_ground = vms_db_ground.vms_db_ground(**self.args['vms_ground'])
        self.db_ground = None

        self.args['lsav'] = {
            'address': vms_address,
            'port': vms_port,
            'username': vms_username,
            'password': vms_password,
            'cert': vms_cert,
            'dbname': 'stepSATdb_FlightAV'
        }

        # Define ls_comm_flight_stream
        if flight_stream_flag == 'ENABLED':
            self.db_fS = ls_comm_flight_stream.ls_comm_flight_stream(**self.args['lsav'])

        # Some mechanisms to allow threads to be paused by a command handler
        self.thread_run_event = multiprocessing.Event()

        # Keep track of the unknown command processes to ensure they aren't
        # deleted by the garbage collector.
        self.cmd_processes = []

        self.threads = []

        # Open the syslog
        syslog.openlog()
        syslog.syslog(syslog.LOG_NOTICE, 'Started')

        # Determine if LinkStar Duplex Radio is installed - first get the data if the radio is installed
        ls_duplex_installed = self.db.ls_duplex_installed_state()

        # Determine if LinkStar Simplex STX Radio is installed - first get the data if the radio is installed
        # ls_simplexstx3_installed = = self.db.ls_simplexstx3_installed_state()

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

        # For now, use the command poll rate to run the "command log monitor" function
        t = periodic_timer.PeriodicTimer(self.process, self.db.retrieve_command_log_poll_rate())
        self.threads.append(t)

        # Use a pre-defined radio status poll time for now
        t = periodic_timer.PeriodicTimer(self.radio_status, 35)
        self.threads.append(t)

        # Flight_Data and Flight_Data_Object use data_download_push_rate
        t = periodic_timer.PeriodicTimer(self.sync_flight_data, self.db.retrieve_data_download_push_rate())
        self.threads.append(t)

        t = periodic_timer.PeriodicTimer(self.sync_flight_data_object, self.db.retrieve_data_download_push_rate())
        self.threads.append(t)

        # Flight_Data_Binary uses binary_data_push_rate
        t = periodic_timer.PeriodicTimer(self.sync_flight_data_binary, self.db.retrieve_binary_data_push_rate())
        self.threads.append(t)

        # Command_Log_ground_to_sv uses command_poll_rate
        t = periodic_timer.PeriodicTimer(self.sync_command_log_ground_to_sv, self.db.retrieve_command_log_poll_rate())
        self.threads.append(t)

        # Command_Log_sv_to_ground uses command_push_rate
        t = periodic_timer.PeriodicTimer(self.sync_command_log_sv_to_ground, self.db.retrieve_command_log_push_rate())
        self.threads.append(t)

        # System_Messages uses command_syslog_push_rate
        t = periodic_timer.PeriodicTimer(self.sync_system_messages, self.db.retrieve_command_syslog_push_rate())
        self.threads.append(t)

        # recording_sessions uses command_syslog_push_rate
        t = periodic_timer.PeriodicTimer(self.sync_vms_recording_sessions, 37)
        self.threads.append(t)

        # Systems_Applications uses retrieve_command_log_poll_rate
        #    Update the ground station Systems_Application table - this tells the ground station the state of the applications on the SV.
        #

        t = periodic_timer.PeriodicTimer(self.update_system_applications_state_to_gnd, 38)
        self.threads.append(t)

        # t = periodic_timer.PeriodicTimer(self.update_system_applications_state_to_gnd, 38)
        # self.threads.append(t)

        # IF the SIMPLEX, LinkStar-STX3 is installed, beacon create a data packet group and transmit to the ground
        # if ls_simplexstx3_installed == 1:
        #   t=periodic_timer.PeriodicTimer(self.transmit_packet_group, self.db.retrieve_packet_group_xmit_rate())
        #   self.threads.append(t)

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

        try:
            while True:
                time.sleep(60.0)
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
        del self.db_ground
        self.db_ground = None

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
        if not cmd:
            self.thread_run_event.wait()

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
        if not cmd:
            self.thread_run_event.wait()

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
        if not cmd:
            self.thread_run_event.wait()

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
        if not cmd:
            self.thread_run_event.wait()

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
        if not cmd:
            self.thread_run_event.wait()

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
