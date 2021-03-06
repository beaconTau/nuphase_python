# ADC board Interface to BeagleBone Black (industrial version)
# SPI0, CS0 for master board. SPI1 CS0 for slave board
#
# for protoBEACON, there is no slave board

from Adafruit_BBIO import SPI
import Adafruit_BBIO.GPIO as GPIO
import math
import time
import os
from tools.bf import *

NUM_BEAMS = 24

class Nuphase():
    spi_bytes = 4  #transaction must include 4 bytes
    firmware_registers_adr_max=256
    firmware_ram_adr_max=128

    map = {
        'FIRMWARE_VER'  : 0x01,
        'FIRMWARE_DATE' : 0x02,
        'SET_READ_REG'  : 0x6D, #pick readout register
        'READ'          : 0x47, #send data to spi miso
        'FORCE_TRIG'    : 0x40, #software trigger
        'CHANNEL'       : 0x41, #select channel to read
        'CHUNK'         : 0x49, #select 32-bit chunk of data in 128-wide bus
        'RAM_ADR'       : 0x45, #ram address
        'MODE'          : 0x42, #select readout mode
        'CALPULSE'      : 0x2A, #toggle RF switch/pulser board
        'THRESHOLDS'    : 0x80,
    }
        
    def __init__(self, spi_clk_freq=10000000, dualBoard=False):
        if not os.path.isfile('/sys/class/gpio/gpio60/value'):
            GPIO.setup("P9_12", GPIO.OUT) #enable pin for 2.5V bus drivers
            GPIO.output("P9_12", GPIO.LOW)  #enable for 2.5V bus drivers
        self.BUS_MASTER = 0
        self.BUS_SLAVE = 1
        self.spi={}
        self.spi[0]=SPI.SPI(self.BUS_MASTER,0) #setup SPI0
        self.spi[0].mode = 0
    
        self.spi[1]=SPI.SPI(self.BUS_SLAVE,0)
        self.spi[1].mode = 0

        self.dualBoard = dualBoard
        
        try:
            self.spi[0].msh = spi_clk_freq
            self.spi[1].msh = spi_clk_freq
        except IOError:
            pass #hardware does not support this speed..

        self.current_buffer = 0
        self.current_trigger= 0
    
    def write(self, dev, data):
        if len(data) != 4:
            return None
        if dev < 0 or dev > 1:
            return None
        self.spi[dev].writebytes(data)        

    def read(self, dev):
        if dev < 0 or dev > 1:
            return None
        return self.spi[dev].readbytes(self.spi_bytes)

    def readRegister(self, dev, address=1):
        if address > self.firmware_registers_adr_max-1 or address < 1:
            return None
        ## set readout register
        send_word=[self.map['SET_READ_REG'], 0x00, 0x00, address & 0xFF]
        self.write(dev, send_word) #set read register of interest
        readback = self.read(dev)
#        print readback
        return readback

    def dna(self):
        dna_bytes = 8
        
        dna_low_slave  = self.readRegister(self.BUS_SLAVE,4)[::-1] #lower 3 bytes 
        dna_mid_slave  = self.readRegister(self.BUS_SLAVE,5)[::-1] #middle 3 bytes
        dna_hi_slave   = self.readRegister(self.BUS_SLAVE,6)[::-1] #upper 2 bytes
        dna_low_master = self.readRegister(self.BUS_MASTER,4)[::-1] #lower 3 bytes 
        dna_mid_master = self.readRegister(self.BUS_MASTER,5)[::-1] #middle 3 bytes
        dna_hi_master  = self.readRegister(self.BUS_MASTER,6)[::-1] #upper 2 bytes        

        board_dna_slave = 0
        board_dna_master = 0

        for i in range(dna_bytes):
            if i < 3:
                board_dna_slave = board_dna_slave | (dna_low_slave[i] << i*8)
                board_dna_master = board_dna_master | (dna_low_master[i] << i*8)
            elif i < 6:
                board_dna_slave = board_dna_slave | (dna_mid_slave[i-3] << i*8)
                board_dna_master = board_dna_master | (dna_mid_master[i-3] << i*8)
            else:
                board_dna_slave = board_dna_slave | (dna_hi_slave[i-6] << i*8)
                board_dna_master = board_dna_master | (dna_hi_master[i-6] << i*8)

        return board_dna_master, board_dna_slave

    def identify(self):
        dna = self.dna()
        for i in range(2):
            if not self.dualBoard and i==1:
                return
            
            print "SPI bus", i
            firmware_version = self.readRegister(i, self.map['FIRMWARE_VER'])
            firmware_version = [firmware_version[1], str((firmware_version[3] & 0xF0)>>4)+'.'+str(firmware_version[3]&0x0F)]
            print 'firmware version:', firmware_version
            firmware_date = self.readRegister(i, self.map['FIRMWARE_DATE'])
            firmware_date = [(firmware_date[1])<<4 | (firmware_date[2] & 0xF0)>>4, firmware_date[2] & 0x0F, firmware_date[3]]
            print 'firmware date:', firmware_date
            print 'board DNA:', hex(dna[i])
            print '-----------------------------------'

    def reset(self, sync=True):
        if sync:
            self.write(self.BUS_MASTER,[39,0,0,1])
        self.write(self.BUS_SLAVE, [127,0,0,1])
        self.write(self.BUS_MASTER, [127,0,0,1])
        if sync:
            self.write(self.BUS_MASTER,[39,0,0,0])

    def getDataValid(self):
        data_valid_master = (self.readRegister(self.BUS_MASTER, 8)[3] & 16) >> 4
        if self.dualBoard:
            data_valid_slave  = (self.readRegister(self.BUS_SLAVE, 8)[3] & 16) >> 4
            return data_valid_master, data_valid_slave
        return data_valid_master
            
    def resetADC(self, sync=True):
        if sync:
            self.write(self.BUS_MASTER,[39,0,0,1])
        self.write(self.BUS_SLAVE, [127,0,0,4])
        self.write(self.BUS_MASTER, [127,0,0,4])
        if sync:
            self.write(self.BUS_MASTER,[39,0,0,0])
                                                        
    def boardInit(self, verbose=False):
        self.write(self.BUS_MASTER,[39,0,0,0]) #make sure sync disabled
        self.externalTriggerInputConfig(enable=False) #disable external trigger 
        self.enablePhasedTriggerToDataManager(False, readback=verbose)
        self.enablePhasedTrigger(False, readback=verbose) #turn off trigger enables
        self.calPulser(False)
        self.preTriggerWindow()
        self.bufferClear(15)
        
        self.write(self.BUS_MASTER,[39,0,0,1]) #send sync
        self.write(self.BUS_SLAVE,[77,0,1,0]) #set buffer to 0 on slave
        self.write(self.BUS_MASTER,[77,0,1,0]) #set buffer to 0 
        self.write(self.BUS_MASTER,[39,0,0,0]) #release sync
        self.write(self.BUS_MASTER,[39,0,0,1]) #send sync
        self.write(self.BUS_SLAVE,[126,0,0,1]) #reset event counter/timestamp on slave
        self.write(self.BUS_MASTER,[126,0,0,1]) #reset event counter/timestamp 
        self.write(self.BUS_MASTER,[39,0,0,0]) #release sync
        self.setReadoutBuffer(0)
        
        self.getDataManagerStatus(verbose=verbose)

    #same as above, but just reset the data manager stuff:
    def eventInit(self):
        self.write(self.BUS_MASTER,[39,0,0,0])
        self.bufferClear(15)

        if self.dualBoard:
            self.write(self.BUS_MASTER,[39,0,0,1]) #send sync
            self.write(self.BUS_SLAVE,[77,0,1,0]) #set buffer to 0 on slave
        self.write(self.BUS_MASTER,[77,0,1,0]) #set buffer to 0

        if self.dualBoard:
            self.write(self.BUS_MASTER,[39,0,0,0]) #release sync

            self.write(self.BUS_MASTER,[39,0,0,1]) #send sync
            self.write(self.BUS_SLAVE,[126,0,0,1]) #reset event counter/timestamp on slave

        self.write(self.BUS_MASTER,[126,0,0,1]) #reset event counter/timestamp

        if self.dualBoard:
            self.write(self.BUS_MASTER,[39,0,0,0]) #release sync

        self.setReadoutBuffer(0)
        
    def bufferClear(self, buf_clear_flag=15):

        if self.dualBoard:
            self.write(self.BUS_MASTER,[39,0,0,1]) #send sync
            self.write(self.BUS_SLAVE, [77,0,0,buf_clear_flag]) #clear buffers on slave
        self.write(self.BUS_MASTER,[77,0,0,buf_clear_flag]) #clear buffers on master
        if self.dualBoard:
            self.write(self.BUS_MASTER,[39,0,0,0]) #release sync

    def dclkReset(self, sync=True):
        if sync:
            self.write(self.BUS_MASTER, [39,0,0,1]) #send sync
            self.write(self.BUS_SLAVE, [55,0,0,1]) #send dclk reset pulse to slave
        self.write(self.BUS_MASTER, [55,0,0,1]) #send dclk reset pulse to master
        if sync:
            self.write(self.BUS_MASTER, [39,0,0,0]) #release sync
            
    def calPulser(self, enable=True, readback=False):

        if enable:
            self.write(self.BUS_MASTER, [42,0,0,3])
            if self.dualBoard:
                self.write(self.BUS_SLAVE, [42,0,0,3])
        else:
            self.write(self.BUS_MASTER, [42,0,0,0])
            if self.dualBoard:
                self.write(self.BUS_SLAVE, [42,0,0,0])

        if readback:
            if self.dualBoard:
                print self.readRegister(self.BUS_SLAVE,42)
            print self.readRegister(self.BUS_MASTER,42)
            

    def setReadoutBuffer(self, buf, readback=False):
        if buf < 0 or buf > 3:
            return None
        self.write(self.BUS_MASTER, [78,0,0,buf])
        if self.dualBoard:
            self.write(self.BUS_SLAVE, [78,0,0,buf])
        if readback:
            print self.readRegister(self.BUS_MASTER,78)
            if self.dualBoard:
                print self.readRegister(self.BUS_SLAVE,78)
        
    def softwareTrigger(self, sync=True):
        if sync and self.dualBoard:
            self.write(self.BUS_MASTER,[39,0,0,1]) #send sync command to master

        if self.dualBoard:
            self.write(self.BUS_SLAVE,[64,0,0,1]) #send software trig to slave
        self.write(self.BUS_MASTER,[64,0,0,1]) #send software trig to master

        if sync and self.dualBoard:
            self.write(self.BUS_MASTER,[39,0,0,0]) #release sync

    def getDataManagerStatus(self, verbose=True):
        status_master = self.readRegister(self.BUS_MASTER, 7)
        status_slave = self.readRegister(self.BUS_SLAVE,7)
        self.buffers_full = [status_master[2] & 1, status_slave[2] & 1]
        self.current_buffer = [(status_master[2] & 48) >> 4,(status_slave[2] & 48) >> 4]
        self.buffer_flags = [status_master[3] & 15, status_slave[3] & 15]
        self.last_trig_type = [(status_master[1] & 3), (status_slave[1] & 3)]
        
        if verbose: # and self.dualBoard:
            print 'status master:', status_master,
            if self.dualBoard:
                print 'status slave:', status_slave
            else:
                print
            print 'current write buffer, master:', self.current_buffer[0],
            if self.dualBoard:
                print 'slave:', self.current_buffer[1]
            else:
                print
            print 'all buffers full?     master:', self.buffers_full[0],
            if self.dualBoard:
                print 'slave:', self.buffers_full[1]
            else:
                print
            print 'buffer full flags     master:', self.buffer_flags[0],
            if self.dualBoard:
                print 'slave:', self.buffer_flags[1]
            else:
                print
            print 'last trig type        master:', self.last_trig_type[0],
            if self.dualBoard:
                print 'slave:', self.last_trig_type[1]
            else:
                print
    def getMetaData(self, verbose=True):
        '''UPDATE FOR BEACON'''
        metadata={}
        metadata['master'] = {}  #master
        metadata['slave'] = {}  #slave
        evt_counter_master_lo = self.readRegister(self.BUS_MASTER, 10)
        evt_counter_master_hi = self.readRegister(self.BUS_MASTER, 11)
        if self.dualBoard:
            evt_counter_slave_lo = self.readRegister(self.BUS_SLAVE, 10)
            evt_counter_slave_hi = self.readRegister(self.BUS_SLAVE, 11)
        trig_counter_master_lo = self.readRegister(self.BUS_MASTER, 12)
        trig_counter_master_hi = self.readRegister(self.BUS_MASTER, 13)
        if self.dualBoard:
            trig_counter_slave_lo = self.readRegister(self.BUS_SLAVE, 12)
            trig_counter_slave_hi = self.readRegister(self.BUS_SLAVE, 13)
        trig_time_master_lo = self.readRegister(self.BUS_MASTER, 14)
        trig_time_master_hi = self.readRegister(self.BUS_MASTER, 15)
        if self.dualBoard:
            trig_time_slave_lo = self.readRegister(self.BUS_SLAVE, 14)
            trig_time_slave_hi = self.readRegister(self.BUS_SLAVE, 15)
        deadtime_master = self.readRegister(self.BUS_MASTER,16)
        if self.dualBoard:
            deadtime_slave = self.readRegister(self.BUS_SLAVE,16)
        trig_info_master = self.readRegister(self.BUS_MASTER,17)
        if self.dualBoard:
            trig_info_slave = self.readRegister(self.BUS_SLAVE,17)
        scaler_counter_master = self.readRegister(self.BUS_MASTER, 19)
        trig_beam_power = []
        for i in range(15):
            trig_beam_power.append(self.readRegister(self.BUS_MASTER, 20+i) )
        
        metadata['master']['evt_count'] = evt_counter_master_hi[1] << 40 | evt_counter_master_hi[3] << 32 | evt_counter_master_hi[3] << 24 |\
                                   evt_counter_master_lo[1] << 16 | evt_counter_master_lo [2] << 8 | evt_counter_master_lo[3]
        metadata['master']['trig_count'] = trig_counter_master_hi[1] << 40 | trig_counter_master_hi[3] << 32 | trig_counter_master_hi[3] << 24 |\
                                    trig_counter_master_lo[1] << 16 | trig_counter_master_lo [2] << 8 | trig_counter_master_lo[3]
        metadata['master']['trig_time'] = trig_time_master_hi[1] << 40 | trig_time_master_hi[2] << 32 | trig_time_master_hi[3] << 24 |\
                                   trig_time_master_lo[1] << 16 | trig_time_master_lo[2] << 8 | trig_time_master_lo[3]
        metadata['master']['deadtime'] =  deadtime_master[1] << 16 | deadtime_master[2] << 8 | deadtime_master[3]
        metadata['master']['last_beam_trig'] = (trig_info_master[2] & 0x7F) << 8 | trig_info_master[3]
        metadata['master']['trig_type'] = (trig_info_master[1] & 0x01) << 1 | (trig_info_master[2] & 0x80) >> 7
        metadata['master']['buffer_no'] = (trig_info_master[1] & 0xC0) >> 6

        if self.dualBoard:
            metadata['slave']['evt_count'] = evt_counter_slave_hi[1] << 40 | evt_counter_slave_hi[3] << 32 | evt_counter_slave_hi[3] << 24 |\
                                             evt_counter_slave_lo[1] << 16 | evt_counter_slave_lo [2] << 8 | evt_counter_slave_lo[3]

            metadata['slave']['trig_count'] = trig_counter_slave_hi[1] << 40 | trig_counter_slave_hi[3] << 32 | trig_counter_slave_hi[3] << 24 |\
                                              trig_counter_slave_lo[1] << 16 | trig_counter_slave_lo [2] << 8 | trig_counter_slave_lo[3]
            metadata['slave']['trig_time'] = trig_time_slave_hi[1] << 40 | trig_time_slave_hi[2] << 32 | trig_time_slave_hi[3] << 24 |\
                                             trig_time_slave_lo[1] << 16 | trig_time_slave_lo[2] << 8 | trig_time_slave_lo[3]
            metadata['slave']['deadtime'] =  deadtime_slave[1] << 16 | deadtime_slave[2] << 8 | deadtime_slave[3]
            metadata['slave']['trig_type'] = (trig_info_slave[1] & 0x01) << 1 | (trig_info_slave[2] & 0x80) >> 7
            metadata['slave']['buffer_no'] = (trig_info_slave[1] & 0xC0) >> 6

        metadata['master']['scaler_slow'] = (scaler_counter_master[2] & 0x0F) << 8 | scaler_counter_master[3]
        metadata['master']['scaler_fast'] = (scaler_counter_master[1] & 0xFF) << 4 | (scaler_counter_master[2] & 0xF0) >> 4

        #metadata['master']['beam_power']=[]
        #for i in range(15):
        #    metadata['master']['beam_power'].append(trig_beam_power[i][1] << 16 | trig_beam_power[i][2] << 8 | trig_beam_power[i][3])
                                   
        return metadata

    def readSysEvent(self, address_start=1, address_stop=64, save=True, filename='test.dat'):
        data_master = self.readBoardEvent(self.BUS_MASTER, address_start=address_start, address_stop=address_stop)
        if self.dualBoard:
            data_slave = self.readBoardEvent(self.BUS_SLAVE, channel_stop=3, address_start=address_start, address_stop=address_stop)

        with open(filename, 'w') as f:
            for i in range(len(data_master[0])):
                for j in range(len(data_master)):
                    f.write(str(data_master[j][i]))
                    f.write('\t')
                if self.dualBoard:
                    for j in range(len(data_slave)):
                        f.write(str(data_slave[j][i]))
                        f.write('\t')
                f.write('\n')

        if self.dualBoard:
            return data_master+data_slave
        else:
            return data_master

                    
    def readBoardEvent(self, dev, channel_start=0, channel_stop=7, address_start=0, address_stop=64):
        data=[]
        for i in range(channel_start, channel_stop+1):
            data.append(self.readChan(dev, i, address_start, address_stop))

        return data 

    def readChan(self, dev, channel, address_start=0, address_stop=64):
        if channel < 0 or channel > 7:
            return None
        
        channel_mask = 0x00 | 1 << channel
        self.write(dev, [65,0,0,channel_mask])
        data=[]
        for i in range(address_start, address_stop):
            data.extend(self.readRamAddress(dev, i))

        return data
            
    def readRamAddress(self, dev, address, readback_address=False, verbose=False):
        data=[]
        return_address=0
        self.write(dev, [69,0,0, 0xFF & address]) #note only picks off lower byte of address input
        if readback_address:
            return_address=self.readRegister(dev,69)
        self.write(dev,[35,0,0,0])
        data.extend(self.read(dev))
        self.write(dev,[36,0,0,0])
        data.extend(self.read(dev))
        self.write(dev,[37,0,0,0])
        data.extend(self.read(dev))
        self.write(dev,[38,0,0,0])
        data.extend(self.read(dev))

        if verbose:
            print dev,return_address,data

        return data

    def getCurrentAttenValues(self, verbose=False):
        current_atten_values = []
        temp=self.readRegister(self.BUS_MASTER,50)
        current_atten_values.extend([temp[3],temp[2],temp[1]])
        temp=self.readRegister(self.BUS_MASTER,51)
        current_atten_values.extend([temp[3],temp[2],temp[1]])
        temp=self.readRegister(self.BUS_MASTER,52)
        current_atten_values.extend([temp[3],temp[2]])

        if self.dualBoard:
            temp=self.readRegister(self.BUS_SLAVE,50)
            current_atten_values.extend([temp[3],temp[2],temp[1]])
            temp=self.readRegister(self.BUS_SLAVE,51)
            current_atten_values.extend([temp[3]])
            
        if verbose:
            print 'reading back attenuation values:', current_atten_values
        return current_atten_values
                                                                                
    def setAttenValues(self, atten_values, readback=True):
        self.write(self.BUS_MASTER, [50, atten_values[2] & 0xFF, atten_values[1] & 0xFF, atten_values[0] & 0xFF])
        self.write(self.BUS_MASTER, [51, atten_values[5] & 0xFF, atten_values[4] & 0xFF, atten_values[3] & 0xFF])
        self.write(self.BUS_MASTER, [52, 0x00, atten_values[7] & 0xFF, atten_values[6] & 0xFF])
        self.write(self.BUS_MASTER, [53,0,0,0])

        if self.dualBoard:
            self.write(self.BUS_SLAVE, [50, 0x00, atten_values[9] & 0xFF, atten_values[8] & 0xFF])
            #self.write(self.BUS_SLAVE, [50, atten_values[10] & 0xFF, atten_values[9] & 0xFF, atten_values[8] & 0xFF])
            #self.write(self.BUS_SLAVE, [51, 0x00, 0x00, atten_values[11] & 0xFF])
            self.write(self.BUS_SLAVE, [53,0,0,0])
            
        if readback:
            print 'set attenuation values to:', atten_values
            readback_atten_values = self.getCurrentAttenValues()
            print 'reading back:', readback_atten_values
            return readback_atten_values

    def externalTriggerInputConfig(self, enable=False, use_gate_gen=False, gate_value=255):
        if self.dualBoard:
            self.write(self.BUS_MASTER, [39,0,0,1]) #send sync
        gate_low_byte = gate_value & 0x00FF
        gate_high_byte = (gate_value & 0xFF00) >> 8

        if self.dualBoard:
            self.write(self.BUS_SLAVE, [75, gate_high_byte, gate_low_byte, 0x00 | (use_gate_gen << 1) | enable])
        self.write(self.BUS_MASTER, [75, gate_high_byte, gate_low_byte, 0x00 | (use_gate_gen << 1) | enable])

        if self.dualBoard:
            self.write(self.BUS_MASTER, [39,0,0,0]) 
        
    def updateScalerValues(self, bus=0):
        self.write(bus, [40,0,0,1])

    def setScalerOut(self, scaler_adr=0, bus=0):
        if scaler_adr < 0 or scaler_adr > 38: #max scalers is 38 for protobeacon
            return None
        self.write(bus, [41,0,0,scaler_adr])

    def readSingleScaler(self, bus=0):
        read_scaler_reg = self.readRegister(bus,3)
        scaler_low = (read_scaler_reg[2] & 0x0F) << 8 | read_scaler_reg[3]
        scaler_hi  = (read_scaler_reg[1] & 0xFF) << 4 | (read_scaler_reg[2] & 0xF0) >> 4
        return scaler_low, scaler_hi
    
    def readScalers(self, bus=0):
        scaler_dict = {}
        scaler_dict[0] = 0 #total  trigger rate
        scaler_dict[1] = [] #rate in each beam
        scaler_dict[2] = 0  # every-second total
        scaler_dict[3] = [] #every-second rate in each beam
        scaler_dict[4] = 0 # total, gated
        scaler_dict[5] = [] #each beam, gated
        self.updateScalerValues()
        self.setScalerOut(0)
        temp = self.readSingleScaler()
        scaler_dict[0] = temp[0]
        scaler_dict[1].append(temp[1])
        self.setScalerOut(16)
        temp = self.readSingleScaler()
        scaler_dict[2] = temp[0]
        scaler_dict[3].append(temp[1])
        self.setScalerOut(8)
        temp = self.readSingleScaler()
        scaler_dict[4] = temp[0]
        scaler_dict[5].append(temp[1])

        #read the ext-trig input (i.e. PPS) latched timestamp
        tmp=self.readRegister(bus, 44)
        latched_timestamp = 0x000000000000 | (tmp[1] << 16) | (tmp[2] << 8) | tmp[3]
        tmp=self.readRegister(bus, 45)
        latched_timestamp = (tmp[1] << 40) | (tmp[2] << 32) | (tmp[3] << 24) | latched_timestamp
        scaler_dict[6] = latched_timestamp
        
        #loop through the rest of the beam scalers:
        for i in range(1,8):
            self.setScalerOut(i)
            temp = self.readSingleScaler()
            scaler_dict[1].extend([temp[0],temp[1]])
            self.setScalerOut(i+16)
            temp = self.readSingleScaler()
            scaler_dict[3].extend([temp[0],temp[1]])
            self.setScalerOut(i+8)
            temp = self.readSingleScaler()
            scaler_dict[5].extend([temp[0],temp[1]])

        # returns dictionary of scaler values
        # keys: [0] = total 0.1 Hz scaler; [1] = individual beams 0.1 Hz scaler
        #       [2] = total 1 Hz scaler; [3] = individual beams 1 Hz scaler
        #       [4] = total 0.1 Hz gated scaler; [5] = individual beams 0.1 Hz gated scaler
        #       [6] = latched timestamp value on ext trig input (i.e. pps)
        return scaler_dict

    def preTriggerWindow(self, value=6):
        if self.dualBoard:
            self.write(self.BUS_SLAVE, [76, 0, 0, value & 0xFF])
        self.write(self.BUS_MASTER, [76, 0, 0, value & 0xFF])

    def enablePhasedTrigger(self, enable=True, readback=True, verification_mode=False, bus=0):
        readback_trig_reg = self.readRegister(bus, 82)
        if enable:
            self.write(bus,[82, readback_trig_reg[1], readback_trig_reg[2], readback_trig_reg[3] | 0x01])
        else:
            self.write(bus,[82, readback_trig_reg[1], readback_trig_reg[2], readback_trig_reg[3] & 0xFE])
        #set verification mode:
        if verification_mode:
            self.write(bus, [85,0,0,0x01])
        else:
            self.write(bus, [85,0,0,0x00])
        ####
        if readback:
            readback_trig_reg = self.readRegister(bus, 82)
            print readback_trig_reg
            return readback_trig_reg

    #def setPhasedTriggerOutput(self, pol=1, width=
        
    def enablePhasedTriggerToDataManager(self, enable=True, readback=False):
        self.write(self.BUS_MASTER, [39,0,0,1])
        if enable:
            self.write(self.BUS_SLAVE, [84,0,0,1])
            self.write(self.BUS_MASTER, [84,0,0,1])
        else:
            self.write(self.BUS_SLAVE, [84,0,0,0])
            self.write(self.BUS_MASTER, [84,0,0,0])
        self.write(self.BUS_MASTER, [39,0,0,0])

        if readback:
            readback_trig_reg = self.readRegister(self.BUS_MASTER, 84)
            print readback_trig_reg
            return readback_trig_reg

    def readAllThresholds(self, bus=0):
        current_thresholds=[]
        for i in range(NUM_BEAMS):
            temp = self.readRegister(bus,self.map['THRESHOLDS']+i)
            current_thresholds.append((temp[1] << 16) | (temp[2] << 8) | temp[3])
        return current_thresholds
    
    def setBeamThresholds(self, threshold, beam=0, readback=True, bus=0):
        if beam < 0 or beam > NUM_BEAMS:
            return None
        if threshold < 0 or threshold > 0x0FFFFF:
            print 'invalid threshold'
            return None
        threshold = int(threshold)
        thresh_hi = (threshold & 0x0F0000) >> 16
        thresh_mid = (threshold & 0x00FF00) >> 8
        thresh_lo = (threshold & 0x0000FF)
        self.write(bus, [self.map['THRESHOLDS']+beam, thresh_hi, thresh_mid, thresh_lo])

        if readback:
            readback_thresh = self.readRegister(self.BUS_MASTER, self.map['THRESHOLDS']+beam)
            print 'reading back threshold for beam', beam, ' Value is', readback_thresh
            return readback_thresh
        


        
if __name__=="__main__":
    d=Nuphase()
    d.boardInit()
    d.identify()
