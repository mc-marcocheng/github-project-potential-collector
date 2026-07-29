# GitHub Repository Research Collector

A Python data-collection utility for research involving public GitHub repository events and metadata.

## Status

Experimental and under active development.

## Requirements

- Python 3.12
- Git

## Testing

```bash
python -m unittest discover -s tests -v
python -m compileall -q collector tests
```

## Privacy and security

The collector processes public information. Collected records and operational
configuration are stored separately and are not published in this repository.

Repository content is treated as untrusted input and is never executed.
