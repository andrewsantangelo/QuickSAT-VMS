#!/usr/bin/env python

import time
import argparse

import vms_db

app_prep_stmt = 'INSERT INTO `stepSATdb_Flight`.`System_Applications` (`application_id`, `application_name`, `application_state`, `application_status`, `virtual_machine_id`, `Configuration_Parts_part_key`, `Configuration_Parts_Configuration_configuration_key`, `Configuration_Parts_Configuration_Mission_mission_key`) VALUES (%(application_id)s, %(application_name)s, \'80\', \'GATEWAY Storage\', %(virtual_machine_id)s, %(Configuration_Parts_part_key)s, %(Configuration_Parts_Configuration_configuration_key)s, %(Configuration_Parts_Configuration_Mission_mission_key)s)'

vm_prep_stmt = 'INSERT INTO `stepSATdb_Flight`.`Virtual_Machines` (`virtual_machine_id`, `virtual_machine_name`) VALUES (%(virtual_machine_id)s, %(virtual_machine_name)s)'

param_prep_stmt = 'INSERT INTO `stepSATdb_Flight`.`Parameter_ID_Table`(`parameter_id`, `System_Applications_application_id`) VALUES (%(parameter_id)s, %(System_Applications_application_id)s)'

cmd_add_stmt = 'INSERT INTO `stepSATdb_Flight`.`Command_Log`(`time_of_command`, `command`, `command_state`, `Recording_Sessions_recording_session_id`, `command_data`) VALUES (NOW(), \'ADD_VMAPP\', \'Pending\', (SELECT MAX(`Recording_Sessions`.`recording_session_id`) FROM `stepSATdb_Flight`.`Recording_Sessions`), %(application_id)s)'

cmd_remove_stmt = 'INSERT INTO `stepSATdb_Flight`.`Command_Log`(`time_of_command`, `command`, `command_state`, `Recording_Sessions_recording_session_id`, `command_data`) VALUES (NOW(), \'REMOVE_VMAPP\', \'Pending\', (SELECT MAX(`Recording_Sessions`.`recording_session_id`) FROM `stepSATdb_Flight`.`Recording_Sessions`), %(application_id)s)'

app_config = {
    'prime1app': {
        'application_id': 1,
        'System_Applications_application_id': 1,
        'application_name': 'prime',
        'virtual_machine_name': 'prime1app',
        'virtual_machine_id': 1,
        'Configuration_Parts_part_key': 'prime_test_app_00001',
        'Configuration_Parts_Configuration_configuration_key': 1,
        'Configuration_Parts_Configuration_Mission_mission_key': 1,
        'parameter_id': 1,
    },
    'prime2app': {
        'application_id': 2,
        'System_Applications_application_id': 2,
        'application_name': 'prime',
        'virtual_machine_name': 'prime2app',
        'virtual_machine_id': 2,
        'Configuration_Parts_part_key': 'prime_test_app_00002',
        'Configuration_Parts_Configuration_configuration_key': 1,
        'Configuration_Parts_Configuration_Mission_mission_key': 1,
        'parameter_id': 2,
    },
    'sineapp'  : {
        'application_id': 3,
        'System_Applications_application_id': 3,
        'application_name': 'sine',
        'virtual_machine_name': 'sineapp',
        'virtual_machine_id': 3,
        'Configuration_Parts_part_key': 'sine_test_app_00001',
        'Configuration_Parts_Configuration_configuration_key': 1,
        'Configuration_Parts_Configuration_Mission_mission_key': 1,
        'parameter_id': 3,
    },
    'sine2app' : {
        'application_id': 4,
        'System_Applications_application_id': 4,
        'application_name': 'sine2',
        'virtual_machine_name': 'sine2app',
        'virtual_machine_id': 4,
        'Configuration_Parts_part_key': 'sine2_test_app_00001',
        'Configuration_Parts_Configuration_configuration_key': 1,
        'Configuration_Parts_Configuration_Mission_mission_key': 1,
        'parameter_id': 4,
    },
    'cosapp'   : {
        'application_id': 5,
        'System_Applications_application_id': 5,
        'application_name': 'cos',
        'virtual_machine_name': 'cosapp',
        'virtual_machine_id': 5,
        'Configuration_Parts_part_key': 'cos_test_app_00001',
        'Configuration_Parts_Configuration_configuration_key': 1,
        'Configuration_Parts_Configuration_Mission_mission_key': 1,
        'parameter_id': 5,
    },
}

def prep(db):
    # Clean the Flight_Data, System_Messages, Command_Log, System_Applications
    # and Parameter_ID_Table tables
    db._execute('DELETE FROM `stepSATdb_Flight`.`Flight_Data`')
    db._execute('DELETE FROM `stepSATdb_Flight`.`System_Messages`')
    db._execute('DELETE FROM `stepSATdb_Flight`.`Command_Log`')
    db._execute('DELETE FROM `stepSATdb_Flight`.`System_Applications`')
    db._execute('DELETE FROM `stepSATdb_Flight`.`Parameter_ID_Table`')
    db._execute('DELETE FROM `stepSATdb_Flight`.`Virtual_Machines`')

    # Ensure that the Recording_Sessions table has only row 0
    db._execute('DELETE FROM `stepSATdb_Flight`.`Recording_Sessions`')
    db._execute('INSERT INTO `stepSATdb_Flight`.`Recording_Sessions`(`recording_session_id`) VALUES (0)')

    # Add the default application set with the state set to "80" (storage)
    db._execute(app_prep_stmt, app_config.values())
    db._execute(param_prep_stmt, app_config.values())
    db._execute(vm_prep_stmt, app_config.values())

    # Add the basic recording session state entry (if it isn't already there)
    stmt = 'INSERT IGNORE INTO `stepSATdb_Flight`.`Recording_Session_State`(`state_index`, `data_download_poll_rate`, `command_poll_rate`, `command_syslog_poll_rate`) VALUES (0, 60, 60, 60)'
    db._execute(stmt)

def add_apps(db, apps):
    for a in map(app_config.get, apps):
        # The command key requires at least 1 second in between commands
        db._execute(cmd_add_stmt, a)
        time.sleep(1.0)

def remove_apps(db, apps):
    for a in map(app_config.get, apps):
        # The command key requires at least 1 second in between commands
        db._execute(cmd_remove_stmt, a)
        time.sleep(1.0)

def increment_session(db):
    db._execute('INSERT INTO `stepSATdb_Flight`.`Recording_Sessions` (`recording_session_id`) SELECT MAX(`recording_session_id`) + 1 FROM `stepSATdb_Flight`.`Recording_Sessions`')

def dump(db):
    stmt = 'SELECT `System_Applications`.`application_id` AS \'id\', `System_Applications`.`application_name` AS \'name\' FROM `stepSATdb_Flight`.`System_Applications`'
    apps = db._execute(stmt)
    apps_fmt = '{:<8} {:<8}'
    print(apps_fmt.format(*apps[0].keys()))
    for a in apps:
        print(apps_fmt.format(*a.values()))

    print('')

    stmt = 'SELECT `Parameter_ID_Table`.`parameter_id` AS \'id\', `Parameter_ID_Table`.`parameter_name` AS \'name\', `Parameter_ID_Table`.`System_Applications_application_id` AS \'app_id\' FROM `stepSATdb_Flight`.`Parameter_ID_Table`'
    params = db._execute(stmt)
    param_fmt = '{:<8} {:<8} {:<8}'
    print(param_fmt.format(*params[0].keys()))
    for p in params:
        print(param_fmt.format(*p.values()))

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Test script to add or remove domains from the QS/VMS database')
    parser.add_argument('--prep', action='store_true', help='re-initialize the QS/VMS database')
    parser.add_argument('--add', action='append', help='domain names to add to the QS/VMS database')
    parser.add_argument('--remove', action='append', help='domain names to delete from the QS/VMS database')
    parser.add_argument('--dump', action='store_true', help='display the current state of the application and parameter tables from the QS/VMS database')
    parser.add_argument('--incr', action='store_true', help='increment the recording session')
    args = parser.parse_args()

    vms_config = {
        #'address': '172.27.5.70',
        'address': '127.0.0.1',
        'port': 3306,
        'username': 'root',
        'password': 'quicksat1',
        'cert': None,
        'dbname': 'stepSATdb_Flight'
    }

    # Connect to the QS/VMS DB
    db = vms_db.vms_db(**vms_config)

    if args.prep:
        prep(db)

    if args.add:
        add_apps(db, args.add)

    if args.remove:
        remove_apps(db, args.remove)

    if args.dump:
        dump(db)

    if args.incr:
        increment_session(db)

