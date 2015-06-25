#!/usr/bin/env python

import crypt_wrapper

if __name__ == '__main__':
    # generate a new encryption key and place it in /opt/qs/key
    filename = 'test.key'
    crypt_wrapper.write_key(filename, crypt_wrapper.generate_key())
    print('New encryption key created and written to ' + filename)

    f = open('test.txt', 'rb')
    data = f.read()
    f.close()

    print('read test text')

    key = crypt_wrapper.read_key(filename)
    ciphertext = crypt_wrapper.encrypt(data, key)
    f = open('ciphertext.bin', 'w+b')
    f.write(ciphertext)
    f.close()

    print('encrypted test text')

    (decodedtext, status) = crypt_wrapper.decrypt(ciphertext, key)

    print('decrypted test text = ' + str(status))

    f = open('decoded_text.txt', 'w')
    f.write(decodedtext)
    f.close()

    print('saved decoded test text')

