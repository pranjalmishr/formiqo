"""Bounded native document parsing, isolated from the API process."""
import json
import sys
from pathlib import Path


def main():
    if sys.platform.startswith('linux'):
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (1536 * 1024**2, 1536 * 1024**2))
        resource.setrlimit(resource.RLIMIT_CPU, (75, 75))
        resource.setrlimit(resource.RLIMIT_FSIZE, (50 * 1024**2, 50 * 1024**2))
    from .extraction import extract, ExtractionError
    try:
        result = extract(Path(sys.argv[1]), sys.argv[2])
        print(json.dumps(result))
    except ExtractionError as exc:
        print(json.dumps({'error': str(exc)}))
        sys.exit(2)
    except Exception:
        print(json.dumps({'error': 'Document processing failed safely. Try a different export.'}))
        sys.exit(2)


if __name__ == '__main__':
    main()
