#ifndef PY_BLOCK_FILTER_H
#define PY_BLOCK_FILTER_H

#include <blockfilter.h>

class PYBlockFilter
{
public:
    GCSFilter *filter;
    BlockFilter *b_filter;

public:

    PYBlockFilter(std::vector< std::vector< unsigned char > >& hashes);
    PYBlockFilter(std::vector< unsigned char > & encoded_filter);
    PYBlockFilter(std::string & block_hash, std::vector< unsigned char > & encoded_filter);
    const std::vector<unsigned char>& GetEncoded();
    ~PYBlockFilter();
    
    bool Match(std::vector< unsigned char >& hash);
    bool MatchAny(std::vector< std::vector< unsigned char > >& hashes);
};

#endif
