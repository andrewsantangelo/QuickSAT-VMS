#!/bin/bash
# ********* NEW CERT Script **********
rm -f *.pem

openssl genrsa 2048 > ca-key.pem
openssl req -new -x509 -nodes -days 3600 -key ca-key.pem -out ca-cert.pem -subj '/DC=com/DC=dornerworks/CN=CA'

openssl req -newkey rsa:2048 -days 3600 -nodes -keyout server-key.pem -out server-req.pem -subj '/DC=com/DC=dornerworks/DC=server'
openssl rsa -in server-key.pem -out server-key.pem
openssl x509 -req -in server-req.pem -days 3600 -CA ca-cert.pem -CAkey ca-key.pem -set_serial 01 -out server-cert.pem

openssl req -newkey rsa:2048 -days 3600 -nodes -keyout client-key.pem -out client-req.pem -subj '/DC=com/DC=dornerworks/DC=server/CN=user'
openssl rsa -in client-key.pem -out client-key.pem
openssl x509 -req -in client-req.pem -days 3600 -CA ca-cert.pem -CAkey ca-key.pem -set_serial 0x100001 -out client-cert.pem

openssl verify -CAfile ca-cert.pem server-cert.pem client-cert.pem

chmod 600 ca-key.pem
chmod 644 ca-cert.pem
chgrp mysql server* client*
chmod 640 server*
chmod 644 client*
