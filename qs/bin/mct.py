#!/usr/bin/env python
"""
A module that handles generating a new configuration file for the MCP target.

Copyright (c) 2016, DornerWorks, Ltd.
"""

import sqlite3
import shutil
import tempfile
import os.path
import re

# Disable some pylint warnings that I don't care about
# pylint: disable=line-too-long,fixme,invalid-name


class Mct(object):
    """
    A class to manage the operations necessary to create an MCT configuration file.
    """
    linux_regex = re.compile(r'(ubuntu|linux|debian)', re.IGNORECASE)
    mirage_regex = re.compile(r'(mirage)', re.IGNORECASE)

    def __init__(self):
        self.working_dir = tempfile.mkdtemp()

        self.db = None
        self.cursor = None
        self.open()

    def __del__(self):
        self.close()

        if self.working_dir:
            shutil.rmtree(self.working_dir)

    def open(self):
        """
        Opens a new MCT SQLite configuration file.
        """
        if not self.db:
            # the python sqlite library does not implement the backup APIs, so
            # we create the new MCT in a file rather than exporting an
            # in-memory DB.
            self.db = sqlite3.connect(os.path.join(self.working_dir, 'mct.db'))
            self.db.row_factory = sqlite3.Row

        if self.db and not self.cursor:
            self.cursor = self.db.cursor()

        # the MCT that was just opened is an empty SQLite database, read the
        # empty MCT SQL file to generate an empty MCT.
        mctscript = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'mct.sql')
        with open(mctscript, 'r') as f:
            cmds = f.read()
            self.cursor.executescript(cmds)
            self.db.commit()

    def commit(self):
        """
        Commits the changes to the currently opened MCT file.
        """
        if self.db:
            self.db.commit()

    def close(self):
        """
        Closes an MCT SQLite configuration file.
        """
        self.commit()
        if self.db:
            self.db.close()
            self.db = None

        if not self.cursor:
            self.cursor = None

    def path(self):
        """
        Returns the path to the current MCT file.
        """
        return os.path.join(self.working_dir, 'mct.db')

    def adddomains(self, doms):
        """
        Adds one or more domains to the current MCT configuration file.
        """
        # The doms parameter is an iterable list of domain configurations
        # that contains the following values:
        #   - id
        #   - os
        #   - name
        #   - app name
        #
        # We need to add the following values so that MCT has enough
        # information for a minimal valid application configuration:
        #   - kernel image
        #   - schedule
        #   - memory
        #   - serial
        #   - extra params (standard boot args for linux domains)
        #
        # All domains get the following values set:
        #   name = <design_part_name> (app name may not be unique)
        #   vcpus = 1
        #   schedule = (apps schedule = 1)
        #
        # Linux domains need the following information:
        #   kernel = '/root/dom0_kernel'
        #   memory = 128
        #   extra  = 'console=hvc0 xencons=tty root=/dev/xvda'
        #   vif = br0
        #   disk = xvda (root), xvdb (app: will be added later by addapps())
        #
        # MirageOS domains need the following information:
        #   kernel = '/opt/mcp/images/mir-<name>.xen'
        #   memory = 32
        #
        # If the domain should have a specific IP address, then the network
        # configuration should also be specified on the kernel boot args:
        #   extra += 'ip=<domu IP> gw =<gw IP> netmask=<netmask>'
        for i in range(len(doms)):
            if self.linux_regex.match(doms[i]['os']):
                doms[i]['kernel'] = '/root/dom0_kernel'
                doms[i]['memory'] = 128
                doms[i]['ramdisk'] = None
                doms[i]['extra'] = 'console=hvc0 xencons=tty root=/dev/xvda'
            elif self.mirage_regex.match(doms[i]['os']):
                doms[i]['kernel'] = '/opt/mcp/images/mir-{}.xen'.format(doms[i]['app'])
                doms[i]['memory'] = 32
                doms[i]['ramdisk'] = None
                doms[i]['extra'] = None
            else:
                msg = 'unsupported OS type: {}'.format(doms[i]['vm_os'])
                raise NotImplementedError(msg)

        self.cursor.executemany('INSERT INTO domainTable VALUES(:id,:name,1,:memory,:kernel,:extra,:ramdisk,1);', doms)

        # Create a list of Linux domains and add block and VIF devices to
        # these domains
        linux_doms = [d for d in doms if self.linux_regex.match(d['os'])]

        # br0 is physical interface 0 in the default MCT
        self.cursor.executemany('INSERT INTO ifaceDomainTable VALUES(:id,0,NULL,NULL,NULL,NULL);', linux_doms)

        # The default LVM root images have the same ID as the domain ID
        self.cursor.executemany('INSERT INTO blockDevDomainTable VALUES(:id,:id,"xvda","rw");', linux_doms)

        # Allow the domains to run in the "operating" state
        self.cursor.executemany('INSERT INTO stateDomainAllocTable VALUES(:id,1,-1,-1,-1,-1);', doms)

        self.db.commit()

        return doms

    def addapps(self, apps):
        """
        Adds one or more applications to the current MCT configuration file.
        """
        # It is assumed at this point that the domain for the application has
        # been created.

        # Linux apps need to have their application images inserted into the
        # block device table. But before we can install these app images into
        # the blockDeviceTable, we have to find out what ID is free that we
        # can give the new block devices.
        self.cursor.execute('SELECT MAX(id) AS max FROM blockDeviceTable LIMIT 1')
        new_block_dev_id = self.cursor.fetchone()['max'] + 1

        # The application parameters are slightly different between linux apps
        # and mirage apps, but the linux apps also need to have the
        # information necessary to add block devices
        for i in range(len(apps)):
            if self.linux_regex.match(apps[i]['vm_os']):
                apps[i]['img_id'] = new_block_dev_id
                new_block_dev_id = new_block_dev_id + 1
                apps[i]['img_name'] = '/opt/mcp/images/{}.img'.format(apps[i]['name'])
                apps[i]['path'] = apps[i]['name']
            elif self.mirage_regex.match(apps[i]['vm_os']):
                apps[i]['img_id'] = None
                apps[i]['img_name'] = None
                apps[i]['path'] = None
            else:
                msg = 'unsupported OS type: {}'.format(apps[i]['vm_os'])
                raise NotImplementedError(msg)

            # Add the parameter information, for now use the application ID
            # and name as the parameter ID and name, and then the parameter
            # type is specific to the application:
            #   prime           = integer (0)
            #   sine(2)/cosine  = float (1)
            apps[i]['param_id'] = apps[i]['param']
            apps[i]['param_name'] = apps[i]['name']
            if apps[i]['type'] == 'INTEGER':
                apps[i]['param_type'] = 0
                apps[i]['param_size'] = 4
            elif apps[i]['type'] == 'REAL':
                apps[i]['param_type'] = 1
                apps[i]['param_size'] = 8
            else:
                msg = 'missing parameter type information for app: {}, param: {}'.format(apps[i]['name'], apps[i]['type'])
                raise NotImplementedError(msg)

        linux_apps = [a for a in apps if self.linux_regex.match(a['vm_os'])]

        # Create the block devices for linux application images
        self.cursor.executemany('INSERT INTO blockDeviceTable VALUES(:img_id,"raw","phy",:img_name,"ext2");', linux_apps)

        # Add the applications
        self.cursor.executemany('INSERT INTO appTable VALUES(:id,:name,:path,:img_id);', apps)

        # Add the parameters
        self.cursor.executemany('INSERT INTO paramTable VALUES(:param_id,:param_name,:param_type,:param_size,:param_size,0);', apps)

        # Link the applications and parameters
        self.cursor.executemany('INSERT INTO appParamLink VALUES(:id,:param_id,1);', apps)

        # Associate the application images with the domain the applications
        # reside in
        self.cursor.executemany('INSERT INTO blockDevDomainTable VALUES(:vm,:img_id,"xvdb","ro");', linux_apps)

        # Now link the applications to the domains they should run in
        self.cursor.executemany('INSERT INTO appDomainLink VALUES(:vm,:id);', apps)

        # Lastly allow the domains to run in the "operating" state
        self.cursor.executemany('INSERT INTO appDomainLink VALUES(:vm,:id);', apps)

        self.db.commit()

        return apps
