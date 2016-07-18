#!/usr/bin/env python
"""
A module that handles retrieving applications from the ground server and
installing them into the space database.

Copyright (c) 2016, DornerWorks, Ltd.
"""

import syslog
import multiprocessing
import subprocess
import time
import traceback
import sys
import os

import vms_db_ground

# These commands require the use of the "sshpass" application since the
# paramiko python module does not support rsync

# Disable some pylint warnings that I don't care about
# pylint: disable=line-too-long,fixme

# Indicate that there is no ground connection by default
VMS_GROUND = None


class VmsFile(object):
    """
    A class that handles VMS file retrieve commands
    """
    def __init__(self):
        self.lock = multiprocessing.Lock()
        self.db_ground = None
        self.db_args = None

    def __del__(self):
        self.close()

    def open(self, **args):
        """
        Opens the connection with the ground database.
        """
        self.lock.acquire()
        if not self.db_ground:
            self.db_args = args
            self.db_ground = vms_db_ground.vms_db_ground(**self.db_args)
        else:
            self.db_ground.open()

    def close(self):
        """
        Releases the lock so that other ground file operations can be attempted.
        """
        self.db_ground.close()
        self.lock.release()

    def get_app(self, app_id):
        """
        Retrieves an application and associated data from the VMS ground server.
        """

        # First retrieve the application information from the ground server,
        # this way we don't need to reconnect to the ground DB later if the
        # connection drops while retracing the application.
        (info, params) = self.db_ground.get_application_info(app_id)

        # If we were able to retrieve the application information successfully,
        # retrieve the file using rsync.  This may take multiple attempts, so
        # if it fails, wait 1 minute and try again.  If the connection to the
        # ground drops while this is running, we'll just have to keep trying.
        if info:
            # If there is no file defined, raise an exception now and don't
            # attempt the upload.
            if not info['application_filename']:
                msg = 'filename not specified for application {}'.format(info)
                raise Exception(msg)

            options = {
                'host': self.db_args['address'],
                'username': self.db_args['fileserver_username'],
                'path': self.db_args['fileserver_pathname'],
                'file': info['application_filename'],
            }
            env = {'SSHPASS': self.db_args['fileserver_password']}

            # format the rsync command
            rsync_str = '/usr/bin/rsync -caqz --rsh="/usr/bin/sshpass -e ssh -l {username}" {host}:{path}/{file} /opt/qs/input/{file}'
            rsync_cmd = rsync_str.format(**options)
            while True:
                # pylint: disable=bare-except
                try:
                    # Run the rsync command
                    proc = subprocess.Popen(rsync_cmd, env=env)
                    status = proc.wait()
                    log_msg = 'rsync {0[host]}:{0[path]}/{0[file]} result = {1}'.format(options, status)
                    syslog.syslog(syslog.LOG_INFO, log_msg)
                except:
                    # Set a fake failure status to keep the loop running
                    status = 254

                    except_data = traceback.format_exception(*sys.exc_info())
                    log_msg = 'rsync {0[host]}:{0[path]}/{0[file]} exception! {1}'.format(options, except_data)
                    syslog.syslog(syslog.LOG_INFO, log_msg)

                # Did rsync complete successfully?  If so return the retrieved
                # info, otherwise sleep 1 minute and then try again later.
                if not status:
                    return (info, params)
                else:
                    time.sleep(60.0)
        return None


# pylint: disable=invalid-name
def process(db, cmd, data):
    """
    The function required for the vms class to call this one to handle custom
    VMS file functions.
    """
    # pylint: disable=too-many-branches,global-statement,protected-access,too-many-statements
    syslog.syslog(syslog.LOG_INFO, 'Vms file {}:{}'.format(cmd, data))

    # Connect to the MCP Target if the connection method is recognized
    args = db.get_db_ground_args()
    ground_db_args = {
        'address': args['server'],
        'port': 3306,
        'username': args['username'],
        'password': args['password'],
        'cert': None,
        'dbname': 'stepSATdb_Flight',
    }

    global VMS_GROUND
    if not VMS_GROUND:
        VMS_GROUND = VmsFile()
    VMS_GROUND.open(**ground_db_args)

    # Now process the command
    cmd = cmd.lower()
    if cmd == 'upload_application':
        (app_info, app_params) = VMS_GROUND.get_app(data)
        if app_info:
            # if file was retrieved successfully, and the get_app() function
            # returned the required database information, insert that info
            # into the DB now.
            app_info['application_state'] = 80
            app_info['application_status'] = 'GATEWAY Storage'
            db.add_app(app_info, app_params)
            result = True
        else:
            msg = 'Unable to retrieve info from ground server for app: {}'.format(data)
            db._log_msg(msg)
            result = False
    elif cmd == 'remove_application':
        info = db.get_app_info(ident=data)
        # If we were able to retrieve the application, remove the application
        # from the filesystem.
        if info:
            # Ensure that the filename is specified before we attempt to
            # remove it
            if not info['application_filename']:
                msg = 'filename not specified for application {}'.format(info)
                raise Exception(msg)
            os.remove('/opt/qs/input/{}'.format(info['application_filename']))
            # If the file removed successfully, update the application state.
            # The local state will get synced to the ground eventually.
            db.set_application_state(info, 50, 'On Ground', None)
    else:
        msg = 'Unsupported VMS file command: {}'.format(cmd)
        db._log_msg(msg)
        result = False

    # Close the connection
    VMS_GROUND.close()

    return result
