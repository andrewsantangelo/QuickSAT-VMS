
#ifndef __MCP_H__
#define __MCP_H__

#ifndef DAEMON_NAME
#  define DAEMON_NAME   "mcp"
#endif

#ifndef MCP_SHM_NAME
#  define MCP_SHM_NAME  "/" DAEMON_NAME "_shm"
#endif

/* useful for testing, can be overridden during startup by the config file */
#ifndef MCP_DIR
#  define MCP_DIR       "/etc/mcp"
#endif

#define ARRAY_SIZE(ARRAY) (sizeof(ARRAY)/sizeof((ARRAY)[0]))
#define UNUSED(x) __attribute__((unused))(x)

#define NSEC_PER_SEC    1000000000
#define NSEC_PER_MSEC   1000000
#define MSEC_PER_SEC    1000

#define STATE_HALTED 0

bool mcp_start(void);
void mcp_run(void);
void mcp_stop(void);

bool mcp_setFlightLeg(uint32_t flightLeg);
bool mcp_getFlightLeg(uint32_t *flightLeg);
bool mcp_setOpMode(uint32_t opMode);
bool mcp_getOpMode(uint32_t *opMode);
bool mcp_setState(uint32_t state);
bool mcp_getState(uint32_t *state);
bool mcp_vmsConnected(void);

#include <syslog.h>
/* The log levels for this function are the same as for the syslog() function.
 *
 * Here are the default syslog() levels (as defined in syslog.h):
 *  LOG_EMERG    0
 *  LOG_ALERT    1
 *  LOG_CRIT     2
 *  LOG_ERR      3
 *  LOG_WARNING  4
 *  LOG_NOTICE   5
 *  LOG_INFO     6
 *  LOG_DEBUG    7 */
void mcp_log(uint32_t level, const char *format, ...);

#endif /* __MCP_H__ */

