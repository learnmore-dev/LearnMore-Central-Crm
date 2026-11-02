import logging
import re


class RedactGoogleCallback(logging.Filter):
    def filter(self, record):
        def redact(value):
            if isinstance(value, str) and '/google-contacts/callback' in value:
                return re.sub(r'([?&](?:code|state|error_description)=)[^&\s"]+', r'\1[redacted]', value)
            return value
        record.msg = redact(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(redact(value) for value in record.args)
        return True
