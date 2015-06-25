
#include <stdio.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <ctype.h>
#include <math.h>
#include <string.h>
#include <time.h>
#include <errno.h>
#include <float.h>
#include <syslog.h>
#include "mcp.h"
#include "mcpCond.h"
#include "mcpParam.h"

static McpCalcChain_t* mcpCond_parse(char **str);
static void mcpCond_skipSpace(char **pos);
static McpCalcChain_t* mcpCond_getValue(char **pos);
static bool mcpCond_getUnaryToken(char **pos, uint32_t *op);
static bool mcpCond_getBinaryToken(char **pos, uint32_t *op);

static double mcpCond_not(double val);
static double mcpCond_cmpl(double val);

static double mcpCond_ne(double val1, double val2);
static double mcpCond_eq(double val1, double val2);
static double mcpCond_gt(double val1, double val2);
static double mcpCond_lt(double val1, double val2);
static double mcpCond_gte(double val1, double val2);
static double mcpCond_lte(double val1, double val2);
static double mcpCond_or(double val1, double val2);
static double mcpCond_and(double val1, double val2);
static double mcpCond_mult(double val1, double val2);
static double mcpCond_div(double val1, double val2);
static double mcpCond_sub(double val1, double val2);
static double mcpCond_add(double val1, double val2);
static double mcpCond_mod(double val1, double val2);
static double mcpCond_pow(double val1, double val2);
static double mcpCond_bitxor(double val1, double val2);
static double mcpCond_bitor(double val1, double val2);
static double mcpCond_bitand(double val1, double val2);
static double mcpCond_bitright(double val1, double val2);
static double mcpCond_bitleft(double val1, double val2);

#ifdef DEBUG
static void UNUSED(mcpCond_debug)(McpCalcChain_t *chain);
#define COND_DEBUG(chain) mcpCond_debug((chain))
#else
#define COND_DEBUG(chain)
#endif

static const McpUnaryParseFuncs_t m_unaryOps[] = {
    { "!", 1, mcpCond_not },
    { "~", 1, mcpCond_cmpl },
};
static const McpBinaryParseFuncs_t m_binaryOps[] = {
    { "!=", 2, mcpCond_ne },
    { "==", 2, mcpCond_eq },
    { ">",  1, mcpCond_gt },
    { "<",  1, mcpCond_lt },
    { ">=", 2, mcpCond_gte },
    { "<=", 2, mcpCond_lte },
    { "||", 2, mcpCond_or },
    { "&&", 2, mcpCond_and },
    { "*",  1, mcpCond_mult },
    { "/",  1, mcpCond_div },
    { "-",  1, mcpCond_sub },
    { "+",  1, mcpCond_add },
    { "%",  1, mcpCond_mod },
    { "**", 2, mcpCond_pow },
    { "^",  1, mcpCond_bitxor },
    { "|",  1, mcpCond_bitor },
    { "&",  1, mcpCond_bitand },
    { ">>", 2, mcpCond_bitright },
    { "<<", 2, mcpCond_bitleft },
};
static const char m_opChars[] = "!~=><*/-+%^|&";
static int32_t m_parenLevel = 0;

McpCalcChain_t* mcpCond_process(const char *str)
{
    McpCalcChain_t *chain = NULL;
    char *pos = (char*)str;

    errno = 0;

    chain = mcpCond_parse(&pos);
    if (NULL != chain) {
        /* Ensure that all of the string was used */
        if ('\0' != *pos) {
            mcp_log(LOG_ERR, "%s:%d failed to parse entire expression: ...\"%s\"",
                   __FUNCTION__, __LINE__, pos);
            mcpCond_freeChain(chain);
            chain = NULL;
        }
    } else {
        mcp_log(LOG_ERR, "%s:%d Failed to process expression \"%s\" (%d:%s)",
               __FUNCTION__, __LINE__, pos, errno, strerror(errno));
    }

    return chain;
}

double mcpCond_calc(McpCalcChain_t *chain) {
    double result, val1;

    COND_DEBUG(chain);

    if (COND_OPTYPE_UNARY_FUNC == chain->type) {
        result = chain->node.unaryFunc->func(mcpCond_calc(chain->next));
    } else {
        if (COND_OPTYPE_CHAIN == chain->type) {
            val1 = mcpCond_calc(chain->node.chain);
        } else if (COND_OPTYPE_PARAM == chain->type) {
            (void)mcpParam_get(chain->node.paramId, &val1);
        } else if (COND_OPTYPE_CONST == chain->type) {
            val1 = chain->node.value;
        }

        /* If this is the last node, return val1 as the result, otherwise the 
         * next element must be a binary function. */
        if (NULL == chain->next) {
            result = val1;
        } else {
            COND_DEBUG(chain->next);
            result = chain->next->node.binaryFunc->func(
                val1, mcpCond_calc(chain->next->next));
        }
    }

    return result;
} /* double mcpCond_calc(McpCalcChain_t *chain) */

void mcpCond_freeChain(McpCalcChain_t *chain) {
    if (NULL != chain) {
	    COND_DEBUG(chain);

        /* If the type of this node is another chain, free it now. */
        if (COND_OPTYPE_CHAIN == chain->type) {
            mcpCond_freeChain(chain->node.chain);
            chain->node.chain = NULL;
        }

        /* Now free the rest of the chain */
        mcpCond_freeChain(chain->next);
        chain->next = NULL;

        free(chain);
    }
} /* void mcpCond_freeChain(McpCalcChain_t *chain) */

static void mcpCond_skipSpace(char **pos) {
    while (isspace((int)**pos)) {
        (*pos)++;
    }
} /* static void mcpCond_skipSpace(char **pos) */

static McpCalcChain_t* mcpCond_parse(char **str) {
    uint32_t op;
    McpCalcChain_t *chain, *node;

    node = (McpCalcChain_t*) malloc(sizeof(McpCalcChain_t));

    if (NULL != node) {
        memset(node, 0, sizeof(McpCalcChain_t));

        if (')' == **str) {
            /* If a paren region has ended abruptly, return 0 as the parsed value */
            (*str)++;
            node->type = COND_OPTYPE_CONST;
            node->node.value = 0.0;
            chain = node;

            COND_DEBUG(chain);
        } else if ('\0' != **str) {
            errno = 0;
            chain = mcpCond_getValue(str);

            if (NULL != chain) {
                if (('\0' != **str) && (')' != **str)) {
                    /* Look for a binary function unless this is the end of the string 
                     * or a paren region. */
                    if (true == mcpCond_getBinaryToken(str, &op)) {
                        chain->next = node;
                        node->type = COND_OPTYPE_BINARY_FUNC;
                        node->node.binaryFunc = (McpBinaryParseFuncs_t*)&m_binaryOps[op];

                        COND_DEBUG(node);

                        node->next = mcpCond_parse(str);
                        if (NULL == node->next) {
                            mcpCond_freeChain(chain);
                            chain = NULL;
                        }
                    } else {
                        errno = EINVAL;
                        mcpCond_freeChain(chain);
                        free(node);
                        chain = NULL;
                    }
                } else {
                    /* the allocated node isn't needed, free it now. */
                    free(node);
                }
            } else if (0 == errno) {
                /* Only look for a unary operator if the get value function did not 
                 * detect a parsing error. */
                if (true == mcpCond_getUnaryToken(str, &op)) {
                    chain = node;
                    chain->type = COND_OPTYPE_UNARY_FUNC;
                    chain->node.unaryFunc = (McpUnaryParseFuncs_t*)&m_unaryOps[op];

                    COND_DEBUG(chain);

                    chain->next = mcpCond_parse(str);
                    if (NULL == chain->next) {
                        mcpCond_freeChain(chain);
                        chain = NULL;
                    }
                } else {
                    /* At this point if a number or a unary operator was not 
                     * detected, there is an error in the string. */
                    errno = EINVAL;
		    free(node);
                    chain = NULL;
                }
            } else {
		mcpCond_freeChain(node);
                chain = NULL;
            }
        } else {
            errno = EINVAL;
	    mcpCond_freeChain(node);
            chain = NULL;
        }
    } else {
        errno = ENOMEM;
    }

    return chain;
} /* static McpCalcChain_t* mcpCond_parse(char **str) */

static McpCalcChain_t* mcpCond_getValue(char **pos) {
    uint32_t idx;
    int32_t savedParenLevel;
    char *str;
    McpCalcChain_t *chain;

    chain = (McpCalcChain_t*) malloc(sizeof(McpCalcChain_t));

    if (NULL != chain) {
        memset(chain, 0, sizeof(McpCalcChain_t));

        mcpCond_skipSpace(pos);

        str = *pos;

        /* If the next token is not $ followed by a number, set the error. */
        if ('$' == **pos) {
            /* Increment past the '$' character */
            (*pos)++;
            str = *pos;

            idx = strtoul(*pos, pos, 0);
            if (str == *pos) {
                errno = EINVAL;
                mcpCond_freeChain(chain);
                chain = NULL;
            } else if (true != mcpParam_valid(idx)) {
                errno = ERANGE;
                mcpCond_freeChain(chain);
                chain = NULL;
            } else {
                chain->type = COND_OPTYPE_PARAM;
                chain->node.paramId = idx;
                COND_DEBUG(chain);
            }
        } else if ('(' == **pos) {
            savedParenLevel = m_parenLevel;
            str = *pos;
            /* Increment past the '(' character and increment the paren region. */
            (*pos)++;
            m_parenLevel++;

            /* Create a new chain and parse the contents of the paren region. */
            chain->type = COND_OPTYPE_CHAIN;

            COND_DEBUG(chain);

            chain->node.chain = mcpCond_parse(pos);

            /* The end parenthesis of a paren region is not processed by mcpCond_parse() 
             * so process it now and ensure that the paren level is the same as when 
             * mcpCond_parse was called */

            /* Increment past the ')' character and decrement the paren region. */
            if (')' == **pos) {
                (*pos)++;
                m_parenLevel--;
            }

            if (savedParenLevel != m_parenLevel) {
                /* Force the parse status to be false now, a paren region error may 
                 * not be caught by mcpCond_parse(). */
                errno = EINVAL;
                mcpCond_freeChain(chain);
                chain = NULL;

                /* Move the buffer position back to where it was when we started 
                 * processing this paren region. */
                *pos = str;
            }
        } else {
            /* Try to read a raw number from the string. */
            chain->type = COND_OPTYPE_CONST;
            chain->node.value = strtod(*pos, pos);
            if (str == *pos) {
                /* If no number was able to be parsed, then return NULL but 
                 * don't set an errno.  This indicates that there is no valid 
                 * "number" in the string at this point. */
                errno = 0;
                mcpCond_freeChain(chain);
                chain = NULL;
            }

            COND_DEBUG(chain);
        }
    } else {
        errno = ENOMEM;
    }

    return chain;
} /* static McpCalcChain_t* mcpCond_getValue(char **pos) */

static bool mcpCond_getUnaryToken(char **pos, uint32_t *op) {
    int32_t idx = -1;
    bool status = false;

    mcpCond_skipSpace(pos);

    /* Next token should be an operation. */
    for (uint32_t i = 0; (ARRAY_SIZE(m_unaryOps) > i) && (-1 == idx); i++) {
        /* An operation should only match if it matches exactly and is not 
         * followed by any other op characters. */
        if ((0 == strncmp(*pos, m_unaryOps[i].str, m_unaryOps[i].numchr))
            && (m_unaryOps[i].numchr == strspn(*pos, m_opChars))) {
            (*pos) += m_unaryOps[i].numchr;
            idx = i;
        }
    }

    /* If the operation cannot be found, set the error. */
    if (-1 == idx) {
        errno = ENOSYS;
    } else {
        *op = (uint32_t) idx;
        status = true;
    }

    return status;
} /* static bool mcpCond_getUnaryToken(char **pos, uint32_t *op) */

static bool mcpCond_getBinaryToken(char **pos, uint32_t *op) {
    int32_t idx = -1;
    bool status = false;

    mcpCond_skipSpace(pos);

    /* Next token should be an operation. */
    for (uint32_t i = 0; (ARRAY_SIZE(m_binaryOps) > i) && (-1 == idx); i++) {
        /* An operation should only match if it matches exactly and is not 
         * followed by any other op characters. */
        if ((0 == strncmp(*pos, m_binaryOps[i].str, m_binaryOps[i].numchr))
            && (m_binaryOps[i].numchr == strspn(*pos, m_opChars))) {
            (*pos) += m_binaryOps[i].numchr;
            idx = i;
        }
    }

    /* If the operation cannot be found, set the error. */
    if (-1 == idx) {
        errno = ENOSYS;
    } else {
        *op = (uint32_t) idx;
        status = true;
    }

    return status;
} /* static bool mcpCond_getBinaryToken(char **pos, uint32_t *op) */

static double mcpCond_not(double val) {
    return (!val);
} /* static double mcpCond_not(double val) */

static double mcpCond_cmpl(double val) {
    return (double)~((uint32_t)val);
} /* static double mcpCond_cmpl(double val) */

static double mcpCond_ne(double val1, double val2) {
    bool result = true;

    if (fabs(val1 - val2) < DBL_EPSILON) {
        result = false;
    }

    return (double)result;
} /* static double mcpCond_ne(double val1, double val2) */

static double mcpCond_eq(double val1, double val2) {
    bool result = false;

    if (fabs(val1 - val2) < DBL_EPSILON) {
        result = true;
    }

    return (double)result;
} /* static double mcpCond_eq(double val1, double val2) */

static double mcpCond_gt(double val1, double val2) {
    return (val1 > val2);
} /* static double mcpCond_gt(double val1, double val2) */

static double mcpCond_lt(double val1, double val2) {
    return (val1 < val2);
} /* static double mcpCond_lt(double val1, double val2) */

static double mcpCond_gte(double val1, double val2) {
    bool result = false;

    if ((val1 > val2) || (fabs(val1 - val2) < DBL_EPSILON)) {
        result = true;
    }

    return (double)result;
} /* static double mcpCond_gte(double val1, double val2) */

static double mcpCond_lte(double val1, double val2) {
    bool result = false;

    if ((val1 < val2) || (fabs(val1 - val2) < DBL_EPSILON)) {
        result = true;
    }

    return (double)result;
} /* static double mcpCond_lte(double val1, double val2) */

static double mcpCond_or(double val1, double val2) {
    return (val1 || val2);
} /* static double mcpCond_or(double val1, double val2) */

static double mcpCond_and(double val1, double val2) {
    return (val1 && val2);
} /* static double mcpCond_and(double val1, double val2) */

static double mcpCond_mult(double val1, double val2) {
    return (val1 * val2);
} /* static double mcpCond_mult(double val1, double val2) */

static double mcpCond_div(double val1, double val2) {
    double result;

    if (val2 == 0.0) {
        result = NAN;
    } else {
        result = val1 / val2;
    }

    return result;
} /* static double mcpCond_div(double val1, double val2) */

static double mcpCond_sub(double val1, double val2) {
    return (val1 - val2);
} /* static double mcpCond_sub(double val1, double val2) */

static double mcpCond_add(double val1, double val2) {
    return (val1 + val2);
} /* static double mcpCond_add(double val1, double val2) */

static double mcpCond_mod(double val1, double val2) {
    double result;

    errno = 0;
    result = fmod(val1, val2);
    if (0 != errno) {
        result = NAN;
    }

    return result;
} /* static double mcpCond_mod(double val1, double val2) */

static double mcpCond_pow(double val1, double val2) {
    double result;

    errno = 0;
    result = pow(val1, val2);
    if (0 != errno) {
        result = NAN;
    }

    return result;
} /* static double mcpCond_pow(double val1, double val2) */

static double mcpCond_bitxor(double val1, double val2) {
    return (double)(((uint32_t)val1) ^ ((uint32_t)val2));
} /* static double mcpCond_bitxor(double val1, double val2) */

static double mcpCond_bitor(double val1, double val2) {
    return (double)(((uint32_t)val1) | ((uint32_t)val2));
} /* static double mcpCond_bitor(double val1, double val2) */

static double mcpCond_bitand(double val1, double val2) {
    return (double)(((uint32_t)val1) & ((uint32_t)val2));
} /* static double mcpCond_bitand(double val1, double val2) */

static double mcpCond_bitright(double val1, double val2) {
    return (double)(((uint32_t)val1) >> ((uint32_t)val2));
} /* static double mcpCond_bitright(double val1, double val2) */

static double mcpCond_bitleft(double val1, double val2) {
    return (double)(((uint32_t)val1) << ((uint32_t)val2));
} /* static double mcpCond_bitleft(double val1, double val2) */

#ifdef DEBUG
static void mcpCond_debug(McpCalcChain_t *chain) {
    if (NULL == chain) {
        syslog(LOG_DEBUG, " -> (null)");
    } else {
        switch (chain->type) {
        case COND_OPTYPE_UNARY_FUNC:
            syslog(LOG_DEBUG, " -> COND_OPTYPE_UNARY_FUNC: %s",
                   chain->node.unaryFunc->str);
            break;
        case COND_OPTYPE_BINARY_FUNC:
            syslog(LOG_DEBUG, " -> COND_OPTYPE_BINARY_FUNC: %s",
                   chain->node.binaryFunc->str);
            break;
        case COND_OPTYPE_PARAM: {
            double value;

            (void)mcpParam_get(chain->node.paramId, &value);

            syslog(LOG_DEBUG, " -> COND_OPTYPE_PARAM: %d = %f",
                   chain->node.paramId, value);
            break;
        }
        case COND_OPTYPE_CONST:
            syslog(LOG_DEBUG, " -> COND_OPTYPE_CONST: %f",
                   chain->node.value);
            break;
        case COND_OPTYPE_CHAIN:
            syslog(LOG_DEBUG, " -> COND_OPTYPE_CHAIN: %p",
                   (void*)chain->node.chain);
            break;
        default:
            syslog(LOG_DEBUG, " -> (unknown type 0x08%x = %p)",
                   chain->type, (void*)chain->node.chain);
            break;
        }
    }
} /* static void mcpCond_debug(McpCalcChain_t *chain) */
#endif

