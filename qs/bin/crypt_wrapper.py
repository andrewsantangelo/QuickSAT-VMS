#!/usr/bin/env python

# The Crypto package is provided by the pycrypto library

import Crypto.Random.OSRNG.posix
import Crypto.Cipher.AES
import Crypto.Hash.HMAC
import Crypto.Hash.SHA384

# The functions defined here are adapted from the examples given here:
# https://leanpub.com/pycrypto/read

__AES_KEYLEN = 32
__TAG_KEYLEN = 48
__KEY_SIZE = __AES_KEYLEN + __TAG_KEYLEN

def read_key(filename):
    """
    Read data from the specified file, and ensure that sufficient data was read
    from the file.
    """
    f = open(filename, 'rb')
    key = f.read(__KEY_SIZE)
    # Ensure that enough data was read from the specified file
    assert len(key) == __KEY_SIZE
    return key

def write_key(filename, key):
    """
    Ensure a valid length key was provided, and write it to the file provided.
    """
    assert len(key) >= __KEY_SIZE
    f = open(filename, 'w+b')
    f.write(key[:__KEY_SIZE])
    f.close()

def generate_key():
    """
    Generate a cryptographically secure random key that has enough data to
    contain an AES-256 key and an HMAC-SHA-384 digest tag.
    """
    return Crypto.Random.OSRNG.posix.new().read(__KEY_SIZE)

def generate_nonce():
    """
    Generate a cryptographically secure random block of data that will be used
    as the IV for the AES CBC algorithm.
    """
    return Crypto.Random.OSRNG.posix.new().read(Crypto.Cipher.AES.block_size)

def new_tag(ciphertext, key):
    """
    Compute a new message tag using HMAC-SHA-384.
    """
    return Crypto.Hash.HMAC.new(key, msg=ciphertext, digestmod=Crypto.Hash.SHA384).digest()

def verify_tag(ciphertext, key):
    """
    Verify the tag on a ciphertext.
    """
    tag_start = len(ciphertext) - __TAG_KEYLEN
    data = ciphertext[:tag_start]

    # The tag strings must be a bytearray so that each element supports the
    # XOR operation
    tag = bytearray(ciphertext[tag_start:])
    actual_tag = bytearray(new_tag(data, key))

    # We must manually compare all bytes of the two texts to prevent
    # modification of the python environment from giving a false tag
    # verification result.  This could be done with the streql package's
    # streql.equals() function, but rather than installing another package
    # we'll just do a constant time comparison here.
    match = 0
    for i in range(__TAG_KEYLEN):
        # This operation should get a true/false result but not contain
        # branches to attempt to ensure that the comparison is constant time.
        # The streql package uses an XOR operation which is a good fit for this
        # type of comparison.  If the rolling XOR result is ever not zero, then
        # you know that the tags did not match.
        match |= tag[i] ^ actual_tag[i]

    return (match == 0)

def pad_data(data):
    """
    Add padding to the end of the data to be encrypted to ensure that the data
    length is a multiple of the required block size.
    """
    # return data if no padding is required
    if len(data) % Crypto.Cipher.AES.block_size == 0:
        return data

    # subtract one byte that should be the 0x80
    # if 0 bytes of padding are required, it means only
    # a single \x80 is required.
    padding_required = (Crypto.Cipher.AES.block_size - 1) - (len(data) % Crypto.Cipher.AES.block_size)

    data = data + '\x80'
    data = '%s%s' % (data, '\x00' * padding_required)

    return data

def unpad_data(data):
    """
    Remove padding from the end of the message that may have been added to
    make sure the data is the required block size.
    """
    if not data:
        return data

    # Strip off any trailing null characters
    mdata = data.rstrip('\x00')
    # If the next byte is the pad character \x80, then there was padding
    if mdata[-1] == '\x80':
        return mdata[:-1]
    else:
        # The pad character was not present, return the data without any
        # characters stripped off.
        return data

def encrypt(data, key):
    """
    Encrypt data using AES in CBC mode. The IV is prepended to the
    ciphertext.
    """
    data = pad_data(data)
    ivec = generate_nonce()
    aes = Crypto.Cipher.AES.new(key[:__AES_KEYLEN], Crypto.Cipher.AES.MODE_CBC, ivec)
    ctxt = aes.encrypt(data)
    tag = new_tag(ivec + ctxt, key[__AES_KEYLEN:])
    return ivec + ctxt + tag

def decrypt(ciphertext, key):
    """
    Decrypt a ciphertext encrypted with AES in CBC mode; assumes the IV
    has been prepended to the ciphertext.
    """
    if len(ciphertext) <= Crypto.Cipher.AES.block_size:
        return None, False
    tag_start = len(ciphertext) - __TAG_KEYLEN
    ivec = ciphertext[:Crypto.Cipher.AES.block_size]
    ctxt = ciphertext[Crypto.Cipher.AES.block_size:tag_start]
    if not verify_tag(ciphertext, key[__AES_KEYLEN:]):
        return None, False
    aes = Crypto.Cipher.AES.new(key[:__AES_KEYLEN], Crypto.Cipher.AES.MODE_CBC, ivec)
    data = aes.decrypt(ctxt)
    return unpad_data(data), True

