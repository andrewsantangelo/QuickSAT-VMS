#!/usr/bin/env python

import radio_status
import subprocess

if __name__ == '__main__':
	subprocess.call(['pkill', 'pppd'])
	radio = radio_status.gsp1720(dtr_pin=None)
	radio.hangup()
