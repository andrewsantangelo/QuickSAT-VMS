#!/bin/sh
### BEGIN INIT INFO
# Provides:          db_bmp_sensor
# Required-Start:    $local_fs $network mysql
# Required-Stop:     $local_fs $network mysql
# Default-Start:     2 3 4 5
# Default-Stop:      0 1 6
# Short-Description: DB Command Processing Service
# Description:       DB Command Processing Service
### END INIT INFO

NAME=db_bmp_sensor
PROG=bmp_sensor_monitor.py
DAEMON=/opt/qs/bin/$PROG
PIDDIR=/var/run
PIDFILE=$PIDDIR/db_bmp_sensor.pid
DAEMONUSER=root
PATH=/sbin:/bin:/usr/sbin:/usr/bin

test -x $DAEMON || exit 0

. /lib/lsb/init-functions

db_bmp_sensor_start () {
	log_daemon_msg "Starting system $NAME Daemon"
	if [ ! -d $PIDDIR ]; then
		mkdir -p $PIDDIR
		chown $DAEMONUSER:$DAEMONUSER $PIDDIR
	fi
	start-stop-daemon -x $DAEMON -p $PIDFILE --make-pidfile --start --background
	status=$?
	log_end_msg ${status}
}

db_bmp_sensor_stop() {
	log_daemon_msg "Stopping system $NAME Daemon"
	start-stop-daemon -p $PIDFILE --stop --retry 5 || echo -n "...which is not running"
	status=$?
	log_end_msg ${status}
	if [ ! -f $PIDFILE ]; then
        rm -f $PIDFILE
    fi
}

case "$1" in
	start|stop)
		db_bmp_sensor_${1}
		;;
	restart)
		if [ -s $PIDFILE ] && kill -0 $(cat $PIDFILE) >/dev/null 2>&1; then
			db_bmp_sensor_stop
			db_bmp_sensor_start
		fi
		;;
	force-stop)
		db_bmp_sensor_stop
		sudo pkill $PROG || true
		sleep 2
		sudo pkill -9 $PROG || true
		;;
	status)
		status_of_proc -p $PIDFILE "$DAEMON" "system-wide $NAME" && exit 0 || exit $?
		;;
	*)
		echo "Usage: /etc/init.d/db_bmp_sensor {start|stop|force-stop|restart|status}"
		exit 1
		;;
esac

exit 0
