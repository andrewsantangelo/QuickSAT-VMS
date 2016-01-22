#!/usr/bin/env python

import vms_db
import vms_db_ground
import time

if __name__ == '__main__':

    vms_ground_config = {
        'address': '192.168.2.1',
        'port': 3306,
        'username': 'admin',
        'password': 'quicksat1',
        'cert': None,
        'dbname': 'stepSATdb_Flight'
    }
    # Connect to the QS/VMS DB
    db_ground = vms_db_ground.vms_db_ground(**vms_ground_config)
    if db_ground.cursor:
        print 'yay'
    
    vms_config = {
        'address': '127.0.0.1',
        'port': 3306,
        'username': 'root',
        'password': 'quicksat1',
        'cert': None,
        'dbname': 'stepSATdb_Flight'
    }
    
    db = vms_db.vms_db(**vms_config)
    
    stmt = '''TRUNCATE TABLE `stepSATdb_Flight`.`Command_Log`'''
    db_ground.cursor.execute(stmt)
    db_ground.db.commit()
    
    stmt = '''TRUNCATE TABLE `stepSATdb_Flight`.`Flight_Data`'''
    db_ground.cursor.execute(stmt)
    db_ground.db.commit()
    
    stmt = '''TRUNCATE TABLE `stepSATdb_Flight`.`Flight_Data_Binary`'''
    db_ground.cursor.execute(stmt)
    db_ground.db.commit()
    
    stmt = '''TRUNCATE TABLE `stepSATdb_Flight`.`Flight_Data_Object`'''
    db_ground.cursor.execute(stmt)
    db_ground.db.commit()
    
    stmt = '''TRUNCATE TABLE `stepSATdb_Flight`.`System_Messages`'''
    db_ground.cursor.execute(stmt)
    db_ground.db.commit()

    stmt = '''
            UPDATE `stepSATdb_Flight`.`Flight_Pointers`
                SET `Flight_Pointers`.`flight_data_event_key` = 0,
                    `Flight_Pointers`.`flight_data_binary_event_key` = 0,
                    `Flight_Pointers`.`flight_data_object_event_key` = 0,
                    `Flight_Pointers`.`system_messages_event_key` = 0
                        WHERE `Flight_Pointers`.`Recording_Sessions_recording_session_id`=(
                            SELECT MAX(`Recording_Sessions`.`recording_session_id`)
                                FROM `stepSATdb_Flight`.`Recording_Sessions`)
            '''
    db.cursor.execute(stmt)
    db.db.commit()
    
    
    