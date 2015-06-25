
#ifndef __MCP_COND_H__
#define __MCP_COND_H__

typedef double (*McpUnaryParseFunc_t)(double val);

typedef double (*McpBinaryParseFunc_t)(double val1, double val2);

typedef struct McpUnaryParseFuncs_s {
    const char * const          str;
    const size_t                numchr;
    const McpUnaryParseFunc_t   func;
} McpUnaryParseFuncs_t;

typedef struct McpBinaryParseFuncs_s {
    const char * const          str;
    const size_t                numchr;
    const McpBinaryParseFunc_t  func;
} McpBinaryParseFuncs_t;

struct McpCalcChain_s;

typedef union McpCalcNode_u {
    McpUnaryParseFuncs_t        *unaryFunc;
    McpBinaryParseFuncs_t       *binaryFunc;
    uint32_t                    paramId;
    double                      value;
    struct McpCalcChain_s       *chain;
} McpCalcNode_t;

typedef enum McpCalcNodeType_e {
    COND_OPTYPE_UNARY_FUNC,
    COND_OPTYPE_BINARY_FUNC,
    COND_OPTYPE_PARAM,
    COND_OPTYPE_CONST,
    COND_OPTYPE_CHAIN,
} McpCalcNodeType_t;

typedef struct McpCalcChain_s {
    struct McpCalcChain_s       *next;
    McpCalcNode_t               node;
    McpCalcNodeType_t           type;
} McpCalcChain_t;

McpCalcChain_t* mcpCond_process(const char *str);
double mcpCond_calc(McpCalcChain_t *chain);
void mcpCond_freeChain(McpCalcChain_t *chain);

#endif /* __MCP_COND_H__ */

