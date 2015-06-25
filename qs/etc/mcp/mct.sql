BEGIN TRANSACTION;

PRAGMA foreign_keys = ON;

CREATE TABLE flightLegTable (
    id          INTEGER PRIMARY KEY,
    name        TEXT
);

--INSERT INTO flightLegTable VALUES(1,'Launch');
--INSERT INTO flightLegTable VALUES(2,'Transit 1');
--INSERT INTO flightLegTable VALUES(3,'Transit 2');
--INSERT INTO flightLegTable VALUES(4,'Perform Experiments');
--INSERT INTO flightLegTable VALUES(5,'Safehold');

INSERT INTO flightLegTable VALUES(1,'Run');
INSERT INTO flightLegTable VALUES(2,'Stop');

CREATE TABLE opModeTable (
    id          INTEGER PRIMARY KEY,
    name        TEXT
);

INSERT INTO opModeTable VALUES(1,'mode 1');
--INSERT INTO opModeTable VALUES(2,'mode 2');
--INSERT INTO opModeTable VALUES(3,'mode 3');
--INSERT INTO opModeTable VALUES(4,'mode 4');
--INSERT INTO opModeTable VALUES(5,'mode 5');

CREATE TABLE scheduleTable (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    timeslice   INTEGER DEFAULT 30
);

INSERT INTO scheduleTable VALUES(1,'default',10);
INSERT INTO scheduleTable VALUES(2,'safe',10);
--INSERT INTO scheduleTable VALUES(2,'experiment',10);
--INSERT INTO scheduleTable VALUES(3,'safe',10);

CREATE TABLE partitionTable (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    memory      INTEGER NOT NULL,   -- memory to allocate in MB
    kernel      TEXT NOT NULL,      -- path to kernel image
    extra       TEXT,               -- additional domain boot params
    ramdisk     TEXT                -- path to ramdisk image
);

-- This test data creates 3 partitions (dom0 is always present but shouldn't be 
-- in the MCT tables):
--  1 = communications
--  2 = propulsion ctrl
--  3 = experiment ctrl
--
-- Finer control over what is running is accomplished by the rules pausing and 
-- unpausing partitions if necessary.  For example, in the 'Perform Experiments' 
-- flight leg propulsion should usually be off, but it may be needed on quickly 
-- if an orbital correction is necessary.
--

--INSERT INTO partitionTable VALUES(1,'communications',8,'mini-os',NULL,'mini-os.gz');
--INSERT INTO partitionTable VALUES(2,'propulsion ctrl',8,'mini-os',NULL,'mini-os.gz');
--INSERT INTO partitionTable VALUES(3,'experiment ctrl',8,'mini-os',NULL,'mini-os.gz');

INSERT INTO partitionTable VALUES(1,'prime1app',8,'primeapp',' --param_id=1','primeapp.gz');
INSERT INTO partitionTable VALUES(2,'prime2app',8,'primeapp',' --param_id=2','primeapp.gz');
INSERT INTO partitionTable VALUES(3,'sineapp',8,'sineapp',' --param_id=3','sineapp.gz');
INSERT INTO partitionTable VALUES(4,'sine2app',8,'sine2app',' --param_id=4','sine2app.gz');
INSERT INTO partitionTable VALUES(5,'cosapp',8,'cosapp',' --param_id=5','cosapp.gz');

-- weight and cpu are allowed to be NULL, in which case they won't be specified
-- when the ARLX config file is generated.
CREATE TABLE schedPartitionAllocTable (
    schedule    INTEGER NOT NULL,
    partition   INTEGER NOT NULL,
    weight      INTEGER default 256,
    cpucap      INTEGER default 0,
    FOREIGN KEY(schedule)   REFERENCES scheduleTable(id),
    FOREIGN KEY(partition)  REFERENCES partitionTable(id),
    CONSTRAINT uc_schedPartition UNIQUE (schedule, partition)
);

-- This test data defines the following partition allocations for the 3 
-- different ARLX schedules:
--
-- partitions |     comms | prop ctrl |  exp ctrl |
-- ------------------------------------------------
-- default    |      10ms |      10ms |           |
-- experiment |      10ms |      10ms |      20ms |
-- safe       |           |           |           |
--
-- In this case the experiment schedule adds a large block of time for 
-- experiment control.  Comms and propulsion control are left enabled in case 
-- they are needed and started paused, but can be unpaused and repaused with a 
-- rule.
--

-- default schedule
--INSERT INTO schedPartitionAllocTable VALUES(1,1,NULL,10);
--INSERT INTO schedPartitionAllocTable VALUES(1,2,NULL,10);

-- experiment schedule
--INSERT INTO schedPartitionAllocTable VALUES(2,1,NULL,10);
--INSERT INTO schedPartitionAllocTable VALUES(2,2,NULL,10);
--INSERT INTO schedPartitionAllocTable VALUES(2,3,NULL,20);

INSERT INTO schedPartitionAllocTable VALUES(1,1,NULL,NULL);
INSERT INTO schedPartitionAllocTable VALUES(1,2,NULL,NULL);
INSERT INTO schedPartitionAllocTable VALUES(1,3,NULL,NULL);
INSERT INTO schedPartitionAllocTable VALUES(1,4,NULL,NULL);
INSERT INTO schedPartitionAllocTable VALUES(1,5,NULL,NULL);

-- A view to make it easier to extract the partition schedule information
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

-- This test data models the following valid states (all X's):
--
--  Modes         | 1 | 2 | 3 | 4 | 5 | ARLX sched |
--  ------------------------------------------------
--  Launch    (1) | X |   |   |   |   |    default |
--  Transit 1 (2) | X | X | X | X |   |    default |
--  Transit 2 (3) | X |   | X | X | X |    default |
--  P Exp     (4) | X | X |   | X |   | experiment |
--  Safehold  (5) | X | X | X | X | X |       safe |
--
-- To prevent a partition from running in a particular flight leg/op mode state, 
-- the partition can be paused.  Or completely separate ARLX schedule can be 
-- designed.
--

-- Flight Leg 1: 'Launch'
--INSERT INTO stateTable VALUES(1,'Launch + 1',1,1,1);

-- Flight Leg 2: 'Transit 1'
--INSERT INTO stateTable VALUES(2,'Transit1 + 1',1,2,1);
--INSERT INTO stateTable VALUES(3,'Transit1 + 2',1,2,2);
--INSERT INTO stateTable VALUES(4,'Transit1 + 3',1,2,3);
--INSERT INTO stateTable VALUES(5,'Transit1 + 4',1,2,4);

-- Flight Leg 3: 'Transit 2'
--INSERT INTO stateTable VALUES(6,'Transit2 + 1',1,3,1);
--INSERT INTO stateTable VALUES(7,'Transit2 + 3',1,3,3);
--INSERT INTO stateTable VALUES(8,'Transit2 + 4',1,3,4);
--INSERT INTO stateTable VALUES(9,'Transit2 + 5',1,3,5);

-- Flight Leg 4: 'Perform Experiment'
--INSERT INTO stateTable VALUES(10,'Perform Experiment + 1',2,4,1);
--INSERT INTO stateTable VALUES(11,'Perform Experiment + 2',2,4,2);
--INSERT INTO stateTable VALUES(12,'Perform Experiment + 4',2,4,4);

-- Flight Leg 5: 'Safehold'
--INSERT INTO stateTable VALUES(13,'Safehold + 1',3,5,1);
--INSERT INTO stateTable VALUES(14,'Safehold + 2',3,5,2);
--INSERT INTO stateTable VALUES(15,'Safehold + 3',3,5,3);
--INSERT INTO stateTable VALUES(16,'Safehold + 4',3,5,4);
--INSERT INTO stateTable VALUES(17,'Safehold + 5',3,5,5);

-- Simple test states
INSERT INTO stateTable VALUES(1,'operating',1,1,1);
INSERT INTO stateTable VALUES(2,'halted',2,2,1);

-- SQLite doesn't support ENUM types, so create a little table to define the 
-- possible actions for rules
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

-- Rules may contain:
--  ()      : parenthesis for evaluation priority
--  $a      : insert the value of parameter "a"
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
CREATE TABLE ruleTable (
    id          INTEGER PRIMARY KEY,
    name        TEXT,
    seconds     REAL NOT NULL DEFAULT 1.0,
    equation    TEXT NOT NULL DEFAULT '0',
    action      INTEGER,
    option      TEXT,
    FOREIGN KEY(action)     REFERENCES mcpActionEnum(id)
);

--INSERT INTO ruleTable VALUES(1,'rule 1',0.625,'($3 > 0) && ($2 < 0)',4,'dom1');
--INSERT INTO ruleTable VALUES(2,'rule 2',1.2,0,5,'dom2');
--INSERT INTO ruleTable VALUES(3,'rule 3',3.0,'($5 - 55) > 0',6,'dom4');
--INSERT INTO ruleTable VALUES(4,'rule 4',0.789,'(55 - $5) < 0',5,'dom3');
--INSERT INTO ruleTable VALUES(5,'rule 5',10.5,1,6,'dom5');
--INSERT INTO ruleTable VALUES(6,'rule 6',3.0,'$4 * 2 + 55 == 75',7,'this is an error message!');
--INSERT INTO ruleTable VALUES(7,'rule 7',2.5,'$1 == 0',3,2.0);
--INSERT INTO ruleTable VALUES(8,'rule 8',0.9,'$1 == 0',3,3.0);
--INSERT INTO ruleTable VALUES(9,'rule 9',1.023456,'$1 == 0',3,4.0);
--INSERT INTO ruleTable VALUES(10,'rule 10',2.0,'$1 == 0',3,5.0);
--INSERT INTO ruleTable VALUES(11,'rule 11',1.0,'$1 == 0',3,1.0);
--INSERT INTO ruleTable VALUES(12,'rule 12',5.0,'$1 + $2',8,7);

--INSERT INTO ruleTable VALUES(1,'get status',60.0,'1',9,0);
INSERT INTO ruleTable VALUES(1,'move to halted state',3600.0,'1',3,0);
INSERT INTO ruleTable VALUES(2,'monitor domain state',60.0,'1',9,0);

CREATE TABLE stateRuleLink (
    state       INTEGER NOT NULL,
    rule        INTEGER NOT NULL,
    FOREIGN KEY(state)      REFERENCES stateTable(id),
    FOREIGN KEY(rule)       REFERENCES ruleTable(id)
);

-- There are 17 states and 11 rules, this set of random data just links some of 
-- them so data exists.

--INSERT INTO stateRuleLink VALUES(1,1);
--INSERT INTO stateRuleLink VALUES(2,2);
--INSERT INTO stateRuleLink VALUES(3,3);
--INSERT INTO stateRuleLink VALUES(4,4);
--INSERT INTO stateRuleLink VALUES(5,5);
--INSERT INTO stateRuleLink VALUES(6,6);
--INSERT INTO stateRuleLink VALUES(1,7);
--INSERT INTO stateRuleLink VALUES(2,8);
--INSERT INTO stateRuleLink VALUES(3,9);
--INSERT INTO stateRuleLink VALUES(4,10);
--INSERT INTO stateRuleLink VALUES(5,11);
--INSERT INTO stateRuleLink VALUES(12,10);
--INSERT INTO stateRuleLink VALUES(13,9);
--INSERT INTO stateRuleLink VALUES(14,8);
--INSERT INTO stateRuleLink VALUES(15,7);
--INSERT INTO stateRuleLink VALUES(16,6);
--INSERT INTO stateRuleLink VALUES(17,5);
--INSERT INTO stateRuleLink VALUES(7,4);
--INSERT INTO stateRuleLink VALUES(8,3);
--INSERT INTO stateRuleLink VALUES(9,2);
--INSERT INTO stateRuleLink VALUES(10,1);

-- Simple state to rule mapping for the demo.
INSERT INTO stateRuleLink VALUES(1,1);
INSERT INTO stateRuleLink VALUES(1,2);

CREATE TABLE paramTable (
    id          INTEGER PRIMARY KEY,
    name        TEXT,
    type        TEXT,
    port        TEXT
);

INSERT INTO paramTable VALUES(1,'param 1',NULL,NULL);
INSERT INTO paramTable VALUES(2,'param 2',NULL,NULL);
INSERT INTO paramTable VALUES(3,'param 3',NULL,NULL);
INSERT INTO paramTable VALUES(4,'param 4',NULL,NULL);
INSERT INTO paramTable VALUES(5,'param 5',NULL,NULL);
--INSERT INTO paramTable VALUES(6,'param 6',NULL,NULL);
--INSERT INTO paramTable VALUES(7,'param 7',NULL,NULL);

-- This table is used to define additional interfaces that should be created 
-- (mostly bridges).  Real interfaces don't have to be defined in this table.  
-- If an interface is defined as a 'static' type, then the address, netmask and 
-- gateway must be provided.
CREATE TABLE physicalInterfaceTable (
    id          INTEGER PRIMARY KEY,
    device      TEXT NOT NULL UNIQUE,
    type        TEXT NOT NULL DEFAULT 'dhcp',   -- dhcp|manual|static
    address     TEXT,
    netmask     TEXT,
    gateway     TEXT
);

--INSERT INTO physicalInterfaceTable VALUES(0,'eth0','dhcp',NULL,NULL,NULL);

CREATE TABLE virtualInterfaceTable (
    id          INTEGER PRIMARY KEY,
    interface   INTEGER,                        -- possible link to phys iface
    type        TEXT NOT NULL DEFAULT 'dhcp',   -- dhcp|manual|static
    address     TEXT,
    netmask     TEXT,
    gateway     TEXT,
    FOREIGN KEY(interface)  REFERENCES physicalInterfaceTable(id)
);

--INSERT INTO virtualInterfaceTable VALUES(0,NULL,'dhcp',NULL,NULL,NULL);
--INSERT INTO virtualInterfaceTable VALUES(1,0,'dhcp',NULL,NULL,NULL);
--INSERT INTO virtualInterfaceTable VALUES(2,NULL,'manual',NULL,NULL,NULL);

-- A view to make it easier to create the virtual interfaces
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

--INSERT INTO ifacePartitionTable VALUES(1,0,NULL,NULL,NULL);
--INSERT INTO ifacePartitionTable VALUES(2,0,NULL,NULL,NULL);
--INSERT INTO ifacePartitionTable VALUES(3,0,NULL,NULL,NULL);
--INSERT INTO ifacePartitionTable VALUES(1,1,NULL,NULL,NULL);
--INSERT INTO ifacePartitionTable VALUES(1,2,NULL,NULL,NULL);

-- A view to make it easier to extract the virtual/physical interface 
-- configuration for a partition
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

-- A logical disk can be created from an existing image, if there is no existing 
-- image that should be used to create the logical disk then a size and type 
-- must be supplied.  The size can also be specified when an image is provided 
-- as long as the size is larger than the image.  The file system type is only 
-- used when an image file is not specified.
CREATE TABLE logicalDiskTable (
    id          INTEGER PRIMARY KEY,
    format      TEXT,                   -- raw|qcow|qcow2|vhd
    path        TEXT,                   -- path to image to place in partition
    size        TEXT,                   -- #[GMK][Bb]
    fstype      TEXT                    -- ext2/3/4|vfat|etc.
);

--INSERT INTO logicalDiskTable VALUES(1,'raw',NULL,'200M','ext3');

CREATE TABLE diskPartitionTable (
    partition   INTEGER NOT NULL,
    disk        INTEGER NOT NULL,
    vdev        TEXT,                   -- xvd[a-z]|hd[a-z]|sd[a-z]
    access      TEXT DEFAULT 'rw',      -- rw|ro
    FOREIGN KEY(partition) REFERENCES partitionTable(id),
    FOREIGN KEY(disk)      REFERENCES logicalDiskTable(id),
    CONSTRAINT uc_partitionDev UNIQUE (partition, vdev)
);

--INSERT INTO diskPartitionTable VALUES(1,1,NULL,NULL);

-- A view to make it easier to extract the logical disk 
-- configuration for a partition
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

-- A view to make it easier to extract the PCI configuration for partitions
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
