
#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <pthread.h>
#include <errno.h>
#include <signal.h>

#include <fcntl.h>
#include <sys/stat.h>
#include <semaphore.h>
#include <unistd.h>
#include <sys/mman.h>

#include "sqlite3.h"
#include "sqlLib.h"
#include "mcpLib.h"

/* tables:
 *  CREATE TABLE paramTable (
 *      id          INTEGER PRIMARY KEY AUTOINCREMENT,
 *      name        TEXT,
 *      type        TEXT,
 *      port        TEXT
 *  );
 */

#ifndef DAEMON_NAME
#  define DAEMON_NAME   "mcp"
#endif

#ifndef MCP_SHM_NAME
#  define MCP_SHM_NAME  "/" DAEMON_NAME "_shm"
#endif

typedef struct McpSharedData_s {
    sem_t           sem;
    uint32_t        mcpState;
    uint32_t        opMode;
    uint32_t        flightLeg;
    uint32_t        numParams;
    double          params[];
} McpSharedData_t;

typedef struct McpLibDb_s {
    sqlite3         *mct;
    SqlStmt_t       *paramValidCheck;   /* SELECT 1 FROM paramTable WHERE id == ? LIMIT 1; */
    SqlStmt_t       *getRuleData;       /* SELECT name, equation FROM ruleTable WHERE id == ? LIMIT 1; */
    sem_t           *sem;
    McpSharedData_t *shm;
} McpLibDb_t;

static pthread_once_t m_dbOnce = PTHREAD_ONCE_INIT;
static McpLibDb_t *m_dbData = NULL;
static char *m_dbFile = NULL;

static void mcpLib_createDbData(void);
static bool mcpLib_entryValid(SqlStmt_t *validStmt, uint32_t id);
bool mcpLib_getMcpStateData(uint32_t *flightLeg, uint32_t *opMode, uint32_t *mcpState);

bool mcpLib_open(char *dbfile) {
    bool success = true;
    int32_t rc;

    /* Only set m_dbFile if it is currently NULL. */
    if (NULL == m_dbFile) {
        m_dbFile = strdup(dbfile);
    }

    /* If the EVENTS data key hasn't been created yet, create it now. */
    rc = pthread_once(&m_dbOnce, mcpLib_createDbData);
    if (0 != rc) {
        success = false;
        fprintf(stderr, "%s:%d error initializing DB connection (%d:%s)\n",
                __FUNCTION__, __LINE__, rc, strerror(rc));
    }

    /* If m_dbData is still NULL, return failure. */
    if (NULL == m_dbData) {
        success = false;
    }

    return success;
} /* bool mcpLib_open(void) */

void mcpLib_close(void) {
    int32_t rc;
    uint32_t shmSize;

    if (NULL != m_dbData) {
        /* delete the mutex and statement data */
        sqlLib_deleteStmt(&m_dbData->paramValidCheck);
        sqlLib_deleteStmt(&m_dbData->getRuleData);

        /* Now close the database connection */
        rc = sqlite3_close_v2(m_dbData->mct);
        if (SQLITE_OK != rc) {
            fprintf(stderr, "%s:%d error closing database (%d:%s)\n",
                    __FUNCTION__, __LINE__, rc, sqlite3_errstr(rc));
        }

        /* Regardless of if there were errors detected, shutdown the SQLite 
         * library */
        rc = sqlite3_shutdown();
        if (SQLITE_OK != rc) {
            fprintf(stderr, "%s:%d error shutting down sqlite library (%d:%s)\n",
                    __FUNCTION__, __LINE__, rc, sqlite3_errstr(rc));
        }

        if (NULL != m_dbData->shm) {
            /* Unmap the shared memory region.  MCP will handle deallocating it once 
             * it is no longer needed. */
            shmSize = sizeof(McpSharedData_t) + (m_dbData->shm->numParams * sizeof(double));
            errno = 0;
            if (0 != munmap(m_dbData->shm, shmSize)) {
                fprintf(stderr, "%s:%d error unmapping shared memory region (%d:%s)\n",
                       __FUNCTION__, __LINE__, errno, strerror(errno));
            }
        }

        free(m_dbData);
        m_dbData = NULL;
    }

    if (NULL != m_dbFile) {
        free(m_dbFile);
        m_dbFile = NULL;
    }
} /* void mcpLib_close(void) */

bool mcpLib_getFlightLeg(uint32_t *leg) {
    return mcpLib_getAllShmStateData(leg, NULL, NULL);
} /* bool mcpLib_getFlightLeg(uint32_t *leg) */

bool mcpLib_getOpMode(uint32_t *mode) {
    return mcpLib_getAllShmStateData(NULL, mode, NULL);
} /* bool mcpLib_getOpMode(uint32_t *mode) */

bool mcpLib_getMcpState(uint32_t *state) {
    return mcpLib_getAllShmStateData(NULL, NULL, state);
} /* bool mcpLib_getMcpState(uint32_t *state) */

bool mcpLib_getAllShmStateData(uint32_t *flightLeg, uint32_t *opMode, uint32_t *mcpState) {
    bool success = true;

    if (NULL != m_dbData) {
        errno = 0;
        if (0 == sem_wait(m_dbData->sem)) {
            if (NULL != flightLeg) {
                *flightLeg = m_dbData->shm->flightLeg;
            }
            if (NULL != opMode) {
                *opMode = m_dbData->shm->opMode;
            }
            if (NULL != mcpState) {
                *mcpState = m_dbData->shm->mcpState;
            }

            errno = 0;
            if (0 != sem_post(m_dbData->sem)) {
                success = false;
                fprintf(stderr, "%s:%d sem_post() error (%d:%s)\n",
                        __FUNCTION__, __LINE__, errno, strerror(errno));
            }
        } else {
            success = false;
            fprintf(stderr, "%s:%d sem_wait() error (%d:%s)\n",
                    __FUNCTION__, __LINE__, errno, strerror(errno));
        }
    } else /* !(NULL != m_dbData) */ {
        success = false;
        fprintf(stderr, "%s:%d MCP library uninitialized\n",
                __FUNCTION__, __LINE__);
    }

    return success;
} /* bool mcpLib_getAllShmStateData(uint32_t *flightLeg, uint32_t *opMode, uint32_t *mcpState) */

bool mcpLib_setParam(uint32_t id, double value) {
    bool success = true;

    if (NULL != m_dbData) {
        success = mcpLib_entryValid(m_dbData->paramValidCheck, id);
        if (true == success) {
            errno = 0;
            if (0 == sem_wait(m_dbData->sem)) {
                /* The parameter ID is 1 based, subtract 1 to get the param index */
                m_dbData->shm->params[id - 1] = value;

                errno = 0;
                if (0 != sem_post(m_dbData->sem)) {
                    success = false;
                    fprintf(stderr, "%s:%d sem_post() error (%d:%s)\n",
                            __FUNCTION__, __LINE__, errno, strerror(errno));
                }
            } else {
                success = false;
                fprintf(stderr, "%s:%d sem_wait() error (%d:%s)\n",
                        __FUNCTION__, __LINE__, errno, strerror(errno));
            }
        } else {
            fprintf(stderr, "%s:%d Invalid param %d\n",
                    __FUNCTION__, __LINE__, id);
        }
    } else /* !(NULL != m_dbData) */ {
        success = false;
        fprintf(stderr, "%s:%d MCP library uninitialized\n",
                __FUNCTION__, __LINE__);
    }

    return success;
} /* bool mcpLib_setParam(uint32_t id, double value) */

bool mcpLib_getParam(uint32_t id, double *value) {
    bool success = true;

    if (NULL != m_dbData) {
        success = mcpLib_entryValid(m_dbData->paramValidCheck, id);
        if (true == success) {
            errno = 0;
            if (0 == sem_wait(m_dbData->sem)) {
                /* The parameter ID is 1 based, subtract 1 to get the param 
                 * index */
                *value = m_dbData->shm->params[id - 1];

                errno = 0;
                if (0 != sem_post(m_dbData->sem)) {
                    success = false;
                    fprintf(stderr, "%s:%d sem_post() error (%d:%s)\n",
                            __FUNCTION__, __LINE__, errno, strerror(errno));
                }
            } else {
                success = false;
                fprintf(stderr, "%s:%d sem_wait() error (%d:%s)\n",
                        __FUNCTION__, __LINE__, errno, strerror(errno));
            }
        } else {
            fprintf(stderr, "%s:%d Invalid param %d\n",
                    __FUNCTION__, __LINE__, id);
        }
    } else /* !(NULL != m_dbData) */ {
        success = false;
        fprintf(stderr, "%s:%d MCP library uninitialized\n",
                __FUNCTION__, __LINE__);
    }

    return success;
} /* bool mcpLib_getParam(uint32_t id, double *value) */

bool mcpLib_getRule(uint32_t id, char **name, char **str) {
    int32_t rc;
    bool success = true;

    if (NULL != m_dbData) {
        if ((NULL != name) && (NULL != str)) {
            /* Set name and str to NULL to start */
            *name = NULL;
            *str = NULL;

            rc = pthread_mutex_lock(&m_dbData->getRuleData->lock);
            if (0 == rc) {
                rc = sqlite3_reset(m_dbData->getRuleData->stmt);
                if (SQLITE_OK != rc) {
                    success = false;
                    fprintf(stderr, "%s:%d error resetting statement (%d:%s)\n",
                            __FUNCTION__, __LINE__, rc, sqlite3_errstr(rc));
                }

                if (true == success) {
                    rc = sqlite3_bind_int(m_dbData->getRuleData->stmt, 1, id);
                    if (SQLITE_OK != rc) {
                        success = false;
                        fprintf(stderr, "%s:%d error binding id %d to param %d (%d:%s)\n",
                                __FUNCTION__, __LINE__, id, 1, rc, sqlite3_errstr(rc));
                    }
                }

                if (true == success) {
                    rc = sqlite3_step(m_dbData->getRuleData->stmt);
                    if (SQLITE_DONE == rc) {
                        /* a return code of SQLITE_DONE means no rows were 
                         * found, so this rule is invalid. */
                        success = false;
                    } else if (SQLITE_ROW != rc) {
                        success = false;
                        fprintf(stderr, "%s:%d error executing prepared statement (%d:%s)\n",
                                __FUNCTION__, __LINE__, rc, sqlite3_errstr(rc));
                    } else {
                        *name = strdup((const char*)sqlite3_column_text(m_dbData->getRuleData->stmt, 0));
                        *str = strdup((const char*)sqlite3_column_text(m_dbData->getRuleData->stmt, 1));
                    }
                }

                rc = pthread_mutex_unlock(&m_dbData->getRuleData->lock);
                if (0 != rc) {
                    fprintf(stderr, "%s:%d error unlocking mutex (%d:%s)\n",
                            __FUNCTION__, __LINE__, rc, strerror(rc));
                }
            } else /* !(0 == rc) */ {
                success = false;
                fprintf(stderr, "%s:%d error locking mutex (%d:%s)\n",
                        __FUNCTION__, __LINE__, rc, strerror(rc));
            }
        } else /* ! ((NULL != name) && (NULL != str)) */ {
            success = false;
            fprintf(stderr, "%s:%d invalid parameter provided (%p/%p)\n",
                    __FUNCTION__, __LINE__, (void*)name, (void*)str);
        }
    } else /* !(NULL != m_dbData) */ {
        success = false;
        fprintf(stderr, "%s:%d MCP library uninitialized\n",
                __FUNCTION__, __LINE__);
    }

    return success;
} /* bool mcpLib_getRule(uint32_t id, char **name, char **str) */

static void mcpLib_createDbData(void) {
    const char *cmd;
    bool success = true;
    int32_t rc, fd;
    uint32_t shmSize;

    m_dbData = (McpLibDb_t*) malloc(sizeof(McpLibDb_t));

    if (NULL == m_dbData) {
        success = false;
        fprintf(stderr, "%s:%d unable to allocate memory for DB connection\n",
                __FUNCTION__, __LINE__);
    } else {
        m_dbData->paramValidCheck = NULL;
        m_dbData->getRuleData = NULL;
    }

    if (true == success) {
        rc = sqlite3_initialize();
        if (SQLITE_OK != rc) {
            success = false;
            fprintf(stderr, "%s:%d error initializing sqlite3 (%d:%s)\n",
                    __FUNCTION__, __LINE__, rc, sqlite3_errstr(rc));
        }
    }

    if (true == success) {
        rc = sqlite3_open_v2(m_dbFile, &m_dbData->mct, SQLITE_OPEN_READWRITE, NULL);
        if (SQLITE_OK != rc) {
            success = false;
            fprintf(stderr, "%s:%d can't open \"%s\" (%d:%s)\n",
                    __FUNCTION__, __LINE__, m_dbFile, rc, sqlite3_errstr(rc));
        }
    }

    if (true == success) {
        cmd = "PRAGMA foreign_keys = ON;";
        rc = sqlite3_exec(m_dbData->mct, cmd, NULL, NULL, NULL);
        if (SQLITE_OK != rc) {
            success = false;
            fprintf(stderr, "%s:%d error executing \"%s\" (%d:%s)\n",
                    __FUNCTION__, __LINE__, cmd, rc, sqlite3_errstr(rc));
        }
    }

    /* Set the busy handler for this database connection to wait at least 
     * 500msec for database locks to become available. */
    if (true == success) {
        rc = sqlite3_busy_timeout(m_dbData->mct, 1000);
        if (SQLITE_OK != rc) {
            success = false;
            fprintf(stderr, "%s:%d error setting busy timeout of %dmsec (%d:%s)\n",
                    __FUNCTION__, __LINE__, 1000, rc, sqlite3_errstr(rc));
        }
    }

    if (true == success) {
        cmd = "SELECT 1 FROM paramTable WHERE id == ? LIMIT 1;";
        m_dbData->paramValidCheck = sqlLib_createStmt(m_dbData->mct, cmd);
        if (NULL == m_dbData->paramValidCheck) {
            success = false;
            fprintf(stderr, "%s:%d error creating statement \"%s\" (%d:%s)\n",
                   __FUNCTION__, __LINE__, cmd, errno, strerror(errno));
        }
    }

    if (true == success) {
        cmd = "SELECT name, equation FROM ruleTable WHERE id == ? LIMIT 1;";
        m_dbData->getRuleData = sqlLib_createStmt(m_dbData->mct, cmd);
        if (NULL == m_dbData->getRuleData) {
            success = false;
            fprintf(stderr, "%s:%d error creating statement \"%s\" (%d:%s)\n",
                   __FUNCTION__, __LINE__, cmd, errno, strerror(errno));
        }
    }

    /* Open the shared memory region. */
    if (true == success) {
        errno = 0;
        fd = shm_open(MCP_SHM_NAME, O_RDWR, 0);
        if (0 >= fd) {
            success = false;
            fprintf(stderr, "%s:%d unable to open shared memory region \"%s\" (%d:%s)\n",
                   __FUNCTION__, __LINE__, MCP_SHM_NAME, errno, strerror(errno));
        }
    }

    /* Get a pointer to the shared memory region. */
    if (true == success) {
        errno = 0;
        /* First get access to the base MCP data, this will tell us the total 
         * size that needs to be mapped. */
        shmSize = sizeof(McpSharedData_t);
        m_dbData->shm = (McpSharedData_t*) mmap(NULL, shmSize, (PROT_READ | PROT_WRITE), MAP_SHARED, fd, 0);
        if (NULL == m_dbData->shm) {
            success = false;
            fprintf(stderr, "%s:%d unable to map shared memory region of size %d (%d:%s)\n",
                   __FUNCTION__, __LINE__, shmSize, errno, strerror(errno));
        } else {
            shmSize += m_dbData->shm->numParams * sizeof(double);
            m_dbData->shm = (McpSharedData_t*) mmap(NULL, shmSize, (PROT_READ | PROT_WRITE), MAP_SHARED, fd, 0);
            if (NULL == m_dbData->shm) {
                success = false;
                fprintf(stderr, "%s:%d unable to remap shared memory region of size %d (%d:%s)\n",
                       __FUNCTION__, __LINE__, shmSize, errno, strerror(errno));
            }
        }
    }

    /* The file descriptor used to open the shared memory region is no longer 
     * needed. */
    if (0 != close(fd)) {
        success = false;
        fprintf(stderr, "%s:%d unable to close shared memory region file descriptor (%d:%s)\n",
               __FUNCTION__, __LINE__, errno, strerror(errno));
    }

    /* Map to the shared memory semaphore */
    if (true == success) {
        m_dbData->sem = &m_dbData->shm->sem;
    }

    if (true != success) {
        mcpLib_close();
    }
} /* static void mcpLib_createDbData(void) */

static bool mcpLib_entryValid(SqlStmt_t *validStmt, uint32_t id) {
    bool success = true;
    int32_t rc;

    if (NULL != m_dbData) {
        rc = pthread_mutex_lock(&validStmt->lock);
        if (0 == rc) {
            rc = sqlite3_reset(validStmt->stmt);
            if (SQLITE_OK != rc) {
                success = false;
                fprintf(stderr, "%s:%d error resetting statement (%d:%s)\n",
                       __FUNCTION__, __LINE__, rc, sqlite3_errstr(rc));
            }

            if (true == success) {
                rc = sqlite3_bind_int(validStmt->stmt, 1, id);
                if (SQLITE_OK != rc) {
                    success = false;
                    fprintf(stderr, "%s:%d error binding id %d to param %d (%d:%s)\n",
                           __FUNCTION__, __LINE__, id, 1, rc, sqlite3_errstr(rc));
                }
            }

            if (true == success) {
                rc = sqlite3_step(validStmt->stmt);
                if (SQLITE_DONE == rc) {
                    /* a return code of SQLITE_DONE means no rows were found, so 
                     * this state is invalid. */
                    success = false;
                } else if (SQLITE_ROW != rc) {
                    success = false;
                    fprintf(stderr, "%s:%d error executing prepared statement (%d:%s)\n",
                           __FUNCTION__, __LINE__, rc, sqlite3_errstr(rc));
                } else if (0 == sqlite3_column_int(validStmt->stmt, 0)) {
                    success = false;
                }
            }

            rc = pthread_mutex_unlock(&validStmt->lock);
            if (0 != rc) {
                fprintf(stderr, "%s:%d error unlocking mutex (%d:%s)\n",
                       __FUNCTION__, __LINE__, rc, strerror(rc));
            }
        } else /* !(0 == rc) */ {
            success = false;
            fprintf(stderr, "%s:%d error locking mutex (%d:%s)\n",
                   __FUNCTION__, __LINE__, rc, strerror(rc));
        }
    } else /* !(NULL != m_dbData) */ {
        success = false;
        fprintf(stderr, "%s:%d MCP library uninitialized\n",
                __FUNCTION__, __LINE__);
    }

    return success;
} /* static bool mcpLib_entryValid(SqlStmt_t *validStmt, uint32_t id) */

