#!/usr/bin/env python

import random

handler = None

class GenericHandler(object):
    def __init__(self):
        self.some_value = random.randint(1, 100)

    def foo(self, db, data):
        db._log_msg('FOO {}: {}'.format(self.some_value, data))
        return False

    def bar(self, db, data):
        db._log_msg('BAR {}: {}'.format(self.some_value, data))
        return True


def process(db, cmd, data):
    # If the handler class instance has not yet been created, create it now
    global handler
    if not handler:
        handler = GenericHandler()

    # Define a mapping of commands to functions
    cmd_map = {
        'foo': handler.foo,
        'bar': handler.bar,
    }

    # Don't worry about checking for errors, they are trapped at a higher level
    cmd = cmd.lower()

    # Assume that the command is in the map, otherwise the traceback will show
    # where the error occurred
    return cmd_map[cmd](db, data)

