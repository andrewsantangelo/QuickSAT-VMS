#!/usr/bin/env python
"""
A module that handles processing the commands to manipulate the target (HOST)
computer.

Copyright (c) 2016, DornerWorks, Ltd.
"""

import syslog
import os.path
import re
import multiprocessing
import time

# Easiest way to do sftp, install with
#   $ pip install paramiko
# install pip as described here:
#   https://pypi.python.org/pypi/setuptools
import paramiko

import mct

# Disable some pylint warnings that I don't care about
# pylint: disable=line-too-long,fixme,unidiomatic-typecheck

# Indicate that there is no MCP connection by default
MCP = None


def app_file_name(app):
    """
    A simple utility that determines the name of the file that is required to
    run the application.
    """
    linux_regex = re.compile(r'(ubuntu|linux|debian)', re.IGNORECASE)
    mirage_regex = re.compile(r'(mirage)', re.IGNORECASE)
    if linux_regex.match(app['vm_os']):
        # For linux applications, there will be a small read-only disk image
        # to transfer
        return '{}.img'.format(app['name'])
    elif mirage_regex.match(app['vm_os']):
        # For mirage applications the kernel must be transfered, and it is
        # expected to be named mir-<app>.xen
        return 'mir-{}.xen'.format(app['name'])
    else:
        msg = 'unsupported OS type: {}'.format(app['vm_os'])
        raise NotImplementedError(msg)


class McpTarget(object):
    """
    A class that handles the MCP commands
    """
    def __init__(self, address, port, username, password):
        self.lock = multiprocessing.Lock()

        self.address = address
        self.port = port
        self.username = username
        self.password = password

        # Open SSH and SFTP connections
        self.ssh = paramiko.SSHClient()
        self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.ssh.load_system_host_keys()
        self.sftp = None

    def __del__(self):
        self.close()

    def close(self):
        """
        Closes SSH/SFTP connections to the target board.
        """
        if self.ssh.get_transport() and self.ssh.get_transport().is_active():
            self.sftp.close()
            self.ssh.close()

        # Wait some time to ensure that MCP has had enough time to complete
        # handling the previous command (such as an MCT reload) before exiting
        # and releasing the lock.
        #
        # TODO: Eventually have MCP create a lock file during reload, and
        # create a "reload_complete" target in the service script so that we
        # can be sure that this process isn't exiting until the MCT reload has
        # been completed.
        time.sleep(10.0)

        self.lock.release()

    def connect(self):
        """
        Opens SSH/SFTP connections to the target board.
        """
        self.lock.acquire()

        if not self.ssh.get_transport() or not self.ssh.get_transport().is_active():
            self.ssh.connect(self.address, port=self.port, username=self.username, password=self.password)
            self.sftp = self.ssh.open_sftp()

    def remove_files(self, files):
        """
        Removes the specified files from the /opt/mcp/images/ directory on the
        target board if they are present in that directory.
        """
        assert type(files) == list
        syslog.syslog(syslog.LOG_INFO, 'MCP remove files: {}'.format(str(files)))
        cur_files = self.sftp.listdir('/opt/mcp/images/')
        syslog.syslog(syslog.LOG_DEBUG, 'files installed on target = {}'.format(str(cur_files)))
        for fil in files:
            # Only bother removing files that are present on the target
            if fil in cur_files:
                path = os.path.join('/opt/mcp/images/', fil)
                syslog.syslog(syslog.LOG_DEBUG, 'Removing "{}" from target'.format(path))
                self.sftp.remove(path)

    def add_files(self, files):
        """
        Add the specified files to the /opt/mcp/images/ directory on the
        target board if they are not already there.
        """
        assert type(files) == list
        syslog.syslog(syslog.LOG_INFO, 'MCP adding files: {}'.format(str(files)))
        cur_files = self.sftp.listdir('/opt/mcp/images/')
        syslog.syslog(syslog.LOG_DEBUG, 'files installed on target = {}'.format(str(cur_files)))
        for fil in files:
            # Only bother adding the new file if it is not already present
            #
            # TODO: md5sum the files to ensure that they are the same before
            # skipping one that is already on the target board.
            if fil not in cur_files:
                src_path = os.path.join('/opt/qs/input/', fil)
                dest_path = os.path.join('/opt/mcp/images/', fil)
                syslog.syslog(syslog.LOG_DEBUG, 'Transferring "{}" to target "{}"'.format(src_path, dest_path))
                self.sftp.put(src_path, dest_path)

                # force the target file systems to sync to ensure that any files
                # written or removed are written through to the disk
                _, stdout, stderr = self.ssh.exec_command('sync')
                status = stdout.channel.recv_exit_status()
                if status != 0:
                    # If the command did not execute correctly, place the
                    # stderr and stdout into an exception message
                    exp = (status, stdout.channel.recv(1000), stderr.channel.recv(1000))
                    raise Exception(exp)

    def reload(self, mctpath):
        """
        Sends the current (presumably new) MCT to the target board and causes
        the MCP service to reload the configuration.
        """
        syslog.syslog(syslog.LOG_INFO, 'Reloading MCP')
        # Send the updated MCT, place this in the /opt/mcp/ staging area
        # first, the reload command will cause it to be copied to the /etc/mcp/
        # directory.
        self.sftp.put(mctpath, '/opt/mcp/mct.db')

        # run the MCP prep script on the MCP target
        _, stdout, stderr = self.ssh.exec_command('sudo service mcp reload')
        status = stdout.channel.recv_exit_status()
        if status != 0:
            # If the command did not execute correctly, place the stderr and
            # stdout into an exception message
            exp = (status, stdout.channel.recv(1000), stderr.channel.recv(1000))
            raise Exception(exp)

        return True

    def start(self):
        """
        Sends a command to the target board to cause the MCP service to be
        started.  If MCP is not running this will cause all configured VMs to
        be started.
        """
        syslog.syslog(syslog.LOG_INFO, 'Starting MCP')
        _, stdout, stderr = self.ssh.exec_command('sudo service mcp start')
        status = stdout.channel.recv_exit_status()
        if status != 0:
            # If the command did not execute correctly, place the stderr and
            # stdout into an exception message
            exp = (status, stdout.channel.recv(1000), stderr.channel.recv(1000))
            raise Exception(exp)
        return True

    def stop(self):
        """
        Sends a command to the target board to cause the MCP service to be
        stopped.  This will cause all configured VMs to be stopped.
        """
        syslog.syslog(syslog.LOG_INFO, 'Stopping MCP')
        _, stdout, stderr = self.ssh.exec_command('sudo service mcp stop')
        status = stdout.channel.recv_exit_status()
        if status != 0:
            # If the command did not execute correctly, place the stderr and
            # stdout into an exception message
            exp = (status, stdout.channel.recv(1000), stderr.channel.recv(1000))
            raise Exception(exp)

        return True

    def restart(self):
        """
        Sends a command to the target board to restart MCP.  Because this stops
        and then starts MCP, this will cause all VMs to be stopped and
        restarted also.
        """
        syslog.syslog(syslog.LOG_INFO, 'Restarting MCP')
        _, stdout, stderr = self.ssh.exec_command('sudo service mcp restart')
        status = stdout.channel.recv_exit_status()
        if status != 0:
            # If the command did not execute correctly, place the stderr and
            # stdout into an exception message
            exp = (status, stdout.channel.recv(1000), stderr.channel.recv(1000))
            raise Exception(exp)

        return True

    def reboot(self):
        """
        Sends a command to reboot the target board.
        """
        syslog.syslog(syslog.LOG_INFO, 'Rebooting MCP Host')
        _, stdout, stderr = self.ssh.exec_command('sudo reboot')
        status = stdout.channel.recv_exit_status()
        if status != 0:
            # If the command did not execute correctly, place the stderr and
            # stdout into an exception message
            exp = (status, stdout.channel.recv(1000), stderr.channel.recv(1000))
            raise Exception(exp)

        return True

    def pause_vm(self, dom):
        """
        Sends a command to the target board to pause a specified VM.
        """
        syslog.syslog(syslog.LOG_INFO, 'Pausing VM {}'.format(dom))
        _, stdout, stderr = self.ssh.exec_command('sudo xl pause {}'.format(dom))
        status = stdout.channel.recv_exit_status()
        if status != 0:
            # If the command did not execute correctly, place the stderr and
            # stdout into an exception message
            exp = (status, stdout.channel.recv(1000), stderr.channel.recv(1000))
            raise Exception(exp)

        return True

    def unpause_vm(self, dom):
        """
        Sends a command to the target board to unpause a specified VM.
        """
        syslog.syslog(syslog.LOG_INFO, 'Unpausing VM {}'.format(dom))
        _, stdout, stderr = self.ssh.exec_command('sudo xl unpause {}'.format(dom))
        status = stdout.channel.recv_exit_status()
        if status != 0:
            # If the command did not execute correctly, place the stderr and
            # stdout into an exception message
            exp = (status, stdout.channel.recv(1000), stderr.channel.recv(1000))
            raise Exception(exp)

        return True

    def reboot_vm(self, dom):
        """
        Sends a command to the target board to reboot a specified VM.
        """
        syslog.syslog(syslog.LOG_INFO, 'Rebooting VM {}'.format(dom))
        _, stdout, stderr = self.ssh.exec_command('sudo xl reboot {}'.format(dom))
        status = stdout.channel.recv_exit_status()
        if status != 0:
            # If the command did not execute correctly, place the stderr and
            # stdout into an exception message
            exp = (status, stdout.channel.recv(1000), stderr.channel.recv(1000))
            raise Exception(exp)

        return True

    def add_app(self, new_app, apps):
        """
        Adds a VM to the operating configuration of a target.  The following
        steps are performed to archive this:
        1. Send the required file(s) to the target board
        2. Generate a new MCT that includes all existing VMs and the newly
           specified VM.
        3. Send the new MCT to the target board
        4. Send a command to cause MCP to reload it's configuration
        """
        syslog.syslog(syslog.LOG_DEBUG, 'adding app: {}'.format(new_app['id']))

        # Create a new MCT with all apps currently on the target board
        # (state > 100), and the app being added.
        mctapps = [a for a in apps if a['state'] >= 100 or a['id'] == new_app['id']]

        syslog.syslog(syslog.LOG_DEBUG, 'Apps for MCT = {}'.format(mctapps))

        # Get a list of the domains that need to be defined.
        dom_dict = {}
        for app in mctapps:
            if app['vm'] not in dom_dict:
                dom_dict[app['vm']] = {
                    'id': app['vm'],
                    'os': app['vm_os'],
                    'name': app['part'],
                    'app': app['name']
                }
        doms = [d for d in dom_dict.values()]

        # Send the specified file(s) to the target board if it isn't already
        # installed (for another VM).
        #
        # NOTE: Currently this consists of only the executable/kernel for
        # the new VM, but it may eventually include additional disk images.
        mct_app_files = [app_file_name(a) for a in mctapps]
        self.add_files(mct_app_files)

        # Construct the new MCT
        newmct = mct.Mct()
        newmct.adddomains(doms)
        newmct.addapps(mctapps)
        newmct.close()

        # Restart MCP
        return self.reload(newmct.path())

    def remove_app(self, remove_app, apps):
        """
        Removes a VM from the operating configuration of a target.  The
        following steps are performed to archive this:
        1. Delete the required file(s) from the target board, if the file(s)
           aren't required by any other VMs
        2. Generate a new MCT that includes all existing VMs except for the
           specified VM.
        3. Send the new MCT to the target board
        4. Send a command to cause MCP to reload it's configuration
        """
        syslog.syslog(syslog.LOG_DEBUG, 'removing app: {}'.format(remove_app['id']))

        # Create a new MCT with all apps currently on the target board
        # (state > 100), Except for the app being added.
        mctapps = [a for a in apps if a['state'] >= 100 and a['id'] != remove_app['id']]

        syslog.syslog(syslog.LOG_DEBUG, 'Apps for MCT = {}'.format(mctapps))

        # Get a list of the domains that need to be defined.
        dom_dict = {}
        for app in mctapps:
            if app['vm'] not in dom_dict:
                dom_dict[app['vm']] = {
                    'id': app['vm'],
                    'os': app['vm_os'],
                    'name': app['part'],
                    'app': app['name']
                }
        doms = [d for d in dom_dict.values()]

        # Identify the name of the files that should remain on the target.
        mct_app_files = [app_file_name(a) for a in mctapps]

        # Remove the specified file(s) from the target board, but only if
        # they are not required by a VM that is still running on the target.
        #
        # NOTE: Currently this consists of only the executable/kernel for
        # the new VM, but it may eventually include additional disk images.
        files = [a for a in [app_file_name(remove_app)] if a not in mct_app_files]
        self.remove_files(files)

        # Construct the new MCT
        newmct = mct.Mct()
        newmct.adddomains(doms)
        newmct.addapps(mctapps)
        newmct.close()

        # Restart MCP
        return self.reload(newmct.path())


# pylint: disable=invalid-name
def process(db, cmd, data):
    """
    The function required for the vms class to call this one to handle custom
    MCP functions.
    """
    # pylint: disable=too-many-branches,global-statement,protected-access,too-many-statements
    syslog.syslog(syslog.LOG_INFO, 'MCP processing command {}:{}'.format(cmd, data))

    global MCP
    if not MCP:
        # Retrieve the address of the board that MCP is running on
        conn_info = db.get_board_connection_data(name='mcp')

        if conn_info['method'] == 'ETHERNET':
            addr = conn_info['address'].split(':', 2)

            # If the port was not specified in the address, set it to the
            # default (22).
            if len(addr) == 1:
                port = 22
            else:
                port = addr[1]

            config = {
                'address': addr[0],
                'port': port,
                'username': conn_info['username'],
                'password': conn_info['password'],
            }
            MCP = McpTarget(**config)
        else:
            msg = 'Unsupported mcp connection method: {}'.format(conn_info['method'])
            db._log_msg(msg)
            return False

    # Connect to the MCP Target if the connection method is recognized
    MCP.connect()

    # Now process the command
    cmd = cmd.lower()
    if cmd == 'reboot':
        result = MCP.reboot()
    elif cmd == 'restart':
        result = MCP.restart()
    elif cmd == 'start':
        result = MCP.start()
    elif cmd == 'stop':
        result = MCP.stop()
    elif cmd == 'add_vmapp':
        # get a list of all apps on the same board as mcp
        apps = db.get_board_apps(name='mcp')

        # Drop any dom0 applications from the list
        apps = [a for a in apps if a['vm'] > 0]

        # The app ID could be an integer or string, coerce both values to
        # strings to compare
        new_app = [a for a in apps if str(a['id']) == str(data)]
        if len(new_app) != 1:
            msg = 'App {} not found in list: {}'.format(data, apps)
            raise Exception(msg)
        else:
            result = MCP.add_app(new_app[0], apps)

        if result:
            # Update the state of the applications added to indicate that it
            # has been added to the target borad (HOST):
            #
            #   50: Stored on the ground station (not visible on the gateway,
            #       but is on the ground station).
            #   80: Stored on the Gateway
            #   100: On the host and operational.
            #   101-199: Operational, on the host, with added messages and
            #       states.  Open and TBD
            #   200: On the host, but NOT operational.  For example the VM is
            #       there, but the executable has stopped.  This might be
            #       necessary for different modes of operation.  Essentially
            #       the VM is ready and waiting, but the app is not in use.
            #   201-299: similar code to 200, but open and TBD
            #   300-399: Error codes; VM and application are on the host.
            #
            status = 'On Host - VM Configured'
            msg = 'Success - VM/App "{}" installed'.format(new_app[0]['part'])
            db.set_application_state(new_app[0], 195, status, msg)

    elif cmd == 'remove_vmapp':
        # get a list of all apps on the same board as mcp
        apps = db.get_board_apps(name='mcp')

        # Drop any dom0 applications from the list
        apps = [a for a in apps if a['vm'] > 0]

        # The app ID could be an integer or string, coerce both values to
        # strings to compare
        remove_app = [a for a in apps if str(a['id']) == str(data)]
        if len(remove_app) != 1:
            msg = 'App {} not found in list: {}'.format(data, apps)
            raise Exception(msg)
        else:
            result = MCP.remove_app(remove_app[0], apps)

        if result:
            # Update the state of the applications added to indicate that it
            # has been added to the target borad (HOST):
            #
            #   50: Stored on the ground station (not visible on the gateway,
            #       but is on the ground station).
            #   80: Stored on the Gateway
            #   100: On the host and operational.
            #   101-199: Operational, on the host, with added messages and
            #       states.  Open and TBD
            #   200: On the host, but NOT operational.  For example the VM is
            #       there, but the executable has stopped.  This might be
            #       necessary for different modes of operation.  Essentially
            #       the VM is ready and waiting, but the app is not in use.
            #   201-299: similar code to 200, but open and TBD
            #   300-399: Error codes; VM and application are on the host.
            #
            status = 'GATEWAY Storage'
            msg = 'Success - VM/App "{}" removed from Host'.format(remove_app[0]['part'])
            db.set_application_state(remove_app[0], 80, status, msg)
    elif cmd == 'pause_vm':
        # Find the name of the VM that should be paused
        name = db.get_app_info(ident=data)['part']
        result = MCP.pause_vm(name)
    elif cmd == 'unpause_vm':
        # Find the name of the VM that should be unpaused
        name = db.get_app_info(ident=data)['part']
        result = MCP.unpause_vm(name)
    elif cmd == 'reboot_vm':
        # Find the name of the VM that should be rebooted
        name = db.get_app_info(ident=data)['part']
        result = MCP.reboot_vm(name)
    else:
        msg = 'Unsupported mcp command: {}'.format(cmd)
        db._log_msg(msg)
        result = False

    # Close the MCP connection
    MCP.close()

    return result
