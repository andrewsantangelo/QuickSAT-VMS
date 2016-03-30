#!/usr/bin/env python
"""
Module that will periodically check the status of MCP on the target board
(HOST) and report that status back to the QS/VMS database.
"""

import argparse
import syslog
import time

# Easiest way to do sftp, install with
#   $ pip install paramiko
# install pip as described here:
#   https://pypi.python.org/pypi/setuptools
import paramiko

import vms_db

# Disable some pylint warnings that I don't care about
# pylint: disable=line-too-long,fixme


def get_mcp_status(address, port, username, password):
    """
    Function that connects to the target board, and then retrieves the MCP
    status.
    """
    # Connect to the target board, get the status of MCP, and close the connection
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.load_system_host_keys()
    ssh.connect(address, port, username, password)

    # Run the status command to check on MCP
    _, out, err = ssh.exec_command('service mcp status')
    exit_status = out.channel.recv_exit_status()
    out_data = out.channel.recv(1000)
    err_data = err.channel.recv(1000)
    ssh.close()

    return (exit_status, out_data, err_data)

if __name__ == '__main__':
    # pylint: disable=invalid-name,star-args
    parser = argparse.ArgumentParser(description='Monitors health of the MCP application')

    # QS/VMS parameters
    db_group = parser.add_argument_group('VMS database arguments')
    db_group.add_argument('--address', default='127.0.0.1', help='address (IP or URL) of QS/VMS database')
    db_group.add_argument('--port', type=int, default=3306, help='UDP port used by the QS/VMS database')
    db_group.add_argument('--cert', help='location of SSL certificate to use to connect to QS/VMS database')
    db_group.add_argument('--dbname', default='stepSATdb_Flight', help='name of the QS/VMS database')
    db_group.add_argument('--username', default='root', help='username for the QS/VMS database')
    db_group.add_argument('--no-username', action='store_true', help='specify that a username is not required for the QS/VMS database (overrides --username)')
    db_group.add_argument('--password', default='quicksat1', help='password for the QS/VMS database')
    db_group.add_argument('--no-password', action='store_true', help='specify that a password is not required for the QS/VMS database (overrides --password)')

    args = parser.parse_args()

    if args.no_vms_password:
        args.vms_password = None
    if args.no_vms_username:
        args.vms_username = None

    # Identify this service as started
    syslog.syslog(syslog.LOG_INFO, 'Starting MCP monitor')

    # Connect to the QS/VMS DB
    db = vms_db.vms_db(**vars(args))

    # Retrieve the address of the board that MCP is running on
    config = db.get_board_connection_data('mcp')
    info = db.get_app_info(name='mcp')

    # Mark the initial MCP status as presumed to be initializing
    msg = 'On Host - App Initializing'
    db.set_application_state(info, 180, msg, None)

    while True:
        # TODO: monitor MCP watchdog GPIO signal
        time.sleep(60)
        (status, stdout, stderr) = get_mcp_status(config['address'], config['port'], config['username'], config['password'])

        #   0 = program is running
        #   1 = program is not running and the pid file exists
        #   3 = program is not running
        #   4 = unable to determine status
        if status != 0:
            msg = 'Failed to get MCP status {}: {}/{}'.format(status, stdout, stderr)
            syslog.syslog(syslog.LOG_ERR, msg)

            msg = 'On Host - App Error'
            err_msg = 'MCP status = {}'.format(status)
            db.set_application_state(info, 200, msg, err_msg)
        else:
            msg = 'On Host - App Operational'
            db.set_application_state(info, 100, msg, None)
