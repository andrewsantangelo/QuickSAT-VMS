#!/usr/bin/env python

import vms_db

if __name__ == '__main__':
    vms_config = {
        'address': '127.0.0.1',
        'port': 3306,
        'username': 'root',
        'password': 'quicksat1',
        'cert': None,
        'dbname': 'stepSATdb_Flight'
    }

    # Connect to the QS/VMS DB
    db = vms_db(**vms_config)

    # Clean the Flight_Data, System_Messages, Command_Log, and
    # Recording_Sessions tables
    db._execute('DELETE FROM `stepSATdb_Flight`.`Flight_Data` WHERE 1')
    db._execute('DELETE FROM `stepSATdb_Flight`.`System_Messages` WHERE 1')
    db._execute('DELETE FROM `stepSATdb_Flight`.`Command_Log` WHERE 1')
    db._execute('DELETE FROM `stepSATdb_Flight`.`Recording_Sessions` WHERE 1')

    # Ensure that the applications and associated parameters are in the DB
    apps = [
        { 'application_id': 1, 'application_name': 'prime1app', 'Configuration_Parts_part_key': 1, 'Configuration_Parts_Configuration_configuration_key': 1, 'Configuration_Parts_Configuration_Mission_mission_key': 1 },
        { 'application_id': 2, 'application_name': 'prime2app', 'Configuration_Parts_part_key': 1, 'Configuration_Parts_Configuration_configuration_key': 1, 'Configuration_Parts_Configuration_Mission_mission_key': 1 },
        { 'application_id': 3, 'application_name': 'sineapp', 'Configuration_Parts_part_key': 1, 'Configuration_Parts_Configuration_configuration_key': 1, 'Configuration_Parts_Configuration_Mission_mission_key': 1 },
        { 'application_id': 4, 'application_name': 'sine2app', 'Configuration_Parts_part_key': 1, 'Configuration_Parts_Configuration_configuration_key': 1, 'Configuration_Parts_Configuration_Mission_mission_key': 1 },
        { 'application_id': 5, 'application_name': 'cosapp', 'Configuration_Parts_part_key': 1, 'Configuration_Parts_Configuration_configuration_key': 1, 'Configuration_Parts_Configuration_Mission_mission_key': 1 },
    ]
    stmt = 'INSERT IGNORE INTO `stepSATdb_Flight`.`System_Applications` (`application_id`, `application_name`, `virtual_machine_id`, `Configuration_Parts_part_key`, `Configuration_Parts_Configuration_configuration_key`, `Configuration_Parts_Configuration_Mission_mission_key`) VALUES (%(application_id)s, %(application_name)s, %(virtual_machine_id)s, %(Configuration_Parts_part_key)s, %(Configuration_Parts_Configuration_configuration_key)s, %(Configuration_Parts_Configuration_Mission_mission_key)s)'
    db._execute(stmt, apps)

    params = [
        { 'parameter_id': 1, 'System_Applications_application_id': 1 },
        { 'parameter_id': 2, 'System_Applications_application_id': 2 },
        { 'parameter_id': 3, 'System_Applications_application_id': 3 },
        { 'parameter_id': 4, 'System_Applications_application_id': 4 },
        { 'parameter_id': 5, 'System_Applications_application_id': 5 },
    ]
    stmt = 'INSERT IGNORE INTO `stepSATdb_Flight`.`Parameter_ID_Table`(`parameter_id`, `System_Applications_application_id`) VALUES (%(parameter_id)s, %(System_Applications_application_id)s)'
    db._execute(stmt, params)

