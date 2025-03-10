from __future__ import annotations

import logging
import socket
import ssl as tls
from cryptography import x509
from urllib.parse import urlparse
from datetime import datetime, UTC, timedelta
from os.path import join as path_join
from os.path import exists as path_exists

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
        self.expiry: timedelta = None
        self.logger: logging.Logger = logger
        self.mode: str = config.get('poll-mode', config_location)
        self.max_age: int = config.get('max-age', config_location)
        self.msg_template: str = config.get('message-template', config_location)
        self.logger.debug(f'mode: {self.mode}, max-age: {self.max_age}, config_location: {config_location}')
        self.location: str = location
        self.config = config
        self.data = None

    def __eq__(self, other: Certificate):
        if self.data is None or other.data is None:
            return False

        return (self.get_hosts() == other.get_hosts()
                and self.data.not_valid_after_utc == other.data.not_valid_after_utc
                and self.data.not_valid_before_utc == other.data.not_valid_before_utc
                and self.data.version == other.data.version
                and self.data.issuer == other.data.issuer)

    ##
    # Load certificate data from PEM format.
    ##
    def load_cert_data(self):
        self.logger.debug(f'Loading data for {self.location}')
        if self.data is not None:
            return

        elif self.mode == 'files':
            self.location = path_join(self.location, self.config.get('cert-file'))
            self.get_cert_files()

        elif self.mode == 'host':
            self.ctx = tls.create_default_context()
            self.ctx.check_hostname = False
            self.ctx.verify_mode = tls.CERT_NONE

            self.host, self.port = self.parse_uri(self.location)
            self.get_cert_host()

        self.data = x509.load_pem_x509_certificate(str.encode(self.cert))

    ##
    # Returns content of specified cert file
    ##
    def get_cert_files(self):
        if not path_exists(self.location):
            self.logger.error(f'Certificate {self.location} does not exist.')
        with open(self.location, 'rt') as cfile:
            self.cert = cfile.read()

    ###
    # Gets certificate of host in PEM format and TLS version
    # Returns (TLS_version, PEM certificate)
    ###
    def get_cert_host(self):
        with socket.create_connection((self.host, self.port)) as sock:
            with self.ctx.wrap_socket(sock, server_hostname=self.host) as ctx_sock:
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
    # Gets all hosts for the certificate
    ##
    def get_hosts(self):
        return self.data.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(x509.DNSName)

    ##
    # Returns if timedelta until (or from) expiry
    ##
    def until_expiry(self) -> timedelta:
        now = datetime.now(UTC)
        self.expiry = self.data.not_valid_after_utc - now
        return self.expiry

    ##
    # Is cert valid?
    ##
    def validate(self) -> bool:
        now = datetime.now(UTC)
        return self.data.not_valid_after_utc > now > self.data.not_valid_before_utc

        ##
    # Should the program warn the admins?
    # Returns True or False
    ##
    def should_warn(self) -> bool:
        if self.expiry is None:
            self.until_expiry()

        self.logger.debug(f"{self.location}")
        self.logger.debug(f"Max age: {self.max_age} days")
        self.logger.debug(f"Valid days: {self.expiry.days} days")
        return self.expiry.days <= self.max_age

    def get_message(self):
        if self.expiry is None:
            self.until_expiry()

        message = (self.msg_template
                   .replace('{nline}', '\n')
                   .replace('{cert.host}', self.location)
                   .replace('{cert.valid_days}', str(self.expiry.days))
                   .replace('{cert.valid_seconds}', str(int(self.expiry.total_seconds())))
                   .replace('{cert.valid}', str(self.validate()))
                   .replace('{cert.max-age}', str(self.max_age))
                   .replace('{cert.alts}', f"{', '.join(self.get_hosts()[:-1])} & {self.get_hosts()[-1]}" if len(self.get_hosts()) > 1 else self.get_hosts()[0]))

        self.logger.debug(message)

        return message
