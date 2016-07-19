#!/usr/bin/env python
"""
A module that handles retrieving applications from the ground server and
installing them into the space database.

Copyright (c) 2016, DornerWorks, Ltd.
"""

import syslog
import subprocess
import time
import traceback
import sys
import os
import errno


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
        self.db_args = None

    def __del__(self):
        pass

    def open(self, **kwargs):
        """
        Opens the connection with the ground database.
        """
        self.db_args = kwargs

    def close(self):
        """
        Releases the lock so that other ground file operations can be attempted.
        """
        pass

    def get_app(self, info):
        """
        Retrieves an application and associated data from the VMS ground server.
        """

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
                proc = subprocess.Popen(rsync_cmd, shell=True, env=env)
                status = proc.wait()
                log_msg = 'rsync {0[host]}:{0[path]}/{0[file]} result = {1}'.format(options, status)
                syslog.syslog(syslog.LOG_INFO, log_msg)
            except OSError as exp:
                # If the error is "no such file", re-raise the exception
                # and stop the command.
                if exp.errno == errno.ENOENT:
                    raise exp
                else:
                    # Set a fake failure status to keep the loop running
                    status = 254

                    except_data = traceback.format_exception(*sys.exc_info())
                    log_msg = 'rsync {0[host]}:{0[path]}/{0[file]} exception! {1}'.format(options, except_data)
                    syslog.syslog(syslog.LOG_INFO, log_msg)
            except:
                # all other exceptions, keep trying
                status = 254

                except_data = traceback.format_exception(*sys.exc_info())
                log_msg = 'rsync {0[host]}:{0[path]}/{0[file]} exception! {1}'.format(options, except_data)
                syslog.syslog(syslog.LOG_INFO, log_msg)

            # Did rsync complete successfully?  If so return the retrieved
            # info, otherwise sleep 1 minute and then try again later.
            if not status:
                return True
            else:
                time.sleep(60.0)


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
        'fileserver_username': args['fileserver_username'],
        'fileserver_pathname': args['fileserver_pathname'],
        'fileserver_password': args['fileserver_password'],
    }

    global VMS_GROUND
    if not VMS_GROUND:
        VMS_GROUND = VmsFile()
    VMS_GROUND.open(**ground_db_args)

    # Now process the command
    cmd = cmd.lower()
    if cmd == 'upload_application':
        info = db.get_app_info(ident=data)
        if info:
            result = VMS_GROUND.get_app(info)
            if result:
                db.set_application_state(info, 80, 'GATEWAY Storage', None)
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

if __name__ == '__main__':
    # pylint: disable=wrong-import-position,too-many-function-args,superfluous-parens
    import vms_db
    test_db = vms_db.vms_db(address='127.0.0.1', port=3306, username='root', password='quicksat1', cert=None, dbname='stepSATdb_Flight')
    if len(sys.argv) > 1:
        testcmd = sys.argv[1]
    if len(sys.argv) > 2:
        appid = sys.argv[2]
    testresult = process(test_db, testcmd, appid)
    print('cmd {},{} = {}'.format(testcmd, appid, testresult))
