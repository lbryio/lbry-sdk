# Generated by the protocol buffer compiler.  DO NOT EDIT!
# source: support.proto

import sys
_b=sys.version_info[0]<3 and (lambda x:x) or (lambda x:x.encode('latin1'))
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from google.protobuf import reflection as _reflection
from google.protobuf import symbol_database as _symbol_database
from google.protobuf import descriptor_pb2
# @@protoc_insertion_point(imports)

_sym_db = _symbol_database.Default()




DESCRIPTOR = _descriptor.FileDescriptor(
  name='support.proto',
  package='pb',
  syntax='proto3',
  serialized_pb=_b('\n\rsupport.proto\x12\x02pb\")\n\x07Support\x12\r\n\x05\x65moji\x18\x01 \x01(\t\x12\x0f\n\x07\x63omment\x18\x02 \x01(\tb\x06proto3')
)
_sym_db.RegisterFileDescriptor(DESCRIPTOR)




_SUPPORT = _descriptor.Descriptor(
  name='Support',
  full_name='pb.Support',
  filename=None,
  file=DESCRIPTOR,
  containing_type=None,
  fields=[
    _descriptor.FieldDescriptor(
      name='emoji', full_name='pb.Support.emoji', index=0,
      number=1, type=9, cpp_type=9, label=1,
      has_default_value=False, default_value=_b("").decode('utf-8'),
      message_type=None, enum_type=None, containing_type=None,
      is_extension=False, extension_scope=None,
      options=None),
    _descriptor.FieldDescriptor(
      name='comment', full_name='pb.Support.comment', index=1,
      number=2, type=9, cpp_type=9, label=1,
      has_default_value=False, default_value=_b("").decode('utf-8'),
      message_type=None, enum_type=None, containing_type=None,
      is_extension=False, extension_scope=None,
      options=None),
  ],
  extensions=[
  ],
  nested_types=[],
  enum_types=[
  ],
  options=None,
  is_extendable=False,
  syntax='proto3',
  extension_ranges=[],
  oneofs=[
  ],
  serialized_start=21,
  serialized_end=62,
)

DESCRIPTOR.message_types_by_name['Support'] = _SUPPORT

Support = _reflection.GeneratedProtocolMessageType('Support', (_message.Message,), dict(
  DESCRIPTOR = _SUPPORT,
  __module__ = 'support_pb2'
  # @@protoc_insertion_point(class_scope:pb.Support)
  ))
_sym_db.RegisterMessage(Support)


# @@protoc_insertion_point(module_scope)
