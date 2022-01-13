import os
import filetype
import logging

types_map = {
    # http://www.iana.org/assignments/media-types
    # Type mapping for automated metadata extraction (video, audio, image, document, binary, model)
    '.a': ('application/octet-stream', 'binary'),
    '.ai': ('application/postscript', 'image'),
    '.aif': ('audio/x-aiff', 'audio'),
    '.aifc': ('audio/x-aiff', 'audio'),
    '.aiff': ('audio/x-aiff', 'audio'),
    '.au': ('audio/basic', 'audio'),
    '.avi': ('video/x-msvideo', 'video'),
    '.bat': ('text/plain', 'document'),
    '.bcpio': ('application/x-bcpio', 'binary'),
    '.bin': ('application/octet-stream', 'binary'),
    '.bmp': ('image/bmp', 'image'),
    '.c': ('text/plain', 'document'),
    '.cdf': ('application/x-netcdf', 'binary'),
    '.cpio': ('application/x-cpio', 'binary'),
    '.csh': ('application/x-csh', 'binary'),
    '.css': ('text/css', 'document'),
    '.csv': ('text/csv', 'document'),
    '.dll': ('application/octet-stream', 'binary'),
    '.doc': ('application/msword', 'document'),
    '.dot': ('application/msword', 'document'),
    '.dvi': ('application/x-dvi', 'binary'),
    '.eml': ('message/rfc822', 'document'),
    '.eps': ('application/postscript', 'document'),
    '.epub': ('application/epub+zip', 'document'),
    '.etx': ('text/x-setext', 'document'),
    '.exe': ('application/octet-stream', 'binary'),
    '.gif': ('image/gif', 'image'),
    '.gtar': ('application/x-gtar', 'binary'),
    '.h': ('text/plain', 'document'),
    '.hdf': ('application/x-hdf', 'binary'),
    '.htm': ('text/html', 'document'),
    '.html': ('text/html', 'document'),
    '.ico': ('image/vnd.microsoft.icon', 'image'),
    '.ief': ('image/ief', 'image'),
    '.iges': ('model/iges', 'model'),
    '.jpe': ('image/jpeg', 'image'),
    '.jpeg': ('image/jpeg', 'image'),
    '.jpg': ('image/jpeg', 'image'),
    '.js': ('application/javascript', 'document'),
    '.json': ('application/json', 'document'),
    '.ksh': ('text/plain', 'document'),
    '.latex': ('application/x-latex', 'binary'),
    '.m1v': ('video/mpeg', 'video'),
    '.m3u': ('application/x-mpegurl', 'audio'),
    '.m3u8': ('application/x-mpegurl', 'video'),
    '.man': ('application/x-troff-man', 'document'),
    '.markdown': ('text/markdown', 'document'),
    '.md': ('text/markdown', 'document'),
    '.me': ('application/x-troff-me', 'binary'),
    '.mht': ('message/rfc822', 'document'),
    '.mhtml': ('message/rfc822', 'document'),
    '.mif': ('application/x-mif', 'binary'),
    '.mov': ('video/quicktime', 'video'),
    '.movie': ('video/x-sgi-movie', 'video'),
    '.mp2': ('audio/mpeg', 'audio'),
    '.mp3': ('audio/mpeg', 'audio'),
    '.mp4': ('video/mp4', 'video'),
    '.mpa': ('video/mpeg', 'video'),
    '.mpd': ('application/dash+xml', 'video'),
    '.mpe': ('video/mpeg', 'video'),
    '.mpeg': ('video/mpeg', 'video'),
    '.mpg': ('video/mpeg', 'video'),
    '.ms': ('application/x-troff-ms', 'binary'),
    '.m4s': ('video/iso.segment', 'binary'),
    '.nc': ('application/x-netcdf', 'binary'),
    '.nws': ('message/rfc822', 'document'),
    '.o': ('application/octet-stream', 'binary'),
    '.obj': ('application/octet-stream', 'model'),
    '.oda': ('application/oda', 'binary'),
    '.p12': ('application/x-pkcs12', 'binary'),
    '.p7c': ('application/pkcs7-mime', 'binary'),
    '.pbm': ('image/x-portable-bitmap', 'image'),
    '.pdf': ('application/pdf', 'document'),
    '.pfx': ('application/x-pkcs12', 'binary'),
    '.pgm': ('image/x-portable-graymap', 'image'),
    '.pl': ('text/plain', 'document'),
    '.png': ('image/png', 'image'),
    '.pnm': ('image/x-portable-anymap', 'image'),
    '.pot': ('application/vnd.ms-powerpoint', 'document'),
    '.ppa': ('application/vnd.ms-powerpoint', 'document'),
    '.ppm': ('image/x-portable-pixmap', 'image'),
    '.pps': ('application/vnd.ms-powerpoint', 'document'),
    '.ppt': ('application/vnd.ms-powerpoint', 'document'),
    '.ps': ('application/postscript', 'document'),
    '.pwz': ('application/vnd.ms-powerpoint', 'document'),
    '.py': ('text/x-python', 'document'),
    '.pyc': ('application/x-python-code', 'binary'),
    '.pyo': ('application/x-python-code', 'binary'),
    '.qt': ('video/quicktime', 'video'),
    '.ra': ('audio/x-pn-realaudio', 'audio'),
    '.ram': ('application/x-pn-realaudio', 'audio'),
    '.ras': ('image/x-cmu-raster', 'image'),
    '.rdf': ('application/xml', 'binary'),
    '.rgb': ('image/x-rgb', 'image'),
    '.roff': ('application/x-troff', 'binary'),
    '.rtx': ('text/richtext', 'document'),
    '.sgm': ('text/x-sgml', 'document'),
    '.sgml': ('text/x-sgml', 'document'),
    '.sh': ('application/x-sh', 'document'),
    '.shar': ('application/x-shar', 'binary'),
    '.snd': ('audio/basic', 'audio'),
    '.so': ('application/octet-stream', 'binary'),
    '.src': ('application/x-wais-source', 'binary'),
    '.stl': ('model/stl', 'model'),
    '.sv4cpio': ('application/x-sv4cpio', 'binary'),
    '.sv4crc': ('application/x-sv4crc', 'binary'),
    '.svg': ('image/svg+xml', 'image'),
    '.swf': ('application/x-shockwave-flash', 'binary'),
    '.t': ('application/x-troff', 'binary'),
    '.tar': ('application/x-tar', 'binary'),
    '.tcl': ('application/x-tcl', 'binary'),
    '.tex': ('application/x-tex', 'binary'),
    '.texi': ('application/x-texinfo', 'binary'),
    '.texinfo': ('application/x-texinfo', 'binary'),
    '.tif': ('image/tiff', 'image'),
    '.tiff': ('image/tiff', 'image'),
    '.tr': ('application/x-troff', 'binary'),
    '.ts': ('video/mp2t', 'video'),
    '.tsv': ('text/tab-separated-values', 'document'),
    '.txt': ('text/plain', 'document'),
    '.ustar': ('application/x-ustar', 'binary'),
    '.vcf': ('text/x-vcard', 'document'),
    '.vtt': ('text/vtt', 'document'),
    '.wav': ('audio/x-wav', 'audio'),
    '.webm': ('video/webm', 'video'),
    '.wiz': ('application/msword', 'document'),
    '.wsdl': ('application/xml', 'document'),
    '.xbm': ('image/x-xbitmap', 'image'),
    '.xlb': ('application/vnd.ms-excel', 'document'),
    '.xls': ('application/vnd.ms-excel', 'document'),
    '.xml': ('text/xml', 'document'),
    '.xpdl': ('application/xml', 'document'),
    '.xpm': ('image/x-xpixmap', 'image'),
    '.xsl': ('application/xml', 'document'),
    '.xwd': ('image/x-xwindowdump', 'image'),
    '.zip': ('application/zip', 'binary'),

    # These are non-standard types, commonly found in the wild.
    '.cbr': ('application/vnd.comicbook-rar', 'document'),
    '.cbz': ('application/vnd.comicbook+zip', 'document'),
    '.flac': ('audio/flac', 'audio'),
    '.lbry': ('application/x-ext-lbry', 'document'),
    '.m4a': ('audio/mp4', 'audio'),
    '.m4v': ('video/m4v', 'video'),
    '.mid': ('audio/midi', 'audio'),
    '.midi': ('audio/midi', 'audio'),
    '.mkv': ('video/x-matroska', 'video'),
    '.mobi': ('application/x-mobipocket-ebook', 'document'),
    '.oga': ('audio/ogg', 'audio'),
    '.ogv': ('video/ogg', 'video'),
    '.ogg': ('video/ogg', 'video'),
    '.pct': ('image/pict', 'image'),
    '.pic': ('image/pict', 'image'),
    '.pict': ('image/pict', 'image'),
    '.prc': ('application/x-mobipocket-ebook', 'document'),
    '.rtf': ('application/rtf', 'document'),
    '.xul': ('text/xul', 'document'),
    
    # microsoft is special and has its own 'standard'
    # https://docs.microsoft.com/en-us/windows/desktop/wmp/file-name-extensions
    '.wmv': ('video/x-ms-wmv', 'video')
}

# maps detected extensions to the possible analogs
# i.e. .cbz file is actually a .zip
synonyms_map = {
    '.zip': ['.cbz'],
    '.rar': ['.cbr'],
    '.ar': ['.a']
}

log = logging.getLogger(__name__)


def guess_media_type(path):
    _, ext = os.path.splitext(path)
    extension = ext.strip().lower()

    # try detecting real file format if path points to a readable file
    try:
        kind = filetype.guess(path)
        if kind:
            realext = f".{kind.extension}"

            # override extension parsed from file...
            if extension != realext:
                if extension:
                    log.warning(f"file extension does not match it's contents {path}, identified as {realext}")
                else:
                    log.debug(f"file {path} does not have extension, identified by contents as {realext}")

                # don't do anything if extension is in synonyms
                if not extension in synonyms_map.get(realext, []):
                    extension = realext

    except OSError as error:
        pass

    if extension[1:]:
        if extension in types_map:
            return types_map[extension]
        return f'application/x-ext-{extension[1:]}', 'binary'
    return 'application/octet-stream', 'binary'


def guess_stream_type(media_type):
    for media, stream in types_map.values():
        if media == media_type:
            return stream
    return 'binary'
