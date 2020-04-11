#include "block_filter.h"

PYBlockFilter::PYBlockFilter(std::vector< std::vector< unsigned char > >& hashes)
{
    GCSFilter::ElementSet elements;
    for (int i = 0; i < hashes.size(); ++i)
    {
        GCSFilter::Element element(hashes[i].size());
        for(int j=0;j<hashes[i].size();j++)
        {
            element[j] = hashes[i][j];
        }
        elements.insert(std::move(element));
    }
    filter=new GCSFilter({0, 0, 20, 1 << 20},elements);
}

PYBlockFilter::PYBlockFilter(std::vector< unsigned char > & encoded_filter)
{
    filter=new GCSFilter({0, 0, 20, 1 << 20}, encoded_filter);
}

PYBlockFilter::PYBlockFilter(std::string & block_hash, std::vector< unsigned char > & encoded_filter)
{
    uint256 m_block_hash = uint256S(block_hash);
    b_filter = new BlockFilter(BlockFilterType::BASIC, m_block_hash, encoded_filter);
    const GCSFilter _filter = b_filter->GetFilter();
    filter=new GCSFilter(_filter.GetParams(), _filter.GetEncoded());
}

const std::vector<unsigned char>& PYBlockFilter::GetEncoded()
{
    return filter->GetEncoded();
}

PYBlockFilter::~PYBlockFilter()
{
    delete filter;
}

bool PYBlockFilter::Match(std::vector< unsigned char >& hash)
{
    GCSFilter::Element element(hash.size());
    for(int j=0;j<hash.size();j++)
    {
        element[j] = hash[j];
    }

    return filter->Match(element);
}

bool PYBlockFilter::MatchAny(std::vector< std::vector< unsigned char > >& hashes)
{
    GCSFilter::ElementSet elements;
    
    for (int i = 0; i < hashes.size(); ++i)
    {
        GCSFilter::Element element(hashes[i].size());
        for(int j=0;j<hashes[i].size();j++)
        {
            element[j] = hashes[i][j];
        }
        elements.insert(std::move(element));
    }
    
    return filter->MatchAny(elements);
}
