#!/usr/bin/env python

import radio_status
import subprocess
import time
import sys

# utility function to test connection to server
def ping(address):
    args = ['ping', '-I', 'ppp0', '-c1', address]
    f = open('/dev/null', 'w')
    return (0 == subprocess.call(args, stdout=f))

if __name__ == '__main__':
    radio = radio_status.gsp1720(dtr_pin=None)
    (avail, rssi) = radio.is_service_available()
    while not avail:
        sys.stdout.write(' ' + str(rssi))
        sys.stdout.flush()
        time.sleep(5)
        (avail, rssi) = radio.is_service_available()
    print('\nservice available!')

    # Wait a small amount of time before making a call, possibly the
    # radio is getting messed up
    (status, msg) = radio.call('777')
    if status:
        print('call success!')
        time.sleep(0.5)

        args = [ '/usr/sbin/pppd', '/dev/ttyO2', '19200', 'noauth', 'defaultroute', 'persist', 'maxfail', '0', 'crtscts', 'local' ]
        subprocess.call(args)

        time.sleep(10)
        server_state = ping('www.google.com')
        print('server state = {}'.format(server_state))
    else:
        print('call failed: ' + msg)

