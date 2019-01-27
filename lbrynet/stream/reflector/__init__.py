__doc__ = """
Reflector is a protocol to re-host lbry blobs and streams.

API Reference:

    Client sends a version handshake: {'version': int,}
        - Client has successfully established connection and may continue

    Client must send a stream descriptor request:
        + {'sd_blob_hash': str, 'sd_blob_size': int}
    
    Client may begin the file transfer of the sd blob if send_sd_blob was True.

    If the Client sends the blob:
        Server indicates if the transfer was successful: {'received_sd_blob': bool,}
    If the transfer was not successful:
        blob is added to the needed_blobs queue.

Server API Reference:
    - Server replies with the same version: +{'version': int,}
        - If the Server has a validated copy of the sd blob:
            * The response will include the needed_blobs field.
        - If the Server does not have the sd blob:
            * The needed_blobs field will not be included.
        - If the Server is not aware of the sd blobs missing:
            * The response will not include needed_blobs.
    + {'send_sd_blob': bool, 'needed_blobs': list, conditional}


TCP/IP Reference:
                            REFLECTOR, 5566

+=============[CLIENT]===========+  +=============[SERVER]===========+
[      FRAME      |    STATE     ]  [      FRAME      |    STATE     ]
|-----------------+--------------|  |-----------------+--------------|
| connection_made | ESTABLISHED  |  | connection_made | ESTABLISHED  |
| connection_lost |   CLOSING    |  | connection_lost |   CLOSING    |
| send_request    | SYN          |  | send_response   | ACK-SEND     |
| data_received   | SYN-RECEIVED |  | data_received   | SYN-RECEIVED |
| send_handshake  | SYN-SEND     |  | handle_request  | SYN-ACK      |
| send_blob       | SYN-SEND     |  +================================+
| send_descriptor | SYN-SEND     |           ReflectorServer TCB
| failed_upload   | SEND-CLOSING |
+================================+
        ReflectorClient TCB

"""
