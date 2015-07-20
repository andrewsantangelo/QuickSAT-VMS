#!/usr/bin/env python

import argparse
import vms
import syslog
import sys
import traceback

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Monitor the QS/VMS command table periodically')
    parser.add_argument('--vms-address', default='127.0.0.1', help='address (IP or URL) of QS/VMS database')
    parser.add_argument('--vms-port', type=int, default=3306, help='UDP port used by the QS/VMS database')
    parser.add_argument('--vms-cert', help='location of SSL certificate to use to connect to QS/VMS database')
    parser.add_argument('--vms-dbname', default='stepSATdb_Flight', help='name of the QS/VMS database')
    parser.add_argument('--vms-username', default='root', help='username for the QS/VMS database')
    parser.add_argument('--no-vms-username', action='store_true', help='specify that a username is not required for the QS/VMS database (overrides --vms-username)')
    parser.add_argument('--vms-password', default='quicksat', help='password for the QS/VMS database')
    parser.add_argument('--no-vms-password', action='store_true', help='specify that a password is not required for the QS/VMS database (overrides --vms-password)')
    parser.add_argument('--mcp-address', required=True, help='address (IP or URL) of the system that MCP is installed on')
    parser.add_argument('--mcp-port', type=int, default=22, help='UDP port used by the system that MCP is installed on')
    parser.add_argument('--mcp-username', default='root', help='username for the system that MCP is installed on')
    parser.add_argument('--no-mcp-username', action='store_true', help='specify that a username is not required for the MCP system (overrides --mcp-username)')
    parser.add_argument('--mcp-password', default='root', help='password for the system that MCP is installed on')
    parser.add_argument('--no-mcp-password', action='store_true', help='specify that a password is not required for the MCP system (overrides --mcp-username)')
    parser.add_argument('--domu-ip-range', default='', help='the IP address range to use for the VMs (DHCP used when this option is blank)')

    # Parse the command line arguments
    args = parser.parse_args()

    if args.no_vms_password:
        args.vms_password = None
    if args.no_vms_username:
        args.vms_username = None

    if args.no_mcp_password:
        args.mcp_password = None
    if args.no_mcp_username:
        args.mcp_username = None

    # Catch any exceptions, log the error and then restart the command 
    # processing service.  We can't assume that the DB connection is still 
    # functional, so just log the error to the syslog.
    run = True
    while run:
        try:
            # All of the required arguments should be present, so just pass 
            # a dict() object to the vms class constructor
            conn = vms.vms(**vars(args))
            conn.run()
            run = False
        except KeyboardInterrupt as e:
            msg = 'caught keyboard interrupt, exiting...'
            syslog.syslog(syslog.LOG_INFO, msg)
            run = False
        except:
            msg = 'RESTARTING, caught exception: {}'.format(traceback.format_exception(*sys.exc_info()))
            syslog.syslog(syslog.LOG_ERR, msg)
            run = False


