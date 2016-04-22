-- This is a blank schema to generate MCT.
--
-- Any hardcoded values that are necessary for the operation of the target 
-- platform are also defined in this file.  They will be removed when the are no 
-- longer necessary.
--
-- Copyright (c) 2016, DornerWorks, Ltd.

PRAGMA foreign_keys = ON;

BEGIN TRANSACTION;

CREATE TABLE flightLegTable (
    id              INTEGER PRIMARY KEY,
    name            TEXT
);

CREATE TABLE opModeTable (
    id              INTEGER PRIMARY KEY,
    name            TEXT
);

CREATE TABLE stateTable (
    id              INTEGER PRIMARY KEY,
    name            TEXT,
    flightLeg       INTEGER NOT NULL,
    opMode          INTEGER NOT NULL,
    FOREIGN KEY(flightLeg)  REFERENCES flightLegTable(id),
    FOREIGN KEY(opMode)     REFERENCES opModeTable(id),
    CONSTRAINT uc_flightLegOpMode UNIQUE (flightLeg, opMode)
);

-- This table defines numbers for the parameter types to be easily mapped to 
-- enumeration values in MCP
CREATE TABLE paramTypeEnum (
    id            INTEGER PRIMARY KEY,
    type          TEXT
);
INSERT INTO paramTypeEnum VALUES(0, 'INTEGER');
INSERT INTO paramTypeEnum VALUES(1, 'REAL');
INSERT INTO paramTypeEnum VALUES(2, 'TEXT');
INSERT INTO paramTypeEnum VALUES(3, 'BLOB');

CREATE TABLE paramTable (
    id              INTEGER PRIMARY KEY,
    name            TEXT NOT NULL,
    type            TEXT NOT NULL,
    min_bytes       INTEGER NOT NULL,
    max_bytes       INTEGER NOT NULL,
    value           BLOB NOT NULL DEFAULT 0.0,
    FOREIGN KEY(type) REFERENCES paramTypeEnum(id)
);

CREATE TABLE mcpActionEnum(
    name            TEXT PRIMARY KEY
);
INSERT INTO mcpActionEnum VALUES('flight_leg');
INSERT INTO mcpActionEnum VALUES('op_mode');
INSERT INTO mcpActionEnum VALUES('mcp_state');
INSERT INTO mcpActionEnum VALUES('reset_domain');
INSERT INTO mcpActionEnum VALUES('pause_domain');
INSERT INTO mcpActionEnum VALUES('unpause_domain');
INSERT INTO mcpActionEnum VALUES('log_message');
INSERT INTO mcpActionEnum VALUES('set_param');
INSERT INTO mcpActionEnum VALUES('domain_status');

-- Rules may contain:
--  ()  : parenthesis for evaluation priority.  Evaluation is currently purely 
--        left-to-right without operator precedence, so parenthesis must be used 
--        to prioritize a sequence.
--  $P1 : insert the value of parameter "1", where "1" is a valid parameter ID.
--  $D1 : insert the current health of domain "1", where "1" is a valid domain 
--        ID.  Values for the domain states are in the "domStateEnum" table.
--  $A1 : insert the current health of app "1", where "1" is a valid app ID.  
--        Values for the domain states are in the "appStateEnum" table.
--                                                              
-- The following unary operations are supported:
--  ! (logical "not"), ~ (bitwise "not")
--                                                              
-- The following binary math operations are supported:
--  *, /, -, +, % (modulus), ** (exp)
--                                                              
-- The following binary logical operations are supported:
--  !=, ==, >, <, >=, <=, || (or), && (and)
--                                                              
-- The following binary bitwise operations are supported:
--  ^ (xor), | (or), & (and), >> (right shift), << (left shift)
--
--
-- Parameter equations may contain:
--  $?  : the "result" value
--  all other values permitted by rules
--
CREATE TABLE ruleTable (
    id              INTEGER PRIMARY KEY,
    name            TEXT NOT NULL,
    equation        TEXT NOT NULL DEFAULT '0',
    target          INTEGER,
    action          TEXT NOT NULL,
    parameter       TEXT,
    FOREIGN KEY(action)     REFERENCES mcpActionEnum(name)
);

CREATE TABLE domStateEnum (
    id              INTEGER PRIMARY KEY,
    state           INTEGER UNIQUE
);

INSERT INTO domStateEnum VALUES(0,'unknown');
INSERT INTO domStateEnum VALUES(1,'init');
INSERT INTO domStateEnum VALUES(2,'init_error');
INSERT INTO domStateEnum VALUES(3,'operating');
INSERT INTO domStateEnum VALUES(4,'paused');
INSERT INTO domStateEnum VALUES(5,'stopped');
INSERT INTO domStateEnum VALUES(6,'error');

CREATE TABLE appStateEnum (
    id              INTEGER PRIMARY KEY,
    state           INTEGER UNIQUE
);

INSERT INTO appStateEnum VALUES(0,'unknown');
INSERT INTO appStateEnum VALUES(1,'init');
INSERT INTO appStateEnum VALUES(2,'init_error');
INSERT INTO appStateEnum VALUES(3,'operating');
INSERT INTO appStateEnum VALUES(4,'paused');
INSERT INTO appStateEnum VALUES(5,'stopped');
INSERT INTO appStateEnum VALUES(6,'error');

CREATE TABLE stateRuleLink (
    state           INTEGER NOT NULL,
    rule            INTEGER NOT NULL,
    seconds         REAL NOT NULL DEFAULT 1.0,
    FOREIGN KEY(state)      REFERENCES stateTable(id),
    FOREIGN KEY(rule)       REFERENCES ruleTable(id)
    CONSTRAINT uc_stateRule UNIQUE (state, rule)
);

-- Each state is associated with one or more schedules.  Each schedule has 
-- a "type" which can be either "credit" or "rtds".  Each schedule is implicitly 
-- a CPU pool.
--
-- TODO: add support for the A653 scheduler.
--
-- Credit schedule uses the timeslice and ratelimit values.  The default 
-- schedule things are:
--  timeslice = 10 (msec)
--  ratelimit = 1000 (usec)
-- 
-- The default schedule "0" is the schedule that the control domain (dom0) uses.  
-- When the system starts it contains all of the CPUs.
--
-- Each "schedule" is translated into a Xen CPU poll.
--
CREATE TABLE scheduleTable (
    id              INTEGER PRIMARY KEY,
    name            TEXT NOT NULL UNIQUE,
    type            TEXT NOT NULL DEFAULT 'credit',
    timeslice       INTEGER DEFAULT 10,
    ratelimit       INTEGER DEFAULT 1000
);

-- The CPU table identifies which CPUs should be assigned to a schedule/CPU 
-- pool.
--
-- The default "Pool-0" which runs the control "Domain-0" is assigned physical 
-- CPU 0.
CREATE TABLE cpuTable (
    id              INTEGER PRIMARY KEY,
    schedule        INTEGER,
    FOREIGN KEY(schedule) REFERENCES scheduleTable(id)
);

-- TODO: ensure that domain cannot have more vcpus than the scheduler it is 
-- assigned to has cpus.
CREATE TABLE domainTable (
    id              INTEGER PRIMARY KEY,
    name            TEXT NOT NULL,
    schedule        INTEGER NOT NULL,
    memory          INTEGER NOT NULL,
    kernel          TEXT NOT NULL,
    extra           TEXT,
    ramdisk         TEXT,
    vcpus           INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY(schedule) REFERENCES scheduleTable(id)
);

-- Not all schedule/domain options apply to all types of schedules.  A value of 
-- -1 indicates that the default schedule value should be used.
-- 
-- CREDIT
-- 
-- cpucap:
-- The total amount of CPU that a domain is allowed to use/be scheduled for.
-- 0 = unlimited
-- 50 = 50% of 1 CPU
-- 100 = 100% of 1 CPU
-- 200 = 100% of 2 CPUs
-- etc.
-- 
-- weight:
-- relative priority compared to other domains.  So a domain with a weight of 
-- 512 is provided twice as much CPU as a domain with a weight of 256.  Valid 
-- range is from 1 to 65535.  If not specified the default is 256.
-- 
-- RTDS
-- 
-- period:
-- A value in microseconds that specifies how often the domain's budget is 
-- renewed.  The default period is 10,000 usec.
-- 
-- budget:
-- A value in microseconds that specifies how much CPU time the domain is 
-- allowed within the given period.  The default budget is 4,000 usec.
--
CREATE TABLE stateDomainAllocTable (
    domain          INTEGER NOT NULL,
    state           INTEGER NOT NULL,
    cpucap          INTEGER DEFAULT -1,
    weight          INTEGER DEFAULT -1,
    period          INTEGER DEFAULT -1,
    budget          INTEGER DEFAULT -1,
    FOREIGN KEY(domain) REFERENCES domainTable(id),
    FOREIGN KEY(state) REFERENCES stateTable(id),
    CONSTRAINT uc_stateDomain UNIQUE (domain, state)
);

-- A list of supported block device formats
CREATE TABLE blockDevFormatEnum (
    format          TEXT PRIMARY KEY
);
INSERT INTO blockDevFormatEnum VALUES("raw");
INSERT INTO blockDevFormatEnum VALUES("qcow");
INSERT INTO blockDevFormatEnum VALUES("qcow2");
INSERT INTO blockDevFormatEnum VALUES("vhd");

-- A list of supported block device types
CREATE TABLE blockDevTypeEnum (
    type            TEXT PRIMARY KEY
);
INSERT INTO blockDevTypeEnum VALUES("file");
INSERT INTO blockDevTypeEnum VALUES("phy");

-- Allowed filesystem types
CREATE TABLE fstypeEnum (
    fstype          TEXT PRIMARY KEY
);
INSERT INTO fstypeEnum VALUES("vfat");
INSERT INTO fstypeEnum VALUES("ext4");
INSERT INTO fstypeEnum VALUES("ext3");
INSERT INTO fstypeEnum VALUES("ext2");
INSERT INTO fstypeEnum VALUES("jffs2");
INSERT INTO fstypeEnum VALUES("squashfs");
INSERT INTO fstypeEnum VALUES("ubifs");
INSERT INTO fstypeEnum VALUES("cifs");
INSERT INTO fstypeEnum VALUES("isofs");
INSERT INTO fstypeEnum VALUES("btrfs");
-- A block device must be a pre-existing partition or a file.  Once defined here 
-- it can be connected to a domain.
--
-- Here are the valid values for the different fields:
--
-- format:  raw|qcow|qcow2|vhd
-- path:    name/path of the filesystem image
CREATE TABLE blockDeviceTable (
    id              INTEGER PRIMARY KEY,
    format          TEXT NOT NULL,
    type            TEXT NOT NULL,
    path            TEXT NOT NULL,
    fstype          TEXT NOT NULL,
    FOREIGN KEY(format)     REFERENCES blockDevFormatEnum(format),
    FOREIGN KEY(type)       REFERENCES blockDevTypeEnum(type),
    FOREIGN KEY(fstype)     REFERENCES fstypeEnum(fstype)
);

-- If the function is NULL, then the config will specify '*' which assigns all 
-- functions to a domain.
CREATE TABLE pciDevTable (
    id              INTEGER PRIMARY KEY,
    name            TEXT,
    pci_domain      INTEGER NOT NULL DEFAULT 0,
    pci_bus         INTEGER NOT NULL,
    pci_device      INTEGER NOT NULL,
    pci_function    INTEGER,
    CONSTRAINT uc_pciAddr UNIQUE (pci_domain, pci_bus, pci_device, pci_function)
);

-- A list of valid interface types for physical interfaces
CREATE TABLE physIfaceTypeEnum (
    type            TEXT PRIMARY KEY
);
INSERT INTO physIfaceTypeEnum VALUES("dhcp");
INSERT INTO physIfaceTypeEnum VALUES("static");
INSERT INTO physIfaceTypeEnum VALUES("manual");

-- This table is used to define additional interfaces that should be created 
-- (mostly bridges).  Real interfaces don't have to be defined in this table.  
-- If an interface is defined as a 'static' type, then the address, netmask and 
-- gateway must be provided.
--
-- The type of the interface can either be
--  dhcp:   which requires a DHCP server to be accessible
--  static: which requires that the address, netmask and gateway are specified
--  manual: which requires that this physical device be connected to a bridge
CREATE TABLE physicalInterfaceTable (
    id              INTEGER PRIMARY KEY,
    device          TEXT NOT NULL UNIQUE,
    type            TEXT NOT NULL DEFAULT "dhcp",
    address         TEXT,
    netmask         TEXT,
    gateway         TEXT,
    FOREIGN KEY(type)  REFERENCES physIfaceTypeEnum(type)
);

-- A list of valid interface types for physical interfaces
CREATE TABLE bridgeIfaceTypeEnum (
    type            TEXT PRIMARY KEY
);
INSERT INTO bridgeIfaceTypeEnum VALUES("dhcp");
INSERT INTO bridgeIfaceTypeEnum VALUES("static");

-- This table defines the bridges that connect to a domain.  They can be linked 
-- to a physical interface, or left as a purely virtual connection between 
-- domains.  In either case an entry in this table will result in a bridge being 
-- created in domain 0.
--
-- The type of the interface can either be
--  dhcp:   which requires a DHCP server to be accessible
--  static: which requires that the address, netmask and gateway are specified
CREATE TABLE bridgeTable (
    id              INTEGER PRIMARY KEY,
    name            TEXT NOT NULL UNIQUE,
    interface       INTEGER,
    type            TEXT NOT NULL DEFAULT "dhcp",
    address         TEXT,
    netmask         TEXT,
    gateway         TEXT,
    FOREIGN KEY(interface)  REFERENCES physicalInterfaceTable(id),
    FOREIGN KEY(type)  REFERENCES bridgeIfaceTypeEnum(type)
);

-- This table connects the virtual interfaces (bridges) to particular domains.  
-- 
-- ip:      [1-255].[1-255].[1-255].[1-255], if left blank it assumes that the 
-- domain will handle obtaining an IP address
-- mac:     [00-ff]:[00-ff]:[00-ff]:[00-ff]:[00-ff]:[00-ff]
-- rate:    both NULL or they define the amount of bytes allowed on this 
--          interface per interval, and the size of the interval.  The maximum 
--          values allowed are:
--              bytes: int64 (not uint)
--              usec: uint32
CREATE TABLE ifaceDomainTable (
    domain          INTEGER NOT NULL,
    bridge          INTEGER NOT NULL,
    ip              TEXT,
    mac             TEXT,
    rate_bytes_per_interval INTEGER,
    rate_usec_per_interval  INTEGER,
    FOREIGN KEY(domain)     REFERENCES domainTable(id),
    FOREIGN KEY(bridge)     REFERENCES bridgeTable(id)
);

-- Access permission types
CREATE TABLE accessEnum (
    access          TEXT PRIMARY KEY
);
INSERT INTO accessEnum VALUES("rw");
INSERT INTO accessEnum VALUES("ro");

-- This table allows connecting a block device to a domain.
--
-- device:  physical device reference
-- vdev:    xvd[a-z]
-- access:  rw|ro
CREATE TABLE blockDevDomainTable (
    domain          INTEGER NOT NULL,
    device          INTEGER NOT NULL,
    vdev            TEXT NOT NULL,
    access          TEXT NOT NULL,
    FOREIGN KEY(domain)     REFERENCES domainTable(id),
    FOREIGN KEY(device)     REFERENCES blockDeviceTable(id),
    FOREIGN KEY(access)     REFERENCES accessEnum(access),
    CONSTRAINT uc_domainDev UNIQUE (domain, vdev)
);

-- This table connects PCI devices to a domain.  Each PCI device can only be 
-- used once.
-- This is only applicable for x86 targets
CREATE TABLE pciDomainTable (
    domain          INTEGER NOT NULL,
    pci             INTEGER NOT NULL UNIQUE,
    FOREIGN KEY(domain)     REFERENCES domainTable(id),
    FOREIGN KEY(pci)        REFERENCES pciDevTable(id)
    CONSTRAINT uc_domainPci UNIQUE (domain, pci)
);

-- This table defines the applications in the system.
--
-- The path column is only important for applications that are contained in 
-- separate files than their domain, such as for Linux domains and applications.
--
-- The dev column can be used to indicate if the application resides on a block 
-- device that may not be automatically mounted by the domain.
CREATE TABLE appTable (
    id              INTEGER PRIMARY KEY,
    name            TEXT,
    path            TEXT,
    dev             INTEGER,
    FOREIGN KEY(dev)     REFERENCES blockDeviceTable(id)
);

-- A value of NULL in the "write" column indicates that the parameter is 
-- read-only for the specified application.  Only 1 application is allowed to 
-- write a parameter.
CREATE TABLE appParamLink (
    app             INTEGER NOT NULL,
    param           INTEGER NOT NULL,
    write           INTEGER DEFAULT NULL,
    FOREIGN KEY(app)        REFERENCES appTable(id),
    FOREIGN KEY(param)      REFERENCES paramTable(id),
    CONSTRAINT uc_appParam UNIQUE (app, param),
    CONSTRAINT uc_paramWrite UNIQUE (param, write)
);

-- This table defines the association between applications and domains
CREATE TABLE appDomainLink (
    domain          INTEGER NOT NULL,
    app             INTEGER NOT NULL,
    FOREIGN KEY(domain)     REFERENCES domainTable(id),
    FOREIGN KEY(app)        REFERENCES appTable(id),
    CONSTRAINT uc_appDomain UNIQUE (domain, app)
);

-- A view to return all information necessary to initialize the parameters on 
-- the target system
CREATE VIEW paramDetailsView AS
    SELECT
        d.domain AS domain,
        d.app AS app,
        l.param AS param,
        l.write AS write,
        p.name AS name,
        p.type AS type,
        p.min_bytes AS min_bytes,
        p.max_bytes AS max_bytes,
        p.value AS value
    FROM appDomainLink AS d
    LEFT JOIN appParamLink AS l
        ON d.app == l.app
    LEFT JOIN paramTable AS p
        ON l.param == p.id;

-- A view to make it easier to extract the block device configuration for 
-- a domain
CREATE VIEW blockDevDomainView AS
    SELECT
        d.domain AS domain,
        d.device AS device,
        b.format AS format,
        b.type AS type,
        b.path AS path,
        b.fstype AS fstype,
        d.vdev AS vdev,
        d.access AS access
    FROM blockDevDomainTable AS d
    LEFT JOIN blockDeviceTable AS b
        ON d.device == b.id;
-- A view to return all information necessary to initialize the applications on 
-- the target system
CREATE VIEW appDetailsView AS
    SELECT
        d.domain AS domain,
        d.app AS app,
        a.name AS name,
        a.path AS path,
        b.vdev AS vdev,
        b.fstype AS fstype
    FROM appDomainLink as d
    LEFT JOIN appTable as a
        ON d.app == a.id
    LEFT JOIN blockDevDomainView AS b
        ON b.device == a.dev AND b.domain == d.domain;

-- A view to make it easier to extract the virtual/physical interface 
-- configuration for a domain
CREATE VIEW ifaceDomainView AS
    SELECT
        i.domain AS domain,
        i.ip AS ip,
        i.mac AS mac,
        i.rate_bytes_per_interval AS rate_bytes_per_interval,
        i.rate_usec_per_interval AS rate_usec_per_interval,
        b.name AS bridge
    FROM bridgeTable AS b
    LEFT JOIN ifaceDomainTable AS i
        ON b.id == i.bridge;

-- A view to make it easier to extract the PCI configuration for a domain
CREATE VIEW pciDomainView AS
    SELECT
        p.domain AS i,
        d.pci_domain AS domain,
        d.pci_bus AS bus,
        d.pci_device AS device,
        d.pci_function AS function
    FROM pciDevTable AS d
    LEFT JOIN pciDomainTable AS p
        ON p.pci == d.id;

--
-- The MCT schema ends here, and the hardcoded application data beings.
--

--
-- SCHEDULE
--

-- Simple run/stop flight legs for testing
INSERT INTO flightLegTable VALUES(0,'init');
INSERT INTO flightLegTable VALUES(1,'run');
INSERT INTO flightLegTable VALUES(2,'safe');

-- Only 1 op mode for testing
INSERT INTO opModeTable VALUES(0,'init');
INSERT INTO opModeTable VALUES(1,'on');

-- Simple MCP states for the simple testing flight legs and op modes.
INSERT INTO stateTable VALUES(0,'init',0,0);
INSERT INTO stateTable VALUES(1,'operating',1,1);
INSERT INTO stateTable VALUES(2,'halted',2,1);

-- Simple rules that stop all domains after an hour, and checks the domain state 
-- every minute.
INSERT INTO ruleTable VALUES(1,'move to halted state','1',2,'mcp_state',NULL);
INSERT INTO ruleTable VALUES(2,'monitor domain state','1',0,'domain_status',NULL);

-- Simple state to rule linking to run the domain state monitor rule in all 
-- states.
INSERT INTO stateRuleLink VALUES(1,2,60.0);
INSERT INTO stateRuleLink VALUES(2,2,60.0);

--
-- PLATFORM RESOURCES
--

-- The default schedule/cpupool which is always installed.  The default schedule 
-- is the schedule that the control domain (Domain-0) runs in.
INSERT INTO scheduleTable VALUES (0, 'Pool-0', 'credit', 10, 1000);

-- The schedule/cpupool for all application domains to run in.
INSERT INTO scheduleTable VALUES (1, 'apps', 'rtds', NULL, NULL);

-- CPU for "Domain-0"
INSERT INTO cpuTable VALUES (0, 0);

-- CPU for additional CPUpool/schedule
INSERT INTO cpuTable VALUES (1, 1);

-- Define the physical interface on this system (will be attached to the bridge)
INSERT INTO physicalInterfaceTable VALUES(0, "eth0", "manual", NULL, NULL, NULL);

-- Define the bridge on this system
INSERT INTO bridgeTable VALUES(0, "br0", 0, "dhcp", NULL, NULL, NULL);

--
-- DOMAIN
--

-- The control domain must be defined and accounted for in the schedule.  The 
-- kernel file doesn't mean much in this case but it is required by the 
-- domainTable.
INSERT INTO domainTable VALUES (0, 'Domain-0', 0, 512, "vmlinuz", NULL, NULL, 0);

-- In the default startup state 0 only "Domain-0" should be running, "Domain-0" 
-- should be running in all other states as well.
INSERT INTO stateDomainAllocTable VALUES(0, 0, -1, -1, -1, -1);
INSERT INTO stateDomainAllocTable VALUES(0, 1, -1, -1, -1, -1);
INSERT INTO stateDomainAllocTable VALUES(0, 2, -1, -1, -1, -1);

-- Define the pre-existing LVM partitions on the target platform
INSERT INTO blockDeviceTable VALUES(1, "raw", "phy", "/dev/vg0/dom1root", "ext4");
INSERT INTO blockDeviceTable VALUES(2, "raw", "phy", "/dev/vg0/dom2root", "ext4");
INSERT INTO blockDeviceTable VALUES(3, "raw", "phy", "/dev/vg0/dom3root", "ext4");
INSERT INTO blockDeviceTable VALUES(4, "raw", "phy", "/dev/vg0/dom4root", "ext4");
INSERT INTO blockDeviceTable VALUES(5, "raw", "phy", "/dev/vg0/dom5root", "ext4");

COMMIT;
