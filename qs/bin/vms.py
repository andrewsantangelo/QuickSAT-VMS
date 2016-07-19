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


def unknown_command_wrapper(db_args, cmd):
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
                result = cmd_process_func(local_db, subcmd[1], cmd['data'])
                status = int(not result)
                local_db.complete_commands(cmd, result)
            except KeyboardInterrupt as e:
                raise e
            except:
                status = 4
                local_db.complete_commands(cmd, False, traceback.format_exception(*sys.exc_info()))
    else:
        status = 2
        # This is not a custom command, just log it as an unknown error
        msg = 'Unknown command {}:{}'.format(cmd['command'], cmd)
        local_db.complete_commands(cmd, False, msg)

    return status


class vms(object):
    # pylint: disable=unused-argument
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

        # Keep track of the unknown command processes to ensure they aren't
        # deleted by the garbage collector.
        self.cmd_processes = []

        self.threads = []

        # Open the syslog
        syslog.openlog()
        syslog.syslog(syslog.LOG_NOTICE, 'Started')

        # For now, use the command poll rate to run the "command log monitor" function
        t = periodic_timer.PeriodicTimer(self.process, self.db.retrieve_command_log_poll_rate())
        self.threads.append(t)

        # Use a pre-defined radio status poll time for now
        t = periodic_timer.PeriodicTimer(self.radio_status, 60)
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

        # System_Messages uses command_syslog_push_rate
        t = periodic_timer.PeriodicTimer(self.sync_system_messages, self.db.retrieve_command_syslog_push_rate())
        self.threads.append(t)

        # Systems_Applications uses retrieve_command_log_poll_rate
        #    Update the ground station Systems_Application table - this tells the ground station the state of the applications on the SV.
        #
        t = periodic_timer.PeriodicTimer(self.update_system_applications_state_to_gnd, self.db.retrieve_command_log_poll_rate())
        self.threads.append(t)

        # Determine if LinkStar Duplex Radio is installed - first get the data if the radio is installed

        ls_duplex_installed = self.db.ls_duplex_installed_state()

        # IF the duplex radio is installed, send the duplex information to the ground periodically
        if ls_duplex_installed == 1:
            # Linkstar duplex state pushing uses command_log_rate
            t = periodic_timer.PeriodicTimer(self.sync_linkstar_duplex_state, self.db.retrieve_command_log_poll_rate())
            self.threads.append(t)

    def __del__(self):
        for t in self.threads:
            t.stop()
        for proc in self.cmd_processes[:]:
            proc.kill()
        syslog.syslog(syslog.LOG_NOTICE, 'Shutting down')
        syslog.closelog()

    def radio_status(self):
        # Have the VMS DB connection retrieve and update the radio status
        self.linkstar.get_radio_status()
        # Keep the poll rate constant for now, it shouldn't change
        return 39

    def run(self):
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
                self.sync_recording_sessions(cmd)
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

    def handle_unknown_command(self, key, cmd):
        # Mark the command as being processed
        self.db.start_command(cmd)

        # Now spawn a separate process to handle the command
        proc = multiprocessing.Process(target=unknown_command_wrapper, name=cmd['command'], args=(self.args['vms'], cmd))
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
        if self.db_ground:
            return True
        else:
            try:
                self.db_ground = vms_db_ground.vms_db_ground(**self.args['vms_ground'])
                print "connected to ground db"
            except:
                raise
            return self.db_ground

    """
    Most functions that use the radio will need to check the radio status first
    """

    def sync_flight_data_object(self, cmd=None):
        self.linkstar.get_radio_status()
        if self.db.check_test_connection():
            if self.check_db_ground_connection():
                print "flight data object test"
                # pylint: disable=bare-except
                try:
                    self.db.sync_selected_db_table('Flight_Data_Object')
                    self.db_ground.sync_selected_db_table('Flight_Data_Object')
                    if cmd:
                        self.db.complete_commands(cmd, True)
                except KeyboardInterrupt as e:
                    raise e
                except:
                    if cmd:
                        self.db.complete_commands(cmd, False, traceback.format_exception(*sys.exc_info()))

    def sync_flight_data_binary(self, cmd=None):
        self.linkstar.get_radio_status()
        if self.db.check_test_connection():
            if self.check_db_ground_connection():
                print "flight data binary test"
                # pylint: disable=bare-except
                try:
                    self.db.sync_selected_db_table('Flight_Data_Binary')
                    self.db_ground.sync_selected_db_table('Flight_Data_Binary')
                    if cmd:
                        self.db.complete_commands(cmd, True)
                except:
                    if cmd:
                        self.db.complete_commands(cmd, False, traceback.format_exception(*sys.exc_info()))

    def sync_flight_data(self, cmd=None):
        self.linkstar.get_radio_status()
        if self.db.check_test_connection():
            if self.check_db_ground_connection():
                print "flight data test"
                # pylint: disable=bare-except
                try:
                    self.db.sync_selected_db_table('Flight_Data')
                    self.db_ground.sync_selected_db_table('Flight_Data')
                    if cmd:
                        self.db.complete_commands(cmd, True)
                except:
                    if cmd:
                        self.db.complete_commands(cmd, False, traceback.format_exception(*sys.exc_info()))

    def sync_system_messages(self, cmd=None):
        self.linkstar.get_radio_status()
        if self.db.check_test_connection():
            if self.check_db_ground_connection():
                print "system message test"
                # pylint: disable=bare-except
                try:
                    self.db.sync_selected_db_table('System_Messages')
                    self.db_ground.sync_selected_db_table('System_Messages')
                    if cmd:
                        self.db.complete_commands(cmd, True)
                except:
                    if cmd:
                        self.db.complete_commands(cmd, False, traceback.format_exception(*sys.exc_info()))

    def sync_recording_sessions(self, cmd=None):
        self.linkstar.get_radio_status()
        if self.db.check_test_connection():
            if self.check_db_ground_connection():
                print "recording sessions test"
                self.db.sync_recording_sessions()
                self.db_ground.sync_recording_sessions()
                print "writing recording session state"
                self.db_ground.sync_recording_session_state()
                self.db_ground.sync_flight_pointers()
                if cmd:
                    self.db.complete_commands(cmd, True)

    def sync_command_log_sv_to_ground(self, cmd=None):
        # sync from sv to ground
        # read from sv db
        # write to ground db
        # update sv db
        self.linkstar.get_radio_status()
        if self.db.check_test_connection():
            if self.check_db_ground_connection():
                # try:
                commands = self.db.read_command_log()
                self.db_ground.add_ground_command_log(commands)  # write to ground db with pushed_to_ground set to true
                self.db.update_sv_command_log(commands)  # rewrite to sv db with pushed_to_ground set to true
                if cmd:
                    self.db.complete_commands(cmd, True)
                print "command log sv to ground test"
                # except:
                #    if cmd:
                #        self.db.complete_commands(cmd, False, traceback.format_exception(*sys.exc_info()))

    def sync_command_log_ground_to_sv(self, cmd=None):
        # sync from ground to sv
        # run pending commands
        self.linkstar.get_radio_status()
        if self.db.check_test_connection():
            if self.check_db_ground_connection():
                # try:
                ground_commands = self.db_ground.read_command_log()
                self.db.add_sv_command_log(ground_commands)  # write to sv db with read_from_sv set to true
                self.db_ground.update_ground_command_log(ground_commands)  # rewrite to ground db with read_from_sv set to true

                if cmd:
                    self.db.complete_commands(cmd, True)
                print "command log ground to sv test"
                # except:
                #    if cmd:
                #       self.db.complete_commands(cmd, False,
                #           traceback.format_exception(*sys.exc_info()))

    def sync_linkstar_duplex_state(self, cmd=None):
        self.linkstar.get_radio_status()
        if self.db.check_test_connection():
            if self.check_db_ground_connection():
                print "sync_linkstar_duplex test"
                # pylint: disable=bare-except
                try:
                    self.db.sync_selected_db_table('LinkStar_Duplex_State')
                    self.db_ground.sync_selected_db_table('LinkStar_Duplex_State')
                    if cmd:
                        self.db.complete_commands(cmd, True)
                except:
                    if cmd:
                        self.db.complete_commands(cmd, False, traceback.format_exception(*sys.exc_info()))

    def update_system_applications_state_to_gnd(self, cmd=None):
        # read from sv db
        # write to ground db
        self.linkstar.get_radio_status()
        if self.db.check_test_connection():
            if self.check_db_ground_connection():
                # pylint: disable=bare-except
                try:
                    print "system_applications sv to ground function"
                    system_applications_data = self.db.read_system_applications()
                    self.db_ground.update_system_applications_gnd(system_applications_data)  # write to ground db the latest state of the applications
                    if cmd:
                        self.db.complete_commands(cmd, True)
                except:
                    if cmd:
                        self.db.complete_commands(cmd, False, traceback.format_exception(*sys.exc_info()))

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
