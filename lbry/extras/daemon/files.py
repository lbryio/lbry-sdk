#!/usr/bin/env python3
"""
Print various types of information regarding the claims.
"""
import os
import time


def print_items(items=None, release_times=None, show="all",
                title=False, typ=False, path=False,
                cid=True, blobs=True, show_channel=False,
                name=True, start=1, end=0,
                file=None, fdate=None, sep=";"):
    """Print items provided by file_list."""
    if not items:
        error = "No claims"
        if file:
            error += f'; no file written "{file}"'
        print(error)
        return False, False

    n_items = len(items)

    out_list = []

    for num, pair in enumerate(zip(items, release_times), start=1):
        if num < start:
            continue
        if end != 0 and num > end:
            break

        item = pair[0]
        release_time = pair[1]

        _path = item.download_path
        _blobs = item.blobs_completed
        _blobs_in_stream = item.blobs_in_stream

        if show in "media" and not _path:
            continue
        if show in "missing" and _path:
            continue
        if show in "incomplete" and _blobs == _blobs_in_stream:
            continue
        if show in "full" and _blobs < _blobs_in_stream:
            continue

        if "release_time" not in item.metadata:
            _time = release_time
        else:
            _time = int(item.metadata["release_time"])
        _time = time.localtime(_time)
        _time = time.strftime("%Y%m%d_%H:%M:%S%z", _time)

        _claim_id = item.claim_id
        _claim_ch = item.channel_name
        _claim_name = item.claim_name
        _title = item.metadata["title"]
        _type = item.metadata["stream_type"]

        out = "{:4d}/{:4d}".format(num, n_items) + sep + f" {_time}" + f"{sep} "

        if cid:
            out += f"{_claim_id}" + f"{sep} "
        if blobs:
            out += "{:3d}/{:3d}".format(_blobs, _blobs_in_stream) + f"{sep} "
        if show_channel:
            if _claim_ch:
                out += f"{_claim_ch}" + f"{sep} "
            else:
                out += "_Unknown_" + f"{sep} "
        if name:
            out += f'"{_claim_name}"' + f"{sep} "

        if title:
            out += f'"{_title}"' + f"{sep} "
        if typ:
            out += f"{_type}" + f"{sep} "
        if path:
            out += f'"{_path}"' + f"{sep} "

        if _path:
            out += "media"
        else:
            out += "no-media"

        out_list.append(out)

    print(f"Number of shown items: {len(out_list)}")

    fdescriptor = 0

    if file:
        dirn = os.path.dirname(file)
        base = os.path.basename(file)

        if fdate:
            fdate = time.strftime("%Y%m%d_%H%M", time.localtime()) + "_"
        else:
            fdate = ""

        file = os.path.join(dirn, fdate + base)

        try:
            with open(file, "w") as fdescriptor:
                for line in out_list:
                    print(line, file=fdescriptor)
                print(f'Summary written: "{file}"')
        except (FileNotFoundError, PermissionError) as err:
            print(f"Cannot open file for writing; {err}")
            file = None

    if not fdescriptor:
        print("\n".join(out_list))

    return len(out_list), file
