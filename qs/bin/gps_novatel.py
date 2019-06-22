import time
import serial #import pyserial library
import Adafruit_BBIO.UART as UART #import UART Library
from time import sleep
UART.setup("UART1")
ser=serial.Serial('/dev/ttyO1',9600)
ser.bytesize = serial.EIGHTBITS #number of bits per bytes
ser.parity = serial.PARITY_NONE #set parity check: no parity
ser.stopbits = serial.STOPBITS_ONE #number of stop bits

def isfloat(value):
  try:
    float(value)
    return True
  except ValueError:
    return False

class GPS:
        def __init__(self):
                #This sets up variables for useful commands.
                #This set is used to set the rate the GPS reports
                GPGGA_1_sec =  "log GPGGA ontime 1\r\n"     #Get GPGGA data every 1 second
                GPVTG_1_sec=  "log GPVTG ontime 1\r\n"      #Get GPRMC data every 1 second  
                GPGSA_1_sec=  "log GPGSA ontime 1\r\n"      #Get GPGSA data every 1 second  
                GPRMC_1_sec=  "log GPRMC ontime 1\r\n"      #Get GPRMC data every 1 second  

                #Commands for which NMEA Sentences are sent
                sleep(1)
                ser.write(GPGGA_1_sec)
                sleep(1)
                ser.write(GPVTG_1_sec)
                sleep(1)
                ser.write(GPGSA_1_sec)
                sleep(1)
                ser.write(GPRMC_1_sec)
                sleep(1)
                ser.flushInput()
                ser.flushInput()
                ser.flushInput()
                ser.flushInput()
                print "GPS Initialized"
        def read(self):
                ser.flushInput()
                ser.flushInput()
                ser.flushInput()
                ser.flushInput()
                ser.flushInput()
                ser.flushInput()
                while ser.inWaiting()==0:
                        pass
                self.NMEA1=ser.readline()
                while ser.inWaiting()==0:
                        pass
                self.NMEA1=ser.readline()
                self.NMEA2=ser.readline()
                self.NMEA3=ser.readline()
                self.NMEA4=ser.readline()
                while ser.inWaiting()==0:
                        pass
                NMEA1_array=self.NMEA1.split(',')
                NMEA2_array=self.NMEA2.split(',')
                NMEA3_array=self.NMEA3.split(',')
                NMEA4_array=self.NMEA4.split(',')
                self.timeUTC=0
                self.dateUTC=0
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
                        self.timeUTC=NMEA1_array[1][:-7]+':'+NMEA1_array[1][-7:-5]+':'+NMEA1_array[1][-5:-1]
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
                        self.timeUTC=NMEA2_array[1][:-7]+':'+NMEA2_array[1][-7:-5]+':'+NMEA2_array[1][-5:-1]
                        self.latDeg=NMEA2_array[2][:-7]
                        self.latMin=NMEA2_array[2][-7:]
                        self.latHem=NMEA2_array[3]
                        self.lonDeg=NMEA2_array[4][:-7]
                        self.lonMin=NMEA2_array[4][-7:]
                        self.lonHem=NMEA2_array[5]
                        self.fix=NMEA2_array[6]
                        self.altitude=NMEA2_array[9]
                        self.sats=NMEA2_array[7]
                if NMEA3_array[0]=='$GPGGA':
                        self.timeUTC=NMEA3_array[1][:-7]+':'+NMEA3_array[1][-7:-5]+':'+NMEA3_array[1][-5:-1]
                        self.latDeg=NMEA3_array[2][:-7]
                        self.latMin=NMEA3_array[2][-7:]
                        self.latHem=NMEA3_array[3]
                        self.lonDeg=NMEA3_array[4][:-7]
                        self.lonMin=NMEA3_array[4][-7:]
                        self.lonHem=NMEA3_array[5]
                        self.fix=NMEA3_array[6]
                        self.altitude=NMEA3_array[9]
                        self.sats=NMEA3_array[7]
                if NMEA4_array[0]=='$GPGGA':
                        self.timeUTC=NMEA4_array[1][:-7]+':'+NMEA4_array[1][-7:-5]+':'+NMEA4_array[1][-5:-1]
                        self.latDeg=NMEA4_array[2][:-7]
                        self.latMin=NMEA4_array[2][-7:]
                        self.latHem=NMEA4_array[3]
                        self.lonDeg=NMEA4_array[4][:-7]
                        self.lonMin=NMEA4_array[4][-7:]
                        self.lonHem=NMEA4_array[5]
                        self.fix=NMEA4_array[6]
                        self.altitude=NMEA4_array[9]
                        self.sats=NMEA4_array[7]

                if NMEA1_array[0] == '$GPVTG':
                        self.magTrue=NMEA1_array[1]
                        self.knots=NMEA1_array[5]
                if NMEA2_array[0] == '$GPVTG':
                        self.magTrue=NMEA2_array[1]
                        self.knots=NMEA2_array[5]
                if NMEA3_array[0] == '$GPVTG':
                        self.magTrue=NMEA3_array[1]
                        self.knots=NMEA3_array[5]
                if NMEA4_array[0] == '$GPVTG':
                        self.magTrue=NMEA4_array[1]
                        self.knots=NMEA4_array[5]

                if NMEA1_array[0] == '$GPGSA':
                        self.gpsFixType=NMEA1_array[2]
                if NMEA2_array[0] == '$GPGSA':
                        self.gpsFixType=NMEA2_array[2]
                if NMEA3_array[0] == '$GPGSA':
                        self.gpsFixType=NMEA3_array[2]
                if NMEA4_array[0] == '$GPGSA':
                        self.gpsFixType=NMEA4_array[2]

                if NMEA1_array[0] == '$GPRMC':
                        self.dateUTC= '20' + NMEA1_array[9][4:6] + '-' + NMEA1_array[9][2:4] + '-' + NMEA1_array[9][:2]
                if NMEA2_array[0] == '$GPRMC':
                        self.dateUTC= '20' + NMEA2_array[9][4:6] + '-' + NMEA2_array[9][2:4] + '-' + NMEA2_array[9][:2]
                if NMEA3_array[0] == '$GPRMC':
                        self.dateUTC= '20' + NMEA3_array[9][4:6] + '-' + NMEA3_array[9][2:4] + '-' + NMEA3_array[9][:2]
                if NMEA4_array[0] == '$GPRMC':
                        self.dateUTC= '20' + NMEA4_array[9][4:6] + '-' + NMEA4_array[9][2:4] + '-' + NMEA4_array[9][:2]

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
                print 'Date: ',myGPS.dateUTC
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
                elif myGPS.fix=='8':
                     print 'Simulation mode'
                else:
                     print 'No Signal'

                if myGPS.gpsFixType=='1':
                     print 'No Fix'
                elif myGPS.gpsFixType=='2':
                     print '2D Fix'
                elif myGPS.gpsFixType=='3':
                     print '3D Fix'
                else:
                     print 'Error'

                print 'You are Tracking: ',myGPS.sats,' satellites'
                print 'My Latitude: ',myGPS.latDeg, 'Degrees ', myGPS.latMin,' minutes ', myGPS.latHem
                print 'My Longitude: ',myGPS.lonDeg, 'Degrees ', myGPS.lonMin,' minutes ', myGPS.lonHem
                print 'My Speed: ', myGPS.knots
                if isfloat(myGPS.altitude):
                    altitude_ft = float(myGPS.altitude)*3.2808
                else:
                    altitude_ft = 0
                print 'My Altitude: ',myGPS.altitude,' m, and ',altitude_ft,' ft'
                print 'My Heading: ',myGPS.magTrue,' deg '
        time.sleep(2)
        
        