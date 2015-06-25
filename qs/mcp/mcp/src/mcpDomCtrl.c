
#include <stdint.h>
#include <stdbool.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
#include <pthread.h>
#include <semaphore.h>
#include <unistd.h>
#include <sys/wait.h>

#include <xen/xen.h>
#include "xen_interface.h"

#include "sqlite3.h"
#include "sqlLib.h"
#include "mcp.h"
#include "mcpDb.h"
#include "mcpDomCtrl.h"
#include "mcpConfig.h"

#include "qs_vms.h"

/* tables:
 *  CREATE TABLE scheduleTable (
 *      id          INTEGER PRIMARY KEY,
 *      name        TEXT NOT NULL UNIQUE,
 *      timeslice   INTEGER
 *  );
 *
 *  CREATE TABLE partitionTable (
 *      id          INTEGER PRIMARY KEY,
 *      name        VARCHAR(16) NOT NULL UNIQUE
 *  );
 *
 *  CREATE TABLE schedPartitionAllocTable (
 *      schedule    INTEGER NOT NULL,
 *      partition   INTEGER NOT NULL,
 *      cputime     REAL NOT NULL,
 *      FOREIGN KEY(schedule)   REFERENCES scheduleTable(id),
 *      FOREIGN KEY(partition)  REFERENCES partitionTable(id),
 *      CONSTRAINT uc_schedPartition UNIQUE (schedule, partition)
 *  );
 */

typedef struct McpDomInfo_s {
    uint32_t        domState;
    char            *name;
    domid_t         id;
    XenDomState_t   xenState;
} McpDomInfo_t;

static SqlStmt_t *m_maxDoms;        /* SELECT MAX(id) FROM partitionTable LIMIT 1; */
static SqlStmt_t *m_domList;        /* SELECT id, name FROM partitionTable; */
static SqlStmt_t *m_schedInfo;      /* SELECT timeslice FROM scheduleTable WHERE id == ? LIMIT 1; */
static SqlStmt_t *m_schedDomInfo;   /* SELECT id, weight, cpucap FROM schedPartitionAllocView WHERE schedule == ?; */

static pthread_mutex_t  m_domInfoLock  = PTHREAD_RECURSIVE_MUTEX_INITIALIZER_NP;

static uint32_t         m_sched         = 0;
static uint32_t         m_numDoms       = 0;
static McpDomInfo_t     *m_domInfo      = NULL;

static bool mcpDC_startDomSched(uint32_t sched);
static void mcpDC_shutdownDoms(void);
static char* mcpDC_getDomName(uint32_t id);

bool mcpDC_initialize(void) {
    bool success = true;
    int32_t rc;
    const char *cmd;

    /* Open xen interface */
    success = xen_open();

    if (true == success) {
        errno = 0;
        cmd = "SELECT MAX(id) FROM partitionTable LIMIT 1;";
        m_maxDoms = sqlLib_createStmt(g_mct, cmd);
        if (NULL == m_maxDoms) {
            success = false;
            mcp_log(LOG_ERR, "%s:%d error creating statement \"%s\" (%d:%s)",
                    __FUNCTION__, __LINE__, cmd, errno, strerror(errno));
        }
    }

    if (true == success) {
        /* Determine how many domains there are in the config (determines size 
         * of required shared memory region). */
        rc = sqlite3_reset(m_maxDoms->stmt);
        if (SQLITE_OK != rc) {
            success = false;
            mcp_log(LOG_ERR, "%s:%d error resetting statement (%d:%s)",
                    __FUNCTION__, __LINE__, rc, sqlite3_errstr(rc));
        } else {
            if (SQLITE_ROW != sqlite3_step(m_maxDoms->stmt)) {
                success = false;
                mcp_log(LOG_ERR, "%s:%d error executing statement (%d:%s)",
                        __FUNCTION__, __LINE__, rc, sqlite3_errstr(rc));
            } else {
                m_numDoms = (uint32_t)sqlite3_column_int(m_maxDoms->stmt, 0);
            }
        }
    }

    if (true == success) {
        errno = 0;
        cmd = "SELECT id, name FROM partitionTable;";
        m_domList = sqlLib_createStmt(g_mct, cmd);
        if (NULL == m_domList) {
            success = false;
            mcp_log(LOG_ERR, "%s:%d error creating statement \"%s\" (%d:%s)",
                    __FUNCTION__, __LINE__, cmd, errno, strerror(errno));
        }
    }

    if (true == success) {
        /* Allocate the domain state storage area. */
        errno = 0;
        m_domInfo = (McpDomInfo_t*)calloc(m_numDoms, sizeof(McpDomInfo_t));
        if (NULL == m_domInfo) {
            success = false;
            mcp_log(LOG_ERR, "%s:%d error allocating domain info (%p) storage (%d:%s)",
                    __FUNCTION__, __LINE__, m_domInfo, errno, strerror(errno));
        } else /* ! (NULL == m_domInfo) */ {
            /* Set each domain to the DOM_STATE_DELETE state and initialize the 
             * dom ID and Xen state values. calloc() sets every byte to 0, but 
             * set the name to NULL in case the allocation method changes in the 
             * future. */
            for (uint32_t id = 1; id <= m_numDoms; id++) {
                m_domInfo[id-1].domState    = DOM_STATE_DELETE;
                m_domInfo[id-1].name        = NULL;
                m_domInfo[id-1].id          = DOMID_INVALID; /* defined by xen */
                m_domInfo[id-1].xenState    = XEN_DOM_UNKNOWN;
            }

            /* Determine which domains are valid. */
            rc = sqlite3_reset(m_domList->stmt);
            if (SQLITE_OK == rc) {
                uint32_t id;

                rc = SQLITE_ROW;
                while ((true == success) && (SQLITE_ROW == rc)) {
                    rc = sqlite3_step(m_domList->stmt);
                    if (SQLITE_ROW == rc) {
                        id = sqlite3_column_int(m_domList->stmt, 0);
                        m_domInfo[id-1].domState = DOM_STATE_INIT;
                        m_domInfo[id-1].name = strdup((char*)sqlite3_column_text(m_domList->stmt, 1));
                    } else if (SQLITE_DONE != rc) {
                        success = false;
                        mcp_log(LOG_ERR, "%s:%d error executing prepared statement (%d:%s)",
                                __FUNCTION__, __LINE__, rc, sqlite3_errstr(rc));
                    }
                } /* while ((true == success) && (SQLITE_ROW == rc)) */
            } else { /* ! (SQLITE_OK == rc) */
                success = false;
                mcp_log(LOG_ERR, "%s:%d error resetting statement (%d:%s)",
                        __FUNCTION__, __LINE__, rc, sqlite3_errstr(rc));
            }
        } /* else ! (NULL == m_domInfo) */
    }

    if (true == success) {
        errno = 0;
        cmd = "SELECT timeslice FROM scheduleTable WHERE id == ? LIMIT 1;";
        m_schedInfo = sqlLib_createStmt(g_mct, cmd);
        if (NULL == m_schedInfo) {
            success = false;
            mcp_log(LOG_ERR, "%s:%d error creating statement \"%s\" (%d:%s)",
                    __FUNCTION__, __LINE__, cmd, errno, strerror(errno));
        }
    }

    if (true == success) {
        errno = 0;
        cmd = "SELECT id, weight, cpucap FROM schedPartitionAllocView WHERE schedule == ?;";
        m_schedDomInfo = sqlLib_createStmt(g_mct, cmd);
        if (NULL == m_schedDomInfo) {
            success = false;
            mcp_log(LOG_ERR, "%s:%d error creating statement \"%s\" (%d:%s)",
                    __FUNCTION__, __LINE__, cmd, errno, strerror(errno));
        }
    }

    /* Create all valid domains (move them from INIT to OFF). */
    for (uint32_t id = 1; (id <= m_numDoms) && (true == success); id++) {
        if (DOM_STATE_DELETE != m_domInfo[id-1].domState) {
            success = mcpDC_setDomState(id, DOM_STATE_OFF);
        }
    }

    return success;
} /* bool mcpDC_initialize(void) */

void mcpDC_shutdown(void) {
    int32_t rc;

    /* lock (if possible) and destroy the mutex. */
    rc = pthread_mutex_trylock(&m_domInfoLock);
    if (0 != rc) {
        mcp_log(LOG_ERR, "%s:%d error locking mutex (%d:%s)",
                __FUNCTION__, __LINE__, rc, strerror(rc));
    }

    rc = pthread_mutex_destroy(&m_domInfoLock);
    if (0 != rc) {
        mcp_log(LOG_ERR, "%s:%d error destroying mutex (%d:%s)",
                __FUNCTION__, __LINE__, rc, strerror(rc));
    }

    mcpDC_shutdownDoms();

    /* clear the domain names from the info table. */
    for (uint32_t i = 0; i < m_numDoms; i++) {
        if (NULL != m_domInfo[i].name) {
            free(m_domInfo[i].name);
        }
    }
    free(m_domInfo);
    m_domInfo = NULL;

    m_numDoms = 0;
    m_sched = 0;

    sqlLib_deleteStmt(&m_maxDoms);
    sqlLib_deleteStmt(&m_domList);
    sqlLib_deleteStmt(&m_schedInfo);
    sqlLib_deleteStmt(&m_schedDomInfo);

    /* Finally, close the xen interface */
    xen_close();
} /* void mcpDC_shutdown(void) */

bool mcpDC_reloadConfig(void) {
    bool success = true;
    uint32_t newMaxDom, oldMaxDom;
    uint32_t *newDomStates;
    int32_t rc;

    rc = pthread_mutex_lock(&m_domInfoLock);
    if (0 == rc) {
        /* Determine how many domains there are in the config (determines size 
         * of required shared memory region. */
        rc = sqlite3_reset(m_maxDoms->stmt);
        if (SQLITE_OK == rc) {
            if (SQLITE_ROW == sqlite3_step(m_maxDoms->stmt)) {
                newMaxDom = (uint32_t)sqlite3_column_int(m_maxDoms->stmt, 0);
            } else {
                success = false;
                mcp_log(LOG_ERR, "%s:%d error executing statement (%d:%s)",
                        __FUNCTION__, __LINE__, rc, sqlite3_errstr(rc));
            }
        } else { /* ! (SQLITE_OK == rc) */
            success = false;
            mcp_log(LOG_ERR, "%s:%d error resetting statement (%d:%s)",
                    __FUNCTION__, __LINE__, rc, sqlite3_errstr(rc));
        }

        /* update the module variables */
        if (true == success) {
            oldMaxDom = m_numDoms;
#ifdef DEBUG
            syslog(LOG_DEBUG, "MCT reload: old doms = %u, new doms = %u", oldMaxDom, newMaxDom);
#endif
            if (newMaxDom > m_numDoms) {
                m_numDoms = newMaxDom;
                /* If there are more domains than there used to be, increase the 
                 * size of the domain name table. */
                errno = 0;
                m_domInfo = realloc(m_domInfo, m_numDoms * sizeof(McpDomInfo_t));
                if (NULL == m_domInfo) {
                    success = false;
                    mcp_log(LOG_ERR, "%s:%d error reallocating domain info array (%d:%s)",
                            __FUNCTION__, __LINE__, errno, strerror(errno));
                }

                /* set the new domain names as NULL */
                for (uint32_t i = oldMaxDom; i < m_numDoms; i++) {
                    m_domInfo[i].name = NULL;
                }
            } /* if (newMaxDom > m_numDoms) */
        }

        if (true == success) {
            /* allocate the new domain state array with the largest of old/new 
             * domain numbers. */
            errno = 0;
            newDomStates = calloc(m_numDoms, sizeof(uint32_t));
            if (NULL == newDomStates) {
                success = false;
                mcp_log(LOG_ERR, "%s:%d error allocating domain state array (%d:%s)",
                        __FUNCTION__, __LINE__, errno, strerror(errno));
            }
        }

        if (true == success) {
            /* add/delete domains procedure:
             *  1. Mark all domains in the new list as DOM_STATE_DELETE
             *  2. Loop through list of doms in MCT and mark all valid doms as 
             *     DOM_STATE_INIT
             *  3. loop through every dom in the state table (after releasing 
             *     the mutex):
             *      - if the new state is DELETE, use the new state
             *      - if the new state is INIT, use the old state (if valid)
             *      - otherwise leave new state as INIT */
            for (uint32_t i = 0; i < m_numDoms; i++) {
                newDomStates[i] = DOM_STATE_DELETE;
            }

            rc = sqlite3_reset(m_domList->stmt);
            if (SQLITE_OK == rc) {
                uint32_t id;

                rc = SQLITE_ROW;
                while ((true == success) && (SQLITE_ROW == rc)) {
                    rc = sqlite3_step(m_domList->stmt);
                    if (SQLITE_ROW == rc) {
                        id = sqlite3_column_int(m_domList->stmt, 0);
                        newDomStates[id-1] = DOM_STATE_INIT;
                        /* if a domain name is NULL, but is now valid, save its 
                         * name */
                        if (NULL == m_domInfo[id-1].name) {
                            m_domInfo[id-1].name = strdup((char*)sqlite3_column_text(m_domList->stmt, 1));
                        }
                    } else if (SQLITE_DONE != rc) {
                        success = false;
                        mcp_log(LOG_ERR, "%s:%d error executing prepared statement (%d:%s)",
                                __FUNCTION__, __LINE__, rc, sqlite3_errstr(rc));
                    }
                } /* while ((true == success) && (SQLITE_ROW == rc)) */
            } else { /* ! (SQLITE_OK == rc) */
                success = false;
                mcp_log(LOG_ERR, "%s:%d error resetting statement (%d:%s)",
                        __FUNCTION__, __LINE__, rc, sqlite3_errstr(rc));
            }
        } /* add/delete domains */

        if (true == success) {
            /* Now determine the state for every domain:
             *  - if new state is DELETE, set as DELETE
             *  - if new state is INIT, and old state is not DELETE, use old 
             *    state
             *  - if ID is beyond range of new states, set as DELETE
             *  - if ID is beyond range of old states, set to value of new state
             *
             * These can be summarized as:
             *  - if ID is valid for new domains, and new state is INIT, use old 
             *    state (if ID is valid for old domains, and state is not 
             *    DELETE)
             *  - if ID is not valid for new domains, set state to DELETE (no 
             *    action is necessary since new dom states are all initialized 
             *    to DELETE)
             *  - otherwise use new state (DELETE or INIT; no action is 
             *    necessary since the new state is already set) */
            for (uint32_t i = 0; i < m_numDoms; i++) {
                if ((i < newMaxDom) && (DOM_STATE_INIT == newDomStates[i])
                    && (i < oldMaxDom) && (DOM_STATE_DELETE != m_domInfo[i].domState)) {
                        newDomStates[i] = m_domInfo[i].domState;
                }
#ifdef DEBUG
                syslog(LOG_DEBUG, "MCT reload: dom %u state = %u", i+1, newDomStates[i]);
#endif
            }

            /* delete domains which must be deleted (if the domain is already 
             * deleted no action will be taken), and create new domains (set the 
             * domain state to DOM_STATE_INIT and then set the state to 
             * DOM_STATE_OFF). */
            for (uint32_t i = 0; (i < oldMaxDom) && (true == success); i++) {
                if (DOM_STATE_DELETE == newDomStates[i]) {
                    success = mcpDC_setDomState(i+1, DOM_STATE_DELETE);
                } else if (DOM_STATE_INIT == newDomStates[i]) {
                    m_domInfo[i].domState = DOM_STATE_INIT;
                    success = mcpDC_setDomState(i+1, DOM_STATE_OFF);
                }
                if (true != success) {
                    mcp_log(LOG_ERR, "%s:%d error changing domain %u state from %u to %u",
                            __FUNCTION__, __LINE__,
                            i+1, m_domInfo[i].domState, newDomStates[i]);
                }
            }
        } /* determine state for every domain (new and old) */

        if (NULL != newDomStates) {
            /* Free the temporary new domain state array. */
            free(newDomStates);
        }

        /* Lastly, set the schedule to 0 to cause the mcp_setSchedule()
         * function that will be called later to properly start new domains */
        m_sched = 0;

        rc = pthread_mutex_unlock(&m_domInfoLock);
        if (0 != rc) {
            mcp_log(LOG_ERR, "%s:%d error unlocking mutex (%d:%s)",
                    __FUNCTION__, __LINE__, rc, strerror(rc));
        }
    } else {
        success = false;
        mcp_log(LOG_ERR, "%s:%d error locking mutex (%d:%s)",
                __FUNCTION__, __LINE__, rc, strerror(rc));
    }

    return success;
} /* bool mcpDC_reloadConfig(void) */

bool mcpDC_setDomState(uint32_t id, McpDomState_t state) {
    bool success = true;
    int32_t rc;
    char *arg = NULL, *domName = NULL;
    pid_t pid;

    rc = pthread_mutex_lock(&m_domInfoLock);
    if (0 == rc) {
        mcp_log(LOG_INFO, "MCP changing dom %d state %d -> %d", id, m_domInfo[id-1].domState, state);

        /* First, see if any action is necessary */
        if (state != m_domInfo[id-1].domState) {
            /* Ensure that the domain ID is valid */
            domName = mcpDC_getDomName(id);
            if (NULL != domName) {
                /* Only some state transitions are valid. */
                if        ((DOM_STATE_INIT   == m_domInfo[id-1].domState) && (DOM_STATE_OFF      == state)) {
                    /* New domains should be created paused. */
                    m_domInfo[id-1].domState = state;
                    (void)asprintf(&arg, "%s/mcp%s.cfg", mcpConfig_get()->xenDir, domName);
                    errno = 0;
                    pid = fork();
                    if (0 == pid) {
                        errno = 0;
                        /* This will only return if the application is unable
                         * to be spawned */
                        if (0 != execl(mcpConfig_get()->xlBinLocation, "xl", "create", "-qp", arg, NULL)) {
                            mcp_log(LOG_ERR, "%s:%d error executing system cmd \"xl create -qp %s\" (%d:%s)",
                                    __FUNCTION__, __LINE__, arg, errno, strerror(errno));
                            /* Exit the spawned process */
                            exit(-errno);
                        }
                    } else if (-1 == pid) {
                        mcp_log(LOG_ERR, "%s:%d error creating child process to create dom %s (%d:%s)",
                                __FUNCTION__, __LINE__, domName, errno, strerror(errno));
                    } else {
                        /* Wait until the spawned process exits so we can check
                         * if command was executed successfully. */
                        if (-1 == waitpid(pid, &rc, 0)) {
                            success = false;
                            mcp_log(LOG_ERR, "%s:%d error waiting for child process %d (%d:%s)",
                                   __FUNCTION__, __LINE__, pid, errno, strerror(errno));
                        }
                        if (0 != WEXITSTATUS(rc)) {
                            success = false;
                            mcp_log(LOG_ERR, "%s:%d system cmd failed \"xl create -qp %s\" (%d)",
                                    __FUNCTION__, __LINE__, arg, WEXITSTATUS(rc));
                        }

                        /* Mark the VM as started, if the start fails the status
                         * will be updated when the domain status is checked.
                         * Set the Xen state accordingly for the domain that was
                         * just created.  But don't let VMS communication issues 
                         * shutdown the entire MCP. */
                        (void)vms_set_vm_state(m_domInfo[id-1].name, QS_VMS_VM_STARTED);
                        m_domInfo[id-1].xenState = XEN_DOM_RUNNING;
                    }
                } else if ((DOM_STATE_DELETE != m_domInfo[id-1].domState) && (DOM_STATE_DELETE   == state)) {
                    /* Destroy the domain if it exists */
                    m_domInfo[id-1].domState = state;
                    pid = fork();
                    if (0 == pid) {
                        errno = 0;
                        if (0 != execl(mcpConfig_get()->xlBinLocation, "xl", "destroy", domName, NULL)) {
                            mcp_log(LOG_ERR, "%s:%d error executing system cmd \"xl destroy %s\" (%d:%s)",
                                    __FUNCTION__, __LINE__, domName, errno, strerror(errno));
                            /* Exit the spawned process */
                            exit(-errno);
                        }
                    } else if (-1 == pid) {
                        mcp_log(LOG_ERR, "%s:%d error creating child process to destroy dom %s (%d:%s)",
                                __FUNCTION__, __LINE__, domName, errno, strerror(errno));
                    } else {
                        /* Wait until the spawned process exits so we can check 
                         * if command was executed successfully. */
                        if (-1 == waitpid(pid, &rc, 0)) {
                            success = false;
                            mcp_log(LOG_ERR, "%s:%d error waiting for child process %d (%d:%s)",
                                   __FUNCTION__, __LINE__, pid, errno, strerror(errno));
                        }
                        if (0 != WEXITSTATUS(rc)) {
                            success = false;
                            mcp_log(LOG_ERR, "%s:%d system cmd failed \"xl destroy %s\" (%d:%d:%s)",
                                    __FUNCTION__, __LINE__, arg, WEXITSTATUS(rc));
                        }
                    }
                } else if ((DOM_STATE_OFF    == m_domInfo[id-1].domState) && (DOM_STATE_ON       == state)) {
                    /* Domains in the OFF state are paused, unpause it now. */
                    m_domInfo[id-1].domState = state;
                    pid = fork();
                    if (0 == pid) {
                        errno = 0;
                        if (0 != execl(mcpConfig_get()->xlBinLocation, "xl", "unpause", domName, NULL)) {
                            mcp_log(LOG_ERR, "%s:%d error executing system cmd \"xl unpause %s\" (%d:%d:%s)",
                                    __FUNCTION__, __LINE__, domName, rc, errno, strerror(errno));
                            /* Exit the spawned process */
                            exit(-errno);
                        }
                    } else if (-1 == pid) {
                        mcp_log(LOG_ERR, "%s:%d error creating child process to unpause dom %s (%d:%s)",
                                __FUNCTION__, __LINE__, domName, errno, strerror(errno));
                    } else {
                        /* Wait until the spawned process exits so we can check 
                         * if command was executed successfully. */
                        if (-1 == waitpid(pid, &rc, 0)) {
                            success = false;
                            mcp_log(LOG_ERR, "%s:%d error waiting for child process %d (%d:%s)",
                                   __FUNCTION__, __LINE__, pid, errno, strerror(errno));
                        }
                        if (0 != WEXITSTATUS(rc)) {
                            success = false;
                            mcp_log(LOG_ERR, "%s:%d system cmd failed \"xl unpause %s\" (%d)",
                                    __FUNCTION__, __LINE__, arg, WEXITSTATUS(rc));
                        }
                    }
                } else if ((DOM_STATE_ON     == m_domInfo[id-1].domState) && (DOM_STATE_OFF      == state)) {
                    /* Domains in the OFF state are paused. */
                    m_domInfo[id-1].domState = state;
                    pid = fork();
                    if (0 == pid) {
                        errno = 0;
                        if (0 != execl(mcpConfig_get()->xlBinLocation, "xl", "pause", domName, NULL)) {
                            mcp_log(LOG_ERR, "%s:%d error executing system cmd \"xl pause %s\" (%d:%d:%s)",
                                    __FUNCTION__, __LINE__, domName, rc, errno, strerror(errno));
                            /* Exit the spawned process */
                            exit(-errno);
                        }
                    } else if (-1 == pid) {
                        mcp_log(LOG_ERR, "%s:%d error creating child process to pause dom %s (%d:%s)",
                                __FUNCTION__, __LINE__, domName, errno, strerror(errno));
                    } else {
                        /* Wait until the spawned process exits so we can check 
                         * if command was executed successfully. */
                        if (-1 == waitpid(pid, &rc, 0)) {
                            success = false;
                            mcp_log(LOG_ERR, "%s:%d error waiting for child process %d (%d:%s)",
                                   __FUNCTION__, __LINE__, pid, errno, strerror(errno));
                        }
                        if (0 != WEXITSTATUS(rc)) {
                            success = false;
                            mcp_log(LOG_ERR, "%s:%d system cmd failed \"xl pause %s\" (%d)",
                                    __FUNCTION__, __LINE__, arg, WEXITSTATUS(rc));
                        }
                    }
                } else if ((DOM_STATE_ON     == m_domInfo[id-1].domState) && (DOM_STATE_PAUSED   == state)) {
                    m_domInfo[id-1].domState = state;
                    pid = fork();
                    if (0 == pid) {
                        errno = 0;
                        if (0 != execl(mcpConfig_get()->xlBinLocation, "xl", "pause", domName, NULL)) {
                            mcp_log(LOG_ERR, "%s:%d error executing system cmd \"xl pause %s\" (%d:%d:%s)",
                                    __FUNCTION__, __LINE__, arg, rc, errno, strerror(errno));
                            /* Exit the spawned process */
                            exit(-errno);
                        }
                    } else if (-1 == pid) {
                        mcp_log(LOG_ERR, "%s:%d error creating child process to pause dom %s (%d:%s)",
                                __FUNCTION__, __LINE__, domName, errno, strerror(errno));
                    } else {
                        /* Wait until the spawned process exits so we can check 
                         * if command was executed successfully. */
                        if (-1 == waitpid(pid, &rc, 0)) {
                            success = false;
                            mcp_log(LOG_ERR, "%s:%d error waiting for child process %d (%d:%s)",
                                   __FUNCTION__, __LINE__, pid, errno, strerror(errno));
                        }
                        if (0 != WEXITSTATUS(rc)) {
                            success = false;
                            mcp_log(LOG_ERR, "%s:%d system cmd failed \"xl pause %s\" (%d)",
                                    __FUNCTION__, __LINE__, arg, WEXITSTATUS(rc));
                        }
                    }
                } else if ((DOM_STATE_ON     == m_domInfo[id-1].domState) && (DOM_STATE_RESET    == state)) {
                    m_domInfo[id-1].domState = DOM_STATE_ON;
                    pid = fork();
                    if (0 == pid) {
                        errno = 0;
                        if (0 != execl(mcpConfig_get()->xlBinLocation, "xl", "reboot", domName, NULL)) {
                            mcp_log(LOG_ERR, "%s:%d error executing system cmd \"xl reboot %s\" (%d:%d:%s)",
                                    __FUNCTION__, __LINE__, arg, rc, errno, strerror(errno));
                            /* Exit the spawned process */
                            exit(-errno);
                        }
                    } else if (-1 == pid) {
                        mcp_log(LOG_ERR, "%s:%d error creating child process to reboot dom %s (%d:%s)",
                                __FUNCTION__, __LINE__, domName, errno, strerror(errno));
                    } else {
                        /* Wait until the spawned process exits so we can check 
                         * if command was executed successfully. */
                        if (-1 == waitpid(pid, &rc, 0)) {
                            success = false;
                            mcp_log(LOG_ERR, "%s:%d error waiting for child process %d (%d:%s)",
                                   __FUNCTION__, __LINE__, pid, errno, strerror(errno));
                        }
                        if (0 != WEXITSTATUS(rc)) {
                            success = false;
                            mcp_log(LOG_ERR, "%s:%d system cmd failed \"xl reboot %s\" (%d)",
                                    __FUNCTION__, __LINE__, arg, WEXITSTATUS(rc));
                        }
                    }
                } else if ((DOM_STATE_PAUSED == m_domInfo[id-1].domState) && (DOM_STATE_UNPAUSED == state)) {
                    m_domInfo[id-1].domState = state;
                    pid = fork();
                    if (0 == pid) {
                        errno = 0;
                        if (0 != execl(mcpConfig_get()->xlBinLocation, "xl", "unpause", domName, NULL)) {
                            mcp_log(LOG_ERR, "%s:%d error executing system cmd \"xl unpause %s\" (%d:%d:%s)",
                                    __FUNCTION__, __LINE__, arg, rc, errno, strerror(errno));
                            /* Exit the spawned process */
                            exit(-errno);
                        }
                    } else if (-1 == pid) {
                        mcp_log(LOG_ERR, "%s:%d error creating child process to unpause dom %s (%d:%s)",
                                __FUNCTION__, __LINE__, domName, errno, strerror(errno));
                    } else {
                        /* Wait until the spawned process exits so we can check 
                         * if command was executed successfully. */
                        if (-1 == waitpid(pid, &rc, 0)) {
                            success = false;
                            mcp_log(LOG_ERR, "%s:%d error waiting for child process %d (%d:%s)",
                                   __FUNCTION__, __LINE__, pid, errno, strerror(errno));
                        }
                        if (0 != WEXITSTATUS(rc)) {
                            success = false;
                            mcp_log(LOG_ERR, "%s:%d system cmd failed \"xl pause %s\" (%d)",
                                    __FUNCTION__, __LINE__, arg, WEXITSTATUS(rc));
                        }
                    }
                } else if (state != m_domInfo[id-1].domState) {
                    /* If the new state is different than the current state and this 
                     * condition is reached, the new state would result in an 
                     * invalid transition. */
                    success = false;
                    mcp_log(LOG_ERR, "%s:%d invalid state transition requested for dom %u: %d -> %d",
                            __FUNCTION__, __LINE__, id, m_domInfo[id-1].domState, state);
                }
            } else /* ! (NULL != domName) */ {
                success = false;
                mcp_log(LOG_ERR, "%s:%d invalid arguments (%d/%d)",
                        __FUNCTION__, __LINE__, id, state);
            }
        } /* if (state != m_domInfo[id-1].domState) */

        rc = pthread_mutex_unlock(&m_domInfoLock);
        if (0 != rc) {
            mcp_log(LOG_ERR, "%s:%d error unlocking mutex (%d:%s)",
                    __FUNCTION__, __LINE__, rc, strerror(rc));
        }
    } else {
        success = false;
        mcp_log(LOG_ERR, "%s:%d error locking mutex (%d:%s)",
                __FUNCTION__, __LINE__, rc, strerror(rc));
    }

    if (NULL != arg) {
        free(arg);
    }

    return success;
} /* bool mcpDC_setDomState(uint32_t id, McpDomState_t state) */

bool mcpDC_getDomState(uint32_t id, McpDomState_t *state) {
    bool success = true;
    int32_t rc;

    rc = pthread_mutex_lock(&m_domInfoLock);
    if (0 == rc) {
        /* Ensure that the domain ID is valid. */
        if ((0 < id) && (m_numDoms > id) && (NULL != state)) {
            *state = m_domInfo[id-1].domState;
        } else {
            success = false;
            mcp_log(LOG_ERR, "%s:%d invalid arguments (%d/%p)",
                    __FUNCTION__, __LINE__, id, (void*)state);
        }

        rc = pthread_mutex_unlock(&m_domInfoLock);
        if (0 != rc) {
            mcp_log(LOG_ERR, "%s:%d error unlocking mutex (%d:%s)",
                    __FUNCTION__, __LINE__, rc, strerror(rc));
        }
    } else {
        success = false;
        mcp_log(LOG_ERR, "%s:%d error locking mutex (%d:%s)",
                __FUNCTION__, __LINE__, rc, strerror(rc));
    }

    return success;
} /* bool mcpDC_getDomState(uint32_t id, McpDomState_t *state) */

bool mcpDC_setSchedule(uint32_t sched) {
    bool success = true, changed = false;
    int32_t rc;
    uint32_t tslice;
    pid_t pid;
    char *arg = NULL;

    mcp_log(LOG_DEBUG, "MCP changing to schedule %u", sched);

    /* Lock the m_domInfoLock instead of bothering with the m_schedInfo->lock.  
     * because we need to access the domain information. */
    rc = pthread_mutex_lock(&m_domInfoLock);
    if (0 == rc) {
        /* See if it is necessary to change schedules or not. */
        if (m_sched != sched) {
            rc = sqlite3_reset(m_schedInfo->stmt);
            if (SQLITE_OK != rc) {
                success = false;
                mcp_log(LOG_ERR, "%s:%d error resetting statement (%d:%s)",
                        __FUNCTION__, __LINE__, rc, sqlite3_errstr(rc));
            }

            if (true == success) {
                rc = sqlite3_bind_int(m_schedInfo->stmt, 1, sched);
                if (SQLITE_OK != rc) {
                    success = false;
                    mcp_log(LOG_ERR, "%s:%d error binding id %d to param %d (%d:%s)",
                            __FUNCTION__, __LINE__, sched, 1, rc, sqlite3_errstr(rc));
                }
            }

            if (true == success) {
                rc = sqlite3_step(m_schedInfo->stmt);
                if (SQLITE_DONE == rc) {
                    /* a return code of SQLITE_DONE means no rows were found, 
                     * but that can still be valid for a 'safe' state */
                    changed = true;
                    m_sched = sched;
                    tslice = 0;
                } else if (SQLITE_ROW != rc) {
                    success = false;
                    mcp_log(LOG_ERR, "%s:%d error executing prepared statement (%d:%s)",
                            __FUNCTION__, __LINE__, rc, sqlite3_errstr(rc));
                } else {
                    changed = true;
                    m_sched = sched;

                    tslice = sqlite3_column_int(m_schedInfo->stmt, 0);
                } /* else (rc == SQLITE_ROW) */
            } /* if (true == success) */
        } /* if (m_sched != sched) */

        rc = pthread_mutex_unlock(&m_domInfoLock);
        if (0 != rc) {
            mcp_log(LOG_ERR, "%s:%d error unlocking mutex (%d:%s)",
                    __FUNCTION__, __LINE__, rc, strerror(rc));
        }
    } else /* !(0 == rc) */ {
        success = false;
        mcp_log(LOG_ERR, "%s:%d error locking mutex (%d:%s)",
                __FUNCTION__, __LINE__, rc, strerror(rc));
    }

    /* If the schedule was changed, update the domains */
    if (true == changed) {
        /* If tslice is not 0 then set a custom timeslice.  This only needs to 
         * be done once since the timeslice is a scheduler-parameter, so it is 
         * (or should be) the same for every domain assigned to the current 
         * schedule. */
        if (0 != tslice) {
            errno = 0;
            pid = fork();
            if (0 == pid) {
                (void)asprintf(&arg, "%d", tslice);
                errno = 0;
                if (0 != execl(mcpConfig_get()->xlBinLocation, "xl", "sched-credit", "-s", "-t", arg, NULL)) {
                    mcp_log(LOG_ERR, "%s:%d error executing system cmd \"xl sched-credit -s -t %s\" (%d:%s)",
                            __FUNCTION__, __LINE__, arg, errno, strerror(errno));
                    /* Exit the spawned process */
                    exit(-errno);
                }
            } else if (-1 == pid) {
                mcp_log(LOG_ERR, "%s:%d error creating child process to set schedule timeslice to %d (%d:%s)",
                        __FUNCTION__, __LINE__, tslice, errno, strerror(errno));
            } else {
                /* Wait until the spawned process exits so we can check 
                 * if command was executed successfully. */
                if (-1 == waitpid(pid, &rc, 0)) {
                    success = false;
                    mcp_log(LOG_ERR, "%s:%d error waiting for child process %d (%d:%s)",
                           __FUNCTION__, __LINE__, pid, errno, strerror(errno));
                }
                if (0 != WEXITSTATUS(rc)) {
                    success = false;
                    mcp_log(LOG_ERR, "%s:%d system cmd failed \"xl sched-credit -s -t %s\" (%d)",
                            __FUNCTION__, __LINE__, arg, WEXITSTATUS(rc));
                }
            }
        } /* if (0 != tslice) */

        success = mcpDC_startDomSched(sched);
    } /* if (true == changed) */

    free(arg);

    return success;
} /* bool mcpDC_setSchedule(uint32_t sched) */

static bool mcpDC_startDomSched(uint32_t sched) {
    bool success = true;
    int32_t rc;
    uint32_t *newDomStates = NULL, *weight = NULL, *cap = NULL;
    char *weightStr = NULL, *capStr = NULL;
    pid_t pid;

    /* Lock the m_domInfoLock instead of bothering with the 
     * m_schedDomInfo->lock.  because we need to access the domain info. */
    rc = pthread_mutex_lock(&m_domInfoLock);
    if (0 == rc) {
        /* These arrays can't be fully created until the mutex is locked, 
         * otherwise access of m_numDoms is a possible race condition. */
        newDomStates = (uint32_t*) calloc(m_numDoms, sizeof(uint32_t));
        weight = (uint32_t*) calloc(m_numDoms, sizeof(uint32_t));
        cap = (uint32_t*) calloc(m_numDoms, sizeof(uint32_t));
        if ((NULL == newDomStates) || (NULL == weight) || (NULL == cap)) {
            success = false;
            mcp_log(LOG_ERR, "%s:%d error allocating space (%p/%p/%p) for starting schedule %u (%d:%s)",
                    __FUNCTION__, __LINE__,
                    newDomStates, weight, cap, sched, errno, strerror(errno));
        }

        if (true == success) {
            /* default all of the new dom states to OFF (unless the domain has 
             * been deleted) */
            for (uint32_t i = 0; i < m_numDoms; i++) {
                if (DOM_STATE_DELETE != m_domInfo[i].domState) {
                    newDomStates[i] = DOM_STATE_OFF;
                } else {
                    newDomStates[i] = DOM_STATE_DELETE;
                }
            }

            rc = sqlite3_reset(m_schedDomInfo->stmt);
            if (SQLITE_OK != rc) {
                success = false;
                mcp_log(LOG_ERR, "%s:%d error resetting statement (%d:%s)",
                        __FUNCTION__, __LINE__, rc, sqlite3_errstr(rc));
            }
        }

        if (true == success) {
            rc = sqlite3_bind_int(m_schedDomInfo->stmt, 1, sched);
            if (SQLITE_OK != rc) {
                success = false;
                mcp_log(LOG_ERR, "%s:%d error binding schedule %d to param %d (%d:%s)",
                        __FUNCTION__, __LINE__, sched, 1, rc, sqlite3_errstr(rc));
            }
        }

        rc = SQLITE_ROW;
        while ((true == success) && (SQLITE_ROW == rc)) {
            rc = sqlite3_step(m_schedDomInfo->stmt);
            if (SQLITE_ROW == rc) {
                uint32_t id;

                id = sqlite3_column_int(m_schedDomInfo->stmt, 0);
                newDomStates[id-1] = DOM_STATE_ON;

                weight[id-1] = sqlite3_column_int(m_schedDomInfo->stmt, 1);
                cap[id-1] = sqlite3_column_int(m_schedDomInfo->stmt, 2);
            } else if (SQLITE_DONE != rc) {
                success = false;
                mcp_log(LOG_ERR, "%s:%d error executing prepared statement (%d:%s)",
                        __FUNCTION__, __LINE__, rc, sqlite3_errstr(rc));
            }
        } /* while ((true == success) && (SQLITE_ROW == rc)) */

        rc = pthread_mutex_unlock(&m_domInfoLock);
        if (0 != rc) {
            mcp_log(LOG_ERR, "%s:%d error unlocking mutex (%d:%s)",
                    __FUNCTION__, __LINE__, rc, strerror(rc));
        }
    } else /* !(0 == rc) */ {
        success = false;
        mcp_log(LOG_ERR, "%s:%d error locking mutex (%d:%s)",
                __FUNCTION__, __LINE__, rc, strerror(rc));
    }

    if (true == success) {
        for (uint32_t i = 0; (i < m_numDoms) && (true == success); i++) {
            /* Before setting the domain to the desired state for this schedule, 
             * set the domain schedule parameters, if any were specified */
            if ((NULL != m_domInfo[i].name) && (0 != weight[i]) && (0 != cap[i])) {
                (void)asprintf(&weightStr, "%u", weight[i]);
                (void)asprintf(&capStr, "%u", cap[i]);

                mcp_log(LOG_DEBUG, "Setting schedule parameters for domain %d: name = \"%s\", weight = %s, cpu cap = %s",
                        i+1, m_domInfo[i].name, weightStr, capStr);
                errno = 0;
                pid = fork();
                if (0 == pid) {
                    errno = 0;
                    if (0 != execl(mcpConfig_get()->xlBinLocation, "xl", "sched-credit", "-d", m_domInfo[i].name, "-w", weight, "-c", cap, NULL)) {
                        mcp_log(LOG_ERR, "%s:%d error executing system cmd \"xl sched-credit -d %s -w %s -c %s\" (%d:%s)",
                                __FUNCTION__, __LINE__, m_domInfo[i].name, weight, cap, errno, strerror(errno));
                        /* Exit the spawned process */
                        exit(-errno);
                    }
                } else if (-1 == pid) {
                    mcp_log(LOG_ERR, "%s:%d error creating child process to adjust sched params for dom %s (%d:%s)",
                            __FUNCTION__, __LINE__, m_domInfo[i].name, errno, strerror(errno));
                } else {
                    /* Wait until the spawned process exits so we can check if 
                     * command was executed successfully. */
                    if (-1 == waitpid(pid, &rc, 0)) {
                        success = false;
                        mcp_log(LOG_ERR, "%s:%d error waiting for child process %d (%d:%s)",
                               __FUNCTION__, __LINE__, pid, errno, strerror(errno));
                    }
                    if (0 != WEXITSTATUS(rc)) {
                        success = false;
                        mcp_log(LOG_ERR, "%s:%d system cmd failed \"xl sched-credit -d %s -w %s -c %s\" (%d)",
                                __FUNCTION__, __LINE__, m_domInfo[i].name, weight, cap, WEXITSTATUS(rc));
                    }
                }

                if (NULL != weightStr) {
                    free(weightStr);
                    weightStr = NULL;
                }
                if (NULL != capStr) {
                    free(capStr);
                    capStr = NULL;
                }
            } /* if ((NULL != m_domInfo[i].name) && (0 != weight[i]) && (0 != cap[i])) */

            /* set the domain state */
            success = mcpDC_setDomState(i+1, newDomStates[i]);
        } /* for (uint32_t i = 0; (i < m_numDoms) && (true == success); i++) */
    } /* if (true == success) */

    if (NULL != newDomStates) {
        free(newDomStates);
    }
    if (NULL != weight) {
        free(weight);
    }
    if (NULL != cap) {
        free(cap);
    }

    return success;
} /* static bool mcpDC_startDomSched(uint32_t sched) */

static void mcpDC_shutdownDoms(void) {
    int32_t rc;

    /* Just lock the m_domInfoLock instead of bothering with the 
     * m_schedDomInfo->lock.  */
    rc = pthread_mutex_lock(&m_domInfoLock);
    if (0 == rc) {
        mcp_log(LOG_DEBUG, "stopping %d doms", m_numDoms);

        for (uint32_t i = 0; i < m_numDoms; i++) {
            (void)mcpDC_setDomState(i+1, DOM_STATE_DELETE);
        }

        rc = pthread_mutex_unlock(&m_domInfoLock);
        if (0 != rc) {
            mcp_log(LOG_ERR, "%s:%d error unlocking mutex (%d:%s)",
                    __FUNCTION__, __LINE__, rc, strerror(rc));
        }
    } else /* !(0 == rc) */ {
        mcp_log(LOG_ERR, "%s:%d error locking mutex (%d:%s)",
                __FUNCTION__, __LINE__, rc, strerror(rc));
    }
} /* static void mcpDC_shutdownDoms(void) */

static char* mcpDC_getDomName(uint32_t id) {
    int32_t rc;
    char *name = NULL;

    rc = pthread_mutex_lock(&m_domInfoLock);
    if (0 == rc) {
        /* Do a quick sanity check sanity check on the arguments */
        if ((0 < id) && (m_numDoms >= id)) {
            name = m_domInfo[id-1].name;
        } else {
            mcp_log(LOG_ERR, "%s:%d invalid domain ID %u",
                    __FUNCTION__, __LINE__, id);
        }

        rc = pthread_mutex_unlock(&m_domInfoLock);
        if (0 != rc) {
            mcp_log(LOG_ERR, "%s:%d error unlocking mutex (%d:%s)",
                    __FUNCTION__, __LINE__, rc, strerror(rc));
        }
    } else /* !(0 == rc) */ {
        mcp_log(LOG_ERR, "%s:%d error locking mutex (%d:%s)",
                __FUNCTION__, __LINE__, rc, strerror(rc));
    }

    return name;
} /* static char* mcpDC_getDomName(uint32_t id) */

bool mcpDC_getStatus(uint32_t size, char *buffer) {
    bool success = true;
    int32_t rc;
    int filedes[2];
    pid_t pid;

    /* create a pipe used to capture the output from the "xl list" process. */
    errno = 0;
    rc = pipe(filedes);
    if (0 == rc) {
        errno = 0;
        pid = fork();
        if (0 == pid) {
            /* the child process doesn't need the reading end */
            close(filedes[0]);

            /* map the output end of the pipe to STDOUT and STDERR */
            dup2(filedes[1], 1);
            dup2(filedes[1], 2);

            /* the output descriptor isn't needed any more */
            close(filedes[1]);

            errno = 0;
            if (0 != execl(mcpConfig_get()->xlBinLocation, "xl", "list", NULL)) {
                mcp_log(LOG_ERR, "%s:%d error executing system cmd \"xl list\" (%d:%s)",
                        __FUNCTION__, __LINE__, errno, strerror(errno));
                /* Exit the spawned process */
                exit(-errno);
            }
        } else if (0 < pid) {
            /* the child process doesn't need the writing end */
            close(filedes[1]);

            /* Read the output from the forked process */
            while(0 != read(filedes[0], buffer, size));

            /* the input descriptor isn't needed any more */
            close(filedes[0]);
        } else {
            success = false;
            mcp_log(LOG_ERR, "%s:%d error forking new process to obtain domain status (%d:%s)",
                    __FUNCTION__, __LINE__, errno, strerror(errno));
        }
    } else {
        success = false;
        mcp_log(LOG_ERR, "%s:%d error creating pipe to obtain domain status (%d:%s)",
                __FUNCTION__, __LINE__, errno, strerror(errno));
    }

    return success;
} /* bool mcpDC_getStatus(char **status) */

bool mcpDC_checkDomState(void) {
    struct XenInfoHandle_s *handle;
    XenDomState_t xenState;
    VmState_t vmState;
    bool success = false;
    int32_t rc;

    /* Map all of the possible Xen domain states to the VM state that we report 
     * to the VMS DB.  If a domain has been destroyed the status is likely to be 
     * XEN_DOM_UNKNOWN, in that case ERROR should be reported.  If a domain is 
     * blocked then it is waiting on I/O or doesn't have priority or has nothing 
     * to do.  In any of those cases the domain is still "STARTED" and likely 
     * operating normally. */
    const VmState_t stateMapping[] = {
        [XEN_DOM_UNKNOWN]   = QS_VMS_VM_ERROR,
        [XEN_DOM_DYING]     = QS_VMS_VM_ERROR,
        [XEN_DOM_SHUTDOWN]  = QS_VMS_VM_ERROR,
        [XEN_DOM_PAUSED]    = QS_VMS_VM_PAUSED,
        [XEN_DOM_BLOCKED]   = QS_VMS_VM_STARTED,
        [XEN_DOM_RUNNING]   = QS_VMS_VM_STARTED,
    };

    rc = pthread_mutex_lock(&m_domInfoLock);
    if (0 == rc) {
        /* We don't know for sure if only MCP controlled domains are running, so 
         * we must ask for as much domain information as possible. */
        handle = xen_getDomInfo(0, 1024);
        if (NULL != handle) {
            /* Check the status of every domain, and if there is a VMS connection 
             * active, pass any state changes up to the DB. */
            for (uint32_t i = 0; i < m_numDoms; i++) {
                /* If a domain has been created (state isn't DOM_STATE_DELETE), 
                 * check the domain state if it has a domain name. */
                if (DOM_STATE_DELETE != m_domInfo[i].domState) {
                    if (NULL != m_domInfo[i].name) {
                        /* Sanity check, ensure that the domain has a valid state */
                        if (ARRAY_SIZE(stateMapping) > m_domInfo[i].xenState) {
                            vmState = stateMapping[m_domInfo[i].xenState];

                            /* If the domain ID is invalid, this function will 
                             * update it with the valid ID so that future domain 
                             * state seraches can be more efficient. */
                            xenState = xen_getDomState(handle, m_domInfo[i].name, &m_domInfo[i].id);
#ifdef DEBUG
                            syslog(LOG_DEBUG, "domain %u:%s status %u, xen: ID %u, state %u",
                                    i+1, m_domInfo[i].name, m_domInfo[i].domState, m_domInfo[i].id, xenState);
#endif

                            if (ARRAY_SIZE(stateMapping) > xenState) {
                                if (vmState != stateMapping[xenState]) {
                                    /* For now, don't let VMS communication 
                                     * issues shutdown the entire MCP. */
                                    (void)vms_set_vm_state(m_domInfo[i].name, stateMapping[xenState]);
                                }
                            } else {
                                mcp_log(LOG_ERR, "%s:%d domain %u:%s has invalid Xen state of %u",
                                        __FUNCTION__, __LINE__, i+1, m_domInfo[i].name, xenState);

                                /* Set the xen state to XEN_DOM_UNKNOWN so the 
                                 * state doesn't remain invalid. */
                                xenState = XEN_DOM_UNKNOWN;
                            }

                            /* Save the new xen state */
                            m_domInfo[i].xenState = xenState;
                        } else { /* ! (ARRAY_SIZE(stateMapping) > m_domInfo[i].xenState) */
                            mcp_log(LOG_ERR, "%s:%d domain %u:%s has invalid Xen state of %u",
                                    __FUNCTION__, __LINE__, i+1, m_domInfo[i].name, m_domInfo[i].xenState);

                            /* Set the xen state to XEN_DOM_UNKNOWN so the state 
                             * doesn't remain invalid. */
                            m_domInfo[i].xenState = XEN_DOM_UNKNOWN;
                        }
                    } else { /* ! (NULL != m_domInfo[i].name) */
                        mcp_log(LOG_WARNING, "Unable to retrieve domain state from Xen, no name set for dom %u", i+1);
                    }
                } /* if (DOM_STATE_DELETE != m_domInfo[i].domState) */
            } /* for (uint32_t i = 0; i < m_numDoms; i++) */

            /* Release the xen interface handle */
            xen_releaseHandle(handle);
        } else { /* ! (NULL != handle) */
            mcp_log(LOG_ERR, "%s:%d xen_getDomInfo(0, 1024) failed", __FUNCTION__, __LINE__);
        }

        rc = pthread_mutex_unlock(&m_domInfoLock);
        if (0 != rc) {
            mcp_log(LOG_ERR, "%s:%d error unlocking mutex (%d:%s)",
                    __FUNCTION__, __LINE__, rc, strerror(rc));
        }
    } else /* !(0 == rc) */ {
        mcp_log(LOG_ERR, "%s:%d error locking mutex (%d:%s)",
                __FUNCTION__, __LINE__, rc, strerror(rc));
    }

    return success;
} /* bool mcpDC_checkDomState(void) */

