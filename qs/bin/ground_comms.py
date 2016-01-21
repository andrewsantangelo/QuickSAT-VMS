#!/usr/bin/env python

# 2 parts:
#   1. receive incoming messages
#   2. transmit outgoing messages
#
# All messages going to and from the ground are of the following format:
#   -----------------
#   | ESN
#   |  (10 chars)
#   -----------------
#   | FileNameSize
#   |  (3 ASCII digits)
#   -----------------
#   | FileName
#   |  (FileNameSize chars)
#   -----------------
#   | NumDataBytes
#   |  (6 ASCII digits)
#   -----------------
#   | Payload
#   |  (NumDataBytes bytes, max of 512K)
#   -----------------
#   | CRC16 of Payload
#   -----------------
#
# Each incoming message must go through the following steps:
#   1. Decode filename
#   2. Extract payload
#   3. Verify CRC
#   4. Decrypt payload (using the contents of /opt/qs/key as the encryption key)
#   5. Decompress the decrypted payload

import zlib
import crcmod

import crypt_wrapper

def read_file(filename):
    f = open(filename, 'rb')

    # Skip the ESN
    f.seek(10)

    # Read the filename
    input_filename_size = int(f.read(3))
    input_filename = f.read(input_filename_size)

    # Read the payload
    input_payload_size = int(f.read(6))
    input_payload = f.read(input_payload_size)
    input_payload_crc = f.read(2)
    f.close()

    # TODO: use the real CRC16 polynomial and characteristics, for now use the
    # XMODEM values.
    crc16_func = crcmod.mkCrcFun(poly=0x11021, rev=False, initCrc=0x0000, xorOut=0x0000)

    # Validate the CRC16 of the payload
    assert crc16_func(input_payload) != input_payload_crc

    # Decrypt the payload
    key = crypt_wrapper.read_key('/opt/qs/key')
    (compresseddata, status) = crypt_wrapper.decrypt(input_payload, key)
    assert status

    # Decompress the payload and put it into a file
    data = zlib.decompress(compresseddata)
    f = open('/opt/qs/input/{}'.format(input_filename), 'wb')
    f.write(data)
    f.close()

def write_file(data, filename, command_filename, esn):
    # compress the payload
    compresseddata = zlib.compress(data)

    # encrypt the payload
    key = crypt_wrapper.read_key('/opt/qs/key')
    payload = crypt_wrapper.encrypt(compresseddata, key)

    # TODO: use the real CRC16 polynomial and characteristics, for now use the
    # XMODEM values.
    crc16_func = crcmod.mkCrcFun(poly=0x11021, rev=False, initCrc=0x0000, xorOut=0x0000)

    # generate a CRC16
    payload_crc = crc16_func(payload)

    # write out to the command file
    f = open('/opt/qs/output/{}'.format(command_filename), 'wb')

    # 10 byte ESN
    f.write(esn)

    # FileNameSize
    f.write(len(filename))

    # FileName
    f.write(filename)

    # PayloadSize
    f.write(len(payload))

    # Payload
    f.write(payload)

    # CRC16
    f.write(payload_crc)

