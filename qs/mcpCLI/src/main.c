#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <errno.h>
#include "mcpLib.h"

#ifndef MCP_DB_FILE
#  define MCP_DB_FILE "/etc/mcp/mct.db"
#endif

int main(int __attribute__ ((unused)) argc, char __attribute__ ((unused)) *argv[]) {
    bool done = false;
    char str[1024], *tok, *p, *ruleName, *ruleEq;
    uint32_t id, flightLeg, opMode, mcpState;
    double value;

    if (true == mcpLib_open(MCP_DB_FILE)) {
        while (true != done) {
            printf("> ");
            fgets(str, 1024, stdin);

            tok = strtok_r(str, " ", &p);
            if (NULL != tok) {
                if (0 == strcasecmp("h", tok)) {
                    printf("Usage:\n"
                           "h\n"
                           "        Display this help dialog.\n"
                           "\n"
                           "s\n"
                           "        Display the current MCP state.\n"
                           "\n"
                           "p <param id> [value]\n"
                           "        Display or change the value of the specified parameter.\n"
                           "\n"
                           "r <rule id>\n"
                           "        Display the name and equation for the specified rule.\n"
                           "\n"
                           "q\n"
                           "        Exit this MCP command line interface.\n"
                           "\n"
                           "\n");
                } else if (0 == strcasecmp("s", tok)) {
                    if (true == mcpLib_getAllShmStateData(&flightLeg, &opMode, &mcpState)) {
                        printf("MCP state      = %d\n"
                               "    flight leg = %d\n"
                               "    op mode    = %d\n",
                               mcpState, flightLeg, opMode);
                    }
                } else if (0 == strcasecmp("p", tok)) {
                    tok = strtok_r(NULL, " ", &p);
                    if (NULL != tok) {
                        /* Get the parameter ID */
                        errno = 0;
                        id = strtoul(tok, &tok, 0);
                        if (0 == errno) {
                            /* See if a value is provided. */
                            tok = strtok_r(NULL, " ", &p);
                            if (NULL != tok) {
                                errno = 0;
                                value = strtod(tok, &tok);
                                if (0 == errno) {
                                    if (true == mcpLib_setParam(id, value)) {
                                        printf("parameter %d set to %f\n", id, value);
                                    }
                                } else {
                                    printf("\"%s\" is not a valid parameter value (%d:%s)\n", tok, errno, strerror(errno));
                                }
                            } else {
                                /* No parameter value was provided, get the 
                                 * current value of the specified param ID */
                                if (true == mcpLib_getParam(id, &value)) {
                                    printf("param %d = %f\n", id, value);
                                }
                            }
                        } else {
                            printf("\"%s\" is not a valid parameter ID (%d:%s)\n", tok, errno, strerror(errno));
                        }
                    } else {
                        printf("Usage: p <param id> [value]\n"
                               "        Display or change the value of the specified parameter.\n"
                               "\n");
                    }
                } else if (0 == strcasecmp("r", tok)) {
                    tok = strtok_r(NULL, " ", &p);
                    if (NULL != tok) {
                        /* Get the rule ID */
                        errno = 0;
                        id = strtoul(tok, &tok, 0);
                        if (0 == errno) {
                            if (true == mcpLib_getRule(id, &ruleName, &ruleEq)) {
                                printf("%s: %s\n", ruleName, ruleEq);
                            }
                        } else {
                            printf("\"%s\" is not a valid rule ID (%d:%s)\n", tok, errno, strerror(errno));
                        }
                    } else {
                        printf("Usage: p <param id> [value]\n"
                               "        Display or change the value of the specified parameter.\n"
                               "\n");
                    }
                } else if (0 == strcasecmp("q", tok)) {
                    done = true;
                } else {
                    printf("\"%s\" is not a valid command\n", str);
                }
            } /* if (NULL != tok) */
        } /* while (true != done) */
    } /* if (true == mcpLib_open(MCP_DB_FILE)) */

    return 0;
} /* int main(int argc, char *argv[]) */

