
#include <stdint.h>
#include <stdbool.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <stdarg.h>
#include "mcp.h"
#include "mcpParam.h"
#include "mcpAction.h"
#include "mcpDomCtrl.h"

/* tables relevant to this module:
 *  CREATE TABLE mcpActionEnum (
 *      id          INTEGER PRIMARY KEY,
 *      name        TEXT
 *  );
 *
 *  INSERT INTO mcpActionEnum VALUES(1,'flight_leg');
 *  INSERT INTO mcpActionEnum VALUES(2,'op_mode');
 *  INSERT INTO mcpActionEnum VALUES(3,'mcp_state');
 *  INSERT INTO mcpActionEnum VALUES(4,'reset_partition');
 *  INSERT INTO mcpActionEnum VALUES(5,'pause_partition');
 *  INSERT INTO mcpActionEnum VALUES(6,'unpause_partition');
 *  INSERT INTO mcpActionEnum VALUES(7,'log_message');
 *  INSERT INTO mcpActionEnum VALUES(8,'set_param');
 *  INSERT INTO mcpActionEnum VALUES(9,'report_status');
 *  INSERT INTO mcpActionEnum VALUES(10,'partition_status');
 */

/* This is an enumeration to more descriptively translate the action IDs to the 
 * action they represent. */
typedef enum McpActionType_e {
    ACTION_SET_FLIGHT_LEG       = 1,
    ACTION_SET_OP_MODE          = 2,
    ACTION_SET_MCP_STATE        = 3,
    ACTION_RESET_PARTITION      = 4,
    ACTION_PAUSE_PARTITION      = 5,
    ACTION_UNPAUSE_PARTITION    = 6,
    ACTION_LOG_MESSAGE          = 7,
    ACTION_SET_PARAM            = 8,
    ACTION_DOMAIN_STATUS        = 9,
} McpActionType_t;

/* The values passed into this function are assumed to be from the MCT tables.  
 * The mcpActionEnum table provides the assurance that the entries of linked 
 * tables are valid.  Because of that we don't have to perform separate 
 * validation of the action. */
bool mcpAction_execute(uint32_t action, char *param, double result) {
    bool success;
    uint32_t intParam;

    switch (action) {
    case ACTION_SET_FLIGHT_LEG:
        intParam = strtoul(param, NULL, 0);
        success = mcp_setFlightLeg(intParam);
        break;
    case ACTION_SET_OP_MODE:
        intParam = strtoul(param, NULL, 0);
        success = mcp_setOpMode(intParam);
        break;
    case ACTION_SET_MCP_STATE:
        intParam = strtoul(param, NULL, 0);
        success = mcp_setState(intParam);
        break;
    case ACTION_RESET_PARTITION:
        intParam = strtoul(param, NULL, 0);
        success = mcpDC_setDomState(intParam, DOM_STATE_RESET);
        break;
    case ACTION_PAUSE_PARTITION:
        intParam = strtoul(param, NULL, 0);
        success = mcpDC_setDomState(intParam, DOM_STATE_PAUSED);
        break;
    case ACTION_UNPAUSE_PARTITION:
        intParam = strtoul(param, NULL, 0);
        success = mcpDC_setDomState(intParam, DOM_STATE_ON);
        break;
    case ACTION_LOG_MESSAGE:
        mcp_log(LOG_INFO, "LOG_MESSAGE \"%s\"", param);
        success = true;
        break;
    case ACTION_SET_PARAM:
        intParam = strtoul(param, NULL, 0);
        success = mcpParam_set(intParam, result);
        break;
    case ACTION_DOMAIN_STATUS:
        success = mcpDC_checkDomState();
        break;
    default:
        success = false;
        mcp_log(LOG_ERR, "%s:%d Invalid action %d (%s)",
                __FUNCTION__, __LINE__, action, param);
        break;
    } /* switch (action) */

    return success;
} /* bool mcpAction_execute(uint32_t action, char *param, double result) */

