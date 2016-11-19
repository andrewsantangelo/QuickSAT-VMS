#!/usr/bin/env python
"""
An example "command handler" class to show how to create a python command
handling script that can run custom commands.
"""

import random
import multiprocessing
import time

# pylint: disable=blacklisted-name,invalid-name,protected-access,global-statement

STX3 = None


class STX3Target(object):
    """
    The generic handler class, it is used to maintain data across multiple
    invocations of the class, as well as to deal with inter-process
    synchronization to deal with processes that may take a while to complete.
    """

    def __init__(self):
        self.some_value = random.randint(1, 100)

        # A multiprocessing lock to ensure that different command processes
        # of this type are not allowed run until any prior command processes
        # (of this type) have completed.
        self.lock = multiprocessing.Lock()

    def foo(self, db, data):
        """
        An example command handler function that creates a message of:
            FOO <random num>: <command data>
        and always fails (returns False)
        """

        self.lock.acquire()

        # Sleep for some time to simulate a long running command
        time.sleep(30.0)

        db._log_msg('FOO {}: {}'.format(self.some_value, data))

        self.lock.release()

        return False

    def bar(self, db, data):
        """
        An example command handler function that creates a message of:
            BAR <random num>: <command data>
        and always succeeds (returns True)
        """

        self.lock.acquire()

        # Sleep for some time to simulate a long running command
        time.sleep(30.0)

        db._log_msg('BAR {}: {}'.format(self.some_value, data))

        self.lock.release()

        return True


def process(db, cmd, data):
    """
    This function is required to exist in a python module to be able to be
    executed as a unknown command handler.  3 arguments are supplied by the
    VMS class when this function is called:

        db:   A unique VMS database object, created only for this process to
              ensure that any DB access performed by this module do not
              interfere with other DB interactions.

        cmd:  The command string of what command should be performed.  The DB
              "command" column has the form of "MODULE.CMD", the "MODULE."
              part is removed before this function is called.

        data: The value that was in the "command_data" column in the DB.  This
              is natively a string in the DB, but can be interpreted as
              desired in this function.

    This function should return True or False to indicate if the command is
    able to be handled successfully or not.  If an exception occurs the
    command will be marked as "Failed" and the exception traceback will be
    inserted into the "Log_Messages" table.
    """

    # If the handler class instance has not yet been created, create it now
    global STX3
    if not STX3:
        STX3 = STX3Target()

    # Define a mapping of commands to functions
    cmd_map = {
        'foo': STX3.foo,
        'bar': STX3.bar,
    }

    # Don't worry about checking for errors, they are trapped at a higher level
    cmd = cmd.lower()

    # Assume that the command is in the map, otherwise the traceback will show
    # where the error occurred
    return cmd_map[cmd](db, data)
