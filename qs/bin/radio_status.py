#!/usr/bin/env python

# Install the required python serial package with one of the following commands:
#
# apt-get install python-serial
#   OR
# pip install pyserial

import serial

class gsp1720(object):
    def __init__(self, port='/dev/ttyO4', baudrate=9600):
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
        self.serial = serial.Serial(**self.args)

    def _command(self, cmd):
        self.serial.flush()
        self.serial.write(cmd + '\r\n')

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
                result[key] = value

        # Return 3 things as a tuple:
        #   1. Status (OK/ERROR translated into True/False)
        #   2. A dictionary of any KEY:VALUE pairs
        #   3. The raw result text
        return (status, result, raw)

    def get_status(self):
        return self._command('AT$QCSTATUS')

    def get_location(self):
        return self._command('AT$QCPLS=1')

if __name__ == '__main__':
    radio = gsp1720()
    status = radio.get_status()
    print('status = {}\n{}'.format(status[0], str(status[1])))

