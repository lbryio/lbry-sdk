#
#
#
#
# known_dbs = ['lbryfile_desc.db', 'lbryfiles.db', 'valuable_blobs.db', 'blobs.db',
#              'lbryfile_blob.db', 'lbryfile_info.db', 'settings.db', 'blind_settings.db',
#              'blind_peers.db', 'blind_info.db', 'lbryfile_info.db', 'lbryfile_manager.db',
#              'live_stream.db', 'stream_info.db', 'stream_blob.db', 'stream_desc.db']
#
#
#     for known_db in known_dbs:
#             log.debug("Moving %s to %s",
#                       os.path.abspath(os.path.join(to_dir, known_db)))
#
#
#     except:
#         raise
#
#     except:
#         raise
#     except:
#         raise
#     except:
#         raise
#
#
#
#     c.execute("create table if not exists blobs (" +
#               "    blob_hash text primary key, " +
#               "    blob_length integer, " +
#               "    last_verified_time real, " +
#               "    next_announce_time real"
#               ")")
#         c.execute("insert into blobs values (?, ?, ?, ?)",
#                   (blob_hash, blob_length, verified_time, announce_time))
#
#
#
#
#     c.execute("create table if not exists lbry_files (" +
#               "    stream_hash text primary key, " +
#               "    key text, " +
#               "    stream_name text, " +
#               "    suggested_file_name text" +
#               ")")
#     c.execute("create table if not exists lbry_file_blobs (" +
#               "    blob_hash text, " +
#               "    stream_hash text, " +
#               "    position integer, " +
#               "    iv text, " +
#               "    length integer, " +
#               "    foreign key(stream_hash) references lbry_files(stream_hash)" +
#               ")")
#     c.execute("create table if not exists lbry_file_descriptors (" +
#               "    sd_blob_hash TEXT PRIMARY KEY, " +
#               "    stream_hash TEXT, " +
#               "    foreign key(stream_hash) references lbry_files(stream_hash)" +
#               ")")
#         c.execute("insert into lbry_files values (?, ?, ?, ?)",
#                   (stream_hash, key, name, suggested_file_name))
#         c.execute("insert into lbry_file_blobs values (?, ?, ?, ?, ?)",
#                   (b_h, s_h, position, iv, length))
#         c.execute("insert into lbry_file_descriptors values (?, ?)",
#                   (sd_blob_hash, stream_hash))
#
#
#
#
#
#     c.execute("create table if not exists live_streams (" +
#               "    stream_hash text primary key, " +
#               "    public_key text, " +
#               "    key text, " +
#               "    stream_name text, " +
#               "    next_announce_time real" +
#               ")")
#     c.execute("create table if not exists live_stream_blobs (" +
#               "    blob_hash text, " +
#               "    stream_hash text, " +
#               "    position integer, " +
#               "    revision integer, " +
#               "    iv text, " +
#               "    length integer, " +
#               "    signature text, " +
#               "    foreign key(stream_hash) references live_streams(stream_hash)" +
#               ")")
#     c.execute("create table if not exists live_stream_descriptors (" +
#               "    sd_blob_hash TEXT PRIMARY KEY, " +
#               "    stream_hash TEXT, " +
#               "    foreign key(stream_hash) references live_streams(stream_hash)" +
#               ")")
#
#
#         c.execute("insert into live_streams values (?, ?, ?, ?, ?)",
#                   (stream_hash, public_key, key, name, next_announce_time))
#         c.execute("insert into live_stream_blobs values (?, ?, ?, ?, ?, ?, ?)",
#                   (b_h, s_h, position, revision, iv, length, signature))
#         c.execute("insert into live_stream_descriptors values (?, ?)",
#                   (sd_blob_hash, stream_hash))
#
#
#     except KeyError:
#         pass
#
#
#     c.execute("create table if not exists lbry_file_options (" +
#               "    blob_data_rate real, " +
#               "    status text," +
#               "    stream_hash text,"
#               "    foreign key(stream_hash) references lbry_files(stream_hash)" +
#               ")")
#             except KeyError:
#             c.execute("insert into lbry_file_options values (?, ?, ?)",
#                       (rate, v, stream_hash))
#
#
#
#
#     info_c.execute("create table if not exists valuable_blobs (" +
#                    "    blob_hash text primary key, " +
#                    "    blob_length integer, " +
#                    "    reference text, " +
#                    "    peer_host text, " +
#                    "    peer_port integer, " +
#                    "    peer_score text" +
#                    ")")
#     peer_c.execute("create table if not exists approved_peers (" +
#                    "    ip_address text, " +
#                    "    port integer" +
#                    ")")
#             peer_c.execute("insert into approved_peers values (?, ?)",
#                            (host, port))
#             info_c.execute("insert into valuable_blobs values (?, ?, ?, ?, ?, ?)",
#                            (blob_hash, length, reference, peer_host, peer_port, peer_score))
