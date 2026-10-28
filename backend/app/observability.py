"""Privacy-preserving logging: no access-query strings or exception payloads."""
import logging


class SafeAccessFilter(logging.Filter):
    def filter(self, record):
        if isinstance(record.args, tuple) and len(record.args) == 5:
            args=list(record.args)
            if isinstance(args[2],str): args[2]=args[2].split('?',1)[0]
            record.args=tuple(args)
        return True


class RedactingFormatter(logging.Formatter):
    def formatException(self, exc_info):
        return 'Exception details suppressed for document privacy; class=' + exc_info[0].__name__
