#!/usr/bin/env python

# Install the required python serial package with one of the following commands:
#
# apt-get install python-serial
#   OR
# pip install pyserial

import serial
import threading

class gsp1720(object):
    # set default dtr_pin back to 48 when dtr_pin init is properly handled
    def __init__(self, port='/dev/ttyO4', baudrate=9600, dtr_pin=None):
        self.lock = threading.RLock()
        # Use a short timeout for read and write operations since the baud
        # rates used with the GSP-1720 radio are so slow.
        self.args = {
            'port': port,
            'baudrate': baudrate,
            'bytesize': 8,
            'parity': serial.PARITY_NONE,
            'stopbits': serial.STOPBITS_ONE,
            'timeout': 1,
            'xonxoff': False,
            'rtscts': False,
            'dsrdtr': False,
            'writeTimeout': 1,
        }
#        self.dtr_pin = dtr_pin
        self.dtr_pin = 48
        self.serial = serial.Serial(**self.args)
        
        if self.dtr_pin:
            import os.path
            if not os.path.exists('/sys/class/gpio/gpio{}'.format(self.dtr_pin)):
                # Enable the GPIO1_16 signal to be used to enable DTR
                with open('/sys/class/gpio/export', 'w') as f:
                    f.write(str(self.dtr_pin))

            with open('/sys/class/gpio/gpio{}/direction'.format(self.dtr_pin), 'w') as f:
                f.write('out')

            with open('/sys/class/gpio/gpio{}/value'.format(self.dtr_pin), 'w') as f:
                f.write('1')

    def __del__(self):
        self.close()

    def close(self):
        with self.lock:
            self.serial.close()

    def _command(self, cmd):
        with self.lock:
            self.serial.flush()
            self.serial.write(b'{}\r'.format(cmd))

            # Because there is a short timeout this will only read the available
            # bytes rather than trying to read all 1000 characters.
            raw = self.serial.read(1000)

        # Split the returned data into lines, the values returned should be
        # one of the following items:
        #   1. The command echoed back
        #   2. A KEY:VALUE pair
        #   3. Blank lines
        #   4. OK or ERROR
        result = {}
        status = False
        for line in raw.split('\r\n'):
            if line == 'OK':
                # If an OK status is returned, set the status of the command
                # to True
                status = True
            elif line != cmd and ':' in line:
                # If there are any KEY:VALUE pairs, add them to the result
                # dictionary
                (key, value) = tuple(line.split(':', 1))
                result[key] = value.strip('\r\n ')

        # Return 3 things as a tuple:
        #   1. Status (OK/ERROR translated into True/False)
        #   2. A dictionary of any KEY:VALUE pairs
        #   3. The raw result text
        return (status, result, raw)

    def get_status(self):
        #print "entering get_status()"
        with self.lock:
            return self._command('AT$QCSTATUS')

    def get_location(self):
        #print "entering get_location()"
        with self.lock:
            return self._command('AT$QCPLS=0')

    def is_service_available(self):
        print "entering is_service_available()"
        (status, data, _) = self.get_status()
        avail = status and (data['RSSI'] >= 1) and (data['SERVICE AVAILABLE'] == 'YES') and (data['ROAMING'] == 'NO')
        if 'SERVICE AVAILABLE' in data and data['SERVICE AVAILABLE'] == 'DEEP_SLEEP':
            print('DEEP_SLEEP!')
        rssi = -1
        roaming = 'NO'
        if 'RSSI' in data:
            rssi = data['RSSI']
        if 'ROAMING' in data:
            roaming = data['ROAMING']
        return (avail, rssi, roaming)
        
    def call(self, number):
        print "entering call()"
        with self.lock:
            self.serial.flush()
            # set the timeout longer to allow time for the connection to be made
            old_timeout = self.serial.timeout
            self.serial.timeout = 60
            # Phone option to ignore DTR changes after a call starts. Adds stability.
            self._command('AT&D0')
            self.serial.write(b'ATD#{}\r'.format(number))

            # there shouldn't be as many bytes to read in response to this command as there
            # are to normal commands
            raw = self.serial.read(18)

            # return the read timeout to normal
            self.serial.timeout = old_timeout

            status = False
            for line in raw.split('\r\n'):
                # we only care if the response is 'CONNECT'
                if line.strip('\r\n ') == 'CONNECT':
                    status = True

            # flush any unread characters
            self.serial.flush()

            return (status, raw)

    def hangup(self):
        with self.lock:
            return self._command('ATH')

if __name__ == '__main__':
    radio = gsp1720()
    status = radio.get_status()
    print('status = {}\n{}'.format(status[0], str(status[1])))

