#!/usr/bin/env python

import time
import argparse
import subprocess
import sys
import traceback

import vms_db
import periodic_timer

def get_app_info(db, app_id):
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
            WHERE `System_Applications`.`application_id` = %s
    '''
    info = db._execute(stmt, (app_id,))
    # There should only be 1 row in response
    if info:
        return info[0]
    else:
        return None

def start_apps(db, path, apps):
    threads = []
    for a in apps:
        info = get_app_info(db, a)

        args = [
            '{}/{}'.format(path, info['name']),
            '--server={}'.format(db.config['host']),
            '--port={}'.format(db.config['port']),
            '--username={}'.format(db.config['user']),
            '--password={}'.format(db.config['password']),
            '--param_id={}'.format(info['param'])
        ]
        try:
            p = subprocess.Popen(args)
            threads.append({'process': p, 'info': info})
        except:
            status = 'On Host - Unable to start app'
            msg = 'Unable to start App {} "{}/{}":\n{}'.format(info['part'], path, info['name'], traceback.format_exception(*sys.exc_info()))
            db.set_application_state(info, 205, status, msg)

    for t in threads:
        status = 'On Host - App Initializing'
        db.set_application_state(info, 180, status, None)

        # Create a monitoring thread
        args = (t['info'], t['process'])
        t['thread'] = periodic_timer.PeriodicTimer(action=monitor_app, delay=60, args=args)
        t['thread'].start()
    return threads

def monitor_app(info, process, _state=[180]):
    # Check if app is still running
    exitcode = process.poll()

    # Set status
    if exitcode:
        if _state[0] != 200:
            status = 'On Host - App Error'
            msg = 'VM/App "{}" exited with status {}'.format(info['part'], exitcode)
            db.set_application_state(info, 200, status, msg)
            _state[0] = 200
    else:
        if _state[0] != 100:
            status = 'On Host - App Operational'
            db.set_application_state(info, 100, status, None)
            _state[0] = 100

def run(threads):
    # Watch for signals
    try:
        while True:
            time.sleep(600.0)
    # TODO: handle other interrupts/exceptions and close down the spawned apps
    # (and update status?)
    except KeyboardInterrupt:
        for t in threads:
            t['thread'].stop()
            if not t['process'].poll():
                t['process'].kill()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Starts and monitors applications')

    # Find out which app(s) to start and monitor
    parser.add_argument('--app', action='append', help='ID of application(s) that should be started and monitored')

    # Path to apps to execute
    parser.add_argument('--app-path', default='/opt/mcp/images', help='Path to where application executables are stored')

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

    # Allow parameters to be specified as command line arguments
    parser.add_argument('--interactive', action='store_true', help='Allow arguments to be specified on the command line rather than from the kernel bootargs')
    args = parser.parse_args()

    # If the interactive flag is not set, parse the kernel bootargs for
    # arguments
    if not args.interactive:
        f = open('/proc/cmdline')
        args = parser.parse_known_args(f.read().strip().split())[0]
        f.close()

    if args.no_password:
        args.password = None
    if args.no_username:
        args.username = None

    # Connect to the QS/VMS DB
    db = vms_db.vms_db(**vars(args))

    # Ensure that at least one app is specified
    assert args.app

    # Start the specified applications
    threads = start_apps(db, args.app_path, args.app)
    run(threads)

