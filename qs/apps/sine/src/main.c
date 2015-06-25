#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>

#include <unistd.h>
#include <getopt.h>

#include <mysql.h>

typedef struct db_server_info {
	char *address;
	uint16_t port;
	char *username;
	char *password;
    char *param_id;
} db_server_info_t;

typedef struct db_conn_info {
	MYSQL *mysql;
	MYSQL_STMT *param_update_stmt;
} db_conn_info_t;

double incr_val(double val);
void db_close(db_conn_info_t *conn);
void db_open(db_conn_info_t *conn, db_server_info_t *db_info);
void db_update(db_conn_info_t *conn, char *param, double val);

double incr_val(double val) {
    const double step = 10.0;
	/* Increment val, unless it is max value */
	if (val < 180.0) {
		val += step;
	}
	else {
		val = 0;
	}
	return val;
}

void db_close(db_conn_info_t *conn) {
	if (NULL != conn) {
		if (NULL != conn->mysql) {
			if (NULL != conn->param_update_stmt) {
				mysql_stmt_close(conn->param_update_stmt);
			}
			mysql_close(conn->mysql);
		}
		conn->mysql = NULL;
		conn->param_update_stmt = NULL;
	}
}

void db_open(db_conn_info_t *conn, db_server_info_t *db_info) {
	bool success = true;
	MYSQL *ret;

	/* Initialize MySQL and connect to the remote DB. */
	conn->mysql = mysql_init(NULL);
	if (NULL == conn->mysql) {
		printf("ERROR: insufficent memory to initialize MySQL library\n");
		success = false;
	}

	if (success) {
#if 0
		/* Secure the database connection */
#define SERVER_SSL_DIR "/etc/mcp/certs/"
#define SERVER_SSL_CLIENT_KEY SERVER_SSL_DIR "client-key.pem"
#define SERVER_SSL_CLIENT_CERT SERVER_SSL_DIR "client-cert.pem"
#define SERVER_SSL_CLIENT_CA SERVER_SSL_DIR "ca-cert.pem"
		mysql_ssl_set(conn->mysql, NULL, NULL,
				SERVER_SSL_CLIENT_CA, NULL, NULL);
#endif

#define DB_NAME "stepSATdb_Flight"
		ret = mysql_real_connect(conn->mysql, db_info->address,
				db_info->username, db_info->password, DB_NAME,
				db_info->port, NULL, 0);
		if (ret != conn->mysql) {
			printf("ERROR: unable to connect to MySQL server @%s:%u (%s)\n",
					db_info->address, db_info->port,
					mysql_error(conn->mysql));
			success = false;
		}
	}

	/* Initialize the prepared statements */
	if (success) {
		conn->param_update_stmt = mysql_stmt_init(conn->mysql);
		if (NULL == conn->param_update_stmt) {
			printf("ERROR: unable to initialize to MySQL prepared statement (%s)\n",
					mysql_error(conn->mysql));
			success = false;
		}
	}

	if (success) {
#define PARAM_UPDATE_STMT_STR "INSERT INTO `stepSATdb_Flight`.`Flight_Data` (`parameter_id`, `time_stamp`, `parameter_value`, `Recording_Sessions_recording_session_id` ) VALUES (?, NOW(), ?, (SELECT MAX(`recording_session_id`) FROM `stepSATdb_Flight`.`Recording_Sessions`))"
		if (0 != mysql_stmt_prepare(conn->param_update_stmt,
					PARAM_UPDATE_STMT_STR, strlen(PARAM_UPDATE_STMT_STR))) {
			printf("ERROR: unable to prepare update parameter MySQL statement (%s)\n",
					mysql_error(conn->mysql));
			success = false;
		}
	}

	/* If any of these initialization steps failed, deallocate the
	 * resources and close the connection */
	if (!success) {
		db_close(conn);
	}
}

void db_update(db_conn_info_t *conn, char *param, double val) {
	MYSQL_BIND bind[2];

	if (NULL != conn->param_update_stmt) {
		memset(bind, 0, sizeof(bind));

        bind[0].buffer_type = MYSQL_TYPE_STRING;
        bind[0].buffer = param;
        bind[0].buffer_length = strlen(param);
		bind[0].is_null = 0;
		bind[0].length = 0;

		bind[1].buffer_type = MYSQL_TYPE_DOUBLE;
		bind[1].buffer = (char*)&val;
		bind[1].is_null = 0;
		bind[1].length = 0;

		if (0 != mysql_stmt_bind_param(conn->param_update_stmt, bind)) {
			printf("ERROR: unable to bind (%s, %f) values to update parameter MySQL statement (%s)\n",
					param, val, mysql_error(conn->mysql));
		} else {
			if (0 != mysql_stmt_execute(conn->param_update_stmt)) {
				printf("ERROR: unable to execute update parameter MySQL statement for params (%s, %f) (%s)\n",
						param, val, mysql_error(conn->mysql));
			}
		}
	}
}

int main(int argc, char *argv[]) {
	double x = 0.0;
	double val = 0.0;

	db_conn_info_t db_conn;
	db_server_info_t db_info;
	int32_t c;

	static struct option long_options[] = {
		{ "server",   optional_argument, NULL, 's' },
		{ "port",     optional_argument, NULL, 'p' },
		{ "username", optional_argument, NULL, 'U' },
		{ "password", optional_argument, NULL, 'P' },
		{ "param_id", optional_argument, NULL, 'i' },
		{ 0,          0,                 NULL,  0 }
	};
	int32_t option_index = 0;

	/* Set the default DB connection values
	 * TODO: having plain text username/password in the program is not
	 *       a good idea. */
	db_info.address  = "localhost";
	db_info.port     = 3306; /* default MySQL listening port */
	db_info.username = "root";
	db_info.password = "root";
	db_info.param_id = "3";

	/* Initialize the DB connection structure */
	db_conn.mysql = NULL;
	db_conn.param_update_stmt = NULL;

	/* Process the command line arguments:
	 * --server=<ip-addr> */
	c = getopt_long(argc, argv, "s:up::", long_options, &option_index);
	while (-1 != c) {
		switch (c) {
		case 0:
			/* do nothing, arg parsed already */
			break;
		case 's':
			db_info.address = optarg;
			break;
		case 'p':
			db_info.port = (uint16_t)strtoul(optarg, NULL, 10);
			break;
		case 'U':
			db_info.username = optarg;
			break;
		case 'P':
			db_info.password = optarg;
			break;
		case 'i':
			db_info.param_id = optarg;
			break;
		case '?':
			/* getopt_long already printed an error message */
			break;
		default:
			abort();
		}

		/* Get the next option */
		option_index = 0;
		c = getopt_long(argc, argv, ":spUPi:",
				long_options, &option_index);
	}

	/* Connect to the database */
	db_open(&db_conn, &db_info);

	for (;;) {
		/* calculate the next sine value */
		val = sin(x);
		printf("sin(%f) = %f\n", x, val);

		db_update(&db_conn, db_info.param_id, val);

		x = incr_val(x);
		sleep(1);
	}

	db_close(&db_conn);

	return 0;
}
