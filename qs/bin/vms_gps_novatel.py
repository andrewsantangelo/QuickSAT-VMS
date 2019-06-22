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
                GPGGA_1_sec=  "log GPGGA ontime 1\r\n"     #Get GPGGA data every 1 second
                GPVTG_1_sec=  "log GPVTG ontime 1\r\n"      #Get GPRMC data every 1 second  
                GPGSA_1_sec=  "log GPGSA ontime 1\r\n"      #Get GPGSA data every 1 second  
                GPRMC_1_sec=  "log GPRMC ontime 1\r\n"      #Get GPRMC data every 1 second  
                GPGSV_1_sec=  "log GPGSV ontime 1\r\n"      #Get GPGSV data every 1 second  

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
                ser.write(GPGSV_1_sec)
                sleep(1)
                ser.flushInput()
                ser.flushInput()
                ser.flushInput()
                ser.flushInput()
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
                self.NMEA5=ser.readline()
                self.NMEA6=ser.readline()
                self.NMEA7=ser.readline()
                self.NMEA8=ser.readline()
                while ser.inWaiting()==0:
                        pass
                NMEA1_array=self.NMEA1.split(',')
                NMEA2_array=self.NMEA2.split(',')
                NMEA3_array=self.NMEA3.split(',')
                NMEA4_array=self.NMEA4.split(',')
                NMEA5_array=self.NMEA5.split(',')
                NMEA6_array=self.NMEA6.split(',')
                NMEA7_array=self.NMEA7.split(',')
                NMEA8_array=self.NMEA8.split(',')
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
                self.SentenceNumber=0
                self.NumberSatellitesInView=0
                self.numDataSentences=0
                self.numDataSentences=0
                self.SatellitesInTracked=[0 for x in range(16)]
                self.SatellitesInView=[]
                self.PDOP=0
                self.HDOP=0
                self.VDOP=0
                # Collect the NMEA parameters and store the individual elements
                print 'NMEA 1: ',NMEA1_array
                print 'NMEA 2: ',NMEA2_array
                print 'NMEA 3: ',NMEA3_array
                print 'NMEA 4: ',NMEA4_array
                print 'NMEA 5: ',NMEA5_array
                print 'NMEA 6: ',NMEA6_array
                print 'NMEA 7: ',NMEA7_array
                print 'NMEA 8: ',NMEA8_array

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
                if NMEA5_array[0]=='$GPGGA':
                        self.timeUTC=NMEA5_array[1][:-7]+':'+NMEA5_array[1][-7:-5]+':'+NMEA5_array[1][-5:-1]
                        self.latDeg=NMEA5_array[2][:-7]
                        self.latMin=NMEA5_array[2][-7:]
                        self.latHem=NMEA5_array[3]
                        self.lonDeg=NMEA5_array[4][:-7]
                        self.lonMin=NMEA5_array[4][-7:]
                        self.lonHem=NMEA5_array[5]
                        self.fix=NMEA5_array[6]
                        self.altitude=NMEA5_array[9]
                        self.sats=NMEA5_array[7]
                if NMEA6_array[0]=='$GPGGA':
                        self.timeUTC=NMEA6_array[1][:-7]+':'+NMEA6_array[1][-7:-5]+':'+NMEA6_array[1][-5:-1]
                        self.latDeg=NMEA6_array[2][:-7]
                        self.latMin=NMEA6_array[2][-7:]
                        self.latHem=NMEA6_array[3]
                        self.lonDeg=NMEA6_array[4][:-7]
                        self.lonMin=NMEA6_array[4][-7:]
                        self.lonHem=NMEA6_array[5]
                        self.fix=NMEA6_array[6]
                        self.altitude=NMEA6_array[9]
                        self.sats=NMEA6_array[7]
                if NMEA7_array[0]=='$GPGGA':
                        self.timeUTC=NMEA7_array[1][:-7]+':'+NMEA7_array[1][-7:-5]+':'+NMEA7_array[1][-5:-1]
                        self.latDeg=NMEA7_array[2][:-7]
                        self.latMin=NMEA7_array[2][-7:]
                        self.latHem=NMEA7_array[3]
                        self.lonDeg=NMEA7_array[4][:-7]
                        self.lonMin=NMEA7_array[4][-7:]
                        self.lonHem=NMEA7_array[5]
                        self.fix=NMEA7_array[6]
                        self.altitude=NMEA7_array[9]
                        self.sats=NMEA7_array[7]
                if NMEA8_array[0]=='$GPGGA':
                        self.timeUTC=NMEA8_array[1][:-7]+':'+NMEA8_array[1][-7:-5]+':'+NMEA8_array[1][-5:-1]
                        self.latDeg=NMEA8_array[2][:-7]
                        self.latMin=NMEA8_array[2][-7:]
                        self.latHem=NMEA8_array[3]
                        self.lonDeg=NMEA8_array[4][:-7]
                        self.lonMin=NMEA8_array[4][-7:]
                        self.lonHem=NMEA8_array[5]
                        self.fix=NMEA8_array[6]
                        self.altitude=NMEA8_array[9]
                        self.sats=NMEA8_array[7]

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
                if NMEA5_array[0] == '$GPVTG':
                        self.magTrue=NMEA5_array[1]
                        self.knots=NMEA5_array[5]
                if NMEA6_array[0] == '$GPVTG':
                        self.magTrue=NMEA6_array[1]
                        self.knots=NMEA6_array[5]
                if NMEA7_array[0] == '$GPVTG':
                        self.magTrue=NMEA7_array[1]
                        self.knots=NMEA7_array[5]
                if NMEA8_array[0] == '$GPVTG':
                        self.magTrue=NMEA8_array[1]
                        self.knots=NMEA8_array[5]

                if NMEA1_array[0] == '$GPGSA':
                        self.gpsFixType=NMEA1_array[2]
                        self.SatellitesInTracked=[NMEA1_array[3+x] for x in range(12)]
                        self.PDOP=NMEA1_array[15]
                        self.HDOP=NMEA1_array[16]
                        self.VDOP=NMEA1_array[17][:NMEA1_array[17].find('*')]
                if NMEA2_array[0] == '$GPGSA':
                        self.gpsFixType=NMEA2_array[2]
                        self.SatellitesInTracked=[NMEA2_array[3+x] for x in range(12)]
                        self.PDOP=NMEA2_array[15]
                        self.HDOP=NMEA2_array[16]
                        self.VDOP=NMEA2_array[17][:NMEA2_array[17].find('*')]
                if NMEA3_array[0] == '$GPGSA':
                        self.gpsFixType=NMEA3_array[2]
                        self.SatellitesInTracked=[NMEA3_array[3+x] for x in range(12)]
                        self.PDOP=NMEA3_array[15]
                        self.HDOP=NMEA3_array[16]
                        self.VDOP=NMEA3_array[17][:NMEA3_array[17].find('*')]
                if NMEA4_array[0] == '$GPGSA':
                        self.gpsFixType=NMEA4_array[2]
                        self.SatellitesInTracked=[NMEA4_array[3+x] for x in range(12)]
                        self.PDOP=NMEA4_array[15]
                        self.HDOP=NMEA4_array[16]
                        self.VDOP=NMEA4_array[17][:NMEA4_array[17].find('*')]
                if NMEA5_array[0] == '$GPGSA':
                        self.gpsFixType=NMEA5_array[2]
                        self.SatellitesInTracked=[NMEA5_array[3+x] for x in range(12)]
                        self.PDOP=NMEA5_array[15]
                        self.HDOP=NMEA5_array[16]
                        self.VDOP=NMEA5_array[17][:NMEA5_array[17].find('*')]
                if NMEA6_array[0] == '$GPGSA':
                        self.gpsFixType=NMEA6_array[2]
                        self.SatellitesInTracked=[NMEA6_array[3+x] for x in range(12)]
                        self.PDOP=NMEA6_array[15]
                        self.HDOP=NMEA6_array[16]
                        self.VDOP=NMEA6_array[17][:NMEA6_array[17].find('*')]
                if NMEA7_array[0] == '$GPGSA':
                        self.gpsFixType=NMEA7_array[2]
                        self.SatellitesInTracked=[NMEA7_array[3+x] for x in range(12)]
                        self.PDOP=NMEA7_array[15]
                        self.HDOP=NMEA7_array[16]
                        self.VDOP=NMEA7_array[17][:NMEA7_array[17].find('*')]
                if NMEA8_array[0] == '$GPGSA':
                        self.gpsFixType=NMEA8_array[2]
                        self.SatellitesInTracked=[NMEA8_array[3+x] for x in range(12)]
                        self.PDOP=NMEA8_array[15]
                        self.HDOP=NMEA8_array[16]
                        self.VDOP=NMEA8_array[17][:NMEA8_array[17].find('*')]

                if NMEA1_array[0] == '$GPGSV':
                        self.SentenceNumber=NMEA1_array[2]
                        #print 'finding *'
                        #print NMEA1_array[3].find('*')
                        #print NMEA1_array[3][:NMEA1_array[3].find('*')]
                        if NMEA1_array[3].find('*') == -1:
                            self.NumberSatellitesInView=NMEA1_array[3]
                        else:
                            self.NumberSatellitesInView=NMEA1_array[3][:NMEA1_array[3].find('*')]
                        self.numDataSentences=NMEA1_array[1]
                        #print 'Number satellites in view set'
                        #print NMEA1_array[3][:NMEA1_array[3].find('*')], self.NumberSatellitesInView
                        num_sentences = int(self.numDataSentences)
                        sentence_num = int(self.SentenceNumber)
                        num_satellites = int(self.NumberSatellitesInView)
                        if sentence_num < num_sentences:
                             self.SatellitesInView.extend([NMEA1_array[4+x] for x in range(15)])
                             last_value = NMEA1_array[19][:NMEA1_array[19].find('*')]
                             #print last_value
                             self.SatellitesInView.extend([last_value])                             
                        elif sentence_num == num_sentences:
                             num_satellites_sentence = num_satellites - (4*(sentence_num-1))
                             #print sentence_num
                             #print num_satellites
                             #print ' check '
                             #print NMEA1_array[((4*num_satellites_sentence)+3)].find('*')
                             self.SatellitesInView.extend([NMEA1_array[4+x] for x in range((4*num_satellites_sentence)-1)])
                             self.SatellitesInView.extend([NMEA1_array[(4*num_satellites_sentence+3)][:NMEA1_array[(4*num_satellites_sentence+3)].find('*')]])                             
                if NMEA2_array[0] == '$GPGSV':
                        self.SentenceNumber=NMEA2_array[2]
                        #print 'finding *'
                        #print NMEA2_array[3].find('*')
                        #print NMEA2_array[3][:NMEA2_array[3].find('*')]
                        if NMEA2_array[3].find('*') == -1:
                           self.NumberSatellitesInView=NMEA2_array[3]
                        else:
                           self.NumberSatellitesInView=NMEA2_array[3][:NMEA2_array[3].find('*')]
                        self.numDataSentences=NMEA2_array[1]
                        #print 'Number satellites in view set'
                        #print NMEA2_array[3][:NMEA2_array[3].find('*')], self.NumberSatellitesInView
                        num_sentences = int(self.numDataSentences)
                        sentence_num = int(self.SentenceNumber)
                        num_satellites = int(self.NumberSatellitesInView)
                        if sentence_num < num_sentences:
                             self.SatellitesInView.extend([NMEA2_array[4+x] for x in range(15)])
                             last_value = NMEA2_array[19][:NMEA2_array[19].find('*')]
                             #print last_value
                             self.SatellitesInView.extend([last_value])                             
                        elif sentence_num == num_sentences:
                             num_satellites_sentence = num_satellites - (4*(sentence_num-1))
                             #print sentence_num
                             #print num_satellites
                             #print ' check '
                             #print NMEA2_array[((4*num_satellites_sentence)+3)].find('*')
                             #self.SatellitesInView.extend([NMEA2_array[4+x] for x in range((4*num_satellites_sentence)-1)])
                             #self.SatellitesInView.extend([NMEA2_array[(4*num_satellites_sentence+3)][:NMEA2_array[(4*num_satellites_sentence+3)].find('*')]])                             
                if NMEA3_array[0] == '$GPGSV':
                        self.SentenceNumber=NMEA3_array[2]
                        #print 'finding *'
                        #print NMEA3_array[3].find('*')
                        #print NMEA3_array[3][:NMEA3_array[3].find('*')]
                        if NMEA3_array[3].find('*') == -1:
                           self.NumberSatellitesInView=NMEA3_array[3]
                        else:
                           self.NumberSatellitesInView=NMEA3_array[3][:NMEA3_array[3].find('*')]
                        self.numDataSentences=NMEA3_array[1]
                        #print 'Number satellites in view set'
                        #print NMEA3_array[3][:NMEA3_array[3].find('*')], self.NumberSatellitesInView
                        num_sentences = int(self.numDataSentences)
                        sentence_num = int(self.SentenceNumber)
                        num_satellites = int(self.NumberSatellitesInView)
                        if sentence_num < num_sentences:
                             self.SatellitesInView.extend([NMEA3_array[4+x] for x in range(15)])
                             last_value = NMEA3_array[19][:NMEA3_array[19].find('*')]
                             #print last_value
                             self.SatellitesInView.extend([last_value])                             
                        elif sentence_num == num_sentences:
                             num_satellites_sentence = num_satellites - (4*(sentence_num-1))
                             #print sentence_num
                             #print num_satellites
                             #print ' check '
                             #print NMEA3_array[((4*num_satellites_sentence+3))].find('*')
                             self.SatellitesInView.extend([NMEA3_array[4+x] for x in range((4*num_satellites_sentence)-1)])
                             self.SatellitesInView.extend([NMEA3_array[(4*num_satellites_sentence+3)][:NMEA3_array[(4*num_satellites_sentence+3)].find('*')]])                             
                if NMEA4_array[0] == '$GPGSV':
                        self.SentenceNumber=NMEA4_array[2]
                        #print 'finding *'
                        #print NMEA4_array[3].find('*')
                        #print NMEA4_array[3][:NMEA4_array[3].find('*')]
                        if NMEA4_array[3].find('*') == -1:
                            self.NumberSatellitesInView=NMEA4_array[3]
                        else:
                            self.NumberSatellitesInView=NMEA4_array[3][:NMEA4_array[3].find('*')]
                        #print 'Number satellites in view set'
                        #print NMEA4_array[3][:NMEA4_array[3].find('*')], self.NumberSatellitesInView
                        self.numDataSentences=NMEA4_array[1]
                        num_sentences = int(self.numDataSentences)
                        sentence_num = int(self.SentenceNumber)
                        num_satellites = int(self.NumberSatellitesInView)
                        if sentence_num < num_sentences:
                             self.SatellitesInView.extend([NMEA4_array[4+x] for x in range(15)])
                             last_value = NMEA4_array[19][:NMEA4_array[19].find('*')]
                             #print last_value
                             self.SatellitesInView.extend([last_value])                             
                        elif sentence_num == num_sentences:
                             num_satellites_sentence = num_satellites - (4*(sentence_num-1))
                             #print sentence_num
                             #print num_satellites
                             #print ' check '
                             #print NMEA4_array[((4*num_satellites_sentence)+3)].find('*')
                             self.SatellitesInView.extend([NMEA4_array[4+x] for x in range((4*num_satellites_sentence)-1)])
                             self.SatellitesInView.extend([NMEA4_array[(4*num_satellites_sentence+3)][:NMEA4_array[(4*num_satellites_sentence+3)].find('*')]])                             
                if NMEA5_array[0] == '$GPGSV':
                        self.SentenceNumber=NMEA5_array[2]
                        #print 'finding *'
                        #print NMEA5_array[3].find('*')
                        #print NMEA5_array[3][:NMEA5_array[3].find('*')]
                        if NMEA5_array[3].find('*') == -1:
                           self.NumberSatellitesInView=NMEA5_array[3]
                        else:
                           self.NumberSatellitesInView=NMEA5_array[3][:NMEA5_array[3].find('*')]
                        self.numDataSentences=NMEA5_array[1]
                        #print 'Number satellites in view set'
                        #print NMEA5_array[3][:NMEA5_array[3].find('*')], self.NumberSatellitesInView
                        num_sentences = int(self.numDataSentences)
                        sentence_num = int(self.SentenceNumber)
                        num_satellites = int(self.NumberSatellitesInView)
                        if sentence_num < num_sentences:
                             self.SatellitesInView.extend([NMEA5_array[4+x] for x in range(15)])
                             last_value = NMEA5_array[19][:NMEA5_array[19].find('*')]
                             #print last_value
                             self.SatellitesInView.extend([last_value])                             
                        elif sentence_num == num_sentences:
                             num_satellites_sentence = num_satellites - (4*(sentence_num-1))
                             #print sentence_num
                             #print num_satellites
                             #print ' check '
                             #print NMEA5_array[((4*num_satellites_sentence)+3)].find('*')
                             self.SatellitesInView.extend([NMEA5_array[4+x] for x in range((4*num_satellites_sentence)-1)])
                             self.SatellitesInView.extend([NMEA5_array[(4*num_satellites_sentence+3)][:NMEA5_array[(4*num_satellites_sentence+3)].find('*')]])                             
                if NMEA6_array[0] == '$GPGSV':
                        self.SentenceNumber=NMEA6_array[2]
                        #print 'finding *'
                        #print NMEA6_array[3].find('*')
                        #print NMEA6_array[3][:NMEA6_array[3].find('*')] 
                        if NMEA6_array[3].find('*') == -1:
                            self.NumberSatellitesInView=NMEA6_array[3]
                        else:
                            self.NumberSatellitesInView=NMEA6_array[3][:NMEA6_array[3].find('*')]
                        #print 'Number satellites in view set'
                        #print NMEA6_array[3][:NMEA6_array[3].find('*')], self.NumberSatellitesInView
                        self.numDataSentences=NMEA6_array[1]
                        num_sentences = int(self.numDataSentences)
                        sentence_num = int(self.SentenceNumber)
                        num_satellites = int(self.NumberSatellitesInView)
                        if sentence_num < num_sentences:
                             self.SatellitesInView.extend([NMEA6_array[4+x] for x in range(15)])
                             last_value = NMEA6_array[19][:NMEA6_array[19].find('*')]
                             #print last_value
                             self.SatellitesInView.extend([last_value])                             
                        elif sentence_num == num_sentences:
                             num_satellites_sentence = num_satellites - (4*(sentence_num-1))
                             #print sentence_num
                             #print num_satellites
                             #print ' check '
                             #print NMEA6_array[(4*num_satellites_sentence+3)].find('*')
                             self.SatellitesInView.extend([NMEA6_array[4+x] for x in range((4*num_satellites_sentence)-1)])
                             self.SatellitesInView.extend([NMEA6_array[(4*num_satellites_sentence+3)][:NMEA6_array[(4*num_satellites_sentence+3)].find('*')]])                             
                if NMEA7_array[0] == '$GPGSV':
                        self.SentenceNumber=NMEA7_array[2]
                        #print 'finding *'
                        #print NMEA7_array[3].find('*')
                        #print NMEA7_array[3][:NMEA7_array[3].find('*')]
                        if NMEA7_array[3].find('*') == -1:
                            self.NumberSatellitesInView=NMEA7_array[3]
                        else:
                            self.NumberSatellitesInView=NMEA7_array[3][:NMEA7_array[3].find('*')]
                        #print 'Number satellites in view set'
                        #print NMEA7_array[3][:NMEA7_array[3].find('*')], self.NumberSatellitesInView
                        self.numDataSentences=NMEA7_array[1]
                        num_sentences = int(self.numDataSentences)
                        sentence_num = int(self.SentenceNumber)
                        num_satellites = int(self.NumberSatellitesInView)
                        if sentence_num < num_sentences:
                             self.SatellitesInView.extend([NMEA7_array[4+x] for x in range(15)])
                             last_value = NMEA7_array[19][:NMEA7_array[19].find('*')]
                             #print last_value
                             self.SatellitesInView.extend([last_value])                             
                        elif sentence_num == num_sentences:
                             num_satellites_sentence = num_satellites - (4*(sentence_num-1))
                             #print sentence_num
                             #print num_satellites
                             #print ' check '
                             #print NMEA7_array[(4*num_satellites_sentence+3)].find('*')
                             self.SatellitesInView.extend([NMEA7_array[4+x] for x in range((4*num_satellites_sentence)-1)])
                             self.SatellitesInView.extend([NMEA7_array[(4*num_satellites_sentence+3)][:NMEA7_array[(4*num_satellites_sentence+3)].find('*')]])                             
                if NMEA8_array[0] == '$GPGSV':
                        self.SentenceNumber=NMEA8_array[2]
                        #print 'finding *'
                        #print NMEA8_array[3].find('*')
                        #print NMEA8_array[3][:NMEA8_array[3].find('*')]
                        if NMEA8_array[3].find('*') == -1:
                            self.NumberSatellitesInView=NMEA8_array[3]
                        else:
                            self.NumberSatellitesInView=NMEA8_array[3][:NMEA8_array[3].find('*')]
                        #print 'Number satellites in view set'
                        #print NMEA8_array[3][:NMEA8_array[3].find('*')], self.NumberSatellitesInView
                        self.numDataSentences=NMEA8_array[1]
                        num_sentences = int(self.numDataSentences)
                        sentence_num = int(self.SentenceNumber)
                        num_satellites = int(self.NumberSatellitesInView)
                        if sentence_num < num_sentences:
                             self.SatellitesInView.extend([NMEA8_array[4+x] for x in range(15)])
                             last_value = NMEA8_array[19][:NMEA8_array[19].find('*')]
                             #print last_value
                             self.SatellitesInView.extend([last_value])                             
                        elif sentence_num == num_sentences:
                             num_satellites_sentence = num_satellites - (4*(sentence_num-1))
                             #print sentence_num
                             #print num_satellites
                             #print ' check '
                             #print NMEA8_array[(4*num_satellites_sentence+3)].find('*')
                             self.SatellitesInView.extend([NMEA8_array[4+x] for x in range((4*num_satellites_sentence)-1)])
                             self.SatellitesInView.extend([NMEA8_array[(4*num_satellites_sentence+3)][:NMEA8_array[(4*num_satellites_sentence+3)].find('*')]])                             

                if NMEA1_array[0] == '$GPRMC':
                        self.dateUTC= '20' + NMEA1_array[9][4:6] + '-' + NMEA1_array[9][2:4] + '-' + NMEA1_array[9][:2]
                if NMEA2_array[0] == '$GPRMC':
                        self.dateUTC= '20' + NMEA2_array[9][4:6] + '-' + NMEA2_array[9][2:4] + '-' + NMEA2_array[9][:2]
                if NMEA3_array[0] == '$GPRMC':
                        self.dateUTC= '20' + NMEA3_array[9][4:6] + '-' + NMEA3_array[9][2:4] + '-' + NMEA3_array[9][:2]
                if NMEA4_array[0] == '$GPRMC':
                        self.dateUTC= '20' + NMEA4_array[9][4:6] + '-' + NMEA4_array[9][2:4] + '-' + NMEA4_array[9][:2]
                if NMEA5_array[0] == '$GPRMC':
                        self.dateUTC= '20' + NMEA5_array[9][4:6] + '-' + NMEA5_array[9][2:4] + '-' + NMEA5_array[9][:2]
                if NMEA6_array[0] == '$GPRMC':
                        self.dateUTC= '20' + NMEA6_array[9][4:6] + '-' + NMEA6_array[9][2:4] + '-' + NMEA6_array[9][:2]
                if NMEA7_array[0] == '$GPRMC':
                        self.dateUTC= '20' + NMEA7_array[9][4:6] + '-' + NMEA7_array[9][2:4] + '-' + NMEA7_array[9][:2]
                if NMEA8_array[0] == '$GPRMC':
                        self.dateUTC= '20' + NMEA8_array[9][4:6] + '-' + NMEA8_array[9][2:4] + '-' + NMEA8_array[9][:2]



if __name__ == '__main__':

     myGPS=GPS()
     while(1):
        myGPS.read()
        print 'NMEA 1: ',myGPS.NMEA1
        print 'NMEA 2: ',myGPS.NMEA2
        print 'NMEA 3: ',myGPS.NMEA3
        print 'NMEA 4: ',myGPS.NMEA4
        print 'NMEA 5: ',myGPS.NMEA5
        print 'NMEA 6: ',myGPS.NMEA6
        print 'NMEA 7: ',myGPS.NMEA7
        print 'NMEA 8: ',myGPS.NMEA8

        print '-----------------------'
        print myGPS.fix
        print '-----------------------'
        print '  '
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
                print 'Number of GSV Sentences: ',myGPS.numDataSentences,'  '
                print 'Number of Satellites in View: ',myGPS.NumberSatellitesInView,'  '
                print 'PDOP: ',myGPS.PDOP,'  '
                print 'HDOP: ',myGPS.HDOP,'  '
                print 'VDOP: ',myGPS.VDOP,'  '
                print 'Satellites Tracked: ',myGPS.SatellitesInTracked,'  '
                print 'Satellites In View: ',myGPS.SatellitesInView,'  '
        time.sleep(3)
        
        