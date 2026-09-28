"""Read a ready-made export; no database scans or compression during requests."""
import json
import logging
import os
import re
from datetime import datetime
from email.utils import formatdate

from fastapi.responses import Response, StreamingResponse

logger = logging.getLogger('tonprices.download')


class ExportUnavailable(Exception):
    def __init__(self, stale=False):
        self.stale = stale


class SnapshotResponse(StreamingResponse):
    def __init__(self, file, headers):
        self.file = file
        super().__init__(iter(lambda: file.read(256 * 1024), b''), media_type='application/gzip', headers=headers)

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            self.file.close()


def download_snapshot(directory, request, now):
    file = None
    try:
        # A manifest can change between reading it and opening the referenced file.
        for attempt in range(2):
            with (directory / 'snapshot.json').open(encoding='utf8') as manifest:
                info = json.loads(manifest.read(16384))
            name = info['file']
            checksum = info['sha256']
            if not re.fullmatch(r'[0-9a-f]{64}', checksum) or name != checksum + '.sqlite3.gz':
                raise ValueError('Invalid export manifest')
            created = datetime.fromisoformat(info['created_at'].replace('Z', '+00:00'))
            if created.tzinfo is None:
                raise ValueError('Snapshot timestamp must contain a timezone')
            age = now - created.timestamp()
            if age > 900 or age < -60:
                raise ExportUnavailable(stale=True)
            try:
                file = (directory / name).open('rb')
                break
            except FileNotFoundError:
                if attempt:
                    raise
        size = os.fstat(file.fileno()).st_size
        if size != info['bytes'] or size <= 0:
            raise ValueError('Snapshot size mismatch')
        etag = '"' + checksum + '"'
        headers = {
            'Content-Disposition': f'attachment; filename="gram-prices-{created.strftime("%Y%m%dT%H%M%SZ")}.sqlite3.gz"',
            'Content-Length': str(size),
            'ETag': etag,
            'Last-Modified': formatdate(created.timestamp(), usegmt=True),
            'Cache-Control': 'public, max-age=60, must-revalidate',
            'X-Checksum-SHA256': checksum,
            'X-Snapshot-Created-At': info['created_at'],
            'X-Snapshot-Age-Seconds': str(max(0, int(age))),
        }
        matches = [part.strip().removeprefix('W/') for part in request.headers.get('if-none-match', '').split(',')]
        if etag in matches or '*' in matches:
            file.close()
            return Response(status_code=304, headers={key: value for key, value in headers.items()
                                                      if key not in ('Content-Length', 'Content-Disposition')})
        if request.method == 'HEAD':
            file.close()
            return Response(media_type='application/gzip', headers=headers)
        return SnapshotResponse(file, headers)
    except ExportUnavailable:
        if file:
            file.close()
        raise
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        if file:
            file.close()
        logger.warning('Prepared database export unavailable')
        raise ExportUnavailable() from None
