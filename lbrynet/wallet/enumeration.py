import exceptions
import types


class EnumException(exceptions.Exception):
    pass


class Enumeration(object):
    """
    enum-like type
    From the Python Cookbook, downloaded from http://code.activestate.com/recipes/67107/
    """

    def __init__(self, name, enumList):
        self.__doc__ = name
        lookup = {}
        reverseLookup = {}
        i = 0
        uniqueNames = []
        uniqueValues = []
        for x in enumList:
            if isinstance(x, types.TupleType):
                x, i = x
            if not isinstance(x, types.StringType):
                raise EnumException, "enum name is not a string: " + x
            if not isinstance(i, types.IntType):
                raise EnumException, "enum value is not an integer: " + i
            if x in uniqueNames:
                raise EnumException, "enum name is not unique: " + x
            if i in uniqueValues:
                raise EnumException, "enum value is not unique for " + x
            uniqueNames.append(x)
            uniqueValues.append(i)
            lookup[x] = i
            reverseLookup[i] = x
            i = i + 1
        self.lookup = lookup
        self.reverseLookup = reverseLookup

    def __getattr__(self, attr):
        if attr not in self.lookup:
            raise AttributeError(attr)
        return self.lookup[attr]

    def whatis(self, value):
        return self.reverseLookup[value]
