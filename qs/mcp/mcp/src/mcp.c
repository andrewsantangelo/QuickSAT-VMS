
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdarg.h>
#include <time.h>
#include <signal.h>
#include <time.h>
#include <pthread.h>
#include <errno.h>
#include <syslog.h>

#include <fcntl.h>
#include <sys/stat.h>
#include <semaphore.h>
#include <unistd.h>
#include <sys/mman.h>

#include "sqlite3.h"
#include "sqlLib.h"
#include "mcp.h"
#include "mcpDb.h"
#include "mcpCond.h"
#include "mcpRules.h"
#include "mcpParam.h"
#include "mcpDomCtrl.h"
#include "mcpConfig.h"

#include "qs_vms.h"

/* tables:
 *  CREATE TABLE ruleTable (
 *      id          INTEGER PRIMARY KEY AUTOINCREMENT,
 *      name        TEXT,
 *      seconds     REAL NOT NULL DEFAULT 1.0,
 *      equation    TEXT NOT NULL DEFAULT '0',
 *      action      INTEGER,
 *      option      TEXT,
 *      FOREIGN KEY(action)     REFERENCES mcpActionEnum(id)
 *  );
 *
 *  CREATE TABLE flightLegTable (
 *      id          INTEGER PRIMARY KEY,
 *      name        TEXT
 *  );
 *
 *  CREATE TABLE opModeTable (
 *      id          INTEGER PRIMARY KEY,
 *      name        TEXT
 *  );
 *
 *  CREATE TABLE stateTable (
 *      id          INTEGER PRIMARY KEY AUTOINCREMENT,
 *      name        TEXT,
 *      schedule INTEGER NOT NULL,
 *      flightLeg   INTEGER NOT NULL,
 *      opMode      INTEGER NOT NULL,
 *      FOREIGN KEY(schedule) REFERENCES scheduleTable(id),
 *      FOREIGN KEY(flightLeg)  REFERENCES flightLegTable(id),
 *      FOREIGN KEY(opMode)     REFERENCES opModeTable(id),
 *      CONSTRAINT uc_flightLegOpMode UNIQUE (flightLeg, opMode)
 *  );
 *
 *  CREATE TABLE stateRuleLink (
 *      state       INTEGER NOT NULL,
 *      rule        INTEGER NOT NULL,
 *      FOREIGN KEY(state)      REFERENCES stateTable(id),
 *      FOREIGN KEY(rule)       REFERENCES ruleTable(id)
 *  );
 *
 *  CREATE TABLE paramTable (
 *      id          INTEGER PRIMARY KEY AUTOINCREMENT,
 *      name        TEXT,
 *      type        TEXT,
 *      port        TEXT
 *  );
 */

sqlite3         *g_mct          = NULL;
McpSharedData_t *g_mcpShm       = NULL;
sem_t           *g_mcpShmSem    = NULL;

static SqlStmt_t *m_stateCheck;     /* SELECT id FROM stateTable WHERE flightLeg == ? AND opMode == ? LIMIT 1; */
static SqlStmt_t *m_stateEntry;     /* SELECT schedule, flightLeg, opMode FROM stateTable WHERE id == ? LIMIT 1; */

/* This flag should be set at startup and not modified again. */
static bool m_vmsConnected = false;

static bool mcp_reload(void);
static bool mcp_loadMCT(char *filename, sqlite3 **db);
static bool mcp_getStateData(uint32_t id, uint32_t *sched, uint32_t *leg, uint32_t *mode);
static bool mcp_getFlightLegAndOpMode(uint32_t *flightLeg, uint32_t *opMode);
static bool mcp_setFlightLegAndOpMode(uint32_t flightLeg, uint32_t opMode);

bool mcp_start(void) {
    bool success = true;
    int32_t rc, fd;
    uint32_t numParams, shmSize, i;
    const char *cmd;
    sqlite3_stmt *stmt;
    McpConfigData_t *config;
    struct timespec vmsDelay, sleepRem = { 0, 0 };

    /* Start MCP:
     *  1. read the MCP configuration file
     *  2. connect to QS/VMS
     *  3. open MCT
     *  4. initialize other modules
     *  5. for each mcpRuleTable rule "SELECT COUNT(*) FROM ruleTable;"
     *      a. validate action
     *      b. pre-parse equation
     *      c. create timer (periodic timer using ruleTable[id].seconds)
     *  6. create prepared statements
     *  7. set state to first state in the MCT (ID 1)
     */

    config = mcpConfig_init();

    if (true == config->vmsEnabled) {
        /* Attempt to connect to the MySQL server */
        for (i = 0; (i <= config->vmsConnectRetries) && (false == m_vmsConnected); i++) {
            /* Wait the configured seconds before attempting to connect to the 
             * QS/VMS server. */
            if (0.0 < config->vmsConnectDelay) {
                syslog(LOG_INFO, "Waiting %f seconds before attempting to connect to QS/VMS server",
                       config->vmsConnectDelay);
                vmsDelay.tv_sec = (uint32_t)config->vmsConnectDelay;
                vmsDelay.tv_nsec = (uint32_t)((uint64_t)(config->vmsConnectDelay * NSEC_PER_SEC) % NSEC_PER_SEC);
                memset(&sleepRem, 0, sizeof(struct timespec));

                errno = 0;
                rc = nanosleep(&vmsDelay, &sleepRem);
                while ((-1 == rc) && (EINTR == errno)) {
                    /* If the sleep was interrupted, sleep again for the remaining 
                     * time */
                    memcpy(&vmsDelay, &sleepRem, sizeof(struct timespec));
                    errno = 0;
                    rc = nanosleep(&vmsDelay, &sleepRem);
                }
                if (-1 == rc) {
                    syslog(LOG_ERR, "%s:%d error sleeping %u/%u seconds, %u/%u remaining (%d:%s)",
                           __FUNCTION__, __LINE__, (uint32_t)vmsDelay.tv_sec, (uint32_t)vmsDelay.tv_nsec,
                           (uint32_t)sleepRem.tv_sec, (uint32_t)sleepRem.tv_nsec, errno, strerror(errno));
                }
            } /* if (0.0 < config->vmsConnectDelay) */

            syslog(LOG_INFO, "QS/VMS connection attempt %d of %d",
                   (i + 1), (config->vmsConnectRetries + 1));

            m_vmsConnected = vms_open(config->vmsAddress, config->vmsPort,
                                      config->vmsUsername, config->vmsPassword,
                                      config->vmsSSLCert, config->vmsDBName);
        } /* for (i = 0; (i <= config->vmsConnectRetries) && (false == m_vmsConnected); i++) */

        if (true == m_vmsConnected) {
            syslog(LOG_INFO, "QS/VMS connection established");
        } else {
            syslog(LOG_INFO, "QS/VMS disconnected");
        }
    } /* if (true == config->vmsEnabled) */

    rc = sqlite3_initialize();
    if (SQLITE_OK != rc) {
        success = false;
        mcp_log(LOG_ERR, "%s:%d error initializing sqlite3 (%d:%s)",
                __FUNCTION__, __LINE__, rc, sqlite3_errstr(rc));
    }

    success = mcp_loadMCT(config->mctFilename, &g_mct);

    if (true == success) {
        errno = 0;
        cmd = "SELECT id FROM stateTable WHERE flightLeg == ? AND opMode == ? LIMIT 1;";
        m_stateCheck = sqlLib_createStmt(g_mct, cmd);
        if (NULL == m_stateCheck) {
            success = false;
            mcp_log(LOG_ERR, "%s:%d error creating statement \"%s\" (%d:%s)",
                   __FUNCTION__, __LINE__, cmd, errno, strerror(errno));
        }
    }

    if (true == success) {
        errno = 0;
        cmd = "SELECT schedule, flightLeg, opMode FROM stateTable WHERE id == ? LIMIT 1;";
        m_stateEntry = sqlLib_createStmt(g_mct, cmd);
        if (NULL == m_stateEntry) {
            success = false;
            mcp_log(LOG_ERR, "%s:%d error creating statement \"%s\" (%d:%s)",
                   __FUNCTION__, __LINE__, cmd, errno, strerror(errno));
        }
    }

    if (true == success) {
        /* Determine how many parameters there are in the config (determines 
         * size of required shared memory region. */
        cmd = "SELECT COUNT(*) FROM paramTable LIMIT 1;";
        rc = sqlite3_prepare_v2(g_mct, cmd, strlen(cmd), &stmt, NULL);
        if (SQLITE_OK != rc) {
            success = false;
            mcp_log(LOG_ERR, "%s:%d error preparing statement \"%s\" (%d:%s)",
                   __FUNCTION__, __LINE__, cmd, rc, sqlite3_errstr(rc));
        } else {
            if (SQLITE_ROW != sqlite3_step(stmt)) {
                success = false;
                mcp_log(LOG_ERR, "%s:%d error executing statement \"%s\" (%d:%s)",
                       __FUNCTION__, __LINE__, cmd, rc, sqlite3_errstr(rc));
            } else {
                numParams = sqlite3_column_int(stmt, 0);
            }
        }

        (void) sqlite3_finalize(stmt);
    }

    if (true == success) {
        /* Create the MCP shared memory region. */
        errno = 0;
        fd = shm_open(MCP_SHM_NAME,
                      (O_CREAT | O_EXCL | O_RDWR),
                      (S_IRUSR | S_IWUSR | S_IRGRP | S_IWGRP | S_IROTH | S_IWOTH));

        if ((0 >= fd) && (EEXIST == errno)) {
            /* If the shared memory currently exists, open it and reset it, but log 
             * debug information. */
            mcp_log(LOG_DEBUG, "%s:%d shared memory region \"%s\" already exists, reopening it",
                   __FUNCTION__, __LINE__, MCP_SHM_NAME);

            errno = 0;
            fd = shm_open(MCP_SHM_NAME,
                          (O_RDWR | O_TRUNC),
                          (S_IRUSR | S_IWUSR | S_IRGRP | S_IWGRP | S_IROTH | S_IWOTH));
        }

        if (0 >= fd) {
            success = false;
            mcp_log(LOG_ERR, "%s:%d unable to open shared memory region \"%s\" (%d:%s)",
                   __FUNCTION__, __LINE__, MCP_SHM_NAME, errno, strerror(errno));
        }
    }

    if (true == success) {
        /* Size the opened shared memory region. */
        shmSize = sizeof(McpSharedData_t) + (numParams * sizeof(double));
        errno = 0;
        if (0 != ftruncate(fd, shmSize)) {
            success = false;
            mcp_log(LOG_ERR, "%s:%d unable to set shared memory region size to %d (%d:%s)",
                   __FUNCTION__, __LINE__, shmSize, errno, strerror(errno));
        }
    }

    if (true == success) {
        /* Get a pointer to the shared memory region. */
        errno = 0;
        g_mcpShm = (McpSharedData_t*) mmap(NULL, shmSize, (PROT_READ | PROT_WRITE), MAP_SHARED, fd, 0);
        if (NULL == g_mcpShm) {
            success = false;
            mcp_log(LOG_ERR, "%s:%d unable to map shared memory region of size %d (%d:%s)",
                   __FUNCTION__, __LINE__, shmSize, errno, strerror(errno));
        }
    }

    if (true == success) {
        /* Create an unnamed semaphore in the shared memory area. */
        errno = 0;
        g_mcpShmSem = &g_mcpShm->sem;
        if (0 != sem_init(g_mcpShmSem, 1, 1)) {
            success = false;
            mcp_log(LOG_ERR, "%s:%d unable to init semaphore (%d:%s)",
                   __FUNCTION__, __LINE__, errno, strerror(errno));
        }
    }

    if (true == success) {
        /* Initialize the shared memory data. */
        g_mcpShm->mcpState = STATE_HALTED;
        g_mcpShm->numParams = numParams;

        /* Once the shared memory region is mapped the file descriptor returned 
         * by shm_open() can be closed */
        if (0 != close(fd)) {
            success = false;
            mcp_log(LOG_ERR, "%s:%d unable to close shared memory region file descriptor (%d:%s)",
                   __FUNCTION__, __LINE__, errno, strerror(errno));
        }
    }

    /* Now that the MCP global data is initialized, init the rest of MCP. */
    if (true == success) {
        success = mcpParam_initialize();
    }

    if (true == success) {
        success = mcpRules_initialize();
    }

    if (true == success) {
        success = mcpDC_initialize();
    }

    return success;
} /* bool mcp_start(void) */

void mcp_run(void) {
    bool success = true;
    sigset_t set;
    siginfo_t sig;
    uint32_t state;
    int32_t rc;
#ifdef PROFILE
    /* When in debug mode, only run MCP for 1 minute before exiting. */
    struct timespec wait = { 60, 0 };
#endif

    /* Run MCP:
     *  1. set the sigmask so signals won't be received by any child threads
     *  2. change MCP to the initial state: 1
     *  3. handle any received signals
     *      SIGCHLD:    ignore
     *      SIGALRM:    ignore
     *      SIGPIPE:    ignore
     *      SIGUSR1:    retrieve MCP state from shared memory
     *                  (not implemented by mcpLib)
     *      SIGHUP:     reload MCT
     *      SIGTERM:    exit MCP
     *      other:      exit MCP (default unknown signal handler)
     */

    errno = 0;

    /* Have child threads ignore signals (except SIGCHLD) */
    if (0 > sigfillset(&set)) {
        success = false;
        mcp_log(LOG_ERR, "%s:%d unable to generate fillset (%d:%s)",
               __FUNCTION__, __LINE__, errno, strerror(errno));
    }
    if (0 > sigdelset(&set, SIGCHLD)) {
        success = false;
        mcp_log(LOG_ERR, "%s:%d unable to generate fillset (%d:%s)",
               __FUNCTION__, __LINE__, errno, strerror(errno));
    }
#ifdef DEBUG
    /* When DEBUG is enabled, make sure that SIGINT is also not ignored to make 
     * it easier to stop the daemon. */
    if (0 > sigdelset(&set, SIGINT)) {
        success = false;
        mcp_log(LOG_ERR, "%s:%d unable to generate fillset (%d:%s)",
               __FUNCTION__, __LINE__, errno, strerror(errno));
    }
#endif
    rc = pthread_sigmask(SIG_BLOCK, &set, NULL);
    if (0 != rc) {
        success = false;
        mcp_log(LOG_ERR, "%s:%d unable to set sigmask (%d:%s)",
               __FUNCTION__, __LINE__, rc, strerror(rc));
    }

    /* If the signal mask was properly set, start MCP processing now. */
    if (true == success) {
        /* Set the MCP state to initial state, ID 1 */
        success = mcp_setState(1);

        while (true == success) {
            errno = 0;
#ifdef PROFILE
            syslog(LOG_DEBUG, "calling sigtimedwait()");
            rc = sigtimedwait(&set, &sig, &wait);
            syslog(LOG_DEBUG, "sigtimedwait() returned %d", rc);
            if (0 >= rc) {
#else
            if (0 >= sigwaitinfo(&set, &sig)) {
#endif
                success = false;
                mcp_log(LOG_ERR, "%s:%d error waiting for signals (%d:%s)",
                       __FUNCTION__, __LINE__, errno, strerror(errno));
            } else /* ! (0 >= sigwaitinfo(&set, &sig)) */ {
                switch (sig.si_signo) {
                case SIGUSR1:
                    /* The mcp_getState() function retrieves the current state 
                     * from the database and forces an update if it is different 
                     * than the last cached state. */
                    (void)mcp_getState(&state);
                    break;
                case SIGHUP:
                    /* Reload the MCT file (but keep currently running domains 
                     * running) */
                    mcp_log(LOG_DEBUG, "received signal %d, reloading MCT", sig.si_signo);
                    (void)mcp_reload();
                    break;
                case SIGCHLD:
                    /* SIGCHLD signals have additional values that are meaninful, 
                     * print them out. */
                    mcp_log(LOG_DEBUG, "ignoring signal %d (code: %d, pid: %d, uid: %d, status: %d)",
                           sig.si_signo, sig.si_code, sig.si_pid, sig.si_uid, sig.si_status);
                    break;
                case SIGALRM:
                case SIGPIPE:
                    mcp_log(LOG_DEBUG, "ignoring signal %d (code: %d, value: %d)",
                           sig.si_signo, sig.si_code, sig.si_value.sival_int);
                    break;
                default:
                    /* Not all of the values printed will have meaning for all 
                     * received signals, but could be useful in debugging if an 
                     * unexpected type of signal is received. */
                    mcp_log(LOG_DEBUG, "received signal %d (code: %d, pid: %d, uid: %d, addr: %p)",
                           sig.si_signo, sig.si_code, sig.si_pid, sig.si_uid, sig.si_addr);

                    /* All signals which are not handled explicitly shoudl cause 
                     * MCP to stop. */
                    success = false;
                    break;
                } /* switch (sig.si_signo) */
            } /* else ! (0 >= sigwaitinfo(&set, &sig)) */
        } /* while (true == success) */

        /* If we have reached this point, stop MCP from running */
        mcp_stop();
    } /* if (false == stop) */
} /* void mcp_run(void) */

void mcp_stop(void) {
    int32_t rc;
    uint32_t shmSize;

    /* Stop MCP:
     *  1. stop all rule processing
     *  2. stop all domains
     *  3. for each mcpRuleTable rule
     *      a. delete timer
     *      b. delete equation chain
     *      c. free rule resources
     *  4. shutdown other modules
     *  5. close MCT connection
     */

    (void)mcp_setState(STATE_HALTED);

    mcpRules_shutdown();
    mcpParam_shutdown();
    mcpDC_shutdown();

    /* Close down all sqlite resources */
    sqlLib_deleteStmt(&m_stateCheck);
    sqlLib_deleteStmt(&m_stateEntry);

    rc = sqlite3_close_v2(g_mct);
    if (SQLITE_OK != rc) {
        mcp_log(LOG_ERR, "%s:%d error closing database (%d:%s)",
               __FUNCTION__, __LINE__, rc, sqlite3_errstr(rc));
    }

    rc = sqlite3_shutdown();
    if (SQLITE_OK != rc) {
        mcp_log(LOG_ERR, "%s:%d error shutting down sqlite library (%d:%s)",
               __FUNCTION__, __LINE__, rc, sqlite3_errstr(rc));
    }

    if (NULL != g_mcpShm) {
        /* destroy the unnamed sem in the shared memory area. */
        errno = 0;
        if (0 != sem_destroy(&g_mcpShm->sem)) {
            mcp_log(LOG_ERR, "%s:%d error destroying semaphore (%d:%s)",
                   __FUNCTION__, __LINE__, errno, strerror(errno));
        }

        /* Regardless of whether or not the semaphore was deleted without 
         * errors, the shared memory region should be unmapped. */
        shmSize = sizeof(McpSharedData_t) + (g_mcpShm->numParams * sizeof(double));
        errno = 0;
        if (0 != munmap(g_mcpShm, shmSize)) {
            mcp_log(LOG_ERR, "%s:%d error unmapping shared memory region (%d:%s)",
                   __FUNCTION__, __LINE__, errno, strerror(errno));
        }
    }

    /* Always try to unlink the shared memory region. */
    if (0 != shm_unlink(MCP_SHM_NAME)) {
        mcp_log(LOG_ERR, "%s:%d error unlinking shared memory region \"%s\" (%d:%s)",
               __FUNCTION__, __LINE__, MCP_SHM_NAME, errno, strerror(errno));
    }

    /* Release the resources used by the config module */
    mcpConfig_close();
} /* void mcp_stop(void) */

bool mcp_setFlightLeg(uint32_t flightLeg) {
    bool success;
    uint32_t opMode, curLeg;

    /* Get the current op mode before we attempt to lock any resources. */
    success = mcp_getFlightLegAndOpMode(&curLeg, &opMode);
    if (true == success) {
        success = mcp_setFlightLegAndOpMode(flightLeg, opMode);
        if (true != success) {
            mcp_log(LOG_ERR, "%s:%d error changing from flight leg %d to %d",
                   __FUNCTION__, __LINE__, curLeg, flightLeg);
        }
    } else {
        mcp_log(LOG_ERR, "%s:%d error retrieving current flight leg and op mode",
               __FUNCTION__, __LINE__);
    }

    return success;
} /* bool mcp_setFlightLeg(uint32_t flightLeg) */

bool mcp_setOpMode(uint32_t opMode) {
    bool success;
    uint32_t flightLeg, curMode;

    /* Get the current op mode before we attempt to lock any resources. */
    success = mcp_getFlightLegAndOpMode(&flightLeg, &curMode);
    if (true == success) {
        success = mcp_setFlightLegAndOpMode(flightLeg, opMode);
        if (true != success) {
            mcp_log(LOG_ERR, "%s:%d error changing from op mode %d to %d",
                   __FUNCTION__, __LINE__, curMode, opMode);
        }
    } else {
        mcp_log(LOG_ERR, "%s:%d error retrieving current flight leg and op mode",
               __FUNCTION__, __LINE__);
    }

    return success;
} /* bool mcp_setOpMode(uint32_t opMode) */

bool mcp_getFlightLeg(uint32_t *flightLeg) {
    return mcp_getFlightLegAndOpMode(flightLeg, NULL);
} /* bool mcp_getFlightLeg(uint32_t *flightLeg) */

bool mcp_getOpMode(uint32_t *opMode) {
    return mcp_getFlightLegAndOpMode(NULL, opMode);
} /* bool mcp_getOpMode(uint32_t *opMode) */

bool mcp_setState(uint32_t state) {
    uint32_t curState, leg = 0, mode = 0, sched = 0;
    bool success = true;

    /* Change to a new state:
     *  1. Verify new state is valid
     *  2. for each active mcpRuleTable rule
     *      a. stop timer
     *  3. change state in published variable (broadcast port or xenstore 
     *     @ /tool/state)
     *  4. set schedule
     *      a. Check current schedule
     *      b. If schedule for this state is different, change it
     *  5. for each active mcpRuleTable rule
     *      a. start timer
     */

    mcp_log(LOG_DEBUG, "changing MCP to state %d", state);

    /* Ensure that the new state is valid */
    if ((STATE_HALTED == state) || (true == mcp_getStateData(state, &sched, &leg, &mode))) {
        errno = 0;
        if (0 == sem_wait(g_mcpShmSem)) {
            /* Get the current state */
            curState = g_mcpShm->mcpState;

            /* If the current state is not invalid, get a list of rules which 
             * are active under the current state, but not the new state. */
            if (STATE_HALTED != curState) {
                success = mcpRules_stop(curState, state);
            }

            /* Change to new state */
            g_mcpShm->mcpState = state;

            /* Set flightLeg & opMode based on current state. */
            g_mcpShm->flightLeg = leg;
            g_mcpShm->opMode = mode;

            /* If the new state is not invalid, and was set successfully, get 
             * a list of rules which are active under the new state, but not the 
             * current state. */
            if (STATE_HALTED != state) {
                success = mcpRules_start(state, curState);
            }

            /* Start the new schedule. */
            success = mcpDC_setSchedule(sched);

            errno = 0;
            if (0 != sem_post(g_mcpShmSem)) {
                success = false;
                mcp_log(LOG_ERR, "%s:%d sem_post() error (%d:%s)",
                       __FUNCTION__, __LINE__, errno, strerror(errno));
            }
        } else {
            success = false;
            mcp_log(LOG_ERR, "%s:%d sem_wait() error (%d:%s)",
                   __FUNCTION__, __LINE__, errno, strerror(errno));
        }
    } else {
        success = false;
        mcp_log(LOG_ERR, "%s:%d Invalid state %d",
               __FUNCTION__, __LINE__, state);
    }

    return success;
} /* bool mcp_setState(uint32_t state) */

bool mcp_getState(uint32_t *state) {
    bool success = true;

    errno = 0;
    if (0 == sem_wait(g_mcpShmSem)) {
        *state = g_mcpShm->mcpState;

        errno = 0;
        if (0 != sem_post(g_mcpShmSem)) {
            success = false;
            mcp_log(LOG_ERR, "%s:%d sem_post() error (%d:%s)",
                   __FUNCTION__, __LINE__, errno, strerror(errno));
        }
    } else {
        success = false;
        mcp_log(LOG_ERR, "%s:%d sem_wait() error (%d:%s)",
                __FUNCTION__, __LINE__, errno, strerror(errno));
    }

    return success;
} /* bool mcp_getState(uint32_t *state) */

bool mcp_vmsConnected(void) {
    return m_vmsConnected;
}

void mcp_log(uint32_t level, const char *format, ...) {
    va_list args;

#ifdef DEBUG
    /* for debug builds, it's easier to see all logs in the syslog */
    va_start(args, format);
    vsyslog(level, format, args);
    va_end(args);
#else
    /* If QS/VMS is not connected send the message to the syslog. */
    if (false == m_vmsConnected) {
	va_start(args, format);
        vsyslog(level, format, args);
	va_end(args);
    } else {
        char *message = NULL;

        errno = 0;
	va_start(args, format);
	vasprintf(&message, format, args);
	va_end(args);

        /* If QS/VMS is connected, log all messages */
        if (NULL != message) {
            vms_status_update(message);

            /* If the log level is higher than the cutoff, send it to the syslog 
             * as well. */
            if (LOG_WARNING <= level) {
                syslog(level, "%s", message);
            }

            free(message);
        } else {
            syslog(LOG_ERR, "%s:%d error allocating error message (%d:%s)",
                   __FUNCTION__, __LINE__, errno, strerror(errno));
	    va_start(args, format);
	    vsyslog(level, format, args);
	    va_end(args);
	}
    }
#endif
} /* void mcp_log(uint32_t level, const char *format, ...) */

static bool mcp_reload(void) {
    bool success = true;
    uint32_t curState;
    McpConfigData_t *config;

    /* Reload MCT:
     *  1. Save current state (so it can be restored later)
     *  2. Clean up all rules, new rules must be re-processed later so shutdown 
     *     the rules module
     *  3. Set the current state to "HALTED" (this won't effect domain control's 
     *     internal state because it tracks the domain's separately)
     *  4. Reload MCT
     *  5. Re-initialize rule processing from the new MCT
     *  6. Have Domain Control look at domain list from new MCT, delete any 
     *     unneeded domains and create any new domains
     *  7. Set the new MCP state to be the saved state (this assumes that the op 
     *     modes/flight legs have not changed)
     *
     *  TODO: have mcp_reload() handle changed op mode/flight leg/mcp state 
     *        configuration changes
     *  TODO: the MCP shared memory region may need to be increased in size to 
     *        deal with new parameters.  Changing the shared memory region on 
     *        the fly is not yet implemented, so the new MCT can't have more 
     *        parameters than the old one. */

    errno = 0;
    if (0 == sem_wait(g_mcpShmSem)) {
        /* Save the current state */
        curState = g_mcpShm->mcpState;

        /* The currently executing rules need to be stopped, but it is possible 
         * that there may be new rules which need to be initialized, so the rule 
         * processing will be shutdown and then re-initialized after the new MCT 
         * is read. */
        mcpRules_shutdown();

        /* Set the current module state to "halted" so that later when the 
         * mcp_setState() function is called the correct actions will be 
         * performed. */
        g_mcpShm->mcpState = STATE_HALTED;

        /* Reload MCT from the file */
        config = mcpConfig_get();
        success = mcp_loadMCT(config->mctFilename, &g_mct);

        /* Re-initialize rule processing */
        if (true == success) {
            success = mcpRules_initialize();
        }

        /* Have domain control reload MCT, create and destroy domains as 
         * necessary. */
        if (true == success) {
            success = mcpDC_reloadConfig();
        }

        errno = 0;
        if (0 != sem_post(g_mcpShmSem)) {
            success = false;
            mcp_log(LOG_ERR, "%s:%d sem_post() error (%d:%s)",
                    __FUNCTION__, __LINE__, errno, strerror(errno));
        }

        /* Start MCP operating again in the same state that it was before
         * (after the semaphore has been released). */
        if (true == success) {
            success = mcp_setState(curState);
        }
    } else {
        success = false;
        mcp_log(LOG_ERR, "%s:%d sem_wait() error (%d:%s)",
                __FUNCTION__, __LINE__, errno, strerror(errno));
    }

    return success;
} /* static bool mcp_reload(void) */

static bool mcp_loadMCT(char *filename, sqlite3 **db) {
    bool success = true;
    int32_t rc;
    sqlite3 *fileMCT = NULL;
    sqlite3_backup *backupMCT = NULL;

    /* Open the MCT as an in-memory database and then restore the in-memory MCT 
     * from the file MCT as if it was a backup. only open this DB if it is not 
     * already opened. */
    if (NULL == *db) {
        rc = sqlite3_open_v2(":memory:", db, SQLITE_OPEN_READWRITE, NULL);
        if (SQLITE_OK != rc) {
            success = false;
            mcp_log(LOG_ERR, "%s:%d can't open in-memory DB (%d:%s)",
                   __FUNCTION__, __LINE__, rc, sqlite3_errstr(rc));
        }
    }

    if (true == success) {
        rc = sqlite3_open_v2(filename, &fileMCT, SQLITE_OPEN_READWRITE, NULL);
        if (SQLITE_OK != rc) {
            success = false;
            mcp_log(LOG_ERR, "%s:%d can't open \"%s\" (%d:%s)",
                   __FUNCTION__, __LINE__, filename, rc, sqlite3_errstr(rc));
        }
    }

    if (true == success) {
        backupMCT = sqlite3_backup_init(*db, "main", fileMCT, "main");
        if (NULL == backupMCT) {
            success = false;
            mcp_log(LOG_ERR, "%s:%d unable to initiate backup from \"%s\" (%d:%s)",
                   __FUNCTION__, __LINE__, filename, sqlite3_errcode(*db), sqlite3_errmsg(*db));
        }
    }

    if (true == success) {
        rc = sqlite3_backup_step(backupMCT, -1);
        if (SQLITE_DONE != rc) {
            success = false;
            mcp_log(LOG_ERR, "%s:%d unable to start backup from \"%s\" (%d:%s)",
                   __FUNCTION__, __LINE__, filename, rc, sqlite3_errstr(rc));
        }
    }

    if (true == success) {
        rc = sqlite3_backup_finish(backupMCT);
        if (SQLITE_OK != rc) {
            success = false;
            mcp_log(LOG_ERR, "%s:%d unable to complete backup from \"%s\" (%d:%s)",
                   __FUNCTION__, __LINE__, filename, rc, sqlite3_errstr(rc));
        }
    }

    /* If the file-based MCT was ever opened, ensure it is closed */
    if (NULL == fileMCT) {
        rc = sqlite3_close_v2(fileMCT);
        if (SQLITE_OK != rc) {
            success = false;
            mcp_log(LOG_ERR, "%s:%d unable to close \"%s\" (%d:%s)",
                   __FUNCTION__, __LINE__, filename, rc, sqlite3_errstr(rc));
        }
    }

    return success;
} /* static bool mcp_loadMCT(char *filename, sqlite3 **db) */

static bool mcp_getStateData(uint32_t id, uint32_t *sched, uint32_t *leg, uint32_t *mode) {
    bool success = true;
    int32_t rc;

    rc = pthread_mutex_lock(&m_stateEntry->lock);
    if (0 == rc) {
        rc = sqlite3_reset(m_stateEntry->stmt);
        if (SQLITE_OK != rc) {
            success = false;
            mcp_log(LOG_ERR, "%s:%d error resetting statement (%d:%s)",
                    __FUNCTION__, __LINE__, rc, sqlite3_errstr(rc));
        }

        if (true == success) {
            rc = sqlite3_bind_int(m_stateEntry->stmt, 1, id);
            if (SQLITE_OK != rc) {
                success = false;
                mcp_log(LOG_ERR, "%s:%d error binding id %d to param %d (%d:%s)",
                        __FUNCTION__, __LINE__, id, 1, rc, sqlite3_errstr(rc));
            }
        }

        if (true == success) {
            rc = sqlite3_step(m_stateEntry->stmt);
            if (SQLITE_DONE == rc) {
                /* a return code of SQLITE_DONE means no rows were found, so 
                 * this state is invalid. */
                success = false;
            } else if (SQLITE_ROW != rc) {
                success = false;
                mcp_log(LOG_ERR, "%s:%d error executing prepared statement (%d:%s)",
                        __FUNCTION__, __LINE__, rc, sqlite3_errstr(rc));
            } else {
                *sched = sqlite3_column_int(m_stateEntry->stmt, 0);
                *leg = sqlite3_column_int(m_stateEntry->stmt, 1);
                *mode = sqlite3_column_int(m_stateEntry->stmt, 2);
            }
        }

        rc = pthread_mutex_unlock(&m_stateEntry->lock);
        if (0 != rc) {
            mcp_log(LOG_ERR, "%s:%d error unlocking mutex (%d:%s)",
                    __FUNCTION__, __LINE__, rc, strerror(rc));
        }
    } else /* !(0 == rc) */ {
        success = false;
        mcp_log(LOG_ERR, "%s:%d error locking mutex (%d:%s)",
                __FUNCTION__, __LINE__, rc, strerror(rc));
    }

    return success;
} /* static bool mcp_getStateData(uint32_t id, uint32_t *sched, uint32_t *leg, uint32_t *mode) */

static bool mcp_getFlightLegAndOpMode(uint32_t *flightLeg, uint32_t *opMode) {
    bool success = true;

    if (0 == sem_wait(g_mcpShmSem)) {
        if (NULL != flightLeg) {
            *flightLeg = g_mcpShm->flightLeg;
        }
        if (NULL != opMode) {
            *opMode = g_mcpShm->opMode;
        }

        errno = 0;
        if (0 != sem_post(g_mcpShmSem)) {
            success = false;
            mcp_log(LOG_ERR, "%s:%d sem_post() error (%d:%s)",
                   __FUNCTION__, __LINE__, errno, strerror(errno));
        }
    } else {
        success = false;
        mcp_log(LOG_ERR, "%s:%d sem_wait() error (%d:%s)",
               __FUNCTION__, __LINE__, errno, strerror(errno));
    }

    return success;
} /* static bool mcp_getFlightLegAndOpMode(uint32_t *flightLeg, uint32_t *opMode) */

static bool mcp_setFlightLegAndOpMode(uint32_t flightLeg, uint32_t opMode) {
    bool success = true;
    uint32_t state;
    int32_t rc;

    rc = pthread_mutex_lock(&m_stateCheck->lock);
    if (0 == rc) {
        rc = sqlite3_reset(m_stateCheck->stmt);
        if (SQLITE_OK != rc) {
            success = false;
            mcp_log(LOG_ERR, "%s:%d error resetting statement (%d:%s)",
                   __FUNCTION__, __LINE__, rc, sqlite3_errstr(rc));
        }

        /* To change the flight leg, see if the new flightLeg/opMode combination 
         * is a valid state or not.  If not return failure.  If it would be 
         * change to the desired state.
         *  1st param == flightLeg
         *  2nd param == opMode */

        if (true == success) {
            rc = sqlite3_bind_int(m_stateCheck->stmt, 1, flightLeg);
            if (SQLITE_OK != rc) {
                success = false;
                mcp_log(LOG_ERR, "%s:%d error binding flightLeg %d to param %d (%d:%s)",
                       __FUNCTION__, __LINE__, flightLeg, 1, rc, sqlite3_errstr(rc));
            }
        }

        if (true == success) {
            rc = sqlite3_bind_int(m_stateCheck->stmt, 2, opMode);
            if (SQLITE_OK != rc) {
                success = false;
                mcp_log(LOG_ERR, "%s:%d error binding opMode %d to param %d (%d:%s)",
                       __FUNCTION__, __LINE__, opMode, 1, rc, sqlite3_errstr(rc));
            }
        }

        if (true == success) {
            rc = sqlite3_step(m_stateCheck->stmt);
            if (SQLITE_DONE == rc) {
                /* a return code of SQLITE_DONE means no rows were found, so 
                 * this flight leg is invalid. */
                success = false;
            } else if (SQLITE_ROW != rc) {
                success = false;
                mcp_log(LOG_ERR, "%s:%d error executing prepared statement (%d:%s)",
                       __FUNCTION__, __LINE__, rc, sqlite3_errstr(rc));
            } else {
                state = sqlite3_column_int(m_stateCheck->stmt, 0);
            }
        }

        rc = pthread_mutex_unlock(&m_stateCheck->lock);
        if (0 != rc) {
            mcp_log(LOG_ERR, "%s:%d error unlocking mutex (%d:%s)",
                   __FUNCTION__, __LINE__, rc, strerror(rc));
        }
    } else /* !(0 == rc) */ {
        success = false;
        mcp_log(LOG_ERR, "%s:%d error locking mutex (%d:%s)",
               __FUNCTION__, __LINE__, rc, strerror(rc));
    }

    /* If success is still true it means that a valid state was retrieved that 
     * matches the desired flight leg and op mode. */
    if (true == success) {
        success = mcp_setState(state);
        if (true != success) {
            mcp_log(LOG_ERR, "%s:%d unable to move to state %d (%d/%d)",
                   __FUNCTION__, __LINE__, state, flightLeg, opMode);
        }
    }

    return success;
} /* static bool mcp_setFlightLegAndOpMode(uint32_t flightLeg, uint32_t opMode) */

