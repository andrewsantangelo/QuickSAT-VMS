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
    db = vms_db.vms_db(**vms_config)

    # Test the db network config and update
    db.connect_to_ground()

