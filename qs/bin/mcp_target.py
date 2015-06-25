#!/usr/bin/env python

import syslog
import os.path

# Easiest way to do sftp, install with
#   $ pip install paramiko
# install pip as described here:
#   https://pypi.python.org/pypi/setuptools
import paramiko

class mcp_target(object):
    def __init__(self, address, port, username, password):
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
        if self.ssh.get_transport() and self.ssh.get_transport().is_active():
            self.sftp.close()
            self.ssh.close()

    def connect(self):
        if not self.ssh.get_transport() or not self.ssh.get_transport().is_active():
            self.ssh.connect(self.address, port=self.port, username=self.username, password=self.password)
            self.sftp = self.ssh.open_sftp()

    def remove_files(self, files):
        syslog.syslog(syslog.LOG_INFO, 'MCP remove files: {}'.format(str(files)))
        installed_files = self.sftp.listdir('/opt/mcp/images/')
        syslog.syslog(syslog.LOG_DEBUG, 'files installed on target = {}'.format(str(installed_files)))
        for f in files:
            # Only bother removing files that are present on the target
            if f in installed_files:
                path = os.path.join('/opt/mcp/images/', f)
                syslog.syslog(syslog.LOG_DEBUG, 'Removing "{}" from target'.format(path))
                self.sftp.remove(path)

    def add_files(self, files):
        syslog.syslog(syslog.LOG_INFO, 'MCP adding files: {}'.format(str(files)))
        installed_files = self.sftp.listdir('/opt/mcp/images/')
        syslog.syslog(syslog.LOG_DEBUG, 'files installed on target = {}'.format(str(installed_files)))
        for f in files:
            # Only bother adding the new file if it is not already present
            if f not in installed_files:
                src_path = os.path.join('/opt/qs/input/', f)
                dest_path = os.path.join('/opt/mcp/images/', f)
                syslog.syslog(syslog.LOG_DEBUG, 'Transferring "{}" to target "{}"'.format(src_path, dest_path))
                self.sftp.put(src_path, dest_path)

                # ensure the new file is executable on the target
                stdin, stdout, stderr = self.ssh.exec_command('chmod +x ' + dest_path)
                status = stdout.channel.recv_exit_status()
                if status != 0:
                    # If the command did not execute correctly, place the
                    # stderr and stdout into an exception message
                    raise Exception(status, stdout, stderr)

                # force the target file systems to sync to ensure that any files
                # written or removed are written through to the disk
                stdin, stdout, stderr = self.ssh.exec_command('sync')
                status = stdout.channel.recv_exit_status()
                if status != 0:
                    # If the command did not execute correctly, place the
                    # stderr and stdout into an exception message
                    raise Exception(status, stdout, stderr)

    def reload(self, mctpath):
        syslog.syslog(syslog.LOG_INFO, 'Reloading MCP')
        # Send the updated MCT
        self.sftp.put(mctpath, '/opt/mcp/mct.db')

        # run the MCP prep script on the MCP target
        stdin, stdout, stderr = self.ssh.exec_command('/opt/mcp/bin/mcpprep --mode=mct --reload /opt/mcp/mct.db')
        status = stdout.channel.recv_exit_status()
        print('mcpprep result: {}\n{}\n{}\n'.format(status, stdout.channel.recv(1000), stderr.channel.recv(1000)))
        if status != 0:
            # If the command did not execute correctly, place the stderr and
            # stdout into an exception message
            raise Exception(status, stdout.channel.recv(1000), stderr.channel.recv(1000))

    def start(self):
        syslog.syslog(syslog.LOG_INFO, 'Starting MCP')
        stdin, stdout, stderr = self.ssh.exec_command('service mcp start')
        status = stdout.channel.recv_exit_status()
        print('mcp start result: {}\n{}\n{}\n'.format(status, stdout.channel.recv(1000), stderr.channel.recv(1000)))
        if status != 0:
            # If the command did not execute correctly, place the stderr and
            # stdout into an exception message
            raise Exception(status, stdout.channel.recv(1000), stderr.channel.recv(1000))

    def stop(self):
        syslog.syslog(syslog.LOG_INFO, 'Stopping MCP')
        stdin, stdout, stderr = self.ssh.exec_command('service mcp stop')
        status = stdout.channel.recv_exit_status()
        print('mcp stop result: {}\n{}\n{}\n'.format(status, stdout.channel.recv(1000), stderr.channel.recv(1000)))
        if status != 0:
            # If the command did not execute correctly, place the stderr and
            # stdout into an exception message
            raise Exception(status, stdout.channel.recv(1000), stderr.channel.recv(1000))

    def restart(self):
        syslog.syslog(syslog.LOG_INFO, 'Restarting MCP')
        stdin, stdout, stderr = self.ssh.exec_command('service mcp restart')
        status = stdout.channel.recv_exit_status()
        print('mcp restart result: {}\n{}\n{}\n'.format(status, stdout.channel.recv(1000), stderr.channel.recv(1000)))
        if status != 0:
            # If the command did not execute correctly, place the stderr and
            # stdout into an exception message
            raise Exception(status, stdout.channel.recv(1000), stderr.channel.recv(1000))

