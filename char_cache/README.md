# Character Cache Mechanism

I have found that depending on zkill or eve resolution API has quite a bit of latency and sub second intel is almost always not possible for first time queries. So I wanted to add a small binary cache which is small enough yet has decent hit rate so majority of queries can be done instantly. 

# Stored Information
* Names
    * Character names
    * Corporation names
    * Alliance names
* IDs
    * Character IDs
    * Corporation IDs
    * Alliance IDs
* Character to Corporation mapping
* Character to Alliance mapping(maybe can be improved? via corp -> alliance mapping)
* Basic kill stats for all characters

# Storage Format
All string names are stored as marisa-trie. IDs are stored as separate binary file using LEB128 encoding. Character to Corporation and Character to Alliance mappings are stored as separate binary files using LEB128 encoding. Basic kill stats are stored as separate binary files using LEB128 encoding. The alliance names and corporation names are prefixed with `#` and `@` respectively to distinguish them from character names. This allows us to store all names in a single trie for ease use and retrieval. 

If we wanted to purely store ids, it's actually quite a bit more efficient to sort them and store them as differences instead of absolute values. However, I have no idea how we can map them back to trie ids. Since trie is absolutely needed for their much more significant space savings. We must use their ordering(i.e trie id serve as index into the binary id file) to store ids instead. 

* names.trie
    * Character names
    * Corporation names
    * Alliance names
* ids.bin
    * **notes** indexed by trie_id from names.trie
    * Character IDs
    * Corporation IDs
    * Alliance IDs
* char_info.bin
    * **notes** indexed by trie_id from names.trie
    * **notes** if corporation_id is 0, it means this name entity is not a character, and ther will not be an alliance entry to save space.
    * Character to Corporation mapping
    * Character to Alliance mapping
* kill_stats.bin
    * Basic kill stats for all characters
    * **TODO**

# Data Source
I initially used https://data.everef.net/characters-corporations-alliances/ data dump. I then filter based on last active field. This reduces from about 20mil characters to about 2mil. However when tested against jita local, the hit rate is only about 45%. Whereas full 20mil is around 77%. After some digging I found that this data was provided by eve-kill.com or previously evekillboard and it's sort of outdated. I then downloaded the most recent data from eve-kill through it's export API and did the same thing again. This results in about 3mil character instead of 2mil and has much better hit rate in jita local at about 65%. This sort of hit rate in jita local usually means if you try it in any large blob staging system, you will get >90% hit rate. I consider this good enough that we don't need the full data dump which would mean about 200-300MB. 

# Data stats
**Test Dataset**: 793 Jita local characters  
**Total Characters**: 20,640,399

Match rates by last_active year filter:

| Year | Characters | Found | Match Rate |
|------|------------|-------|------------|
| 2005 | 20,097,072 | 611   | 77.0%      |
| 2006 | 20,097,072 | 611   | 77.0%      |
| 2007 | 20,097,072 | 611   | 77.0%      |
| 2008 | 3,517,301  | 518   | 65.3%      |
| 2009 | 3,427,710  | 517   | 65.2%      |
| 2010 | 3,307,100  | 516   | 65.1%      |
| 2011 | 3,169,748  | 514   | 64.8%      |
| 2012 | 3,022,855  | 512   | 64.6%      |
| 2013 | 2,857,316  | 510   | 64.3%      |
| 2014 | 2,623,127  | 508   | 64.1%      |
| 2015 | 2,393,397  | 503   | 63.4%      |
| 2016 | 2,195,489  | 499   | 62.9%      |
| 2017 | 1,987,680  | 497   | 62.7%      |
| 2018 | 1,781,610  | 489   | 61.7%      |
| 2019 | 1,584,227  | 484   | 61.0%      |
| 2020 | 1,392,634  | 477   | 60.2%      |
| 2021 | 1,128,521  | 463   | 58.4%      |
| 2022 | 916,247    | 441   | 55.6%      |
| 2023 | 732,244    | 431   | 54.4%      |
