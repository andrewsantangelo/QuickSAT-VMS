#!/usr/bin/python
# Copyright (c) 2017 sci_Zone, Inc.
# Author: Andrew Santangelo
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.

# Can enable debug output by uncommenting:
#import logging
#logging.basicConfig(level=logging.DEBUG)

import Adafruit_BMP.BMP085 as BMP085

import argparse
import vms_db
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
import periodic_timer

import ctypes
import ctypes.util
import time
from time import sleep


# Default constructor will pick a default I2C bus.
#
# For the Raspberry Pi this means you should hook up to the only exposed I2C bus
# from the main GPIO header and the library will figure out the bus number based
# on the Pi's revision.
#

# Optionally you can override the bus number:
#sensor = BMP085.BMP085(busnum=2)

# You can also optionally change the BMP085 mode to one of BMP085_ULTRALOWPOWER,
# BMP085_STANDARD, BMP085_HIGHRES, or BMP085_ULTRAHIGHRES.  See the BMP085
# datasheet for more details on the meanings of each mode (accuracy and power
# consumption are primarily the differences).  The default mode is STANDARD.
#sensor = BMP085.BMP085(mode=BMP085.BMP085_ULTRAHIGHRES)

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




class vms_bmpsensor(object):
    def __init__(self, vms_address, vms_port, vms_cert, vms_username, vms_password, vms_dbname, **kwargs ):
        # For the Beaglebone Black the library will assume bus 1 by default, which is
        # exposed with SCL = P9_19 and SDA = P9_20.
        self.sensor = BMP085.BMP085()

        # Save the arguments
        self.args = {
            'vms': {
                'address': vms_address,
                'port': vms_port,
                'username': vms_username,
                'password': vms_password,
                'cert': vms_cert,
                'dbname': vms_dbname
            }
        }

        # Connect to the QS/VMS DB
        self.db = vms_db.vms_db(**self.args['vms'])
        print "ARGS SET"
        # Some mechanisms to allow threads to be paused by a command handler
        self.thread_run_event = multiprocessing.Event()

        # Keep track of the unknown command processes to ensure they aren't
        # deleted by the garbage collector.
        self.cmd_processes = []

        self.threads = []

        # Open the syslog
        syslog.openlog()
        syslog.syslog(syslog.LOG_NOTICE, 'Started')

        print "set periodic timer for writing BMP data"
        t = periodic_timer.PeriodicTimer(self.write_bmp_data_to_db, 300)
        self.threads.append(t)
        
        
    def __del__(self):
        for t in self.threads:
            t.stop()
        for proc in self.cmd_processes[:]:
            proc.kill()
        syslog.syslog(syslog.LOG_NOTICE, 'Shutting down')
        syslog.closelog()
        
    def run(self):
        print "in run"
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

    def write_bmp_data_to_db(self):
        print('Temp = {0:0.2f} *C'.format(self.sensor.read_temperature()))
        self.db.write_flight_data('Temperature',str(self.sensor.read_temperature()))
        print('Pressure = {0:0.2f} Pa'.format(self.sensor.read_pressure()))
        self.db.write_flight_data('Pressure',str(self.sensor.read_pressure()))
        print('Altitude = {0:0.2f} m'.format(self.sensor.read_altitude()))
        self.db.write_flight_data('Altitude',str(self.sensor.read_altitude()))
        print('SeaLevelPressure = {0:0.2f} Pa'.format(self.sensor.read_sealevel_pressure()))
        self.db.write_flight_data('SeaLevelPressure', str(self.sensor.read_sealevel_pressure()))



if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Monitor the QS/VMS command table periodically')
    parser.add_argument('--vms-address', default='127.0.0.1', help='address (IP or URL) of QS/VMS database')
    parser.add_argument('--vms-port', type=int, default=3306, help='UDP port used by the QS/VMS database')
    parser.add_argument('--vms-cert', help='location of SSL certificate to use to connect to QS/VMS database')
    parser.add_argument('--vms-dbname', default='stepSATdb_Flight', help='name of the QS/VMS database')
    parser.add_argument('--vms-username', default='root', help='username for the QS/VMS database')
    parser.add_argument('--no-vms-username', action='store_true', help='specify that a username is not required for the QS/VMS database (overrides --vms-username)')
    parser.add_argument('--vms-password', default='Quicksat!1', help='password for the QS/VMS database')
    parser.add_argument('--no-vms-password', action='store_true', help='specify that a password is not required for the QS/VMS database (overrides --vms-password)')

    print "Set up"
    # Parse the command line arguments
    args = parser.parse_args()

    if args.no_vms_password:
        args.vms_password = None
    if args.no_vms_username:
        args.vms_username = None
    print "args set"

    myBMP=bmp_sensor(**vars(args))
    while(1):
        # Test code to separately monitor the BPM unit as a stand alone application
        myBMP.write_bmp_data_to_db()
        print('Temp = {0:0.2f} *C'.format(myBMP.sensor.read_temperature()))
        print('Pressure = {0:0.2f} Pa'.format(myBMP.sensor.read_pressure()))
        print('Altitude = {0:0.2f} m'.format(myBMP.sensor.read_altitude()))
        print('SealevelPressure = {0:0.2f} Pa'.format(myBMP.sensor.read_sealevel_pressure()))
        print '\r\n'
        time.sleep(60)
