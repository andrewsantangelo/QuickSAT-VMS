
#include <stdint.h>
#include <stdbool.h>
#include <pthread.h>
#include <errno.h>
#include <string.h>
#include <stdlib.h>
#include <signal.h>
#include <syslog.h>

#include <semaphore.h> /* needed because of sem_t definition in mcpDb.h */

#include "sqlite3.h"
#include "mcp.h"
#include "mcpDb.h"
#include "mcpCond.h"
#include "mcpAction.h"
#include "mcpRules.h"

/* tables relevant to rule changes:
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
 *  CREATE TABLE paramTable (
 *      id          INTEGER PRIMARY KEY AUTOINCREMENT,
 *      name        TEXT,
 *      type        TEXT,
 *      port        TEXT
 *  );
 *
 *  CREATE TABLE stateRuleLink (
 *      state       INTEGER NOT NULL,
 *      rule        INTEGER NOT NULL,
 *      FOREIGN KEY(state)      REFERENCES stateTable(id),
 *      FOREIGN KEY(rule)       REFERENCES ruleTable(id)
 *  );
 */

typedef struct McpRule_s {
    uint32_t            id;
    struct itimerspec   seconds;
    timer_t             timer;
    McpCalcChain_t      *chain;
    uint32_t            actionId;
    void                *param;
} McpRule_t;

static McpRule_t *m_rules = NULL;
static uint32_t m_numRules = 0;
static uint64_t m_startTime = 0;

static pthread_mutex_t m_stateChangeLock = PTHREAD_MUTEX_INITIALIZER;
static sqlite3_stmt *m_stateChangeStmt;

bool mcpRules_initialize(void) {
    int32_t rc;
    bool success = true;
    const char *text, *cmd;
    sqlite3_stmt *stmt;
    uint32_t i, size;
    struct sigevent sigevt;
    double seconds;
    const void *blob;
    struct timespec now;

    /* Determine how many rules are defined in the MCT */
    cmd = "SELECT COUNT(*) FROM ruleTable LIMIT 1;";
    rc = sqlite3_prepare_v2(g_mct, cmd, strlen(cmd), &stmt, NULL);
    if (SQLITE_OK != rc) {
        success = false;
        mcp_log(LOG_ERR, "%s:%d error preparing statement \"%s\" (%d:%s)",
               __FUNCTION__, __LINE__, cmd, rc, sqlite3_errmsg(g_mct));
    } else {
        if (SQLITE_ROW != sqlite3_step(stmt)) {
            success = false;
            mcp_log(LOG_ERR, "%s:%d error executing statement \"%s\" (%d:%s)",
                   __FUNCTION__, __LINE__, cmd, rc, sqlite3_errmsg(g_mct));
        } else {
            m_numRules = sqlite3_column_int(stmt, 0);
            m_rules = (McpRule_t*) malloc(sizeof(McpRule_t) * m_numRules);
            memset(m_rules, 0, sizeof(sizeof(McpRule_t) * m_numRules));
        }
    }

    (void) sqlite3_finalize(stmt);

    if (true == success) {
        /* Validate and prepare each rule */
        cmd = "SELECT * FROM ruleTable;";
        rc = sqlite3_prepare_v2(g_mct, cmd, strlen(cmd), &stmt, NULL);
        if (SQLITE_OK != rc) {
            success = false;
            mcp_log(LOG_ERR, "%s:%d error preparing statement \"%s\" (%d:%s)",
                   __FUNCTION__, __LINE__, cmd, rc, sqlite3_errstr(rc));
        } else /* ! (SQLITE_OK != rc) */ {
            rc = sqlite3_step(stmt);
            while ((true == success) && (SQLITE_ROW == rc)) {
                /* ruleTable columns:
                 *  0: id
                 *  1: name
                 *  2: seconds
                 *  3: equation
                 *  4: action
                 *  5: option */
                i = sqlite3_column_int(stmt, 0);
                m_rules[i-1].id = i;

                seconds = sqlite3_column_double(stmt, 2);
                m_rules[i-1].seconds.it_value.tv_sec = (uint32_t)seconds;
                m_rules[i-1].seconds.it_value.tv_nsec = (uint32_t)((uint64_t)(seconds * NSEC_PER_SEC) % NSEC_PER_SEC);
                m_rules[i-1].seconds.it_interval.tv_sec = m_rules[i-1].seconds.it_value.tv_sec;
                m_rules[i-1].seconds.it_interval.tv_nsec = m_rules[i-1].seconds.it_value.tv_nsec;

                /* Supply the "action" and the size of the "param" columns to 
                 * the action validation function. */
                blob = sqlite3_column_blob(stmt, 5);
                size = sqlite3_column_bytes(stmt, 5);

                m_rules[i-1].param = malloc(size + 1);
                memcpy(m_rules[i-1].param, blob, size);
                ((char*)m_rules[i-1].param)[size] = '\0';

                m_rules[i-1].actionId = sqlite3_column_int(stmt, 4);

                text = (char*) sqlite3_column_text(stmt, 3);
                m_rules[i-1].chain = mcpCond_process(text);

                if (NULL == m_rules[i-1].chain) {
                    success = false;
                    mcp_log(LOG_CRIT, "%s:%d equation \"%s\" is invalid",
                           __FUNCTION__, __LINE__, text);
                } else {
                    /* Now that the action and chain have been validated, 
                     * create a timer that will be used to run the periodic 
                     * condition check for this rule. */
                    memset(&sigevt, 0, sizeof(sigevt));
                    sigevt.sigev_notify = SIGEV_THREAD;
                    sigevt.sigev_value.sival_ptr = (void*)&m_rules[i-1];
                    sigevt.sigev_notify_function = mcpRules_exec;

                    errno = 0;
#ifdef __CYGWIN__
                    /* Cygwin doesn't implement the standard MONOTONIC clock for 
                     * timers. */
                    if (0 > timer_create(CLOCK_REALTIME, &sigevt, &m_rules[i-1].timer)) {
#else
                    if (0 > timer_create(CLOCK_MONOTONIC, &sigevt, &m_rules[i-1].timer)) {
#endif
                        success = false;
                        mcp_log(LOG_ERR, "%s:%d error creating timer for rule %d (%d:%s)",
                               __FUNCTION__, __LINE__, i, errno, strerror(errno));
                    }
                } /* else !(NULL == m_rules[i-1].chain) */

                if (true == success) {
                    rc = sqlite3_step(stmt);
                }
            } /* while ((true == success) && (SQLITE_ROW == rc)) */

            if (true == success) {
                if (SQLITE_DONE != rc) {
                    mcp_log(LOG_ERR, "%s:%d error executing statement \"%s\" for row %d of %d (%d:%s)",
                           __FUNCTION__, __LINE__, cmd, i, m_numRules, rc, sqlite3_errstr(rc));
                } else {
                    rc = SQLITE_OK;
                }
            }
        } /* else ! (SQLITE_OK != rc) */

        (void) sqlite3_finalize(stmt);
    } /* if (true == success) */

    if (true == success) {
        /* Prepare the state change statement, the first variable is the new 
         * state, the second is the old state. */
        cmd = "SELECT rule FROM stateRuleLink WHERE state == ? AND rule NOT IN (SELECT rule FROM stateRuleLink WHERE state == ?);";
        rc = sqlite3_prepare_v2(g_mct, cmd, strlen(cmd), &m_stateChangeStmt, NULL);
        if (SQLITE_OK != rc) {
            success = false;
            mcp_log(LOG_ERR, "%s:%d error preparing statement \"%s\" (%d:%s)",
                   __FUNCTION__, __LINE__, cmd, rc, sqlite3_errstr(rc));
        }
    }

    /* Lastly, record the current time for debugging purposes. */
    errno = 0;
    if (0 > clock_gettime(CLOCK_MONOTONIC, &now)) {
        mcp_log(LOG_ERR, "%s:%d error retrieving current time (%d:%s)",
               __FUNCTION__, __LINE__, errno, strerror(errno));
    } else {
        m_startTime = ((uint64_t)now.tv_sec * NSEC_PER_SEC) + now.tv_nsec;
    }

    return success;
} /* bool mcpRules_initialize(void) */

void mcpRules_shutdown(void) {
    for (uint32_t i = 0; i < m_numRules; i++) {
        errno = 0;
        if (0 > timer_delete(m_rules[i].timer)) {
            mcp_log(LOG_ERR, "%s:%d error deleting timer for rule %d (%d:%s)",
                   __FUNCTION__, __LINE__, i, errno, strerror(errno));
        }

        mcpCond_freeChain(m_rules[i].chain);

        if (NULL != m_rules[i].param) {
            free(m_rules[i].param);
        }
    }

    if (NULL != m_rules) {
        free(m_rules);
    }

    (void) sqlite3_finalize(m_stateChangeStmt);
} /* void mcpRules_shutdown(void) */

bool mcpRules_stop(uint32_t curState, uint32_t newState) {
    uint32_t i;
    int32_t rc;
    struct itimerspec zerotime;
    bool success = true;

    rc = pthread_mutex_lock(&m_stateChangeLock);
    if (0 == rc) {
        rc = sqlite3_reset(m_stateChangeStmt);
        if (SQLITE_OK != rc) {
            success = false;
            mcp_log(LOG_ERR, "%s:%d error resetting statement (%d:%s)",
                   __FUNCTION__, __LINE__, rc, sqlite3_errstr(rc));
        }

        /* When stopping a state we need to find the rules for the old state 
         * which are should not be running in the current state.  In this 
         * situation the curState should be the first parameter and the newState 
         * should be the second parameter. */
        if (true == success) {
            rc = sqlite3_bind_int(m_stateChangeStmt, 1, curState);
            if (SQLITE_OK != rc) {
                success = false;
                mcp_log(LOG_ERR, "%s:%d error binding curState %d to param %d (%d:%s)",
                       __FUNCTION__, __LINE__, curState, 1, rc, sqlite3_errstr(rc));
            }
        }

        if (true == success) {
            rc = sqlite3_bind_int(m_stateChangeStmt, 2, newState);
            if (SQLITE_OK != rc) {
                success = false;
                mcp_log(LOG_ERR, "%s:%d error binding newState %d to param %d (%d:%s)",
                       __FUNCTION__, __LINE__, newState, 2, rc, sqlite3_errstr(rc));
            }
        }

        if (true == success) {
            memset(&zerotime, 0, sizeof(struct itimerspec));
            rc = sqlite3_step(m_stateChangeStmt);
            while ((true == success) && (SQLITE_ROW == rc)) {
                /* The stateRuleLink table has a restriction that each rule or 
                 * state index must match an entry in the ruleTable or 
                 * stateTable, so this index does not have to be validated. */
                i = sqlite3_column_int(m_stateChangeStmt, 0);

                mcp_log(LOG_INFO, "state %d: stopping rule %d", curState, i);

                errno = 0;
                if (0 > timer_settime(m_rules[i-1].timer, 0, &zerotime, NULL)) {
                    success = false;
                    mcp_log(LOG_ERR, "%s:%d error stopping timer for rule %d (%d:%s)",
                           __FUNCTION__, __LINE__, i, errno, strerror(errno));
                } else {
                    rc = sqlite3_step(m_stateChangeStmt);
                    if ((SQLITE_ROW != rc) && (SQLITE_DONE != rc)) {
                        success = false;
                        mcp_log(LOG_ERR, "%s:%d error executing prepared statement (%d:%s)",
                               __FUNCTION__, __LINE__, rc, sqlite3_errstr(rc));
                    }
                }
            } /* while ((true == success) && (SQLITE_ROW == rc)) */
        }

        rc = pthread_mutex_unlock(&m_stateChangeLock);
        if (0 != rc) {
            mcp_log(LOG_ERR, "%s:%d error unlocking mutex (%d:%s)\n",
                    __FUNCTION__, __LINE__, rc, strerror(rc));
        }
    } else /* !(0 == rc) */ {
        success = false;
        mcp_log(LOG_ERR, "%s:%d error locking mutex (%d:%s)\n",
                __FUNCTION__, __LINE__, rc, strerror(rc));
    }

    return success;
} /* bool mcpRules_stop(uint32_t curState, uint32_t newState) */

bool mcpRules_start(uint32_t newState, uint32_t curState) {
    uint32_t i;
    int32_t rc;
    bool success = true;

    rc = pthread_mutex_lock(&m_stateChangeLock);
    if (0 == rc) {
        rc = sqlite3_reset(m_stateChangeStmt);
        if (SQLITE_OK != rc) {
            success = false;
            mcp_log(LOG_ERR, "%s:%d error resetting statement (%d:%s)",
                   __FUNCTION__, __LINE__, rc, sqlite3_errstr(rc));
        }

        /* When starting a state we need to find the rules for the new state 
         * which are not running already in the current state.  In this 
         * situation the newState should be the first parameter and the curState 
         * should be the second parameter. */
        if (true == success) {
            rc = sqlite3_bind_int(m_stateChangeStmt, 1, newState);
            if (SQLITE_OK != rc) {
                success = false;
                mcp_log(LOG_ERR, "%s:%d error binding curState %d to param %d (%d:%s)",
                       __FUNCTION__, __LINE__, curState, 1, rc, sqlite3_errstr(rc));
            }
        }

        if (true == success) {
            rc = sqlite3_bind_int(m_stateChangeStmt, 2, curState);
            if (SQLITE_OK != rc) {
                success = false;
                mcp_log(LOG_ERR, "%s:%d error binding newState %d to param %d (%d:%s)",
                       __FUNCTION__, __LINE__, newState, 2, rc, sqlite3_errstr(rc));
            }
        }

        if (true == success) {
            rc = sqlite3_step(m_stateChangeStmt);
            while ((true == success) && (SQLITE_ROW == rc)) {
                /* The stateRuleLink table has a restriction that each rule or 
                 * state index must match an entry in the ruleTable or 
                 * stateTable, so this index does not have to be validated. */
                i = sqlite3_column_int(m_stateChangeStmt, 0);

                mcp_log(LOG_INFO, "state %d: starting rule %d every %d.%03d sec",
                       newState, i, (int)m_rules[i-1].seconds.it_value.tv_sec,
                       (int)m_rules[i-1].seconds.it_value.tv_nsec / NSEC_PER_MSEC);

                errno = 0;
                if (0 > timer_settime(m_rules[i-1].timer, 0, &m_rules[i-1].seconds, NULL)) {
                    success = false;
                    mcp_log(LOG_ERR, "%s:%d error starting timer for rule %d (%d:%s)",
                           __FUNCTION__, __LINE__, i, errno, strerror(errno));
                } else {
                    rc = sqlite3_step(m_stateChangeStmt);
                    if ((SQLITE_ROW != rc) && (SQLITE_DONE != rc)) {
                        success = false;
                        mcp_log(LOG_ERR, "%s:%d error executing prepared statement (%d:%s)",
                               __FUNCTION__, __LINE__, rc, sqlite3_errstr(rc));
                    }
                }
            } /* while ((true == success) && (SQLITE_ROW == rc)) */
        }

        rc = pthread_mutex_unlock(&m_stateChangeLock);
        if (0 != rc) {
            mcp_log(LOG_ERR, "%s:%d error unlocking mutex (%d:%s)\n",
                    __FUNCTION__, __LINE__, rc, strerror(rc));
        }
    } else /* !(0 == rc) */ {
        success = false;
        mcp_log(LOG_ERR, "%s:%d error locking mutex (%d:%s)\n",
                __FUNCTION__, __LINE__, rc, strerror(rc));
    }

    return success;
} /* bool mcpRules_start(uint32_t newState, uint32_t curState) */

void mcpRules_exec(union sigval data) {
    McpRule_t *ruleInfo;
    double result;

    /* Execute rule:
     *  1. locate rule
     *  2. execute condition chain
     *  3. if condition is not 0, execute action
     */

    ruleInfo = data.sival_ptr;
    result = mcpCond_calc(ruleInfo->chain);

#ifdef DEBUG
    {
        struct timespec now;
        uint64_t diff;

        if (0 > clock_gettime(CLOCK_MONOTONIC, &now)) {
            diff = 0;
            syslog(LOG_ERR, "%s:%d error retrieving current time (%d:%s)",
                   __FUNCTION__, __LINE__, errno, strerror(errno));
        } else {
            diff = (((uint64_t)now.tv_sec * NSEC_PER_SEC) + now.tv_nsec) - m_startTime;
        }

        syslog(LOG_DEBUG, "%u.%03u: rule %u = %f",
               (uint32_t)(diff / NSEC_PER_SEC),
               (uint32_t)((diff % NSEC_PER_SEC) / NSEC_PER_MSEC),
               ruleInfo->id, result);
    }
#endif

    if (0 != result) {
        if (true != mcpAction_execute(ruleInfo->actionId, ruleInfo->param, result)) {
            mcp_log(LOG_ERR, "%s:%d error executing action %d (%s, %f) for rule %d",
                   __FUNCTION__, __LINE__, ruleInfo->actionId, (char*)ruleInfo->param, result, ruleInfo->id);
        }
#ifdef DEBUG
        else {
            syslog(LOG_DEBUG, "Executed action %d (%s, %f) for rule %d",
                   ruleInfo->actionId, (char*)ruleInfo->param, result, ruleInfo->id);
        }
#endif
    }
} /* void mcpRules_exec(union sigval data) */

