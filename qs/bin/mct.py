#!/usr/bin/env python
"""
A module that handles generating a new configuration file for the MCP target.
"""

import sqlite3
import shutil
import tempfile
import os.path
import string

# For the get_ip_address() function
import socket
import fcntl
import struct

# Disable some pylint warnings that I don't care about
# pylint: disable=line-too-long,fixme,invalid-name


def get_ip_address(ifname):
    """
    Retreive the IP address of a specified network adapter.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    # Use the SIOCGIFADDR ioctl (0x8915) to get the IP address of the socket
    # that was just created: http://linux.die.net/man/7/netdevice
    SIOCGIFADDR = 0x8915

    # The ioctl() parameter is the ifreq structure, which is 256 bytes in size,
    # the interface name is placed in the "ifr_name" field, which is in the
    # first 16 bytes of the struct.
    result = fcntl.ioctl(sock.fileno(), SIOCGIFADDR, struct.pack('256s', ifname[:15]))

    # The returned buffer is the ifreq structure, extract the ip address from
    # the ifr_addr field (bytes 20-24 contain the ip address), turn the bytes
    # a normal IPv4 address string.
    return socket.inet_ntoa(result[20:24])


def get_gateway_ip():
    """
    Returns the default network gateway IP address and network adapter.
    """
    routes = open('/proc/net/route', 'r')
    for line in routes:
        fields = line.strip().split()
        if fields:
            if fields[2] != 'Gateway' and fields[2] != '00000000':
                return (fields[0], socket.inet_ntoa(struct.pack("<L", int(fields[2], 16))))
    # If this line is reached, presumably there is no defined default gateway,
    # just return a network values
    return ('eth0', '192.268.0.1')


def get_network_info():
    """
    Returns the default network interface, gateway and IP address.
    """
    (iface, gate) = get_gateway_ip()
    addr = get_ip_address(iface)
    return (iface, gate, addr)


class Mct(object):
    """
    A class to manage the operations necessary to create an MCT configuration file.
    """
    def __init__(self):
        self.working_dir = tempfile.mkdtemp()

        self.db = None
        self.cursor = None
        self.open()

        # the MCT that was just opened is (should be) a blank database
        self.cursor.executescript('''
            BEGIN TRANSACTION;

            PRAGMA foreign_keys = ON;

            CREATE TABLE flightLegTable (
                id          INTEGER PRIMARY KEY,
                name        TEXT
            );

            CREATE TABLE opModeTable (
                id          INTEGER PRIMARY KEY,
                name        TEXT
            );

            CREATE TABLE scheduleTable (
                id          INTEGER PRIMARY KEY,
                name        TEXT NOT NULL UNIQUE,
                timeslice   INTEGER DEFAULT 30
            );

            CREATE TABLE partitionTable (
                id          INTEGER PRIMARY KEY,
                name        TEXT NOT NULL UNIQUE,
                memory      INTEGER NOT NULL,   -- memory to allocate in MB
                kernel      TEXT NOT NULL,      -- path to kernel image
                extra       TEXT,               -- additional domain boot params
                ramdisk     TEXT                -- path to ramdisk image
            );

            CREATE TABLE schedPartitionAllocTable (
                schedule    INTEGER NOT NULL,
                partition   INTEGER NOT NULL,
                weight      INTEGER default 256,
                cpucap      INTEGER default 0,
                FOREIGN KEY(schedule)   REFERENCES scheduleTable(id),
                FOREIGN KEY(partition)  REFERENCES partitionTable(id),
                CONSTRAINT uc_schedPartition UNIQUE (schedule, partition)
            );

            CREATE VIEW schedPartitionAllocView AS
                SELECT
                    s.schedule AS schedule,
                    p.id AS id,
                    p.name AS name,
                    s.weight AS weight,
                    s.cpucap AS cpucap
                FROM schedPartitionAllocTable AS s
                LEFT JOIN partitionTable AS p
                ON s.partition == p.id;

            CREATE TABLE stateTable (
                id          INTEGER PRIMARY KEY,
                name        TEXT,
                schedule    INTEGER NOT NULL,
                flightLeg   INTEGER NOT NULL,
                opMode      INTEGER NOT NULL,
                FOREIGN KEY(schedule)   REFERENCES scheduleTable(id),
                FOREIGN KEY(flightLeg)  REFERENCES flightLegTable(id),
                FOREIGN KEY(opMode)     REFERENCES opModeTable(id),
                CONSTRAINT uc_flightLegOpMode UNIQUE (flightLeg, opMode)
            );

            CREATE TABLE mcpActionEnum (
                id          INTEGER PRIMARY KEY,
                name        TEXT
            );

            INSERT INTO mcpActionEnum VALUES(1,'flight_leg');
            INSERT INTO mcpActionEnum VALUES(2,'op_mode');
            INSERT INTO mcpActionEnum VALUES(3,'mcp_state');
            INSERT INTO mcpActionEnum VALUES(4,'reset_partition');
            INSERT INTO mcpActionEnum VALUES(5,'pause_partition');
            INSERT INTO mcpActionEnum VALUES(6,'unpause_partition');
            INSERT INTO mcpActionEnum VALUES(7,'log_message');
            INSERT INTO mcpActionEnum VALUES(8,'set_param');
            INSERT INTO mcpActionEnum VALUES(9,'domain_status');

            CREATE TABLE ruleTable (
                id          INTEGER PRIMARY KEY,
                name        TEXT,
                seconds     REAL NOT NULL DEFAULT 1.0,
                equation    TEXT NOT NULL DEFAULT '0',
                action      INTEGER,
                option      TEXT,
                FOREIGN KEY(action)     REFERENCES mcpActionEnum(id)
            );

            CREATE TABLE stateRuleLink (
                state       INTEGER NOT NULL,
                rule        INTEGER NOT NULL,
                FOREIGN KEY(state)      REFERENCES stateTable(id),
                FOREIGN KEY(rule)       REFERENCES ruleTable(id)
            );

            CREATE TABLE paramTable (
                id          INTEGER PRIMARY KEY,
                name        TEXT,
                type        TEXT,
                value       REAL NOT NULL DEFAULT 0.0
            );

            CREATE TABLE physicalInterfaceTable (
                id          INTEGER PRIMARY KEY,
                device      TEXT NOT NULL UNIQUE,
                type        TEXT NOT NULL DEFAULT 'dhcp',   -- dhcp|manual|static
                address     TEXT,
                netmask     TEXT,
                gateway     TEXT
            );

            CREATE TABLE virtualInterfaceTable (
                id          INTEGER PRIMARY KEY,
                interface   INTEGER,                        -- possible link to phys iface
                type        TEXT NOT NULL DEFAULT 'dhcp',   -- dhcp|manual|static
                address     TEXT,
                netmask     TEXT,
                gateway     TEXT,
                FOREIGN KEY(interface)  REFERENCES physicalInterfaceTable(id)
            );

            CREATE VIEW virtualInterfaceView AS
                SELECT
                    v.id AS id,
                    v.type AS type,
                    p.device AS device,
                    v.address AS address,
                    v.netmask AS netmask,
                    v.gateway AS gateway
                FROM virtualInterfaceTable AS v
                LEFT JOIN physicalInterfaceTable AS p
                ON v.interface == p.id;

            CREATE TABLE ifacePartitionTable (
                partition   INTEGER NOT NULL,
                vif         INTEGER NOT NULL,
                ip          TEXT,               -- [1-255].[1-255].[1-255].[1-255]
                mac         TEXT,               -- [00-ff]:[00-ff]:[00-ff]:[00-ff]:[00-ff]:[00-ff]
                rate        TEXT,               -- #[GMK][Bb]/s[@#[mu]s]
                FOREIGN KEY(partition) REFERENCES partitionTable(id),
                FOREIGN KEY(vif)       REFERENCES virtualInterfaceTable(id)
            );

            CREATE VIEW ifacePartitionView AS
                SELECT
                    i.partition AS partition,
                    i.ip AS ip,
                    i.mac AS mac,
                    i.rate AS rate,
                    v.id AS id
                FROM virtualInterfaceTable AS v
                LEFT JOIN ifacePartitionTable AS i
                ON v.id == i.vif;

            CREATE TABLE logicalDiskTable (
                id          INTEGER PRIMARY KEY,
                format      TEXT,                   -- raw|qcow|qcow2|vhd
                path        TEXT,                   -- path to image to place in partition
                size        TEXT,                   -- #[GMK][Bb]
                fstype      TEXT                    -- ext2/3/4|vfat|etc.
            );

            CREATE TABLE diskPartitionTable (
                partition   INTEGER NOT NULL,
                disk        INTEGER NOT NULL,
                vdev        TEXT,                   -- xvd[a-z]|hd[a-z]|sd[a-z]
                access      TEXT DEFAULT 'rw',      -- rw|ro
                FOREIGN KEY(partition) REFERENCES partitionTable(id),
                FOREIGN KEY(disk)      REFERENCES logicalDiskTable(id),
                CONSTRAINT uc_partitionDev UNIQUE (partition, vdev)
            );

            CREATE VIEW diskPartitionView AS
                SELECT
                    d.partition AS partition,
                    l.id AS id,
                    l.format AS format,
                    l.path AS path,
                    d.vdev AS vdev,
                    d.access AS access
                FROM diskPartitionTable AS d
                LEFT JOIN logicalDiskTable AS l
                ON d.disk == l.id;

            CREATE TABLE pciDevTable (
                id          INTEGER PRIMARY KEY,
                name        TEXT,
                domain      INT NOT NULL,
                bus         INT NOT NULL,
                device      INT NOT NULL,
                function    INT,    -- If the function is NULL, then the config will
                                    -- specify '*' which assigns all functions to a domain.
                CONSTRAINT uc_pciAddr UNIQUE (domain, bus, device, function)
            );

            CREATE TABLE pciPartitionTable (
                partition   INTEGER NOT NULL,
                pci         INTEGER NOT NULL,
                FOREIGN KEY(partition) REFERENCES partitionTable(id),
                FOREIGN KEY(pci)       REFERENCES pciDevTable(id)
            );

            CREATE VIEW pciPartitionView AS
                SELECT
                    p.partition AS partition,
                    pci.domain AS domain,
                    pci.bus AS bus,
                    pci.device AS device,
                    pci.function AS function
                FROM pciDevTable AS pci
                LEFT JOIN pciPartitionTable AS p
                ON p.pci == pci.id;

            COMMIT;
            ''')

        # Create the static parts of MCT that are not taken from the QS/VMS
        # database at this time
        self.cursor.executescript('''
                BEGIN TRANSACTION;
                INSERT INTO flightLegTable VALUES(1,'Run');
                INSERT INTO flightLegTable VALUES(2,'Stop');
                INSERT INTO opModeTable VALUES(1,'mode 1');
                INSERT INTO scheduleTable VALUES(1,'default',10);
                INSERT INTO scheduleTable VALUES(2,'safe',10);
                INSERT INTO stateTable VALUES(1,'operating',1,1,1);
                INSERT INTO stateTable VALUES(2,'halted',2,2,1);
                INSERT INTO ruleTable VALUES(1,'move to halted state',3600.0,'1',3,2);
                INSERT INTO ruleTable VALUES(2,'monitor domain state',60.0,'1',9,0);
                INSERT INTO stateRuleLink VALUES(1,1);
                INSERT INTO stateRuleLink VALUES(1,2);
                INSERT INTO stateRuleLink VALUES(2,2);
                COMMIT;
                ''')

        # For now parameters are not associated with applications, so just add
        # 100 parameters as placeholders
        params = [(i, 'param{}'.format(i)) for i in range(1, 100)]
        self.cursor.executemany('INSERT INTO paramTable VALUES(?,?,NULL,0.0);', params)

        # Add the standard domU disks
        self.cursor.executescript('''
                BEGIN TRANSACTION;
                INSERT INTO logicalDiskTable VALUES(1,'raw','/dev/vg0/dom1root','700M','ext4');
                INSERT INTO logicalDiskTable VALUES(2,'raw','/dev/vg0/dom2root','700M','ext4');
                INSERT INTO logicalDiskTable VALUES(3,'raw','/dev/vg0/dom3root','700M','ext4');
                INSERT INTO logicalDiskTable VALUES(4,'raw','/dev/vg0/dom4root','700M','ext4');
                INSERT INTO logicalDiskTable VALUES(5,'raw','/dev/vg0/dom5root','700M','ext4');
                INSERT INTO logicalDiskTable VALUES(6,'raw','/dev/vg0/domUopt','100M','ext4');
                COMMIT;
                ''')

        self.db.commit()

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

    def addapps(self, apps, dom0_ip, domu_ip_range, db_password):
        """
        Adds one or more applications to the current MCT configuration file.
        """
        # The apps parameter is an iterable list of application configurations
        # that contains the following values:
        #   - id
        #   - name
        #   - param
        # We need to add the following values so that MCT has enough
        # information for a minimal valid application configuration:
        #   - kernel image
        #   - memory
        #   - vcpus
        #   - serial
        #   - disk
        #   - vif
        #   - extra params (image boot params, and app paras)

        (_, gateway_ip, vms_ip_addr) = get_network_info()

        # Figure out the IP address prefix to use for the domains
        domu_ip_prefix = string.rsplit(dom0_ip, '.', 1)[0]

        # These static values were determined during integration testing for
        # the SHARC mission.
        #   name = <design_part_name> (app name may not be unique)
        #   kernel = '/root/zImage'
        #   memory = 128
        #
        # If the domu should use DHCP these are the extra boot params that
        # should be specified:
        #   extra = 'console=hvc0 xencons=tty root=/dev/xvda ro
        #       domu_start=/opt/mcp/images/<name> domu_server=<bbb ip> domu_param=<param>'
        #
        # If a domu IP range is specified, these are the extra boot params that
        # should be specified:
        #   extra = 'console=hvc0 xencons=tty root=/dev/xvda
        #       domu_start=/opt/mcp/images/<name> domu_server=<bbb ip> domu_param=<param>
        #       ip=<domu prefix>.<domu IP range>+<id> gw=<domu prefix.1> netmask=255.255.255.0'
        for i in range(len(apps)):
            # apps[i]['kernel'] = '{}.gz'.format(apps[i]['name'])
            apps[i]['kernel'] = '/root/zImage'
            apps[i]['memory'] = 128
            apps[i]['ramdisk'] = None

            # Set the domU extra boot params
            # apps[i]['extra'] = 'console=hvc0 xencons=tty root=/dev/xvda domu_start=/opt/mcp/images/{} domu_server={} domu_param={}'.format(apps[i]['name'], vms_ip_addr, apps[i]['param'])
            apps[i]['extra'] = 'console=hvc0 xencons=tty root=/dev/xvda --password={} --app={} --address={}'.format(db_password, apps[i]['id'], vms_ip_addr)
            if domu_ip_range:
                apps[i]['extra'] += ' ip={}.{} gw={} netmask=255.255.255.0'.format(domu_ip_prefix, int(domu_ip_range) + int(apps[i]['vm']), gateway_ip)

        # These values are used for every domain, so they are added
        # automatically by the mcpprep script that runs on the MCP target
        #   vcpus = 2
        #   serial = 'pty'
        #   vif = [ 'bridge=br0' ]

        # Every app needs 2 things:
        #   1. an entry in the partitionTable
        #   2. The partition assigned to a schedule (the 'run' schedule)
        self.cursor.executemany('INSERT INTO partitionTable VALUES(:id,:part,:memory,:kernel,:extra,:ramdisk);', apps)

        # allocate the partition to schedule 1
        self.cursor.executemany('INSERT INTO schedPartitionAllocTable VALUES(1,:id,NULL,NULL);', apps)

        # These disks needed for each application, so add the correct
        # references.  dom#root = <virtual machine ID>, domUopt = 6
        #   disk = [ 'phy:/dev/vg0/dom#root,xvda,w', 'phy:/dev/vg0/domUopt,xvdb,w' ]
        self.cursor.executemany('INSERT INTO diskPartitionTable VALUES(:id,:vm,\'xvda\',\'w\');', apps)
        self.cursor.executemany('INSERT INTO diskPartitionTable VALUES(:id,6,\'xvdb\',\'w\');', apps)

        self.db.commit()

        return apps
