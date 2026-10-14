# Contributing
Keep the bridge fail-closed. New operations require threat-model review, explicit schemas, malformed-input tests, and documentation of mutation. Do not add arbitrary command or ADB-argument passthrough. Run `python3 -m unittest discover -s tests -v`. Never include queue contents, device logs, phone numbers, message text, credentials, or backups in patches.
