#!/usr/bin/env python

import sys
import sqlite3

def gen_mct(cmds):
    db = sqlite3.connect('mct.db')
    c = db.cursor()
    c.executescript(cmds)
    db.commit()
    db.close()

if __name__ == '__main__':
    # If there is an argument use that as the filename, otherwise assume the
    # SQL command input file is named "mct.sql"
    if 2 <= len(sys.argv):
        cmdfile = sys.argv[1]
    else:
        cmdfile = 'mct.sql'

    f = open(cmdfile, 'r')
    cmds = f.read()
    f.close()

    gen_mct(cmds)

