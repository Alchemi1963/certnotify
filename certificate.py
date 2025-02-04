import logging
import socket
import ssl as tls
from cryptography import x509
from urllib.parse import urlparse
from datetime import datetime, timedelta

import configuration

default_ports = {
    "http": 80,
    "https": 443,
    "ftp": 21,
    "sftp": 22,
    "ftps": 990,
    "smtp": 25,
    "smtps": 465,
    "pop3": 110,
    "pop3s": 995,
    "imap": 143,
    "imaps": 993,
    "ldap": 389,
    "ldaps": 636,
    "ssh": 22,
    "telnet": 23,
    "nntp": 119,
    "gopher": 70,
    "rtsp": 554,
    "mysql": 3306,
    "postgresql": 5432,
    "redis": 6379,
    "mongodb": 27017,
    "smb": 445
}


class Certificate:
    def __init__(self, location: str, config: configuration.Configuration, logger: logging.Logger,
                 config_location: str = None):
        self.logger = logger
        self.check_interval = config.get('check-interval', config_location)
        self.mode = config.get('mode', config_location)
        self.max_age = config.get('max-age', config_location)
        if self.mode == 'files':
            self.location = location
            self.get_cert_files()

        elif self.mode == 'host':
            self.ctx = tls.create_default_context()
            self.ctx.check_hostname = False
            self.ctx.verify_mode = tls.CERT_NONE
            self.location = self.parse_uri(location)
            self.get_cert_host()

        self.load_cert_data()

    ##
    # Load certificate data from PEM format.
    ##
    def load_cert_data(self):
        self.data = x509.load_pem_x509_certificate(str.encode(self.cert))

    ##
    # Returns content of specified cert file
    ##
    def get_cert_files(self):
        with open(self.location, 'rt') as cfile:
            self.cert = cfile.read()

    ###
    # Gets certificate of host in PEM format and TLS version
    # Returns (TLS_version, PEM certificate)
    ###
    def get_cert_host(self):
        with socket.create_connection(self.host) as sock:
            with self.ctx.wrap_socket(sock, server_hostname=self.host[0]) as ctx_sock:
                self.cert = tls.DER_cert_to_PEM_cert(ctx_sock.getpeercert(True))

    ###
    # Parses address of host. Returns (hostname, port)
    # Assumes https if no scheme is specified.
    ###
    def parse_uri(self, url):
        if "://" not in url:  # if no scheme is present, assume https
            url = "https://" + url
            uri = urlparse(url)
        return uri.hostname, uri.port if uri.port is not None else default_ports[uri.scheme]

    ##
    # Validate certificate
    # Returns False if certificate is invalid, timedelta until expiry if valid
    ##
    def validate(self):
        now = datetime.now()
        if now < self.data.not_valid_before or now > self.data.not_valid_after:
            return False
        return self.data.not_valid_after - now

    ##
    # Should the program warn the admins?
    # Returns True or False
    ##
    def should_warn(self):
        valid = self.validate()
        if not valid:
            return True
        return valid.total_seconds() >= (self.max_age * 86400)  # max_age * 86400 seconds per day
