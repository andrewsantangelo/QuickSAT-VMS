import time
import serial #import pyserial library
import Adafruit_BBIO.UART as UART #import UART Library
import serial
import Adafruit_BBIO.UART as UART
from time import sleep
UART.setup("UART1")
ser=serial.Serial('/dev/ttyO1',9600)
class GPS:
        def __init__(self):
                #This sets up variables for useful commands.
                #This set is used to set the rate the GPS reports
                UPDATE_10_sec=  "$PMTK220,10000*2F\r\n" #Update Every 10 Seconds
                UPDATE_5_sec=  "$PMTK220,5000*1B\r\n"   #Update Every 5 Seconds  
                UPDATE_1_sec=  "$PMTK220,1000*1F\r\n"   #Update Every One Second
                UPDATE_200_msec=  "$PMTK220,200*2C\r\n" #Update Every 200 Milliseconds
                #This set is used to set the rate the GPS takes measurements
                MEAS_10_sec = "$PMTK300,10000,0,0,0,0*2C\r\n" #Measure every 10 seconds
                MEAS_5_sec = "$PMTK300,5000,0,0,0,0*18\r\n"   #Measure every 5 seconds
                MEAS_1_sec = "$PMTK300,1000,0,0,0,0*1C\r\n"   #Measure once a second
                MEAS_200_msec= "$PMTK300,200,0,0,0,0*2F\r\n"  #Meaure 5 times a second
                #Set the Baud Rate of GPS
                BAUD_57600 = "$PMTK251,57600*2C\r\n"          #Set Baud Rate at 57600
                BAUD_9600 ="$PMTK251,9600*17\r\n"             #Set 9600 Baud Rate
                #Commands for which NMEA Sentences are sent
                ser.write(BAUD_9600)
                sleep(1)
                ser.baudrate=9600
                GPRMC_ONLY= "$PMTK314,0,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0*29\r\n" #Send only the GPRMC Sentence
                GPRMC_GPGGA="$PMTK314,0,1,0,1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0*28\r\n"#Send GPRMC AND GPGGA Sentences
                SEND_ALL ="$PMTK314,1,1,1,1,1,1,0,0,0,0,0,0,0,0,0,0,0,0,0*28\r\n" #Send All Sentences
                SEND_NOTHING="$PMTK314,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0*28\r\n" #Send Nothing
                ser.write(UPDATE_200_msec)
                sleep(1)
                ser.write(MEAS_200_msec)
                sleep(1)
                ser.write(GPRMC_GPGGA)
                sleep(1)
                ser.flushInput()
                ser.flushInput()
                print "GPS Initialized"
        def read(self):
                ser.flushInput()
                ser.flushInput()
                while ser.inWaiting()==0:
                        pass
                self.NMEA1=ser.readline()
                while ser.inWaiting()==0:
                        pass
                self.NMEA2=ser.readline()
                while ser.inWaiting()==0:
                        pass
                self.NMEA3=ser.readline()
                while ser.inWaiting()==0:
                        pass
                self.NMEA4=ser.readline()
                NMEA1_array=self.NMEA1.split(',')
                NMEA2_array=self.NMEA2.split(',')
                NMEA3_array=self.NMEA3.split(',')
                NMEA4_array=self.NMEA4.split(',')
                self.timeUTC=0
                self.latDeg=0
                self.latMin=0
                self.latHem=0
                self.lonDeg=0
                self.lonMin=0
                self.lonHem=0
                self.knots=0
                self.fix=0
                self.altitude=0
                self.sats=0 
                self.magTrue=0
                self.gpsFixType=0
                if NMEA1_array[0]=='$GPGGA':
                        self.timeUTC=NMEA1_array[1][:-8]+':'+NMEA1_array[1][-8:-6]+':'+NMEA1_array[1][-6:-4]
                        self.latDeg=NMEA1_array[2][:-7]
                        self.latMin=NMEA1_array[2][-7:]
                        self.latHem=NMEA1_array[3]
                        self.lonDeg=NMEA1_array[4][:-7]
                        self.lonMin=NMEA1_array[4][-7:]
                        self.lonHem=NMEA1_array[5]
                        self.fix=NMEA1_array[6]
                        self.altitude=NMEA1_array[9]
                        self.sats=NMEA1_array[7]
                if NMEA2_array[0]=='$GPGGA':
                        self.timeUTC=NMEA2_array[1][:-8]+':'+NMEA2_array[1][-8:-6]+':'+NMEA2_array[1][-6:-4]
                        self.latDeg=NMEA2_array[2][:-7]
                        self.latMin=NMEA2_array[2][-7:]
                        self.latHem=NMEA2_array[3]
                        self.lonDeg=NMEA2_array[4][:-7]
                        self.lonMin=NMEA2_array[4][-7:]
                        self.lonHem=NMEA2_array[5]
                        self.fix=NMEA2_array[6]
                        self.altitude=NMEA2_array[9]
                        self.sats=NMEA2_array[7]
                if NMEA1_array[0] == '$GPVTG':
                        self.magTrue=NMEA1_array[1]
                        self.knots=NMEA1_array[5]
                if NMEA2_array[0] == '$GPVTG':
                        self.magTrue=NMEA2_array[1]
                        self.knots=NMEA2_array[5]
                if NMEA1_array[0] == '$GPGSA':
                        self.gpsFixType=NMEA1_array[2]
                if NMEA2_array[0] == '$GPGSA':
                        self.gpsFixType=NMEA2_array[2]


if __name__ == '__main__':

     myGPS=GPS()
     while(1):
        myGPS.read()
        print myGPS.NMEA1
        print myGPS.NMEA2
        print myGPS.NMEA3
        print myGPS.NMEA4
        if myGPS.fix!=0:
                print 'Universal Time: ',myGPS.timeUTC
                if myGPS.fix=='1':
                     print 'GPS Fix (SPS)'
                elif myGPS.fix=='2':
                     print 'DGPS fix'
                elif myGPS.fix=='3':
                     print 'PPS fix'
                elif myGPS.fix=='4':
                     print 'Real Time Kinematic'
                elif myGPS.fix=='5':
                     print 'Float RTK'
                elif myGPS.fix=='6':
                     print 'estimated (dead reckoning)'
                elif myGPS.fix=='7':
                     print 'Manual input mode'
                else:
                     print 'Simulation mode'

                if myGPS.gpsFixType=='1':
                     print 'No Fix'
                elif myGPS.gpsFixType=='2':
                     print '2D Fix'
                else:
                     print '3D Fix'
                print 'You are Tracking: ',myGPS.sats,' satellites'
                print 'My Latitude: ',myGPS.latDeg, 'Degrees ', myGPS.latMin,' minutes ', myGPS.latHem
                print 'My Longitude: ',myGPS.lonDeg, 'Degrees ', myGPS.lonMin,' minutes ', myGPS.lonHem
                print 'My Speed: ', myGPS.knots
                altitude_ft = float(myGPS.altitude)*3.2808
                print 'My Altitude: ',myGPS.altitude,' m, and ',altitude_ft,' ft'
                print 'My Heading: ',myGPS.magTrue,' deg '
        time.sleep(2)

